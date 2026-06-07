"""
jobs.py — Job processing functions for Comic Book Generator.

Workflow:
1. Synopsis generation (for random/themed modes) or wait for user input (custom mode)
2. Story synopsis confirmation
3. Reference profile generation (no panels yet)
4. WAIT for user to proceed to style/reference
5. Style/reference image generation
6. WAIT for user to proceed to panel breakdown
7. Panel breakdown (allow editing)
8. Panel image generation
"""

import asyncio
import logging
import os
import time
import uuid

from fastapi import HTTPException

from generator import (
    ComicStory,
    generate_all_panels,
    generate_master_reference,
    regenerate_panel,
    panel_seed,
    _panel_gen_dims,
    _panel_prompt,
)

from . import state as global_state
from .models import JobStatus
from .utils import log_system_resources, _image_to_base64
from .persistence import save_jobs, _job_assets_dir
from .broadcasting import (
    broadcast_job_update,
    broadcast_image_generating,
)

logger = logging.getLogger("comic-server")


def _load_models():
    """Load both text and image generation models.
    
    The text model uses OpenRouter for language generation, and the image
    generator contacts OpenRouter's image model. Both are lightweight client
    wrappers, so we instantiate them here.
    """
    try:
        logger.info("=" * 60)
        logger.info("Loading models via OpenRouter...")
        log_system_resources("PRE-MODEL-LOAD")
        logger.info("=" * 60)

        from generator import TextGenerator, ImageGenerator
        global_state.text_gen = TextGenerator()
        global_state.text_gen.load()

        # ImageGenerator performs remote API calls; load validates API key.
        global_state.img_gen = ImageGenerator()
        global_state.img_gen.load()

        global_state.models_loaded = True
        global_state.models_loading = False
        logger.info("=" * 60)
        logger.info("All models loaded! Server ready.")
        log_system_resources("POST-MODEL-LOAD")
        logger.info("=" * 60)
    except Exception as e:
        logger.error(f"Failed to load models: {e}", exc_info=True)
        global_state.models_loading = False
        global_state.models_loaded = False


async def process_job(job):
    """Process a single comic generation job.

    Workflow:
    1. Synopsis generation (for random/themed modes) or wait for user input (custom mode)
    2. Story synopsis confirmation
    3. Reference profile generation (no panels yet)
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
            seed = int.from_bytes(os.urandom(4), "big")
            job.synopsis_seed = seed
            save_jobs()  # Save job state before API call for recovery
            
            try:
                # Add timeout for synopsis generation (30 seconds)
                synopsis = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, global_state.text_gen.generate_random_synopsis, theme, seed
                    ),
                    timeout=30.0
                )
                job.input_text = synopsis
                logger.info(f"Generated synopsis with seed {seed}: {synopsis[:50]}...")
            except asyncio.TimeoutError:
                job.status = JobStatus.ERROR
                job.error = "Synopsis generation timed out - please try again"
                job.wait_for_user = False
                save_jobs()
                await broadcast_job_update(job)
                return
            except Exception as e:
                job.status = JobStatus.ERROR
                job.error = f"Failed to generate synopsis: {str(e)}"
                job.wait_for_user = False
                save_jobs()
                await broadcast_job_update(job)
                logger.error(f"Synopsis generation failed for job {job.job_id}: {e}")
                return

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
            try:
                synopsis = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, lambda: global_state.text_gen.generate(prompt, max_tokens=500)
                    ),
                    timeout=30.0
                )
                job.input_text = synopsis
                logger.info(f"Extracted synopsis from full story: {synopsis}")
            except asyncio.TimeoutError:
                job.status = JobStatus.ERROR
                job.error = "Synopsis extraction timed out - please try again"
                job.wait_for_user = False
                save_jobs()
                await broadcast_job_update(job)
                return
            except Exception as e:
                job.status = JobStatus.ERROR
                job.error = f"Failed to extract synopsis: {str(e)}"
                job.wait_for_user = False
                save_jobs()
                await broadcast_job_update(job)
                logger.error(f"Synopsis extraction failed for job {job.job_id}: {e}")
                return

        # Generate a title from the synopsis
        logger.info(f"Generating title for job {job.job_id}...")
        try:
            title = await asyncio.wait_for(
                loop.run_in_executor(
                    None, global_state.text_gen.generate_title, job.input_text
                ),
                timeout=15.0
            )
            logger.info(f"Generated title: {title}")
        except asyncio.TimeoutError:
            title = "Untitled Story"
            logger.warning(f"Title generation timed out for job {job.job_id}, using default")
        except Exception as e:
            title = "Untitled Story"
            logger.warning(f"Title generation failed for job {job.job_id}: {e}, using default")

        # ========================================
        # STEP 2: Show synopsis for user confirmation (NO panels yet)
        # ========================================
        job.stage = "story"
        job.status = JobStatus.GENERATING_STORY
        job.progress_current = 1
        job.progress_total = 1

        # Create a minimal story object with synopsis (no panels yet)
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

        try:
            story = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: global_state.text_gen.generate_reference_profile(job.input_text, title)
                ),
                timeout=30.0
            )
            job.story = story
            logger.info(f"Reference profile generated: {story.title} ({len(story.panels)} panels)")
            await broadcast_job_update(job)
            save_jobs()
        except asyncio.TimeoutError:
            job.status = JobStatus.ERROR
            job.error = "Reference profile generation timed out - please try again"
            job.wait_for_user = False
            save_jobs()
            await broadcast_job_update(job)
            return
        except Exception as e:
            job.status = JobStatus.ERROR
            job.error = f"Failed to generate reference profile: {str(e)}"
            job.wait_for_user = False
            save_jobs()
            await broadcast_job_update(job)
            logger.error(f"Reference profile generation failed for job {job.job_id}: {e}")
            return

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
            
            # Use a closure to capture panel reference properly
            def generate_single_panel(p):
                gen_w, gen_h = _panel_gen_dims(p.index)
                p.image = global_state.img_gen.generate(
                    prompt=_panel_prompt(story, p),
                    width=gen_w,
                    height=gen_h,
                    reference_image=story.master_reference,
                    seed=panel_seed(story, p.index),
                )
            
            try:
                # Add timeout for panel generation (90 seconds per panel)
                await asyncio.wait_for(
                    loop.run_in_executor(None, generate_single_panel, panel),
                    timeout=90.0
                )
            except asyncio.TimeoutError:
                job.status = JobStatus.ERROR
                job.error = f"Panel {panel.index + 1} generation timed out - please try again"
                save_jobs()
                await broadcast_job_update(job)
                logger.error(f"Panel {panel.index + 1} generation timed out for job {job.job_id}")
                return
            except Exception as e:
                job.status = JobStatus.ERROR
                job.error = f"Failed to generate panel {panel.index + 1}: {str(e)}"
                save_jobs()
                await broadcast_job_update(job)
                logger.error(f"Panel {panel.index + 1} generation failed for job {job.job_id}: {e}")
                return

            job.progress_current += 1

            # Brief breather between inference jobs
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


__all__ = [
    "_load_models",
    "process_job",
]