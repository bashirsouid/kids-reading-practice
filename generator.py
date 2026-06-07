"""
generator.py - Core AI generation logic for Comic Book Generator.

Text generation runs via OpenRouter API (Nemotron-3-Nano / GPT-3.5-Turbo).
Image generation runs via OpenRouter API (sourceful/riverflow-v2.5-fast:free).

No local GPU/NPU inference required - all models run remotely via OpenRouter.
"""

import os
import random
import re
import logging
import base64
import concurrent.futures
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Union, List
import threading
import io
from io import BytesIO

import httpx
from PIL import Image, ImageDraw, ImageFont

# Import config for parallelization settings
from backend.config import IMAGE_GEN_CONCURRENCY

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
# SDXL-Turbo is trained at 512px; smaller gen size = faster + better quality
PANEL_GEN_SIZE = 512

# Text model: OpenRouter — uses OpenRouter API for text generation
PRIMARY_TEXT_MODEL_ID = os.getenv("PRIMARY_TEXT_MODEL_ID", "google/gemma-4-31b-it:free")
FALLBACK_TEXT_MODEL_ID = os.getenv("FALLBACK_TEXT_MODEL_ID", "google/gemma-4-26b-a4b-it:free")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
# Backwards compatibility
TEXT_MODEL_ID = PRIMARY_TEXT_MODEL_ID

# Image model: OpenRouter image generation model
# Uses sourceful/riverflow-v2.5-fast:free for free image generation
IMAGE_MODEL_ID = os.getenv("IMAGE_MODEL_ID", "sourceful/riverflow-v2.5-fast:free")


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
    """Generates comic story structure via OpenRouter API.
    
    Uses OpenRouter's chat completion endpoint for text generation.
    """

    def __init__(self, primary_model: str = PRIMARY_TEXT_MODEL_ID, fallback_model: Optional[str] = FALLBACK_TEXT_MODEL_ID):
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self._lock = threading.Lock()
        self._active_model: Optional[str] = None

    def load(self):
        """Validate that the OpenRouter API key is present."""
        if not OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY not set in environment")
        logger.info("TextGenerator ready to use OpenRouter API.")

    def _call_api(self, messages: list[dict], max_tokens: int, temperature: float) -> str:
        """Call OpenRouter chat completion endpoint, trying primary then fallback."""
        import httpx
        for model in [self.primary_model, self.fallback_model]:
            if not model:
                continue
            try:
                logger.info(f"Calling OpenRouter model {model} (max_tokens={max_tokens}, temperature={temperature})")
                url = "https://openrouter.ai/api/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://github.com/bashirs/comic-generator",
                    "X-Title": "Comic Generator",
                }
                payload = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                # Use explicit timeout with TimeoutException handling
                try:
                    response = httpx.post(url, headers=headers, json=payload, timeout=120.0)
                    response.raise_for_status()
                except httpx.TimeoutException:
                    logger.warning(f"OpenRouter model {model} timed out")
                    continue
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                self._active_model = model
                return content.strip()
            except Exception as e:
                # Attempt to capture detailed response from OpenRouter for debugging
                resp_text = ""
                # httpx.HTTPStatusError carries the response object
                if isinstance(e, httpx.HTTPStatusError) and hasattr(e, "response") and e.response is not None:
                    try:
                        resp_text = e.response.text[:500]
                    except Exception:
                        resp_text = "<could not read response>"
                logger.warning(f"OpenRouter model {model} failed: {e}. Response: {resp_text}")
                continue
        raise RuntimeError("All OpenRouter models failed to generate a response")

    def generate(self, prompt: str, max_tokens: int = 1500) -> str:
        """Generate text from a prompt using OpenRouter API."""
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
            return self._call_api(messages, max_tokens=max_tokens, temperature=0.5)

    def generate_story(self, synopsis: str, max_retries: int = 5) -> ComicStory:
        """Generate a complete comic story structure with retry logic."""
        prompt = _build_story_prompt(synopsis)
        for attempt in range(max_retries):
            raw = ""
            try:
                raw = self.generate(prompt, max_tokens=2000)
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

    def generate_random_synopsis(self, theme: Optional[str] = None, seed: Optional[int] = None) -> str:
        """Generate a longer random story synopsis (5-8 sentences)."""
        if seed is not None:
            random.seed(seed)
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

        messages = [
            {"role": "system", "content": "You are a creative children's story writer. Respond with only the synopsis text."},
            {"role": "user", "content": prompt},
        ]
        return self._call_api(messages, max_tokens=500, temperature=0.8)

    def generate_title(self, synopsis: str) -> str:
        """Generate a catchy title for the story based on the synopsis."""
        prompt = (
            "Generate a catchy, fun title (max 5 words) for a children's comic book based on this synopsis:\n"
            "'" + synopsis + "'\n\n"
            "Respond with ONLY the title text, nothing else."
        )
        messages = [
            {"role": "system", "content": "You are a creative children's book author. Respond with only the title."},
            {"role": "user", "content": prompt},
        ]
        title = self._call_api(messages, max_tokens=50, temperature=0.7)
        return title.strip().strip('"').strip("'")


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
    "character names" and producing blank studio images.
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
    feeding the image model a blank-rendering prompt.
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
        # loudly here than to silently feed the image model an empty character list and
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


# - Image Generator -
class ImageGenerator:
    """Generates comic panel images via OpenRouter API.
    
    Uses the sourceful/riverflow-v2.5-fast:free model for free image generation.
    Character consistency is maintained through detailed character descriptions
    embedded in every panel prompt plus deterministic seeding when supported.
    """

    def __init__(self, model_id: str = IMAGE_MODEL_ID):
        self.model_id = model_id

    def load(self):
        """Validate that the OpenRouter API key is present."""
        if not OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY not set in environment")
        logger.info("ImageGenerator ready to use OpenRouter API with model: " + self.model_id)

    def generate(
        self,
        prompt: str,
        width: int = 512,
        height: int = 512,
        steps: int = 1,
        guidance: float = 0.0,
        reference_image: Optional[Image.Image] = None,
        reference_strength: float = 1.0,
        seed: Optional[int] = None,
        step_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Image.Image:
        """Generate an image via OpenRouter API.
        
        Args:
            prompt: Text prompt for image generation
            width: Output image width
            height: Output image height
            steps: Ignored (kept for API compatibility)
            guidance: Ignored (kept for API compatibility)
            reference_image: Optional reference image for img2img (if supported by model)
            reference_strength: Strength of reference image influence (if supported)
            seed: Optional seed for deterministic generation
            step_callback: Ignored (kept for API compatibility)
        
        Returns:
            PIL Image object
        """
        self.load()

        if seed is None:
            seed = int.from_bytes(os.urandom(4), "big")

        # Build the request payload for OpenRouter
        # The riverflow model accepts image generation via chat completions
        # with special parameters for image output
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://github.com/bashirs/comic-generator",
            "X-Title": "Comic Generator",
            "Content-Type": "application/json",
        }

        # Prepare the message content - for image models, we send the prompt
        messages = [{"role": "user", "content": prompt}]

        payload = {
            "model": self.model_id,
            "messages": messages,
            "max_tokens": 1000,
            # Riverflow is an image-only model - requires modalities parameter
            "modalities": ["image"],
        }
        
        # Add seed if provided (some models support it)
        if seed is not None:
            payload["seed"] = seed

        # Add image generation parameters
        # Note: Riverflow v2.5 supports aspect_ratio and image_size via image_config
        # but for simplicity we use the default 1:1 aspect ratio at 1K resolution
        # If specific dimensions are needed, we can add image_config later

        logger.info(f"Calling OpenRouter image model {self.model_id} (size={width}x{height}, seed={seed})")

        # Make the API call
        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=270.0,
        )
        response.raise_for_status()
        data = response.json()

        # Parse the response - OpenRouter image models return images
        # in message.images array with base64 data URLs
        # Format: {"images": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]}
        message = data["choices"][0]["message"]
        images = message.get("images", [])
        
        img_data = None
        
        if images:
            # Primary: extract from images array (OpenRouter image model format)
            image_url = images[0].get("image_url", {}).get("url", "")
            if isinstance(image_url, str) and image_url.startswith("data:image"):
                # Extract base64 data after the comma
                b64_data = image_url.split(",")[1]
                img_data = base64.b64decode(b64_data)
            elif isinstance(image_url, str) and image_url.startswith("http"):
                # It's a URL - fetch the image
                img_response = httpx.get(image_url, timeout=90.0)
                img_response.raise_for_status()
                img_data = img_response.content
            else:
                # Try to decode as raw base64
                try:
                    img_data = base64.b64decode(image_url)
                except Exception:
                    raise RuntimeError(f"Unexpected image URL format: {image_url[:200]}")
        else:
            # Fallback: check if content has base64 data (legacy format)
            content = message.get("content")
            if isinstance(content, str) and content.startswith("data:image"):
                b64_data = content.split(",")[1]
                img_data = base64.b64decode(b64_data)
            elif isinstance(content, str) and content.startswith("http"):
                img_response = httpx.get(content, timeout=90.0)
                img_response.raise_for_status()
                img_data = img_response.content
            elif content is not None:
                try:
                    img_data = base64.b64decode(content)
                except Exception:
                    pass
            
            if img_data is None:
                raise RuntimeError(
                    f"Unexpected image response format - no images in response. "
                    f"Message: {message}"
                )

        # Load the image using PIL
        img = Image.open(BytesIO(img_data))
        img = img.convert("RGB")
        
        # Resize to requested dimensions if needed
        if img.width != width or img.height != height:
            img = img.resize((width, height), Image.LANCZOS)

        logger.info(
            f"Image generation complete (seed={seed}): "
            f"{prompt[:50]}..."
        )
        return img


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
    """Build a tight, scene-first image prompt for one panel (SDXL-Turbo).

    Order (leading tokens weighted most heavily by SDXL text encoder):

        1. Scene description — what's happening in THIS panel.
        2. World/setting — story-wide visual anchor (location, time, mood).
        3. Compact character anchors — only characters present in the panel.
        4. Art-style suffix — tone and palette.
        5. One short continuity reminder.

    Target: ~150 tokens (SDXL-Turbo CLIP tokenizer is 77-token per encoder;
    keep each part concise). Deliberately omitted: full synopsis, full-book
    panel outline, numbered rules lists — these inflate prompts without
    measurable quality lift at 4-step inference.
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
    gives SDXL-Turbo a nudge toward consistent character/style appearances
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
    """Generate the master character reference image via SDXL-Turbo text2img."""
    # Fail loudly rather than pass an empty character list. The old
    # silent-fallthrough behavior produced a blank off-white image
    # (the model rendered the "plain studio background" with no characters).
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
    progress_callback: Optional[Callable[[int, int, int], None]] = None,
):
    """Generate images for all panels in a story.
    
    Args:
        story: The comic story containing panels to generate
        img_gen: ImageGenerator instance to use
        progress_callback: Called with (panel_idx, completed, total) as each panel finishes
    """
    if story.master_reference is None:
        generate_master_reference(story, img_gen)

    panels_to_generate = [
        panel for panel in story.panels
        if not panel.is_placeholder and panel.image is None
    ]
    total = len(panels_to_generate)
    if total == 0:
        return
    
    def generate_panel(panel: Panel):
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
        return panel.index

    # Use ThreadPoolExecutor for parallel panel generation
    # IMAGE_GEN_CONCURRENCY is clamped between 1-6 in config
    with concurrent.futures.ThreadPoolExecutor(max_workers=IMAGE_GEN_CONCURRENCY) as executor:
        # Submit all panel generation tasks
        future_to_panel = {executor.submit(generate_panel, panel): panel for panel in panels_to_generate}
        
        # Process completed tasks as they finish
        completed = 0
        for future in concurrent.futures.as_completed(future_to_panel):
            panel_idx = future.result()
            completed += 1
            if progress_callback:
                progress_callback(panel_idx, completed, total)


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
