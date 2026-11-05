#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Dec  1 17:53:21 2023

@author: lbergamasco
"""
import argparse
from parse_config import ConfigParser
import os
import torch
import data_loader.data_loaders as module_data
import loss as module_loss
import metric as module_metric
import utae as module_arch
import numpy as np
import matplotlib.pyplot as plt
from sklearn.metrics import confusion_matrix, precision_score, recall_score, f1_score
import tifffile as tiff
from scipy.io import savemat
import digitalhub as dh
import glob
import json

def main(config_or_dir):
    if isinstance(config_or_dir, str) and os.path.isdir(config_or_dir):
        root_dir = config_or_dir
        for subdir in sorted(os.listdir(root_dir)):
            exp_path = os.path.join(root_dir, subdir)
            if not os.path.isdir(exp_path):
                continue
            # Search for the json and checkpoint in the subfolder
            config_path = glob.glob(os.path.join(exp_path, '*.json'))[0]
            checkpoint_path = glob.glob(os.path.join(exp_path, '*.pth'))[0]
            # load the config
            with open(config_path, 'r') as f:
                config_dict = json.load(f)
            config = ConfigParser(config_dict)
            config.resume = checkpoint_path
            print(f"Test the model in {exp_path}")
            main(config)  # Call main normally for this model
        return  # Exit after doing everything

    config = config_or_dir
    proj_name = config["proj_name"]

    maindir = "."
    data_folder = "data"
    output_folder = "output"
    input_folder = "input"

    data_path = os.path.join(maindir, data_folder, input_folder)
    result_path = os.path.join(maindir, data_folder, output_folder)
    dataset_folder = os.path.join(data_path,"dataset")
    feature_folder = os.path.join(data_path, "features")
    rainfall_map_folder = os.path.join(data_path, "rainfall_map")

    for folder in (data_path, result_path, dataset_folder, feature_folder, rainfall_map_folder):
        os.makedirs(folder, exist_ok=True)

    proj = dh.get_or_create_project(proj_name)
    dataset_artifact = proj.get_artifact("Dataset")
    dataset_path = dataset_artifact.download(dataset_folder, overwrite=True)
    feature_artifact = proj.get_artifact("03_features")
    feature_path = feature_artifact.download(feature_folder, overwrite=True)
    rainfal_map_artifact = proj.get_artifact("04_rainfall")
    rainfall_map_path = rainfal_map_artifact.download(rainfall_map_folder, overwrite=True)

    logger = config.get_logger('test')
    
    #recover in_channels
    in_channels = config['arch']['args']['in_channels']

    # build model architecture
    model = config.init_obj('arch', module_arch)
    logger.info(model)

    # get function handles of loss and metrics
    loss_fn = config.init_obj('loss', module_loss)
    metric_fns = [getattr(module_metric, met) for met in config['metrics']]

    logger.info('Loading checkpoint: {} ...'.format(config.resume))

    # loading on CPU-only machine
    checkpoint = proj.get_model("AD-model")
    checkpoint = torch.load(config.resume, map_location=torch.device('cpu'), weights_only=False)
    state_dict = checkpoint['state_dict']
    if config['n_gpu'] > 1:
        model = torch.nn.DataParallel(model)
    model.load_state_dict(state_dict)

    # prepare model for testing
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = model.to(device)
    model.eval()

    if config.comp_thresh:
        data_loader = config.init_obj('data_loader', module_data)
        predictions = []

        for im, _ in data_loader:
            im = im.to(non_blocking=True, device=device)
            with torch.no_grad():
                output = model(im)#.encoder_q(im_1,im_2)
                output = output.cpu().numpy()
                predictions.append(output)
        predictions = np.concatenate(predictions,axis=0)
        th = np.mean(predictions,axis=0)+np.std(predictions,axis=0)
        print('Threshold for normal data: {}'.format(th))
        #save on json file
        threshold_path = os.path.join(result_path, "threshold.json")
        thresh_dict = {"threshold":th}
        with open(threshold_path, "w") as f:
            json.dump(thresh_dict, f)
        proj.log_artifact(name=proj_name, kind="artifact", source=threshold_path)
    elif not config.comp_thresh and config.thresh_dir is not None:
        threshold_artifact = proj.get_artifact("threshdold")
        threshold_path = threshold_artifact.download(data_path,overwrite=True)
        with open(threshold_path, "r") as f:
            thresh_dict = json.load(f)
        th = thresh_dict["threshold"]

    

if __name__ == '__main__':
    args = argparse.ArgumentParser(description='PyTorch Template')
    args.add_argument('-c', '--config', default=None, type=str,
                      help='config file path (default: None)')
    args.add_argument('-r', '--resume', default=None, type=str,
                      help='path to latest checkpoint (default: None)')
    args.add_argument('-d', '--device', default=None, type=str,
                      help='indices of GPUs to enable (default: all)')
    args.add_argument('--dir', default=None, type=str, help='root folder containing multiple experiment subfolders')
    args.add_argument('--comp_thresh', default=False, type=bool, help='If True, compute the threshold for the anomaly detection by processing the training set (default: False)')
    args.add_argument('--thresh_dir', default=None, type=str, help='If comp-thresh is False, thresholds are taken by from the file with this path (default: None)')

    parsed = args.parse_args()
    if parsed.dir:
        main(parsed.dir)
    else:
        config = ConfigParser.from_args(args)
        main(config)
    