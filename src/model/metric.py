import torch
import torch.nn.functional as F
from torch import nn
import torchmetrics

def m_kld(mu, logvar, recon_x,x, seg_x, gt,NUM_CLASSES, ignore_index=None):
    """
    Kullback-Leibler divergence
    """

    KLD_element =mu.pow(2).add_(logvar.exp()).mul_(-1).add_(1).add_(logvar)
    KLD = torch.sum(KLD_element).mul_(-0.5)
    return KLD/torch.numel(x)

def m_mse(mu, logvar, recon_x,x, seg_x, gt, NUM_CLASSES, ignore_index=None):
    """
    Mean Squared Error
    """
    reconstruction_function = nn.MSELoss(reduction='mean')
    return reconstruction_function(recon_x, x)

def m_ce(mu, logvar, recon_x,x,seg_x,gt, NUM_CLASSES, ignore_index=-100):
    """
    Cross Entropy Loss
    """
    return F.cross_entropy(seg_x, gt, reduction='mean', ignore_index=ignore_index)

def m_ssim(mu, logvar, recon_x, x, seg_x, gt, NUM_CLASSES, ignore_index=None):
    """
    Structural Similarity Index Measure (SSIM)
    """
    device = recon_x.device
    ssim_metric = torchmetrics.image.StructuralSimilarityIndexMeasure(data_range=1.0).to(device)
    if recon_x.dim() == 5:  # [B, C, T, H, W]
        B, C, T, H, W = recon_x.shape
        ssim_scores = []
        for t in range(T):
            ssim_scores.append(ssim_metric(recon_x[:, :, t], x[:, :, t]))
        return torch.stack(ssim_scores).mean()
    return ssim_metric(recon_x, x)

def m_oa(mu, logvar, recon_x, x, seg_x, gt, NUM_CLASSES, ignore_index=-100):
    """
    Overall Accuracy (OA)
    """
    device = recon_x.device
    acc = torchmetrics.classification.MulticlassAccuracy(num_classes=NUM_CLASSES, ignore_index=ignore_index).to(device)
    return acc(seg_x, gt)

def m_iou(mu, logvar, recon_x, x, seg_x, gt, NUM_CLASSES, ignore_index=-100):
    """
    Intersection over Union (IoU)
    """
    device = recon_x.device
    iou = torchmetrics.classification.MulticlassJaccardIndex(num_classes=NUM_CLASSES, ignore_index=ignore_index).to(device)
    return iou(seg_x, gt)


def m_f1(mu, logvar, recon_x, x, seg_x, gt, NUM_CLASSES, ignore_index=-100):
    """
    F1 Score (macro)
    """
    device = recon_x.device
    f1 = torchmetrics.classification.MulticlassF1Score(num_classes=NUM_CLASSES, average='macro', ignore_index=ignore_index).to(device)
    return f1(seg_x, gt)

def m_f1_per_class(mu, logvar, recon_x, x, seg_x, gt, NUM_CLASSES, ignore_index=-100):
    """
    F1 Score per class
    """
    device = recon_x.device
    f1 = torchmetrics.classification.MulticlassF1Score(num_classes=NUM_CLASSES, average=None, ignore_index=ignore_index).to(device)
    return f1(seg_x, gt)

def m_precision_per_class(mu, logvar, recon_x, x, seg_x, gt, NUM_CLASSES, ignore_index=-100):
    """
    Precision per class
    """
    device = recon_x.device
    precision = torchmetrics.classification.MulticlassPrecision(num_classes=NUM_CLASSES, average=None, ignore_index=ignore_index).to(device)
    return precision(seg_x, gt)

def m_recall_per_class(mu, logvar, recon_x, x, seg_x, gt, NUM_CLASSES, ignore_index=-100):
    """
    Recall per class
    """
    device = recon_x.device
    recall = torchmetrics.classification.MulticlassRecall(num_classes=NUM_CLASSES, average=None, ignore_index=ignore_index).to(device)
    return recall(seg_x, gt)