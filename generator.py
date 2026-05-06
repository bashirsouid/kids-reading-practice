"""
generator.py — Core AI generation logic for Comic Book Generator.

Handles text generation (story → JSON), image generation (SDXL Lightning),
and comic page rendering (PIL-based 8.5x11" layout).
"""

import json
import os
import random
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable
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
CAPTION_H = 100
PANEL_GEN_SIZE = 768

# ── Model IDs (hardcoded — best options for this hardware) ───────────────────
IMAGE_MODEL_ID = "ByteDance/SDXL-Lightning"
TEXT_MODEL_ID = "Qwen/Qwen2.5-7B-Instruct"

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


@dataclass
class ComicStory:
    title: str
    synopsis: str
    art_style: str
    character_bible: str
    panels: list[Panel] = field(default_factory=list)


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
        self.pipe = pipeline(
            "text-generation",
            model=self.model_id,
            torch_dtype=DTYPE,
            device_map="auto",
            trust_remote_code=True,
        )
        logger.info(f"Text model loaded successfully on device: {self.pipe.device}")

    def generate(self, prompt: str, max_tokens: int = 2000) -> str:
        """Generate text from a prompt."""
        with self._lock:
            self.load()
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a children's comic book writer. "
                        "Always respond with valid JSON only. "
                        "No markdown fences, no explanation, no text outside the JSON object. "
                        "The response must start with { and end with }."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
            out = self.pipe(
                messages,
                max_new_tokens=max_tokens,
                do_sample=True,
                temperature=0.3,  # Low temp for reliable JSON
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

    def generate_story(self, synopsis: str, max_retries: int = 3) -> ComicStory:
        """Generate a complete comic story structure with retry logic."""
        prompt = _build_story_prompt(synopsis)
        for attempt in range(max_retries):
            try:
                raw = self.generate(prompt)
                return _parse_story_json(raw, synopsis)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"Story generation attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    raise ValueError(
                        f"Failed to generate valid story after {max_retries} attempts: {e}"
                    )
        raise ValueError("Story generation failed")

    def generate_random_synopsis(self, theme: Optional[str] = None) -> str:
        """Generate a random story synopsis, optionally themed."""
        if theme:
            prompt = (
                f"Generate a brief, fun children's comic book synopsis (2-3 sentences) "
                f"about the theme: '{theme}'. "
                f"Respond with ONLY the synopsis text, nothing else."
            )
        else:
            # Pick a random base theme and ask the LLM to embellish
            base = random.choice(RANDOM_THEMES)
            prompt = (
                f"Expand this into a brief, fun children's comic book synopsis (2-3 sentences): "
                f"'{base}'. "
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
                max_new_tokens=200,
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


def _build_story_prompt(synopsis: str) -> str:
    """Build the JSON generation prompt for a comic story."""
    return f"""Create a 6-panel children's comic book story based on this synopsis:
"{synopsis}"

Respond with ONLY valid JSON in this exact format:
{{
  "title": "Story Title",
  "art_style": "bright colorful children's book illustration style, clean lines, friendly characters",
  "character_bible": "Brief description of each character's appearance for consistent rendering",
  "panels": [
    {{
      "index": 0,
      "characters": ["CharacterName1", "CharacterName2"],
      "image_prompt": "Detailed image generation prompt describing the scene, characters, setting, action. Include character appearance details. Suitable for children.",
      "caption": "Short dialog or narration text for this panel (max 20 words)"
    }}
  ]
}}

Rules:
- Exactly 6 panels (index 0-5)
- "characters" must use the EXACT same character name strings across all panels
- Each image_prompt must be self-contained, vivid, and describe a children's book illustration
- Captions should be simple enough for a child learning to read
- Keep it fun, positive, age-appropriate
- Your response must be ONLY the JSON object, starting with {{ and ending with }}
"""


def _parse_story_json(raw: str, synopsis: str) -> ComicStory:
    """Parse raw LLM output into a ComicStory dataclass."""
    # Extract JSON from response (handle any stray text)
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("LLM did not return valid JSON")
    data = json.loads(raw[start:end])

    if "panels" not in data:
        raise KeyError("Missing 'panels' key in response")
    if len(data["panels"]) != 6:
        raise ValueError(f"Expected 6 panels, got {len(data['panels'])}")

    panels = [
        Panel(
            index=p["index"],
            image_prompt=p.get("image_prompt", ""),
            caption=p.get("caption", ""),
            characters=p.get("characters", []),
        )
        for p in data["panels"]
    ]
    return ComicStory(
        title=data.get("title", "Untitled"),
        synopsis=synopsis,
        art_style=data.get("art_style", "children's book illustration"),
        character_bible=data.get("character_bible", ""),
        panels=panels,
    )


# ── Image Generator ──────────────────────────────────────────────────────────
class ImageGenerator:
    """Generates comic panel images using SDXL Lightning (4-step)."""

    def __init__(self, model_id: str = IMAGE_MODEL_ID):
        self.model_id = model_id
        self.pipe = None
        self._lock = threading.Lock()

    def load(self):
        """Load the image model into GPU memory."""
        if self.pipe is not None:
            return
        from diffusers import StableDiffusionXLPipeline, EulerDiscreteScheduler
        from huggingface_hub import hf_hub_download

        logger.info(f"Loading image model: {self.model_id}")

        # SDXL Lightning uses a base SDXL model + LoRA weights
        base_model = "stabilityai/stable-diffusion-xl-base-1.0"

        self.pipe = StableDiffusionXLPipeline.from_pretrained(
            base_model,
            torch_dtype=DTYPE,
            variant="fp16",
        )

        # Load the 4-step Lightning LoRA
        self.pipe.load_lora_weights(
            hf_hub_download(self.model_id, "sdxl_lightning_4step_lora.safetensors")
        )
        self.pipe.fuse_lora()

        # Configure scheduler for Lightning
        self.pipe.scheduler = EulerDiscreteScheduler.from_config(
            self.pipe.scheduler.config,
            timestep_spacing="trailing",
        )

        # Move to GPU — no offloading needed with 75 GB budget
        self.pipe = self.pipe.to(DEVICE)

        # Enable memory-efficient attention, slicing, and tiling to prevent GPU timeouts on APUs
        self.pipe.enable_attention_slicing(1)
        self.pipe.enable_vae_slicing()
        self.pipe.vae.enable_tiling()

        logger.info(f"Image model LoRA weights fused. Pipeline moved to {DEVICE}.")
        logger.info("Image model loaded successfully on GPU.")

    def generate(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        steps: int = 4,
        guidance: float = 1.0,
    ) -> Image.Image:
        """Generate an image from a text prompt."""
        with self._lock:
            self.load()
            
            # Free fragmented memory before heavy allocation
            import gc
            gc.collect()
            torch.cuda.empty_cache()
            
            result = self.pipe(
                prompt=prompt,
                width=width,
                height=height,
                num_inference_steps=steps,
                guidance_scale=guidance,
                generator=torch.Generator(device=DEVICE).manual_seed(
                    int.from_bytes(os.urandom(4), "big")
                ),
            )
            logger.info(f"Image generation complete for prompt: {prompt[:50]}...")
            
            # Ensure GPU kernels are finished before releasing lock
            torch.cuda.synchronize()
            
            # Free intermediate tensors immediately
            torch.cuda.empty_cache()
            
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
    page = Image.new("RGB", (PAGE_W, PAGE_H), (245, 235, 220))
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

    # Title banner
    draw.rectangle([0, 0, PAGE_W, TITLE_H], fill=(20, 20, 60))
    tx = PAGE_W // 2
    ty = TITLE_H // 2
    draw.text((tx + 3, ty + 3), story.title, font=font_title, fill=(0, 0, 0), anchor="mm")
    draw.text((tx, ty), story.title, font=font_title, fill=(255, 220, 50), anchor="mm")

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

        # Caption strip
        draw.rectangle([x, y + img_h, x + pw, y + ph], fill=(240, 230, 200))
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
def generate_all_panels(
    story: ComicStory,
    img_gen: ImageGenerator,
    progress_callback: Optional[Callable[[int, int], None]] = None,
):
    """Generate images for all panels in a story."""
    rects = compute_panel_rects()
    total = len(story.panels)

    for panel in story.panels:
        pw, ph = rects[panel.index][2], rects[panel.index][3]
        img_h = ph - CAPTION_H
        aspect = pw / img_h

        gen_h = PANEL_GEN_SIZE
        gen_w = int(PANEL_GEN_SIZE * aspect)
        gen_w = (gen_w // 64) * 64
        gen_h = (gen_h // 64) * 64

        full_prompt = (
            f"{story.art_style}. {story.character_bible}. "
            f"Scene: {panel.image_prompt}"
        )

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
) -> Image.Image:
    """Regenerate a single panel, optionally with a text modification."""
    panel = story.panels[panel_index]
    rects = compute_panel_rects()
    pw, ph = rects[panel_index][2], rects[panel_index][3]
    img_h = ph - CAPTION_H
    aspect = pw / img_h

    gen_w = (int(PANEL_GEN_SIZE * aspect) // 64) * 64
    gen_h = (PANEL_GEN_SIZE // 64) * 64

    if modification:
        panel.image_prompt = panel.image_prompt + ". " + modification

    full_prompt = (
        f"{story.art_style}. {story.character_bible}. "
        f"Scene: {panel.image_prompt}"
    )

    logger.info(f"Regenerating panel {panel_index + 1}: {full_prompt[:80]}...")
    panel.image = img_gen.generate(
        prompt=full_prompt,
        width=gen_w,
        height=gen_h,
    )
    return panel.image
