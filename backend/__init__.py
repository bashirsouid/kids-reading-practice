"""
backend — AI Comic Book Generator backend package.

This package provides a modular FastAPI backend for comic generation.
"""

from .models import JobStatus, ComicJob
from . import state
from .config import LOG_DIR, LOG_FILE, STATIC_DIR, OUTPUT_DIR, JOBS_FILE, JOB_ASSETS_DIR
from .main import app

__all__ = [
    "JobStatus",
    "ComicJob",
    "state",
    "LOG_DIR",
    "LOG_FILE",
    "STATIC_DIR",
    "OUTPUT_DIR",
    "JOBS_FILE",
    "JOB_ASSETS_DIR",
    "app",
]