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
IMAGE_MODEL_ID = "baidu/ERNIE-Image-Turbo"
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
      "caption": "Exactly 3-5 sentences (50-70 words) providing rich narration and plenty of reading practice for kids."
    }}
  ]
}}

Rules:
- Exactly 6 panels (index 0-5)
- "characters" must use the EXACT same character name strings across all panels
- Each image_prompt must be a vivid, literal visual description of the scene described in the 'caption' to ensure perfect visual alignment.
- Captions must be 3-5 sentences long, descriptive, and engaging for children learning to read.
- Keep it positive and educational.
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



# ── Custom Ernie Pipeline ───────────────────────────────────────────────────
from diffusers import ErnieImagePipeline
from diffusers.pipelines.ernie_image.pipeline_output import ErnieImagePipelineOutput
from diffusers.utils.torch_utils import randn_tensor


def _patch_vae_for_cpu_execution(vae):
    """Pin VAE to CPU (fp32) and route encode/decode through CPU.

    On gfx1151 (Strix Halo / Ryzen AI Max) the VAE decode at the end of
    generation hits conv shapes whose MIOpen solver hangs the GPU ring;
    the kernel watchdog then resets the device and takes the host
    compositor down with it. Keeping the VAE on CPU sidesteps the entire
    class of hang. The VAE is small and a 768×768 decode finishes in
    ~1–2s on this hardware — a fine trade for not crashing the desktop.
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


class ErnieImageImg2ImgPipeline(ErnieImagePipeline):
    """Custom implementation of Image-to-Image for ErnieImagePipeline."""
    
    @torch.no_grad()
    def __call__(
        self,
        prompt: Optional[Union[str, List[str]]] = None,
        image: Optional[Image.Image] = None,
        strength: float = 0.6,
        height: int = 1024,
        width: int = 1024,
        num_inference_steps: int = 8,
        guidance_scale: float = 1.0,
        num_images_per_prompt: int = 1,
        generator: Optional[torch.Generator] = None,
        latents: Optional[torch.Tensor] = None,
        output_type: str = "pil",
        return_dict: bool = True,
        use_pe: bool = True,
        **kwargs
    ):
        if image is None:
            return super().__call__(
                prompt=prompt, height=height, width=width, 
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale, generator=generator,
                latents=latents, output_type=output_type,
                return_dict=return_dict, use_pe=use_pe, **kwargs
            )

        device = self._execution_device
        dtype = self.transformer.dtype
        self._guidance_scale = guidance_scale

        # 1. Enhance prompt
        if use_pe and self.pe is not None:
            prompt = [self._enhance_prompt_with_pe(p, device, width=width, height=height) for p in [prompt] if isinstance(p, str)]
            if isinstance(prompt, list) and len(prompt) == 1:
                prompt = prompt[0]

        # 2. Encode prompt
        text_hiddens = self.encode_prompt(prompt, device, num_images_per_prompt)
        if self.do_classifier_free_guidance:
            uncond_text_hiddens = self.encode_prompt("", device, num_images_per_prompt)

        # 3. Prepare image latents
        # VAE is pinned to CPU/fp32 for stability — preprocess stays on
        # CPU/fp32 to match, then we promote latents to (device, dtype)
        # for the diffusion loop.
        from diffusers.image_processor import VaeImageProcessor
        image_processor = VaeImageProcessor(vae_scale_factor=self.vae_scale_factor)
        init_image_cpu = image_processor.preprocess(image, height=height, width=width).to(dtype=torch.float32)

        # Use .mode() rather than .sample(generator): the patched VAE
        # returns CPU tensors and `generator` lives on CUDA, so sample()
        # would device-mismatch. Img2img adds explicit noise below, so
        # a deterministic encode is fine.
        init_latents = self.vae.encode(init_image_cpu).latent_dist.mode()
        init_latents = init_latents.to(device=device, dtype=dtype)

        # Patchify first, THEN normalize — order matters. The bn buffers
        # are sized for the 128-channel patchified latent space, so the
        # original "normalize 32ch then patchify" path was incorrect (and
        # would shape-mismatch on the unnormalize side after denoising).
        # This mirrors the parent ErnieImagePipeline txt2img path.
        init_latents = self._patchify_latents(init_latents)

        # Handle case where VAE BN stats have more channels than latents (e.g., due to different model versions)
        bn_mean = self.vae.bn.running_mean[:init_latents.shape[1]].view(1, -1, 1, 1).to(device=device, dtype=dtype)
        bn_std = torch.sqrt(
            self.vae.bn.running_var[:init_latents.shape[1]].view(1, -1, 1, 1).to(dtype=torch.float32) + 1e-5
        ).to(device=device, dtype=dtype)
        init_latents = (init_latents - bn_mean) / bn_std
        
        # 4. Add noise based on strength
        # Turbo models use very few steps, so we map strength to steps
        timesteps_to_run = int(num_inference_steps * strength)
        if timesteps_to_run < 1: timesteps_to_run = 1
        
        # Sigmas for flow matching: 1.0 (noise) -> 0.0 (clean)
        # For img2img, we start at sigma = strength
        # Ensure we use float32 for scheduler compatibility to avoid BFloat16 issues
        sigmas = torch.linspace(strength, 0.0, timesteps_to_run + 1, dtype=torch.float32, device=device)
        # Convert to numpy array for scheduler to avoid tensor type issues
        sigmas_np = sigmas[:-1].cpu().numpy()
        self.scheduler.set_timesteps(sigmas=sigmas_np, device=device)
        
        noise = randn_tensor(init_latents.shape, generator=generator, device=device, dtype=dtype)
        latents = (1.0 - strength) * init_latents + strength * noise

        # 5. Denoising loop
        cfg_text_hiddens = list(uncond_text_hiddens) + list(text_hiddens) if self.do_classifier_free_guidance else text_hiddens
        text_bth, text_lens = self._pad_text(
            text_hiddens=cfg_text_hiddens, device=device, dtype=dtype, text_in_dim=self.transformer.config.text_in_dim
        )

        for i, t in enumerate(self.scheduler.timesteps):
            latent_model_input = torch.cat([latents, latents], dim=0) if self.do_classifier_free_guidance else latents
            t_batch = torch.full((latent_model_input.shape[0],), t.to(dtype=torch.float32).item(), device=device, dtype=dtype)

            pred = self.transformer(
                hidden_states=latent_model_input,
                timestep=t_batch,
                text_bth=text_bth,
                text_lens=text_lens,
                return_dict=False,
            )[0]

            if self.do_classifier_free_guidance:
                pred_uncond, pred_cond = pred.chunk(2, dim=0)
                pred = pred_uncond + guidance_scale * (pred_cond - pred_uncond)

            latents = self.scheduler.step(pred, t, latents).prev_sample

        # 6. Post-process
        if output_type == "latent":
            return latents

        # Unnormalize and Unpatchify
        latents = latents * bn_std + bn_mean
        latents = self._unpatchify_latents(latents)
        
        # vae.decode is patched to run on CPU/fp32; result is a CPU tensor.
        images = self.vae.decode(latents, return_dict=False)[0]
        images = (images.clamp(-1, 1) + 1) / 2
        images = images.permute(0, 2, 3, 1).float().cpu().numpy()

        if output_type == "pil":
            images = [Image.fromarray((img * 255).astype("uint8")) for img in images]

        return ErnieImagePipelineOutput(images=images, revised_prompts=None)


# ── Image Generator ──────────────────────────────────────────────────────────
class ImageGenerator:
    """Generates comic panel images using SDXL Lightning (4-step)."""

    def __init__(self, model_id: str = IMAGE_MODEL_ID):
        self.model_id = model_id
        self.pipe = None
        self._lock = threading.Lock()

    def load(self):
        """Load the image model into GPU memory (with VAE pinned to CPU)."""
        if self.pipe is not None:
            return

        logger.info(f"Loading image model: {self.model_id}")

        self.pipe = ErnieImageImg2ImgPipeline.from_pretrained(
            self.model_id,
            torch_dtype=DTYPE,
        ).to(DEVICE)

        # Pin the VAE to CPU. End-of-generation VAE convs were hanging
        # the amdgpu ring on gfx1151 and resetting the GPU (which kills
        # both this process and the host compositor). VAE tiling/slicing
        # only reduce the probability — running on CPU eliminates it.
        self.pipe.vae = _patch_vae_for_cpu_execution(self.pipe.vae)
        logger.info("VAE pinned to CPU/fp32 for gfx1151 stability.")

        try:
            self.pipe.enable_attention_slicing(1)
        except Exception as e:
            logger.warning(f"Attention slicing not available: {e}")

        logger.info("ERNIE-Image-Turbo loaded.")


    def generate(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        steps: int = 8,
        guidance: float = 1.0,
        init_image: Optional[Image.Image] = None,
        strength: float = 0.6,
    ) -> Image.Image:
        """Generate an image from a text prompt, optionally using an init image for consistency."""
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

            with torch.inference_mode():
                result = self.pipe(
                    prompt=prompt,
                    image=init_image,
                    strength=strength,
                    width=width,
                    height=height,
                    num_inference_steps=steps,
                    guidance_scale=guidance,
                    generator=torch.Generator(device=DEVICE).manual_seed(seed),
                    # ERNIE's prompt-enhancer is a separate LLM that
                    # piles more pressure onto the GPU. Keeping it off
                    # is one less moving part on flaky hardware.
                    use_pe=False,
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
def generate_all_panels(
    story: ComicStory,
    img_gen: ImageGenerator,
    progress_callback: Optional[Callable[[int, int], None]] = None,
):
    """Generate images for all panels in a story."""
    rects = compute_panel_rects()
    total = len(story.panels)

    anchor_image = None
    for panel in story.panels:
        pw, ph = rects[panel.index][2], rects[panel.index][3]
        img_h = ph - CAPTION_H
        aspect = pw / img_h

        gen_h = PANEL_GEN_SIZE
        gen_w = int(PANEL_GEN_SIZE * aspect)
        gen_w = (gen_w // 16) * 16  # ERNIE needs divisibility by 16
        gen_h = (gen_h // 16) * 16

        full_prompt = f"{story.art_style}. {story.character_bible}. Scene: {panel.image_prompt}."

        logger.info(f"Generating panel {panel.index + 1}/{total}: {full_prompt[:80]}...")
        
        # Use anchor image for consistency if it's not the first panel
        panel.image = img_gen.generate(
            prompt=full_prompt,
            width=gen_w,
            height=gen_h,
            init_image=anchor_image,
            strength=0.6 if anchor_image else 1.0,
        )

        if panel.index == 0:
            anchor_image = panel.image

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

    # Optimize prompt: Use art style, character bible, and the visual scene description.
    full_prompt = f"{story.art_style}. {story.character_bible}. Scene: {panel.image_prompt}."

    logger.info(f"Regenerating panel {panel_index + 1}: {full_prompt[:80]}...")
    # Use the first panel as anchor if it exists for consistency
    anchor_image = story.panels[0].image if len(story.panels) > 0 and story.panels[0].image else None
    
    panel.image = img_gen.generate(
        prompt=full_prompt,
        width=gen_w,
        height=gen_h,
        init_image=anchor_image if panel_index > 0 else None,
        strength=0.6 if panel_index > 0 and anchor_image else 1.0,
    )
    return panel.image
