from __future__ import print_function
import argparse
import torch
import torch.nn as nn
import torch.utils.data
from torchvision import datasets, transforms
from torch.autograd import Variable
import torch.optim as optim
import torchvision.utils as vutils
import torchvision.models as models

from nets.classifiers import _netD_cifar10,_netG_cifar10
from constants import *
from utils.utils import accu,TestAcc_dataloader, TestAcc_tensor, TestAdvAcc_dataloader
import models.model_train as model_train
from dataProcess.read_data import read_CIFAR10
import glob
import copy
from vae import *
#torch.manual_seed(31415926)
#torch.cuda.manual_seed(31415926)
batch_size = 64
test_batch_size = 128
train_data , valid_data, test_data = read_CIFAR10(batch_size, test_batch_size, 0.2)
attack_method = model_train.advexam_gradient
h_dim = 100



def acquireInputGradient(netD, dataset1, dataset2, loss_func):
	netD.eval()
	res1 = 0.0
	res1_error = 0.0
	num1 = 0
	for i, data_batch in enumerate(dataset1):
		feature, label = data_batch
		#gaussnoise = torch.zeros(feature.size()).cuda()
		#gaussnoise.normal_()
		#feature = feature + 0.02* gaussnoise
		#netD_cp = copy.deepcopy(netD)
		perturb = torch.zeros(feature.size()).cuda()
		feature, label = Variable(feature.cuda()), Variable(label.cuda())
		perturb = Variable(perturb, requires_grad = True)
		feature_adv = feature + perturb
		outputs = netD(feature_adv)
		_, pred = torch.max(outputs, 1)
		error = loss_func(outputs, label)

		error.backward()
		res_temp = 0.0
		for j,image in enumerate(feature):
			if pred.data[j]==label.data[j]:
				res_temp  += torch.sum(torch.abs(perturb.grad[j].data))
		res1 += res_temp/feature.size()[0]
		res1_error += error.data[0]
		num1 +=1
	res2 = 0.0
	res2_error = 0.0
	num2 = 0
	for i, data_batch in enumerate(dataset2):
		feature, label = data_batch
		#gaussnoise = torch.zeros(feature.size()).cuda()
		#gaussnoise.normal_()
		#feature = feature + 0.02* gaussnoise
		#netD_cp = copy.deepcopy(netD)
		perturb = torch.zeros(feature.size()).cuda()
		feature, label = Variable(feature.cuda()), Variable(label.cuda())
		perturb = Variable(perturb, requires_grad = True)
		feature_adv = feature + perturb
		outputs = netD(feature_adv)
		_, pred = torch.max(outputs, 1)
		error = loss_func(outputs, label)

		error.backward()
		res_temp = 0.0
		for j,image in enumerate(feature):
			if pred.data[j]==label.data[j]:
				res_temp  += torch.sum(torch.abs(perturb.grad[j].data))
		res2 += res_temp/feature.size()[0]
		res2_error += error.data[0]
		num2 +=1
	print("%3.5f \t %3.5f \t %3.5f \t %3.5f" %(res1/num1, res1_error/num1, res2/num2, res2_error/num2))
	return

model = VAE()
model.cuda()
epoch_num=400
for epoch in range(1, epoch_num + 1):
	train(epoch)
	test(epoch)
	if epoch%10==1:
		sample = Variable(torch.randn(batch_size, h_dim))
		sample = sample.cuda()
		sample = model.decode(sample).cpu()
		save_image(sample.data,
			'Vae_results/sample_' + str(epoch) + '.png',normalize = True)

model.eval()

netD = _netD_cifar10()
netD.cuda()
loss_func = nn.CrossEntropyLoss()
optimizerD = optim.SGD(netD.parameters(), lr=0.01, weight_decay = 0.0002)
epoch_num = 70


def max_loss(output):
	val,label = torch.max(output,1)
	return loss_func(output,label)

sample = Variable(torch.randn(batch_size, h_dim)).cuda()
for epoch in range(epoch_num):
	running_loss_D = .0
	running_acc_D = .0
	running_loss_reg = .0
	for i, data_batch in enumerate(train_data):
		netD.train()

		netD.zero_grad()
		feature,label = data_batch
		feature = feature.cuda()
		label = label.cuda()

		sample.data.normal_()
		sample = model.decode(sample)
		feature_vae = sample.data


		netD_cp = copy.deepcopy(netD)
		feature_vae_adv = model_train.maxlogit_attack(netD_cp, feature_vae, 'sign', 0.001, 7, 0.005)
		
		feature_vae_adv, label = Variable(feature_vae_adv), Variable(label.cuda())	
		feature, feature_vae = Variable(feature), Variable(feature_vae)

		outputs_vae_adv = netD(feature_vae_adv.detach())
		error_vae_adv = max_loss(outputs_vae_adv)

		outputs= netD(feature)
		error = loss_func(outputs, label)

		outputs_vae= netD(feature_vae)
		error_vae = max_loss(outputs_vae)

		error_tr = error_vae_adv - error_vae + error
		error_tr.backward()
		optimizerD.step()

		running_loss_D += error
		running_loss_reg += error_vae_adv - error_vae
		running_acc_D += accu(outputs, label)/batch_size

		if i%100==99:
			print('[%d/%d][%d/%d] Adv perf: %.4f / %.4f / %.4f'
				% (epoch, epoch_num, i, len(train_data),
					running_loss_reg.data.cpu().numpy()[0]/100, running_loss_D.data.cpu().numpy()[0]/100, running_acc_D/100))
			running_loss_D = .0
			running_acc_D = .0
			running_loss_reg = .0
		#if epoch%5==2 and i%500==0:
			#vutils.save_image(feature_gau_adv.data, './adv_image/adv_image_epoch_%03d_%03d_perb.png' %(epoch,i), normalize = True)
			#vutils.save_image(feature.data, './adv_image/adv_image_epoch_%03d_%03d_orig.png' %(epoch,i), normalize = True)
	if epoch in {20,35,50, 65}:
		optimizerD.param_groups[0]['lr'] /= 2.0
				#coef_FGSM *= 1.5
	if epoch % 5 == 0:
		#dataset_adv = torch.load('./adv_exam/adv_gradient_FGSM_step1.pt')
		train_acc, train_loss = TestAcc_dataloader(netD, train_data,loss_func)
		valid_acc, valid_loss = TestAcc_dataloader(netD, valid_data,loss_func)
		test_acc, test_loss = TestAcc_dataloader(netD, test_data,loss_func)
		#test_adv_acc = TestAcc_tensor(netD, dataset_adv)
		print('[%d/%d]Clean  accuracy: %.3f \t %.3f \t %.3f' %(epoch, epoch_num, train_acc, valid_acc, test_acc) )
		
		acc_tr, loss_tr = TestAdvAcc_dataloader(netD, train_data, 'sign', coef_FGSM, attack_method,loss_func, 1, coef_FGSM)
		acc_valid, loss_valid = TestAdvAcc_dataloader(netD, valid_data, 'sign', coef_FGSM, attack_method,loss_func, 1, coef_FGSM)
		acc_t, loss_t = TestAdvAcc_dataloader(netD, test_data, 'sign', coef_FGSM, attack_method,loss_func, 1, coef_FGSM)
		print('[%d/%d]Attack accuracy: %.3f \t %.3f \t %.3f' %(epoch, epoch_num,acc_tr, acc_valid, acc_t))
		
		#acquireInputGradient(netD, valid_data, test_data, loss_func)
		print("Train Loss: %3.5f;Valid Loss: %3.5f; Test Loss: %3.5f" %(train_loss, valid_loss, test_loss))
		print("Train Loss: %3.5f;Valid Loss: %3.5f; Test Loss: %3.5f" %(loss_tr, loss_valid, loss_t))
		print("===="*5)
		
torch.save(netD.state_dict(), './netD_vae_adv.pkl')


