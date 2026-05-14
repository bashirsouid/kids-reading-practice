"""
generator.py — Core AI generation logic for Comic Book Generator.

Handles text generation (story → JSON), image generation (FLUX.1-dev),
and comic page rendering (PIL-based 8.5x11" layout).
"""

import json
import os
import random
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Union, List
import threading

import torch
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("comic-generator")

# ── Constants ────────────────────────────────────────────────────────────────
DPI = 300
PAGE_W = int(8.5 * DPI)   # 2550
PAGE_H = int(11.0 * DPI)  # 3300
GUTTER = 44
COLS = 2
ROWS = 3
TITLE_H = 220
CAPTION_H = 200
PANEL_GEN_SIZE = 768

# ── Model IDs (hardcoded — best options for this hardware) ───────────────────
# FLUX.1-dev via Diffusers — no LoRA, no IP-Adapter.
# FLUX's built-in T5-XXL text encoder handles long, detailed prompts
# (character descriptions, scene composition) natively, giving us
# high cross-panel character consistency without external IP-Adapter.
IMAGE_MODEL_ID = "black-forest-labs/FLUX.1-dev"

# FLUX.1-dev quality defaults: 28 steps is the sweet spot between
# fidelity and speed for comic-panel-sized outputs.
PANEL_INFERENCE_STEPS = 28

# FLUX uses classifier-free guidance; 5.0 is the recommended default
# and produces vivid, well-composed outputs without over-saturation.
GUIDANCE_SCALE = 5.0

# Qwen2.5-3B-Instruct: ~3x faster than 7B on this GPU, still strong at the
# 6-panel structured story task. The 7B variant was overkill for the work
# and made the retry loop painful when the LLM produced malformed output.
TEXT_MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"

DEVICE = "cuda"
DTYPE = torch.bfloat16


# ── Data Classes ─────────────────────────────────────────────────────────────
@dataclass
class Panel:
    index: int
    image_prompt: str
    caption: str
    characters: list[str] = field(default_factory=list)
    image: Optional[Image.Image] = None
    is_placeholder: bool = False


@dataclass
class Character:
    """Represents a character extracted from the character bible."""
    name: str
    description: str = ""


@dataclass
class ComicStory:
    title: str
    synopsis: str
    art_style: str
    character_bible: str
    panels: list[Panel] = field(default_factory=list)
    # Hidden reference image of all characters together. Generated up front
    # and used as a textual character description source for every panel
    # prompt so character identity stays consistent across panels —
    # including for characters that don't appear until later in the plot.
    # Not rendered in the final comic page.
    master_reference: Optional[Image.Image] = None
    characters: list[Character] = field(default_factory=list)


# ── Random Story Themes ──────────────────────────────────────────────────────
RANDOM_THEMES = [
    "A brave little mouse goes on an adventure in a big city",
    "Two best friends discover a magical garden behind their school",
    "A clumsy dragon tries to learn how to fly",
    "A curious kitten explores a haunted toy store on Halloween",
    "A team of baby animals start their own pizza delivery service",
    "A young astronaut discovers friendly aliens on the moon",
    "A shy penguin learns to dance at the winter festival",
    "A robot and a puppy become unlikely best friends",
    "A pirate parrot finds a treasure map in a library book",
    "A group of dinosaurs start a rock band",
    "A tiny fairy helps a lost butterfly find its way home",
    "A superhero kid whose power is making people laugh",
    "A wizard's cat accidentally turns everything into candy",
    "Two siblings shrink down and explore their own backyard jungle",
    "A baby yeti discovers summer for the first time",
]


# ── Text Generator ───────────────────────────────────────────────────────────
class TextGenerator:
    """Generates comic story structure as JSON using Qwen2.5-7B-Instruct."""

    def __init__(self, model_id: str = TEXT_MODEL_ID):
        self.model_id = model_id
        self.pipe = None
        self._lock = threading.Lock()

    def load(self):
        """Load the text model into GPU memory."""
        if self.pipe is not None:
            return
        from transformers import pipeline
        logger.info(f"Loading text model: {self.model_id}")
        # Use explicit device (not device_map="auto") so .to("cpu"/"cuda") works
        # cleanly when we shuttle the model off-GPU during image generation.
        self.pipe = pipeline(
            "text-generation",
            model=self.model_id,
            torch_dtype=DTYPE,
            device=DEVICE,
            trust_remote_code=True,
        )
        logger.info(f"Text model loaded successfully on device: {self.pipe.device}")

    def generate(self, prompt: str, max_tokens: int = 1500) -> str:
        """Generate text from a prompt.

        Uses a structured plain-text format (not JSON) for the story —
        empirically far more reliable on small models than JSON, which
        breaks on a single missing comma or unescaped quote. max_tokens
        is sized for the full 6-panel story plus headroom.
        """
        with self._lock:
            self.load()
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a children's comic book writer. "
                        "When asked for a story, respond using the exact "
                        "labeled plain-text format requested by the user. "
                        "Do not use JSON. Do not wrap your answer in markdown "
                        "code fences. Do not add commentary, headings, or "
                        "any text outside the format."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
            out = self.pipe(
                messages,
                max_new_tokens=max_tokens,
                max_length=max_tokens,
                do_sample=True,
                temperature=0.5,
                return_full_text=False,
            )
            logger.info("Text generation inference complete.")
            
            # Ensure GPU work is done and clean up
            torch.cuda.synchronize()
            torch.cuda.empty_cache()

            generated = out[0]["generated_text"]
            if isinstance(generated, list):
                return generated[-1]["content"].strip()
            else:
                return generated.strip()

    def generate_story(self, synopsis: str, max_retries: int = 5) -> ComicStory:
        """Generate a complete comic story structure with retry logic."""
        prompt = _build_story_prompt(synopsis)
        for attempt in range(max_retries):
            try:
                raw = self.generate(prompt, max_tokens=2000)
                raw_trimmed = raw[:500] + "..." if len(raw) > 500 else raw
                result = _parse_story_text(raw, synopsis)
                logger.info(f"Story generation succeeded on attempt {attempt + 1}. Panels: {len(result.panels)}")
                return result
            except (KeyError, ValueError) as e:
                raw_short = raw[:800] + "..." if len(raw) > 800 else raw
                logger.warning(f"Story generation attempt {attempt + 1} failed: {e}")
                logger.warning(f"Raw output: {raw_short}")
                if attempt == max_retries - 1:
                    raise ValueError(
                        f"Failed to generate valid story after {max_retries} attempts: {e}"
                    )
        raise ValueError("Story generation failed")

    def generate_reference_profile(self, synopsis: str, title: str = "Untitled", max_retries: int = 5) -> ComicStory:
        """Generate style and character metadata for the reference step only."""
        prompt = _build_reference_profile_prompt(synopsis, title)
        for attempt in range(max_retries):
            raw = ""
            try:
                raw = self.generate(prompt, max_tokens=900)
                result = _parse_reference_profile_text(raw, synopsis, title)
                logger.info(f"Reference profile generation succeeded on attempt {attempt + 1}.")
                return result
            except (KeyError, ValueError) as e:
                raw_short = raw[:800] + "..." if len(raw) > 800 else raw
                logger.warning(f"Reference profile generation attempt {attempt + 1} failed: {e}")
                logger.warning(f"Raw output: {raw_short}")
                if attempt == max_retries - 1:
                    raise ValueError(
                        f"Failed to generate valid reference profile after {max_retries} attempts: {e}"
                    )
        raise ValueError("Reference profile generation failed")

    def generate_random_synopsis(self, theme: Optional[str] = None) -> str:
        """Generate a longer random story synopsis (5-8 sentences).
        
        This synopsis provides a clear situation/setup, a conflict/action, and a brief resolution,
        making it suitable for splitting into six comic panels.
        """
        if theme:
            prompt = (
                f"Generate a fun children's comic book synopsis (5-8 sentences) about the theme: '{theme}'. "
                f"It should include a clear situation or setup, a conflict or action, and a short resolution. "
                f"Respond with ONLY the synopsis text, nothing else."
            )
        else:
            # Pick a random base theme and ask the LLM to elaborate into a mini-story
            base = random.choice(RANDOM_THEMES)
            prompt = (
                f"Expand this into a fun children's comic book synopsis (5-8 sentences): '{base}'. "
                f"Make sure it has a clear situation/setup, a conflict/action, and a brief resolution. "
                f"Respond with ONLY the synopsis text, nothing else."
            )
        
        with self._lock:
            self.load()
            messages = [
                {"role": "system", "content": "You are a creative children's story writer. Respond with only the synopsis text."},
                {"role": "user", "content": prompt},
            ]
            out = self.pipe(
                messages,
                max_new_tokens=500,
                max_length=500,
                do_sample=True,
                temperature=0.8,
                return_full_text=False,
            )
            
            # Ensure GPU work is done and clean up
            torch.cuda.synchronize()
            torch.cuda.empty_cache()

            generated = out[0]["generated_text"]
            if isinstance(generated, list):
                return generated[-1]["content"].strip()
            else:
                return generated.strip()

    def generate_title(self, synopsis: str) -> str:
        """Generate a catchy title for the story based on the synopsis."""
        prompt = (
            f"Generate a catchy, fun title (max 5 words) for a children's comic book based on this synopsis:\n"
            f"'{synopsis}'\n\n"
            f"Respond with ONLY the title text, nothing else."
        )
        with self._lock:
            self.load()
            messages = [
                {"role": "system", "content": "You are a creative children's book author. Respond with only the title."},
                {"role": "user", "content": prompt},
            ]
            out = self.pipe(
                messages,
                max_new_tokens=50,
                do_sample=True,
                temperature=0.7,
                return_full_text=False,
            )
            
            torch.cuda.synchronize()
            torch.cuda.empty_cache()

            generated = out[0]["generated_text"]
            if isinstance(generated, list):
                return generated[-1]["content"].strip().strip('"').strip("'")
            else:
                return generated.strip().strip('"').strip("'")


def _build_story_prompt(synopsis: str) -> str:
    """Build the structured plain-text prompt for a comic story.

    A plain-text labeled format is used instead of JSON. Small instruction-
    tuned models (3–7B) reliably break JSON on long outputs (missing commas,
    unescaped quotes inside captions). The same models reproduce a labeled
    plain-text format almost perfectly because there is no syntax to break.
    """
    return f"""Write a 6-panel children's comic book story based on this synopsis:
"{synopsis}"

Use EXACTLY the following labeled plain-text format. Do not output JSON.
Do not output markdown. Do not add any commentary before or after.

TITLE: <story title on one line>

ART_STYLE: <one short sentence describing the visual style, e.g. "modern 3D animation style, cinematic lighting, high detail">

CHARACTER_BIBLE: <one paragraph describing EVERY character that appears in ANY panel of this story, including characters introduced in later panels (e.g., aliens that show up only in panel 3 or 4). For each character cover: species/type, body shape, dominant colors and markings, distinctive features, clothing/accessories.>

PANEL 1
CHARACTERS: <comma-separated list of character names appearing in this panel; use the same name spellings across panels>
SCENE: <vivid literal visual description of the panel — characters, setting, action; suitable as an image-generation prompt>
CAPTION: <exactly 3 to 5 sentences (50 to 70 words) of narration for kids learning to read>

PANEL 2
CHARACTERS: ...
SCENE: ...
CAPTION: ...

(Continue with PANEL 3, PANEL 4, PANEL 5, and PANEL 6 in the same format.)

Keep the story positive and educational. Output exactly six panels labeled
PANEL 1 through PANEL 6."""


def _build_reference_profile_prompt(synopsis: str, title: str) -> str:
    """Build metadata only for Step 3 reference generation."""
    return f"""Create character reference metadata for this children's comic book.

TITLE: {title}

SYNOPSIS: "{synopsis}"

Use EXACTLY the following labeled plain-text format. Do not output JSON.
Do not output markdown. Do not add panels, scenes, captions, or commentary.

TITLE: <story title on one line>

ART_STYLE: <one short sentence describing the visual style, e.g. "modern 3D animation style, cinematic lighting, high detail">

CHARACTER_BIBLE: <one paragraph describing EVERY important character likely to appear in this story. For each character cover: species/type, body shape, dominant colors and markings, distinctive features, clothing/accessories.>"""


# Top-level header fields that appear before PANEL 1.
_HEADER_FIELDS = ("TITLE", "ART_STYLE", "CHARACTER_BIBLE")

# Per-panel field block. We anchor on "PANEL <n>" and grab the three labeled
# sub-fields up to the next PANEL marker or end of string. DOTALL lets fields
# span multiple lines, which is fine because the next field label terminates
# the current one via lookahead.
_PANEL_BLOCK_RE = re.compile(
    r"PANEL\s+(\d+)\b(.*?)(?=\bPANEL\s+\d+\b|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_PANEL_FIELD_RE = re.compile(
    r"\b(CHARACTERS|SCENE|CAPTION)\s*:\s*(.*?)(?=\b(?:CHARACTERS|SCENE|CAPTION)\s*:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_HEADER_FIELD_RE = re.compile(
    r"\b(TITLE|ART_STYLE|CHARACTER_BIBLE)\s*:\s*(.*?)"
    r"(?=\b(?:TITLE|ART_STYLE|CHARACTER_BIBLE)\s*:|\bPANEL\s+\d+\b|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _auto_detect_characters(character_bible: str) -> list[Character]:
    """Parse a list of characters from the LLM-generated character bible.
    
    Tries to be robust against various formats (bulleted lists, colons, bolding).
    Returns a list of Character objects with names and descriptions.
    """
    if not character_bible:
        return []
        
    characters = []
    
    # Split by lines first to handle list formats
    lines = [line.strip() for line in character_bible.split('\n') if line.strip()]
    
    EXCLUDED_WORDS = {
        'the', 'a', 'an', 'and', 'or', 'but', 'if', 'then', 'else', 'when',
        'where', 'how', 'why', 'what', 'which', 'who', 'whom', 'whose',
        'there', 'this', 'that', 'these', 'those', 'it', 'its', 'he', 'his',
        'him', 'she', 'her', 'hers', 'they', 'them', 'their', 'theirs',
        'we', 'us', 'our', 'ours', 'you', 'your', 'yours', 'i', 'me', 'my', 'mine',
        'mountain', 'forest', 'setting', 'background', 'scene', 'landscape'
    }

    for line in lines:
        # 1. Try to match list patterns: "- Name: Description" or "* Name: Description" or "1. Name: Description"
        # Also handles bolding like "- **Name**: Description"
        list_match = re.match(r'^[\-\*\d\.]*\s*(?:\*\*)?([A-Z][^:]+?)(?:\*\*)?\s*[:\-]\s*(.+)$', line)
        if list_match:
            name = list_match.group(1).strip()
            desc = list_match.group(2).strip()
            
            # Clean up name (remove extra bolding or trailing punctuation)
            name = re.sub(r'[\*\:]', '', name).strip()
            
            if name.lower() not in EXCLUDED_WORDS and len(name) >= 2:
                characters.append(Character(name=name, description=desc))
                continue

        # 2. If not a list item, try sentence-based approach for this line
        segments = re.split(r'(?<=[.!?])\s+(?=[A-Z])', line)
        for segment in segments:
            segment = segment.strip()
            if not segment: continue
            
            # Pattern: "Name is/was a..."
            m = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:is|was)\s+(?:a|an|the)?\s*(.+)$', segment, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                desc = m.group(2).strip()
                if name.lower() not in EXCLUDED_WORDS and len(name) >= 2:
                    characters.append(Character(name=name, description=desc))
            else:
                # Fallback: first capitalized word as name, rest as description
                words = segment.split()
                if words and words[0][0].isupper() and len(words) > 1:
                    name = words[0].strip('.,:;()')
                    name_lower = name.lower()
                    
                    if name_lower not in EXCLUDED_WORDS and len(name) >= 3:
                        desc = ' '.join(words[1:])[:150]
                        characters.append(Character(name=name, description=desc))
    
    # Deduplicate by name
    seen = set()
    unique_chars = []
    for c in characters:
        if c.name.lower() not in seen:
            seen.add(c.name.lower())
            unique_chars.append(c)
            
    return unique_chars


def _parse_story_text(raw: str, synopsis: str) -> ComicStory:
    """Parse the labeled plain-text comic format into a ComicStory."""
    text = raw.strip()
    # Strip markdown fences if the model wrapped the response anyway.
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]

    # Split off the header (everything before PANEL 1) for the top-level fields.
    panel1_match = re.search(r"\bPANEL\s+1\b", text, re.IGNORECASE)
    header = text[: panel1_match.start()] if panel1_match else text

    headers: dict[str, str] = {}
    for m in _HEADER_FIELD_RE.finditer(header):
        headers[m.group(1).upper()] = m.group(2).strip()

    panels: list[Panel] = []
    seen_indices: set[int] = set()
    for block in _PANEL_BLOCK_RE.finditer(text):
        idx_1based = int(block.group(1))
        if idx_1based in seen_indices:
            continue
        seen_indices.add(idx_1based)
        body = block.group(2)

        fields: dict[str, str] = {}
        for fm in _PANEL_FIELD_RE.finditer(body):
            fields[fm.group(1).upper()] = fm.group(2).strip()

        scene = fields.get("SCENE", "").strip()
        caption = fields.get("CAPTION", "").strip()
        chars_raw = fields.get("CHARACTERS", "").strip()
        characters = [c.strip() for c in re.split(r"[,;]\s*", chars_raw) if c.strip()]

        if not scene or not caption:
            logger.debug(f"Panel {idx_1based} dropped: scene={'yes' if scene else 'NO'}, caption={'yes' if caption else 'NO'}")
            # An incomplete panel block — drop it, the retry loop will handle it.
            continue

        panels.append(
            Panel(
                index=idx_1based - 1,  # store 0-based to keep render logic identical
                characters=characters,
                image_prompt=scene,
                caption=caption,
            )
        )

    # Pad or truncate to exactly 6 panels
    while len(panels) < 6:
        panels.append(
            Panel(
                index=len(panels),
                characters=[],
                image_prompt="[Placeholder scene description]",
                caption="[Placeholder caption text]",
                is_placeholder=True,
            )
        )
    panels = panels[:6]


    panels.sort(key=lambda p: p.index)

    # Auto-detect characters from character_bible
    character_bible = headers.get("CHARACTER_BIBLE", "")
    characters = _auto_detect_characters(character_bible)

    return ComicStory(
        title=headers.get("TITLE", "Untitled").strip() or "Untitled",
        synopsis=synopsis,
        art_style=headers.get("ART_STYLE", "modern 3D animation style"),
        character_bible=character_bible,
        panels=panels,
        characters=characters,
    )


def _parse_reference_profile_text(raw: str, synopsis: str, fallback_title: str) -> ComicStory:
    text = raw.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]

    headers: dict[str, str] = {}
    for m in _HEADER_FIELD_RE.finditer(text):
        headers[m.group(1).upper()] = m.group(2).strip()

    character_bible = headers.get("CHARACTER_BIBLE", "").strip()
    if not character_bible:
        raise ValueError("Missing CHARACTER_BIBLE")

    characters = _auto_detect_characters(character_bible)

    return ComicStory(
        title=headers.get("TITLE", fallback_title).strip() or fallback_title,
        synopsis=synopsis,
        art_style=headers.get("ART_STYLE", "modern 3D animation style"),
        character_bible=character_bible,
        panels=[],
        characters=characters,
    )



# ── VAE Stability Patch (gfx1151) ────────────────────────────────────────────
def _patch_vae_for_cpu_execution(vae):
    """Pin VAE to CPU (fp32) and route encode/decode through CPU.

    On gfx1151 (Strix Halo / Ryzen AI Max) the VAE decode at the end of
    generation hits conv shapes whose MIOpen solver hangs the GPU ring;
    the kernel watchdog then resets the device and takes the host
    compositor down with it. Keeping the VAE on CPU sidesteps the entire
    class of hang. The VAE is small and a decode finishes in ~1–2s on
    this hardware — a fine trade for not crashing the desktop. This is
    architecture-agnostic; the same patch works for AutoencoderKL (SDXL)
    and AutoencoderKLFlux2 (ERNIE) alike.
    """
    vae.to(device="cpu", dtype=torch.float32)
    vae.eval()

    original_decode = vae.decode
    original_encode = vae.encode

    def safe_decode(z, *args, **kwargs):
        with torch.no_grad():
            z_cpu = z.detach().to(device="cpu", dtype=torch.float32)
            return original_decode(z_cpu, *args, **kwargs)

    def safe_encode(x, *args, **kwargs):
        with torch.no_grad():
            x_cpu = x.detach().to(device="cpu", dtype=torch.float32)
            return original_encode(x_cpu, *args, **kwargs)

    vae.decode = safe_decode
    vae.encode = safe_encode
    return vae


# ── Image Generator ──────────────────────────────────────────────────────────
class ImageGenerator:
    """Generates comic panel images using FLUX.1-dev.

    The character-consistency strategy is:
      1. Generate a master reference image (text2img).
      2. Extract full character descriptions from the reference story data.
      3. For each panel, embed the complete character descriptions directly
         into the text prompt. FLUX's T5-XXL text encoder is excellent at
         following detailed character prompts, giving us high cross-panel
         consistency without IP-Adapter.
    """

    def __init__(self, model_id: str = IMAGE_MODEL_ID):
        self.model_id = model_id
        self.pipe = None
        self._lock = threading.Lock()

    def load(self):
        """Load FLUX.1-dev pipeline, with VAE on CPU."""
        if self.pipe is not None:
            return

        from diffusers import FluxPipeline

        logger.info(f"Loading FLUX.1-dev base: {self.model_id}")

        self.pipe = FluxPipeline.from_pretrained(
            self.model_id,
            torch_dtype=DTYPE,
            use_safetensors=True,
        ).to(DEVICE)

        # FLUX.1-dev does not use IP-Adapter. Character consistency is
        # handled via detailed text prompts generated by the T5-XXL encoder.

        # gfx1151 stability — see _patch_vae_for_cpu_execution.
        self.pipe.vae = _patch_vae_for_cpu_execution(self.pipe.vae)
        logger.info("VAE pinned to CPU/fp32 for gfx1151 stability.")

        logger.info("FLUX.1-dev loaded.")

    def generate(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        steps: int = PANEL_INFERENCE_STEPS,
        guidance: float = GUIDANCE_SCALE,
        reference_image: Optional[Image.Image] = None,
        step_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Image.Image:
        """Generate an image from a text prompt using FLUX.1-dev.

        FLUX does not use IP-Adapter. Character consistency is achieved
        by embedding full character descriptions into the text prompt
        (see _panel_prompt). The reference_image parameter is kept for
        API compatibility and future img2img support, but is not used
        in the current FLUX pipeline.

        guidance defaults to 5.0 (standard FLUX classifier-free guidance).

        step_callback, if provided, is called after each inference step
        with (current_step, total_steps) to report progress.
        """
        import gc

        with self._lock:
            self.load()

            # Drain anything left over (text-gen logits, prior panel
            # latents) before kicking off another GPU job. Cheap to do.
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()

            seed = int.from_bytes(os.urandom(4), "big")

            # Build a diffusers-compatible step-end callback that adapts to
            # our simpler (step, total) signature.
            cb_kwargs = {}
            if step_callback is not None:
                total_steps = steps
                def _on_step_end(pipe, step_index, timestep, callback_kwargs):
                    # step_index is 0-based; report 1-based for the UI
                    step_callback(step_index + 1, total_steps)
                    return callback_kwargs
                cb_kwargs["callback_on_step_end"] = _on_step_end

            with torch.inference_mode():
                result = self.pipe(
                    prompt=prompt,
                    width=width,
                    height=height,
                    num_inference_steps=steps,
                    guidance_scale=guidance,
                    generator=torch.Generator(device=DEVICE).manual_seed(seed),
                    **cb_kwargs,
                )
            logger.info(f"Image generation complete for prompt: {prompt[:50]}...")

            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
            gc.collect()

            return result.images[0]


# ── Comic Page Renderer ──────────────────────────────────────────────────────
def compute_panel_rects():
    """Compute the (x, y, w, h) rectangles for a 2×3 panel grid."""
    usable_w = PAGE_W - GUTTER * (COLS + 1)
    usable_h = PAGE_H - TITLE_H - GUTTER * (ROWS + 1)
    pw = usable_w // COLS
    ph = usable_h // ROWS
    rects = []
    for row in range(ROWS):
        for col in range(COLS):
            x = GUTTER + col * (pw + GUTTER)
            y = TITLE_H + GUTTER + row * (ph + GUTTER)
            rects.append((x, y, pw, ph))
    return rects


def render_page(story: ComicStory) -> Image.Image:
    """Render the full comic page as an 8.5×11" PIL Image."""
    page = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
    draw = ImageDraw.Draw(page)

    # Load fonts
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 96)
        font_caption = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
        font_badge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except Exception:
        font_title = ImageFont.load_default()
        font_caption = font_title
        font_badge = font_title

    # Title banner — white background with black text for ink-saving prints
    draw.rectangle([0, 0, PAGE_W, TITLE_H], fill=(255, 255, 255))
    tx = PAGE_W // 2
    ty = TITLE_H // 2
    draw.text((tx, ty), story.title, font=font_title, fill=(20, 20, 20), anchor="mm")

    # Panels
    rects = compute_panel_rects()
    for i, (x, y, pw, ph) in enumerate(rects):
        panel = story.panels[i] if i < len(story.panels) else None
        img_h = ph - CAPTION_H

        # Panel border
        draw.rectangle([x - 3, y - 3, x + pw + 3, y + ph + 3], fill=(20, 20, 60))
        draw.rectangle([x, y, x + pw, y + ph], fill=(255, 255, 255))

        if panel and panel.image:
            img = panel.image.convert("RGB")
            img = img.resize((pw, img_h), Image.LANCZOS)
            page.paste(img, (x, y))
        else:
            draw.rectangle([x, y, x + pw, y + img_h], fill=(200, 200, 200))
            draw.text(
                (x + pw // 2, y + img_h // 2),
                f"Panel {i + 1}",
                font=font_badge,
                fill=(100, 100, 100),
                anchor="mm",
            )

        # Caption strip — white background for ink-saving
        draw.rectangle([x, y + img_h, x + pw, y + ph], fill=(255, 255, 255))
        if panel:
            _draw_wrapped_text(
                draw, panel.caption, font_caption,
                x + 10, y + img_h, pw - 20, CAPTION_H,
                fill=(20, 20, 20),
            )

        # Panel number badge
        bx, by, br = x + 18, y + 18, 22
        draw.ellipse([bx - br, by - br, bx + br, by + br], fill=(20, 20, 60))
        draw.text((bx, by), str(i + 1), font=font_badge, fill=(255, 255, 255), anchor="mm")

    return page


def _draw_wrapped_text(
    draw: ImageDraw.Draw,
    text: str,
    font,
    x: int,
    y: int,
    max_width: int,
    max_height: int,
    fill=(0, 0, 0),
):
    """Draw word-wrapped text within a bounding box."""
    words = text.split()
    lines = []
    line = ""
    for w in words:
        test = (line + " " + w).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] < max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)

    line_h = 36
    total_text_h = len(lines) * line_h
    ty = y + (max_height - total_text_h) // 2
    for ln in lines:
        draw.text((x + max_width // 2, ty), ln, font=font, fill=fill, anchor="mt")
        ty += line_h


# ── Generation Orchestrator ──────────────────────────────────────────────────
def _panel_gen_dims(panel_index: int) -> tuple[int, int]:
    """Return (width, height) the image model should generate for a panel.

    SDXL was trained on (multiples of) 64-pixel buckets — keeping the
    output dims aligned avoids resize artefacts inside the VAE.
    """
    rects = compute_panel_rects()
    pw, ph = rects[panel_index][2], rects[panel_index][3]
    img_h = ph - CAPTION_H
    aspect = pw / img_h
    gen_w = (int(PANEL_GEN_SIZE * aspect) // 64) * 64
    gen_h = (PANEL_GEN_SIZE // 64) * 64
    return gen_w, gen_h


def _panel_prompt(story: ComicStory, panel: Panel) -> str:
     """Build the image prompt for a single panel.

     FLUX's T5-XXL text encoder excels at following detailed character
     descriptions embedded directly in the prompt. This replaces the
     IP-Adapter approach — instead of conditioning on a reference image,
     we inject each character's full visual description into the text
     prompt, ensuring consistent appearance across all panels.
     """
     # Build a consolidated character description block for all characters
     # that appear in the story (not just this panel). FLUX's long-context
     # T5 encoder handles this gracefully and maintains identity.
     char_descriptions = []
     if story.characters:
         for c in story.characters:
             char_descriptions.append(
                 f"{c.name}: {c.description}" if c.description else c.name
             )
     chars_block = "; ".join(char_descriptions)

     # Front-load the art style, then the scene, then explicit character
     # descriptions so the T5 encoder allocates attention to all of them.
     prompt_parts = [
         story.art_style,
         panel.image_prompt,
     ]
     if chars_block:
         prompt_parts.append(
             f"Characters: {chars_block}"
         )

     return ", ".join(prompt_parts)


def _generate_reference_prompt(story: ComicStory) -> str:
    """Generate a synopsis-driven reference prompt for the master reference image.

    Instead of a generic "standing together" scene, this creates a prompt based on
    the story's opening context from the synopsis, so the reference image serves as
    an establishing frame that captures the story's setting and character poses
    relevant to the narrative.

    Returns the full reference generation prompt with art style, scene context,
    characters, and quality directives.
    """
    # Extract scene context from synopsis (first 1-2 sentences give opening context)
    synopsis_context = story.synopsis[:200] if story.synopsis else ""
    
    # Build character descriptions
    if story.characters:
        char_list_str = ". ".join([f"{c.name}: {c.description}" for c in story.characters])
        char_names = ", ".join([c.name for c in story.characters])
        char_desc = f"Characters in scene: {char_list_str}. All of them ({char_names}) present."
    else:
        char_desc = f"Characters: {story.character_bible}"

    # Build a scene description based on synopsis context
    scene_context = (
        f"Opening scene from the story: {synopsis_context} "
        f"Show the characters positioned naturally as if starting the adventure, "
        f"with natural poses and body language reflecting the story mood. "
    )

    # Construct the full reference prompt
    prompt = (
        f"{story.art_style}, establishing shot, "
        f"{scene_context}"
        f"Full-body view of all characters together, clear faces and distinguishing features, "
        f"natural lighting, high quality illustration, no text, no labels. "
        f"{char_desc}"
    )

    return prompt


def generate_master_reference(
    story: ComicStory,
    img_gen: "ImageGenerator",
    step_callback: Optional[Callable[[int, int], None]] = None,
) -> Image.Image:
    """Generate the master character reference image via FLUX text2img.

    The reference is generated from a text-only prompt derived from the
    story synopsis and character bible. Since FLUX does not use IP-Adapter,
    this image serves as the canonical visual reference for the story's
    characters and setting. Its generated pixels are not passed to the
    pipeline — only the extracted character descriptions feed into panel
    prompts for cross-panel consistency.
    """
    gen_w, gen_h = _panel_gen_dims(0)

    # Generate reference prompt based on synopsis + characters + style
    prompt = _generate_reference_prompt(story)

    logger.info("Generating master reference image from synopsis context...")
    logger.debug(f"Reference prompt: {prompt[:150]}...")
    img = img_gen.generate(
        prompt=prompt,
        width=gen_w,
        height=gen_h,
        step_callback=step_callback,
    )
    story.master_reference = img
    logger.info("Master reference ready.")
    return img


def generate_all_panels(
    story: ComicStory,
    img_gen: ImageGenerator,
    progress_callback: Optional[Callable[[int, int], None]] = None,
):
    """Generate images for all panels in a story.

    A single master reference is generated up front for visual consistency.
    Each panel then runs text2img with the full character descriptions
    embedded in the prompt (leveraging FLUX's T5-XXL encoder for
    cross-panel character consistency).
    """
    if story.master_reference is None:
        generate_master_reference(story, img_gen)

    total = len(story.panels)
    for panel in story.panels:
        gen_w, gen_h = _panel_gen_dims(panel.index)
        full_prompt = _panel_prompt(story, panel)
        logger.info(f"Generating panel {panel.index + 1}/{total}: {full_prompt[:80]}...")

        panel.image = img_gen.generate(
            prompt=full_prompt,
            width=gen_w,
            height=gen_h,
        )

        if progress_callback:
            progress_callback(panel.index + 1, total)


def regenerate_panel(
    story: ComicStory,
    panel_index: int,
    img_gen: ImageGenerator,
    modification: Optional[str] = None,
    step_callback: Optional[Callable[[int, int], None]] = None,
) -> Image.Image:
    """Regenerate a single panel, optionally with a text modification."""
    panel = story.panels[panel_index]
    gen_w, gen_h = _panel_gen_dims(panel_index)

    if modification:
        panel.image_prompt = panel.image_prompt + ". " + modification

    # Build the master reference lazily for stories that don't have one yet
    # (e.g., regenerating a panel from a story generated under an older code
    # path).
    if story.master_reference is None:
        generate_master_reference(story, img_gen)

    full_prompt = _panel_prompt(story, panel)
    logger.info(f"Regenerating panel {panel_index + 1}: {full_prompt[:80]}...")

    panel.image = img_gen.generate(
        prompt=full_prompt,
        width=gen_w,
        height=gen_h,
        step_callback=step_callback,
    )
    return panel.image
