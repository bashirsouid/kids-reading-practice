FROM python:3.11-slim

# ── System dependencies ──────────────────────────────────────────────────────
ENV DEBIAN_FRONTEND=noninteractive
# Disable Valid-Until check to avoid "Release file is not valid yet" errors
RUN apt-get update -o Acquire::Check-Valid-Until=false && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    curl wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Environment variables ──────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV TOKENIZERS_PARALLELISM=false

WORKDIR /app

# ── Python dependencies ──────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ─────────────────────────────────────────────────────────
COPY *.py ./
COPY backend/ ./backend/
COPY static/ ./static/

EXPOSE 7860

CMD ["python", "-u", "-m", "backend.main"]
