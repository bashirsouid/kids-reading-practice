#!/usr/bin/env bash
# Build the frontend React application
echo "Building frontend..."
cd frontend && npm run build && cd ..

# Start the Docker Compose services
docker compose up -d "$@" --build
