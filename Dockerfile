# ============================================================================
# Stage 1: Build Frontend React + TypeScript (Vite)
# ============================================================================
FROM node:22-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ============================================================================
# Stage 2: Runtime Python 3.12 + FastAPI (GCP Cloud Run Ready)
# ============================================================================
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=gcp \
    AI_PROVIDER=vertex-ai \
    PORT=8080

# Unicode font for the PDF guides (arrows, comparison signs); Helvetica lacks them.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r ./backend/requirements.txt

COPY config/ ./config/
COPY backend/ ./backend/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist
RUN mkdir -p /app/data

EXPOSE 8080
WORKDIR /app/backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
