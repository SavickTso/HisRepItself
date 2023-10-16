from torch.utils.data import Dataset
import numpy as np
from h5py import File
import scipy.io as sio
from utils import data_utils
from matplotlib import pyplot as plt
import torch
import os
from utils import ang2joint


class Datasets(Dataset):
    def __init__(self, skip_rate, actions=None, split=0):
        """
        :param path_to_data:
        :param actions:
        :param input_n:
        :param output_n:
        :param dct_used:
        :param split: 0 train, 1 testing, 2 validation
        :param sample_rate:
        """
        self.path_to_data = "./datasets/amass/"
        self.split = split
        # self.in_n = opt.input_n
        # self.out_n = opt.output_n
        # self.sample_rate = opt.sample_rate
        self.p3d = []
        self.keys = []
        self.data_idx = []
        self.joint_used = np.arange(4, 22)
        seq_len = self.in_n + self.out_n

        skel = np.load("./body_models/smpl_skeleton.npz")
        p3d0 = torch.from_numpy(skel["p3d0"]).float().cuda()
        parents = skel["parents"]
        parent = {}
        for i in range(len(parents)):
            parent[i] = parents[i]
        n = 0
        # for ds in amass_splits[split]:
        ds = "CMU"
        if not os.path.isdir(self.path_to_data + ds):
            print(ds)
            exit
        print(">>> loading {}".format(ds))
        for sub in os.listdir(self.path_to_data + ds):
            if not os.path.isdir(self.path_to_data + ds + "/" + sub):
                continue
            for act in os.listdir(self.path_to_data + ds + "/" + sub):
                if not act.endswith(".npz"):
                    continue
                # if not ('walk' in act or 'jog' in act or 'run' in act or 'treadmill' in act):
                #     continue
                pose_all = np.load(self.path_to_data + ds + "/" + sub + "/" + act)
                try:
                    poses = pose_all["poses"]
                except:
                    print("no poses at {}_{}_{}".format(ds, sub, act))
                    continue
                frame_rate = pose_all["mocap_framerate"]
                # gender = pose_all['gender']
                # dmpls = pose_all['dmpls']
                # betas = pose_all['betas']
                # trans = pose_all['trans']
                fn = poses.shape[0]
                sample_rate = 1  # int(frame_rate // 25)
                fidxs = range(0, fn, sample_rate)
                fn = len(fidxs)
                poses = poses[fidxs]
                poses = torch.from_numpy(poses).float().cuda()
                poses = poses.reshape([fn, -1, 3])
                # remove global rotation
                poses[:, 0] = 0
                p3d0_tmp = p3d0.repeat([fn, 1, 1])
                p3d = ang2joint.ang2joint(p3d0_tmp, poses, parent)
                # self.p3d[(ds, sub, act)] = p3d.cpu().data.numpy()
                self.p3d.append(p3d.cpu().data.numpy())
                if split == 2:
                    valid_frames = np.arange(0, fn - seq_len + 1, skip_rate)
                else:
                    valid_frames = np.arange(0, fn - seq_len + 1, skip_rate)

                # tmp_data_idx_1 = [(ds, sub, act)] * len(valid_frames)
                self.keys.append((ds, sub, act))
                tmp_data_idx_1 = [n] * len(valid_frames)
                tmp_data_idx_2 = list(valid_frames)
                self.data_idx.extend(zip(tmp_data_idx_1, tmp_data_idx_2))
                n += 1

    def __len__(self):
        return np.shape(self.data_idx)[0]

    def __getitem__(self, item):
        key, start_frame = self.data_idx[item]
        # fs = np.arange(start_frame, start_frame + self.in_n + self.out_n)
        return self.p3d[key]  # [fs]  # , key
