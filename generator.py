"""
generator.py - Core AI generation logic for Comic Book Generator.

Handles text generation (story -> JSON), image generation (FLUX.1-dev),
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


# - Constants -
DPI = 300
PAGE_W = int(8.5 * DPI)
PAGE_H = int(11.0 * DPI)
GUTTER = 44
COLS = 2
ROWS = 3
TITLE_H = 220
CAPTION_H = 200
PANEL_GEN_SIZE = 768

IMAGE_MODEL_ID = "black-forest-labs/FLUX.1-dev"
PANEL_INFERENCE_STEPS = 28
GUIDANCE_SCALE = 5.0
TEXT_MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"

DEVICE = "cuda"
DTYPE = torch.bfloat16


# - Data Classes -
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
    master_reference: Optional[Image.Image] = None
    characters: list[Character] = field(default_factory=list)


# - Random Story Themes -
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


# - Text Generator -
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
        logger.info("Loading text model: " + self.model_id)
        self.pipe = pipeline(
            "text-generation",
            model=self.model_id,
            torch_dtype=DTYPE,
            device=DEVICE,
            trust_remote_code=True,
        )
        logger.info("Text model loaded successfully on device: " + str(self.pipe.device))

    def generate(self, prompt: str, max_tokens: int = 1500) -> str:
        """Generate text from a prompt."""
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
                logger.info("Story generation succeeded on attempt " + str(attempt + 1) + ". Panels: " + str(len(result.panels)))
                return result
            except (KeyError, ValueError) as e:
                raw_short = raw[:800] + "..." if len(raw) > 800 else raw
                logger.warning("Story generation attempt " + str(attempt + 1) + " failed: " + str(e))
                logger.warning("Raw output: " + raw_short)
                if attempt == max_retries - 1:
                    raise ValueError(
                        "Failed to generate valid story after " + str(max_retries) + " attempts: " + str(e)
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
                logger.info("Reference profile generation succeeded on attempt " + str(attempt + 1) + ".")
                return result
            except (KeyError, ValueError) as e:
                raw_short = raw[:800] + "..." if len(raw) > 800 else raw
                logger.warning("Reference profile generation attempt " + str(attempt + 1) + " failed: " + str(e))
                logger.warning("Raw output: " + raw_short)
                if attempt == max_retries - 1:
                    raise ValueError(
                        "Failed to generate valid reference profile after " + str(max_retries) + " attempts: " + str(e)
                    )
        raise ValueError("Reference profile generation failed")

    def generate_random_synopsis(self, theme: Optional[str] = None) -> str:
        """Generate a longer random story synopsis (5-8 sentences)."""
        if theme:
            prompt = (
                "Generate a fun children's comic book synopsis (5-8 sentences) about the theme: '"
                + theme + "'. "
                "It should include a clear situation or setup, a conflict or action, and a short resolution. "
                "Respond with ONLY the synopsis text, nothing else."
            )
        else:
            base = random.choice(RANDOM_THEMES)
            prompt = (
                "Expand this into a fun children's comic book synopsis (5-8 sentences): '"
                + base + "'. "
                "Make sure it has a clear situation/setup, a conflict/action, and a brief resolution. "
                "Respond with ONLY the synopsis text, nothing else."
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
            "Generate a catchy, fun title (max 5 words) for a children's comic book based on this synopsis:\n"
            "'" + synopsis + "'\n\n"
            "Respond with ONLY the title text, nothing else."
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
    """Build the structured plain-text prompt for a comic story."""
    return (
        "Write a 6-panel children's comic book story based on this synopsis:\n"
        '"' + synopsis + '"\n\n'
        "Use EXACTLY the following labeled plain-text format. Do not output JSON.\n"
        "Do not output markdown. Do not add any commentary before or after.\n\n"
        "TITLE: <story title on one line>\n\n"
        "ART_STYLE: <one short sentence describing the visual style, e.g. \"modern 3D animation style, cinematic lighting, high detail\">\n\n"
        "CHARACTER_BIBLE: <one single paragraph describing EVERY character that appears in ANY panel of this story, including characters introduced in later panels. For EACH character provide ALL of the following details in a single flowing paragraph:\n"
        "- Full name\n"
        "- Species/type (human, cat, robot, dragon, etc.)\n"
        "- Body shape and size (tall, short, chubby, slim, tiny, large, etc.)\n"
        "- Exact HAIR COLOR and HAIR STYLE (e.g., \"long curly red hair\", \"short black buzzcut\", \"blue braided ponytail\")\n"
        "- Exact EYE COLOR (e.g., \"big green eyes\", \"dark brown eyes\", \"golden amber eyes\")\n"
        "- Exact SKIN TONE (e.g., \"fair pale skin\", \"medium brown skin\", \"dark brown skin\", \"warm olive skin\")\n"
        "- Exact CLOTHING with specific COLORS and garment types (e.g., \"red hoodie with blue jeans and white sneakers\", \"purple wizard robe with gold stars and brown boots\")\n"
        "- Any DISTINCTIVE MARKINGS or ACCESSORIES (e.g., \"a scar on left cheek\", \"round glasses\", \"a silver necklace\", \"freckles\", \"cat whiskers\", \"a magic wand\")\n"
        "- Overall personality vibe or posture if relevant (e.g., \"always smiling\", \"shy and hunched\", \"confident stance with arms crossed\")\n\n"
        "IMPORTANT: The CHARACTER_BIBLE must be a SINGLE paragraph (no bullet points, no line breaks within it) so it can be parsed reliably. Separate each character's description with a period and space. Make descriptions vivid and specific - NEVER say \"colorful clothes\" or \"nice hair\" without specifying exact colors and styles.>\n\n"
        "PANEL 1\n"
        "CHARACTERS: <comma-separated list of character names appearing in this panel; use the same name spellings across all panels>\n"
        "SCENE: <vivid literal visual description of the panel - characters, setting, action; suitable as an image-generation prompt>\n"
        "CAPTION: <exactly 3 to 5 sentences (50 to 70 words) of narration for kids learning to read>\n\n"
        "PANEL 2\n"
        "CHARACTERS: ...\n"
        "SCENE: ...\n"
        "CAPTION: ...\n\n"
        "(Continue with PANEL 3, PANEL 4, PANEL 5, and PANEL 6 in the same format.)\n\n"
        "Keep the story positive and educational. Output exactly six panels labeled\n"
        "PANEL 1 through PANEL 6."
    )


def _build_reference_profile_prompt(synopsis: str, title: str) -> str:
    """Build metadata only for Step 3 reference generation."""
    return (
        "Create character reference metadata for this children's comic book.\n\n"
        "TITLE: " + title + "\n\n"
        'SYNOPSIS: "' + synopsis + '"\n\n'
        "Use EXACTLY the following labeled plain-text format. Do not output JSON.\n"
        "Do not output markdown. Do not add panels, scenes, captions, or commentary.\n\n"
        "TITLE: <story title on one line>\n\n"
        "ART_STYLE: <one short sentence describing the visual style, e.g. \"modern 3D animation style, cinematic lighting, high detail\">\n\n"
        "CHARACTER_BIBLE: <one single paragraph describing EVERY important character likely to appear in this story. For EACH character provide ALL of the following details in a single flowing paragraph:\n"
        "- Full name\n"
        "- Species/type (human, cat, robot, dragon, etc.)\n"
        "- Body shape and size (tall, short, chubby, slim, tiny, large, etc.)\n"
        "- Exact HAIR COLOR and HAIR STYLE (e.g., \"long curly red hair\", \"short black buzzcut\", \"blue braided ponytail\")\n"
        "- Exact EYE COLOR (e.g., \"big green eyes\", \"dark brown eyes\", \"golden amber eyes\")\n"
        "- Exact SKIN TONE (e.g., \"fair pale skin\", \"medium brown skin\", \"dark brown skin\", \"warm olive skin\")\n"
        "- Exact CLOTHING with specific COLORS and garment types (e.g., \"red hoodie with blue jeans and white sneakers\", \"purple wizard robe with gold stars and brown boots\")\n"
        "- Any DISTINCTIVE MARKINGS or ACCESSORIES (e.g., \"a scar on left cheek\", \"round glasses\", \"a silver necklace\", \"freckles\", \"cat whiskers\", \"a magic wand\")\n"
        "- Overall personality vibe or posture if relevant\n\n"
        "IMPORTANT: The CHARACTER_BIBLE must be a SINGLE paragraph (no bullet points, no line breaks within it). Separate each character's description with a period and space. Make descriptions vivid and specific - NEVER say \"colorful clothes\" or \"nice hair\" without specifying exact colors and styles. This is critical for generating a consistent reference image.>"
    )


_HEADER_FIELDS = ("TITLE", "ART_STYLE", "CHARACTER_BIBLE")

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
    """Parse a list of characters from the LLM-generated character bible."""
    if not character_bible:
        return []

    characters = []
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
        list_match = re.match(r'^[\-\*\d\.]*\s*(?:\*\*)?([A-Z][^:]+?)(?:\*\*)?\s*[:\-]\s*(.+)$', line)
        if list_match:
            name = list_match.group(1).strip()
            desc = list_match.group(2).strip()
            name = re.sub(r'[\*\:]', '', name).strip()
            if name.lower() not in EXCLUDED_WORDS and len(name) >= 2:
                characters.append(Character(name=name, description=desc))
                continue

        segments = re.split(r'(?<=[.!?])\s+(?=[A-Z])', line)
        for segment in segments:
            segment = segment.strip()
            if not segment: continue
            m = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:is|was)\s+(?:a|an|the)?\s*(.+)$', segment, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                desc = m.group(2).strip()
                if name.lower() not in EXCLUDED_WORDS and len(name) >= 2:
                    characters.append(Character(name=name, description=desc))
            else:
                words = segment.split()
                if words and words[0][0].isupper() and len(words) > 1:
                    name = words[0].strip('.,:;()')
                    name_lower = name.lower()
                    if name_lower not in EXCLUDED_WORDS and len(name) >= 3:
                        desc = ' '.join(words[1:])[:150]
                        characters.append(Character(name=name, description=desc))

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
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]

    panel1_match = re.search(r"\bPANEL\s+1\b", text, re.IGNORECASE)
    header = text[: panel1_match.start()] if panel1_match else text

    headers = {}
    for m in _HEADER_FIELD_RE.finditer(header):
        headers[m.group(1).upper()] = m.group(2).strip()

    panels = []
    seen_indices = set()
    for block in _PANEL_BLOCK_RE.finditer(text):
        idx_1based = int(block.group(1))
        if idx_1based in seen_indices:
            continue
        seen_indices.add(idx_1based)
        body = block.group(2)

        fields = {}
        for fm in _PANEL_FIELD_RE.finditer(body):
            fields[fm.group(1).upper()] = fm.group(2).strip()

        scene = fields.get("SCENE", "").strip()
        caption = fields.get("CAPTION", "").strip()
        chars_raw = fields.get("CHARACTERS", "").strip()
        characters = [c.strip() for c in re.split(r"[,;]\s*", chars_raw) if c.strip()]

        if not scene or not caption:
            logger.debug("Panel " + str(idx_1based) + " dropped: scene=" + ("yes" if scene else "NO") + ", caption=" + ("yes" if caption else "NO"))
            continue

        panels.append(
            Panel(
                index=idx_1based - 1,
                characters=characters,
                image_prompt=scene,
                caption=caption,
            )
        )

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

    headers = {}
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


# - VAE Stability Patch (gfx1151) -
def _patch_vae_for_cpu_execution(vae):
    """Pin VAE to CPU (fp32) and route encode/decode through CPU."""
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


# - Image Generator -
class ImageGenerator:
    """Generates comic panel images using FLUX.1-dev."""

    def __init__(self, model_id: str = IMAGE_MODEL_ID):
        self.model_id = model_id
        self.pipe = None
        self._lock = threading.Lock()

    def load(self):
        """Load FLUX.1-dev pipeline, with VAE on CPU."""
        if self.pipe is not None:
            return
        from diffusers import FluxPipeline
        logger.info("Loading FLUX.1-dev base: " + self.model_id)
        self.pipe = FluxPipeline.from_pretrained(
            self.model_id,
            torch_dtype=DTYPE,
            use_safetensors=True,
        ).to(DEVICE)
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
        """Generate an image from a text prompt using FLUX.1-dev."""
        import gc

        with self._lock:
            self.load()
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()

            seed = int.from_bytes(os.urandom(4), "big")

            cb_kwargs = {}
            if step_callback is not None:
                total_steps = steps
                def _on_step_end(pipe, step_index, timestep, callback_kwargs):
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
            logger.info("Image generation complete for prompt: " + prompt[:50] + "...")

            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
            gc.collect()

            return result.images[0]


# - Comic Page Renderer -
def compute_panel_rects():
    """Compute the (x, y, w, h) rectangles for a 2x3 panel grid."""
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
    """Render the full comic page as an 8.5x11" PIL Image."""
    page = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
    draw = ImageDraw.Draw(page)

    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 96)
        font_caption = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
        font_badge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except Exception:
        font_title = ImageFont.load_default()
        font_caption = font_title
        font_badge = font_title

    draw.rectangle([0, 0, PAGE_W, TITLE_H], fill=(255, 255, 255))
    tx = PAGE_W // 2
    ty = TITLE_H // 2
    draw.text((tx, ty), story.title, font=font_title, fill=(20, 20, 20), anchor="mm")

    rects = compute_panel_rects()
    for i, (x, y, pw, ph) in enumerate(rects):
        panel = story.panels[i] if i < len(story.panels) else None
        img_h = ph - CAPTION_H

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
                "Panel " + str(i + 1),
                font=font_badge,
                fill=(100, 100, 100),
                anchor="mm",
            )

        draw.rectangle([x, y + img_h, x + pw, y + ph], fill=(255, 255, 255))
        if panel:
            _draw_wrapped_text(
                draw, panel.caption, font_caption,
                x + 10, y + img_h, pw - 20, CAPTION_H,
                fill=(20, 20, 20),
            )

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


# - Generation Orchestrator -
def _panel_gen_dims(panel_index: int) -> tuple[int, int]:
    """Return (width, height) the image model should generate for a panel."""
    rects = compute_panel_rects()
    pw, ph = rects[panel_index][2], rects[panel_index][3]
    img_h = ph - CAPTION_H
    aspect = pw / img_h
    gen_w = (int(PANEL_GEN_SIZE * aspect) // 64) * 64
    gen_h = (PANEL_GEN_SIZE // 64) * 64
    return gen_w, gen_h


def _build_character_profiles(characters: list[Character], art_style: str) -> str:
    """Build detailed, visually distinct character profiles for prompt injection."""
    if not characters:
        return ""

    profiles = []
    for i, c in enumerate(characters):
        name = c.name
        desc = c.description.strip()

        profile = (
            str(i + 1) + ". " + name + ": " + desc
        )

        if len(desc) < 50:
            profile += (
                " Give " + name + " a UNIQUE and visually distinct appearance "
                "that is clearly different from every other character - "
                "different body type, clothing, colors, and features."
            )

        profiles.append(profile)

    names = [c.name for c in characters]
    differentiator = (
        "IMPORTANT - CHARACTER DIFFERENTIATION: "
        "All " + str(len(characters)) + " characters (" + ", ".join(names) +
        ") must have visually DISTINCT appearances. "
        "No two characters should look alike. Differentiate them through "
        "species, body proportions, height, hair color and style, eye color, "
        "skin tone, dominant clothing colors, clothing style, hairstyle, "
        "accessories, and any other visual features. "
        "If the story includes background characters or villagers, they must "
        "also look different from the main characters and from each other."
    )

    return "\n".join(profiles) + "\n\n" + differentiator


def _match_word(word: str, keyword: str) -> bool:
    """Check if a word matches a keyword, handling plural/suffix forms.

    E.g., 'robes' matches 'robe', 'beard' matches 'beard'.
    Uses simple startswith for plural/suffix variations.
    """
    clean = word.strip('.,;:!?()-')
    # Exact match
    if clean == keyword:
        return True
    # Plural/suffix: keyword must be >= 3 chars and clean word longer than keyword
    if len(keyword) >= 3 and len(clean) > len(keyword) and clean.startswith(keyword):
        return True
    return False


def _extract_color_by_context(desc_lower: str, context_keywords: list[str],
                              color_list: list[str]) -> list[str]:
    """Extract colors that are associated with specific context keywords.

    Instead of blindly matching color words anywhere in the description,
    this checks if a color word appears near (within 3 words before) a
    context keyword like 'hair', 'eyes', 'skin', 'hoodie', etc.
    This prevents false matches like picking up 'blue' from 'blue hoodie'
    as an eye color. Uses fuzzy matching for plural/suffix forms.
    """
    found = []
    words_raw = desc_lower.split()
    words = [w.strip('.,;:!?()-') for w in words_raw]
    for i, word in enumerate(words):
        is_context = any(_match_word(word, kw) for kw in context_keywords)
        if is_context:
            for j in range(max(0, i - 3), i):
                # Check 2-word compound color first (e.g., "dark brown")
                if j + 1 < i:
                    two_word = words[j] + " " + words[j + 1]
                    if two_word in color_list and two_word not in found:
                        found.append(two_word)
                # Then single word
                if words[j] in color_list and words[j] not in found:
                    is_part_of = any(words[j] in fc and fc != words[j] for fc in found)
                    if not is_part_of:
                        found.append(words[j])
    return found


def _build_character_style_dna(characters: list[Character]) -> str:
    """Build an explicit per-character 'style DNA' block for maximum consistency.

    This extracts or synthesizes granular visual attributes for each character:
    hair color, hair style, eye color, skin tone, clothing color(s) and type,
    accessories, body type, height, and any unique markings. Each attribute
    is stated as an explicit factual declaration (not a suggestion) so the
    image model treats them as hard constraints.

    This block is included in BOTH the reference image prompt and every
    panel prompt, giving FLUX's T5-XXL encoder the strongest possible signal
    for cross-panel character consistency.
    """
    if not characters:
        return ""

    dna_parts = ["=== CHARACTER STYLE DNA (HARD CONSTRAINTS - DO NOT DEVIATE) ==="]
    dna_parts.append(
        "The following describes the EXACT visual appearance of each character. "
        "Every image must depict each character with these attributes. "
        "Do NOT change hair color, clothing color, skin tone, eye color, "
        "or any other described feature between panels."
    )
    dna_parts.append("")

    for i, c in enumerate(characters):
        name = c.name
        desc = c.description.strip()
        desc_lower = desc.lower()

        attr_lines = ["--- " + name + " (Character " + str(i + 1) + ") ---"]

        # --- Hair Color ---
        hair_context = ["hair", "haired", "head", "beard", "mustache", "moustache", "fur"]
        hair_colors = ["black", "brown", "blonde", "red", "auburn", "white", "gray",
                       "silver", "golden", "dark brown", "light brown", "blond",
                       "ginger", "strawberry", "platinum", "chestnut", "jet"]
        found_hair = _extract_color_by_context(desc_lower, hair_context, hair_colors)
        if found_hair:
            attr_lines.append("  HAIR COLOR: " + ", ".join(found_hair))
            attr_lines.append("  NOTE: " + name + "'s hair must ALWAYS be " + ", ".join(found_hair) + " in every panel.")
        else:
            attr_lines.append(
                "  HAIR COLOR: Assign a distinctive, specific hair color "
                "unique to " + name + " and different from all other characters."
            )

        # --- Hair Style ---
        hair_styles = ["long", "short", "curly", "straight", "wavy", "braided",
                       "ponytail", "buns", "bob", "mohawk", "spiky", "slicked",
                       "messy", "flowing", "pigtails", "dreadlocks", "afro",
                       "crew cut"]
        found_style = [hs for hs in hair_styles if hs in desc_lower]
        if found_style:
            attr_lines.append("  HAIR STYLE: " + ", ".join(found_style))
        else:
            attr_lines.append(
                "  HAIR STYLE: Distinctive hairstyle that helps identify " + name +
                " at a glance."
            )

        # --- Eye Color ---
        eye_context = ["eye", "eyes", "eyed", "pupil"]
        eye_colors = ["blue", "green", "brown", "hazel", "amber", "gray", "black",
                       "red", "violet", "light blue", "dark brown", "gold",
                       "steel", "honey", "emerald", "sapphire", "warm brown"]
        found_eyes = _extract_color_by_context(desc_lower, eye_context, eye_colors)
        if found_eyes:
            attr_lines.append("  EYE COLOR: " + ", ".join(found_eyes))
        else:
            attr_lines.append(
                "  EYE COLOR: Assign a specific, memorable eye color for " + name +
                " that is different from other characters."
            )

        # --- Skin Tone ---
        skin_context = ["skin", "complexion", "sun-kissed", "sun-touched", "olive-skinned", "fair-skinned"]
        skin_tones = ["fair", "light", "medium", "tan", "brown", "dark", "deep",
                       "pale", "olive", "golden", "dark brown", "light brown",
                       "porcelain", "ruddy", "sun-kissed"]
        found_skin = _extract_color_by_context(desc_lower, skin_context, skin_tones)
        if found_skin:
            attr_lines.append("  SKIN TONE: " + ", ".join(found_skin))
        else:
            attr_lines.append(
                "  SKIN TONE: Assign a specific skin tone for " + name +
                " that remains consistent across all panels."
            )

        # --- Clothing Color and Type ---
        all_clothing = ["hoodie", "jacket", "shirt", "dress", "cape", "hat",
                        "scarf", "gloves", "boots", "shoes", "sneakers", "pants", "shorts",
                        "skirt", "sweater", "vest", "tunic", "robe", "overalls",
                        "suspenders", "bow tie", "necktie", "crown", "tiara",
                        "helmet", "mask", "cloak", "sash", "collar"]
        clothing_colors = ["red", "blue", "green", "yellow", "orange", "purple",
                           "pink", "white", "black", "gray", "brown", "navy",
                           "scarlet", "teal", "maroon", "turquoise", "magenta",
                           "crimson", "gold", "silver", "beige", "ivory", "lavender"]
        found_colors = _extract_color_by_context(desc_lower, all_clothing, clothing_colors)
        found_types = [k for k in all_clothing if k in desc_lower
                       and k not in ["pants", "shorts", "skirt"]]
        if found_colors or found_types:
            if found_colors:
                attr_lines.append("  CLOTHING COLORS: " + ", ".join(found_colors))
            if found_types:
                attr_lines.append("  CLOTHING/ACCESSORIES: " + ", ".join(found_types))
            attr_lines.append(
                "  NOTE: " + name + "'s clothing colors and style must remain EXACTLY "
                "the same in every panel."
            )
        else:
            attr_lines.append(
                "  CLOTHING: Assign specific, distinctive clothing with clear "
                "colors and style for " + name + ". Must be consistent across all panels."
            )

        # --- Distinctive Markings / Accessories ---
        marking_keywords = ["scar", "freckles", "glasses", "patch", "tattoo",
                            "birthmark", "mole", "whiskers", "spots", "stripes",
                            "horns", "wings", "tail", "antlers"]
        found_markings = [m for m in marking_keywords if m in desc_lower]
        if found_markings:
            attr_lines.append("  DISTINCTIVE MARKINGS/ACCESSORIES: " + ", ".join(found_markings))
        else:
            attr_lines.append(
                "  DISTINCTIVE MARKINGS: Note any unique features that distinguish "
                + name + " from all other characters."
            )

        # --- Body Type / Species ---
        species_keywords = ["cat", "dog", "rabbit", "dragon", "fox", "bear",
                            "bird", "wolf", "deer", "mouse", "pig", "frog",
                            "robot", "alien", "elf", "dwarf", "giant"]
        body_keywords = ["tall", "short", "small", "large", "slim", "chubby",
                         "thin", "muscular", "stocky", "tiny", "big"]
        found_species = [s for s in species_keywords if s in desc_lower]
        found_body = [b for b in body_keywords if b in desc_lower]
        if found_species:
            attr_lines.append("  SPECIES/TYPE: " + ", ".join(found_species))
        if found_body:
            attr_lines.append("  BODY TYPE: " + ", ".join(found_body))

        # Summary line with original description
        attr_lines.append("  FULL DESCRIPTION: " + desc)
        attr_lines.append(
            "  >> CONSISTENCY RULE: When generating ANY panel, " + name +
            " must ALWAYS have these exact attributes. Never change, swap, or omit them."
        )

        dna_parts.append("\n".join(attr_lines))
        dna_parts.append("")

    # Add global cross-character consistency rules
    dna_parts.append("=== GLOBAL CONSISTENCY RULES ===")
    dna_parts.append(
        "1. NO character can change their hair color, hairstyle, eye color, "
        "skin tone, or clothing between panels."
    )
    dna_parts.append(
        "2. Each character must be UNIQUELY identifiable by at least 2 visual "
        "attributes (e.g., hair color + clothing color) that no other character shares."
    )
    dna_parts.append(
        "3. If a character's exact attributes are unclear, maintain the MOST "
        "PROMINENT visual features from the reference image."
    )
    dna_parts.append(
        "4. Background characters and villagers must also have consistent "
        "appearances if they appear in multiple panels."
    )
    dna_parts.append(
        "5. Colors must be EXACT - if a character has a red hoodie and brown hair, "
        "every panel must show that red hoodie and brown hair without variation."
    )

    return "\n".join(dna_parts)


def _build_story_context_block(story: ComicStory, panel: Panel, panel_index: int) -> str:
     """Build a narrative context block that tells the model where this panel
     sits in the overall story arc.

     FLUX's long context window allows us to include the full synopsis,
     the panel's position in the story, and surrounding panel summaries.
     This dramatically improves story consistency because the model
     understands the narrative flow rather than generating isolated scenes.
     """
     total_panels = len(story.panels)

     # Build a concise summary of all panels for narrative anchoring
     panel_summaries = []
     for p in story.panels:
         char_names = ", ".join(p.characters) if p.characters else "no characters specified"
         scene_preview = p.image_prompt[:80] + ("..." if len(p.image_prompt) > 80 else "")
         panel_summaries.append(
             "  Panel " + str(p.index + 1) + ": " + scene_preview + " [" + char_names + "]"
         )

     this_panel_chars = set(panel.characters) if panel.characters else set()
     all_char_names = [c.name for c in story.characters]
     excluded_chars = [name for name in all_char_names if name not in this_panel_chars]

     context = (
         'STORY SYNOPSIS: "' + story.synopsis + '"\n'
         "\n"
         "PANEL POSITION: Panel " + str(panel_index + 1) + " of " + str(total_panels) + ".\n"
         "\n"
         "FULL STORY OUTLINE:\n"
     )
     for summary in panel_summaries:
         context += summary + "\n"

     context += (
         "\n"
         "CURRENT PANEL: Panel " + str(panel_index + 1) +
         " specifically depicts: " + panel.image_prompt + "\n"
         "Characters in THIS panel: " +
         (", ".join(panel.characters) if panel.characters else "none specified") + "\n"
     )

     if excluded_chars:
         context += (
             "\n"
             "CHARACTERS NOT IN THIS PANEL (DO NOT INCLUDE): " + ", ".join(excluded_chars) + "\n"
         )

     context += (
         "\n"
         "IMPORTANT: This panel is one frame in a sequential story. "
         "The scene should flow naturally from the previous panels and lead into the next ones. "
         "Do NOT generate a random standalone scene - every element must serve the narrative. "
         "Match the art style, character appearances, and world established in the reference image. "
         "ONLY include characters listed under 'Characters in THIS panel'. "
         "Characters listed under 'CHARACTERS NOT IN THIS PANEL' must NOT appear anywhere in the image. "
         "The panel scene description above is the authoritative source for what this image must contain.\n"
     )

     return context


def _panel_prompt(story: ComicStory, panel: Panel) -> str:
     """Build the image prompt for a single panel with maximum consistency.

     Strategy for FLUX.1-dev's T5-XXL encoder:
       1. Art style directive (sets visual tone for everything)
       2. Full story context + panel sequence position (narrative anchoring)
       3. Specific scene description for this panel
       4. Detailed character profiles WITH EXCLUSIONS for characters not in this panel
       5. Explicit character style DNA (hair color/style, eye color, skin tone,
          clothing colors, accessories) as hard constraints
       6. Global consistency rules

     This replaces simple comma-concatenated prompts. By embedding the
     full story synopsis, panel sequence context, rich character profiles,
     and granular style DNA, FLUX generates images that are narratively
     connected and visually consistent across panels.
     """
     art_style = story.art_style or "modern 3D animation style, cinematic lighting, high detail"
     art_style = art_style.rstrip(".")

     story_context = _build_story_context_block(story, panel, panel.index)
     panel_scene = panel.image_prompt

     this_panel_char_names = set(panel.characters) if panel.characters else set()
     panel_characters = [c for c in story.characters if c.name in this_panel_char_names]
     char_profiles = _build_character_profiles(panel_characters, art_style)

     style_dna = _build_character_style_dna(story.characters)

     excluded_char_names = [c.name for c in story.characters if c.name not in this_panel_char_names]
     exclusion_block = ""
     if excluded_char_names:
         exclusion_block = (
             "=== EXCLUDED CHARACTERS (DO NOT DEPICT) ===\n"
             "The following characters must NOT appear anywhere in this image:\n"
         )
         for name in excluded_char_names:
             desc = next((c.description for c in story.characters if c.name == name), "")
             exclusion_block += "  - " + name + ": " + desc + "\n"
         exclusion_block += (
             "\nUnder no circumstances should these characters be visible in this panel. "
             "If the scene description does not mention them, they must be absent.\n"
         )

     prompt_parts = [
         "Art style: " + art_style + ".",
         "",
         "=== STORY CONTEXT ===",
         story_context,
         "",
         "=== THIS PANEL SCENE ===",
         panel_scene,
     ]

     if char_profiles:
         prompt_parts.extend([
             "",
             "=== CHARACTER IDENTITY GUIDE (MAINTAIN THESE EXACTLY) ===",
             char_profiles,
         ])

     if exclusion_block:
         prompt_parts.extend([
             "",
             exclusion_block,
         ])

     if style_dna:
         prompt_parts.extend([
             "",
             style_dna,
         ])

     prompt_parts.extend([
         "",
         "=== CONSISTENCY RULES (FOLLOW ALL) ===",
         "1. All characters must match their descriptions EXACTLY in every panel - same body, same colors, same clothing.",
         "2. Art style and color palette must be identical across all panels.",
         "3. This is panel " + str(panel.index + 1) + " of " + str(len(story.panels)) +
         " - the scene must be a natural frame within the complete story.",
         "4. Background and setting should be consistent with the story world described in the synopsis.",
         "5. No two characters look alike. Every character has a unique visual identity.",
         "6. If a character appears in this scene, their appearance must exactly match the reference image.",
         "7. ONLY depict characters listed in 'Characters in THIS panel' above. Characters listed in 'EXCLUDED CHARACTERS' must NOT appear.",
         "8. Follow the CHARACTER STYLE DNA above as HARD CONSTRAINTS - never deviate from stated hair color, eye color, skin tone, or clothing colors.",
     ])

     return "\n".join(prompt_parts)


def _generate_reference_prompt(story: ComicStory) -> str:
    """Generate a synopsis-driven reference prompt for the master reference image.

    Instead of a generic "standing together" scene, this creates a prompt based on
    the story's opening context from the synopsis, so the reference image serves as
    an establishing frame that captures the story's setting and character poses
    relevant to the narrative.

    The prompt now includes the full CHARACTER STYLE DNA block so that the
    reference image itself depicts each character with maximum visual specificity,
    making it a reliable anchor for all subsequent panel generations.
    """
    synopsis_context = story.synopsis[:250] if story.synopsis else ""

    if story.characters:
        char_list_parts = []
        for i, c in enumerate(story.characters):
            desc = c.description.strip()
            char_list_parts.append(c.name + ": " + desc)
            if len(desc) < 40:
                char_list_parts.append(
                    "  NOTE: " + c.name + " must look visually unique - "
                    "different species/body/clothes/colors from all other characters."
                )
        char_list_str = ". ".join(char_list_parts)
        char_names = ", ".join([c.name for c in story.characters])
        char_desc = (
            "Characters in scene: " + char_list_str + ". "
            "All characters (" + char_names + ") are present together in one establishing shot. "
            "Each character must have a DISTINCT visual appearance - "
            "different species, body shapes, heights, dominant colors, clothing, "
            "and accessories. No character should look like a copy of another."
        )
    else:
        char_desc = "Characters: " + story.character_bible

    scene_context = (
        "Opening scene from the story: " + synopsis_context + " "
        "Show the characters positioned naturally as if starting the adventure, "
        "with natural poses and body language reflecting the story mood. "
        "Position all characters clearly and distinctly so each is fully visible. "
    )

    style_dna = _build_character_style_dna(story.characters)

    art_style = story.art_style or "modern 3D animation style, cinematic lighting, high detail"
    art_style = art_style.rstrip(".")

    prompt = (
        art_style + ", establishing shot, "
        + scene_context
        + "Full-body view of all characters together, clear faces and distinguishing features, "
        "natural lighting, high quality illustration, no text, no labels. "
        + char_desc
        + "\n\n" + style_dna
    )

    return prompt


def generate_master_reference(
    story: ComicStory,
    img_gen: "ImageGenerator",
    step_callback: Optional[Callable[[int, int], None]] = None,
) -> Image.Image:
    """Generate the master character reference image via FLUX text2img."""
    gen_w, gen_h = _panel_gen_dims(0)

    prompt = _generate_reference_prompt(story)

    logger.info("Generating master reference image from synopsis context...")
    logger.debug("Reference prompt: " + prompt[:150] + "...")
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
    """Generate images for all panels in a story."""
    if story.master_reference is None:
        generate_master_reference(story, img_gen)

    total = len(story.panels)
    for panel in story.panels:
        gen_w, gen_h = _panel_gen_dims(panel.index)
        full_prompt = _panel_prompt(story, panel)
        logger.info("Generating panel " + str(panel.index + 1) + "/" + str(total) + ": " + full_prompt[:80] + "...")

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

    if story.master_reference is None:
        generate_master_reference(story, img_gen)

    full_prompt = _panel_prompt(story, panel)
    logger.info("Regenerating panel " + str(panel_index + 1) + ": " + full_prompt[:80] + "...")

    panel.image = img_gen.generate(
        prompt=full_prompt,
        width=gen_w,
        height=gen_h,
        step_callback=step_callback,
    )
    return panel.image