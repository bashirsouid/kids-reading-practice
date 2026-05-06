"""
server.py — FastAPI web server for Comic Book Generator.

Provides REST API + WebSocket for real-time generation progress.
Single-worker job queue ensures only one generation runs at a time.
"""

import asyncio
import io
import json
import logging
import os
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

# ── Early Logging Setup ──────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "comic-generator.log"

log_format = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# File Handler
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=10*1024*1024, backupCount=5)
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

# Limit GPU resources (now with logging configured)
from gpu_utils import limit_gpu_cores
limit_gpu_cores()

logger = logging.getLogger("comic-server")

import time
import uuid
import psutil
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from generator import (
    TextGenerator,
    ImageGenerator,
    ComicStory,
    Panel,
    render_page,
    generate_all_panels,
    regenerate_panel,
)

def log_system_resources(stage: str):
    """Log current RAM and CPU usage."""
    try:
        vm = psutil.virtual_memory()
        logger.info(f"[{stage}] System Resources: RAM Used: {vm.percent}% ({vm.used // 1024**2}MB / {vm.total // 1024**2}MB)")
    except Exception as e:
        logger.warning(f"Could not log system resources: {e}")

# ── Lifespan Handler ─────────────────────────────────────────────────────────
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for model loading and job worker."""
    global text_gen, img_gen, models_loaded, models_loading

    # Start background worker
    logger.info("Starting background job worker...")
    worker_task = asyncio.create_task(job_worker())
    log_system_resources("STARTUP")

    # Load models in a background thread
    models_loading = True
    loop = asyncio.get_event_loop()
    loading_task = loop.run_in_executor(None, _load_models)
    
    yield
    
    # Cleanup (optional)
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

# ── App Setup ────────────────────────────────────────────────────────────────
app = FastAPI(title="AI Comic Book Generator", version="1.0.0", lifespan=lifespan)

# Serve static files
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ── Global State ─────────────────────────────────────────────────────────────
class JobStatus(str, Enum):
    QUEUED = "queued"
    GENERATING_SYNOPSIS = "generating_synopsis"
    GENERATING_STORY = "generating_story"
    GENERATING_PANELS = "generating_panels"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class ComicJob:
    job_id: str
    status: JobStatus
    mode: str  # "random", "themed", "custom"
    input_text: str
    created_at: float
    story: Optional[ComicStory] = None
    progress_current: int = 0
    progress_total: int = 6
    error: Optional[str] = None
    panel_thumbnails: dict = field(default_factory=dict)  # panel_index -> base64


# In-memory job store
jobs: dict[str, ComicJob] = {}
job_queue: asyncio.Queue = asyncio.Queue()
active_websockets: dict[str, list[WebSocket]] = {}

# Model instances (loaded once at startup)
text_gen: Optional[TextGenerator] = None
img_gen: Optional[ImageGenerator] = None
models_loaded = False
models_loading = False


# ── Pydantic Models ──────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    mode: str  # "random", "themed", "custom"
    text: str = ""  # theme for "themed", full story for "custom", ignored for "random"


class RegeneratePanelRequest(BaseModel):
    job_id: str
    panel_index: int
    modification: str = ""  # optional edit text


class UpdateCaptionRequest(BaseModel):
    job_id: str
    panel_index: int
    caption: str


class UpdateTitleRequest(BaseModel):
    job_id: str
    title: str


# ── Run ──────────────────────────────────────────────────────────────────────
def _load_models():
    """Load both AI models into GPU memory."""
    global text_gen, img_gen, models_loaded, models_loading
    try:
        logger.info("=" * 60)
        logger.info("Loading AI models into GPU memory...")
        log_system_resources("PRE-MODEL-LOAD")
        logger.info("=" * 60)

        text_gen = TextGenerator()
        text_gen.load()

        img_gen = ImageGenerator()
        img_gen.load()

        models_loaded = True
        models_loading = False
        logger.info("=" * 60)
        logger.info("All models loaded! Server ready.")
        log_system_resources("POST-MODEL-LOAD")
        logger.info("=" * 60)
    except Exception as e:
        logger.error(f"Failed to load models: {e}", exc_info=True)
        models_loading = False


# ── Background Job Worker ────────────────────────────────────────────────────
async def job_worker():
    """Single-worker consumer that processes one job at a time."""
    while True:
        job_id = await job_queue.get()
        job = jobs.get(job_id)
        if not job:
            continue

        try:
            await process_job(job)
        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)
            job.status = JobStatus.ERROR
            job.error = str(e)
            await broadcast_job_update(job)
        finally:
            job_queue.task_done()


async def process_job(job: ComicJob):
    """Process a single comic generation job."""
    logger.info(f"--- START PROCESSING JOB {job.job_id} ---")
    log_system_resources(f"JOB-{job.job_id}-START")
    loop = asyncio.get_event_loop()

    # Step 1: Generate synopsis (for random/themed modes)
    if job.mode in ("random", "themed"):
        job.status = JobStatus.GENERATING_SYNOPSIS
        await broadcast_job_update(job)

        theme = job.input_text if job.mode == "themed" else None
        synopsis = await loop.run_in_executor(
            None, text_gen.generate_random_synopsis, theme
        )
        job.input_text = synopsis
        logger.info(f"Generated synopsis: {synopsis}")

    # Step 2: Generate story structure
    job.status = JobStatus.GENERATING_STORY
    await broadcast_job_update(job)

    story = await loop.run_in_executor(
        None, text_gen.generate_story, job.input_text
    )
    job.story = story
    logger.info(f"Story generated: {story.title} ({len(story.panels)} panels)")
    await broadcast_job_update(job)

    # Step 3: Generate panel images
    job.status = JobStatus.GENERATING_PANELS
    job.progress_current = 0
    job.progress_total = len(story.panels)
    await broadcast_job_update(job)

    # Generate panels one by one with progress updates
    for panel in story.panels:
        log_system_resources(f"JOB-{job.job_id}-PANEL-{panel.index}")
        def generate_single_panel(p=panel):
            from generator import compute_panel_rects, PANEL_GEN_SIZE, CAPTION_H
            rects = compute_panel_rects()
            pw, ph = rects[p.index][2], rects[p.index][3]
            img_h = ph - CAPTION_H
            aspect = pw / img_h
            gen_w = (int(PANEL_GEN_SIZE * aspect) // 64) * 64
            gen_h = (PANEL_GEN_SIZE // 64) * 64
            full_prompt = (
                f"{story.art_style}. {story.character_bible}. "
                f"Scene: {p.image_prompt}"
            )
            p.image = img_gen.generate(prompt=full_prompt, width=gen_w, height=gen_h)

        await loop.run_in_executor(None, generate_single_panel)
        job.progress_current = panel.index + 1

        # Give the GPU and Window Manager some room to breathe
        await asyncio.sleep(1.0)

        # Generate thumbnail for WebSocket preview
        if panel.image:
            job.panel_thumbnails[panel.index] = _image_to_base64(
                panel.image, max_size=256
            )

        await broadcast_job_update(job)

    # Step 4: Done
    job.status = JobStatus.COMPLETE
    await broadcast_job_update(job)
    logger.info(f"Job {job.job_id} complete: {story.title}")


def _image_to_base64(img, max_size: int = 512) -> str:
    """Convert a PIL Image to a base64-encoded JPEG string."""
    import base64
    # Resize for thumbnail
    ratio = min(max_size / img.width, max_size / img.height)
    if ratio < 1:
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ── WebSocket Broadcasting ───────────────────────────────────────────────────
async def broadcast_job_update(job: ComicJob):
    """Send job status update to all connected WebSocket clients."""
    data = {
        "job_id": job.job_id,
        "status": job.status.value,
        "mode": job.mode,
        "synopsis": job.input_text,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "error": job.error,
        "queue_position": _get_queue_position(job.job_id),
    }
    if job.story:
        data["story"] = {
            "title": job.story.title,
            "art_style": job.story.art_style,
            "character_bible": job.story.character_bible,
            "panels": [
                {
                    "index": p.index,
                    "caption": p.caption,
                    "image_prompt": p.image_prompt,
                    "has_image": p.image is not None,
                }
                for p in job.story.panels
            ],
        }
    if job.panel_thumbnails:
        data["panel_thumbnails"] = job.panel_thumbnails

    message = json.dumps(data)

    # Broadcast to all connected clients for this job
    ws_list = active_websockets.get(job.job_id, [])
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
    # Check if the job is currently being processed
    queued_ids = list(job_queue._queue)
    if job_id in queued_ids:
        return queued_ids.index(job_id) + 1
    return 0


# ── API Routes ───────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the main SPA."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return index_path.read_text()


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok" if models_loaded else "loading",
        "models_loaded": models_loaded,
        "models_loading": models_loading,
        "active_jobs": len([j for j in jobs.values() if j.status not in (JobStatus.COMPLETE, JobStatus.ERROR)]),
        "queue_size": job_queue.qsize(),
    }


@app.post("/api/generate")
async def generate_comic(req: GenerateRequest):
    """Submit a new comic generation job."""
    if not models_loaded:
        raise HTTPException(status_code=503, detail="Models are still loading. Please wait.")

    if req.mode not in ("random", "themed", "custom"):
        raise HTTPException(status_code=400, detail="Mode must be 'random', 'themed', or 'custom'")

    if req.mode == "custom" and not req.text.strip():
        raise HTTPException(status_code=400, detail="Custom mode requires story text")

    if req.mode == "themed" and not req.text.strip():
        raise HTTPException(status_code=400, detail="Themed mode requires a theme")

    job_id = str(uuid.uuid4())[:8]
    job = ComicJob(
        job_id=job_id,
        status=JobStatus.QUEUED,
        mode=req.mode,
        input_text=req.text.strip(),
        created_at=time.time(),
    )
    jobs[job_id] = job
    await job_queue.put(job_id)

    return {
        "job_id": job_id,
        "status": job.status.value,
        "queue_position": job_queue.qsize(),
    }


@app.get("/api/status/{job_id}")
async def get_job_status(job_id: str):
    """Get the status of a job."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = {
        "job_id": job.job_id,
        "status": job.status.value,
        "mode": job.mode,
        "synopsis": job.input_text,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "error": job.error,
        "queue_position": _get_queue_position(job.job_id),
    }
    if job.story:
        result["story"] = {
            "title": job.story.title,
            "panels": [
                {"index": p.index, "caption": p.caption, "has_image": p.image is not None}
                for p in job.story.panels
            ],
        }
    return result


@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """WebSocket for real-time job progress updates."""
    await websocket.accept()

    if job_id not in active_websockets:
        active_websockets[job_id] = []
    active_websockets[job_id].append(websocket)

    try:
        # Send current state immediately
        job = jobs.get(job_id)
        if job:
            await broadcast_job_update(job)

        # Keep connection alive
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # Send ping to keep alive
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        ws_list = active_websockets.get(job_id, [])
        if websocket in ws_list:
            ws_list.remove(websocket)


@app.post("/api/regenerate-panel")
async def api_regenerate_panel(req: RegeneratePanelRequest):
    """Regenerate a single panel."""
    if not models_loaded:
        raise HTTPException(status_code=503, detail="Models still loading")

    job = jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found or not complete")

    if req.panel_index < 0 or req.panel_index >= len(job.story.panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")

    loop = asyncio.get_event_loop()
    modification = req.modification if req.modification else None

    await loop.run_in_executor(
        None,
        regenerate_panel,
        job.story,
        req.panel_index,
        img_gen,
        modification,
    )

    # Update thumbnail
    panel = job.story.panels[req.panel_index]
    if panel.image:
        job.panel_thumbnails[req.panel_index] = _image_to_base64(panel.image, max_size=256)

    return {"status": "ok", "panel_index": req.panel_index}


@app.post("/api/update-caption")
async def api_update_caption(req: UpdateCaptionRequest):
    """Update a panel's caption text."""
    job = jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    if req.panel_index < 0 or req.panel_index >= len(job.story.panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")

    job.story.panels[req.panel_index].caption = req.caption
    return {"status": "ok"}


@app.post("/api/update-title")
async def api_update_title(req: UpdateTitleRequest):
    """Update the comic title."""
    job = jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    job.story.title = req.title
    return {"status": "ok"}


@app.get("/api/export/{job_id}")
async def export_comic(job_id: str):
    """Export the comic page as a downloadable PNG."""
    job = jobs.get(job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.COMPLETE:
        raise HTTPException(status_code=400, detail="Job not complete yet")

    # Render the final page
    page = render_page(job.story)

    # Save to output directory
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in job.story.title)[:40]
    filename = f"{safe_title.replace(' ', '_')}_{job_id}.png"

    # Also save to disk
    output_path = OUTPUT_DIR / filename
    page.save(str(output_path), dpi=(300, 300))

    # Stream the image as response
    buf = io.BytesIO()
    page.save(buf, format="PNG", dpi=(300, 300))
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/preview/{job_id}")
async def preview_comic(job_id: str):
    """Get a preview image of the current comic page (lower res)."""
    job = jobs.get(job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    page = render_page(job.story)

    # Resize for web preview
    preview_w = 800
    ratio = preview_w / page.width
    preview_h = int(page.height * ratio)
    page = page.resize((preview_w, preview_h))

    buf = io.BytesIO()
    page.save(buf, format="JPEG", quality=85)
    buf.seek(0)

    return StreamingResponse(buf, media_type="image/jpeg")


@app.get("/api/panel-image/{job_id}/{panel_index}")
async def get_panel_image(job_id: str, panel_index: int):
    """Get a single panel image."""
    job = jobs.get(job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    if panel_index < 0 or panel_index >= len(job.story.panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")

    panel = job.story.panels[panel_index]
    if not panel.image:
        raise HTTPException(status_code=404, detail="Panel image not generated yet")

    buf = io.BytesIO()
    panel.image.convert("RGB").save(buf, format="JPEG", quality=90)
    buf.seek(0)

    return StreamingResponse(buf, media_type="image/jpeg")


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
