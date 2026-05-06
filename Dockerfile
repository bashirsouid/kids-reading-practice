FROM rocm/pytorch:rocm6.2_ubuntu22.04_py3.10_pytorch_release_2.3.0

# Clean apt cache from base image to free space, then install fonts
RUN rm -rf /var/cache/apt/archives/* /var/lib/apt/lists/* && \
    apt-get update && \
    apt-get install -y --no-install-recommends fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# ── ROCm environment for Ryzen AI Max 395 (Strix Halo / gfx1151) ──
ENV HSA_OVERRIDE_GFX_VERSION=11.0.0
ENV HSA_ENABLE_SDMA=0
ENV HSA_XNACK=1
ENV HSA_ENABLE_SCRATCH_QUERIES=0
ENV ROCR_VISIBLE_DEVICES=0
ENV HIP_VISIBLE_DEVICES=0
ENV PYTORCH_HIP_ALLOC_CONF=expandable_segments:True,garbage_collection_threshold:0.6

# ── MIOpen behavior on gfx1151 ─────────────────────────────────────────
# The compositor-killing crash at the first VAE decode looks like an
# amdgpu ring timeout, not OOM. The most common trigger on gfx1151 is
# MIOpen autotuning a novel conv shape: the solver search picks an
# implementation that hangs the device instead of returning an error,
# and the watchdog resets the GPU (taking every GPU client with it).
#
# FIND_MODE=2 = FAST: skip the autotune/find pass and use heuristics.
# We trade a little per-shape perf for not hanging on the first call.
ENV MIOPEN_FIND_MODE=2
# Persistent kernel cache behavior
# We disable these to prevent the "Cannot open database file" error and potential hangs
ENV MIOPEN_DEBUG_DISABLE_USERDB=1
ENV MIOPEN_DEBUG_DISABLE_KCACHE=1
# Workaround for GEMM-based convolution hangs/errors on RDNA3
ENV MIOPEN_DEBUG_CONV_GEMM=0
RUN mkdir -p /root/.cache/miopen && chmod -R 777 /root/.cache/miopen
# Verbose AMD logging — useful while we're still narrowing this down.
# Drop to 1 or remove once stable.
ENV AMD_LOG_LEVEL=2
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

# Self-healing startup: remove any corrupted directories and then start the server.
CMD ["bash", "-c", "rm -rf /root/.cache/miopen/* && python -u server.py"]
