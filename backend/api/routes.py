"""
routes.py — All API route handlers for the backend.
"""

import asyncio
import io
import json
import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse

from generator import (
    Character,
    render_page,
    generate_master_reference,
    generate_all_panels,
    regenerate_panel,
)

from ..config import STATIC_DIR, OUTPUT_DIR, JOB_ASSETS_DIR
from ..models import (
    JobStatus, ComicJob,
    GenerateRequest, RegeneratePanelRequest, UpdateCharactersRequest,
    UpdateCaptionRequest, UpdateTitleRequest, UpdateSynopsisRequest,
    UpdateArtStyleRequest, UpdateStorySettingRequest,
    GenerateSynopsisRequest, UpdatePanelRequest,
    UpdatePanelsRequest, UpdateCharacterRequest,
)
from .. import state as global_state
from ..persistence import save_jobs, delete_job_assets
from ..utils import _image_to_base64, _find_job, _make_project_slug, log_system_resources
from ..broadcasting import (
    broadcast_job_update,
    broadcast_image_generating,
    _make_step_callback,
)
from ..jobs import process_job

logger = logging.getLogger("comic-server")
router = APIRouter()


def _delete_reference_asset(job_id: str) -> None:
    ref_path = JOB_ASSETS_DIR / job_id / "master_reference.jpg"
    if ref_path.exists():
        ref_path.unlink()


def _delete_panel_asset(job_id: str, panel_index: int) -> None:
    panel_path = JOB_ASSETS_DIR / job_id / f"panel_{panel_index}.jpg"
    if panel_path.exists():
        panel_path.unlink()


def _delete_all_panel_assets(job_id: str) -> None:
    assets_dir = JOB_ASSETS_DIR / job_id
    if not assets_dir.exists():
        return
    for panel_path in assets_dir.glob("panel_*.jpg"):
        panel_path.unlink()


def _mark_panel_image_invalid(job, panel_index: int) -> None:
    if not job.story or panel_index >= len(job.story.panels):
        return
    job.story.panels[panel_index].image = None
    job.panel_thumbnails.pop(panel_index, None)
    _delete_panel_asset(job.job_id, panel_index)
    if job.stage == "complete":
        job.stage = "panels"
        job.status = JobStatus.READY


def _get_job_tasks(job_id: str) -> dict[str, asyncio.Task]:
    return global_state.job_tasks.setdefault(job_id, {})


def _task_is_running(job_id: str, name: str) -> bool:
    task = global_state.job_tasks.get(job_id, {}).get(name)
    return bool(task and not task.done())


def _start_job_task(job_id: str, name: str, coro_factory):
    tasks = _get_job_tasks(job_id)
    existing = tasks.get(name)
    if existing and not existing.done():
        return existing, False

    task = asyncio.create_task(coro_factory())
    tasks[name] = task

    def cleanup(done_task):
        current = global_state.job_tasks.get(job_id, {}).get(name)
        if current is done_task:
            global_state.job_tasks.get(job_id, {}).pop(name, None)

    task.add_done_callback(cleanup)
    return task, True


# ── Static File Routes ─────────────────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the main SPA."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return index_path.read_text()


@router.get("/project", response_class=HTMLResponse)
async def serve_project_no_slug():
    """Redirect /project to create page."""
    return await serve_index()


@router.get("/project/{slug}", response_class=HTMLResponse)
async def serve_project(slug: str):
    """Serve SPA for project by slug — frontend handles routing."""
    return await serve_index()


# ── Health and Status Routes ─────────────────────────────────────────────────
@router.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok" if global_state.models_loaded else "loading",
        "models_loaded": global_state.models_loaded,
        "models_loading": global_state.models_loading,
        "active_jobs": len([
            j for j in global_state.jobs.values()
            if j.status in (
                JobStatus.QUEUED,
                JobStatus.GENERATING_SYNOPSIS,
                JobStatus.GENERATING_STORY,
                JobStatus.GENERATING_REFERENCE,
                JobStatus.GENERATING_PANELS,
            )
        ]),
    }


@router.get("/api/recent")
async def list_recent_jobs():
    """List recent projects for the home page, including in-progress work."""
    recent = sorted(
        [j for j in global_state.jobs.values() if j.slug],
        key=lambda j: j.created_at,
        reverse=True
    )
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


@router.get("/api/status/slug/{slug}")
async def get_job_status_by_slug(slug: str):
    """Get job status by slug."""
    job = _find_job(slug)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _build_job_status_response(job)


@router.get("/api/status/{job_id}")
async def get_job_status(job_id: str):
    """Get the status of a job."""
    job = global_state.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _build_job_status_response(job)


def _build_job_status_response(job):
    """Build the job status response dict."""
    tasks = global_state.job_tasks.get(job.job_id, {})
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
        "wait_for_user": job.wait_for_user,
        "has_reference": job.story.master_reference is not None if job.story else False,
        "operations": {
            name: not task.done()
            for name, task in tasks.items()
        },
    }
    if job.story:
        result["story"] = {
            "title": job.story.title,
            "synopsis": job.story.synopsis,
            "art_style": job.story.art_style,
            # New shared world-anchor; defaults to "" on older saved jobs.
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
    return result


# ── WebSocket Routes ─────────────────────────────────────────────────────────
@router.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """WebSocket for real-time job progress updates."""
    await websocket.accept()

    # Thread-safe registration of websocket
    async with global_state._ws_lock:
        if job_id not in global_state.active_websockets:
            global_state.active_websockets[job_id] = []
        global_state.active_websockets[job_id].append(websocket)

    try:
        job = global_state.jobs.get(job_id)
        if job:
            await broadcast_job_update(job)

        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        async with global_state._ws_lock:
            ws_list = global_state.active_websockets.get(job_id, [])
            if websocket in ws_list:
                ws_list.remove(websocket)


# ── Job Management Routes ────────────────────────────────────────────────────
@router.post("/api/generate")
async def api_generate(req: GenerateRequest):
    """Start a new comic generation job."""
    if not global_state.models_loaded:
        raise HTTPException(status_code=503, detail="Models still loading")

    job_id = str(uuid.uuid4())
    job = ComicJob(
        job_id=job_id,
        status=JobStatus.GENERATING_SYNOPSIS,
        mode=req.mode,
        input_text=req.text,
        created_at=time.time(),
        slug=_make_project_slug(job_id),
        randomness_level=req.randomness_level,
    )
    global_state.jobs[job_id] = job
    save_jobs()  # Persist immediately for recovery on refresh
    logger.info(f"New job created: {job_id} (mode={req.mode}, randomness={req.randomness_level})")
    
    # Start autonomous story/profile initialization. Later stages are explicit
    # API calls so browser tabs do not drive backend control flow.
    _start_job_task(job_id, "initial", lambda: process_job(job))
    
    return {"job_id": job_id, "slug": job.slug}


@router.post("/api/cancel/{job_id}")
async def api_cancel(job_id: str):
    """Request cancellation of a running job."""
    job = global_state.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.cancel_requested = True
    save_jobs()
    return {"status": "cancelled"}


@router.delete("/api/project/{slug}")
async def api_delete_project(slug: str):
    """Delete a project and all its assets."""
    job = _find_job(slug)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job_id = job.job_id
    for task in global_state.job_tasks.get(job_id, {}).values():
        if not task.done():
            task.cancel()
    global_state.job_tasks.pop(job_id, None)
    
    # Delete assets directory first
    delete_job_assets(job_id)
    
    # Remove job from memory
    del global_state.jobs[job_id]
    
    # Persist changes
    save_jobs()
    
    logger.info(f"Deleted project {slug} (job_id: {job_id})")
    return {"status": "deleted", "slug": slug}


# ── Panel Routes ─────────────────────────────────────────────────────────────
@router.post("/api/regenerate-panel")
async def api_regenerate_panel(req: RegeneratePanelRequest):
    """Regenerate a single panel."""
    if not global_state.models_loaded:
        raise HTTPException(status_code=503, detail="Models still loading")

    job = global_state.jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found or not complete")

    if req.panel_index < 0 or req.panel_index >= len(job.story.panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")

    await broadcast_image_generating(job, "panel", req.panel_index)

    loop = asyncio.get_event_loop()
    modification = req.modification if req.modification else None
    step_cb = _make_step_callback(req.job_id, "panel", req.panel_index)

    await loop.run_in_executor(
        None,
        regenerate_panel,
        job.story,
        req.panel_index,
        global_state.img_gen,
        modification,
        step_cb,
    )

    panel = job.story.panels[req.panel_index]
    if panel.image:
        job.panel_thumbnails[req.panel_index] = _image_to_base64(panel.image, max_size=256)
    save_jobs()
    await broadcast_job_update(job)

    return {"status": "ok", "panel_index": req.panel_index}


@router.post("/api/update-caption")
async def api_update_caption(req: UpdateCaptionRequest):
    """Update a panel's caption text."""
    job = global_state.jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    if req.panel_index < 0 or req.panel_index >= len(job.story.panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")

    job.story.panels[req.panel_index].caption = req.caption
    save_jobs()
    return {"status": "ok"}


@router.post("/api/update-title")
async def api_update_title(req: UpdateTitleRequest):
    """Update the comic title."""
    job = global_state.jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    job.story.title = req.title
    save_jobs()
    return {"status": "ok"}


@router.post("/api/update-synopsis")
async def api_update_synopsis(req: UpdateSynopsisRequest):
    """Update the comic synopsis."""
    job = global_state.jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    job.story.synopsis = req.synopsis
    job.input_text = req.synopsis
    job.story.character_bible = ""
    job.story.characters = []
    job.story.master_reference = None
    job.story.panels = []
    job.panel_thumbnails.clear()
    _delete_reference_asset(req.job_id)
    _delete_all_panel_assets(req.job_id)
    job.stage = "story"
    job.status = JobStatus.READY
    save_jobs()
    return {"status": "ok"}


@router.post("/api/update-art-style")
async def api_update_art_style(req: UpdateArtStyleRequest):
    """Update the art style for a job."""
    job = global_state.jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    logger.info(f"Updating art style for job {req.job_id} to: {req.art_style}")
    if job.story.art_style != req.art_style:
        job.story.art_style = req.art_style
        job.story.master_reference = None
        for panel in job.story.panels:
            panel.image = None
        job.panel_thumbnails.clear()
        _delete_reference_asset(req.job_id)
        _delete_all_panel_assets(req.job_id)
        if job.stage in ("panel_breakdown", "panels", "complete"):
            job.stage = "reference"
            job.status = JobStatus.READY
    save_jobs()
    return {"status": "ok"}


@router.post("/api/update-story-setting")
async def api_update_story_setting(req: UpdateStorySettingRequest):
    """Update the shared world/setting anchor for a job.

    The story_setting is injected into every panel prompt as a world anchor
    (location, time of day, mood, lighting). Editing it lets the user steer
    the visual world without rewriting each panel's scene description.
    """
    job = global_state.jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    logger.info(f"Updating story setting for job {req.job_id}")
    if getattr(job.story, "story_setting", "") != req.story_setting:
        job.story.story_setting = req.story_setting
        job.story.master_reference = None
        for panel in job.story.panels:
            panel.image = None
        job.panel_thumbnails.clear()
        _delete_reference_asset(req.job_id)
        _delete_all_panel_assets(req.job_id)
        if job.stage in ("panel_breakdown", "panels", "complete"):
            job.stage = "reference"
            job.status = JobStatus.READY
    save_jobs()
    return {"status": "ok"}


@router.post("/api/update-characters")
async def api_update_characters(req: UpdateCharactersRequest):
    """Update the character list for a job."""
    job = global_state.jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    logger.info(f"Updating characters for job {req.job_id}")
    new_chars = []
    for cdict in req.characters:
        new_chars.append(Character(name=cdict.get("name", ""), description=cdict.get("description", "")))

    job.story.characters = new_chars
    save_jobs()
    return {"status": "ok"}


@router.post("/api/generate-synopsis")
async def api_generate_synopsis(req: GenerateSynopsisRequest):
    """Extract synopsis from full story text (for full story mode/custom mode)."""
    if not global_state.models_loaded:
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
        lambda: global_state.text_gen.generate(prompt, max_tokens=500)
    )

    return {"synopsis": synopsis}


@router.post("/api/generate-panel-breakdown/{job_id}")
async def api_generate_panel_breakdown(job_id: str):
    """Break synopsis into 6 panels (for panel breakdown step)."""
    if not global_state.models_loaded:
        raise HTTPException(status_code=503, detail="Models still loading")

    job = global_state.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    loop = asyncio.get_event_loop()

    previous_story = job.story
    story = await loop.run_in_executor(
        None, global_state.text_gen.generate_story, job.input_text
    )
    if previous_story:
        story.master_reference = previous_story.master_reference
        if previous_story.title:
            story.title = previous_story.title
        if previous_story.art_style:
            story.art_style = previous_story.art_style
        # Preserve the world anchor from Step 3 — user may have edited it
        # there, and we don't want generate_story's fresh sample to clobber
        # their edit. getattr keeps us safe loading older saved jobs.
        prev_setting = getattr(previous_story, "story_setting", "")
        if prev_setting:
            story.story_setting = prev_setting
        if previous_story.character_bible:
            story.character_bible = previous_story.character_bible
        if previous_story.characters:
            story.characters = previous_story.characters

    job.story = story
    job.panel_thumbnails.clear()
    _delete_all_panel_assets(job_id)
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


@router.post("/api/generate-reference/{job_id}")
async def api_generate_reference(job_id: str):
    """Explicitly generate the master reference image."""
    if not global_state.models_loaded:
        raise HTTPException(status_code=503, detail="Models still loading")

    job = global_state.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job.story:
        raise HTTPException(status_code=400, detail="Story not generated yet")

    _, started = _start_job_task(job_id, "reference", lambda: _generate_reference_task(job))
    if not started:
        return {"status": "ok", "message": "Reference generation already running"}
    return {"status": "ok", "message": "Reference generation started"}


@router.post("/api/regenerate-story-profile/{job_id}")
async def api_regenerate_story_profile(job_id: str):
    """Re-run the LLM character/style/world profile pass.

    Useful when an earlier run left the project with no parseable
    characters (the old parser was broken on compound words like
    ``palm-sized``, which produced garbage character names and made
    the reference image come out blank). Re-running with the current
    parser usually rescues the project without forcing a full restart.

    Preserves the user's edited title / synopsis / panels / master
    reference if they exist — only the AI-generated profile fields
    (art_style, story_setting, character_bible, characters) are
    replaced.
    """
    if not global_state.models_loaded:
        raise HTTPException(status_code=503, detail="Models still loading")

    job = global_state.jobs.get(job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    loop = asyncio.get_event_loop()
    synopsis = job.story.synopsis or job.input_text
    title = job.story.title or "Untitled"

    new_profile = await loop.run_in_executor(
        None,
        lambda: global_state.text_gen.generate_reference_profile(synopsis, title),
    )

    # Surgically replace just the AI-generated profile fields; leave
    # user-owned and downstream-generated state alone.
    job.story.art_style = new_profile.art_style
    job.story.story_setting = new_profile.story_setting
    job.story.character_bible = new_profile.character_bible
    job.story.characters = new_profile.characters
    job.story.master_reference = None
    for panel in job.story.panels:
        panel.image = None
    job.panel_thumbnails.clear()
    _delete_reference_asset(job_id)
    _delete_all_panel_assets(job_id)
    job.status = JobStatus.READY
    job.stage = "story"
    job.error = None

    logger.info(
        "Regenerated story profile for job " + job_id + ": "
        + str(len(new_profile.characters)) + " character(s) ("
        + ", ".join(c.name for c in new_profile.characters) + ")"
    )

    save_jobs()
    await broadcast_job_update(job)
    return {
        "status": "ok",
        "characters": [{"name": c.name, "description": c.description} for c in new_profile.characters],
        "story_setting": new_profile.story_setting,
        "art_style": new_profile.art_style,
        "character_bible": new_profile.character_bible,
    }


async def _generate_reference_task(job):
    """Background task to generate master reference image."""
    loop = asyncio.get_event_loop()

    job.status = JobStatus.GENERATING_REFERENCE
    job.progress_current = 0
    job.progress_total = 1
    job.error = None
    await broadcast_job_update(job)

    await broadcast_image_generating(job, "reference")

    try:
        logger.info(f"Job {job.job_id}: generating master character reference...")
        log_system_resources(f"JOB-{job.job_id}-MASTER-REF")

        step_cb = _make_step_callback(job.job_id, "reference")
        try:
            # Add timeout for reference generation (90 seconds)
            await asyncio.wait_for(
                loop.run_in_executor(
                    None, generate_master_reference, job.story, global_state.img_gen, step_cb
                ),
                timeout=90.0
            )
        except asyncio.TimeoutError:
            job.status = JobStatus.ERROR
            job.error = "Reference image generation timed out - please try again"
            save_jobs()
            await broadcast_job_update(job)
            logger.error(f"Reference generation timed out for job {job.job_id}")
            return
        
        await asyncio.sleep(0.5)

        job.progress_current = 1
        job.status = JobStatus.READY
        if job.stage == "story":
            job.stage = "reference"
        save_jobs()
        await broadcast_job_update(job)

    except Exception as e:
        logger.error(f"Failed to generate master reference: {e}", exc_info=True)
        job.status = JobStatus.ERROR
        job.error = f"Failed to generate master reference: {e}"
        save_jobs()
        await broadcast_job_update(job)


@router.post("/api/generate-panels/{job_id}")
async def api_generate_panels(job_id: str):
    """Generate panel images for a job that's at the panel stage."""
    if not global_state.models_loaded:
        raise HTTPException(status_code=503, detail="Models still loading")

    job = global_state.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job.story or not job.story.master_reference:
        raise HTTPException(status_code=400, detail="Master reference not generated yet")

    if _task_is_running(job_id, "panels") or job.status == JobStatus.GENERATING_PANELS:
        return {"status": "ok", "message": "Already generating panels"}

    _start_job_task(job_id, "panels", lambda: _generate_panels_task(job))
    return {"status": "ok", "message": "Panel generation started"}


async def _generate_panels_task(job):
    """Background task to generate panel images in parallel."""
    loop = asyncio.get_event_loop()
    story = job.story

    try:
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
        save_jobs()
        await broadcast_job_update(job)

        # Broadcast image_generating for all panels at once (parallel generation)
        for panel in panels_needing_images:
            await broadcast_image_generating(job, "panel", panel.index)

        def progress_callback(panel_idx: int, completed: int, total: int):
            """Update job progress as panels complete in parallel."""
            with global_state._job_state_lock:
                job.progress_current = completed
                # Generate thumbnail for completed panel
                if panel_idx < len(story.panels):
                    panel = story.panels[panel_idx]
                    if panel.image:
                        job.panel_thumbnails[panel_idx] = _image_to_base64(
                            panel.image, max_size=256
                        )
            # Note: We do NOT broadcast from this callback to avoid deadlock.
            # The broadcast will happen once all panels complete after the executor returns.

        try:
            # Run parallel panel generation in executor
            def generate_all_wrapper():
                generate_all_panels(
                    story,
                    global_state.img_gen,
                    progress_callback=progress_callback,
                )

            await asyncio.wait_for(
                loop.run_in_executor(None, generate_all_wrapper),
                timeout=540.0,  # 90 seconds per panel * 6 panels
            )
        except asyncio.TimeoutError:
            job.status = JobStatus.ERROR
            job.error = "Panel generation timed out - please try again"
            save_jobs()
            await broadcast_job_update(job)
            logger.error(f"Panel generation timed out for job {job.job_id}")
            return
        except Exception as e:
            job.status = JobStatus.ERROR
            job.error = f"Failed to generate panels: {str(e)}"
            save_jobs()
            await broadcast_job_update(job)
            logger.error(f"Panel generation failed for job {job.job_id}: {e}")
            return

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


@router.post("/api/proceed/{job_id}")
async def api_proceed_to_next_stage(job_id: str):
    """Signal the job to proceed to the next stage (user clicked 'Next')."""
    job = global_state.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.stage in ("synopsis", "story", "synopsis_confirmation"):
        if _task_is_running(job_id, "initial") or not job.story or not job.story.character_bible:
            raise HTTPException(status_code=409, detail="Story profile is still being prepared")
        job.stage = "reference"
    elif job.stage == "reference":
        if not job.story or not job.story.master_reference:
            raise HTTPException(status_code=400, detail="Master reference not generated successfully - cannot proceed to panel breakdown")
        job.stage = "panel_breakdown"
    elif job.stage == "panel_breakdown":
        if not job.story or not job.story.panels:
            raise HTTPException(status_code=400, detail="Panel breakdown has not been generated yet")
        job.stage = "panels"
    elif job.stage == "panels":
        # When user clicks Next at the panels stage, check if all non-placeholder panels have images
        if not job.story or not job.story.panels:
            raise HTTPException(status_code=400, detail="Panel breakdown has not been generated yet")
        all_panels_done = all(
            p.image is not None for p in job.story.panels if not p.is_placeholder
        )
        if not all_panels_done:
            raise HTTPException(status_code=400, detail="Panel images not generated yet - please generate all panel images first")
        job.stage = "complete"
        job.status = JobStatus.COMPLETE
        save_jobs()
        await broadcast_job_update(job)

    job.wait_for_user = False
    logger.info(f"Job {job_id}: user requested to proceed from stage '{job.stage}'")
    save_jobs()
    return {"status": "ok", "stage": job.stage}


@router.post("/api/update-panel")
async def api_update_panel(req: UpdatePanelRequest):
    """Update individual panel content (caption or image_prompt)."""
    job = global_state.jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    if req.panel_index < 0 or req.panel_index >= len(job.story.panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")

    panel = job.story.panels[req.panel_index]
    if req.caption is not None:
        panel.caption = req.caption
    if req.image_prompt is not None:
        if panel.image_prompt != req.image_prompt:
            _mark_panel_image_invalid(job, req.panel_index)
        panel.image_prompt = req.image_prompt
    if req.characters is not None:
        if panel.characters != req.characters:
            _mark_panel_image_invalid(job, req.panel_index)
        panel.characters = req.characters

    if panel.is_placeholder:
        # Check if both required fields have real content (not placeholder or empty)
        has_real_caption = panel.caption and not panel.caption.startswith("[Placeholder")
        has_real_image_prompt = panel.image_prompt and not panel.image_prompt.startswith("[Placeholder")
        if has_real_caption and has_real_image_prompt:
            panel.is_placeholder = False
            logger.info(f"Cleared placeholder flag for panel {req.panel_index + 1}")

    save_jobs()
    return {"status": "ok", "panel_index": req.panel_index}


@router.post("/api/update-panels")
async def api_update_panels(req: UpdatePanelsRequest):
    """Update all panels at once (used when saving panel breakdown edits)."""
    job = global_state.jobs.get(req.job_id)
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
            if panel.image_prompt != panel_data["image_prompt"]:
                _mark_panel_image_invalid(job, idx)
            panel.image_prompt = panel_data["image_prompt"]
        if "characters" in panel_data:
            if panel.characters != panel_data["characters"]:
                _mark_panel_image_invalid(job, idx)
            panel.characters = panel_data["characters"]
        if "is_placeholder" in panel_data:
            panel.is_placeholder = panel_data["is_placeholder"]
        else:
            # Auto-detect if panel is still placeholder based on content
            # A panel is a placeholder if either caption OR image_prompt is empty/placeholder
            has_real_caption = panel.caption and not panel.caption.startswith("[Placeholder")
            has_real_image_prompt = panel.image_prompt and not panel.image_prompt.startswith("[Placeholder")
            panel.is_placeholder = not (has_real_caption and has_real_image_prompt)

    logger.info(f"Updated {len(req.panels)} panels for job {req.job_id}")
    save_jobs()
    return {"status": "ok", "panels_updated": len(req.panels)}


@router.post("/api/update-character")
async def api_update_character(req: UpdateCharacterRequest):
    """Update character descriptions for reference generation."""
    job = global_state.jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    job.story.character_bible = req.character_bible
    save_jobs()
    return {"status": "ok"}


# ── Image Export Routes ─────────────────────────────────────────────────────
@router.get("/api/master-reference/{slug}")
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


@router.get("/api/export/{job_id}")
async def export_comic(job_id: str):
    """Export the comic page as a downloadable PNG."""
    job = global_state.jobs.get(job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    # Allow export if job is complete OR all non-placeholder panels have images
    all_panels_done = job.story and all(
        p.image is not None for p in job.story.panels if not p.is_placeholder
    )
    if job.status != JobStatus.COMPLETE and job.stage != "complete" and not all_panels_done:
        raise HTTPException(status_code=400, detail="Job not complete yet - panel images are still being generated")

    # If panels are done but status isn't COMPLETE, update it now
    if all_panels_done and job.status != JobStatus.COMPLETE:
        job.stage = "complete"
        job.status = JobStatus.COMPLETE
        save_jobs()
        await broadcast_job_update(job)

    page = render_page(job.story)

    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in job.story.title)[:40]
    filename = f"{safe_title.replace(' ', '_')}_{job_id}.png"

    output_path = OUTPUT_DIR / filename
    page.save(str(output_path), dpi=(300, 300))

    buf = io.BytesIO()
    page.save(buf, format="PNG", dpi=(300, 300))
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/preview/{job_id}")
async def preview_comic(job_id: str):
    """Get a preview image of the current comic page (lower res)."""
    job = _find_job(job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    page = render_page(job.story)

    preview_w = 800
    ratio = preview_w / page.width
    preview_h = int(page.height * ratio)
    page = page.resize((preview_w, preview_h))

    buf = io.BytesIO()
    page.save(buf, format="JPEG", quality=85)
    buf.seek(0)

    return StreamingResponse(buf, media_type="image/jpeg")


@router.get("/api/panel-image/{job_id}/{panel_index}")
async def get_panel_image(job_id: str, panel_index: int):
    """Get a single panel image."""
    job = global_state.jobs.get(job_id)
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


@router.get("/api/master-reference/{job_id}")
async def get_master_reference(job_id: str):
    """Inspect the hidden master character-reference image for a job."""
    job = _find_job(job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.story.master_reference:
        raise HTTPException(status_code=404, detail="Master reference not generated yet")

    buf = io.BytesIO()
    job.story.master_reference.convert("RGB").save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/jpeg")


# ── Catch-all SPA Routes ─────────────────────────────────────────────────────
@router.get("/{slug}", response_class=HTMLResponse)
async def serve_slug_route(slug: str):
    """Serve the SPA for direct project slug URLs."""
    if slug == "api":
        raise HTTPException(status_code=404, detail="Not found")
    return await serve_index()


@router.get("/{slug}/{page}", response_class=HTMLResponse)
async def serve_slug_step_route(slug: str, page: str):
    """Serve the SPA for project step URLs like /project-abc123/panelImages."""
    if slug == "api":
        raise HTTPException(status_code=404, detail="Not found")
    return await serve_index()
