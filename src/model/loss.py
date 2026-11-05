import torch.nn.functional as F
from torch import nn
import torch


def kl_loss(p, q):
    res = p * (torch.log(p + 0.0001) - torch.log(q + 0.0001))
    return torch.mean(torch.sum(res, dim=-1), dim=1)

def anomaly_attention_loss(output, input, series, prior, win_size, k=3):
    series_loss = 0.0
    prior_loss = 0.0
    for u in range(len(prior)):
        series_loss += (torch.mean(kl_loss(series[u], (
                prior[u] / torch.unsqueeze(torch.sum(prior[u], dim=-1), dim=-1).repeat(1, 1, 1,
                                                                                        win_size)).detach())) + torch.mean(
            kl_loss((prior[u] / torch.unsqueeze(torch.sum(prior[u], dim=-1), dim=-1).repeat(1, 1, 1,
                                                                                                win_size)).detach(),
                        series[u])))
        prior_loss += (torch.mean(kl_loss(
            (prior[u] / torch.unsqueeze(torch.sum(prior[u], dim=-1), dim=-1).repeat(1, 1, 1,
                                                                                    win_size)),
            series[u].detach())) + torch.mean(
                    kl_loss(series[u].detach(), (
                    prior[u] / torch.unsqueeze(torch.sum(prior[u], dim=-1), dim=-1).repeat(1, 1, 1,
                                                                                            win_size)))))
    series_loss = series_loss / len(prior)
    prior_loss = prior_loss / len(prior)

    rec_loss = mse(output, input)

    loss1 = rec_loss - k * series_loss
    loss2 = rec_loss + k * prior_loss

    return loss1, loss2

def mse(p,q):
    return F.mse_loss(p,q)