# 📚 AI Comic Book Generator for Kids

An AI-powered comic book generator specifically designed to create engaging reading practice materials for children. This project leverages state-of-the-art LLMs and Image Generation models to turn simple ideas into multi-panel comic stories with consistent characters and vibrant art styles.

![Example Comic](examples/Penguin_s_Dance_94f7980d.png)

## 🚀 Features

- **Automated Storytelling**: Generates 6-panel stories with age-appropriate vocabulary using **Qwen2.5-7B-Instruct**.
- **High-Quality Illustrations**: Produces beautiful 1024x1024 panels using **SDXL-Lightning** (4-step inference).
- **Long Prompt Support**: Custom embedding chunking allows for extremely detailed scene descriptions (> 77 tokens) without truncation.
- **Hardware Optimized**: Specifically tuned for **AMD Strix Halo (Ryzen AI Max 395)** hardware:
  - Aggressive GPU Compute Unit masking for host stability.
  - TinyVAE integration for massive VRAM savings.
  - Efficient memory management for shared 96GB GTT environments.
- **Interactive UI**: A sleek web interface to preview, regenerate, and manage your comic books.

## 🛠️ Technology Stack

- **Backend**: FastAPI (Python 3.10)
- **Image Model**: SDXL-Lightning (ByteDance) + TinyVAE
- **Text Model**: Qwen2.5-7B-Instruct (via Transformers)
- **Compute Backend**: AMD ROCm (PyTorch)
- **Infrastructure**: Docker Compose

## 📦 Getting Started

### Prerequisites
- Linux OS (Ubuntu 22.04+ recommended)
- AMD GPU with ROCm support (Strix Halo/RDNA3 preferred)
- Docker & Docker Compose

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/bashirsouid/kids-reading-practice.git
   cd kids-reading-practice
   ```

2. **Launch with Docker**:
   ```bash
   docker compose up --build
   ```

3. **Access the App**:
   Open your browser and navigate to `http://localhost:7860`.

## ⚙️ Configuration

The system is pre-configured for stable operation on Strix Halo hardware. Key resource limits are managed in `gpu_utils.py`:
- `HSA_CU_MASK`: Limits the GPU to a subset of compute units to ensure the host window manager remains responsive during heavy generation tasks.

## 📖 How it Works

1. **Idea to Script**: You provide a theme (e.g., "A penguin learning to dance").
2. **LLM Generation**: Qwen generates a cohesive 6-panel script, including character descriptions, art style, and narrative captions.
3. **Image Synthesis**: The script is passed to the SDXL-Lightning pipeline. For long descriptions, the prompt is automatically chunked into 77-token blocks and re-stitched in embedding space to ensure full adherence to the scene details.
4. **Final Assembly**: The panels are served via the web UI for immediate reading practice.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request or open an issue for hardware compatibility reports.

---
*Created for the love of reading and the power of AI.*
