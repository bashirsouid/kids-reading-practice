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

# Watch logs for the comic generator container
echo "Watching logs for comic-generator..."
echo "Press Ctrl+C to stop."

# Dynamically resolve the container name
# Allow DC_CMD_STR from parent (exported by start.sh -w / restart.sh -w)
if [ -n "${DC_CMD_STR:-}" ]; then
  CONTAINER=$(eval "$DC_CMD_STR" ps -q comic-generator 2>/dev/null | head -1) || true
else
  CONTAINER=$(dc ps -q comic-generator 2>/dev/null | head -1) || true
fi

if [ -z "$CONTAINER" ]; then
  echo "Error: No running comic-generator container found" >&2
  exit 1
fi

docker logs -f "$CONTAINER"