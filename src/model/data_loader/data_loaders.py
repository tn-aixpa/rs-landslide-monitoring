from torchvision.transforms import v2
from torch.utils.data import Dataset
from torchvision.transforms import functional as TF
import numpy as np
import os
import torch
from torch.utils.data import DataLoader

class InSARDataLoader(DataLoader):
    """
    DataLoader wrapper for dataset derived from the features coming from Interferometric SAR data
    image_dir (str): the folder path containing tha dataset images.
    batch_size (int): the batch size to use during the training (default 32).
    shuffle (bool): If True, the dataset will be shuffled at the beginning of each epoch (default True).
    num_workers (int): The number of parallelized workers used to load the data (default 4).
    augmentations (bool): If True, data augmentation processes will be applied to the data before the processing in the model (default True).
    drop_last (bool): If True, it drops the last batch of the epoch that might not achieve the batch size (default False).
    """

    def __init__(self, image_dir, batch_size=32, shuffle=True, num_workers=4, augmentations=True, drop_last=False):
        self.image_dir = image_dir
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.num_workers = num_workers
        self.drop_last = drop_last
        if augmentations:
            self.transform = v2.Compose([
                v2.RandomHorizontalFlip(p=0.5),
                v2.RandomVerticalFlip(p=0.5),
                #v2.RandomRotation(degrees=90),
                #v2.ToTensorV2(transpose_mask=True)
            ]
            )
        else:            
            self.transform = None
        self.dataset = InSARDataset(self.image_dir, transform=self.transform)
        super().__init__(self.dataset, batch_size=self.batch_size, shuffle=self.shuffle, num_workers=self.num_workers, drop_last=self.drop_last)

class InSARDataset(Dataset):
    def __init__(self, data_path, transform=None):
        """
        data_path (str): path to directory containing Sentinel-2 input files (C, T, H, W).
        transform (torchvision.transform): data augmentation operations (default None).
        """
        self.files = [os.path.join(data_path, f) for f in os.listdir(data_path) if f.endswith('.npy')]
        self.transform = transform

    def __len__(self):
        return len(self.files)

    def __getitem__(self, idx):
        # lazy load (only this sample)
        x = np.load(self.files[idx])        # (C, T, H, W)

        x[np.isnan(x)] = 0

        x = torch.tensor(x, dtype=torch.float32)

        if self.transform:
            x = self.transform(x)

        return x, x