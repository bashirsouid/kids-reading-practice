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
import re
import sys
import time
import uuid
from pathlib import Path
from logging.handlers import RotatingFileHandler

# ── Early Logging Setup ──────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
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

# Limit GPU resources (now with logging configured)
from gpu_utils import limit_gpu_cores
limit_gpu_cores()

logger = logging.getLogger("comic-server")

import time
import uuid
import psutil
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image

from generator import (
    TextGenerator,
    ImageGenerator,
    ComicStory,
    Panel,
    render_page,
    generate_all_panels,
    regenerate_panel,
    _panel_gen_dims,
    _panel_prompt,
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

    # Load jobs from disk
    load_jobs()

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
JOBS_FILE = OUTPUT_DIR / "jobs.json"
JOB_ASSETS_DIR = OUTPUT_DIR / "jobs"
JOB_ASSETS_DIR.mkdir(exist_ok=True)

# Mount static assets (JS/CSS) from React build
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


# ── Global State ─────────────────────────────────────────────────────────────
# ── Enum Definitions ─────────────────────────────────────────────────────────
class JobStatus(str, Enum):
    QUEUED = "queued"
    GENERATING_SYNOPSIS = "generating_synopsis"
    GENERATING_STORY = "generating_story"
    GENERATING_REFERENCE = "generating_reference"
    PANEL_BREAKDOWN = "panel_breakdown"
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
    slug: str = ""  # URL-friendly project name
    cancel_requested: bool = False
    stage: str = "input"  # input, synopsis, story, reference, panel_breakdown, panels, complete, error
    wait_for_user: bool = False  # Pause and wait for user to click "Next"


# In-memory job store
jobs: dict[str, ComicJob] = {}
job_queue: asyncio.Queue = asyncio.Queue()
active_websockets: dict[str, list[WebSocket]] = {}

# Model instances (loaded once at startup)
text_gen: Optional[TextGenerator] = None
img_gen: Optional[ImageGenerator] = None
models_loaded = False
models_loading = False

def save_jobs():
    """Serialize and save jobs to disk."""
    dump = {}
    for jid, job in jobs.items():
        _save_job_images(job)
        job_dict = asdict(job)
        if job_dict.get("story"):
            # Remove PIL images before serialization
            job_dict["story"]["master_reference"] = None
            for p in job_dict["story"]["panels"]:
                p["image"] = None
        dump[jid] = job_dict
        
    try:
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(dump, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save jobs: {e}")

def load_jobs():
    """Load jobs from disk."""
    global jobs
    if not JOBS_FILE.exists():
        return
        
    try:
        with open(JOBS_FILE, "r", encoding="utf-8") as f:
            dump = json.load(f)
            
        for jid, jdict in dump.items():
            story_dict = jdict.pop("story", None)
            jdict["status"] = JobStatus(jdict["status"])
            job = ComicJob(**jdict)
            if story_dict:
                from generator import ComicStory, Panel, Character
                panels = []
                for pdict in story_dict.get("panels", []):
                    panels.append(Panel(**pdict))
                characters = []
                for cdict in story_dict.get("characters", []):
                    characters.append(Character(**cdict))
                
                story_dict["panels"] = panels
                story_dict["characters"] = characters
                job.story = ComicStory(**story_dict)
                _load_job_images(job)
            if not job.slug:
                job.slug = _make_project_slug(job.job_id)
            jobs[jid] = job
            
        logger.info(f"Loaded {len(jobs)} jobs from disk.")
    except Exception as e:
        logger.error(f"Failed to load jobs: {e}")


def _job_assets_dir(job_id: str) -> Path:
    path = JOB_ASSETS_DIR / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_job_images(job: ComicJob):
    """Persist generated PIL images outside jobs.json so projects survive restarts."""
    if not job.story:
        return

    assets_dir = _job_assets_dir(job.job_id)

    if job.story.master_reference is not None:
        ref_path = assets_dir / "master_reference.jpg"
        job.story.master_reference.convert("RGB").save(ref_path, format="JPEG", quality=92)

    for panel in job.story.panels:
        if panel.image is None:
            continue
        panel_path = assets_dir / f"panel_{panel.index}.jpg"
        panel.image.convert("RGB").save(panel_path, format="JPEG", quality=92)


def _load_job_images(job: ComicJob):
    """Load persisted images for an existing job, if they were generated earlier."""
    if not job.story:
        return

    assets_dir = JOB_ASSETS_DIR / job.job_id
    ref_path = assets_dir / "master_reference.jpg"
    if ref_path.exists():
        with Image.open(ref_path) as img:
            job.story.master_reference = img.copy()

    for panel in job.story.panels:
        panel_path = assets_dir / f"panel_{panel.index}.jpg"
        if panel_path.exists():
            with Image.open(panel_path) as img:
                panel.image = img.copy()


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


class UpdateSynopsisRequest(BaseModel):
    job_id: str
    synopsis: str


class UpdateArtStyleRequest(BaseModel):
    job_id: str
    art_style: str


class GenerateSynopsisRequest(BaseModel):
    full_story: str


class ProceedToNextStageRequest(BaseModel):
    job_id: str


class UpdatePanelRequest(BaseModel):
    job_id: str
    panel_index: int
    caption: Optional[str] = None
    image_prompt: Optional[str] = None


class UpdatePanelsRequest(BaseModel):
    job_id: str
    panels: list[dict]  # List of panel objects with index, caption, image_prompt, characters, is_placeholder


class UpdateCharacterRequest(BaseModel):
    job_id: str
    character_bible: str


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
    """Process a single comic generation job.
    
    Workflow:
    1. Synopsis generation (for random/themed modes) or wait for user input (custom mode)
    2. Story synopsis confirmation
    3. Reference profile generation (no panels)
    4. WAIT for user to proceed to style/reference
    5. Style/reference image generation
    6. WAIT for user to proceed to panel breakdown
    7. Panel breakdown (allow editing)
    8. Panel image generation
    """
    logger.info(f"--- START PROCESSING JOB {job.job_id} ---")
    log_system_resources(f"JOB-{job.job_id}-START")
    loop = asyncio.get_event_loop()

    try:
        # ========================================
        # STEP 1: Generate synopsis (random/themed modes) or wait for user (custom mode)
        # ========================================
        if job.mode in ("random", "themed"):
            job.stage = "synopsis"
            job.status = JobStatus.GENERATING_SYNOPSIS
            job.progress_current = 0
            job.progress_total = 1
            await broadcast_job_update(job)

            theme = job.input_text if job.mode == "themed" else None
            synopsis = await loop.run_in_executor(
                None, text_gen.generate_random_synopsis, theme
            )
            job.input_text = synopsis
            logger.info(f"Generated synopsis: {synopsis}")
        
        # For custom mode, synopsis is the input text itself
        if job.mode == "custom":
            job.stage = "synopsis"
            job.status = JobStatus.GENERATING_SYNOPSIS
            job.progress_current = 0
            job.progress_total = 1
            await broadcast_job_update(job)
            # Story text becomes the synopsis for custom mode
            logger.info(f"Using custom input as synopsis")
        
        # For fullstory mode, extract synopsis from the full story text
        if job.mode == "fullstory":
            job.stage = "synopsis"
            job.status = JobStatus.GENERATING_SYNOPSIS
            job.progress_current = 0
            job.progress_total = 1
            await broadcast_job_update(job)
            
            prompt = (
                f"Extract a fun children's comic book synopsis (5-8 sentences) "
                f"from this full story text. Include a clear situation/setup, conflict/action, and a short resolution. "
                f"Focus on the main characters, setting, and key events. "
                f"Respond with ONLY the synopsis text, nothing else.\n\n"
                f"Story text:\n{job.input_text}"
            )
            synopsis = await loop.run_in_executor(
                None, lambda: text_gen.generate(prompt, max_tokens=500)
            )
            job.input_text = synopsis
            logger.info(f"Extracted synopsis from full story: {synopsis}")

        # Generate a title from the synopsis
        logger.info(f"Generating title for job {job.job_id}...")
        title = await loop.run_in_executor(
            None, text_gen.generate_title, job.input_text
        )
        logger.info(f"Generated title: {title}")

        # ========================================
        # STEP 2: Show synopsis for user confirmation (NO panels yet)
        # ========================================
        job.stage = "story"
        job.status = JobStatus.GENERATING_STORY
        job.progress_current = 1
        job.progress_total = 1
        
        # Create a minimal story object with synopsis (no panels yet)
        from generator import ComicStory
        job.story = ComicStory(
            title=title,
            synopsis=job.input_text,
            art_style="",  # Will be generated later
            character_bible="",  # Will be generated later
            panels=[],  # No panels yet - waiting for confirmation
        )
        
        await broadcast_job_update(job)
        logger.info(f"Synopsis generated, waiting for user confirmation")

        # ========================================
        # STEP 2b: WAIT for user to confirm synopsis before preparing reference metadata
        # ========================================
        job.stage = "synopsis_confirmation"
        job.status = JobStatus.GENERATING_STORY
        job.wait_for_user = True
        await broadcast_job_update(job)

        # Wait for user to confirm the synopsis
        while job.wait_for_user and not job.cancel_requested:
            await asyncio.sleep(2.0)
            await broadcast_job_update(job)

        if job.cancel_requested:
            job.status = JobStatus.ERROR
            job.error = "Generation cancelled by user"
            await broadcast_job_update(job)
            return

        job.wait_for_user = False

        # ========================================
        # STEP 2c: Generate reference metadata AFTER synopsis confirmation (NO panels yet)
        # ========================================
        job.stage = "story"
        job.status = JobStatus.GENERATING_STORY
        job.progress_current = 0
        job.progress_total = 1
        await broadcast_job_update(job)

        story = await loop.run_in_executor(
            None, lambda: text_gen.generate_reference_profile(job.input_text, title)
        )
        job.story = story
        logger.info(f"Reference profile generated: {story.title} ({len(story.panels)} panels)")
        await broadcast_job_update(job)
        save_jobs()

        # ========================================
        # STEP 3: WAIT for user to proceed to style/reference
        # ========================================
        job.stage = "reference"
        job.status = JobStatus.GENERATING_REFERENCE
        job.wait_for_user = True
        await broadcast_job_update(job)

        # Wait for user to signal they want to proceed
        while job.wait_for_user and not job.cancel_requested:
            await asyncio.sleep(2.0)
            await broadcast_job_update(job)

        if job.cancel_requested:
            job.status = JobStatus.ERROR
            job.error = "Generation cancelled by user"
            await broadcast_job_update(job)
            return

        job.wait_for_user = False

        # NOTE: Reference image generation is now handled separately via /api/generate-reference
        # so the user can regenerate it as many times as they want without advancing the job state.
        
        # ========================================
        # STEP 5: WAIT for user to proceed to panel breakdown
        # ========================================
        if job.stage != "panels":
            job.stage = "panel_breakdown"
            job.status = JobStatus.PANEL_BREAKDOWN
            job.wait_for_user = True
            await broadcast_job_update(job)

            # Wait for user to signal they want to proceed
            while job.wait_for_user and not job.cancel_requested:
                await asyncio.sleep(2.0)
                await broadcast_job_update(job)

            if job.cancel_requested:
                job.status = JobStatus.ERROR
                job.error = "Generation cancelled by user"
                await broadcast_job_update(job)
                return

            job.wait_for_user = False

        # ========================================
        # STEP 6: Panel breakdown (editable stage)
        # ========================================
        story = job.story
        if not story or not story.panels:
            raise ValueError("Panel breakdown has not been generated yet")

        # The story has panels at this point - user may have edited/confirmed them.
        job.stage = "panels"
        await broadcast_job_update(job)

        # ========================================
        # STEP 7: Generate panel images
        # ========================================
        # Only count non-placeholder panels for progress
        real_panels = [p for p in story.panels if not p.is_placeholder]
        job.progress_total = len(real_panels)
        job.progress_current = 0
        job.status = JobStatus.GENERATING_PANELS
        await broadcast_job_update(job)

        for panel in story.panels:
            # Skip placeholder panels - they need user input before generating images
            if panel.is_placeholder:
                logger.info(f"Skipping placeholder panel {panel.index + 1}")
                continue
            
            # Check for cancel request
            if job.cancel_requested:
                job.status = JobStatus.ERROR
                job.error = "Generation cancelled by user"
                await broadcast_job_update(job)
                logger.info(f"Job {job.job_id} cancelled by user")
                return

            log_system_resources(f"JOB-{job.job_id}-PANEL-{panel.index}")
            def generate_single_panel(p=panel):
                gen_w, gen_h = _panel_gen_dims(p.index)
                p.image = img_gen.generate(
                    prompt=_panel_prompt(story, p),
                    width=gen_w,
                    height=gen_h,
                    reference_image=story.master_reference,
                )

            await loop.run_in_executor(None, generate_single_panel)
            job.progress_current += 1

            # Brief breather between GPU jobs
            await asyncio.sleep(0.5)

            # Generate thumbnail for WebSocket preview
            if panel.image:
                job.panel_thumbnails[panel.index] = _image_to_base64(
                    panel.image, max_size=256
                )
                save_jobs()

            await broadcast_job_update(job)

        # Step 4: Done
        job.stage = "complete"
        job.status = JobStatus.COMPLETE
        await broadcast_job_update(job)
        save_jobs()
        logger.info(f"Job {job.job_id} complete: {story.title}")

    except Exception as e:
        logger.error(f"Job {job.job_id} failed: {e}", exc_info=True)
        job.status = JobStatus.ERROR
        job.error = str(e)
        job.wait_for_user = False
        save_jobs()
        await broadcast_job_update(job)


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
    """Send job status update to all connected WebSocket clients.
    The payload now includes a `type` field to indicate the nature of the update:
    - "progress" for regular progress updates.
    - "complete" when the master reference image is ready.
    - "error" when an error occurs.
    """
    # Save jobs on any state update
    # save_jobs() # Decoupled from broadcast to avoid excessive I/O

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
    queued_ids = list(job_queue._queue)
    if job_id in queued_ids:
        return queued_ids.index(job_id) + 1
    return 0


def _make_slug(title: str) -> str:
    """Convert a title to a URL-friendly slug."""
    slug = title.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    slug = slug.strip('-')
    return slug[:50] if slug else str(uuid.uuid4())[:8]


def _make_project_slug(job_id: str) -> str:
    """Create a stable URL slug for a project before its title exists."""
    return f"project-{job_id[:8]}"


def _find_job(ref: str) -> Optional[ComicJob]:
    """Find a job by id or URL slug."""
    return jobs.get(ref) or next((j for j in jobs.values() if j.slug == ref), None)


# ── API Routes ───────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the main SPA."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return index_path.read_text()


@app.get("/project", response_class=HTMLResponse)
async def serve_project_no_slug():
    """Redirect /project to create page."""
    return await serve_index()


@app.get("/project/{slug}", response_class=HTMLResponse)
async def serve_project(slug: str):
    """Serve SPA for project by slug — frontend handles routing."""
    return await serve_index()


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


@app.get("/api/recent")
async def list_recent_jobs():
    """List recent projects for the home page, including in-progress work."""
    recent = sorted(
        [j for j in jobs.values() if j.slug],
        key=lambda j: j.created_at,
        reverse=True
    )[:10]
    return [
        {
            "job_id": j.job_id,
            "slug": j.slug,
            "title": j.story.title if j.story else "Untitled",
            "created_at": j.created_at,
            "mode": j.mode,
            "status": j.status.value,
            "stage": j.stage,
        }
        for j in recent
    ]


@app.get("/project/{slug}")
async def get_job_by_slug(slug: str):
    """Redirect to index for SPA routing by slug."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return index_path.read_text()


@app.get("/api/status/slug/{slug}")
async def get_job_status_by_slug(slug: str):
    """Get job status by slug."""
    job = _find_job(slug)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    result = {
        "job_id": job.job_id,
        "slug": job.slug,
        "status": job.status.value,
        "stage": job.stage,
        "mode": job.mode,
        "synopsis": job.input_text,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "error": job.error,
        "queue_position": _get_queue_position(job.job_id),
        "wait_for_user": job.wait_for_user,
        "has_reference": job.story.master_reference is not None if job.story else False,
    }
    if job.story:
        result["story"] = {
            "title": job.story.title,
            "synopsis": job.story.synopsis,
            "art_style": job.story.art_style,
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
    return result


@app.get("/api/status/{job_id}")
async def get_job_status(job_id: str):
    """Get the status of a job."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = {
        "job_id": job.job_id,
        "slug": job.slug,
        "status": job.status.value,
        "stage": job.stage,
        "mode": job.mode,
        "synopsis": job.input_text,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "error": job.error,
        "queue_position": _get_queue_position(job.job_id),
        "wait_for_user": job.wait_for_user,
        "has_reference": job.story.master_reference is not None if job.story else False,
    }
    if job.story:
        result["story"] = {
            "title": job.story.title,
            "synopsis": job.story.synopsis,
            "art_style": job.story.art_style,
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


@app.post("/api/generate")
async def api_generate(req: GenerateRequest):
    """Start a new comic generation job."""
    if not models_loaded:
        raise HTTPException(status_code=503, detail="Models still loading")

    job_id = str(uuid.uuid4())
    job = ComicJob(
        job_id=job_id,
        status=JobStatus.QUEUED,
        mode=req.mode,
        input_text=req.text,
        created_at=time.time(),
        slug=_make_project_slug(job_id),
    )
    jobs[job_id] = job
    job_queue.put_nowait(job_id)
    save_jobs()
    logger.info(f"New job created: {job_id} (mode={req.mode})")
    return {"job_id": job_id, "slug": job.slug}


@app.post("/api/cancel/{job_id}")
async def api_cancel(job_id: str):
    """Request cancellation of a running job."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.cancel_requested = True
    save_jobs()
    return {"status": "cancelled"}


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
    save_jobs()

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
    save_jobs()
    return {"status": "ok"}


@app.post("/api/update-title")
async def api_update_title(req: UpdateTitleRequest):
    """Update the comic title."""
    job = jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    job.story.title = req.title
    save_jobs()
    return {"status": "ok"}


@app.post("/api/update-synopsis")
async def api_update_synopsis(req: UpdateSynopsisRequest):
    """Update the comic synopsis."""
    job = jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    job.story.synopsis = req.synopsis
    save_jobs()
    return {"status": "ok"}


@app.post("/api/update-art-style")
async def api_update_art_style(req: UpdateArtStyleRequest):
    """Update the art style for a job."""
    job = jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    job.story.art_style = req.art_style
    save_jobs()
    return {"status": "ok"}


@app.post("/api/generate-synopsis")
async def api_generate_synopsis(req: GenerateSynopsisRequest):
    """Extract synopsis from full story text (for full story mode/custom mode)."""
    if not models_loaded:
        raise HTTPException(status_code=503, detail="Models still loading")

    loop = asyncio.get_event_loop()
    
    prompt = (
        f"Extract a fun children's comic book synopsis (5-8 sentences) "
        f"from this full story text. Include a clear situation/setup, conflict/action, and a short resolution. "
        f"Focus on the main characters, setting, and key events. "
        f"Respond with ONLY the synopsis text, nothing else.\n\n"
        f"Story text:\n{req.full_story}"
    )

    synopsis = await loop.run_in_executor(
        None,
        lambda: text_gen.generate(prompt, max_tokens=500)
    )
    
    return {"synopsis": synopsis}


@app.post("/api/generate-panel-breakdown/{job_id}")
async def api_generate_panel_breakdown(job_id: str):
    """Break synopsis into 6 panels (for panel breakdown step).
    
    This regenerates the panel breakdown for an existing job's synopsis.
    Useful when the user wants to redo the panel structure.
    """
    if not models_loaded:
        raise HTTPException(status_code=503, detail="Models still loading")

    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    loop = asyncio.get_event_loop()
    
    previous_story = job.story

    # Generate the panel breakdown from current synopsis/input_text.
    story = await loop.run_in_executor(
        None, text_gen.generate_story, job.input_text
    )
    if previous_story:
        story.master_reference = previous_story.master_reference
        if previous_story.title:
            story.title = previous_story.title
        if previous_story.art_style:
            story.art_style = previous_story.art_style
        if previous_story.character_bible:
            story.character_bible = previous_story.character_bible
        if previous_story.characters:
            story.characters = previous_story.characters

    job.story = story
    job.stage = "panel_breakdown"
    job.status = JobStatus.PANEL_BREAKDOWN
    if not job.slug:
        job.slug = _make_project_slug(job.job_id)
    save_jobs()
    
    await broadcast_job_update(job)
    return {
        "status": "ok",
        "panels": len(story.panels),
        "breakdown": [
            {
                "index": p.index,
                "caption": p.caption,
                "image_prompt": p.image_prompt,
                "characters": p.characters,
                "has_image": p.image is not None,
                "is_placeholder": p.is_placeholder,
            }
            for p in story.panels
        ],
    }


@app.post("/api/generate-reference/{job_id}")
async def api_generate_reference(job_id: str):
    """Explicitly generate the master reference image."""
    global img_gen
    
    if not models_loaded:
        raise HTTPException(status_code=503, detail="Models still loading")
    
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    if not job.story:
        raise HTTPException(status_code=400, detail="Story not generated yet")
        
    # Queue reference generation as a background task
    asyncio.create_task(_generate_reference_task(job))
    
    return {"status": "ok", "message": "Reference generation started"}

async def _generate_reference_task(job: ComicJob):
    """Background task to generate master reference image."""
    global img_gen
    loop = asyncio.get_event_loop()
    
    job.status = JobStatus.GENERATING_REFERENCE
    job.progress_current = 0
    job.progress_total = 1
    job.error = None
    await broadcast_job_update(job)
    
    from generator import generate_master_reference
    
    try:
        logger.info(f"Job {job.job_id}: generating master character reference...")
        log_system_resources(f"JOB-{job.job_id}-MASTER-REF")
        
        await loop.run_in_executor(None, generate_master_reference, job.story, img_gen)
        await asyncio.sleep(0.5)
        
        job.progress_current = 1
        # Leave status as GENERATING_REFERENCE so the stage stays "reference" 
        # waiting for the user to proceed.
        save_jobs()
        await broadcast_job_update(job)
        
    except Exception as e:
        logger.error(f"Failed to generate master reference: {e}", exc_info=True)
        job.status = JobStatus.ERROR
        job.error = f"Failed to generate master reference: {e}"
        save_jobs()
        await broadcast_job_update(job)

@app.post("/api/generate-panels/{job_id}")
async def api_generate_panels(job_id: str):
    """Generate panel images for a job that's at the panel stage.
    
    This endpoint triggers background generation of panel images for all
    non-placeholder panels that don't have images yet.
    """
    global img_gen
    
    if not models_loaded:
        raise HTTPException(status_code=503, detail="Models still loading")
    
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if not job.story or not job.story.master_reference:
        raise HTTPException(status_code=400, detail="Master reference not generated yet")
    
    # Check if already generating panels
    if job.status == JobStatus.GENERATING_PANELS:
        return {"status": "ok", "message": "Already generating panels"}
    
    # Queue panel generation as a background task
    asyncio.create_task(_generate_panels_task(job))
    
    return {"status": "ok", "message": "Panel generation started"}


async def _generate_panels_task(job: ComicJob):
    """Background task to generate panel images."""
    global img_gen
    loop = asyncio.get_event_loop()
    story = job.story
    
    try:
        # Count non-placeholder panels that need images
        panels_needing_images = [
            p for p in story.panels 
            if not p.is_placeholder and p.image is None
        ]
        
        if not panels_needing_images:
            job.stage = "complete"
            job.status = JobStatus.COMPLETE
            save_jobs()
            await broadcast_job_update(job)
            return
        
        job.status = JobStatus.GENERATING_PANELS
        job.progress_total = len(panels_needing_images)
        job.progress_current = 0
        job.error = None
        job.cancel_requested = False
        await broadcast_job_update(job)
        
        from generator import (
            _panel_prompt,
            _panel_gen_dims,
        )
        
        for panel in story.panels:
            # Skip placeholder panels or panels that already have images
            if panel.is_placeholder or panel.image is not None:
                continue
            
            # Check for cancel request
            if job.cancel_requested:
                job.status = JobStatus.ERROR
                job.error = "Generation cancelled by user"
                await broadcast_job_update(job)
                return
            
            log_system_resources(f"JOB-{job.job_id}-PANEL-{panel.index}")
            
            def generate_single_panel(p=panel):
                gen_w, gen_h = _panel_gen_dims(p.index)
                p.image = img_gen.generate(
                    prompt=_panel_prompt(story, p),
                    width=gen_w,
                    height=gen_h,
                    reference_image=story.master_reference,
                )
            
            await loop.run_in_executor(None, generate_single_panel)
            job.progress_current += 1
            
            # Brief breather between GPU jobs
            await asyncio.sleep(0.5)
            
            # Generate thumbnail for WebSocket preview
            if panel.image:
                job.panel_thumbnails[panel.index] = _image_to_base64(
                    panel.image, max_size=256
                )
                save_jobs()
            
            await broadcast_job_update(job)
        
        # All done
        job.stage = "complete"
        job.status = JobStatus.COMPLETE
        save_jobs()
        await broadcast_job_update(job)
        logger.info(f"Job {job.job_id} panel generation complete")
        
    except Exception as e:
        logger.error(f"Panel generation failed for job {job.job_id}: {e}", exc_info=True)
        job.status = JobStatus.ERROR
        job.error = str(e)
        save_jobs()
        await broadcast_job_update(job)


@app.post("/api/proceed/{job_id}")
async def api_proceed_to_next_stage(job_id: str):
    """Signal the job to proceed to the next stage (user clicked 'Next')."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Validate that master reference exists before proceeding past reference stage
    if job.stage == "reference":
        if not job.story or not job.story.master_reference:
            raise HTTPException(status_code=400, detail="Master reference not generated successfully - cannot proceed to panel breakdown")
    elif job.stage == "panel_breakdown":
        if not job.story or not job.story.panels:
            raise HTTPException(status_code=400, detail="Panel breakdown has not been generated yet")
        job.stage = "panels"
    
    job.wait_for_user = False
    logger.info(f"Job {job_id}: user requested to proceed from stage '{job.stage}'")
    save_jobs()
    return {"status": "ok", "stage": job.stage}


@app.post("/api/update-panel")
async def api_update_panel(req: UpdatePanelRequest):
    """Update individual panel content (caption or image_prompt)."""
    job = jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    if req.panel_index < 0 or req.panel_index >= len(job.story.panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")

    panel = job.story.panels[req.panel_index]
    if req.caption is not None:
        panel.caption = req.caption
    if req.image_prompt is not None:
        panel.image_prompt = req.image_prompt
    
    # Clear placeholder flag if panel has real content (not just placeholders)
    if panel.is_placeholder:
        # Check if the content is no longer placeholder text
        is_still_placeholder = (
            (not panel.caption or panel.caption.startswith("[Placeholder")) or
            (not panel.image_prompt or panel.image_prompt.startswith("[Placeholder"))
        )
        if not is_still_placeholder:
            panel.is_placeholder = False
            logger.info(f"Cleared placeholder flag for panel {req.panel_index + 1}")
    
    save_jobs()
    return {"status": "ok", "panel_index": req.panel_index}


@app.post("/api/update-panels")
async def api_update_panels(req: UpdatePanelsRequest):
    """Update all panels at once (used when saving panel breakdown edits)."""
    job = jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")
    
    for panel_data in req.panels:
        idx = panel_data.get("index")
        if idx is None or idx < 0 or idx >= len(job.story.panels):
            continue
        
        panel = job.story.panels[idx]
        if "caption" in panel_data:
            panel.caption = panel_data["caption"]
        if "image_prompt" in panel_data:
            panel.image_prompt = panel_data["image_prompt"]
        if "characters" in panel_data:
            panel.characters = panel_data["characters"]
        if "is_placeholder" in panel_data:
            panel.is_placeholder = panel_data["is_placeholder"]
        else:
            # Auto-detect if panel is still placeholder based on content
            is_still_placeholder = (
                (not panel.caption or panel.caption.startswith("[Placeholder")) or
                (not panel.image_prompt or panel.image_prompt.startswith("[Placeholder"))
            )
            panel.is_placeholder = is_still_placeholder
    
    logger.info(f"Updated {len(req.panels)} panels for job {req.job_id}")
    save_jobs()
    return {"status": "ok", "panels_updated": len(req.panels)}


@app.post("/api/update-character")
async def api_update_character(req: UpdateCharacterRequest):
    """Update character descriptions for reference generation."""
    job = jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    job.story.character_bible = req.character_bible
    save_jobs()
    return {"status": "ok"}


@app.get("/api/master-reference/{slug}")
async def get_master_reference_by_slug(slug: str):
    """Get the master reference image by slug."""
    job = _find_job(slug)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.story.master_reference:
        raise HTTPException(status_code=404, detail="Master reference not generated yet")

    buf = io.BytesIO()
    job.story.master_reference.convert("RGB").save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/jpeg")


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
    job = _find_job(job_id)
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


@app.get("/api/master-reference/{job_id}")
async def get_master_reference(job_id: str):
    """Inspect the hidden master character-reference image for a job.

    Useful for debugging character consistency: if panels look wrong,
    check whether the reference itself is what you expected.
    """
    job = _find_job(job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.story.master_reference:
        raise HTTPException(status_code=404, detail="Master reference not generated yet")

    buf = io.BytesIO()
    job.story.master_reference.convert("RGB").save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/jpeg")


@app.get("/{slug}", response_class=HTMLResponse)
async def serve_slug_route(slug: str):
    """Serve the SPA for direct project slug URLs."""
    if slug == "api":
        raise HTTPException(status_code=404, detail="Not found")
    return await serve_index()


@app.get("/{slug}/{page}", response_class=HTMLResponse)
async def serve_slug_step_route(slug: str, page: str):
    """Serve the SPA for project step URLs like /project-abc123/panelImages."""
    if slug == "api":
        raise HTTPException(status_code=404, detail="Not found")
    return await serve_index()


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
