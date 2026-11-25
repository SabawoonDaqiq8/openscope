# syntax=docker/dockerfile:1

# --- 1. Build the Angular dashboard ------------------------------------------------------
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npx ng build

# --- 2. Python runtime: API + engine, serving the built dashboard -----------------------
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN pip install ".[api,ai]"

COPY examples ./examples
COPY --from=web /web/dist/web/browser ./static

RUN useradd --create-home --uid 1000 openscope && mkdir /data && chown openscope /data
USER openscope

ENV OPENSCOPE_DB_URL=sqlite:////data/openscope.db \
    OPENSCOPE_STATIC_DIR=/app/static \
    OPENSCOPE_DEMO_DIR=/app/examples
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["uvicorn", "openscope.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
