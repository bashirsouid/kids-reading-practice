# 📚 AI Comic Book Generator for Kids — Intel NPU Branch

An AI-powered comic book generator that creates engaging 6-panel reading practice materials for children. This branch (`intel-npu`) ports all AI inference to the **Intel NPU and Intel Arc iGPU** using **OpenVINO**, targeting the **Lenovo X1 Carbon Gen 13** (Intel Core Ultra 200V / Lunar Lake).

> **Platform branch**: This is the `intel-npu` branch. The `main` branch targets AMD Strix Halo (ROCm). See the [branch comparison](#branch-comparison) section for differences.

![Example Comic](examples/Penguin_s_Dance_94f7980d.png)

---

## Hardware Target

| Component | Spec |
|---|---|
| **Machine** | Lenovo X1 Carbon Gen 13 |
| **CPU** | Intel Core Ultra 200V (Lunar Lake) |
| **NPU** | Intel NPU 4 — ~48 TOPS |
| **iGPU** | Intel Arc 140V |
| **RAM** | 16–32 GB LPDDR5x (shared with iGPU) |

---

## AI Model Changes (vs main branch)

| | `main` (AMD ROCm) | `intel-npu` (this branch) |
|---|---|---|
| **Text model** | Qwen2.5-3B-Instruct via PyTorch on CUDA | Qwen2.5-3B-Instruct via **OVModelForCausalLM** on **Intel NPU** (INT4) |
| **Image model** | FLUX.1-dev (28 steps) on AMD GPU | **SDXL-Turbo** (4 steps) via **OVStableDiffusionXLPipeline** on **Intel Arc iGPU** |
| **Inference backend** | PyTorch + ROCm | **OpenVINO** (no CUDA/ROCm) |
| **Image consistency** | FLUX-Redux SigLIP prior | Prompt-anchored + deterministic seeding |

### Why SDXL-Turbo instead of FLUX.1-dev?

FLUX.1-dev requires 28 inference steps and ~23 GB in FP16. On a laptop iGPU with shared system memory this is impractical. SDXL-Turbo uses adversarial diffusion distillation (ADD) to produce high-quality images in **1–4 steps** with `guidance_scale=0`, making it a natural fit for battery-powered mobile hardware.

The INT4-quantized Qwen2.5-3B-Instruct model on the NPU generates story text in roughly the same latency as the GPU-based version on the main branch, thanks to the NPU's 48 TOPS throughput on transformer workloads.

---

## 🚀 Features

- **Automated Storytelling**: Generates 6-panel stories with age-appropriate vocabulary using **Qwen2.5-3B-Instruct on Intel NPU**.
- **Fast Illustrations**: Produces vibrant panel art in 4 steps using **SDXL-Turbo on Intel Arc iGPU**.
- **Zero CUDA/ROCm**: Pure **OpenVINO** inference — works on any Intel AI PC.
- **Compiled Model Cache**: OpenVINO compiles models for your device on first run and caches them — subsequent starts are instant.
- **Device Fallback**: Both models automatically fall back to CPU if NPU/GPU drivers are missing.
- **Interactive UI**: Web interface for previewing, regenerating, and exporting comics.

---

## 🛠️ Technology Stack

- **Backend**: FastAPI (Python 3.11)
- **Text inference**: [optimum-intel](https://github.com/huggingface/optimum-intel) `OVModelForCausalLM` on Intel NPU
- **Image inference**: [optimum-intel](https://github.com/huggingface/optimum-intel) `OVStableDiffusionXLPipeline` on Intel Arc iGPU
- **OpenVINO runtime**: 2024.5+
- **Frontend**: React 19 + Vite + Tailwind CSS

---

## 📁 Project Structure

```
.
├── backend/
│   ├── main.py           # FastAPI application entry point
│   ├── config.py         # Configuration constants and paths
│   ├── models.py         # Pydantic models and dataclasses
│   ├── state.py          # Global state (jobs, queues, websockets)
│   ├── persistence.py    # Job save/load and image persistence
│   ├── broadcasting.py   # WebSocket and progress broadcasting
│   ├── jobs.py           # Job processing worker
│   ├── utils.py          # Helper utilities
│   └── api/routes.py     # All API route handlers
├── frontend/             # React/Vite frontend application
├── generator.py          # AI generation (OpenVINO text + image)
├── npu_utils.py          # Intel NPU/iGPU device detection
├── download_models.py    # Pre-download HuggingFace weights
├── requirements.txt      # Python dependencies (OpenVINO stack)
├── Dockerfile            # Ubuntu 22.04 + Intel GPU drivers + OpenVINO
└── docker-compose.yml    # Intel device passthrough (NPU + Arc iGPU)
```

---

## 📦 Getting Started

### Prerequisites

- Linux OS (Ubuntu 22.04+ recommended) or Windows 11 with WSL2
- Intel Core Ultra 200 series (Lunar Lake) or similar Intel AI PC
- Intel NPU driver: [`intel-level-zero-npu`](https://github.com/intel/linux-npu-driver/releases)
- Intel GPU driver: Mesa / Intel compute runtime (`intel-opencl-icd`, `libze-intel-gpu1`)
- Docker & Docker Compose (for containerized setup)

### 1. Install Intel NPU and GPU drivers (host)

```bash
# Add Intel repository
wget -qO- https://apt.repos.intel.com/intel-gpg-keys/GPG-PUB-KEY-INTEL-SW-PRODUCTS.PUB \
  | sudo gpg --dearmor -o /usr/share/keyrings/intel-sw-products.gpg
echo "deb [signed-by=/usr/share/keyrings/intel-sw-products.gpg] https://apt.repos.intel.com/openvino/2025 ubuntu22 main" \
  | sudo tee /etc/apt/sources.list.d/intel-openvino-2025.list

sudo apt-get update
sudo apt-get install -y intel-level-zero-npu libze-intel-gpu1 intel-opencl-icd

# Add your user to render group for GPU access
sudo usermod -aG render,video $USER
# Log out and back in, then verify:
ls /dev/dri/renderD*   # should show renderD128 or similar
ls /dev/accel/         # should show accel0 for NPU
```

### 2. Clone and launch with Docker

```bash
git clone https://github.com/bashirsouid/kids-reading-practice.git
cd kids-reading-practice
git checkout intel-npu

# Set your HuggingFace token (needed for gated models)
export HF_TOKEN=your_token_here

docker compose up --build
```

### 3. Running locally (without Docker)

```bash
# Install PyTorch CPU-only first (avoids pulling CUDA wheels)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# Install remaining dependencies
pip install -r requirements.txt

# (Optional) Pre-download model weights
python download_models.py

# Start server
python -m backend.main
# or: uvicorn backend.main:app --host 0.0.0.0 --port 7860
```

Open `http://localhost:7860` in your browser.

---

## ⚙️ Configuration

All settings are controlled via environment variables:

| Variable | Default | Description |
|---|---|---|
| `NPU_DEVICE` | `NPU` | OpenVINO device for text model. Set to `CPU` to force CPU. |
| `IMAGE_DEVICE` | `GPU` | OpenVINO device for image model. Set to `CPU` to force CPU. |
| `OV_CACHE_DIR` | `.cache/ov_models` | Where compiled OpenVINO models are cached. |
| `TEXT_MODEL_ID` | `Qwen/Qwen2.5-3B-Instruct` | HuggingFace model ID for text generation. |
| `IMAGE_MODEL_ID` | `stabilityai/sdxl-turbo` | HuggingFace model ID for image generation. |
| `PANEL_INFERENCE_STEPS` | `4` | Diffusion steps per panel (1–8 for SDXL-Turbo). |
| `HF_TOKEN` | _(empty)_ | HuggingFace token for downloading gated models. |

### First-run model export

On the very first launch, `generator.py` will:
1. Download the HuggingFace weights (or use the local cache if pre-downloaded).
2. Export them to **OpenVINO IR format** via `optimum-intel`.
3. Compile the IR for your target device (NPU / GPU / CPU).
4. Cache the compiled blobs in `OV_CACHE_DIR`.

This one-time export takes 5–15 minutes for the text model and 10–20 minutes for the image model. After that, startup takes only a few seconds.

---

## 📖 How It Works

1. **Idea → Script**: You provide a theme (e.g., "A penguin learning to dance").
2. **LLM on NPU**: Qwen2.5-3B-Instruct (INT4, OpenVINO) generates a 6-panel script with character descriptions, art style, and narrative captions — running on the Intel NPU.
3. **Image on Arc iGPU**: SDXL-Turbo (OpenVINO) generates each panel in 4 steps using detailed text prompts that include character descriptions for visual consistency — running on the Intel Arc iGPU.
4. **Assembly**: Panels are composited into an 8.5×11″ comic page at 300 DPI, ready for printing or PDF export.

---

## Branch Comparison

| Feature | `main` | `intel-npu` |
|---|---|---|
| Hardware | AMD Strix Halo (Ryzen AI Max 395) | Intel Core Ultra 200V (X1 Carbon Gen 13) |
| GPU framework | AMD ROCm / PyTorch | Intel OpenVINO |
| Text model device | CUDA GPU | Intel NPU (INT4) |
| Image model | FLUX.1-dev (28 steps) | SDXL-Turbo (4 steps) |
| Image device | CUDA GPU | Intel Arc iGPU |
| VAE CPU patch | Yes (AMD gfx1151 stability) | Not needed |
| Character consistency | FLUX-Redux + img2img | Prompt engineering + seeds |
| Docker base image | `rocm/pytorch:rocm6.2` | `ubuntu:22.04` + Intel GPU drivers |

---

## 🤝 Contributing

Contributions welcome! If you have an Intel AI PC and run this successfully (or find issues), please open an issue with your hardware/driver versions.

---

*Created for the love of reading and the power of AI.*
