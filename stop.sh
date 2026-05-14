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

# Stop the Docker Compose services
"$DOCKER_COMPOSE" down "$@"