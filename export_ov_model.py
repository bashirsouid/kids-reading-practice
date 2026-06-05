#!/usr/bin/env python3
"""
export_ov_model.py — Export SDXL-Turbo to OpenVINO IR format for GPU.

This script:
1. Downloads the SDXL-Turbo model if not cached
2. Exports it to OpenVINO IR format (without device parameter for export)
3. Recompiles it for the target GPU device
4. Saves the compiled model to cache for reuse

Run this in the container at startup once, then subsequent starts will reuse.
"""

import os
import sys
from pathlib import Path

# Set up paths - use the same cache directory as generator.py
OV_CACHE_DIR = Path(__file__).parent / ".cache" / "ov_models"
OV_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Use the same model ID as in generator.py
IMAGE_MODEL_ID = os.getenv("IMAGE_MODEL_ID", "stabilityai/sdxl-turbo")
IMAGE_DEVICE = os.getenv("IMAGE_DEVICE", "GPU").upper()

print("=" * 60)
print("Exporting SDXL-Turbo to OpenVINO IR for Intel Arc iGPU")
print("=" * 60)
print(f"Model ID: {IMAGE_MODEL_ID}")
print(f"Cache directory: {OV_CACHE_DIR}")
print(f"Target device: {IMAGE_DEVICE}")
print()

# Load the model with OpenVINO export
from optimum.intel import OVStableDiffusionXLPipeline
import openvino as ov

core = ov.Core()
print(f"Available OpenVINO devices: {core.available_devices}")

ov_config = {"PERFORMANCE_HINT": "LATENCY", "CACHE_DIR": str(OV_CACHE_DIR)}

print("Loading model and exporting to OpenVINO IR...")
pipe = OVStableDiffusionXLPipeline.from_pretrained(
    IMAGE_MODEL_ID,
    export=True,
    ov_config=ov_config,
)

print(f"Exported model loaded. Recompiling for {IMAGE_DEVICE}...")

# Recompile all submodels for the target device
for submodel_name in pipe._ov_submodel_names:
    submodel = getattr(pipe, submodel_name)
    if hasattr(submodel, '_compile_model'):
        submodel._compile_model(device=IMAGE_DEVICE, ov_config=ov_config)

print("Model compiled for GPU successfully!")

# Save the compiled model
output_dir = OV_CACHE_DIR / IMAGE_MODEL_ID.replace("/", "--")
print(f"Saving compiled model to {output_dir}...")
pipe.save_pretrained(str(output_dir))

print()
print("=" * 60)
print("SUCCESS: Model exported and compiled for OpenVINO GPU")
print("=" * 60)

# List exported files
print("\nExported files:")
for f in sorted(output_dir.rglob("*")):
    if f.is_file() and f.suffix in ['.xml', '.bin']:
        size_mb = f.stat().st_size / 1024 / 1024
        print(f"  {f.relative_to(output_dir)} ({size_mb:.1f} MB)")