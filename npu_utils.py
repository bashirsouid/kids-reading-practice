"""
npu_utils.py — Intel NPU/iGPU device detection and logging.

Replaces gpu_utils.py (AMD ROCm) for the Intel NPU branch. Enumerates
available OpenVINO devices at startup so the log confirms the NPU and
Arc iGPU are visible before model loading begins.
"""

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("npu-utils")


def log_npu_devices() -> None:
    """Enumerate available OpenVINO devices and log their names.

    Runs at startup (imported by config.py). Non-fatal: if OpenVINO is not
    yet installed or device drivers are missing the warning is logged and
    startup continues — models will fall back to CPU automatically.
    """
    try:
        import openvino as ov
        core = ov.Core()
        devices = core.available_devices
        logger.info("OpenVINO available devices: " + ", ".join(devices) if devices else "none")

        if "NPU" in devices:
            try:
                name = core.get_property("NPU", "FULL_DEVICE_NAME")
                logger.info("Intel NPU: " + str(name))
            except Exception:
                logger.info("Intel NPU detected (name query unavailable).")

        if "GPU" in devices:
            try:
                name = core.get_property("GPU", "FULL_DEVICE_NAME")
                logger.info("Intel GPU: " + str(name))
            except Exception:
                logger.info("Intel GPU detected (name query unavailable).")

        if "CPU" in devices:
            try:
                name = core.get_property("CPU", "FULL_DEVICE_NAME")
                logger.info("CPU fallback available: " + str(name))
            except Exception:
                pass

        if "NPU" not in devices:
            logger.warning(
                "Intel NPU not found in OpenVINO device list. "
                "Ensure the Intel NPU driver is installed "
                "(intel-level-zero-npu or equivalent) and that the device "
                "is enabled in BIOS. Text generation will fall back to CPU."
            )
        if "GPU" not in devices:
            logger.warning(
                "Intel Arc GPU not found in OpenVINO device list. "
                "Ensure Intel GPU drivers are installed. "
                "Image generation will fall back to CPU."
            )

    except ImportError:
        logger.warning(
            "openvino package not found. Install with: "
            "pip install openvino>=2024.5.0  "
            "Device enumeration skipped; models will fall back to CPU."
        )
    except Exception as e:
        logger.warning("Could not enumerate OpenVINO devices: " + str(e))


if __name__ == "__main__":
    log_npu_devices()
