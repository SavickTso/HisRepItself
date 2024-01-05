import math
import os
import pickle
import sys
import time
from sys import exit

import IPython
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, random_split

from model import utils_rf
from utils import amass as datasets


class MultiHeadAttention(nn.Module):
    def __init__(self, d_model, n_heads):
        super(MultiHeadAttention, self).__init__()
        self.n_heads = n_heads
        self.head_dim = d_model // n_heads
        print("head_dim is", self.head_dim)
        self.fc_query = nn.Linear(d_model, d_model)
        self.fc_key = nn.Linear(d_model, d_model)
        self.fc_value = nn.Linear(d_model, d_model)

        self.fc_out = nn.Linear(d_model, d_model)

    def forward(self, query, key, value, mask=None):
        # Linear transformations
        query = self.fc_query(query).to(torch.float16)
        key = self.fc_key(key).to(torch.float16)
        value = self.fc_value(value).to(torch.float16)

        # Reshape for multi-heads
        query = query.view(query.shape[0], -1, self.n_heads, self.head_dim).permute(
            0, 2, 1, 3
        )
        key = key.view(key.shape[0], -1, self.n_heads, self.head_dim).permute(
            0, 2, 1, 3
        )
        value = value.view(value.shape[0], -1, self.n_heads, self.head_dim).permute(
            0, 2, 1, 3
        )

        # Attention calculation
        energy = torch.matmul(query, key.permute(0, 1, 3, 2)) / (self.head_dim**0.5)
        # print("energy's shape is", energy.shape)
        print("energy's sample1, head1 is", energy[0][0])
        # IPython.embed()
        # sys.exit()
        if mask is not None:
            energy = energy.masked_fill(mask == 0, float("-1e20"))

        attention = torch.softmax(energy, dim=-1)
        print("attention's shape is", attention.shape)
        x = torch.matmul(attention, value).to(torch.float32)

        # x = F.scaled_dot_product_attention(query, key, value).to(torch.float32)
        print("x's dtype is", x.dtype)
        print("x's shape is", x.shape)
        # Reshape and concatenate
        x = x.permute(0, 2, 1, 3).contiguous()
        x = x.view(x.shape[0], -1, self.n_heads * self.head_dim)

        # Final linear layer
        x = self.fc_out(x)

        return x


class PositionalEncoding(nn.Module):
    def __init__(self, d_model, max_len=2533):
        super(PositionalEncoding, self).__init__()
        position = torch.arange(0, max_len).unsqueeze(1).float().cuda()
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float()
            * -(torch.log(torch.tensor(10000.0)) / d_model)
        ).cuda()
        self.positional_encoding = torch.zeros((1, max_len, d_model)).cuda()
        self.positional_encoding[0, :, 0::2] = torch.sin(position * div_term)
        self.positional_encoding[0, :, 1::2] = torch.cos(position * div_term)

    def forward(self, x):
        return x + self.positional_encoding[:, : x.size(1)].detach()


class FeedForward(nn.Module):
    def __init__(self, d_model, d_ff, dropout=0.1):
        super(FeedForward, self).__init__()
        self.linear1 = nn.Linear(d_model, d_ff)
        self.dropout = nn.Dropout(dropout)
        self.linear2 = nn.Linear(d_ff, d_model)

    def forward(self, x):
        x = torch.relu(self.linear1(x))
        x = self.dropout(x)
        x = self.linear2(x)
        return x


class TransformerBlock(nn.Module):
    def __init__(self, d_model, n_heads, d_ff, dropout=0.1):
        super(TransformerBlock, self).__init__()
        self.attention = MultiHeadAttention(d_model, n_heads)
        self.norm1 = nn.LayerNorm(d_model)
        self.dropout = nn.Dropout(dropout)

        self.feed_forward = FeedForward(d_model, d_ff)
        self.norm2 = nn.LayerNorm(d_model)

    def forward(self, x, mask):
        attention_output = self.attention(x, x, x, mask)
        print("shape of attention_output", attention_output.shape)
        x = x + self.dropout(attention_output)
        x = self.norm1(x)

        feed_forward_output = self.feed_forward(x)
        x = x + self.dropout(feed_forward_output)
        x = self.norm2(x)

        return x


class Transformer(nn.Module):
    def __init__(
        self, d_model, n_heads, d_ff, num_blocks, max_len, num_classes, dropout=0.1
    ):
        super(Transformer, self).__init__()
        self.positional_encoding = PositionalEncoding(d_model, max_len)
        self.transformer_blocks = nn.ModuleList(
            [
                TransformerBlock(d_model, n_heads, d_ff, dropout)
                for _ in range(num_blocks)
            ]
        )
        self.classification_head = nn.Linear(d_model, num_classes)

    def forward(self, x, mask):
        print("input x shape", x.shape)
        x = self.positional_encoding(x)
        for transformer_block in self.transformer_blocks:
            x = transformer_block(x, mask)
        # Global average pooling along the sequence dimension
        x = x.mean(dim=1)
        # Classification head
        x = self.classification_head(x)
        return x


seed = 42
# Numpy
np.random.seed(seed)
# Pytorch
torch.manual_seed(seed)
torch.cuda.manual_seed(seed)
torch.backends.cudnn.deterministic = True
torch.use_deterministic_algorithms = True

# Example usage:
sample_number = 32
sequence_length = 2533
d_model = 156
n_heads = 4
d_ff = 128
num_blocks = 2
max_len = 2533
num_classes = 23
dropout = 0.1
BATCH_SIZE = 32
NUM_EPOCH = 100

model = Transformer(d_model, n_heads, d_ff, num_blocks, max_len, num_classes, dropout)
# input_data = torch.randn((sample_number, sequence_length, data_dimension))
# mask = torch.ones((sample_number, sequence_length))
mask = None


optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
# 誤差関数
criterion = torch.nn.CrossEntropyLoss()

# データセットの用意
data_loader = dict()
# dataset = datasets.Datasets()
with open("dataset_amass_bmlmovi_120.pkl", "rb") as file:
    dataset = pickle.load(file)

# IPython.embed()
test_size = int(0.2 * len(dataset))
train_size = len(dataset) - test_size
train_dataset, test_dataset = random_split(dataset, [train_size, test_size])
print(">>> Training dataset length: {:d}".format(dataset.__len__()))
data_loader["train"] = DataLoader(
    train_dataset,
    batch_size=BATCH_SIZE,
    shuffle=False,
    num_workers=0,
    pin_memory=False,
)
data_loader["test"] = DataLoader(
    test_dataset,
    batch_size=BATCH_SIZE,
    shuffle=False,
    num_workers=0,
    pin_memory=False,
)
model.cuda()
model.train()
print(model)

for epoch in range(1, NUM_EPOCH + 1):
    correct_pb = 0
    sum_loss = 0
    # IPython.embed()
    for batch_idx, (data, label) in enumerate(data_loader["train"]):
        data = data.cuda()
        # label = torch.eye(23)[label].float()  # numclasses=23
        label = label.cuda()
        # print("label's shape is", label.shape)
        # print(batch_idx)
        # print("labels shape", label.shape)
        # print("labels shape", label)
        output_pb = model(data, mask).to(torch.float32)
        # print("the output shape is", output_pb.shape)
        # print("the output is", output_pb)
        loss = criterion(output_pb, label)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        sum_loss += loss.item()
        _, predict = torch.max(output_pb.data, 1)
        correct_pb += (predict == label).sum().item()

    print(
        "# Epoch: {} | Loss: {:.4f} | Accuracy PB: {:.3f}[%]".format(
            epoch,
            sum_loss / len(data_loader["train"].dataset),
            (100.0 * correct_pb / len(data_loader["train"].dataset)),
        )
    )
    # if 100.0 * correct_pb / len(data_loader["train"].dataset) >= 20:
    #     break

model.eval()

correct_pb = 0
with torch.no_grad():
    for batch_idx, (data, label) in enumerate(data_loader["test"]):
        data = data.cuda()
        label = label.cuda()
        tic = time.time()
        output_pb = model(data, mask)

        _, predict = torch.max(output_pb.data, 1)
        correct_pb += (predict == label).sum().item()
        print("inference time is", time.time() - tic)

print(
    "# Test Accuracy: {:.3f}[%]".format(
        100.0 * correct_pb / len(data_loader["test"].dataset)
    )
)
IPython.embed()
