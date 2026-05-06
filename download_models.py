import os
from huggingface_hub import snapshot_download

def download_models():
    models = [
        "Qwen/Qwen2.5-7B-Instruct",
        "baidu/ERNIE-Image-Turbo"
    ]
    
    token = os.environ.get("HF_TOKEN")
    
    for model_id in models:
        print(f"\n{'='*60}")
        print(f"PRE-DOWNLOADING MODEL: {model_id}")
        print(f"{'='*60}")
        
        try:
            snapshot_download(
                repo_id=model_id,
                token=token,
                resume_download=True,
                # For ERNIE-Image-Turbo, we want all files including the large transformer shards
            )
            print(f"\nSUCCESS: {model_id} is fully downloaded and cached.")
        except Exception as e:
            print(f"\nERROR downloading {model_id}: {e}")

if __name__ == "__main__":
    download_models()
