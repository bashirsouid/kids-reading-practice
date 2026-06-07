"""
config.py — Configuration constants and paths for the backend.
"""

import logging
import os
from dotenv import load_dotenv
load_dotenv()
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

if not os.getenv("OPENROUTER_API_KEY"):
    raise RuntimeError("OPENROUTER_API_KEY not set in .env")

# ── Early Logging Setup ──────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = str(LOG_DIR / "comic-generator.log")

log_format = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# File Handler
file_handler = RotatingFileHandler(str(LOG_FILE), maxBytes=10*1024*1024, backupCount=5)
file_handler.setFormatter(log_format)

# Console Handler
console_handler = logging.StreamHandler(sys.__stdout__)
console_handler.setFormatter(log_format)

# Root Logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Capture stdout/stderr
class StreamToLogger:
    def __init__(self, logger, log_level, stream):
        self.logger = logger
        self.log_level = log_level
        self.stream = stream

    def write(self, buf):
        if buf.strip():
            for line in buf.rstrip().splitlines():
                self.logger.log(self.log_level, line.rstrip())
        self.stream.write(buf)

    def flush(self):
        self.stream.flush()

    def isatty(self):
        return self.stream.isatty()

sys.stdout = StreamToLogger(logging.getLogger("STDOUT"), logging.INFO, sys.__stdout__)
sys.stderr = StreamToLogger(logging.getLogger("STDERR"), logging.ERROR, sys.__stderr__)

# ── Directory Configuration ───────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent.parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
JOBS_FILE = OUTPUT_DIR / "jobs.json"
JOB_ASSETS_DIR = OUTPUT_DIR / "jobs"
JOB_ASSETS_DIR.mkdir(exist_ok=True)

# ── Image Generation Configuration ────────────────────────────────────────────
# Number of concurrent workers for panel image generation (1-6, default 6 for testing)
IMAGE_GEN_CONCURRENCY = max(1, min(6, int(os.getenv("IMAGE_GEN_CONCURRENCY", "6"))))

# Export file_handler for use in main.py
__all__ = [
    "LOG_DIR",
    "LOG_FILE",
    "log_format",
    "file_handler",
    "console_handler",
    "root_logger",
    "StreamToLogger",
    "STATIC_DIR",
    "OUTPUT_DIR",
    "JOBS_FILE",
    "JOB_ASSETS_DIR",
    "IMAGE_GEN_CONCURRENCY",
]