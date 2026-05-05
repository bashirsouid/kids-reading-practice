import os, shutil

os.makedirs("output", exist_ok=True)
for fname in ["comic_generator.py", "install.sh", "run.sh"]:
    shutil.copy(f"/tmp/{fname}", f"output/{fname}")
    size = os.path.getsize(f"output/{fname}")
    print(f"output/{fname}: {size} bytes")
