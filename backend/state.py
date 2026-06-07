"""
state.py — Global state for the backend.
"""

import asyncio
from typing import Optional

from .models import ComicJob

# Thread-safe lock for websocket operations
_ws_lock = asyncio.Lock()

# In-memory job store
jobs: dict[str, ComicJob] = {}
active_websockets: dict[str, list] = {}

# Model instances (loaded once at startup)
text_gen: Optional[object] = None  # TextGenerator
img_gen: Optional[object] = None  # ImageGenerator
models_loaded = False
models_loading = False

__all__ = [
    "jobs",
    "active_websockets",
    "_ws_lock",  # Export the lock for thread-safe websocket access
    "text_gen",
    "img_gen",
    "models_loaded",
    "models_loading",
]