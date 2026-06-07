"""
main.py — FastAPI application entry point for the backend.

Usage:
    python -m backend.main
    uvicorn backend.main:app --host 0.0.0.0 --port 7860
"""

import asyncio
import logging

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import STATIC_DIR, file_handler
from . import state as global_state
from .persistence import load_jobs
from .jobs import _load_models
from .api.routes import router

logger = logging.getLogger("comic-server")


# ── Lifespan Handler ─────────────────────────────────────────────────────────
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for model loading."""
    # Load jobs from disk
    load_jobs()

    # Load models in a background thread
    global_state.models_loading = True
    loop = asyncio.get_event_loop()
    loading_task = loop.run_in_executor(None, _load_models)

    yield

    # Cleanup
    pass


# ── App Setup ────────────────────────────────────────────────────────────────
app = FastAPI(title="AI Comic Book Generator", version="1.0.0", lifespan=lifespan)

# Serve static assets (JS/CSS) from React build - MUST be before router to avoid catch-all conflicts
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

# Include API routes
app.include_router(router)


# ── Run ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Ensure uvicorn logs also go to our file handler
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
        l = logging.getLogger(logger_name)
        l.addHandler(file_handler)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=7860,
        log_level="info",
    )