# PakkaKhata: one image = React web app + FastAPI service. Runs offline (DEMO_MODE=replay) or on Railway.
# --- stage 1: build the web app
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- stage 2: python service
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DEMO_MODE=replay
# libgomp1: OpenMP runtime LightGBM needs on Linux
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
COPY --from=web /web/dist ./web/dist
# the training world is regenerated (seeded, identical) so "Retrain" works; demo DB, models and reports are committed
RUN python data/generate.py --world-only && useradd -m pakka && chown -R pakka /app
USER pakka
EXPOSE 8000
# Railway / Render / Fly set $PORT
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
