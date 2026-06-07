"""
jobs.py — Job processing functions for Comic Book Generator.

Workflow:
1. Generate or normalize the synopsis.
2. Create an editable story shell.
3. Generate reference metadata.

Later image and panel stages are triggered by explicit API endpoints.
"""

import asyncio
import logging
import os

from generator import (
    ComicStory,
)

from . import state as global_state
from .models import JobStatus
from .utils import log_system_resources
from .persistence import save_jobs
from .broadcasting import (
    broadcast_job_update,
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
    """Create the editable story shell and reference metadata for one project.

    The backend used to behave like a wizard controller: it paused in
    wait_for_user loops and expected one frontend tab to advance it. That made
    refreshes and multiple tabs brittle. This initializer now does only the
    autonomous work needed to make a project editable, then stops. Reference
    images, panel breakdowns, and panel images are triggered by explicit,
    idempotent endpoints and can be recovered by polling /api/status.
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
            job.progress_total = 2
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
            job.progress_total = 2
            await broadcast_job_update(job)
            # Story text becomes the synopsis for custom mode
            logger.info(f"Using custom input as synopsis")

        # For fullstory mode, extract synopsis from the full story text
        if job.mode == "fullstory":
            job.stage = "synopsis"
            job.status = JobStatus.GENERATING_SYNOPSIS
            job.progress_current = 0
            job.progress_total = 2
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
        job.progress_total = 2

        # Create a minimal story object with synopsis (no panels yet)
        job.story = ComicStory(
            title=title,
            synopsis=job.input_text,
            art_style="",  # Will be generated later
            character_bible="",  # Will be generated later
            panels=[],  # No panels yet - waiting for confirmation
        )

        await broadcast_job_update(job)
        save_jobs()
        logger.info("Synopsis generated; preparing reference metadata")

        # ========================================
        # STEP 2c: Generate reference metadata AFTER synopsis confirmation (NO panels yet)
        # ========================================
        job.stage = "story"
        job.status = JobStatus.GENERATING_STORY
        job.progress_current = 1
        job.progress_total = 2
        await broadcast_job_update(job)

        try:
            synopsis_for_profile = job.story.synopsis if job.story else job.input_text
            title_for_profile = job.story.title if job.story else title
            story = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: global_state.text_gen.generate_reference_profile(
                        synopsis_for_profile,
                        title_for_profile,
                    ),
                ),
                timeout=30.0
            )
            if job.story:
                if job.story.synopsis != synopsis_for_profile:
                    job.progress_current = 2
                    job.status = JobStatus.READY
                    job.wait_for_user = False
                    logger.info(
                        f"Discarding stale reference profile for job {job.job_id}; synopsis changed during generation"
                    )
                    save_jobs()
                    await broadcast_job_update(job)
                    return
                story.title = job.story.title or story.title
                story.synopsis = job.story.synopsis or story.synopsis
            job.story = story
            job.progress_current = 2
            job.status = JobStatus.READY
            job.wait_for_user = False
            logger.info(f"Reference profile generated: {story.title}")
            save_jobs()
            await broadcast_job_update(job)
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
        logger.info(f"Job {job.job_id} initialized: {job.story.title if job.story else 'Untitled'}")

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
