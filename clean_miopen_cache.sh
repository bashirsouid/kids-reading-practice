#!/bin/bash
# clean_miopen_cache.sh — Safely remove corrupted MIOpen cache directories.
# This script targets the specific "directory instead of file" corruption
# that causes miopenStatusInternalError on RDNA3 / Strix Halo.

CONTAINER_NAME=$(docker compose ps -q comic-generator)

if [ -z "$CONTAINER_NAME" ]; then
    echo "Error: comic-generator container is not running."
    exit 1
fi

echo "Checking for corrupted MIOpen cache directories..."
# Find directories (type d) named *.ukdb in the cache path and remove them.
docker compose exec comic-generator find /root/.cache/miopen -maxdepth 1 -type d -name '*.ukdb' -print -exec rm -rf {} +

echo "Checking for other potentially corrupted metadata files..."
docker compose exec comic-generator find /root/.cache/miopen -maxdepth 1 -type d -name '*.udb.txt' -print -exec rm -rf {} +
docker compose exec comic-generator find /root/.cache/miopen -maxdepth 1 -type d -name '*.ufdb.txt' -print -exec rm -rf {} +

echo "Done. Corrupted directories removed. Actual database files (.ukdb) were not touched if they are files."
echo "You may need to restart the container for changes to take effect: docker compose restart comic-generator"
