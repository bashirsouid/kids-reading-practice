"""
broadcasting.py — WebSocket and progress broadcasting functions.
"""

import asyncio
import json
import logging
from typing import Optional

from . import state as global_state
from .utils import _make_project_slug

logger = logging.getLogger("comic-server")


async def broadcast_image_generating(job, target: str, panel_index: Optional[int] = None):
    """Notify clients that image generation has started (blank the old image)."""
    data = {
        "type": "image_generating",
        "job_id": job.job_id,
        "target": target,  # "reference" or "panel"
        "panel_index": panel_index,
    }
    message = json.dumps(data)
    ws_list = global_state.active_websockets.get(job.job_id, [])
    disconnected = []
    for ws in ws_list:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        ws_list.remove(ws)


async def broadcast_image_progress(job, target: str, step: int, total_steps: int, panel_index: Optional[int] = None):
    """Notify clients of step-level image generation progress."""
    data = {
        "type": "image_progress",
        "job_id": job.job_id,
        "target": target,  # "reference" or "panel"
        "panel_index": panel_index,
        "step": step,
        "total_steps": total_steps,
    }
    message = json.dumps(data)
    ws_list = global_state.active_websockets.get(job.job_id, [])
    disconnected = []
    for ws in ws_list:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        ws_list.remove(ws)


def _make_step_callback(job, target: str, panel_index: Optional[int] = None):
    """Create a thread-safe step callback for image generation.

    The callback is invoked from executor threads, so it dispatches
    the WebSocket broadcast back to the event loop via
    asyncio.run_coroutine_threadsafe.
    """
    loop = asyncio.get_event_loop()

    def step_cb(step: int, total_steps: int):
        asyncio.run_coroutine_threadsafe(
            broadcast_image_progress(job, target, step, total_steps, panel_index),
            loop,
        )

    return step_cb


async def broadcast_job_update(job):
    """Send job status update to all connected WebSocket clients.
    The payload now includes a `type` field to indicate the nature of the update:
    - "progress" for regular progress updates.
    - "complete" when the master reference image is ready.
    - "error" when an error occurs.
    """
    # Base data shared across all message types
    data = {
        "job_id": job.job_id,
        "slug": job.slug,
        "status": job.status.value,
        "stage": job.stage,
        "mode": job.mode,
        "synopsis": job.input_text,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "queue_position": _get_queue_position(job.job_id),
        "wait_for_user": job.wait_for_user,
        "has_reference": job.story.master_reference is not None if job.story else False,
        "error": job.error,
    }

    # Determine message type based on job state
    if job.error:
        data["type"] = "error"
        data["message"] = job.error
    elif job.story and job.story.master_reference is not None:
        data["type"] = "complete"
        data["reference_ready"] = True
    else:
        data["type"] = "progress"
        # include progress fields for UI updates
        data["progress"] = job.progress_current
        data["total"] = job.progress_total

    # Include story details if available
    if job.story:
        data["story"] = {
            "title": job.story.title,
            "synopsis": job.story.synopsis,
            "art_style": job.story.art_style,
            # New shared world-anchor; getattr keeps us safe loading older
            # jobs that pre-date the field.
            "story_setting": getattr(job.story, "story_setting", ""),
            "character_bible": job.story.character_bible,
            "characters": [{"name": c.name, "description": c.description} for c in job.story.characters],
            "panels": [
                {
                    "index": p.index,
                    "caption": p.caption,
                    "image_prompt": p.image_prompt,
                    "characters": p.characters,
                    "has_image": p.image is not None,
                    "is_placeholder": p.is_placeholder,
                }
                for p in job.story.panels
            ],
        }
    if job.panel_thumbnails:
        data["panel_thumbnails"] = job.panel_thumbnails

    message = json.dumps(data)

    # Broadcast to all connected clients for this job
    ws_list = global_state.active_websockets.get(job.job_id, [])
    disconnected = []
    for ws in ws_list:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        ws_list.remove(ws)


def _get_queue_position(job_id: str) -> int:
    """Get the position of a job in the queue (0 = currently processing)."""
    queued_ids = list(global_state.job_queue._queue)
    if job_id in queued_ids:
        return queued_ids.index(job_id) + 1
    return 0


__all__ = [
    "broadcast_image_generating",
    "broadcast_image_progress",
    "_make_step_callback",
    "broadcast_job_update",
    "_get_queue_position",
]