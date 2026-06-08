# 📚 AI Comic Book Generator for Kids — OpenRouter Edition

An AI-powered comic book generator that creates engaging 6-panel reading practice materials for children. This version uses **OpenRouter API** for both text and image generation, requiring no local GPU or NPU hardware.

There are a lot of pre-generated sample comics in the `examples/` folder if you just want to select a pre-generated one to print. I haven't read all of them though so I dont have any recommendations for the best ones.

![Example Comic](examples/Basil_s_Big_Bend_fe213bca-2666-4a63-a675-9f48c286a545.png)

---

## 🚀 Features

- **Automated Storytelling**: Generates 6-panel stories with age-appropriate vocabulary using **OpenRouter text models** (Nemotron-3-Nano, GPT-3.5-Turbo, etc.).
- **AI Image Generation**: Produces vibrant panel art using **OpenRouter image models** (Riverflow v2.5 Fast).
- **No Local GPU Required**: Pure API-based inference — works on any machine with internet access.
- **Interactive UI**: Web interface for previewing, regenerating, and exporting comics.

---

## 🛠️ Technology Stack

- **Backend**: FastAPI (Python 3.11)
- **Text inference**: OpenRouter API (HTTP-based)
- **Image inference**: OpenRouter API (Riverflow v2.5 Fast)
- **Frontend**: React 19 + Vite + Tailwind CSS

---

## 📁 Project Structure

```
.
├── backend/
│   ├── main.py           # FastAPI application entry point
│   ├── config.py         # Configuration constants and paths
│   ├── models.py         # Pydantic models and dataclasses
│   ├── state.py          # Global state (jobs, queues, websockets)
│   ├── persistence.py    # Job save/load and image persistence
│   ├── broadcasting.py   # WebSocket and progress broadcasting
│   ├── jobs.py           # Job processing worker
│   ├── utils.py          # Helper utilities
│   └── api/routes.py     # All API route handlers
├── frontend/             # React/Vite frontend application
├── generator.py          # AI generation (OpenRouter API)
├── requirements.txt      # Python dependencies
├── Dockerfile            # Ubuntu 22.04 + Python
└── docker-compose.yml    # Container orchestration
```

---

## 📦 Getting Started

### Prerequisites

- Linux OS (Ubuntu 22.04+ recommended) or any system with Docker
- Internet access (for OpenRouter API)
- OpenRouter API key (free tier available)

### 1. Get an OpenRouter API Key

1. Visit [openrouter.ai](https://openrouter.ai) and sign up
2. Get your API key from the dashboard

### 2. Clone and launch with Docker

```bash
git clone https://github.com/bashirs/comic-generator.git
cd comic-generator

# Set your OpenRouter API key
export OPENROUTER_API_KEY=sk-or-your-key-here

docker compose up --build
```

### 3. Running locally (without Docker)

```bash
# Install dependencies
pip install -r requirements.txt

# Set your OpenRouter API key
export OPENROUTER_API_KEY=sk-or-your-key-here

# Start server
python -m backend.main
# or: uvicorn backend.main:app --host 0.0.0.0 --port 7860
```

Open `http://localhost:7860` in your browser.

---

## ⚙️ Configuration

All settings are controlled via environment variables:

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | _(empty)_ | Your OpenRouter API key (required) |
| `PRIMARY_TEXT_MODEL_ID` | `openrouter/nvidia/nemotron-3-nano-30b-a3b:free` | Primary text model for story generation |
| `FALLBACK_TEXT_MODEL_ID` | `openrouter/openai/gpt-3.5-turbo` | Fallback text model if primary fails |
| `IMAGE_MODEL_ID` | `openrouter/sourceful/riverflow-v2.5-fast:free` | Image generation model |

---

## 📖 How It Works

1. **Idea → Script**: You provide a theme (e.g., "A penguin learning to dance").
2. **LLM via OpenRouter**: Text model generates a 6-panel script with character descriptions, art style, and narrative captions.
3. **Image via OpenRouter**: Riverflow model generates each panel using detailed text prompts that include character descriptions for visual consistency.
4. **Assembly**: Panels are composited into an 8.5×11″ comic page at 300 DPI, ready for printing or PDF export.

---

## 🤝 Contributing

Contributions welcome! If you have improvements or find issues, please open an issue.

---

*Created for the love of reading and the power of AI.*
