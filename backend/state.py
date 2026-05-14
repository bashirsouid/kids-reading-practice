"""
state.py — Global state for the backend.
"""

import asyncio
from typing import Optional

from .models import ComicJob

# In-memory job store
jobs: dict[str, ComicJob] = {}
job_queue: asyncio.Queue = asyncio.Queue()
active_websockets: dict[str, list] = {}

# Model instances (loaded once at startup)
text_gen: Optional[object] = None  # TextGenerator
img_gen: Optional[object] = None  # ImageGenerator
models_loaded = False
models_loading = False

__all__ = [
    "jobs",
    "job_queue",
    "active_websockets",
    "text_gen",
    "img_gen",
    "models_loaded",
    "models_loading",
]