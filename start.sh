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
WATCH=false
CLEAN=false
DOCKER_ARGS=()

while [[ $# -gt 0 ]]; do
  case $1 in
    -w|--watch)   WATCH=true; shift ;;
    -c|--clean)   CLEAN=true; shift ;;
    -b|--build)   DOCKER_ARGS+=("--build"); shift ;;
    --no-build)   ;; # --build is default; --no-build is a no-op (kept for compatibility)
    -h|--help)
      echo "Usage: $0 [OPTIONS] [-- DOCKER_COMPOSE_ARGS]"
      echo ""
      echo "Options:"
      echo "  -w, --watch      Start services and then watch logs (Ctrl+C stops watching, not the service)"
      echo "  -c, --clean      Clean volumes and orphaned containers before starting"
      echo "  -b, --build      Build images before starting (default: true, always passed to docker compose)"
      echo "      --no-build   Skip image build (passed to docker compose as --no-build)"
      echo "  -h, --help       Show this help message"
      echo ""
      echo "Any additional arguments are passed through to docker compose."
      exit 0
      ;;
    *) DOCKER_ARGS+=("$1"); shift ;;
  esac
done

echo "=== Comic Generator Startup ==="

# Always pass --build by default (retain original behavior)
# But allow --no-build from DOCKER_ARGS to override
BUILD_FLAGS=("--build")
for arg in "${DOCKER_ARGS[@]}"; do
  if [[ "$arg" == "--no-build" ]]; then
    BUILD_FLAGS=()
    break
  fi
done

# Clean if requested
if [ "$CLEAN" = true ]; then
  echo "Cleaning previous state (volumes + orphans)..."
  "$DOCKER_COMPOSE" down -v --remove-orphans "${DOCKER_ARGS[@]}" 2>/dev/null || true
fi

# Build the frontend React application
echo "Building frontend..."
cd frontend && npm run build && cd ..

# Start the Docker Compose services
echo "Starting services..."
"$DOCKER_COMPOSE" up -d "${DOCKER_ARGS[@]}" "${BUILD_FLAGS[@]}"
echo "Services started."

# Watch logs if requested
if [ "$WATCH" = true ]; then
  echo ""
  echo "=== Watching logs (Ctrl+C to stop watching, service stays running) ==="
  # shellcheck disable=SC2064
  trap "echo ''; echo 'Stopped watching. Service is still running.'; exit 0" INT
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [ -f "$SCRIPT_DIR/watch_logs.sh" ]; then
    exec "$SCRIPT_DIR/watch_logs.sh"
  else
    echo "Warning: watch_logs.sh not found, falling back to docker logs"
    CONTAINER=$("$DOCKER_COMPOSE" ps -q comic-generator 2>/dev/null | head -1)
    if [ -n "$CONTAINER" ]; then
      docker logs -f "$CONTAINER"
    else
      echo "Error: Could not find running comic-generator container" >&2
      exit 1
    fi
  fi
fi