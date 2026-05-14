#!/usr/bin/env bash
set -euo pipefail

# Resolve docker compose command (handles both "docker compose" plugin and "docker-compose" binary)
if command -v docker-compose &>/dev/null; then
  dc() { docker-compose "$@"; }
elif docker compose version &>/dev/null 2>&1; then
  dc() { docker compose "$@"; }
else
  echo "Error: neither 'docker compose' (plugin) nor 'docker-compose' (binary) found" >&2
  exit 1
fi

# Parse flags
DRY_RUN=false
NO_VOLUMENS=false
NO_BUILD=false
NO_OUTPUT=false
NO_LOGS=false
NO_HF_CACHE=false

while [[ $# -gt 0 ]]; do
  case $1 in
    -n|--dry-run)   DRY_RUN=true; shift ;;
    --no-volumes)   NO_VOLUMENS=true; shift ;;
    --no-build)     NO_BUILD=true; shift ;;
    --no-output)    NO_OUTPUT=true; shift ;;
    --no-logs)      NO_LOGS=true; shift ;;
    --no-hf-cache)  NO_HF_CACHE=true; shift ;;
    -h|--help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Clean up all project resources (containers, volumes, build artifacts, etc.)."
      echo ""
      echo "Options:"
      echo "  -n, --dry-run      Show what would be cleaned without doing it"
      echo "  --no-volumes       Skip removing Docker volumes (hf-cache)"
      echo "  --no-build         Skip removing the frontend/ build directory"
      echo "  --no-output        Skip removing the output/ directory"
      echo "  --no-logs          Skip removing the logs/ directory"
      echo "  --no-hf-cache      Skip removing the HuggingFace cache volume"
      echo "  -h, --help         Show this help message"
      echo ""
      echo "By default, everything is cleaned. Use the --no-* flags to keep specific resources."
      exit 0
      ;;
    *) echo "Unknown option: $1 (see --help)" >&2; exit 1 ;;
  esac
done

# Decide what to clean based on --no-* flags
CLEAN_VOLUMENS=true
CLEAN_BUILD=true
CLEAN_OUTPUT=true
CLEAN_LOGS=true
CLEAN_HF_CACHE=true

# If ALL --no-* flags are set, still do Docker teardown but skip resource dirs
if $NO_VOLUMENS && $NO_BUILD && $NO_OUTPUT && $NO_LOGS && $NO_HF_CACHE; then
  CLEAN_BUILD=false
  CLEAN_OUTPUT=false
  CLEAN_LOGS=false
  echo "Note: all --no-* flags set; will still tear down Docker resources."
else
  $NO_VOLUMENS && CLEAN_VOLUMENS=false
  $NO_BUILD     && CLEAN_BUILD=false
  $NO_OUTPUT    && CLEAN_OUTPUT=false
  $NO_LOGS      && CLEAN_LOGS=false
  $NO_HF_CACHE  && CLEAN_HF_CACHE=false
fi

header() {
  echo ""
  echo "=== $1 ==="
}

run_or_preview() {
  local desc="$1" cmd="$2"
  if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would: $desc"
  else
    echo "  $desc ..."
    eval "$cmd"
  fi
}

# 1. Tear down Docker Compose (containers + optionally volumes)
header "Docker cleanup"

if [ "$DRY_RUN" = true ]; then
  echo "[DRY RUN] Would: stop and remove containers"
  $CLEAN_VOLUMENS && echo "[DRY RUN] Would: remove volumes (--remove-orphans)"
else
  echo "  Stopping and removing containers ..."
  dc down --remove-orphans 2>/dev/null || true
  if $CLEAN_VOLUMENS; then
    echo "  Removing volumes ..."
    dc down -v --remove-orphans 2>/dev/null || true
  fi
fi

# 2. Clean frontend build
if $CLEAN_BUILD; then
  header "Frontend build artifacts"
  if [ -d "frontend/build" ]; then
    run_or_preview "Remove frontend/build/" "rm -rf frontend/build"
  elif [ -d "frontend/dist" ]; then
    run_or_preview "Remove frontend/dist/" "rm -rf frontend/dist"
  else
    echo "  No frontend build directory found (checked build/ and dist/)"
  fi
fi

# 3. Clean output directory
if $CLEAN_OUTPUT; then
  header "Output directory"
  if [ -d "output" ]; then
    run_or_preview "Remove output/ directory" "rm -rf output"
  else
    echo "  No output/ directory found"
  fi
fi

# 4. Clean logs directory
if $CLEAN_LOGS; then
  header "Logs directory"
  if [ -d "logs" ]; then
    run_or_preview "Remove logs/ directory" "rm -rf logs"
  else
    echo "  No logs/ directory found"
  fi
fi

# 5. Clean HuggingFace cache volume
if $CLEAN_HF_CACHE; then
  header "HuggingFace cache volume"
  VOLUME_EXISTS=$(docker volume ls -q --filter name=comic-generator_hf-cache 2>/dev/null || true)
  if [ -n "$VOLUME_EXISTS" ]; then
    run_or_preview "Remove Docker volume comic-generator_hf-cache" \
      "docker volume rm comic-generator_hf-cache"
  else
    echo "  HuggingFace cache volume not found (may have been removed with docker compose down -v)"
  fi
fi

# Summary
header "Done"
[ "$DRY_RUN" = true ] && echo "This was a dry run. Re-run without --dry-run to actually clean."
echo "All clean!"