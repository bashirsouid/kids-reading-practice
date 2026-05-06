import torch
import os

if torch.cuda.is_available():
    props = torch.cuda.get_device_properties(0)
    print(f"Device name: {props.name}")
    print(f"Compute Units (Multi Processor Count): {props.multi_processor_count}")
    print(f"Total Memory: {props.total_memory / (1024**3):.2f} GB")
else:
    print("CUDA (ROCm) not available")
