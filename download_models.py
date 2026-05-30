"""
download_models.py — Pre-download HuggingFace models for the Intel NPU branch.

Run this before first launch to cache the model weights. On first use,
generator.py will export them to OpenVINO IR format automatically
(stored in .cache/ov_models/).
"""

import os
from huggingface_hub import snapshot_download


def download_models():
    models = [
        # Text generation: Qwen2.5-3B-Instruct (exported to OV INT4 for NPU)
        "Qwen/Qwen2.5-3B-Instruct",
        # Image generation: SDXL-Turbo (exported to OV for Intel Arc iGPU)
        "stabilityai/sdxl-turbo",
    ]

    token = os.environ.get("HF_TOKEN")

    for model_id in models:
        print("\n" + "=" * 60)
        print("PRE-DOWNLOADING MODEL: " + model_id)
        print("=" * 60)

        try:
            snapshot_download(
                repo_id=model_id,
                token=token,
                resume_download=True,
            )
            print("\nSUCCESS: " + model_id + " is fully downloaded and cached.")
        except Exception as e:
            print("\nERROR downloading " + model_id + ": " + str(e))


if __name__ == "__main__":
    download_models()
