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
# The compositor-killing crash at the first VAE decode is an amdgpu
# ring timeout, not OOM. Primary mitigation now lives in generator.py
# (the VAE is pinned to CPU). These env vars cover the few convs that
# still execute on the GPU (transformer side of the pipeline) so they
# stay on known-good kernels.
#
# FIND_MODE=2 = FAST: skip the autotune/find pass and use heuristics.
ENV MIOPEN_FIND_MODE=2
# Persistent kernel cache behavior
# We disable these to prevent the "Cannot open database file" error and potential hangs
ENV MIOPEN_DEBUG_DISABLE_USERDB=1
ENV MIOPEN_DEBUG_DISABLE_KCACHE=1
# Disable the conv solvers that have historically hung on RDNA3 / gfx1151.
# Direct + Implicit GEMM are the most reliable on this hardware.
ENV MIOPEN_DEBUG_CONV_GEMM=0
ENV MIOPEN_DEBUG_CONV_FFT=0
ENV MIOPEN_DEBUG_CONV_WINOGRAD=0
# Force the Implicit GEMM dynamic kernels to be the primary solver.
ENV MIOPEN_DEBUG_CONV_IMPLICIT_GEMM=1
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
COPY backend/ ./backend/
COPY static/ ./static/

EXPOSE 7860

# Self-healing startup: remove any corrupted directories and then start the server.
CMD ["bash", "-c", "rm -rf /root/.cache/miopen/* && python -u -m backend.main"]
