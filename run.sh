#!/usr/bin/env bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  run.sh — Kids Comic Book Generator launcher
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
MAIN_SCRIPT="$SCRIPT_DIR/comic_generator.py"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()  { echo -e "${CYAN}${BOLD}[INFO]${RESET}  $*"; }
error() { echo -e "${RED}${BOLD}[ERR ]${RESET}  $*"; exit 1; }
warn()  { echo -e "${YELLOW}${BOLD}[WARN]${RESET}  $*"; }

# ── Sanity checks ─────────────────────────────────────────────────────────────
[[ -f "$MAIN_SCRIPT" ]] || error "comic_generator.py not found in $SCRIPT_DIR"

if [[ ! -d "$VENV_DIR" ]]; then
    error "Virtual environment not found. Run ./install.sh first."
fi

PYTHON="$VENV_DIR/bin/python"
[[ -x "$PYTHON" ]] || error "Python not found in venv. Re-run ./install.sh"

# ── Environment setup ─────────────────────────────────────────────────────────

export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
export TOKENIZERS_PARALLELISM=false
export TORCH_DTYPE="bfloat16"

# Add ROCm to PATH if present
if [[ -d "/opt/rocm/bin" ]]; then
    export PATH="/opt/rocm/bin:$PATH"
fi

# ── GPU detection & platform-specific tuning ──────────────────────────────────
IS_AMD=false
IS_STRIX_HALO=false
VRAM_MB=0

if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
    VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null \
              | head -1 | tr -d ' ')
    GPU=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    info "NVIDIA GPU: ${GPU} — ${VRAM_MB} MiB"
    export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"

elif command -v rocminfo &>/dev/null; then
    IS_AMD=true
    GPU=$(rocminfo 2>/dev/null | grep -m1 "Marketing Name" | sed 's/.*: *//')

    # Detect Strix Halo by gfx arch or product name
    if rocminfo 2>/dev/null | grep -qi "gfx1151\|8060s\|strix halo\|radeon 8060"; then
        IS_STRIX_HALO=true
        info "AMD Strix Halo detected (Ryzen AI Max 395)"
        # AoTriton generates fused kernels for diffusion — ~2x faster on RDNA 3.5 [web:46]
        # export TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1
        # info "AoTriton experimental kernels enabled"
    else
        info "AMD ROCm GPU: ${GPU}"
    fi

    # HIP memory allocator (ROCm equivalent of PYTORCH_CUDA_ALLOC_CONF)
    export PYTORCH_HIP_ALLOC_CONF="expandable_segments:True,garbage_collection_threshold:0.8"

    if [[ "$IS_STRIX_HALO" == "true" ]]; then
        # Disable SDMA engine — can stall on APUs with unified memory
        export HSA_ENABLE_SDMA=0
        export HSA_XNACK=0
        export ROCR_VISIBLE_DEVICES=0
        export HIP_VISIBLE_DEVICES=0

        # Even if ROCm supports gfx1151, Torch often lacks the kernels.
        # Spoofing as gfx1100 (11.0.0) ensures Torch uses compatible RDNA3 kernels.
        info "Setting HSA_OVERRIDE_GFX_VERSION=11.0.0 for Torch compatibility"
        export HSA_OVERRIDE_GFX_VERSION="11.0.0"
    fi

    # Report VRAM via rocm-smi
    VRAM_MB=$(rocm-smi --showmeminfo vram 2>/dev/null \
              | awk '/Total/{print $NF; exit}' || echo 0)

else
    warn "No GPU detected — running on CPU (very slow)"
fi

# ── VRAM report ────────────────────────────────────────────────────────────────
if (( VRAM_MB > 0 )) 2>/dev/null; then
    VRAM_GB=$(awk "BEGIN {printf \"%.1f\", $VRAM_MB/1024}")
    info "VRAM: ${VRAM_GB} GB"
    if (( VRAM_MB >= 40960 )); then
        info "✓ Ample VRAM — both models held in GPU memory simultaneously"
    elif (( VRAM_MB >= 16384 )); then
        info "Model CPU offload will be used between generations"
    else
        warn "Low VRAM — sequential CPU offload active (slower)"
    fi
fi

# ── Parse optional CLI flags ──────────────────────────────────────────────────
EXTRA_ARGS=()
OUTPUT_DIR="$SCRIPT_DIR"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir|-o)
            OUTPUT_DIR="$2"
            mkdir -p "$OUTPUT_DIR"
            shift 2
            ;;
        --hf-home)
            export HF_HOME="$2"
            shift 2
            ;;
        --cpu)
            export CUDA_VISIBLE_DEVICES=""
            warn "Forcing CPU mode via --cpu flag"
            shift
            ;;
        --help|-h)
            echo ""
            echo -e "${BOLD}Usage:${RESET} ./run.sh [options]"
            echo ""
            echo "Options:"
            echo "  -o, --output-dir DIR    Directory to save comic output (default: .)"
            echo "      --hf-home DIR       Override HuggingFace cache directory"
            echo "      --cpu               Force CPU-only mode (disables GPU)"
            echo "  -h, --help              Show this help"
            echo ""
            exit 0
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

# ── Launch ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}  ╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}  ║   🎨  Kids Comic Book Generator              ║${RESET}"
echo -e "${BOLD}${CYAN}  ╚══════════════════════════════════════════════╝${RESET}"
echo ""
info "Python:     $($PYTHON --version)"
info "Platform:   $([[ "$IS_STRIX_HALO" == "true" ]] && echo "AMD Strix Halo (Ryzen AI Max 395)" || echo "standard")"
info "HF cache:   $HF_HOME"
info "Output dir: $OUTPUT_DIR"
echo ""

cd "$OUTPUT_DIR"
exec "$PYTHON" "$MAIN_SCRIPT" "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"