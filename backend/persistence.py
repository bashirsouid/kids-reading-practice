"""
persistence.py — Job save/load and image persistence functions.
"""

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from PIL import Image

from .config import JOBS_FILE, JOB_ASSETS_DIR
from .models import ComicJob, JobStatus
from . import state as global_state

logger = logging.getLogger("comic-server")


def _job_assets_dir(job_id: str) -> Path:
    """Get the assets directory for a job."""
    path = JOB_ASSETS_DIR / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_jobs():
    """Serialize and save jobs to disk."""
    dump = {}
    for jid, job in global_state.jobs.items():
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
                from dataclasses import fields as _dc_fields
                from generator import ComicStory, Panel, Character
                panel_keys = {f.name for f in _dc_fields(Panel)}
                char_keys = {f.name for f in _dc_fields(Character)}
                story_keys = {f.name for f in _dc_fields(ComicStory)}

                panels = []
                for pdict in story_dict.get("panels", []):
                    panels.append(Panel(**{k: v for k, v in pdict.items() if k in panel_keys}))
                characters = []
                for cdict in story_dict.get("characters", []):
                    characters.append(Character(**{k: v for k, v in cdict.items() if k in char_keys}))

                story_dict["panels"] = panels
                story_dict["characters"] = characters
                # Filter unknown keys so older saves (or future renames)
                # don't blow up the loader.
                story_kwargs = {k: v for k, v in story_dict.items() if k in story_keys}
                job.story = ComicStory(**story_kwargs)
                _load_job_images(job)
            if not job.slug:
                from .utils import _make_project_slug
                job.slug = _make_project_slug(job.job_id)
            global_state.jobs[jid] = job

        logger.info(f"Loaded {len(global_state.jobs)} jobs from disk.")
    except Exception as e:
        logger.error(f"Failed to load jobs: {e}")


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


__all__ = [
    "save_jobs",
    "load_jobs",
    "_job_assets_dir",
]