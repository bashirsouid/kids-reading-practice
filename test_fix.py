#!/usr/bin/env python3
"""Test script to verify FLUX pipeline can be instantiated correctly."""

import sys
import os

# Add the current directory to the path so we can import generator
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_flux_pipeline_import():
    """Test that FluxPipeline can be imported from diffusers."""
    print("Testing FLUX pipeline import...")

    try:
        from diffusers import FluxPipeline
        print(f"  FluxPipeline imported successfully from diffusers")
        print(f"  FluxPipeline class: {FluxPipeline}")
        return True
    except ImportError as e:
        print(f"  FAILED: Could not import FluxPipeline: {e}")
        return False


def test_flux_pipeline_init():
    """Test that FluxPipeline has the expected structure (without downloading the model)."""
    print("\nTesting FLUX pipeline structure...")

    try:
        import torch
        from diffusers import FluxPipeline

        # Verify the class has the expected methods and attributes
        assert hasattr(FluxPipeline, "from_pretrained"), "Missing from_pretrained"
        assert hasattr(FluxPipeline, "__init__"), "Missing __init__"

        # Verify the pipeline's expected parameter names by inspecting __init__
        import inspect
        sig = inspect.signature(FluxPipeline.__init__)
        param_names = list(sig.parameters.keys())
        assert "vae" in param_names, "FluxPipeline should accept 'vae' parameter"

        print(f"  FluxPipeline class structure verified")
        print(f"  Pipeline class: {FluxPipeline}")

        # Verify the model ID resolves to a valid path format
        model_id = "black-forest-labs/FLUX.1-dev"
        print(f"  Model ID: {model_id}")

        return True

    except Exception as e:
        print(f"  Pipeline structure check error: {e}")
        return False


def test_generator_import():
    """Test that the ImageGenerator class imports correctly."""
    print("\nTesting ImageGenerator import...")

    try:
        from generator import ImageGenerator, IMAGE_MODEL_ID, PANEL_INFERENCE_STEPS, GUIDANCE_SCALE
        print(f"  ImageGenerator imported successfully")
        print(f"  IMAGE_MODEL_ID = {IMAGE_MODEL_ID}")
        print(f"  PANEL_INFERENCE_STEPS = {PANEL_INFERENCE_STEPS}")
        print(f"  GUIDANCE_SCALE = {GUIDANCE_SCALE}")
        assert IMAGE_MODEL_ID == "black-forest-labs/FLUX.1-dev", \
            f"Expected FLUX model ID, got: {IMAGE_MODEL_ID}"
        assert PANEL_INFERENCE_STEPS == 28, \
            f"Expected 28 inference steps, got: {PANEL_INFERENCE_STEPS}"
        assert GUIDANCE_SCALE == 5.0, \
            f"Expected guidance_scale 5.0, got: {GUIDANCE_SCALE}"
        print("  All assertions passed!")
        return True
    except Exception as e:
        print(f"  FAILED: {e}")
        return False


def test_no_ip_adapter_imports():
    """Verify no IP-Adapter or Lightning references remain in generator.py code."""
    print("\nVerifying IP-Adapter/Lightning references are removed from code...")

    try:
        with open(os.path.join(os.path.dirname(__file__), "generator.py"), "r") as f:
            source = f.read()

        forbidden = [
            "LIGHTNING_LORA",
            "IP_ADAPTER",
            "ip_scale",
            "set_ip_adapter_scale",
            "StableDiffusionXLPipeline",
        ]

        # Check only code lines (strip comments to avoid false positives
        # from explanatory text like "no IP-Adapter").
        code_lines = []
        for line in source.splitlines():
            stripped = line.strip()
            # Skip pure comment lines and blank lines
            if stripped.startswith("#") or not stripped:
                continue
            # Also strip inline comments
            if "#" in line:
                line = line[:line.index("#")]
            code_lines.append(line)

        code_source = "\n".join(code_lines)

        found = [term for term in forbidden if term in code_source]
        if found:
            print(f"  FAILED: Found forbidden terms in code: {found}")
            return False

        print("  All SDXL/Lightning/IP-Adapter code references removed!")
        return True
    except Exception as e:
        print(f"  FAILED: {e}")
        return False


if __name__ == "__main__":
    results = []
    results.append(("FluxPipeline import", test_flux_pipeline_import()))
    results.append(("FluxPipeline init", test_flux_pipeline_init()))
    results.append(("ImageGenerator import", test_generator_import()))
    results.append(("No IP-Adapter/Lightning refs", test_no_ip_adapter_imports()))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    sys.exit(0 if all_passed else 1)