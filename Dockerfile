# ── Stage 1: Build frontend ─────────────────────────────────────────
FROM node:22-alpine AS frontend-builder

WORKDIR /app/web-ui
COPY web-ui/package.json web-ui/package-lock.json ./
RUN npm ci --no-audit
COPY web-ui/ ./
RUN npm run build

# ── Stage 2: Python backend ───────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# System deps (for lxml, faiss, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY api_server.py ./
COPY routers/ ./routers/
COPY app/ ./app/
COPY src/ ./src/

# Copy built frontend
COPY --from=frontend-builder /app/web-ui/dist ./web-ui/dist

# Create data directories
RUN mkdir -p data/raw data/graph data/embeddings data/cache data/workspace data/light_rag

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
