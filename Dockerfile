FROM python:3.14.2-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Jerusalem \
    # TELL UV TO USE SYSTEM PYTHON (Fixes the mismatch)
    UV_PROJECT_ENVIRONMENT=/usr/local

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc build-essential python3-dev curl iproute2 tzdata libffi-dev libssl-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Install dependencies
COPY pyproject.toml uv.lock README.md ./
# Compile bytecode for faster startup
# We use --no-install-project because we don't need to pip-install the bot itself, just its deps
RUN uv sync --frozen --no-dev --compile-bytecode --no-install-project

# --------------------------------------------------------

FROM python:3.14.2-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Jerusalem

ARG BUILD_VERSION=dev
ENV TELE_HOME_SUPERVISOR_BUILD_VERSION=$BUILD_VERSION

# Runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl iproute2 tzdata git ca-certificates iputils-ping iputils-tracepath procps \
    && rm -rf /var/lib/apt/lists/* \
    && ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "arm64" ]; then DOCKER_ARCH="aarch64"; elif [ "$ARCH" = "amd64" ]; then DOCKER_ARCH="x86_64"; else DOCKER_ARCH="$ARCH"; fi \
    && echo "Downloading Docker CLI for architecture: $DOCKER_ARCH" \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${DOCKER_ARCH}/docker-29.1.2.tgz" -o docker.tgz \
    && tar -xzf docker.tgz --strip-components=1 -C /usr/local/bin docker/docker \
    && rm docker.tgz \
    && chmod +x /usr/local/bin/docker \
    && docker --version

WORKDIR /app

# Create data directory
RUN mkdir -p /app/data && chmod 777 /app/data

# Copy installed packages from builder (Now this actually contains your deps!)
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy source code
COPY . .

CMD ["python", "/app/bot.py"]