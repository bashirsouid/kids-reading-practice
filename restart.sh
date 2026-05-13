#!/usr/bin/env bash
# Restart the Docker Compose services
docker-compose down "$@"
docker-compose up -d "$@" --build
