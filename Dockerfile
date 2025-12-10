FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Jerusalem

# Add toolchain + headers so psutil can build on aarch64
RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc build-essential python3-dev curl iproute2 tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Keep pip/setuptools/wheel up to date to prefer wheels when available
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["python", "/app/bot.py"]

