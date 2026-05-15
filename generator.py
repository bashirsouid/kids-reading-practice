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

# T5-XXL hard ceiling for FLUX. Anything past this is silently dropped, so
# prompts must stay well under it or the scene description is what gets cut.
FLUX_MAX_PROMPT_TOKENS = 512

# How strongly panel generation should be anchored to the master reference
# when the FluxImg2ImgPipeline fallback is used.
#   1.0  → pure text-to-image (reference ignored).
#   0.95 → high freedom for the scene, mild palette/style anchor (recommended).
#   0.85 → reference dominates color + character look, scenes vary less.
PANEL_REF_STRENGTH = float(os.environ.get("PANEL_REF_STRENGTH", "0.95"))

# FLUX-Redux: SigLIP-based image-to-prompt-embedding adapter that injects the
# reference image as joint-attention conditioning rather than as a latent.
# Gives style/character consistency without the composition leak you get from
# pure img2img. When available it's the preferred path; otherwise we fall
# back to img2img, then to text2img.
USE_FLUX_REDUX = os.environ.get("USE_FLUX_REDUX", "1") != "0"
FLUX_REDUX_REPO = os.environ.get("FLUX_REDUX_REPO", "black-forest-labs/FLUX.1-Redux-dev")

# Redux fuses text-derived and image-derived embeddings. Scaling these lets
# the user dial the balance:
#   REDUX_PROMPT_SCALE  > 1 → text (scene description) dominates more.
#   REDUX_POOLED_SCALE  < 1 → reference image's pooled style signal weakens.
# Defaults bias toward "scene matters most, reference is the style anchor".
REDUX_PROMPT_SCALE = float(os.environ.get("REDUX_PROMPT_SCALE", "1.5"))
REDUX_POOLED_SCALE = float(os.environ.get("REDUX_POOLED_SCALE", "1.0"))


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
    # One-sentence world anchor (location, time of day, mood, lighting).
    # Shared across every panel so the world stays visually consistent.
    story_setting: str = ""
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
            # Pass ONLY max_new_tokens. Passing max_length alongside (the old
            # behavior) made transformers treat max_length as the cap on
            # *prompt+output* tokens, which silently clipped longer character
            # bibles mid-sentence and confused the downstream parser.
            out = self.pipe(
                messages,
                max_new_tokens=max_tokens,
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
                # 1200 tokens gives the CHARACTER_BIBLE paragraph headroom
                # even with 3-4 detailed characters; 900 was sometimes
                # clipping mid-character.
                raw = self.generate(prompt, max_tokens=1200)
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


_BIBLE_FORMAT_INSTRUCTIONS = (
    "CHARACTER_BIBLE: <use a bulleted list. ONE LINE per character. "
    "Each line MUST start with \"- \" followed by the character's name, "
    "then a colon, then a comma-separated description. The first colon on "
    "the line is the boundary between the name and the description. "
    "Format shown with placeholders (use the actual characters from your "
    "story, not these placeholders):\n"
    "  - FirstCharacterName: species, body shape, exact hair color and style, exact eye color, exact skin or fur tone, exact clothing with colors, accessories or markings, personality or posture\n"
    "  - SecondCharacterName: species, body, hair, eyes, skin, clothing, accessories, personality\n\n"
    "Rules:\n"
    "- One character per line, starting with \"- \".\n"
    "- The character name is whatever appears before the FIRST colon on the line.\n"
    "- Do NOT put a dash in the name itself (compound words go in the description part).\n"
    "- Always specify exact colors — never say \"colorful clothes\" or \"nice hair\".\n"
    "- Include EVERY character that appears in any panel of the story, even minor ones.>"
)


def _build_story_prompt(synopsis: str) -> str:
    """Build the labeled plain-text prompt for a comic story.

    The CHARACTER_BIBLE is requested as a bulleted per-line list — one
    character per line, "- Name: description" — rather than a flowing
    paragraph. Flowing paragraphs are hard to parse reliably because
    descriptions naturally contain compound words ("palm-sized",
    "pale-blue"), and the earlier parser's name/desc separator regex
    treated those internal dashes as boundaries, producing nonsense
    "character names" and FLUX-generating blank studio images.
    """
    return (
        "Write a 6-panel children's comic book story based on this synopsis:\n"
        '"' + synopsis + '"\n\n'
        "Use EXACTLY the following labeled plain-text format. Do not output JSON.\n"
        "Do not output markdown code fences. Do not add any commentary before or after.\n\n"
        "TITLE: <story title on one line>\n\n"
        "ART_STYLE: <one short sentence describing the visual style, e.g. \"modern 3D animation, cinematic lighting, high detail\">\n\n"
        "STORY_SETTING: <one short sentence describing the shared visual world: location, time of day, weather, lighting, and mood. Every panel happens inside this world. e.g. \"a misty pine forest at twilight, soft moonlight filtering through tall trees, glowing fireflies\">\n\n"
        + _BIBLE_FORMAT_INSTRUCTIONS
        + "\n\n"
        "PANEL 1\n"
        "CHARACTERS: <comma-separated list of character names appearing in this panel; use the same name spellings across all panels>\n"
        "SCENE: <vivid literal visual description of the panel. Say exactly what each character is DOING (use clear action verbs), where they are positioned, and what is visible in the foreground and background. Write it as an image-generation prompt — no narration voice, no \"meanwhile\", just what the camera sees.>\n"
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
    """Build metadata only for Step 3 reference generation (no panels yet)."""
    return (
        "Create character reference metadata for this children's comic book.\n\n"
        "TITLE: " + title + "\n\n"
        'SYNOPSIS: "' + synopsis + '"\n\n'
        "Use EXACTLY the following labeled plain-text format. Do not output JSON.\n"
        "Do not output markdown code fences. Do not add panels, scenes, captions, or commentary.\n\n"
        "TITLE: <story title on one line>\n\n"
        "ART_STYLE: <one short sentence describing the visual style, e.g. \"modern 3D animation, cinematic lighting, high detail\">\n\n"
        "STORY_SETTING: <one short sentence describing the shared visual world: location, time of day, weather, lighting, and mood>\n\n"
        + _BIBLE_FORMAT_INSTRUCTIONS
    )


_HEADER_FIELDS = ("TITLE", "ART_STYLE", "STORY_SETTING", "CHARACTER_BIBLE")

_PANEL_BLOCK_RE = re.compile(
    r"PANEL\s+(\d+)\b(.*?)(?=\bPANEL\s+\d+\b|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_PANEL_FIELD_RE = re.compile(
    r"\b(CHARACTERS|SCENE|CAPTION)\s*:\s*(.*?)(?=\b(?:CHARACTERS|SCENE|CAPTION)\s*:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_HEADER_FIELD_RE = re.compile(
    r"\b(TITLE|ART_STYLE|STORY_SETTING|CHARACTER_BIBLE)\s*:\s*(.*?)"
    r"(?=\b(?:TITLE|ART_STYLE|STORY_SETTING|CHARACTER_BIBLE)\s*:|\bPANEL\s+\d+\b|\Z)",
    re.IGNORECASE | re.DOTALL,
)


_GARBAGE_NAMES = {
    'title', 'art_style', 'story_setting', 'character_bible',
    'characters', 'character', 'caption',
    'scene', 'setting', 'background', 'foreground', 'panel', 'landscape',
    'the', 'a', 'an', 'and', 'or', 'but', 'if', 'then', 'else', 'when',
    'where', 'how', 'why', 'what', 'which', 'who', 'whom', 'whose',
    'there', 'here', 'this', 'that', 'these', 'those',
    'it', 'its', 'he', 'his', 'him', 'she', 'her', 'hers',
    'they', 'them', 'their', 'theirs',
    'we', 'us', 'our', 'ours', 'you', 'your', 'yours',
    'i', 'me', 'my', 'mine',
    'sure', 'okay', 'ok', "here's", 'note', 'notes',
    'one', 'two', 'three', 'four', 'five', 'six',
}

# A character name must look like a proper noun: 1-3 capitalized words made
# of letters or apostrophes. This rejects "Here are the characters" and
# other prose phrases that happen to contain a colon.
_NAME_VALID_RE = re.compile(r"^[A-Z][a-zA-Z']{1,29}(?:\s+[A-Z][a-zA-Z']{1,29}){0,2}$")
_PROPER_NOUN_RE = r"[A-Z][a-zA-Z']{1,29}(?:\s+[A-Z][a-zA-Z']{1,29}){0,2}"


def _is_valid_character_name(name: str) -> bool:
    """Reject prose, field labels, and other non-name strings."""
    if not name or len(name) > 60:
        return False
    if not _NAME_VALID_RE.match(name):
        return False
    if name.lower() in _GARBAGE_NAMES:
        return False
    return True


def _auto_detect_characters(character_bible: str) -> list[Character]:
    """Extract characters from a CHARACTER_BIBLE produced by the LLM.

    Runs three independent parse passes and merges results (deduped by
    name). This handles the wide variety of shapes Qwen-3B actually
    produces:

    1. **Bulleted per-line** — what the prompt requests:
         - Bramble: small fluffy brown rabbit
         - Glow: palm-sized luminous moth

    2. **Inline "Name: desc"** patterns anywhere — catches the case
       where the LLM puts multiple characters on one line:
         "Bramble: small brown rabbit. Glow: palm-sized moth."

    3. **Flowing paragraph "Name is/was ..."** — catches LLM deviation
       and legacy saved jobs:
         "Bramble is a small brown rabbit. Glow is a palm-sized moth."

    The first-colon-only split (never on `-`) was the critical fix:
    earlier the parser treated dashes in descriptions ("palm-sized",
    "pale-blue") as name boundaries, producing garbage names and
    feeding FLUX a blank-rendering prompt.
    """
    if not character_bible:
        return []

    chars: list[Character] = []
    seen: set[str] = set()

    def add(name: str, desc: str) -> None:
        if not _is_valid_character_name(name):
            return
        if not desc or len(desc) < 5:
            return
        if name.lower() in seen:
            return
        seen.add(name.lower())
        chars.append(Character(name=name, description=desc))

    # Pass 1: per-line bulleted/colon-prefixed entries.
    for raw_line in character_bible.split('\n'):
        line = re.sub(r'^[\-\*•\d\.\)\s]+', '', raw_line).strip()
        if ':' not in line:
            continue
        name, _, desc = line.partition(':')
        name = re.sub(r'[\*\_`]', '', name).strip()
        add(name, desc.strip())

    # Pass 2: every "ProperNoun: ..." occurrence anywhere in the text.
    # Handles inline lists where multiple characters share a single line.
    matches = list(re.finditer(
        rf"(?:^|[\s\n\-•])\s*({_PROPER_NOUN_RE})\s*:\s*",
        character_bible,
    ))
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        ds = m.end()
        de = matches[i + 1].start() if i + 1 < len(matches) else len(character_bible)
        desc = character_bible[ds:de].strip(" .,;-\n")
        add(name, desc)

    # Pass 3: flowing "Name is/was ..." sentences.
    SENTENCE_RE = re.compile(
        rf"\b({_PROPER_NOUN_RE})\s+(?:is|was)\s+(?:a|an|the)?\s*"
        rf"([^.!?]+?)(?=\s*(?:{_PROPER_NOUN_RE}\s+(?:is|was)|[.!?]|$))"
    )
    for m in SENTENCE_RE.finditer(character_bible):
        add(m.group(1).strip(), m.group(2).strip())

    return chars


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
    if characters:
        logger.info("Story parse: extracted " + str(len(characters)) + " character(s): " + ", ".join(c.name for c in characters))
    else:
        logger.warning("Story parse: extracted 0 characters. CHARACTER_BIBLE first 400 chars: " + (character_bible[:400] or "<empty>").replace("\n", "\\n"))

    return ComicStory(
        title=headers.get("TITLE", "Untitled").strip() or "Untitled",
        synopsis=synopsis,
        art_style=headers.get("ART_STYLE", "modern 3D animation, cinematic lighting, high detail"),
        character_bible=character_bible,
        story_setting=headers.get("STORY_SETTING", "").strip(),
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
        # The retry loop in generate_reference_profile will try again with a
        # fresh sample. After max_retries it bubbles up — better to fail
        # loudly here than to silently feed FLUX an empty character list and
        # produce a blank reference image.
        logger.warning("Reference profile parse: LLM produced no CHARACTER_BIBLE. Raw first 400 chars: " + text[:400].replace("\n", "\\n"))
        raise ValueError("LLM did not produce a CHARACTER_BIBLE")
    characters = _auto_detect_characters(character_bible)
    if not characters:
        logger.warning("Reference profile parse: extracted 0 characters from CHARACTER_BIBLE. Bible first 400 chars: " + character_bible[:400].replace("\n", "\\n"))
        raise ValueError("Could not extract any characters from CHARACTER_BIBLE")
    logger.info("Reference profile parse: extracted " + str(len(characters)) + " character(s): " + ", ".join(c.name for c in characters))

    return ComicStory(
        title=headers.get("TITLE", fallback_title).strip() or fallback_title,
        synopsis=synopsis,
        art_style=headers.get("ART_STYLE", "modern 3D animation, cinematic lighting, high detail"),
        character_bible=character_bible,
        story_setting=headers.get("STORY_SETTING", "").strip(),
        panels=[],
        characters=characters,
    )


# - VAE Stability Patch (gfx1151) -
def _patch_vae_for_cpu_execution(vae):
    """Pin VAE to CPU (fp32) and route encode/decode through CPU.

    The encode wrapper bounces the returned latent distribution back to the
    caller's original device so img2img pipelines (which sample from
    ``latent_dist`` with a CUDA generator) don't device-mismatch.
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
            if torch.is_tensor(x):
                orig_device = x.device
                orig_dtype = x.dtype
                x_cpu = x.detach().to(device="cpu", dtype=torch.float32)
            else:
                orig_device = torch.device(DEVICE)
                orig_dtype = DTYPE
                x_cpu = x
            result = original_encode(x_cpu, *args, **kwargs)
            ld = getattr(result, "latent_dist", None)
            if ld is not None and ld.parameters.device != orig_device:
                try:
                    from diffusers.models.autoencoders.vae import DiagonalGaussianDistribution
                except ImportError:
                    from diffusers.models.vae import DiagonalGaussianDistribution
                new_params = ld.parameters.to(device=orig_device, dtype=orig_dtype)
                result.latent_dist = DiagonalGaussianDistribution(new_params)
            return result

    vae.decode = safe_decode
    vae.encode = safe_encode
    return vae


# - Image Generator -
class ImageGenerator:
    """Generates comic panel images using FLUX.1-dev.

    Three generation paths in order of preference when a reference image is
    provided:

      1. **FLUX-Redux** (preferred). The reference goes through a SigLIP
         image encoder + image-embedder and is injected into the joint
         attention as prompt-like embeddings. Style + character look
         transfer cleanly; the text prompt fully determines composition.
         Requires the ``black-forest-labs/FLUX.1-Redux-dev`` weights —
         downloaded automatically by HuggingFace on first use. Disable
         with env var ``USE_FLUX_REDUX=0``.
      2. **FluxImg2ImgPipeline** (fallback). The reference is VAE-encoded
         and used as the starting latent. High ``reference_strength``
         (default 0.95) keeps the composition free but anchors color
         palette and character look.
      3. **FluxPipeline** (final fallback). Pure text-to-image.

    The path used per call is chosen automatically based on what loaded.
    """

    def __init__(self, model_id: str = IMAGE_MODEL_ID):
        self.model_id = model_id
        self.pipe = None
        self._img2img_pipe = None
        self._redux_pipe = None
        # Cache the failure so we don't keep trying to load a model we know
        # we don't have. Reset by restarting the process.
        self._redux_unavailable = False
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

    def _ensure_img2img(self):
        """Lazily construct the img2img pipeline, sharing weights with text2img."""
        if self._img2img_pipe is not None:
            return self._img2img_pipe
        from diffusers import FluxImg2ImgPipeline
        # Share all weights — no extra GPU memory, no second download.
        self._img2img_pipe = FluxImg2ImgPipeline(**self.pipe.components)
        logger.info("FluxImg2ImgPipeline initialized (shared weights).")
        return self._img2img_pipe

    def _try_load_redux(self):
        """Best-effort load of the FLUX-Redux prior pipeline.

        Returns the pipeline on success, ``None`` on any failure (model not
        available locally, no network, OOM, etc.). Failures are cached so we
        don't retry every panel.
        """
        if self._redux_unavailable or not USE_FLUX_REDUX:
            return None
        if self._redux_pipe is not None:
            return self._redux_pipe
        try:
            from diffusers import FluxPriorReduxPipeline
        except ImportError as e:
            logger.warning(
                "FluxPriorReduxPipeline not available in this diffusers "
                "version; falling back to img2img. (" + str(e) + ")"
            )
            self._redux_unavailable = True
            return None
        try:
            logger.info("Loading FLUX-Redux prior: " + FLUX_REDUX_REPO)
            # Share text encoders/tokenizers with the base pipe so the prior
            # can fuse text + image without loading them again.
            self._redux_pipe = FluxPriorReduxPipeline.from_pretrained(
                FLUX_REDUX_REPO,
                text_encoder=self.pipe.text_encoder,
                text_encoder_2=self.pipe.text_encoder_2,
                tokenizer=self.pipe.tokenizer,
                tokenizer_2=self.pipe.tokenizer_2,
                torch_dtype=DTYPE,
            ).to(DEVICE)
            logger.info("FLUX-Redux loaded.")
            return self._redux_pipe
        except Exception as e:
            logger.warning(
                "FLUX-Redux unavailable, falling back to img2img: " + repr(e)
            )
            self._redux_unavailable = True
            self._redux_pipe = None
            return None

    def _cuda_recover(self):
        """Drain CUDA caches/sync before retrying after a transient failure."""
        import gc
        gc.collect()
        if torch.cuda.is_available():
            try:
                torch.cuda.synchronize()
            except Exception:
                pass
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass

    def _run_with_retry(self, fn, *, label: str):
        """Run an image-gen call and retry once on a transient CUDA failure.

        OOM and HIP/CUDA kernel hiccups on gfx1151 are usually recoverable
        if we drain the allocator and re-issue. We deliberately do not
        change image dimensions — silently returning a smaller image would
        surprise callers.
        """
        try:
            return fn()
        except torch.cuda.OutOfMemoryError as e:
            logger.warning(label + " OOM, draining and retrying once: " + str(e))
            self._cuda_recover()
            return fn()
        except RuntimeError as e:
            msg = str(e)
            if any(tok in msg for tok in ("CUDA", "HIP", "MIOpen", "out of memory")):
                logger.warning(label + " CUDA RuntimeError, retrying once: " + msg[:200])
                self._cuda_recover()
                return fn()
            raise

    def generate(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        steps: int = PANEL_INFERENCE_STEPS,
        guidance: float = GUIDANCE_SCALE,
        reference_image: Optional[Image.Image] = None,
        reference_strength: float = PANEL_REF_STRENGTH,
        seed: Optional[int] = None,
        step_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Image.Image:
        """Generate an image with FLUX.1-dev.

        Routes through Redux > img2img > text2img depending on what's
        available and whether a reference is supplied.
        """
        with self._lock:
            self.load()
            self._cuda_recover()

            if seed is None:
                seed = int.from_bytes(os.urandom(4), "big")

            cb_kwargs = {}
            if step_callback is not None:
                total_steps = steps
                def _on_step_end(pipe, step_index, timestep, callback_kwargs):
                    step_callback(step_index + 1, total_steps)
                    return callback_kwargs
                cb_kwargs["callback_on_step_end"] = _on_step_end

            # Decide which path to take.
            redux = None
            if reference_image is not None:
                redux = self._try_load_redux()

            use_img2img = (
                redux is None
                and reference_image is not None
                and 0.0 < reference_strength < 1.0
            )

            with torch.inference_mode():
                if redux is not None and reference_image is not None:
                    ref = reference_image.convert("RGB").resize(
                        (width, height), Image.LANCZOS
                    )

                    def _do_redux():
                        prior_out = redux(
                            image=ref,
                            prompt=prompt,
                            prompt_embeds_scale=REDUX_PROMPT_SCALE,
                            pooled_prompt_embeds_scale=REDUX_POOLED_SCALE,
                        )
                        return self.pipe(
                            prompt_embeds=prior_out.prompt_embeds,
                            pooled_prompt_embeds=prior_out.pooled_prompt_embeds,
                            width=width,
                            height=height,
                            num_inference_steps=steps,
                            guidance_scale=guidance,
                            generator=torch.Generator(device=DEVICE).manual_seed(seed),
                            **cb_kwargs,
                        )

                    result = self._run_with_retry(_do_redux, label="redux")
                    logger.info(
                        "redux complete (prompt_scale=" + str(REDUX_PROMPT_SCALE)
                        + ", pooled_scale=" + str(REDUX_POOLED_SCALE)
                        + ", seed=" + str(seed) + "): "
                        + prompt[:50] + "..."
                    )

                elif use_img2img:
                    ref = reference_image.convert("RGB").resize(
                        (width, height), Image.LANCZOS
                    )
                    pipe = self._ensure_img2img()
                    # When strength < 1 the pipeline only denoises the last
                    # `steps * strength` timesteps. Scale up so the effective
                    # step count stays close to the text2img setting.
                    scaled_steps = max(steps, int(round(steps / max(reference_strength, 1e-3))))

                    def _do_img2img():
                        return pipe(
                            prompt=prompt,
                            image=ref,
                            strength=reference_strength,
                            width=width,
                            height=height,
                            num_inference_steps=scaled_steps,
                            guidance_scale=guidance,
                            max_sequence_length=FLUX_MAX_PROMPT_TOKENS,
                            generator=torch.Generator(device=DEVICE).manual_seed(seed),
                            **cb_kwargs,
                        )

                    result = self._run_with_retry(_do_img2img, label="img2img")
                    logger.info(
                        "img2img complete (strength="
                        + str(reference_strength) + ", seed=" + str(seed) + "): "
                        + prompt[:50] + "..."
                    )

                else:
                    def _do_text2img():
                        return self.pipe(
                            prompt=prompt,
                            width=width,
                            height=height,
                            num_inference_steps=steps,
                            guidance_scale=guidance,
                            max_sequence_length=FLUX_MAX_PROMPT_TOKENS,
                            generator=torch.Generator(device=DEVICE).manual_seed(seed),
                            **cb_kwargs,
                        )

                    result = self._run_with_retry(_do_text2img, label="text2img")
                    logger.info(
                        "text2img complete (seed=" + str(seed) + "): "
                        + prompt[:50] + "..."
                    )

            self._cuda_recover()
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


def _compact_char_anchor(c: Character, max_chars: int = 220) -> str:
    """Return a tight, prompt-ready visual description for one character.

    Trims the LLM-written description down to ~220 chars so multiple
    characters can be inlined into a panel prompt without blowing past T5's
    512-token cap. The description itself is treated as authoritative —
    the previous heuristic regex extractor only added noise by re-phrasing
    the LLM's text inconsistently between panels.
    """
    desc = (c.description or "").strip().replace("\n", " ")
    desc = re.sub(r"\s+", " ", desc)
    if not desc:
        desc = "a distinct character with a unique visual appearance"
    if len(desc) > max_chars:
        cut = desc[:max_chars]
        # Snap to last word boundary so we don't end mid-word.
        sp = cut.rfind(" ")
        if sp > max_chars // 2:
            cut = cut[:sp]
        desc = cut + "..."
    return c.name + ": " + desc


def _trim_setting(setting: str, max_chars: int = 200) -> str:
    """Trim the story-level setting line so it doesn't dominate the prompt."""
    s = re.sub(r"\s+", " ", (setting or "").strip()).rstrip(".")
    if len(s) > max_chars:
        s = s[:max_chars].rsplit(" ", 1)[0] + "..."
    return s


def _panel_prompt(story: ComicStory, panel: Panel) -> str:
    """Build a tight, scene-first FLUX prompt for one panel.

    Order (T5-XXL weights early tokens more heavily; total budget 512):

        1. Scene description — what's happening in THIS panel.
        2. World/setting — story-wide visual anchor (location, time, mood).
        3. Compact character anchors — only characters present in the panel.
        4. Art-style suffix — tone and palette.
        5. One short continuity reminder.

    Target: ~250 tokens. Deliberately omitted vs the original prompt: the
    full synopsis, full-book panel outline, "excluded characters" block
    (T5 has no negation), regex "STYLE DNA" block, and numbered rules
    lists. All burned token budget without measurable lift.
    """
    art_style = (story.art_style or "modern 3D animation, cinematic lighting, high detail").rstrip(".")
    scene = (panel.image_prompt or "").strip().rstrip(".")
    setting = _trim_setting(getattr(story, "story_setting", ""), max_chars=200)

    this_panel = set(panel.characters or [])
    if this_panel:
        panel_chars = [c for c in story.characters if c.name in this_panel]
    else:
        panel_chars = list(story.characters)
    char_anchors = [_compact_char_anchor(c) for c in panel_chars]

    parts: list[str] = []
    if scene:
        parts.append("Scene: " + scene + ".")
    if setting:
        parts.append("World: " + setting + ".")
    if char_anchors:
        parts.append(
            "Characters in this panel (keep appearance identical to the reference sheet):\n"
            + "\n".join("- " + a for a in char_anchors)
        )
    parts.append(
        "Style: " + art_style + ", comic book panel, "
        "consistent character design, clean lines, vibrant colors, "
        "no on-image text, no speech bubbles, no captions."
    )
    parts.append(
        "Panel " + str(panel.index + 1) + " of " + str(len(story.panels))
        + " — same characters, same world, same palette as the rest of the book."
    )

    return "\n\n".join(parts)


def _generate_reference_prompt(story: ComicStory) -> str:
    """Build a clean character-sheet prompt for the master reference image.

    A turnaround/lineup designed to anchor downstream panel generation:
    no story action — the cast standing in a neutral pose against a plain
    background so the reference encodes character look and color palette
    cleanly. The story setting is mentioned only as a tone hint (one line)
    so the reference's color/atmosphere is in the right ballpark for the
    book without the reference becoming a "scene."
    """
    art_style = (story.art_style or "modern 3D animation, cinematic lighting, high detail").rstrip(".")
    setting = _trim_setting(getattr(story, "story_setting", ""), max_chars=160)

    if story.characters:
        anchors = [_compact_char_anchor(c, max_chars=260) for c in story.characters]
        names = ", ".join(c.name for c in story.characters)
        char_block = "\n".join("- " + a for a in anchors)
        parts = [
            "Character reference sheet. Lineup of every named character standing "
            "side by side in a neutral T-pose against a plain off-white studio "
            "background, full body visible head to toe, even soft lighting, "
            "clear faces, no text, no labels, no props, no other characters.",
            "Cast (" + names + "):\n" + char_block,
            "Style: " + art_style + ", consistent character design, "
            "clean lines, vibrant colors, distinct silhouettes.",
        ]
        if setting:
            parts.append("Color and mood reference for the book (do NOT depict this scene here, this is a plain studio character sheet): " + setting + ".")
        return "\n\n".join(parts)

    bible = (story.character_bible or "").strip()
    if len(bible) > 800:
        bible = bible[:800].rsplit(" ", 1)[0] + "..."
    parts = [
        "Character reference sheet. All main characters standing side by side "
        "against a plain off-white background, full body visible, even soft "
        "lighting, no text, no labels.",
        "Characters: " + bible,
        "Style: " + art_style + ", clean lines, vibrant colors.",
    ]
    if setting:
        parts.append("Color and mood reference for the book: " + setting + ".")
    return "\n\n".join(parts)


def _story_base_seed(story: ComicStory) -> int:
    """Derive a stable base seed from the story's title.

    Same title → same seed neighborhood for every panel of the book, which
    gives FLUX a strong nudge toward consistent character/style appearances
    across panels. Different stories live in different neighborhoods.
    """
    import hashlib
    key = (story.title or "untitled").strip().lower().encode("utf-8")
    digest = hashlib.sha256(key).digest()
    return int.from_bytes(digest[:4], "big")


def panel_seed(story: ComicStory, panel_index: int) -> int:
    """Per-panel seed: story base + panel offset (mod 32-bit)."""
    return (_story_base_seed(story) + panel_index * 1_000_003) & 0xFFFFFFFF


def generate_master_reference(
    story: ComicStory,
    img_gen: "ImageGenerator",
    step_callback: Optional[Callable[[int, int], None]] = None,
    seed: Optional[int] = None,
) -> Image.Image:
    """Generate the master character reference image via FLUX text2img."""
    # Fail loudly rather than feed FLUX an empty character list. The old
    # silent-fallthrough behavior produced a blank off-white image (FLUX
    # rendered the "plain studio background" with no characters to depict).
    if not story.characters and not (story.character_bible or "").strip():
        raise ValueError(
            "Cannot generate master reference: story has no characters. "
            "The LLM did not produce a CHARACTER_BIBLE. Re-run synopsis "
            "confirmation to retry the character profile, or edit the "
            "character bible directly."
        )

    gen_w, gen_h = _panel_gen_dims(0)

    prompt = _generate_reference_prompt(story)

    logger.info(
        "Generating master reference image (character sheet) for "
        + str(len(story.characters)) + " character(s): "
        + (", ".join(c.name for c in story.characters) or "<none, using bible>")
    )
    # Full prompt at INFO so we can diagnose blank/garbage reference issues
    # without enabling debug logging.
    logger.info("Reference prompt:\n" + prompt)
    img = img_gen.generate(
        prompt=prompt,
        width=gen_w,
        height=gen_h,
        # The reference itself is the anchor — generate it as text2img so
        # nothing biases it.
        reference_image=None,
        reference_strength=1.0,
        seed=seed if seed is not None else _story_base_seed(story),
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
            reference_image=story.master_reference,
            seed=panel_seed(story, panel.index),
        )

        if progress_callback:
            progress_callback(panel.index + 1, total)


def regenerate_panel(
    story: ComicStory,
    panel_index: int,
    img_gen: ImageGenerator,
    modification: Optional[str] = None,
    step_callback: Optional[Callable[[int, int], None]] = None,
    seed: Optional[int] = None,
) -> Image.Image:
    """Regenerate a single panel, optionally with a text modification.

    Default seed behavior: random — the user is regenerating because they
    didn't like the previous result, so we deliberately give a fresh draw
    rather than the deterministic per-story seed.
    """
    panel = story.panels[panel_index]
    gen_w, gen_h = _panel_gen_dims(panel_index)

    # IMPORTANT: do NOT permanently mutate panel.image_prompt with the
    # modification — the previous implementation appended every modification
    # to the stored scene description, so a few rounds of "make it sunnier"
    # would balloon the prompt and drift the scene irreversibly. Build a
    # one-shot effective scene for this single call instead.
    if modification:
        base_scene = (panel.image_prompt or "").strip().rstrip(".")
        effective_scene = base_scene + ". " + modification.strip() if base_scene else modification.strip()
        ephemeral = Panel(
            index=panel.index,
            image_prompt=effective_scene,
            caption=panel.caption,
            characters=list(panel.characters),
            is_placeholder=panel.is_placeholder,
        )
    else:
        ephemeral = panel

    if story.master_reference is None:
        generate_master_reference(story, img_gen)

    full_prompt = _panel_prompt(story, ephemeral)
    logger.info("Regenerating panel " + str(panel_index + 1) + ": " + full_prompt[:80] + "...")

    panel.image = img_gen.generate(
        prompt=full_prompt,
        width=gen_w,
        height=gen_h,
        reference_image=story.master_reference,
        seed=seed,
        step_callback=step_callback,
    )
    return panel.image