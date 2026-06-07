"""
broadcasting.py — WebSocket and progress broadcasting functions.
"""

import asyncio
import json
import logging
from typing import Optional

from . import state as global_state

logger = logging.getLogger("comic-server")


async def _get_ws_list(job_id: str) -> list:
    """Thread-safe getter for websocket list."""
    async with global_state._ws_lock:
        return list(global_state.active_websockets.get(job_id, []))


async def _remove_ws(job_id: str, ws) -> None:
    """Thread-safe removal of websocket from list."""
    async with global_state._ws_lock:
        ws_list = global_state.active_websockets.get(job_id, [])
        if ws in ws_list:
            ws_list.remove(ws)


async def broadcast_image_generating(job, target: str, panel_index: Optional[int] = None):
    """Notify clients that image generation has started (blank the old image)."""
    data = {
        "type": "image_generating",
        "job_id": job.job_id,
        "target": target,  # "reference" or "panel"
        "panel_index": panel_index,
    }
    message = json.dumps(data)
    ws_list = await _get_ws_list(job.job_id)
    disconnected = []
    for ws in ws_list:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        await _remove_ws(job.job_id, ws)


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
    ws_list = await _get_ws_list(job.job_id)
    disconnected = []
    for ws in ws_list:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        await _remove_ws(job.job_id, ws)


def _make_step_callback(job_id: str, target: str, panel_index: Optional[int] = None):
    """Create a thread-safe step callback for image generation.

    The callback is invoked from executor threads, so it dispatches
    the WebSocket broadcast back to the event loop via
    asyncio.run_coroutine_threadsafe.
    
    Uses job_id instead of job object to avoid stale references.
    """
    loop = asyncio.get_event_loop()

    async def do_broadcast(step: int, total_steps: int):
        """Internal async function to get fresh job from state and broadcast."""
        job = global_state.jobs.get(job_id)
        if job:
            await broadcast_image_progress(job, target, step, total_steps, panel_index)

    def step_cb(step: int, total_steps: int):
        asyncio.run_coroutine_threadsafe(
            do_broadcast(step, total_steps),
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
    elif job.status.value == "complete" or job.stage == "complete":
        data["type"] = "complete"
    else:
        data["type"] = "progress"
        # include progress fields for UI updates
        data["progress"] = job.progress_current
        data["total"] = job.progress_total

    if job.story and job.story.master_reference is not None:
        data["reference_ready"] = True

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

    # Broadcast to all connected clients for this job (thread-safe)
    ws_list = await _get_ws_list(job.job_id)
    disconnected = []
    for ws in ws_list:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        await _remove_ws(job.job_id, ws)


def _get_queue_position(job_id: str) -> int:
    """Get the position of a job in the queue (0 = currently processing).
    
    Since we removed the queue, this always returns 0.
    Kept for backwards compatibility.
    """
    return 0


__all__ = [
    "broadcast_image_generating",
    "broadcast_image_progress",
    "_make_step_callback",
    "broadcast_job_update",
    "_get_queue_position",
]
