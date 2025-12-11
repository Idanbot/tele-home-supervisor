FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Jerusalem

# Install build deps to compile any wheels (psutil, cryptography, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc build-essential python3-dev curl iproute2 tzdata libffi-dev libssl-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels

COPY requirements.txt .

# Build wheels into /wheels
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
 && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Jerusalem

# Runtime deps (keep minimal). We still install curl and iproute2 so
# runtime checks (ip, curl) work inside the container.
# Also install git (for version info) and download docker CLI binary directly
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl iproute2 tzdata git ca-certificates iputils-ping \
    && rm -rf /var/lib/apt/lists/* \
    && ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "arm64" ]; then DOCKER_ARCH="aarch64"; elif [ "$ARCH" = "amd64" ]; then DOCKER_ARCH="x86_64"; else DOCKER_ARCH="$ARCH"; fi \
    && echo "Downloading Docker CLI for architecture: $DOCKER_ARCH" \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${DOCKER_ARCH}/docker-25.0.3.tgz" -o docker.tgz \
    && tar -xzf docker.tgz --strip-components=1 -C /usr/local/bin docker/docker \
    && rm docker.tgz \
    && chmod +x /usr/local/bin/docker \
    && docker --version

WORKDIR /app

# Copy pre-built wheels from the builder stage and install from them to
# avoid compiling in the final image (smaller, faster, deterministic).
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt

COPY . .

CMD ["python", "/app/bot.py"]

