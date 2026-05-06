
import torch
from diffusers import ErnieImagePipeline

model_id = "baidu/ERNIE-Image-Turbo"
pipe = ErnieImagePipeline.from_pretrained(model_id, torch_dtype=torch.bfloat16)

print("VAE Structure:")
print(pipe.vae)

if hasattr(pipe, 'transformer'):
    print("\nTransformer config:")
    print(pipe.transformer.config)
