FROM ubuntu:22.04

# ── System dependencies ──────────────────────────────────────────────────────
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -o Acquire::Check-Valid-Until=false -o Acquire::Check-Date=false && apt-get install -y --no-install-recommends \
    python3.11 python3.11-dev python3-pip python3.11-venv \
    fonts-dejavu-core \
    curl wget ca-certificates \
    libgomp1 gnupg ocl-icd-libopencl1 && rm -rf /var/lib/apt/lists/*

# Use python3.11 as default python
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

# ── Intel NPU driver packages ───────────────────────────────────────────────
# Install Intel NPU driver and required Level Zero runtime from GitHub releases.
RUN wget -q https://github.com/intel/linux-npu-driver/releases/download/v1.26.0/linux-npu-driver-v1.26.0.20251125-19665715237-ubuntu2204.tar.gz \
    && tar -xf linux-npu-driver-v1.26.0.20251125-19665715237-ubuntu2204.tar.gz \
    && rm linux-npu-driver-v1.26.0.20251125-19665715237-ubuntu2204.tar.gz \
    && apt-get update -o Acquire::Check-Valid-Until=false -o Acquire::Check-Date=false \
    && apt-get install -y --no-install-recommends libtbb12 \
    && dpkg -i *.deb \
    && rm -f *.deb *.deb.asc

# ── Intel GPU driver packages ────────────────────────────────────────────────
# Install Intel GPU compute runtime (OpenCL + Level Zero) for OpenVINO GPU plugin
# Using release 25.13.33276.16 which supports Ubuntu 22.04
RUN wget -q https://github.com/intel/intel-graphics-compiler/releases/download/v2.10.8/intel-igc-core-2_2.10.8+18926_amd64.deb \
    && wget -q https://github.com/intel/intel-graphics-compiler/releases/download/v2.10.8/intel-igc-opencl-2_2.10.8+18926_amd64.deb \
    && wget -q https://github.com/intel/compute-runtime/releases/download/25.13.33276.16/intel-level-zero-gpu_1.6.33276.16_amd64.deb \
    && wget -q https://github.com/intel/compute-runtime/releases/download/25.13.33276.16/intel-opencl-icd_25.13.33276.16_amd64.deb \
    && wget -q https://github.com/intel/compute-runtime/releases/download/25.13.33276.16/libigdgmm12_22.7.0_amd64.deb \
    && dpkg -i *.deb \
    && rm -f *.deb

# Install Level Zero runtime (required by intel-level-zero-npu)
RUN wget -q https://github.com/oneapi-src/level-zero/releases/download/v1.24.2/level-zero_1.24.2+u22.04_amd64.deb \
    && dpkg -i level-zero_1.24.2+u22.04_amd64.deb \
    && rm level-zero_1.24.2+u22.04_amd64.deb \
    && groupadd -f -g 106 render

# ── OpenVINO environment variables ──────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV TOKENIZERS_PARALLELISM=false
ENV ZE_ENABLE_VALIDATION_LAYER=0
ENV SYCL_CACHE_PERSISTENT=1

WORKDIR /app

# ── Python dependencies ──────────────────────────────────────────────────────
# Install specific CPU-only PyTorch version to avoid compatibility issues with transformers
RUN pip install --no-cache-dir torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ─────────────────────────────────────────────────────────
COPY *.py ./
COPY backend/ ./backend/
COPY static/ ./static/

EXPOSE 7860

CMD ["python", "-u", "-m", "backend.main"]