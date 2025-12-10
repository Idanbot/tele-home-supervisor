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
# Also install docker CLI (for docker stats/logs commands) and git (for version info)
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl iproute2 tzdata docker.io git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy pre-built wheels from the builder stage and install from them to
# avoid compiling in the final image (smaller, faster, deterministic).
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt

COPY . .

CMD ["python", "/app/bot.py"]

