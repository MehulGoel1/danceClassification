import argparse
import numpy as np
import json
import os
import torch
import torch.nn as nn
import torchvision.models as models
from torch.utils.data import Dataset, DataLoader
from tqdm import tqdm
import torch.nn.functional as F

from logger import Logger
from utils import *
from model import *
from dataset import *

np.set_printoptions(precision=3)
np.set_printoptions(suppress=True)

def argParser():
    """
    This function creates a parser object which parses all the flags from the command line
    We can access the parsed command line values using the args object returned by this function
    Usage:
        First field is the flag name.
        dest=NAME is the name to reference when using the parameter (args.NAME)
        default is the default value of the parameter
    Example:
        > python run.py --gpu 0
        args.gpu <-- 0
    """
    parser = argparse.ArgumentParser()

    # model specifications
    parser.add_argument("--mode", dest="mode", default='train', help="Mode is one of 'train', 'test'")
    parser.add_argument("--model", dest="model", default="baseline_lstm", help="Name of model to use")
    parser.add_argument("--encode", dest="encode", default=0, help="encode is 0 or 1, default 0")
    parser.add_argument("--gpu", dest="gpu", type=str, default='0', help="The gpu number if there's more than one gpu")
    parser.add_argument("--batch-size", dest="batch_size", type=int, default=100, help="Size of the minibatch")
    parser.add_argument("--learning-rate", dest="learning_rate", type=float, default=1e-3, help="Learning rate for training")
    parser.add_argument("--epochs", dest="epochs", type=int, default=10, help="Number of epochs to train for")

    # dataset and logger paths
    parser.add_argument("--image-train-path", dest="image_train_path", help="Training data file for the image dataset")
    parser.add_argument("--image-val-path", dest="image_val_path", help="Validation data file for the image dataset")
    parser.add_argument("--encode-path", dest="encode_path", help="Image encodings data file")
    parser.add_argument("--pose-train-path", dest="pose_train_path", help="Training data file for the pose dataset")
    parser.add_argument("--pose-val-path", dest="pose_val_path", help="Validation data file for the pose dataset")
    parser.add_argument("--log", dest="log", default='', help="Unique log directory name under log/. If the name is empty, do not store logs")

    # create argparser
    args = parser.parse_args()
    return args


def main():
    """
    Perform training of testing of many to one model
    Optionally encode your data first with a CNN
    """
    # setup
    print("Setting up...")
    args = argParser()
    device = torch.device('cuda:' + args.gpu if torch.cuda.is_available() else "cpu")
    print("Using device: ", device)

    # Set up logging
    unique_logdir = create_unique_logdir(args.log, args.learning_rate)
    logger = Logger(unique_logdir) if args.log != '' else None
    print("All training logs will be saved to: ", unique_logdir)
    print("Will log to tensorboard: ", logger is not None)

    # Turns args into a dictionary to pass to models
    kwargs = vars(args)
    params = kwargs.copy()

    # Encode your data before using it
    encode_path_train = os.path.join(args.encode_path, "encoded_features_train.pt")
    encode_path_val = os.path.join(args.encode_path, "encoded_features_val.pt")

    if args.encode == 1:
        print("Starting encoding...")

        # indexes don't exist, create them
        if not os.path.exists(args.train_path):
            make_jpg_index("/mnt/disks/disk1/raw/rgb")
            
        # initialize image Datasets and DataLoaders
        image_dataset = rawImageDataset(args.image_train_path)
        image_dataloader = DataLoader(image_dataset, batch_size=args.batch_size, shuffle=False, num_workers=4)
        val_image_dataset = rawImageDataset(args.image_val_path)
        val_image_dataloader = DataLoader(val_image_dataset, batch_size=args.batch_size, shuffle=False, num_workers=4)
        
        # Forward pass through the RGB CNN encoding model
        rgb_encoder = ModelChooser("resnet18_features")
        rgb_encoder = rgb_encrgb_encoderoding_model.to(device)
        # Run a test forward pass to save all features
        print("Computing RGB CNN forward pass...")
        test(rgb_encoder, image_dataloader, device, save_filepath=encode_path_train)
        test(rgb_encoder, val_image_dataloader, device, save_filepath=encode_path_val)


        # Train the Densepose CNN encoding model
#         pose_encoder = ModelChooser("pose_features")
#         pose_encoder = pose_encoder.to(device)
#         print("Computing Pose CNN forward and backward passes...")
        # initialize pose Datasets and DataLoaders
        pose_dataset = rawPoseDataset(args.pose_train_path)
        pose_dataloader = DataLoader(pose_dataset, batch_size=args.batch_size, shuffle=False, num_workers=4)
        val_pose_dataset = rawPoseDataset(args.pose_val_path)
        val_pose_dataloader = DataLoader(val_pose_dataset, batch_size=args.batch_size, shuffle=False, num_workers=4)
#         optimizer = optim.SGD(model.parameters(), lr=.01,
#                      momentum=0.9, nesterov=True)
#         train(pose_encoder, optimizer, pose_dataloader, device)


    # Load the model
    model = ModelChooser(args.model, **kwargs)
    model = model.to(device)

    # Load the encoded feature dataset
    # TODO: concatenate the RGB and pose data
    frame_select = range(0,300,5)
    dataset = rnnDataset(encode_path_train, args.train_path, frame_select)
    dataloader = DataLoader(dataset, batch_size=args.batch_size, shuffle=False, num_workers=4)
    val_dataset = rnnDataset(encode_path_val, args.val_path, frame_select)
    val_dataloader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False, num_workers=4)


    if args.mode == 'train':
        print("Starting training...")
        # Save all params used to train
        json.dump(params, open(os.path.join(unique_logdir, "params.json"), 'w'), indent=2)

        # TODO: Better way to pick the optimizer
        optimizer = optim.SGD(model.parameters(), lr=args.learning_rate,
                     momentum=0.9, nesterov=True)
        # train model
        train(model, optimizer, dataloader, val_dataloader, device, logger=logger, **kwargs)

    elif args.mode == 'test':
        print("Starting testing...")
        test(model, dataloader, device)

def train(model, optimizer, dataloader, val_dataloader, device, epochs=10, 
    dtype=None, logger=None, **kwargs):
    
    criterion = nn.CrossEntropyLoss()

    save_to_log = logger is not None
    logdir = logger.get_logdir() if logger is not None else None

    for e in range(epochs):
        # initialize loss
        epoch_loss = []
        num_correct = 0
        num_samples = 0
        model.train()

        # train for one epoch
        for t, (x,y) in enumerate(tqdm(dataloader)):
            model.train()
            x = x.to(device=device, dtype=dtype)  # move to device, e.g. GPU
            y = y.to(device=device, dtype=torch.long)
            scores = model(x)
            loss = criterion(scores, y)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            epoch_loss.append(loss.item())

            # calculate accuracy
            _, preds = scores.max(1)
            num_correct += (preds == y).sum()
            num_samples += preds.size(0)

        # End of epoch, run validations
        model.eval()
        with torch.no_grad():
            epoch_train_loss = np.mean(epoch_loss)
            epoch_train_acc = float(num_correct) / num_samples
            epoch_val_acc, epoch_val_loss = \
                test(model, optimizer, val_dataloader, device)

        # Add to logger on tensorboard at the end of an epoch
        if save_to_log:
            logger.scalar_summary("epoch_train_loss", epoch_train_loss, epoch)
            logger.scalar_summary("epoch_train_acc", epoch_train_acc, epoch)
            logger.scalar_summary("epoch_val_loss", epoch_val_loss, epoch)
            logger.scalar_summary("epoch_val_acc", epoch_val_acc, epoch)

            # TO DO: Save epoch checkpoint
            # if epoch % log_every == 0:
            #     save_checkpoint(logdir, model, optimizer, epoch, epoch_average_loss, lr)
            # # Save best validation checkpoint
            # if epoch_val_loss == min_val_loss:
            #     save_checkpoint(logdir, model, optimizer, epoch, epoch_average_loss, lr, "val_ppl")

        print('Epoch {} | train loss: {} | val loss: {} | train acc: {} | val acc: {}' \
            .format(e + 1, epoch_train_loss, epoch_val_loss, epoch_train_acc, epoch_val_acc))


def test(model, optimizer, dataloader, device, dtype=None, save_filepath=None, **kwargs):
    """
    Test your model on the dataloaded by dataloader
    """

    criterion = nn.CrossEntropyLoss()

    aggregate_loss = []
    all_scores = []
    num_correct = 0
    num_samples = 0
    
    # Tests on batches of data from dataloader
    model.eval()
    with torch.no_grad():
        for (i, batch) in enumerate(tqdm(dataloader)):
            x, y = batch
            x = x.to(device=device, dtype=dtype)  # move to device, e.g. GPU
            y = y.to(device=device, dtype=torch.long)
            scores = model(x)
            loss = criterion(scores, y)
            aggregate_loss.append(loss.item())
            _, preds = scores.max(1)
            num_correct += (preds == y).sum()
            num_samples += preds.size(0)

            # Record scores to save
            if save_filepath is not None:
                all_scores.append(scores)

    if save_filepath:
        encoding = torch.cat(all_scores)
        torch.save(encoding, save_filepath)
    
    # Report accuracy and average loss
    acc = float(num_correct) / num_samples
    print('Got %d / %d correct (%.2f)' % (num_correct, num_samples, 100 * acc))

    # Calculate average loss
    average_loss = np.mean(aggregate_loss)

    return acc, average_loss


if __name__ == "__main__":
    main()
