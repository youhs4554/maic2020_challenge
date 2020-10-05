import torch
import torch.utils.data
import pandas as pd
import os
import numpy as np
from utils.preprocessing import prepare_data, random_undersampling
from sklearn.preprocessing import MinMaxScaler
import joblib


class MAIC2020(torch.utils.data.Dataset):
    save_dir = os.path.join("/data", ".cache", "datasets", "MAIC2020")
    os.system("mkdir -p {}".format(save_dir))

    def __init__(self,
                 infile='data/train_cases.csv',
                 SRATE=100, MINUTES_AHEAD=5, VALIDATION_SPLIT=0.2,
                 transform=None, ext_scaler=None, use_ext=False, train=True, composition=True):

        # provide composition of target for reconstruction and classification task
        self.composition = composition

        phase = "train" if train else "val"
        if not os.path.exists(os.path.join(self.save_dir, f"x_train.pkl")) or not os.path.exists(os.path.join(self.save_dir, f"x_val.pkl")):
            # split train/validation data
            df = pd.read_csv(infile)

            # random state is a seed value
            train_df = df.sample(frac=1-VALIDATION_SPLIT, random_state=200)
            valid_df = df.drop(train_df.index)

            x_train, y_train = prepare_data(
                train_df, "train", save_dir=self.save_dir,
                SRATE=SRATE, MINUTES_AHEAD=MINUTES_AHEAD)

            x_val, y_val = prepare_data(
                valid_df, "val", save_dir=self.save_dir,
                SRATE=SRATE, MINUTES_AHEAD=MINUTES_AHEAD)

            self.X = x_train if train else x_val
            self.y_true = y_train if train else y_val

        else:
            xfile_path = os.path.join(self.save_dir, f'x_{phase}.pkl')
            yfile_path = os.path.join(self.save_dir, f'y_{phase}.pkl')

            print('loading...', flush=True, end='')
            self.X = pd.read_pickle(xfile_path).values
            self.y_true = pd.read_pickle(yfile_path).values
            print('done', flush=True)

        # 0: signal_ids, 1~4: externals, 5~: raw_signals
        signal_ids, self.ext, self.X = np.split(self.X, [1, 5, ], axis=1)

        self.y_true = self.y_true[:, [1]].astype(bool)

        self.X = self.X.astype("float")
        self.ext = self.ext.astype("float")
        self.signal_ids = signal_ids.ravel()

        if use_ext:
            ext_scaler = MinMaxScaler()
            if ext_scaler is not None:
                ext_scaler = ext_scaler

            # crazy way! exclude a categorical column(i.e. sex)
            ext_to_scale = self.ext[:, [0, 2, 3]]
            # sclaing external data
            ext_to_scale = ext_scaler.fit_transform(ext_to_scale)
            # save scaler as a file
            joblib.dump(ext_scaler, "scaler.gz")

            # synthesizes columns: [age, sex, weight, height]
            self.ext = np.insert(ext_to_scale, 1, self.ext[:, 1], axis=1)

        self.use_ext = use_ext  # use external data or not
        self.SRATE = SRATE
        self.transform = transform

    def __len__(self):
        return len(self.X)

    def __getitem__(self, ix):
        if self.use_ext:
            ext_sample = self.ext[ix]
            ext_sample = torch.tensor(ext_sample).float()

        x_sample = self.X[ix]
        y_sample = self.y_true[ix]

        # input : 20 [sec] => 20 * (100 [Hz]) = 2,000 [sample points]
        x_sample = torch.tensor(x_sample).view(-1, self.SRATE * 20).float()
        y_sample = torch.tensor(y_sample).long()

        if self.transform is not None:
            x_sample = self.transform(x_sample)

        if self.use_ext:
            return x_sample, y_sample, ext_sample

        return x_sample, y_sample


class MAIC2020_rec(MAIC2020):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.future_root = os.path.join(self.save_dir, "future_data")

    def __getitem__(self, ix):
        signal_id = self.signal_ids[ix]

        # load future signal data
        target_X = np.load(os.path.join(self.future_root, signal_id) + ".npy")

        # current signal
        current_X = self.X[ix]

        # input : 20 [sec] => 20 * (100 [Hz]) = 2,000 [sample points]
        current_X = torch.tensor(current_X).view(-1, self.SRATE * 20).float()

        # target : 60 [sec] after 5min
        target_X = torch.tensor(target_X).view(-1, self.SRATE * 60).float()

        if self.transform is not None:
            current_X = self.transform(current_X)
            target_X = self.transform(target_X)
        if self.composition:
            # provide classification target along with rec. targets
            y_sample = self.y_true[ix]
            y_sample = torch.tensor(y_sample).float()
            return current_X, target_X, y_sample
        else:
            return current_X, target_X


if __name__ == "__main__":
    pass
