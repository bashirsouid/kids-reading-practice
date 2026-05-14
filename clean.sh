#!/usr/bin/env bash
set -euo pipefail

# Resolve docker compose command (handles both "docker compose" and "docker-compose")
if type docker compose &>/dev/null; then
  DOCKER_COMPOSE="docker compose"
elif type docker-compose &>/dev/null; then
  DOCKER_COMPOSE="docker-compose"
else
  echo "Error: neither 'docker compose' nor 'docker-compose' found" >&2
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

# Decide what to clean
CLEAN_VOLUMENS=true
CLEAN_BUILD=true
CLEAN_OUTPUT=true
CLEAN_LOGS=true
CLEAN_HF_CACHE=true

# If specific --no-* flags are set, only disable those individually.
# If ALL --no-* flags are set, assume the user wants nothing — but that's unusual.
# Default behavior (--no-* not specified): clean everything.

# We need at least one thing to clean
if $NO_VOLUMENS && $NO_BUILD && $NO_OUTPUT && $NO_LOGS && $NO_HF_CACHE; then
  # When ALL flags are explicitly set to skip, do a basic docker-only clean
  CLEAN_VOLUMENS=true;  CLEAN_BUILD=false; CLEAN_OUTPUT=false; CLEAN_LOGS=false
  echo "Note: all --no-* flags set; will still tear down Docker resources."
else
  CLEAN_VOLUMENS=$([[ "$NO_VOLUMENS" == false && "$NO_HF_CACHE" == false ]] && echo true || echo false)
  CLEAN_BUILD=$([[ "$NO_BUILD" == false ]] && echo true || echo false)
  CLEAN_OUTPUT=$([[ "$NO_OUTPUT" == false ]] && echo true || echo false)
  CLEAN_LOGS=$([[ "$NO_LOGS" == false ]] && echo true || echo false)
  # NO_HF_CACHE only matters if NO_VOLUMENS is also not set; handled above
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
  if $CLEAN_VOLUMENS; then
    echo "[DRY RUN] Would: remove volumes (--remove-orphans)"
  fi
else
  echo "  Stopping and removing containers ..."
  "$DOCKER_COMPOSE" down --remove-orphans 2>/dev/null || true
  if $CLEAN_VOLUMENS; then
    echo "  Removing volumes ..."
    "$DOCKER_COMPOSE" down -v --remove-orphans 2>/dev/null || true
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
  # Also clean node_modules if a clean rebuild is desired — but that's aggressive
  # run_or_preview "Remove frontend/node_modules/" "rm -rf frontend/node_modules"
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
if $CLEAN_HF_CACHE && $CLEAN_VOLUMENS; then
  header "HuggingFace cache volume"
  VOLUME_EXISTS=$(docker volume ls -q --filter name=comic-generator_hf-cache 2>/dev/null || true)
  if [ -n "$VOLUME_EXISTS" ]; then
    run_or_preview "Remove Docker volume comic-generator_hf-cache" \
      "docker volume rm comic-generator_hf-cache"
  else
    echo "  HuggingFace cache volume not found (may have been removed with docker compose down -v)"
  fi
elif $CLEAN_HF_CACHE && ! $CLEAN_VOLUMENS; then
  header "HuggingFace cache (standalone)"
  VOLUME_EXISTS=$(docker volume ls -q --filter name=comic-generator_hf-cache 2>/dev/null || true)
  if [ -n "$VOLUME_EXISTS" ]; then
    run_or_preview "Remove Docker volume comic-generator_hf-cache" \
      "docker volume rm comic-generator_hf-cache"
  else
    echo "  HuggingFace cache volume not found"
  fi
fi

# Summary
header "Done"
if [ "$DRY_RUN" = true ]; then
  echo "This was a dry run. Re-run without --dry-run to actually clean."
fi
echo "All clean!"