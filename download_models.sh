#!/bin/bash

# This script downloads the models used by the comic generator.
docker compose run --rm -v "$(pwd):/app" comic-generator python download_models.py
