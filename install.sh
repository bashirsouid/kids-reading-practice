#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║        AI Comic Generator — Installer            ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Python Detection ─────────────────────────────────────────────────────────
PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" -c "import sys; print(sys.version_info[:2])" 2>/dev/null)
        major=$("$candidate" -c "import sys; print(sys.version_info[0])")
        minor=$("$candidate" -c "import sys; print(sys.version_info[1])")
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$candidate"
            echo "✓ Python: $candidate ($major.$minor)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "✗ ERROR: Python 3.10+ required. Install with:"
    echo "  sudo apt install python3.12 python3.12-venv"
    exit 1
fi

# ── Virtual Environment ───────────────────────────────────────────────────────
VENV_DIR="$SCRIPT_DIR/.venv"
if [ -d "$VENV_DIR" ]; then
    echo "✓ venv already exists at .venv/"
    if ! "$VENV_DIR/bin/python" -c "import torch" 2>/dev/null; then
        echo "  (packages not installed yet, continuing...)"
    fi
else
    echo "→ Creating virtual environment at .venv/ ..."
    "$PYTHON" -m venv "$VENV_DIR"
    echo "✓ venv created"
fi

PIP="$VENV_DIR/bin/pip"
VENV_PYTHON="$VENV_DIR/bin/python"

echo ""
echo "→ Upgrading pip/setuptools/wheel..."
"$PIP" install --quiet --upgrade pip setuptools wheel

# ── GPU Detection ─────────────────────────────────────────────────────────────
GPU_TYPE="cpu"
STRIX_HALO=false
ROCM_VERSION=""

echo ""
echo "── GPU Detection ────────────────────────────────────"

if command -v nvidia-smi &>/dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "Unknown")
    echo "✓ NVIDIA GPU detected: $GPU_NAME"
    GPU_TYPE="cuda"
elif command -v rocminfo &>/dev/null; then
    ROCM_OUT=$(rocminfo 2>/dev/null || echo "")
    echo "✓ ROCm detected"
    if echo "$ROCM_OUT" | grep -qi "gfx1151\|strix halo\|radeon 395"; then
        echo "✓ Ryzen AI Max 395 (Strix Halo / gfx1151) detected!"
        STRIX_HALO=true
        GPU_TYPE="rocm"
        # Detect ROCm version
        if command -v rocminfo &>/dev/null; then
            ROCM_VERSION=$(rocminfo 2>/dev/null | grep -i "ROCm" | head -1 | grep -oP '\d+\.\d+' | head -1 || echo "")
        fi
        echo "  ROCm version: ${ROCM_VERSION:-unknown}"
    else
        GPU_TYPE="rocm"
    fi
else
    echo "  No GPU detected — using CPU (generation will be slow)"
fi

# ── PyTorch Installation ───────────────────────────────────────────────────────
echo ""
echo "── Installing PyTorch ───────────────────────────────"

if "$VENV_PYTHON" -c "import torch; print('torch', torch.__version__)" 2>/dev/null; then
    echo "  PyTorch already installed, skipping."
else
    if [ "$GPU_TYPE" = "cuda" ]; then
        echo "→ Installing PyTorch with CUDA 12.4..."
        "$PIP" install --quiet torch torchvision torchaudio \
            --index-url https://download.pytorch.org/whl/cu124
    elif [ "$GPU_TYPE" = "rocm" ]; then
        if [ "$STRIX_HALO" = true ]; then
            echo "→ Installing PyTorch ROCm nightly (gfx1151/Strix Halo support)..."
            # Try nightly first for gfx1151
            "$PIP" install --quiet --pre torch torchvision torchaudio \
                --index-url https://download.pytorch.org/whl/nightly/rocm6.3 || {
                echo "  Nightly failed, trying rocm6.2..."
                "$PIP" install --quiet torch torchvision torchaudio \
                    --index-url https://download.pytorch.org/whl/rocm6.2
            }
        else
            echo "→ Installing PyTorch with ROCm 6.2..."
            "$PIP" install --quiet torch torchvision torchaudio \
                --index-url https://download.pytorch.org/whl/rocm6.2
        fi
    else
        echo "→ Installing PyTorch (CPU only)..."
        "$PIP" install --quiet torch torchvision torchaudio \
            --index-url https://download.pytorch.org/whl/cpu
    fi
    echo "✓ PyTorch installed"
fi

# ── Core Dependencies ──────────────────────────────────────────────────────────
echo ""
echo "── Installing Python packages ───────────────────────"
"$PIP" install --quiet \
    "diffusers>=0.31.0" \
    "transformers>=4.45.0" \
    "accelerate>=0.30.0" \
    "safetensors>=0.4.0" \
    "huggingface_hub>=0.24.0" \
    "Pillow>=10.0.0" \
    "rich>=13.0.0" \
    "sentencepiece" \
    "protobuf"
echo "✓ Core packages installed"

# ── Verify Imports ─────────────────────────────────────────────────────────────
echo ""
echo "── Verifying imports ────────────────────────────────"
FAILED=0
for pkg in torch diffusers transformers accelerate PIL rich; do
    if "$VENV_PYTHON" -c "import $pkg" 2>/dev/null; then
        VER=$("$VENV_PYTHON" -c "import $pkg; print(getattr($pkg, '__version__', 'ok'))" 2>/dev/null || echo "ok")
        echo "  ✓ $pkg ($VER)"
    else
        echo "  ✗ $pkg FAILED"
        FAILED=$((FAILED+1))
    fi
done
if [ $FAILED -gt 0 ]; then
    echo ""
    echo "WARNING: $FAILED import(s) failed. Run again or check errors above."
fi

# ── FluxKontext check ──────────────────────────────────────────────────────────
if "$VENV_PYTHON" -c "from diffusers import FluxKontextPipeline" 2>/dev/null; then
    echo "  ✓ FluxKontextPipeline available"
else
    DIFFUSERS_VER=$("$VENV_PYTHON" -c "import diffusers; print(diffusers.__version__)" 2>/dev/null || echo "?")
    echo "  ⚠ FluxKontextPipeline not found (diffusers=$DIFFUSERS_VER)"
    echo "    Will fall back to standard FluxPipeline (no reference editing)"
    echo "    To enable: pip install 'diffusers>=0.32.0' --upgrade"
fi

# ── HuggingFace Cache ──────────────────────────────────────────────────────────
echo ""
echo "── HuggingFace Cache ────────────────────────────────"
HF_CACHE="${HF_HOME:-$HOME/.cache/huggingface/hub}"
echo "  Cache location: $HF_CACHE"
if [ -d "$HF_CACHE" ]; then
    for model_slug in "models--black-forest-labs--FLUX.1-kontext-dev" \
                      "models--black-forest-labs--FLUX.1-dev" \
                      "models--black-forest-labs--FLUX.1-schnell" \
                      "models--Qwen--Qwen2.5-1.5B-Instruct" \
                      "models--Qwen--Qwen2.5-3B-Instruct"; do
        model_path="$HF_CACHE/$model_slug"
        if [ -d "$model_path" ]; then
            SIZE=$(du -sh "$model_path" 2>/dev/null | cut -f1 || echo "?")
            DISPLAY=$(echo "$model_slug" | sed 's/models--//;s/--/\//g')
            echo "  ✓ Cached: $DISPLAY ($SIZE)"
        fi
    done
else
    echo "  (No HF cache found — models will be downloaded on first run)"
fi

if [ -z "${HF_TOKEN:-}" ] && [ ! -f "$HOME/.cache/huggingface/token" ]; then
    echo ""
    echo "  ⚠ No HuggingFace token found."
    echo "    FLUX.1-dev and FLUX.1-kontext-dev require accepting a license."
    echo "    Run: huggingface-cli login"
    echo "    Or:  export HF_TOKEN=your_token_here"
fi

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  Installation complete!                          ║"
echo "║  Run: ./run.sh                                   ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
