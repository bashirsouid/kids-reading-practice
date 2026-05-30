FROM ubuntu:22.04

# ── System dependencies ──────────────────────────────────────────────────────
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-dev python3-pip python3.11-venv \
    fonts-dejavu-core \
    curl wget ca-certificates \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Use python3.11 as default python
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

# ── Intel NPU / GPU driver packages ─────────────────────────────────────────
# These packages provide the user-space drivers required by OpenVINO to see
# the Intel NPU and Intel Arc iGPU devices inside the container.
# They are installed from Intel's official APT repository.
RUN wget -qO- https://apt.repos.intel.com/intel-gpg-keys/GPG-PUB-KEY-INTEL-SW-PRODUCTS.PUB \
    | gpg --dearmor -o /usr/share/keyrings/intel-sw-products.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/intel-sw-products.gpg] https://apt.repos.intel.com/openvino/2025 ubuntu22 main" \
    > /etc/apt/sources.list.d/intel-openvino-2025.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    intel-level-zero-npu \
    libze-intel-gpu1 \
    intel-opencl-icd \
    && rm -rf /var/lib/apt/lists/*

# ── OpenVINO environment variables ──────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV TOKENIZERS_PARALLELISM=false
# Disable Intel GPU HW metrics that need additional perms inside containers
ENV ZE_ENABLE_VALIDATION_LAYER=0
ENV SYCL_CACHE_PERSISTENT=1

WORKDIR /app

# ── Python dependencies ──────────────────────────────────────────────────────
# Install CPU-only PyTorch first (avoids pulling CUDA wheels)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ─────────────────────────────────────────────────────────
COPY *.py ./
COPY backend/ ./backend/
COPY static/ ./static/

EXPOSE 7860

CMD ["python", "-u", "-m", "backend.main"]
