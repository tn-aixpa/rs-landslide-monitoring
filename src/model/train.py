import argparse
import collections
import torch
import numpy as np
from data_loader.data_loaders import InSARDataLoader
from loss import mse
import metric as module_metric
from utae import UTAE
from parse_config import ConfigParser
from trainer import Trainer
from utils import prepare_device
import os
import warnings
import digitalhub as dh
from digitalhub_runtime_python import handler
warnings.filterwarnings("ignore")


# fix random seeds for reproducibility
SEED = 123 
torch.manual_seed(SEED)
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False
np.random.seed(SEED)

os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'

@handler()
def main(proj_name,batch_size=128,in_channels=3,learning_rate=0.0001,weight_decay= 0.01,n_epochs=100,
         save_dir="model-checkpoint/", save_period=1, verbosity=2, early_stop=10):
    maindir = "."
    data_folder = "data"
    output_folder = save_dir
    input_folder = "input"
    out_conv=[32,in_channels]

    data_path = os.path.join(maindir, data_folder, input_folder)
    result_path = os.path.join(maindir, data_folder, output_folder)
    dataset_folder = os.path.join(data_path,"Dataset")
    for f in (dataset_folder,result_path):
        os.makedirs(f,exist_ok=True)

    proj = dh.get_or_create_project(proj_name)
    dataset_artifact = proj.get_artifact("Dataset")
    dataset_path = dataset_artifact.download(dataset_folder,overwrite=True)

    # setup data_loader instances
    data_loader = InSARDataLoader(os.path.join(dataset_path,"training"),batch_size=batch_size,
                                  shuffle=True, num_workers=8,augmentations=True,drop_last=True)
    valid_data_loader = InSARDataLoader(os.path.join(dataset_path,"val"),batch_size=batch_size,
                                  shuffle=True, num_workers=8,augmentations=False,drop_last=True)

    # build model architecture, then print to console
    model = UTAE(in_channels=in_channels,out_conv=out_conv)

    # prepare for (multi-device) GPU training
    device, device_ids = prepare_device(1)
    model = model.to(device)
    if len(device_ids) > 1:
        model = torch.nn.DataParallel(model, device_ids=device_ids)



    # get function handles of loss and metrics
    criterion = torch.nn.MSELoss()
    metrics = [torch.nn.MSELoss()]

    # build optimizer, learning rate scheduler. delete every lines containing lr_scheduler for disabling scheduler
    trainable_params = filter(lambda p: p.requires_grad, model.parameters())
    optimizer = torch.optim.Adam(trainable_params,lr=learning_rate,weight_decay=weight_decay,amsgrad=True)
    lr_scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(optimizer,T_0=20,eta_min=1e-6)
    len_epoch = n_epochs
    #freeze = config['trainer'].get('freeze', False)
    config = {
        "proj_name":proj_name,
        "epochs":len_epoch,
        "save_dir":result_path,
        "save_period":save_period,
        "verbosity":verbosity,
        "monitor": "off",
        "early_stop": early_stop,
        "tensorboard": False
    }

    trainer = Trainer(model, criterion, metrics, optimizer,
                      config=config,
                      device=device,
                      data_loader=data_loader,
                      valid_data_loader=valid_data_loader,
                      lr_scheduler=lr_scheduler,
                      len_epoch=len_epoch)

    trainer.train()


# if __name__ == '__main__':
#     args = argparse.ArgumentParser(description='PyTorch Template')
#     args.add_argument('-c', '--config', default=None, type=str,
#                       help='config file path (default: None)')
#     args.add_argument('-r', '--resume', default=None, type=str,
#                       help='path to latest checkpoint (default: None)')
#     args.add_argument('-d', '--device', default=None, type=str,
#                       help='indices of GPUs to enable (default: all)')

#     # custom cli options to modify configuration from default values given in json file.
#     CustomArgs = collections.namedtuple('CustomArgs', 'flags type target')
#     options = [
#         CustomArgs(['--lr', '--learning_rate'],
#                    type=float, target='optimizer;args;lr'),
#         CustomArgs(['--bs', '--batch_size'], type=int,
#                    target='data_loader;args;batch_size')
#     ]
#     config = ConfigParser.from_args(args, options)
#     main(config)
