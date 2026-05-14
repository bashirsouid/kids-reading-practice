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
    ComicStory,
    Panel,
    Character,
    render_page,
    generate_master_reference,
    regenerate_panel,
    _panel_gen_dims,
    _panel_prompt,
)

from ..config import STATIC_DIR, OUTPUT_DIR
from ..models import (
    JobStatus, ComicJob,
    GenerateRequest, RegeneratePanelRequest, UpdateCharactersRequest,
    UpdateCaptionRequest, UpdateTitleRequest, UpdateSynopsisRequest,
    UpdateArtStyleRequest, GenerateSynopsisRequest, UpdatePanelRequest,
    UpdatePanelsRequest, UpdateCharacterRequest,
)
from .. import state as global_state
from ..persistence import save_jobs
from ..utils import _image_to_base64, _find_job, _make_project_slug, log_system_resources
from ..broadcasting import (
    broadcast_job_update,
    broadcast_image_generating,
    _make_step_callback,
    _get_queue_position,
)

logger = logging.getLogger("comic-server")
router = APIRouter()


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
        "active_jobs": len([j for j in global_state.jobs.values() if j.status not in (JobStatus.COMPLETE, JobStatus.ERROR)]),
        "queue_size": global_state.job_queue.qsize(),
    }


@router.get("/api/recent")
async def list_recent_jobs():
    """List recent projects for the home page, including in-progress work."""
    recent = sorted(
        [j for j in global_state.jobs.values() if j.slug],
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


# ── WebSocket Routes ─────────────────────────────────────────────────────────
@router.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """WebSocket for real-time job progress updates."""
    await websocket.accept()

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
        status=JobStatus.QUEUED,
        mode=req.mode,
        input_text=req.text,
        created_at=time.time(),
        slug=_make_project_slug(job_id),
    )
    global_state.jobs[job_id] = job
    global_state.job_queue.put_nowait(job_id)
    save_jobs()
    logger.info(f"New job created: {job_id} (mode={req.mode})")
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
    step_cb = _make_step_callback(job, "panel", req.panel_index)

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
    save_jobs()
    return {"status": "ok"}


@router.post("/api/update-art-style")
async def api_update_art_style(req: UpdateArtStyleRequest):
    """Update the art style for a job."""
    job = global_state.jobs.get(req.job_id)
    if not job or not job.story:
        raise HTTPException(status_code=404, detail="Job not found")

    logger.info(f"Updating art style for job {req.job_id} to: {req.art_style}")
    job.story.art_style = req.art_style
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

    asyncio.create_task(_generate_reference_task(job))
    return {"status": "ok", "message": "Reference generation started"}


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

        step_cb = _make_step_callback(job, "reference")
        await loop.run_in_executor(
            None, generate_master_reference, job.story, global_state.img_gen, step_cb
        )
        await asyncio.sleep(0.5)

        job.progress_current = 1
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

    if job.status == JobStatus.GENERATING_PANELS:
        return {"status": "ok", "message": "Already generating panels"}

    asyncio.create_task(_generate_panels_task(job))
    return {"status": "ok", "message": "Panel generation started"}


async def _generate_panels_task(job):
    """Background task to generate panel images."""
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
        await broadcast_job_update(job)

        for panel in story.panels:
            if panel.is_placeholder or panel.image is not None:
                continue

            if job.cancel_requested:
                job.status = JobStatus.ERROR
                job.error = "Generation cancelled by user"
                await broadcast_job_update(job)
                return

            log_system_resources(f"JOB-{job.job_id}-PANEL-{panel.index}")
            await broadcast_image_generating(job, "panel", panel.index)

            step_cb = _make_step_callback(job, "panel", panel.index)

            def generate_single_panel(p=panel, cb=step_cb):
                gen_w, gen_h = _panel_gen_dims(p.index)
                p.image = global_state.img_gen.generate(
                    prompt=_panel_prompt(story, p),
                    width=gen_w,
                    height=gen_h,
                    reference_image=story.master_reference,
                    step_callback=cb,
                )

            await loop.run_in_executor(None, generate_single_panel)
            job.progress_current += 1
            await asyncio.sleep(0.5)

            if panel.image:
                job.panel_thumbnails[panel.index] = _image_to_base64(
                    panel.image, max_size=256
                )
                save_jobs()

            await broadcast_job_update(job)

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
        panel.image_prompt = req.image_prompt

    if panel.is_placeholder:
        is_still_placeholder = (
            (not panel.caption or panel.caption.startswith("[Placeholder")) or
            (not panel.image_prompt or panel.image_prompt.startswith("[Placeholder"))
        )
        if not is_still_placeholder:
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
            panel.image_prompt = panel_data["image_prompt"]
        if "characters" in panel_data:
            panel.characters = panel_data["characters"]
        if "is_placeholder" in panel_data:
            panel.is_placeholder = panel_data["is_placeholder"]
        else:
            is_still_placeholder = (
                (not panel.caption or panel.caption.startswith("[Placeholder")) or
                (not panel.image_prompt or panel.image_prompt.startswith("[Placeholder"))
            )
            panel.is_placeholder = is_still_placeholder

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

    if job.status != JobStatus.COMPLETE:
        raise HTTPException(status_code=400, detail="Job not complete yet")

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