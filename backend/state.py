"""
state.py — Global state for the backend.
"""

import asyncio
import threading
from typing import Optional

from .models import ComicJob

# Thread-safe lock for websocket operations (asyncio)
_ws_lock = asyncio.Lock()

# Thread-safe lock for job state modifications (threading)
_job_state_lock = threading.Lock()

# In-memory job store
jobs: dict[str, ComicJob] = {}
active_websockets: dict[str, list] = {}
job_tasks: dict[str, dict[str, asyncio.Task]] = {}

# Model instances (loaded once at startup)
text_gen: Optional[object] = None  # TextGenerator
img_gen: Optional[object] = None  # ImageGenerator
models_loaded = False
models_loading = False

__all__ = [
    "jobs",
    "active_websockets",
    "job_tasks",
    "_ws_lock",
    "_job_state_lock",  # Thread-safe lock for job state modifications
    "text_gen",
    "img_gen",
    "models_loaded",
    "models_loading",
]
