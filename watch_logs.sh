#!/usr/bin/env bash
# Watch logs for the comic generator container
echo "Watching logs for comic-generator-comic-generator-1..."
echo "Press Ctrl+C to stop."
docker logs -f comic-generator-comic-generator-1
