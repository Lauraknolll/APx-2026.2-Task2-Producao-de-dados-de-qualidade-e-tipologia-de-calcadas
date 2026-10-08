import os
import torch
from torch import nn
from copy import deepcopy
import timm

if not torch.cuda.is_available():
    os.environ['XFORMERS_DISABLED'] = '1'

from dinov2.models.vision_transformer import vit_small, vit_base, vit_large, vit_giant2

class DinoVisionTransformerClassifier(nn.Module):

    def __init__(self, model_size="small", nc=0):
        super(DinoVisionTransformerClassifier, self).__init__()
        self.model_size = model_size

        if nc == 0:
            print("Number of classes must be greater than 0")
            exit(1)

        # loading a model with registers
        n_register_tokens = 4

        if model_size == "small":
            model = vit_small(patch_size=14,
                              img_size=526,
                              init_values=1.0,
                              num_register_tokens=n_register_tokens,
                              block_chunks=0)
            self.embedding_size = 384
            self.number_of_heads = 6

        elif model_size == "base":
            model = vit_base(patch_size=14,
                             img_size=526,
                             init_values=1.0,
                             num_register_tokens=n_register_tokens,
                             block_chunks=0)
            self.embedding_size = 768
            self.number_of_heads = 12

        elif model_size == "large":
            model = vit_large(patch_size=14,
                              img_size=526,
                              init_values=1.0,
                              num_register_tokens=n_register_tokens,
                              block_chunks=0)
            self.embedding_size = 1024
            self.number_of_heads = 16

        elif model_size == "giant":
            model = vit_giant2(patch_size=14,
                               img_size=526,
                               init_values=1.0,
                               num_register_tokens=n_register_tokens,
                               block_chunks=0)
            self.embedding_size = 1536
            self.number_of_heads = 24

        self.transformer = deepcopy(model)

        self.classifier = nn.Sequential(nn.Linear(self.embedding_size, 256), nn.ReLU(), nn.Linear(256, nc))

    def forward(self, x):
        x = self.transformer(x)
        x = self.transformer.norm(x)
        x = self.classifier(x)
        return x


class CLIP_Classifier(nn.Module):
    def __init__(self, model_name='', n_target_classes=7):
        super().__init__()
        self.model = timm.create_model(model_name=model_name, pretrained=True, in_chans=3)
        # Replace the final head with a two-layer classifier.
        num_features = self.model.num_features
        self.model.head = nn.Linear(num_features, 256)
        self.fully_connect = nn.Sequential(nn.Linear(256, 128),
                                           nn.ReLU(),
                                           nn.Linear(128, n_target_classes))

    def forward(self, image):
        x = self.model(image)
        x = self.fully_connect(x)
        return x
