FROM rocm/pytorch:rocm6.2_ubuntu22.04_py3.10_pytorch_release_2.3.0

# Clean apt cache from base image to free space, then install fonts
RUN rm -rf /var/cache/apt/archives/* /var/lib/apt/lists/* && \
    apt-get update && \
    apt-get install -y --no-install-recommends fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# ── ROCm environment for Ryzen AI Max 395 (Strix Halo / gfx1151) ──
ENV HSA_OVERRIDE_GFX_VERSION=11.0.0
ENV HSA_ENABLE_SDMA=0
ENV HSA_XNACK=0
ENV HSA_ENABLE_SCRATCH_QUERIES=0
ENV ROCR_VISIBLE_DEVICES=0
ENV HIP_VISIBLE_DEVICES=0
ENV PYTORCH_HIP_ALLOC_CONF=garbage_collection_threshold:0.8
ENV TOKENIZERS_PARALLELISM=false
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install/Upgrade PyTorch for compatibility with Transformers 4.48+
RUN pip install --no-cache-dir --upgrade torch>=2.5.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2

# Install other Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY *.py ./
COPY static/ ./static/

EXPOSE 7860

CMD ["python", "-u", "server.py"]
