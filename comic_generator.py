#!/usr/bin/env python3
"""
comic_generator.py — AI Comic Book Generator
Generates a print-ready 8.5x11" comic page using FLUX + a local LLM.
"""

import os
import sys
import json
import math
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# ── Rich TUI ────────────────────────────────────────────────────────────────
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel as RichPanel
from rich.table import Table
from rich.progress import track

console = Console()

# ── Constants ────────────────────────────────────────────────────────────────
DPI = 300
PAGE_W = int(8.5 * DPI)   # 2550
PAGE_H = int(11.0 * DPI)  # 3300
GUTTER = 44
COLS = 2
ROWS = 3
TITLE_H = 220
CAPTION_H = 100
PANEL_GEN_SIZE = 1024

HF_CACHE = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface" / "hub"))

FLUX_MODELS = [
    "black-forest-labs/FLUX.1-kontext-dev",
    "black-forest-labs/FLUX.1-dev",
    "black-forest-labs/FLUX.1-schnell",
    "baidu/ERNIE-Image",
    "baidu/ERNIE-Image-Turbo",
]

TEXT_MODELS = [
    "Qwen/Qwen2.5-1.5B-Instruct",
    "Qwen/Qwen2.5-3B-Instruct",
    "microsoft/Phi-3.5-mini-instruct",
    "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
]

# ── Hardware Detection ────────────────────────────────────────────────────────
def detect_hardware() -> dict:
    hw = {
        "is_unified": False,
        "backend": "cpu",
        "vram_gb": 0,
        "should_offload": True,
        "dtype_str": "float32",
        "device": "cpu",
    }
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0).lower()
            is_amd = "amd" in name or "radeon" in name
            hw["backend"] = "rocm" if is_amd else "cuda"
            hw["device"] = "cuda"
            vram = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            hw["vram_gb"] = vram
            hw["should_offload"] = vram < 16
            hw["dtype_str"] = "bfloat16"

            # Unified memory detection for Strix Halo
            if is_amd and ("395" in name or "8060" in name or "strix halo" in name):
                hw["is_unified"] = True
                hw["vram_gb"] = vram # Use total reported VRAM
                hw["should_offload"] = False
                console.print(f"[green]Detected:[/] {name.upper()} — {vram:.1f} GB unified memory")
            else:
                console.print(f"[green]{hw['backend'].upper()} GPU:[/] {name} ({vram:.1f} GB VRAM)")
        else:
            # Check ROCm via rocminfo fallback
            result = subprocess.run(["rocminfo"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                hw["backend"] = "rocm"
                hw["device"] = "cuda"
                output = result.stdout.lower()
                # Strix Halo / gfx1151 detection
                if "gfx1151" in output or "strix halo" in output or "radeon 395" in output:
                    hw["is_unified"] = True
                    hw["vram_gb"] = 80
                    hw["should_offload"] = False
                    hw["dtype_str"] = "bfloat16"
                    console.print("[green]Detected:[/] Ryzen AI Max 395 (Strix Halo) — 80 GB unified memory")
                else:
                    # Try to get VRAM from rocm-smi
                    smi = subprocess.run(
                        ["rocm-smi", "--showmeminfo", "vram", "--json"],
                        capture_output=True, text=True, timeout=5
                    )
                    if smi.returncode == 0:
                        data = json.loads(smi.stdout)
                        for dev in data.values():
                            if isinstance(dev, dict) and "VRAM Total Memory (B)" in dev:
                                hw["vram_gb"] = int(dev["VRAM Total Memory (B)"]) / (1024**3)
                    hw["should_offload"] = hw["vram_gb"] < 16
                    hw["dtype_str"] = "bfloat16"
                console.print(f"[green]ROCm GPU:[/] {hw['vram_gb']:.1f} GB VRAM, unified={hw['is_unified']}")
    except Exception as e:
        console.print(f"[yellow]Hardware detection warning:[/] {e}")
    return hw


HW = detect_hardware()


def get_torch_dtype():
    import torch
    return {"bfloat16": torch.bfloat16, "float16": torch.float16}.get(HW["dtype_str"], torch.float32)


# ── HuggingFace Cache Scanner ─────────────────────────────────────────────────
def scan_hf_cache(model_list: list[str]) -> dict[str, Path]:
    found = {}
    if not HF_CACHE.exists():
        return found
    for m in model_list:
        slug = "models--" + m.replace("/", "--")
        p = HF_CACHE / slug
        if p.exists():
            found[m] = p
    return found


# ── Model Picker ──────────────────────────────────────────────────────────────
def pick_flux_model() -> str:
    cached = scan_hf_cache(FLUX_MODELS)
    console.rule("[bold cyan]Select Image Generation Model[/]")
    options = {}
    idx = 1
    if cached:
        console.print("[bold green]Found in HF cache:[/]")
        for m, p in cached.items():
            console.print(f"  [{idx}] {m}  [dim](cached)[/dim]")
            options[str(idx)] = m
            idx += 1
    console.print("[bold yellow]Download / load:[/]")
    for m in FLUX_MODELS:
        if m not in cached:
            console.print(f"  [{idx}] {m}")
            options[str(idx)] = m
            idx += 1
    console.print(f"  [{idx}] Enter custom HF model ID or local path")
    options[str(idx)] = "__custom__"
    choice = Prompt.ask("Choice", choices=list(options.keys()), default="1")
    if options[choice] == "__custom__":
        return Prompt.ask("Model ID or local path")
    return options[choice]


def pick_text_model() -> str:
    cached = scan_hf_cache(TEXT_MODELS)
    console.rule("[bold cyan]Select Story/Text Model[/]")
    options = {}
    idx = 1
    if cached:
        console.print("[bold green]Found in HF cache:[/]")
        for m in cached:
            console.print(f"  [{idx}] {m}  [dim](cached)[/dim]")
            options[str(idx)] = m
            idx += 1
    for m in TEXT_MODELS:
        if m not in cached:
            console.print(f"  [{idx}] {m}")
            options[str(idx)] = m
            idx += 1
    idx2 = idx
    console.print(f"  [{idx2}] Enter custom model ID")
    options[str(idx2)] = "__custom__"
    idx2 += 1
    console.print(f"  [{idx2}] Manual entry (no text model)")
    options[str(idx2)] = "__manual__"
    choice = Prompt.ask("Choice", choices=list(options.keys()), default="1")
    if options[choice] == "__custom__":
        return Prompt.ask("Model ID or local path")
    return options[choice]


# ── Text Generator ────────────────────────────────────────────────────────────
class TextGenerator:
    def __init__(self, model_id: str):
        self.model_id = model_id
        self.pipe = None

    def load(self):
        if self.pipe is not None:
            return
        import torch
        from transformers import pipeline
        console.print(f"[cyan]Loading text model:[/] {self.model_id}")
        self.pipe = pipeline(
            "text-generation",
            model=self.model_id,
            torch_dtype=get_torch_dtype(),
            device_map="auto",
            trust_remote_code=True,
        )
        console.print("[green]Text model loaded.[/]")

    def generate(self, prompt: str, max_tokens: int = 1200) -> str:
        self.load()
        messages = [
            {"role": "system", "content": "You are a children's comic book writer. Always respond with valid JSON only, no markdown, no explanation."},
            {"role": "user", "content": prompt},
        ]
        out = self.pipe(messages, max_new_tokens=max_tokens, do_sample=True, temperature=0.7)
        return out[0]["generated_text"][-1]["content"]


# ── Character Registry ────────────────────────────────────────────────────────
@dataclass
class CharacterEntry:
    name: str
    first_panel: int
    image: object  # PIL Image


class CharacterRegistry:
    def __init__(self):
        self.registry: dict[str, CharacterEntry] = {}

    def register(self, name: str, panel_idx: int, image):
        key = name.strip().lower()
        if key not in self.registry:
            self.registry[key] = CharacterEntry(name=name, first_panel=panel_idx, image=image)

    def get_references(self, character_names: list[str], exclude_self_panel: int = -1):
        refs = []
        for n in character_names:
            key = n.strip().lower()
            if key in self.registry:
                entry = self.registry[key]
                refs.append(entry.image)
        return refs

    def all_images(self):
        return [e.image for e in self.registry.values()]


# ── Image Stitcher ────────────────────────────────────────────────────────────
def stitch_references(images: list, max_width_multiplier: float = 3.0):
    """Concatenate reference images side-by-side into one wide image for Kontext."""
    from PIL import Image
    if not images:
        return None
    if len(images) == 1:
        return images[0].convert("RGB")
    target_h = 512
    resized = []
    for img in images:
        img = img.convert("RGB")
        ratio = target_h / img.height
        w = int(img.width * ratio)
        resized.append(img.resize((w, target_h), Image.LANCZOS))
    max_w = int(target_h * max_width_multiplier)
    total_w = sum(r.width for r in resized)
    if total_w > max_w:
        # Scale down uniformly
        scale = max_w / total_w
        resized = [r.resize((int(r.width * scale), int(r.height * scale)), Image.LANCZOS) for r in resized]
    canvas = Image.new("RGB", (sum(r.width for r in resized), resized[0].height), (255, 255, 255))
    x = 0
    for r in resized:
        canvas.paste(r, (x, 0))
        x += r.width
    return canvas


# ── Image Generator ───────────────────────────────────────────────────────────
class ImageGenerator:
    def __init__(self, model_id: str):
        self.model_id = model_id
        self.pipe = None
        self.is_kontext = "kontext" in model_id.lower()

    def load(self):
        if self.pipe is not None:
            return
        import torch
        from diffusers import FluxPipeline
        console.print(f"[cyan]Loading image model:[/] {self.model_id}")
        dtype = get_torch_dtype()
        kwargs = {"torch_dtype": dtype}
        if not Path(self.model_id).exists():
            kwargs["use_auth_token"] = True
        try:
            if "ERNIE" in self.model_id:
                from diffusers import DiffusionPipeline
                self.pipe = DiffusionPipeline.from_pretrained(self.model_id, **kwargs)
                self.is_kontext = False
            elif self.is_kontext:
                try:
                    from diffusers import FluxKontextPipeline
                    self.pipe = FluxKontextPipeline.from_pretrained(self.model_id, **kwargs)
                except ImportError:
                    console.print("[yellow]FluxKontextPipeline not found, falling back to FluxPipeline[/]")
                    self.pipe = FluxPipeline.from_pretrained(self.model_id, **kwargs)
                    self.is_kontext = False
            else:
                self.pipe = FluxPipeline.from_pretrained(self.model_id, **kwargs)
        except Exception as e:
            console.print(f"[red]Error loading model:[/] {e}")
            raise
        if not HW["should_offload"]:
            self.pipe = self.pipe.to(HW["device"])
            console.print(f"[green]Image model loaded on {HW['device']} (no offloading — {HW['vram_gb']:.0f} GB available)[/]")
        else:
            self.pipe.enable_model_cpu_offload()
            console.print("[yellow]CPU offloading enabled (limited VRAM)[/]")
        # Optional torch.compile for ROCm/CUDA speedup
        if HW["backend"] in ("rocm", "cuda") and not HW["should_offload"]:
            if Confirm.ask("[dim]Enable torch.compile for faster generation? (may take ~2min first run)[/dim]", default=False):
                try:
                    import torch
                    self.pipe.transformer = torch.compile(self.pipe.transformer, backend="inductor")
                    console.print("[green]torch.compile enabled.[/]")
                except Exception as e:
                    console.print(f"[yellow]torch.compile skipped: {e}[/]")

    def generate(self, prompt: str, reference_image=None, width: int = 1024, height: int = 1024, steps: int = 28, guidance: float = 3.5):
        import torch
        self.load()
        if "Turbo" in self.model_id:
            steps = min(steps, 8)
        kwargs = dict(
            prompt=prompt,
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=guidance,
            generator=torch.Generator(device=HW["device"]).manual_seed(
                int.from_bytes(os.urandom(4), "big")
            ),
        )
        if reference_image is not None and self.is_kontext:
            kwargs["image"] = reference_image
        result = self.pipe(**kwargs)
        return result.images[0]


# ── Story Generator ───────────────────────────────────────────────────────────
@dataclass
class Panel:
    index: int
    image_prompt: str
    caption: str
    characters: list[str] = field(default_factory=list)
    image: object = None  # PIL Image


@dataclass
class ComicStory:
    title: str
    synopsis: str
    art_style: str
    character_bible: str
    panels: list[Panel] = field(default_factory=list)


def build_story_prompt(synopsis: str) -> str:
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
- Each image_prompt must be self-contained and vivid
- Captions should be simple enough for a child learning to read
- Keep it fun, positive, age-appropriate
"""


def generate_story_with_llm(synopsis: str, text_gen: TextGenerator) -> ComicStory:
    prompt = build_story_prompt(synopsis)
    console.print("[cyan]Generating story with LLM...[/]")
    raw = text_gen.generate(prompt)
    # Extract JSON from response
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("LLM did not return valid JSON")
    data = json.loads(raw[start:end])
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
        title=data["title"],
        synopsis=synopsis,
        art_style=data.get("art_style", "children's book illustration"),
        character_bible=data.get("character_bible", ""),
        panels=panels,
    )


def generate_story_manual(synopsis: str) -> ComicStory:
    title = Prompt.ask("Comic title")
    art_style = Prompt.ask("Art style", default="bright colorful children's book illustration")
    char_bible = Prompt.ask("Character descriptions (brief)")
    panels = []
    for i in range(6):
        console.rule(f"Panel {i+1}")
        prompt = Prompt.ask(f"  Image prompt for panel {i+1}")
        caption = Prompt.ask(f"  Caption for panel {i+1}")
        chars_raw = Prompt.ask(f"  Characters in this panel (comma-separated)", default="")
        chars = [c.strip() for c in chars_raw.split(",") if c.strip()]
        panels.append(Panel(index=i, image_prompt=prompt, caption=caption, characters=chars))
    return ComicStory(title=title, synopsis=synopsis, art_style=art_style, character_bible=char_bible, panels=panels)


# ── Page Renderer ─────────────────────────────────────────────────────────────
def compute_panel_rects():
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


def render_page(story: ComicStory) -> object:
    from PIL import Image, ImageDraw, ImageFont
    page = Image.new("RGB", (PAGE_W, PAGE_H), (245, 235, 220))
    draw = ImageDraw.Draw(page)

    # Title banner
    draw.rectangle([0, 0, PAGE_W, TITLE_H], fill=(20, 20, 60))
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 96)
        font_caption = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
        font_badge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except Exception:
        font_title = ImageFont.load_default()
        font_caption = font_title
        font_badge = font_title

    # Title text with shadow
    tx = PAGE_W // 2
    ty = TITLE_H // 2
    draw.text((tx + 3, ty + 3), story.title, font=font_title, fill=(0, 0, 0), anchor="mm")
    draw.text((tx, ty), story.title, font=font_title, fill=(255, 220, 50), anchor="mm")

    rects = compute_panel_rects()
    for i, (x, y, pw, ph) in enumerate(rects):
        panel = story.panels[i] if i < len(story.panels) else None
        img_h = ph - CAPTION_H

        # Panel border
        draw.rectangle([x - 3, y - 3, x + pw + 3, y + ph + 3], fill=(20, 20, 60))
        draw.rectangle([x, y, x + pw, y + ph], fill=(255, 255, 255))

        if panel and panel.image:
            # Scale image to fit panel image area
            img = panel.image.convert("RGB")
            img = img.resize((pw, img_h), Image.LANCZOS)
            page.paste(img, (x, y))
        else:
            draw.rectangle([x, y, x + pw, y + img_h], fill=(200, 200, 200))
            draw.text((x + pw // 2, y + img_h // 2), f"Panel {i+1}", font=font_badge, fill=(100, 100, 100), anchor="mm")

        # Caption strip
        draw.rectangle([x, y + img_h, x + pw, y + ph], fill=(240, 230, 200))
        if panel:
            # Word wrap caption
            words = panel.caption.split()
            lines = []
            line = ""
            for w in words:
                test = (line + " " + w).strip()
                bbox = draw.textbbox((0, 0), test, font=font_caption)
                if bbox[2] - bbox[0] < pw - 20:
                    line = test
                else:
                    if line:
                        lines.append(line)
                    line = w
            if line:
                lines.append(line)
            line_h = 36
            total_text_h = len(lines) * line_h
            ty_cap = y + img_h + (CAPTION_H - total_text_h) // 2
            for ln in lines:
                draw.text((x + pw // 2, ty_cap), ln, font=font_caption, fill=(20, 20, 20), anchor="mt")
                ty_cap += line_h

        # Panel number badge
        bx, by, br = x + 18, y + 18, 22
        draw.ellipse([bx - br, by - br, bx + br, by + br], fill=(20, 20, 60))
        draw.text((bx, by), str(i + 1), font=font_badge, fill=(255, 255, 255), anchor="mm")

    return page


# ── Generation Orchestrator ───────────────────────────────────────────────────
def generate_all_panels(story: ComicStory, img_gen: ImageGenerator, registry: CharacterRegistry):
    rects = compute_panel_rects()
    for panel in track(story.panels, description="Generating panels..."):
        pw, ph = rects[panel.index][2], rects[panel.index][3]
        img_h = ph - CAPTION_H
        # Compute aspect ratio for panel
        aspect = pw / img_h
        gen_h = PANEL_GEN_SIZE
        gen_w = int(PANEL_GEN_SIZE * aspect)
        gen_w = (gen_w // 64) * 64  # round to multiple of 64
        gen_h = (gen_h // 64) * 64

        # Build prompt with art style and character bible
        full_prompt = f"{story.art_style}. {story.character_bible}. Scene: {panel.image_prompt}"

        # Gather reference images
        refs = registry.get_references(panel.characters)
        ref_image = stitch_references(refs) if refs else None

        console.print(f"  Panel {panel.index + 1}: {len(refs)} character ref(s), prompt={full_prompt[:60]}...")
        panel.image = img_gen.generate(
            prompt=full_prompt,
            reference_image=ref_image,
            width=gen_w,
            height=gen_h,
        )

        # Register newly introduced characters
        for char_name in panel.characters:
            registry.register(char_name, panel.index, panel.image)


# ── Edit Menu ─────────────────────────────────────────────────────────────────
def preview_page(page):
    tmp = Path("/tmp/comic_preview.png")
    page.save(str(tmp), dpi=(DPI, DPI))
    for viewer in ["eog", "feh", "xdg-open", "open"]:
        if shutil.which(viewer):
            subprocess.Popen([viewer, str(tmp)])
            break
    else:
        console.print(f"[yellow]Saved preview to {tmp}[/]")


def edit_menu(story: ComicStory, img_gen: ImageGenerator, registry: CharacterRegistry) -> ComicStory:
    while True:
        page = render_page(story)
        console.rule("[bold cyan]Comic Editor[/]")
        table = Table(show_header=False, box=None)
        table.add_row("[1]", "Start over (new synopsis)")
        table.add_row("[2]", "Regenerate a panel (same prompt)")
        table.add_row("[3]", "Edit a panel image (modify with text prompt)")
        table.add_row("[4]", "Edit caption text only")
        table.add_row("[5]", "Change title")
        table.add_row("[6]", "Preview page")
        table.add_row("[7]", "Save & exit")
        console.print(table)

        choice = Prompt.ask("Choice", choices=["1","2","3","4","5","6","7"])

        if choice == "1":
            return None  # signal restart

        elif choice == "2":
            pnum = int(Prompt.ask("Panel number to regenerate (1-6)")) - 1
            panel = story.panels[pnum]
            rects = compute_panel_rects()
            pw, ph = rects[pnum][2], rects[pnum][3]
            img_h = ph - CAPTION_H
            aspect = pw / img_h
            gen_h = PANEL_GEN_SIZE
            gen_w = (int(PANEL_GEN_SIZE * aspect) // 64) * 64
            gen_h = (gen_h // 64) * 64
            refs = registry.get_references(panel.characters)
            ref_image = stitch_references(refs) if refs else None
            full_prompt = f"{story.art_style}. {story.character_bible}. Scene: {panel.image_prompt}"
            panel.image = img_gen.generate(full_prompt, reference_image=ref_image, width=gen_w, height=gen_h)

        elif choice == "3":
            pnum = int(Prompt.ask("Panel number to edit (1-6)")) - 1
            panel = story.panels[pnum]
            mod = Prompt.ask("Describe the change (e.g. 'make it raining')")
            panel.image_prompt = panel.image_prompt + ". " + mod
            rects = compute_panel_rects()
            pw, ph = rects[pnum][2], rects[pnum][3]
            img_h = ph - CAPTION_H
            aspect = pw / img_h
            gen_w = (int(PANEL_GEN_SIZE * aspect) // 64) * 64
            gen_h = (PANEL_GEN_SIZE // 64) * 64
            # Use existing panel image as anchor ref + character refs
            refs = [panel.image] + registry.get_references(panel.characters)
            ref_image = stitch_references(refs)
            full_prompt = f"{story.art_style}. {story.character_bible}. Scene: {panel.image_prompt}"
            panel.image = img_gen.generate(full_prompt, reference_image=ref_image, width=gen_w, height=gen_h)

        elif choice == "4":
            pnum = int(Prompt.ask("Panel number to edit caption (1-6)")) - 1
            console.print(f"Current: [italic]{story.panels[pnum].caption}[/]")
            story.panels[pnum].caption = Prompt.ask("New caption text")

        elif choice == "5":
            console.print(f"Current title: [italic]{story.title}[/]")
            story.title = Prompt.ask("New title")

        elif choice == "6":
            preview_page(page)

        elif choice == "7":
            out_dir = Path(os.environ.get("COMIC_OUTPUT_DIR", Path.home() / "comics"))
            out_dir.mkdir(parents=True, exist_ok=True)
            safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in story.title)[:40]
            out_path = out_dir / f"{safe_title.replace(' ', '_')}.png"
            page.save(str(out_path), dpi=(DPI, DPI))
            console.print(f"[bold green]Saved:[/] {out_path}")
            break

    return story


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    console.print(RichPanel.fit(
        "[bold yellow]🎨 AI Comic Book Generator[/]\n[dim]Powered by FLUX + local LLM[/dim]",
        border_style="cyan"
    ))
    console.print(f"[dim]Hardware: {HW['backend'].upper()}, VRAM={HW['vram_gb']:.1f}GB, offload={HW['should_offload']}, unified={HW['is_unified']}[/dim]\n")

    # Select models
    flux_model_id = pick_flux_model()
    text_model_id = pick_text_model()

    img_gen = ImageGenerator(flux_model_id)
    text_gen = None if text_model_id == "__manual__" else TextGenerator(text_model_id)

    # Load image model now (keeps both loaded when VRAM allows)
    img_gen.load()
    if text_gen:
        text_gen.load()

    registry = CharacterRegistry()

    while True:
        # Get synopsis
        synopsis = Prompt.ask("\n[bold]Enter a synopsis for the comic story[/]")

        # Generate story structure
        try:
            if text_gen:
                story = generate_story_with_llm(synopsis, text_gen)
            else:
                story = generate_story_manual(synopsis)
        except Exception as e:
            console.print(f"[red]Story generation failed:[/] {e}")
            if Confirm.ask("Switch to manual entry?"):
                story = generate_story_manual(synopsis)
            else:
                continue

        console.print(RichPanel(
            f"[bold]{story.title}[/]\n\n[italic]{story.character_bible}[/]\n\nArt style: {story.art_style}",
            title="Generated Story",
            border_style="green"
        ))
        for p in story.panels:
            console.print(f"  [cyan]Panel {p.index+1}[/] ({', '.join(p.characters) or 'no chars'}): {p.caption}")

        if not Confirm.ask("\nProceed with image generation?", default=True):
            continue

        # Generate all panel images
        registry = CharacterRegistry()
        generate_all_panels(story, img_gen, registry)

        # Enter edit menu
        result = edit_menu(story, img_gen, registry)
        if result is None:
            console.print("[yellow]Starting over...[/]")
            continue
        break

    console.print("[bold green]Done! Enjoy your comic. 🎉[/]")


if __name__ == "__main__":
    main()
