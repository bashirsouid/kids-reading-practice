
import torch
from diffusers import ErnieImagePipeline
from PIL import Image

model_id = "baidu/ERNIE-Image-Turbo"
pipe = ErnieImagePipeline.from_pretrained(model_id, torch_dtype=torch.bfloat16)

print(f"VAE config: {pipe.vae.config}")
if hasattr(pipe.vae, 'bn'):
    print(f"VAE BN running_mean shape: {pipe.vae.bn.running_mean.shape}")

# Test encoding an image
img = Image.new("RGB", (1024, 1024), (255, 255, 255))
from diffusers.image_processor import VaeImageProcessor
processor = VaeImageProcessor(vae_scale_factor=pipe.vae_scale_factor)
pixel_values = processor.preprocess(img, height=1024, width=1024).to(dtype=torch.bfloat16)
latents = pipe.vae.encode(pixel_values).latent_dist.sample()
print(f"Encoded latents shape: {latents.shape}")
