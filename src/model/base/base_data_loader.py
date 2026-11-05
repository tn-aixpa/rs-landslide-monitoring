import numpy as np
from torch.utils.data import DataLoader
from torch.utils.data.dataloader import default_collate 
from torch.utils.data.sampler import SubsetRandomSampler


class BaseDataLoader(DataLoader):
    """
    Base class for all data loaders
    """
    def __init__(self, dataset, batch_size, shuffle, validation_split, num_workers, collate_fn=default_collate):
        self.validation_split = validation_split
        self.shuffle = shuffle

        self.batch_idx = 0
        self.n_samples = len(dataset)

        # Split dataset into train, validation and test sets
        self.sampler, self.valid_sampler, self.test_sampler = self._split_sampler(self.validation_split)

        # Arguments for config.json
        self.init_kwargs = {
            'dataset': dataset,
            'batch_size': batch_size,
            'shuffle': self.shuffle,
            'collate_fn': collate_fn,
            'num_workers': num_workers
        }


        if self.sampler is not None:
            super().__init__(sampler=self.sampler, **self.init_kwargs)
        else:
            super().__init__(**self.init_kwargs)

    def _split_sampler(self, split):
        if split == 0.0:
            return None, None, None
        
        # Create a list of indices corresponding to dataset samples
        idx_full = np.arange(self.n_samples) 

        # Ensure reproducibility
        np.random.seed(0)
        np.random.shuffle(idx_full) #shuffle the indices

        if isinstance(split, int): 
            # Use fixed number of samples for validation/test
            len_valid = split
            len_test = split
        else:
            # Use percentage of samples for validation/test
            len_valid = int(self.n_samples * split) 
            len_test = int(self.n_samples * split)

        # Split dataset into validation, test and training indices
        valid_idx = idx_full[0:len_valid] 
        test_idx = idx_full[len_valid:len_valid + len_test] 
        train_idx = np.delete(idx_full, np.arange(0, len_valid + len_test))

        # Create random samplers for each split
        train_sampler = SubsetRandomSampler(train_idx)#créé des batchs ect de façon aléatoire
        valid_sampler = SubsetRandomSampler(valid_idx)
        test_sampler = SubsetRandomSampler(test_idx) #test_sampler not used in this class

        # turn off shuffle option which is mutually exclusive with sampler
        self.shuffle = False
        self.n_samples = len(train_idx)

        return train_sampler, valid_sampler, test_sampler

    def split_validation(self):
        """Return a DataLoader for the validation split"""
        if self.valid_sampler is None:
            return None
        else:
            return DataLoader(sampler=self.valid_sampler, **self.init_kwargs)
        
    def split_test(self):
        """Return a DataLoader for the test split"""
        if self.test_sampler is None:
            return None
        else:
            return DataLoader(sampler=self.test_sampler, **self.init_kwargs)
