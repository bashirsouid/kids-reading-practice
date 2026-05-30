#!/usr/bin/env python3
"""Test script to verify Intel NPU branch imports and constants are correct."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_ov_pipeline_import():
    """Test that OVStableDiffusionXLPipeline can be imported from optimum.intel."""
    print("Testing OVStableDiffusionXLPipeline import...")
    try:
        from optimum.intel import OVStableDiffusionXLPipeline
        print("  OVStableDiffusionXLPipeline imported successfully from optimum.intel")
        return True
    except ImportError as e:
        print("  FAILED: Could not import OVStableDiffusionXLPipeline: " + str(e))
        return False


def test_ov_lm_import():
    """Test that OVModelForCausalLM can be imported from optimum.intel."""
    print("\nTesting OVModelForCausalLM import...")
    try:
        from optimum.intel import OVModelForCausalLM
        print("  OVModelForCausalLM imported successfully from optimum.intel")
        return True
    except ImportError as e:
        print("  FAILED: Could not import OVModelForCausalLM: " + str(e))
        return False


def test_generator_constants():
    """Test that the Intel NPU branch has the expected model IDs and constants."""
    print("\nTesting generator constants for Intel NPU branch...")
    try:
        from generator import (
            ImageGenerator,
            TextGenerator,
            IMAGE_MODEL_ID,
            TEXT_MODEL_ID,
            PANEL_INFERENCE_STEPS,
            GUIDANCE_SCALE,
            NPU_DEVICE,
            IMAGE_DEVICE,
            PANEL_GEN_SIZE,
        )
        print("  IMAGE_MODEL_ID = " + IMAGE_MODEL_ID)
        print("  TEXT_MODEL_ID = " + TEXT_MODEL_ID)
        print("  PANEL_INFERENCE_STEPS = " + str(PANEL_INFERENCE_STEPS))
        print("  GUIDANCE_SCALE = " + str(GUIDANCE_SCALE))
        print("  NPU_DEVICE = " + NPU_DEVICE)
        print("  IMAGE_DEVICE = " + IMAGE_DEVICE)
        print("  PANEL_GEN_SIZE = " + str(PANEL_GEN_SIZE))

        assert "sdxl-turbo" in IMAGE_MODEL_ID.lower() or "sdxl" in IMAGE_MODEL_ID.lower(), \
            "Expected SDXL-Turbo image model, got: " + IMAGE_MODEL_ID
        assert PANEL_INFERENCE_STEPS <= 8, \
            "Expected <=8 steps for fast inference on NPU branch, got: " + str(PANEL_INFERENCE_STEPS)
        assert GUIDANCE_SCALE == 0.0, \
            "Expected guidance_scale=0.0 for SDXL-Turbo, got: " + str(GUIDANCE_SCALE)
        assert PANEL_GEN_SIZE <= 512, \
            "Expected PANEL_GEN_SIZE<=512 for SDXL-Turbo, got: " + str(PANEL_GEN_SIZE)
        print("  All assertions passed!")
        return True
    except Exception as e:
        print("  FAILED: " + str(e))
        return False


def test_no_cuda_rocm_in_code():
    """Verify no CUDA/ROCm imports remain in generator.py code paths."""
    print("\nVerifying no CUDA/ROCm code paths remain in generator.py...")
    try:
        with open(os.path.join(os.path.dirname(__file__), "generator.py"), "r") as f:
            source = f.read()

        # Strip comments before checking — allow references in docstrings/comments
        code_lines = []
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if "#" in line:
                line = line[:line.index("#")]
            code_lines.append(line)
        code_source = "\n".join(code_lines)

        forbidden = [
            "torch.cuda",
            "DEVICE = \"cuda\"",
            ".to(DEVICE)",
            "torch_dtype=DTYPE",
            "FluxPipeline",
            "FluxImg2ImgPipeline",
            "FluxPriorReduxPipeline",
            "HSA_CU_MASK",
            "rocminfo",
        ]

        found = [term for term in forbidden if term in code_source]
        if found:
            print("  FAILED: Found forbidden terms in code: " + str(found))
            return False

        print("  No CUDA/ROCm/FLUX code paths found — clean Intel NPU branch!")
        return True
    except Exception as e:
        print("  FAILED: " + str(e))
        return False


def test_npu_utils_import():
    """Test that npu_utils can be imported."""
    print("\nTesting npu_utils import...")
    try:
        from npu_utils import log_npu_devices
        print("  npu_utils.log_npu_devices imported successfully")
        return True
    except ImportError as e:
        print("  FAILED: " + str(e))
        return False


if __name__ == "__main__":
    results = []
    results.append(("OVStableDiffusionXLPipeline import", test_ov_pipeline_import()))
    results.append(("OVModelForCausalLM import", test_ov_lm_import()))
    results.append(("Generator constants (Intel NPU)", test_generator_constants()))
    results.append(("No CUDA/ROCm in code", test_no_cuda_rocm_in_code()))
    results.append(("npu_utils import", test_npu_utils_import()))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print("  " + name + ": " + status)
        if not passed:
            all_passed = False

    sys.exit(0 if all_passed else 1)
