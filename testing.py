# -*- coding: utf-8 -*-
"""Test_pretrain.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1dWswYUoGPkJaSrs0iXfhyD2U0zvsRRt2
"""

# !pip install pytorch-lightning
# !pip install git+https://github.com/PytorchLightning/pytorch-lightning-bolts.git@master --upgrade
# !pip install lightning-bolts

# Commented out IPython magic to ensure Python compatibility.
## Standard libraries
import os
from copy import deepcopy

## Imports for plotting
import matplotlib.pyplot as plt
plt.set_cmap('cividis')
# %matplotlib inline
from IPython.display import set_matplotlib_formats
set_matplotlib_formats('svg', 'pdf') # For export
import matplotlib
matplotlib.rcParams['lines.linewidth'] = 2.0
import seaborn as sns
sns.set()

## tqdm for loading bars
# from tqdm.notebook import tqdm
from tqdm import tqdm

## PyTorch
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.utils.data as data
import torch.optim as optim

## Torchvision
import torchvision
from torchvision.datasets import STL10
from torchvision import transforms

# PyTorch Lightning
# try:
#     import pytorch_lightning as pl
# except ModuleNotFoundError: # Google Colab does not have PyTorch Lightning installed by default. Hence, we do it here if necessary
#     !pip install --quiet pytorch-lightning>=1.4
#     import pytorch_lightning as pl
import pytorch_lightning as pl
from pytorch_lightning.callbacks import LearningRateMonitor, ModelCheckpoint

from PIL import Image
import glob
import os

# Import tensorboard
# %load_ext tensorboard

# Path to the folder where the datasets are/should be downloaded (e.g. CIFAR10)
DATASET_PATH = "D:/Research/Dataset/UFI_multidisease/all_no_normal"
# Path to the folder where the pretrained models are saved
CHECKPOINT_PATH = "checkpoints"
# In this notebook, we use data loaders with heavier computational processing. It is recommended to use as many
# workers as possible in a data loader, which corresponds to the number of CPU cores
# NUM_WORKERS = os.cpu_count()
NUM_WORKERS = 0
# Setting the seed
pl.seed_everything(42)

# Ensure that all operations are deterministic on GPU (if used) for reproducibility
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False

device = torch.device("cuda:0") if torch.cuda.is_available() else torch.device("cpu")
print("Device:", device)
print("Number of workers:", NUM_WORKERS)

import os
import torch
import pandas as pd
from skimage import io, transform
import numpy as np
import matplotlib.pyplot as plt
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms, utils

# Ignore warnings
import warnings
warnings.filterwarnings("ignore")

from torchmetrics.classification import MultilabelAUROC
from torchmetrics.classification import MultilabelF1Score
from torchmetrics.classification import MultilabelPrecision
from torchmetrics.classification import MultilabelRecall
from torchmetrics.classification import MultilabelAccuracy
from torchmetrics.classification import MultilabelSpecificity
from torchmetrics.classification import MultilabelConfusionMatrix
from torchmetrics.classification import MultiClassAUROC
from torchmetrics.classification import MultiClassF1Score
from torchmetrics.classification import MultiClassPrecision
from torchmetrics.classification import MultiClassRecall
from torchmetrics.classification import MultiClassAccuracy
class SimCLR(pl.LightningModule):

    def __init__(self, hidden_dim, lr, temperature, weight_decay, max_epochs=1000):
        super().__init__()
        self.save_hyperparameters()
        assert self.hparams.temperature > 0.0, 'The temperature must be a positive float!'
        # Base model f(.)
        self.convnet = torchvision.models.resnet34(num_classes=4*hidden_dim)  # Output of last linear layer
        # The MLP for g(.) consists of Linear->ReLU->Linear
        self.convnet.fc = nn.Sequential(
            self.convnet.fc,  # Linear(ResNet output, 4*hidden_dim)
            nn.ReLU(inplace=True),
            nn.Linear(4*hidden_dim, hidden_dim)
        )


    def configure_optimizers(self):
        optimizer = optim.AdamW(self.parameters(),
                                lr=self.hparams.lr,
                                weight_decay=self.hparams.weight_decay)
        lr_scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer,
                                                            T_max=self.hparams.max_epochs,
                                                            eta_min=self.hparams.lr/50)
        return [optimizer], [lr_scheduler]

    def info_nce_loss(self, batch, mode='train'):
        imgs, _ = batch
        imgs = torch.cat(imgs, dim=0)

        # Encode all images
        feats = self.convnet(imgs)
        # Calculate cosine similarity
        cos_sim = F.cosine_similarity(feats[:,None,:], feats[None,:,:], dim=-1)
        # Mask out cosine similarity to itself
        self_mask = torch.eye(cos_sim.shape[0], dtype=torch.bool, device=cos_sim.device)
        cos_sim.masked_fill_(self_mask, -9e15)
        # Find positive example -> batch_size//2 away from the original example
        pos_mask = self_mask.roll(shifts=cos_sim.shape[0]//2, dims=0)
        # InfoNCE loss
        cos_sim = cos_sim / self.hparams.temperature
        nll = -cos_sim[pos_mask] + torch.logsumexp(cos_sim, dim=-1)
        nll = nll.mean()

        # Logging loss
        self.log(mode+'_loss', nll)
        # Get ranking position of positive example
        comb_sim = torch.cat([cos_sim[pos_mask][:,None],  # First position positive example
                              cos_sim.masked_fill(pos_mask, -9e15)],
                             dim=-1)
        sim_argsort = comb_sim.argsort(dim=-1, descending=True).argmin(dim=-1)
        # Logging ranking metrics
        self.log(mode+'_acc_top1', (sim_argsort == 0).float().mean(), prog_bar=True)
        self.log(mode+'_acc_top5', (sim_argsort < 5).float().mean(), prog_bar=True)
        self.log(mode+'_acc_mean_pos', 1+sim_argsort.float().mean(), prog_bar=True)

        return nll

    def training_step(self, batch, batch_idx):
        return self.info_nce_loss(batch, mode='train')

    def validation_step(self, batch, batch_idx):
        self.info_nce_loss(batch, mode='val')

class LogisticRegression(pl.LightningModule):

    def __init__(self, feature_dim, num_classes, lr, weight_decay, max_epochs=100):
        super().__init__()
        self.save_hyperparameters()
        # Mapping from representation h to classes
        # self.network = network
        ####################################################
        simclr = simclr_model
        self.network = deepcopy(simclr.convnet)
        self.network.fc = nn.Identity()  # Removing projection head g(.)
        self.network.eval()
        self.network.to(device)
        self.model = nn.Linear(512, 6)
        #######################################################
        # self.network = torchvision.models.resnet34(num_classes=6, pretrained=False)
        #####################barlow#############################
        # simclr = encoder
        # # self.network = deepcopy(simclr.convnet)
        # self.network = deepcopy(simclr)
        # # self.network.fc = nn.Identity()  # Removing projection head g(.)
        # self.network.eval()
        # self.network.to(device)
        # self.model = nn.Linear(512, 6)


    def configure_optimizers(self):
        optimizer = optim.AdamW(self.parameters(),
                                lr=self.hparams.lr,
                                weight_decay=self.hparams.weight_decay)
        lr_scheduler = optim.lr_scheduler.MultiStepLR(optimizer,
                                                      milestones=[int(self.hparams.max_epochs*0.6),
                                                                  int(self.hparams.max_epochs*0.8)],
                                                      gamma=0.1)
        return [optimizer], [lr_scheduler]

    def _calculate_loss(self, batch, mode='train'):
        # feats, labels = batch
        # preds = self.model(feats)
        # loss = F.cross_entropy(preds, labels)
        # acc = (preds.argmax(dim=-1) == labels).float().mean()
        #
        # self.log(mode + '_loss', loss)
        # self.log(mode + '_acc', acc)
        imgs, labels = batch

        # preds = self.network(imgs)

        features = self.network(imgs)
        preds = self.model(features)
        # preds = torch.sigmoid(preds)

        # preds = preds.squeeze()
        criterion = nn.BCEWithLogitsLoss()

        # loss = F.cross_entropy(preds, labels)
        loss = criterion(preds, labels.float())

        # acc = (preds.argmax(dim=-1) == labels).float().mean()
        acc = MultilabelAccuracy(num_labels=6).to(device)
        auc = MultilabelAUROC(num_labels=6, average="macro", thresholds=None).to(device)
        f1 = MultilabelF1Score(num_labels=6, average="macro").to(device)
        precision = MultilabelPrecision(num_labels=6, average="macro").to(device)
        recall = MultilabelRecall(num_labels=6, average="macro", threshold=0.3).to(device)

        acc = MultiClassAccuracy(num_classes=6).to(device)
        auc = MultiClassAUROC(num_classes=6, average="macro", thresholds=None).to(device)
        f1 = MultiClassF1Score(num_classes=6, average="macro").to(device)
        precision = MultiClassPrecision(num_labels=6, average="macro").to(device)
        recall = MultiClassRecall(num_labels=6, average="macro", threshold=0.3).to(device)
        # specificity = MultilabelSpecificity(num_labels=7).to(device)
        # confusion_matrix = MultiClassConfusionMatrix(num_labels=6).to(device)

        accuracy = acc(preds, labels)
        auc_score = auc(preds, labels)
        f1_score = f1(preds, labels)
        precision_score = precision(preds, labels)
        recall_score = recall(preds, labels)
        # specificity_score = specificity(preds, labels)
        # confusion_matrix_score = confusion_matrix(preds, labels)
        # tn = confusion_matrix_score[:, 0, 0]
        # tp = confusion_matrix_score[:, 1, 1]
        # fn = confusion_matrix_score[:, 1, 0]
        # fp = confusion_matrix_score[:, 0, 1]
        # specificity_score_matrix = tn / (tn + fp)
        # sensitivity_score_matrix = tp / (tp + fn)

        self.log(mode + '_acc', accuracy, prog_bar=True)
        self.log(mode + '_auc', auc_score, prog_bar=True)
        self.log(mode + '_f1', f1_score, prog_bar=True)
        self.log(mode + '_precision', precision_score, prog_bar=True)
        self.log(mode + '_recall', recall_score, prog_bar=True)
        # self.log(mode + '_specificity', specificity_score, prog_bar=True)
        self.log(mode + '_specificity_matrix', specificity_score_matrix.mean(), prog_bar=True)
        self.log(mode + '_sensitivity_matrix', sensitivity_score_matrix.mean(), prog_bar=True)

        self.log(mode + '_loss', loss, prog_bar=True)


        # if mode == 'val':
        #     print("accuracy ", accuracy)
        #     print("auc score ", auc_score)
        #     print("f1", f1_score)
        #     print("precision", precision_score)
            # print("recall", recall_score)
            # print("specificity_matrix", specificity_score_matrix.mean())
            # print("sensitivity_matrix", sensitivity_score_matrix.mean())

        if mode=='test':
            # auc_class = MultilabelAUROC(num_labels=6, average=None, thresholds=None).to(device)
            # auc_score_class = auc_class(preds, labels)
            # print("AUC score for each class: ", auc_score_class)

            acc_class =  MultilabelAccuracy(num_labels=6, average=None).to(device)
            acc_score_class = acc_class(preds, labels)
            print("Accuracy for each class: ", acc_score_class)


            f1_class = MultilabelF1Score(num_labels=6, average=None).to(device)
            f1_score_class = f1_class(preds, labels)
            print("F1 score for each class: ", f1_score_class)

            precision_class = MultilabelPrecision(num_labels=6, average=None).to(device)
            pre_score_class = precision_class(preds, labels)
            print("Precison for each class: ", pre_score_class)

            recall_class = MultilabelRecall(num_labels=6, average=None, threshold=0.2).to(device)
            recall_score_class = recall_class(preds, labels)
            print("AUC score for each class: ", recall_score_class)



        return loss

    def training_step(self, batch, batch_idx):
        return self._calculate_loss(batch, mode='train')

    def validation_step(self, batch, batch_idx):
        self._calculate_loss(batch, mode='val')

    def test_step(self, batch, batch_idx):
        self._calculate_loss(batch, mode='test')

import os
import pandas as pd
from torchvision.io import read_image
from torch.utils.data import Dataset

class CustomImageDataset(Dataset):
    def __init__(self, annotations_file, img_dir, transform=None, target_transform=None):
        self.img_labels = pd.read_csv(annotations_file)
        self.img_dir = img_dir
        self.transform = transform
        self.target_transform = target_transform
        self.label_arr = np.asarray(self.img_labels.iloc[:, 1:])

    def __len__(self):
        return len(self.img_labels)

    def __getitem__(self, idx):
        img_path = os.path.join(self.img_dir, self.img_labels.iloc[idx, 0])
        image = read_image(img_path+'.jpeg')
        # label = self.img_labels.iloc[idx, 1]
        label = self.label_arr[idx]
        if self.transform:
            image = self.transform(image)
        if self.target_transform:
            label = self.target_transform(label)
        # print(img_path,label)
        return image, label

# class ToFeature(object):
#     """Convert ndarrays in sample to Tensors."""
#     def __init__(self, model):
#         self.model = model
#
#
#     def __call__(self, image):
#         # Prepare model
#         network = deepcopy(self.model.convnet)
#         network.fc = nn.Identity()  # Removing projection head g(.)
#         network.eval()
#         network.to(device)
#
#         return network(image.unsqueeze(0).to(device))
#         # Encode all images
#         # data_loader = data.DataLoader(dataset, batch_size=64, num_workers=NUM_WORKERS, shuffle=False, drop_last=False)
#         # for batch_imgs, batch_labels in tqdm(data_loader):
#         #     # batch_imgs = batch_imgs.to(device)
#         #     batch_feats = network(batch_imgs)
#         # return batch_feats

simclr_model = SimCLR.load_from_checkpoint("models/epoch=1002-step=116348.ckpt")

train_transforms = transforms.Compose([transforms.ToPILImage(),
                                       transforms.RandomHorizontalFlip(),
                                       transforms.RandomVerticalFlip(),
                                       transforms.RandomRotation(180),
                                       transforms.Resize((512,512)),
                                       transforms.RandomGrayscale(p=0.2),
                                       transforms.GaussianBlur(kernel_size=9, sigma=(0.1, 0.5)),
                                       transforms.ToTensor(),
                                       transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                                            std=[0.229, 0.224, 0.225]),
                                       # ToFeature(simclr_model)
                                       # transforms.Normalize((0.5,), (0.5,))
                                       ])
img_transforms = transforms.Compose([transforms.ToTensor(),
                                     transforms.Normalize((0.5,), (0.5,))])
from torchvision.datasets.imagenet import ImageFolder
# dataset = CustomImageDataset(annotations_file="C:/Users/User/Fundus Dataset/UFI_multidisease/labels_nohead_no_normal.csv",
#                              img_dir="C:/Users/User/Fundus Dataset/UFI_multidisease/all_no_normal" ,transform=train_transforms)
data_path = 'C:/Users/User/Fundus Dataset/Public/EyePACS/'
dataset = CustomImageDataset(annotations_file=os.path.join(data_path, 'trainLabels.csv'),
                                  img_dir=os.path.join(data_path, 'train/eyepacs_preprocess'),
                                  transform=train_transforms)
train_img_aug_data, test_img_aug_data = torch.utils.data.random_split(dataset, [35000, 108])



# train_img_aug_data = ImageFolder("D:/Research/Dataset/UFI_multidisease/train", train_transforms)
# test_img_aug_data = ImageFolder("D:/Research/Dataset/UFI_multidisease/validate", train_transforms)
# @torch.no_grad()
# def prepare_data_features(model, dataset):
#     # Prepare model
#     network = deepcopy(model.convnet)
#     network.fc = nn.Identity()  # Removing projection head g(.)
#     network.eval()
#     network.to(device)
#
#     # Encode all images
#     data_loader = data.DataLoader(dataset, batch_size=64, num_workers=NUM_WORKERS, shuffle=False, drop_last=False)
#     feats, labels = [], []
#     for batch_imgs, batch_labels in tqdm(data_loader):
#         batch_imgs = batch_imgs.to(device)
#         batch_feats = network(batch_imgs)
#         feats.append(batch_feats.detach().cpu())
#         labels.append(batch_labels)
#
#     feats = torch.cat(feats, dim=0)
#     labels = torch.cat(labels, dim=0)
#
#     # Sort images by labels
#     labels, idxs = labels.sort()
#     feats = feats[idxs]
#     # print(labels)
#     return data.TensorDataset(feats, labels)

# simclr_model = SimCLR.load_from_checkpoint("models/epoch=83-step=1092.ckpt")

# network = deepcopy(simclr_model.convnet)
# network.fc = nn.Identity()  # Removing projection head g(.)
# network.eval()
# network.to(device)
# train_feats_simclr = prepare_data_features(simclr_model, train_img_aug_data)
# test_feats_simclr = prepare_data_features(simclr_model, test_img_aug_data)
# torch.save(train_feats_simclr, 'train_feats_simclr.pt')
# torch.save(test_feats_simclr, 'test_feats_simclr.pt')
# train_feats_simclr = torch.load('train_feats_simclr.pt')
# test_feats_simclr = torch.load('test_feats_simclr.pt')

#
# class BarlowTwinsLoss(nn.Module):
#     def __init__(self, batch_size, lambda_coeff=5e-3, z_dim=128):
#         super().__init__()
#
#         self.z_dim = z_dim
#         self.batch_size = batch_size
#         self.lambda_coeff = lambda_coeff
#
#     def off_diagonal_ele(self, x):
#         # taken from: https://github.com/facebookresearch/barlowtwins/blob/main/main.py
#         # return a flattened view of the off-diagonal elements of a square matrix
#         n, m = x.shape
#         assert n == m
#         return x.flatten()[:-1].view(n - 1, n + 1)[:, 1:].flatten()
#
#     def forward(self, z1, z2):
#         # N x D, where N is the batch size and D is output dim of projection head
#         z1_norm = (z1 - torch.mean(z1, dim=0)) / torch.std(z1, dim=0)
#         z2_norm = (z2 - torch.mean(z2, dim=0)) / torch.std(z2, dim=0)
#
#         cross_corr = torch.matmul(z1_norm.T, z2_norm) / self.batch_size
#
#         on_diag = torch.diagonal(cross_corr).add_(-1).pow_(2).sum()
#         off_diag = self.off_diagonal_ele(cross_corr).pow_(2).sum()
#
#         return on_diag + self.lambda_coeff * off_diag
#
# encoder = torchvision.models.resnet34(pretrained=False)
#
# # for CIFAR10, replace the first 7x7 conv with smaller 3x3 conv and remove the first maxpool
# encoder.conv1 = nn.Conv2d(3, 64, kernel_size=3, stride=1, padding=1, bias=False)
# encoder.maxpool = nn.MaxPool2d(kernel_size=1, stride=1)
#
# # replace classification fc layer of Resnet to obtain representations from the backbone
# encoder.fc = nn.Identity()
#
# class ProjectionHead(nn.Module):
#     def __init__(self, input_dim=2048, hidden_dim=2048, output_dim=128):
#         super().__init__()
#
#         self.projection_head = nn.Sequential(
#             nn.Linear(input_dim, hidden_dim, bias=True),
#             nn.BatchNorm1d(hidden_dim),
#             nn.ReLU(),
#             nn.Linear(hidden_dim, output_dim, bias=False),
#         )
#
#     def forward(self, x):
#         return self.projection_head(x)
#
# def fn(warmup_steps, step):
#     if step < warmup_steps:
#         return float(step) / float(max(1, warmup_steps))
#     else:
#         return 1.0
#
# from functools import partial
# def linear_warmup_decay(warmup_steps):
#     return partial(fn, warmup_steps)
#
# class BarlowTwins(pl.LightningModule):
#     def __init__(
#         self,
#         encoder,
#         encoder_out_dim,
#         num_training_samples,
#         batch_size,
#         lambda_coeff=5e-3,
#         z_dim=128,
#         learning_rate=1e-4,
#         warmup_epochs=10,
#         max_epochs=200,
#     ):
#         super().__init__()
#
#         self.encoder = encoder
#         self.projection_head = ProjectionHead(input_dim=encoder_out_dim, hidden_dim=encoder_out_dim, output_dim=z_dim)
#         self.loss_fn = BarlowTwinsLoss(batch_size=batch_size, lambda_coeff=lambda_coeff, z_dim=z_dim)
#
#         self.learning_rate = learning_rate
#         self.warmup_epochs = warmup_epochs
#         self.max_epochs = max_epochs
#
#         self.train_iters_per_epoch = num_training_samples // batch_size
#
#     def forward(self, x):
#         return self.encoder(x)
#
#     def shared_step(self, batch):
#         (x1, x2, _), _ = batch
#
#         z1 = self.projection_head(self.encoder(x1))
#         z2 = self.projection_head(self.encoder(x2))
#
#         return self.loss_fn(z1, z2)
#
#     def training_step(self, batch, batch_idx):
#         loss = self.shared_step(batch)
#         self.log("train_loss", loss, on_step=True, on_epoch=False)
#         return loss
#
#     def validation_step(self, batch, batch_idx):
#         loss = self.shared_step(batch)
#         self.log("val_loss", loss, on_step=False, on_epoch=True)
#
#     def configure_optimizers(self):
#         optimizer = torch.optim.Adam(self.parameters(), lr=self.learning_rate)
#
#         warmup_steps = self.train_iters_per_epoch * self.warmup_epochs
#
#         scheduler = {
#             "scheduler": torch.optim.lr_scheduler.LambdaLR(
#                 optimizer,
#                 linear_warmup_decay(warmup_steps),
#             ),
#             "interval": "step",
#             "frequency": 1,
#         }
#
#         return [optimizer], [scheduler]
#
# encoder_out_dim = 512
# batch_size = 64
# num_workers = 32  # to run notebook on CPU
# max_epochs = 2000
# z_dim = 128
# DATASET_TRAIN = "C:/Users/User/Fundus Dataset/UFI-all/"
# DATASET_TEST = "C:/Users/User/Fundus Dataset/UFI-all/"
# def cifar10_normalization():
#     normalize = transforms.Normalize(
#         mean=[x / 255.0 for x in [125.3, 123.0, 113.9]], std=[x / 255.0 for x in [63.0, 62.1, 66.7]]
#     )
#     return normalize
#
# class BarlowTwinsTransform:
#     def __init__(self, train=True, input_height=112, gaussian_blur=True, jitter_strength=1.0, normalize=None):
#         self.input_height = input_height
#         self.gaussian_blur = gaussian_blur
#         self.jitter_strength = jitter_strength
#         self.normalize = normalize
#         self.train = train
#
#         color_jitter = transforms.ColorJitter(
#             0.8 * self.jitter_strength,
#             0.8 * self.jitter_strength,
#             0.8 * self.jitter_strength,
#             0.2 * self.jitter_strength,
#         )
#
#         color_transform = [transforms.RandomApply([color_jitter], p=0.8), transforms.RandomGrayscale(p=0.2)]
#
#         if self.gaussian_blur:
#             kernel_size = int(0.1 * self.input_height)
#             if kernel_size % 2 == 0:
#                 kernel_size += 1
#
#             color_transform.append(transforms.RandomApply([transforms.GaussianBlur(kernel_size=kernel_size)], p=0.5))
#
#         self.color_transform = transforms.Compose(color_transform)
#
#         if normalize is None:
#             self.final_transform = transforms.ToTensor()
#         else:
#             self.final_transform = transforms.Compose([transforms.ToTensor(), normalize])
#
#         self.transform = transforms.Compose(
#             [
#                 transforms.RandomResizedCrop(self.input_height),
#                 transforms.RandomHorizontalFlip(p=0.5),
#                 self.color_transform,
#                 self.final_transform,
#             ]
#         )
#
#         self.finetune_transform = None
#         if self.train:
#             self.finetune_transform = transforms.Compose(
#                 [
#                     transforms.RandomCrop(32, padding=4, padding_mode="reflect"),
#                     transforms.RandomHorizontalFlip(),
#                     transforms.ToTensor(),
#                 ]
#             )
#         else:
#             self.finetune_transform = transforms.ToTensor()
#
#     def __call__(self, sample):
#         return self.transform(sample), self.transform(sample), self.finetune_transform(sample)
#
#
# train_transform = BarlowTwinsTransform(
#     train=True, input_height=112, gaussian_blur=False, jitter_strength=0.5, normalize=cifar10_normalization()
# )
# # train_dataset = CIFAR10(root=".", train=True, download=True, transform=train_transform)
# train_dataset =  torchvision.datasets.ImageFolder(root=DATASET_TRAIN, transform=train_transform)
#
# val_transform = BarlowTwinsTransform(
#     train=False, input_height=112, gaussian_blur=False, jitter_strength=0.5, normalize=cifar10_normalization()
# )
# val_dataset = torchvision.datasets.ImageFolder(root=DATASET_TEST, transform=train_transform)
#
# train_loader = data.DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=num_workers, drop_last=True)
# val_loader = data.DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=num_workers, drop_last=True)
#
# model = BarlowTwins(
#     encoder=encoder,
#     encoder_out_dim=encoder_out_dim,
#     num_training_samples=14946,
#     batch_size=batch_size,
#     z_dim=z_dim,
# )
#
# # online_finetuner = OnlineFineTuner(encoder_output_dim=encoder_out_dim, num_classes=10)
# checkpoint_callback = ModelCheckpoint(every_n_epochs=100, save_top_k=-1, save_last=True)
#
# batch_size =16
# num_workers = 32  # to run notebook on CPU
# max_epochs = 2000
# z_dim = 128
#
# ckpt_model = torch.load('models/epoch=1699-step=197200.ckpt')
# # print(list(iter(ckpt_model)))# print(ckpt_model)# upload checkpoint to aws
# model.load_state_dict(ckpt_model['state_dict'])
# encoder = model.encoder
#
# class BarlowTwinsTransform:
#     def __init__(self, train=True, input_height=112, gaussian_blur=True, jitter_strength=1.0, normalize=None):
#         self.input_height = input_height
#         self.gaussian_blur = gaussian_blur
#         self.jitter_strength = jitter_strength
#         self.normalize = normalize
#         self.train = train
#
#         color_jitter = transforms.ColorJitter(
#             0.8 * self.jitter_strength,
#             0.8 * self.jitter_strength,
#             0.8 * self.jitter_strength,
#             0.2 * self.jitter_strength,
#         )
#
#         color_transform = [transforms.RandomApply([color_jitter], p=0.8), transforms.RandomGrayscale(p=0.2)]
#
#         if self.gaussian_blur:
#             kernel_size = int(0.1 * self.input_height)
#             if kernel_size % 2 == 0:
#                 kernel_size += 1
#
#             color_transform.append(transforms.RandomApply([transforms.GaussianBlur(kernel_size=kernel_size)], p=0.5))
#
#         self.color_transform = transforms.Compose(color_transform)
#
#         if normalize is None:
#             self.final_transform = transforms.ToTensor()
#         else:
#             self.final_transform = transforms.Compose([transforms.ToTensor(), normalize])
#
#         self.transform = transforms.Compose(
#             [
#                 transforms.RandomResizedCrop(self.input_height),
#                 transforms.RandomHorizontalFlip(p=0.5),
#                 self.color_transform,
#                 self.final_transform,
#             ]
#         )
#
#         self.finetune_transform = None
#         if self.train:
#             self.finetune_transform = transforms.Compose(
#                 [
#                     transforms.RandomCrop(32, padding=4, padding_mode="reflect"),
#                     transforms.RandomHorizontalFlip(),
#                     transforms.ToTensor(),
#                 ]
#             )
#         else:
#             self.finetune_transform = transforms.ToTensor()
#
#     def __call__(self, sample):
#         return self.transform(sample), self.transform(sample), self.finetune_transform(sample)
#
#
# def cifar10_normalization():
#     normalize = transforms.Normalize(
#         mean=[x / 255.0 for x in [125.3, 123.0, 113.9]], std=[x / 255.0 for x in [63.0, 62.1, 66.7]]
#     )
#     return normalize
#
#
# train_transform = BarlowTwinsTransform(
#     train=True, input_height=224, gaussian_blur=False, jitter_strength=0.5, normalize=cifar10_normalization()
# )
# # train_dataset = CIFAR10(root=".", train=True, download=True, transform=train_transform)
# train_dataset =  torchvision.datasets.ImageFolder(root=DATASET_TRAIN, transform=train_transform)
#
# val_transform = BarlowTwinsTransform(
#     train=False, input_height=224, gaussian_blur=False, jitter_strength=0.5, normalize=cifar10_normalization()
# )
# val_dataset = torchvision.datasets.ImageFolder(root=DATASET_TEST, transform=train_transform)
#
# train_loader = data.DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=num_workers, drop_last=True)
# val_loader = data.DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=num_workers, drop_last=True)
#
# class BarlowTwinsLoss(nn.Module):
#     def __init__(self, batch_size, lambda_coeff=5e-3, z_dim=128):
#         super().__init__()
#
#         self.z_dim = z_dim
#         self.batch_size = batch_size
#         self.lambda_coeff = lambda_coeff
#
#     def off_diagonal_ele(self, x):
#         # taken from: https://github.com/facebookresearch/barlowtwins/blob/main/main.py
#         # return a flattened view of the off-diagonal elements of a square matrix
#         n, m = x.shape
#         assert n == m
#         return x.flatten()[:-1].view(n - 1, n + 1)[:, 1:].flatten()
#
#     def forward(self, z1, z2):
#         # N x D, where N is the batch size and D is output dim of projection head
#         z1_norm = (z1 - torch.mean(z1, dim=0)) / torch.std(z1, dim=0)
#         z2_norm = (z2 - torch.mean(z2, dim=0)) / torch.std(z2, dim=0)
#
#         cross_corr = torch.matmul(z1_norm.T, z2_norm) / self.batch_size
#
#         on_diag = torch.diagonal(cross_corr).add_(-1).pow_(2).sum()
#         off_diag = self.off_diagonal_ele(cross_corr).pow_(2).sum()
#
#         return on_diag + self.lambda_coeff * off_diag



def train_logreg(batch_size, train_feats_data, test_feats_data, max_epochs=100, **kwargs):
    trainer = pl.Trainer(default_root_dir=os.path.join(CHECKPOINT_PATH, "dt_eyep"),
                         accelerator="gpu" if str(device).startswith("cuda") else "cpu",
                         devices=1,
                         max_epochs=max_epochs,
                         callbacks=[ModelCheckpoint(save_weights_only=True, mode='max', monitor='val_auc'),
                                    LearningRateMonitor("epoch")],
                         enable_progress_bar=True,
                         check_val_every_n_epoch=2)
    trainer.logger._default_hp_metric = None

    # Data loaders
    train_loader = data.DataLoader(train_feats_data, batch_size=batch_size, shuffle=True,
                                   drop_last=False, pin_memory=False, num_workers=0)
    test_loader = data.DataLoader(test_feats_data, batch_size=batch_size, shuffle=False,
                                  drop_last=False, pin_memory=False, num_workers=0)

    # Check whether pretrained model exists. If yes, load it and skip training
    pretrained_filename = os.path.join(CHECKPOINT_PATH, "ResNet.ckpt")
    if os.path.isfile(pretrained_filename):
        print(f"Found pretrained model at {pretrained_filename}, loading...")
        model = LogisticRegression.load_from_checkpoint(pretrained_filename)
    else:
        pl.seed_everything(42)  # To be reproducable
        # model = LogisticRegression(**kwargs)
        # trainer.fit(model, train_loader, test_loader)
        # model = LogisticRegression.load_from_checkpoint(trainer.checkpoint_callback.best_model_path)
        model = LogisticRegression.load_from_checkpoint("checkpoints/dt_simclr_m4/lightning_logs/version_0/checkpoints/epoch=89-step=4140-v2.ckpt")
        model.model = nn.Linear(512,1)



    # Test best model on train and validation set
    # train_result = trainer.test(model, test_loader, verbose=False)
    test_result = trainer.test(model, test_loader, verbose=False)
    # result = {"train": train_result[0]["test_auc"], "test": test_result[0]["test_auc"]}
    result = {"test": test_result[0]["test_auc"]}
    metrics_results = {"acc": test_result[0]["test_acc"],
                       "f1": test_result[0]["test_f1"],
                       "precision": test_result[0]["test_precision"],
                       "recall": test_result[0]["test_recall"],
                       "sensitivity_matrix": test_result[0]["test_sensitivity_matrix"],
                       "specificity_matrix": test_result[0]["test_specificity_matrix"]
                       }


    return model, result, metrics_results


sim_model, sim_result, metrics = train_logreg(batch_size=64,
                                     train_feats_data=train_img_aug_data,
                                     test_feats_data=test_img_aug_data,
                                     feature_dim=512,
                                     num_classes=6,
                                     lr=1e-3,
                                     weight_decay=1e-3)
# print(f"AUC on training set: {100*sim_result['train']:4.2f}%")
print(f"AUC on test set: {100*sim_result['test']:4.2f}%")

print(f"Acc on test set: {100*metrics['acc']:4.2f}%")
print(f"F1 on test set: {100*metrics['f1']:4.2f}%")
print(f"Precision on test set: {100*metrics['precision']:4.2f}%")
print(f"Recall on test set: {100*metrics['recall']:4.2f}%")

print(f"Specificity matrix on test set: {100*metrics['specificity_matrix']:4.2f}%")
print(f"Sensitivity matrix on test set: {100*metrics['sensitivity_matrix']:4.2f}%")

# def get_smaller_dataset(original_dataset, num_imgs_per_label):
#     new_dataset = data.TensorDataset(
#         *[t.unflatten(0, (7, -1))[:,:num_imgs_per_label].flatten(0, 1) for t in original_dataset.tensors]
#     )
#     return new_dataset
#
# results = {}
# for num_imgs_per_label in [10, 20, 50, 100, 200, 500]:
#     sub_train_set = get_smaller_dataset(train_feats_simclr, num_imgs_per_label)
#     _, small_set_results = train_logreg(batch_size=64,
#                                         train_feats_data=sub_train_set,
#                                         test_feats_data=test_feats_simclr,
#                                         model_suffix=num_imgs_per_label,
#                                         feature_dim=train_feats_simclr.tensors[0].shape[1],
#                                         num_classes=10,
#                                         lr=1e-3,
#                                         weight_decay=1e-3)
#     results[num_imgs_per_label] = small_set_results
#
# dataset_sizes = sorted([k for k in results])
# test_scores = [results[k]["test"] for k in dataset_sizes]
#
# fig = plt.figure(figsize=(6,4))
# plt.plot(dataset_sizes, test_scores, '--', color="#000", marker="*", markeredgecolor="#000", markerfacecolor="y", markersize=16)
# plt.xscale("log")
# plt.xticks(dataset_sizes, labels=dataset_sizes)
# plt.title("STL10 classification over dataset size", fontsize=14)
# plt.xlabel("Number of images per class")
# plt.ylabel("Test accuracy")
# plt.minorticks_off()
# plt.show()
#
# for k, score in zip(dataset_sizes, test_scores):
#     print(f'Test accuracy for {k:3d} images per label: {100*score:4.2f}%')

