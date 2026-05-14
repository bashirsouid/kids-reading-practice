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
WATCH=false
CLEAN=false
DOCKER_ARGS=()

while [[ $# -gt 0 ]]; do
  case $1 in
    -w|--watch)   WATCH=true; shift ;;
    -c|--clean)   CLEAN=true; shift ;;
    -b|--build)   DOCKER_ARGS+=("--build"); shift ;;
    --no-build)   ;; # --build is default; --no-build suppresses it
    -h|--help)
      echo "Usage: $0 [OPTIONS] [-- DOCKER_COMPOSE_ARGS]"
      echo ""
      echo "Options:"
      echo "  -w, --watch      Restart services and then watch logs (Ctrl+C stops watching, not the service)"
      echo "  -c, --clean      Clean volumes and orphaned containers before restarting"
      echo "  -b, --build      Build images before restarting (default: true, always passed to docker compose)"
      echo "      --no-build   Skip image build"
      echo "  -h, --help       Show this help message"
      echo ""
      echo "Any additional arguments are passed through to docker compose."
      exit 0
      ;;
    *) DOCKER_ARGS+=("$1"); shift ;;
  esac
done

echo "=== Comic Generator Restart ==="

# --build is default; --no-build in DOCKER_ARGS removes it
BUILD_FLAGS=("--build")
for arg in "${DOCKER_ARGS[@]}"; do
  if [[ "$arg" == "--no-build" ]]; then
    BUILD_FLAGS=()
    break
  fi
done

# Clean / stop
if [ "$CLEAN" = true ]; then
  echo "Cleaning previous state (volumes + orphans)..."
  dc down -v --remove-orphans "${DOCKER_ARGS[@]}" 2>/dev/null || true
else
  echo "Stopping services..."
  dc down "${DOCKER_ARGS[@]}" 2>/dev/null || true
fi

# Build the frontend React application
echo "Building frontend..."
cd frontend && npm run build && cd ..

# Start the Docker Compose services
echo "Starting services..."
dc up -d "${DOCKER_ARGS[@]}" "${BUILD_FLAGS[@]}"
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
    CONTAINER=$(dc ps -q comic-generator 2>/dev/null | head -1) || true
    if [ -n "$CONTAINER" ]; then
      docker logs -f "$CONTAINER"
    else
      echo "Error: Could not find running comic-generator container" >&2
      exit 1
    fi
  fi
fi