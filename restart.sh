#!/usr/bin/env bash
# Build the frontend React application
echo "Building frontend..."
cd frontend && npm run build && cd ..

# Restart the Docker Compose services
docker compose down "$@"
docker compose up -d "$@" --build
