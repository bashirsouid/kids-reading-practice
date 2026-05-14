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

# Stop the Docker Compose services
dc down "$@"