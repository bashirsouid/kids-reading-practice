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

# Watch logs for the comic generator container
echo "Watching logs for comic-generator..."
echo "Press Ctrl+C to stop."

# Dynamically resolve the container name
CONTAINER=$("$DOCKER_COMPOSE" ps -q comic-generator 2>/dev/null | head -1)
if [ -z "$CONTAINER" ]; then
  echo "Error: No running comic-generator container found" >&2
  exit 1
fi

docker logs -f "$CONTAINER"