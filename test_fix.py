#!/usr/bin/env python3
"""Test script to verify the tensor size fix"""

import torch
import sys
import os

# Add the current directory to the path so we can import generator
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_tensor_slicing():
    """Test our fix for tensor slicing"""
    # Simulate the shapes from the error
    # Error said: The size of tensor a (32) must match the size of tensor b (128) at non-singleton dimension 1
    # This suggests init_latents had shape [..., 32, ...] but bn_mean/bn_std had shape [..., 128, ...]
    
    print("Testing tensor slicing fix...")
    
    # Simulate init_latents with 32 channels (the smaller dimension from error)
    init_latents = torch.randn(1, 32, 16, 16)  # batch, channels, height, width
    
    # Simulate bn running stats with 128 channels (the larger dimension from error)
    fake_bn_mean = torch.randn(128)
    fake_bn_var = torch.randn(128).abs() + 1  # variance must be positive
    
    print(f"init_latents shape: {init_latents.shape}")
    print(f"bn_mean shape: {fake_bn_mean.shape}")
    print(f"bn_var shape: {fake_bn_var.shape}")
    
    # Original code (would fail):
    try:
        bn_mean_orig = fake_bn_mean.view(1, -1, 1, 1)
        bn_std_orig = torch.sqrt(fake_bn_var.view(1, -1, 1, 1) + 1e-5)
        result_orig = (init_latents - bn_mean_orig) / bn_std_orig
        print("Original code: Unexpectedly succeeded!")
    except RuntimeError as e:
        print(f"Original code failed as expected: {str(e)[:100]}...")
    
    # Fixed code:
    try:
        bn_mean_fixed = fake_bn_mean[:init_latents.shape[1]].view(1, -1, 1, 1)
        bn_std_fixed = torch.sqrt(fake_bn_var[:init_latents.shape[1]].view(1, -1, 1, 1) + 1e-5)
        result_fixed = (init_latents - bn_mean_fixed) / bn_std_fixed
        print(f"Fixed code succeeded! Result shape: {result_fixed.shape}")
        print("Fix verified!")
        return True
    except Exception as e:
        print(f"Fixed code failed: {e}")
        return False

if __name__ == "__main__":
    success = test_tensor_slicing()
    sys.exit(0 if success else 1)