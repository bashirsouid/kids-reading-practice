"""
models.py — Pydantic models and dataclasses for the backend.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class JobStatus(str, Enum):
    """Status enum for comic generation jobs."""
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
    """Dataclass representing a comic generation job."""
    job_id: str
    status: JobStatus
    mode: str  # "random", "themed", "custom"
    input_text: str
    created_at: float
    story: Optional[object] = None  # ComicStory - imported from generator
    progress_current: int = 0
    progress_total: int = 6
    error: Optional[str] = None
    panel_thumbnails: dict = field(default_factory=dict)  # panel_index -> base64
    slug: str = ""  # URL-friendly project name
    cancel_requested: bool = False
    stage: str = "input"  # input, synopsis, story, reference, panel_breakdown, panels, complete, error
    wait_for_user: bool = False  # Pause and wait for user to click "Next"


# ── Pydantic Request Models ──────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    mode: str  # "random", "themed", "custom"
    text: str = ""  # theme for "themed", full story for "custom", ignored for "random"


class RegeneratePanelRequest(BaseModel):
    job_id: str
    panel_index: int
    modification: str = ""  # optional edit text


class UpdateCharactersRequest(BaseModel):
    job_id: str
    characters: list[dict]


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


__all__ = [
    "JobStatus",
    "ComicJob",
    "GenerateRequest",
    "RegeneratePanelRequest",
    "UpdateCharactersRequest",
    "UpdateCaptionRequest",
    "UpdateTitleRequest",
    "UpdateSynopsisRequest",
    "UpdateArtStyleRequest",
    "GenerateSynopsisRequest",
    "ProceedToNextStageRequest",
    "UpdatePanelRequest",
    "UpdatePanelsRequest",
    "UpdateCharacterRequest",
]