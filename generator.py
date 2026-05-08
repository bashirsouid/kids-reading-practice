"""
generator.py — Core AI generation logic for Comic Book Generator.

Handles text generation (story → JSON), image generation (SDXL Lightning),
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
# SDXL base + SDXL-Lightning 4-step LoRA + IP-Adapter Plus.
#   * Lightning gives us 4-step inference (fast, comparable to ERNIE-Turbo's 8).
#   * IP-Adapter Plus is what actually gets us cross-panel character
#     consistency: it conditions the cross-attention on a reference image's
#     embeddings, instead of (incorrectly) constraining the latent the way
#     img2img does. Works even on distilled/turbo schedules because it
#     biases the model's output without eating denoising budget.
IMAGE_MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
LIGHTNING_LORA_REPO = "ByteDance/SDXL-Lightning"
LIGHTNING_LORA_FILE = "sdxl_lightning_4step_lora.safetensors"
IP_ADAPTER_REPO = "h94/IP-Adapter"
IP_ADAPTER_SUBFOLDER = "sdxl_models"
IP_ADAPTER_WEIGHT = "ip-adapter-plus_sdxl_vit-h.safetensors"
# Scale 0.0 = ignore reference; 1.0 = strongly bias toward reference.
# 0.6 leaves enough headroom for the prompt to drive scene composition
# while keeping characters recognisable across panels.
IP_ADAPTER_SCALE = 0.6
PANEL_INFERENCE_STEPS = 4

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


@dataclass
class ComicStory:
    title: str
    synopsis: str
    art_style: str
    character_bible: str
    panels: list[Panel] = field(default_factory=list)
    # Hidden reference image of all characters together. Generated up front
    # and passed as the IP-Adapter conditioning image for every panel so
    # character identity stays consistent across panels — including for
    # characters that don't appear until later in the plot. Not rendered
    # in the final comic page.
    master_reference: Optional[Image.Image] = None


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

    def generate_story(self, synopsis: str, max_retries: int = 3) -> ComicStory:
        """Generate a complete comic story structure with retry logic."""
        prompt = _build_story_prompt(synopsis)
        for attempt in range(max_retries):
            try:
                raw = self.generate(prompt)
                return _parse_story_text(raw, synopsis)
            except (KeyError, ValueError) as e:
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

ART_STYLE: <one short sentence describing the visual style, e.g. "bright colorful children's book illustration, clean lines, friendly characters">

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

    if len(panels) != 6:
        raise ValueError(f"Expected 6 panels, got {len(panels)}")

    panels.sort(key=lambda p: p.index)

    return ComicStory(
        title=headers.get("TITLE", "Untitled").strip() or "Untitled",
        synopsis=synopsis,
        art_style=headers.get("ART_STYLE", "children's book illustration"),
        character_bible=headers.get("CHARACTER_BIBLE", ""),
        panels=panels,
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
    """Generates comic panel images using SDXL + Lightning + IP-Adapter Plus.

    The character-consistency strategy is:
      1. Generate a master reference image (text2img, IP-Adapter scale=0).
      2. For each panel, pass that reference as ip_adapter_image and let
         the prompt drive the scene. The IP-Adapter biases the cross-
         attention layers toward the reference's character/style without
         eating denoising-budget the way img2img would.
    """

    def __init__(self, model_id: str = IMAGE_MODEL_ID):
        self.model_id = model_id
        self.pipe = None
        self._lock = threading.Lock()

    def load(self):
        """Load SDXL + Lightning LoRA + IP-Adapter Plus, with VAE on CPU."""
        if self.pipe is not None:
            return

        from diffusers import StableDiffusionXLPipeline, EulerDiscreteScheduler
        from huggingface_hub import hf_hub_download

        logger.info(f"Loading SDXL base: {self.model_id}")
        self.pipe = StableDiffusionXLPipeline.from_pretrained(
            self.model_id,
            torch_dtype=DTYPE,
            variant="fp16",
            use_safetensors=True,
        ).to(DEVICE)

        logger.info("Loading SDXL-Lightning 4-step LoRA...")
        lora_path = hf_hub_download(LIGHTNING_LORA_REPO, LIGHTNING_LORA_FILE)
        self.pipe.load_lora_weights(lora_path)
        self.pipe.fuse_lora()

        # SDXL-Lightning was trained against this scheduler config;
        # defaults will produce blurry / oversaturated results.
        self.pipe.scheduler = EulerDiscreteScheduler.from_config(
            self.pipe.scheduler.config, timestep_spacing="trailing"
        )

        logger.info("Loading IP-Adapter Plus (sdxl_models)...")
        self.pipe.load_ip_adapter(
            IP_ADAPTER_REPO,
            subfolder=IP_ADAPTER_SUBFOLDER,
            weight_name=IP_ADAPTER_WEIGHT,
        )
        # Default to 0 — generate() flips this on per-call when a
        # reference image is supplied.
        self.pipe.set_ip_adapter_scale(0.0)

        # gfx1151 stability — see _patch_vae_for_cpu_execution.
        self.pipe.vae = _patch_vae_for_cpu_execution(self.pipe.vae)
        logger.info("VAE pinned to CPU/fp32 for gfx1151 stability.")

        try:
            self.pipe.enable_attention_slicing(1)
        except Exception as e:
            logger.warning(f"Attention slicing not available: {e}")

        logger.info("SDXL + Lightning + IP-Adapter Plus loaded.")


    def generate(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        steps: int = PANEL_INFERENCE_STEPS,
        guidance: float = 0.0,
        reference_image: Optional[Image.Image] = None,
        ip_scale: float = IP_ADAPTER_SCALE,
    ) -> Image.Image:
        """Generate an image from a text prompt.

        If reference_image is supplied, IP-Adapter conditions the cross-
        attention on its embeddings (this is what carries character
        consistency across panels). Otherwise IP-Adapter scale is set to
        0 and we get pure text2img — that's the path used to build the
        master reference itself.

        guidance defaults to 0 because SDXL-Lightning was distilled
        without classifier-free guidance; setting it >1 produces over-
        saturated, broken outputs.
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

            if reference_image is not None:
                self.pipe.set_ip_adapter_scale(ip_scale)
                ip_kwargs = {"ip_adapter_image": reference_image}
            else:
                self.pipe.set_ip_adapter_scale(0.0)
                ip_kwargs = {}

            with torch.inference_mode():
                result = self.pipe(
                    prompt=prompt,
                    width=width,
                    height=height,
                    num_inference_steps=steps,
                    guidance_scale=guidance,
                    generator=torch.Generator(device=DEVICE).manual_seed(seed),
                    **ip_kwargs,
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

    The IP-Adapter handles character identity from the master reference,
    so the prompt focuses on style and scene. We keep the prompt short
    and front-load the most important content because SDXL's text
    encoders truncate at 77 tokens each.
    """
    chars_focus = ""
    if panel.characters:
        chars_focus = f" Featuring {', '.join(panel.characters)}."
    return (
        f"{story.art_style}. Scene: {panel.image_prompt}.{chars_focus} "
        f"Children's book illustration, friendly, vivid colors."
    )


def generate_master_reference(
    story: ComicStory,
    img_gen: "ImageGenerator",
) -> Image.Image:
    """Generate the hidden master character reference image.

    The reference is text2img only (IP-Adapter scale = 0 inside generate
    when reference_image is None) and shows every character described in
    the character_bible standing together in a neutral scene. It is then
    used as the IP-Adapter conditioning image for every panel, which is
    what gives us cross-panel character consistency.

    The reference is not added to the rendered comic page.
    """
    gen_w, gen_h = _panel_gen_dims(0)

    prompt = (
        f"{story.art_style}. "
        f"Single group illustration showing all the main characters of this "
        f"story together in one frame, full body view, friendly poses, plain "
        f"neutral background, soft daylight, clear faces, no text and no "
        f"labels. Characters: {story.character_bible}"
    )

    logger.info("Generating master character reference image...")
    img = img_gen.generate(
        prompt=prompt,
        width=gen_w,
        height=gen_h,
        reference_image=None,
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

    A single master reference is generated up front; every panel then
    runs text2img with that reference passed through IP-Adapter so
    characters stay recognisable across panels.
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
            reference_image=story.master_reference,
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
        reference_image=story.master_reference,
    )
    return panel.image
