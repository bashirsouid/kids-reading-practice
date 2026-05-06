import logging
import torch
from generator import ImageGenerator, ComicStory, Panel
from PIL import Image

logging.basicConfig(level=logging.INFO)

def test_ernie_gen():
    gen = ImageGenerator()
    print("Loading model...")
    gen.load()
    
    print("Generating Panel 0 (text-to-image)...")
    img0 = gen.generate(
        prompt="A cute brown mouse with a red hat, children's book style",
        width=512,
        height=512,
        steps=8,
        guidance=1.0
    )
    img0.save("scratch/test_panel0.png")
    
    print("Generating Panel 1 (image-to-image with Panel 0 reference)...")
    img1 = gen.generate(
        prompt="A cute brown mouse with a red hat is eating a piece of cheese, children's book style",
        width=512,
        height=512,
        steps=8,
        guidance=1.0,
        init_image=img0,
        strength=0.6
    )
    img1.save("scratch/test_panel1.png")
    print("Test complete. Check scratch/test_panel0.png and scratch/test_panel1.png")

if __name__ == "__main__":
    test_ernie_gen()
