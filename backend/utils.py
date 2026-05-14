"""
utils.py — Helper utilities for the backend.
"""

import io
import re
import base64
import logging
import time
import uuid
from typing import Optional

import psutil
from PIL import Image

logger = logging.getLogger("comic-server")


def log_system_resources(stage: str):
    """Log current RAM and CPU usage."""
    try:
        vm = psutil.virtual_memory()
        logger.info(f"[{stage}] System Resources: RAM Used: {vm.percent}% ({vm.used // 1024**2}MB / {vm.total // 1024**2}MB)")
    except Exception as e:
        logger.warning(f"Could not log system resources: {e}")


def _image_to_base64(img, max_size: int = 512) -> str:
    """Convert a PIL Image to a base64-encoded JPEG string."""
    # Resize for thumbnail
    ratio = min(max_size / img.width, max_size / img.height)
    if ratio < 1:
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


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


def _find_job(ref: str) -> Optional[object]:
    """Find a job by id or URL slug."""
    from . import state as global_state
    return global_state.jobs.get(ref) or next((j for j in global_state.jobs.values() if j.slug == ref), None)


__all__ = [
    "log_system_resources",
    "_image_to_base64",
    "_make_slug",
    "_make_project_slug",
    "_find_job",
]