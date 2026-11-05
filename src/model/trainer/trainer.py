import numpy as np
import torch
from torchvision.utils import make_grid
from .base import BaseTrainer
from utils import inf_loop, MetricTracker
import digitalhub as dh

class Trainer(BaseTrainer):
    """
    Trainer class: define an epoch of training and validation.
    """

    def __init__(self, model, criterion, metric_ftns, optimizer, config, device,
                 data_loader=None, valid_data_loader=None, lr_scheduler=None, len_epoch=None):
        super().__init__(model, criterion, metric_ftns, optimizer, config)
        """
        params:
            model: the neural network
            criterion: the loss function
            metric_ftns: metrics for evaluation
            optimizer: the optimizer for the model
            config: configuration of this training from config.json
            device: torch.device, CPU or GPU
            data_loader: data loader for training
            valid_data_loader: data loader for validation
            lr_scheduler: learning rate scheduler
            len_epoch: the number of batches per epoch. None means to use the entire data_loader.
            seg: boolean, whether to perform segmentation task
        """
        self.config = config
        self.device = device
        self.data_loader = data_loader
        self.input_channels = self.model.in_channels
        self.anomaly_attention = self.model.anomaly_attention
        self.win_size = self.model.win_size
        self.proj_name = config["proj_name"]

        if len_epoch is None:
            # epoch-based training
            self.len_epoch = len(self.data_loader)
        else:
            # iteration-based training
            self.data_loader = inf_loop(data_loader)
            self.len_epoch = len_epoch
        self.valid_data_loader = valid_data_loader
        self.do_validation = self.valid_data_loader is not None
        self.log_step = 5000 # interval for logging
        # if lr_scheduler is not None:
        #     if isinstance(lr_scheduler, torch.optim.lr_scheduler.CosineAnnealingLR) or isinstance(lr_scheduler,torch.optim.lr_scheduler.CosineAnnealingWarmRestarts):
        #         self.lr_scheduler = lr_scheduler(self.optimizer, **config['lr_scheduler']['args'])
        #     else:
        self.lr_scheduler = lr_scheduler

# Set up visualization writer instance
        self.train_metrics = MetricTracker(
            'loss',
            *[m.__name__ for m in self.metric_ftns],
            writer=self.writer
        )
        self.valid_metrics = MetricTracker(
            'loss',
            *[m.__name__ for m in self.metric_ftns],
            writer=self.writer
        )
        metric_keys = ['loss']
        for met in self.metric_ftns:
            metric_keys.append(met.__name__)

        self.train_metrics = MetricTracker(*metric_keys, writer=self.writer)
        self.valid_metrics = MetricTracker(*metric_keys, writer=self.writer)

        #to have a graph in Tensorboard
        self.model.eval()
        
        data, target = next(iter(self.data_loader))
        self.n_time_slots = data.shape[2]
        rows, cols = data.shape[3], data.shape[4]
        if isinstance(self.input_channels, list):
            dummy_input = []
            for i in range(len(self.input_channels)):
                dummy_input.append(torch.randn(1, self.input_channels[i], self.n_time_slots, rows, cols).to(self.device))
            
            self.writer.add_graph(self.model, tuple(dummy_input))
        else:  
            dummy_input = torch.randn(1, self.input_channels, self.n_time_slots, rows, cols).to(self.device) 
            self.writer.add_graph(self.model, dummy_input)

        self.epoch=0

    @staticmethod
    def visu(input):
        """
        Prepare input for visualization in Tensorboard
        """
        if input.dim() == 5:
            input_visu = input[:, :, 0, :, :]
            return input_visu
        return input

    def recursive_todevice(x, device):
        if isinstance(x, torch.Tensor):
            return x.to(device)
        elif isinstance(x, dict):
            return {k: recursive_todevice(v, device) for k, v in x.items()}
        else:
            return [recursive_todevice(c, device) for c in x]

    def _train_epoch(self, epoch):
        """
        Training logic for an epoch

        :param epoch: Integer, current training epoch.
        :return: A log that contains average loss and metric in this epoch.
        """
        self.epoch+=1
        self.model.train() #activate dropout, batchnorm...
        self.train_metrics.reset()

        for batch_idx, (data, target) in enumerate(self.data_loader):
            data, target = data.to(self.device), target.to(self.device)
            target = target.long() #CrossEntropyLoss needs target to be of type Long
            self.optimizer.zero_grad()
            #print(torch.isnan(data1).any(), torch.isnan(data2).any(), torch.isnan(target).any())
            if self.anomaly_attention:
                out, maps, prior, sigma = self.model(data)
                loss1, loss2 = self.criterion(out,target,maps,prior,self.win_size)
                loss1.backward(retain_graph=True)
                loss2.backward()

            else:
                out = self.model(data)
                loss = self.criterion(out, target)
                loss.backward() 
            
            self.optimizer.step() #update weights

            #Writing metrics on Tensorboard
            self.writer.set_step((epoch - 1) * self.len_epoch + batch_idx) #step = which batch we’re on (accumulated across epochs).
            if self.anomaly_attention:
                self.train_metrics.update('loss', loss1.item()) #update loss value
            else:
                self.train_metrics.update('loss', loss.item()) #update loss value

            if batch_idx % self.log_step == 0:
                #Writing images on Tensorboard

                self.logger.debug('Train Epoch: {} {} Loss: {:.6f}'.format(
                    epoch,
                    self._progress(batch_idx),
                    loss.item()))

            if batch_idx == self.len_epoch:
                break
        log = self.train_metrics.result()

        if self.do_validation:
            val_log = self._valid_epoch(epoch)
            log.update(**{'val_'+k: v for k, v in val_log.items()})

        if self.lr_scheduler is not None:
            if isinstance(self.lr_scheduler, torch.optim.lr_scheduler.ReduceLROnPlateau):
                self.lr_scheduler.step(val_log['loss'])
            else:
                self.lr_scheduler.step()

        torch.cuda.empty_cache() 

        return log
    

    def _valid_epoch(self, epoch):
        """
        Validate after training an epoch

        :param epoch: Integer, current training epoch.
        :return: A log that contains information about validation
        """
        self.model.eval()
        self.valid_metrics.reset()
        with torch.no_grad():
            for batch_idx, (data, target) in enumerate(self.valid_data_loader):

                data, target = data.to(self.device), target.to(self.device)
                target = target.long() #CrossEntropyLoss needs target to be of type Long
                #print(torch.isnan(data1).any(), torch.isnan(data2).any(), torch.isnan(target).any())
                if self.anomaly_attention:
                    out, maps, prior, sigma = self.model(data)
                    loss1, loss2 = self.criterion(out,target,maps,prior,self.win_size)
    
                else:
                    out = self.model(data)
                    loss = self.criterion(out, target)

                #metric update on Tensorboard
                if batch_idx==0:
                    self.writer.set_step(epoch, 'valid')
                if self.anomaly_attention:
                    self.valid_metrics.update('loss', loss1.item(), val=True) #update loss value
                else:
                    self.valid_metrics.update('loss', loss.item(), val=True) #update loss value
                
                if batch_idx == self.len_epoch:
                    break

        # # add histogram of model parameters to the tensorboard
        # for name, p in self.model.named_parameters():
        #     self.writer.add_histogram(name, p, bins='auto')

        return self.valid_metrics.result(val=True)

    def _progress(self, batch_idx):
        """
        Progress bar
        """
        base = '[{}/{} ({:.0f}%)]'
        if hasattr(self.data_loader, 'n_samples'):
            current = batch_idx * self.data_loader.batch_size
            total = self.data_loader.n_samples
        else:
            current = batch_idx
            total = self.len_epoch
        return base.format(current, total, 100.0 * current / total)
