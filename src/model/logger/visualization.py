import importlib
from datetime import datetime
import numpy as np
import torch


class TensorboardWriter():
    def __init__(self, log_dir, logger, enabled):
        self.writer = None
        self.selected_module = ""

        if enabled:
            log_dir = str(log_dir)

            # Retrieve vizualization writer.
            succeeded = False
            for module in ["torch.utils.tensorboard", "tensorboardX"]:
                try:
                    self.writer = importlib.import_module(module).SummaryWriter(log_dir)
                    succeeded = True
                    break
                except ImportError:
                    succeeded = False
                self.selected_module = module

            if not succeeded:
                message = "Warning: visualization (Tensorboard) is configured to use, but currently not installed on " \
                    "this machine. Please install TensorboardX with 'pip install tensorboardx', upgrade PyTorch to " \
                    "version >= 1.1 to use 'torch.utils.tensorboard' or turn off the option in the 'config.json' file."
                logger.warning(message)

        self.step = 0
        self.mode = ''

        self.tb_writer_ftns = {
            'add_scalar', 'add_scalars', 'add_image', 'add_images', 'add_audio',
            'add_text', 'add_histogram', 'add_pr_curve', 'add_embedding'
        }
        self.tag_mode_exceptions = {'add_histogram', 'add_embedding'}
        self.timer = datetime.now()

    def set_step(self, step, mode='train'):
        self.mode = mode
        self.step = step
        if step == 0:
            self.timer = datetime.now()
        else:
            duration = datetime.now() - self.timer
            self.add_scalar('steps_per_sec', 1 / duration.total_seconds())
            self.timer = datetime.now()

    def __getattr__(self, name):
        """
        If visualization is configured to use:
            return add_data() methods of tensorboard with additional information (step, tag) added.
        Otherwise:
            return a blank function handle that does nothing
        """
        if name == "add_graph":
            return getattr(self.writer, "add_graph")
        if name in self.tb_writer_ftns: 
            add_data = getattr(self.writer, name, None) 

            def wrapper(tag, data, *args, **kwargs): 
                    if name not in self.tag_mode_exceptions:
                        tag = '{}/{}'.format(tag, self.mode)
                    if name == "add_image": 
                        if data.dim() == 4:
                            data = data[:, 0, :, :]  # Take the first image in the temporal series
                            data = data.squeeze(1)
                            print(data.shape)
                        if data.dim() == 3 and data.size(0) > 3:#For Sentinel-2 images, we only take the RGB image in TensorBoard (since PIL doesn’t handle 10-dimensional images).
                            data = data[[2,1,0], :, :]
                        elif data.dim() == 3 and data.size(0) == 2:
                            # Convert 2-channel image to 3-channel by adding a zero (blue) channel for Sentinel-1 images
                            zeros = data.new_zeros(1, data.size(1), data.size(2))
                            data = torch.cat([data, zeros], dim=0)
                    add_data(tag, data, self.step, *args, **kwargs)
            return wrapper
        else:
            # default action for returning methods defined in this class, set_step() for instance.
            try:
                attr = object.__getattr__(self,name)
            except AttributeError:
                raise AttributeError("type object '{}' has no attribute '{}'".format(self.selected_module, name))
            return attr

    def close(self):
        if self.writer is not None:
            self.writer.close()
