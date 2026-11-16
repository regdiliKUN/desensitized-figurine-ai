"""Integration check against the installed ComfyUI reference encoder.

Run with ComfyUI/venv/Scripts/python.exe; no model weights or GPU inference.
"""
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'ComfyUI'))
import torch
from comfy_extras.nodes_qwen import TextEncodeQwenImageEditPlus
from completion import sampling_size


class VaeProbe:
    def encode(self,image):
        self.size=(image.shape[2],image.shape[1])
        return torch.zeros((1,16,image.shape[1]//8,image.shape[2]//8))


class ClipProbe:
    def tokenize(self,*args,**kwargs): return []
    def encode_from_tokens_scheduled(self,tokens):
        return [[torch.zeros((1,1,1)),{}]]


if __name__=='__main__':
    for source in [(512,388),(512,752),(800,600)]:
        width,height=sampling_size(source,'qwen',.5)
        vae=VaeProbe()
        TextEncodeQwenImageEditPlus.execute(ClipProbe(),'probe',vae,
            image1=torch.zeros((1,height,width,3)))
        assert vae.size==(width,height),(source,vae.size,(width,height))
        print(f'PASS {source}: reference and sample both {width}x{height}')
