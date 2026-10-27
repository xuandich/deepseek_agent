# syntax=docker/dockerfile:1.4
FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y \
    libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 \
    libasound2 libxshmfence1 libxrandr2 libxcomposite1 \
    libxdamage1 libxfixes3 libx11-xcb1 libxtst6 libpango-1.0-0 \
    libcairo2 libglib2.0-0 libgtk-3-0 libxslt1.1 libxss1 libxcb1 libxcb-shm0 \
    libxcb-shape0 libxcb-xfixes0 libxcb-randr0 \
    libgl1-mesa-dri libva2 \
    libvdpau1 libexpat1 libfontconfig1 libfreetype6 libjpeg62-turbo \
    libpng16-16 libwebp7 libopus0 libvpx7 libevent-2.1-7 libffi8 \
    libgssapi-krb5-2 libicu72 libssl3 libcurl4 libarchive13 libbz2-1.0 \
    liblzma5 libsqlite3-0 libudev1 libxkbcommon-x11-0 \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# 1. Copy dependency manifests first (changes less often)
COPY pyproject.toml uv.lock* ./

# 2. Sync the virtual environment (without the project itself yet)
RUN uv sync --frozen --no-install-project --no-dev || uv sync --no-install-project --no-dev

# 3. Install the Playwright browser, using a cache mount
RUN --mount=type=cache,target=/root/.cache/ms-playwright \
    uv run playwright install --with-deps chromium

# 4. Copy the rest of the source
COPY . .

# 5. Install the project itself
RUN uv sync --frozen --no-dev || uv sync --no-dev

# 6. Prepare the data directory
RUN mkdir -p /root/.deepseek-agent/session

VOLUME ["/root/.deepseek-agent"]
ENTRYPOINT ["uv", "run", "deepseek-agent"]
