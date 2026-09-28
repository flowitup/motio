# Motio engine (JSON API + video pipeline) for a Linux server.
#   docker build -t motio-engine .
#   docker run -e MOTIO_TOKEN=... -e ELEVENLABS_API_KEY=... -p 8765:8765 -v motio-data:/data motio-engine
# The server stack (engine + Postiz + HTTPS) lives in deploy/, see docs/DEPLOY.md.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    MOTIO_DATA=/data \
    HF_HOME=/data/cache/huggingface

# ffmpeg for render/ASR, DejaVu (Latin) + Noto CJK fonts for the Linux entries in config._FONTS,
# tzdata so TZ applies to channel posting times
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core fonts-noto-cjk ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
# yt-dlp solves YouTube's JavaScript challenges with Deno (+ the yt-dlp-ejs package from uv.lock)
COPY --from=denoland/deno:bin-2.9.7 /deno /usr/local/bin/deno

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY motio ./motio

RUN useradd --create-home --uid 1000 motio && mkdir -p /data && chown motio:motio /data
USER motio
VOLUME /data
EXPOSE 8765

# Token comes from MOTIO_TOKEN; the engine refuses to listen on 0.0.0.0 without one.
CMD ["python", "-m", "motio", "engine", "--host", "0.0.0.0", "--port", "8765", "--headless"]
