# 1) build the React dashboard (also served by the backend at / as a fallback)
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# 2) the agent (Playwright image already has Chromium's system libraries)
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/app/data PORT=8000
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && python -m playwright install --with-deps chromium
COPY . .
COPY --from=ui /ui/dist ./frontend/dist
RUN mkdir -p /app/data
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
