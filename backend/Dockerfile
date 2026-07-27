# syntax=docker/dockerfile:1
# Python 3.13 is a deliberate INTERMEDIATE step — 3.14 is not reachable yet.
# Blockers measured against this requirements.txt (2026-07-27):
#   pydantic-core  (via pydantic 2.10.3) no cp314 wheel; building from source
#                  fails hard — PyO3 0.22.6 caps at 3.13. Needs pydantic >=2.12.
#   asyncpg 0.30.0        no cp314 wheel  -> needs 0.31.0
#   psycopg2-binary 2.9.10 no cp314 wheel -> needs 2.9.11
#   rapidfuzz 3.10.1      no cp314 wheel  -> needs 3.14.0
#   voyageai 0.3.x        Requires-Python <3.14 -> needs >=0.4.0
# Keep this digest in sync with `python-version` in .github/workflows/*.yml.
FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91

WORKDIR /app

# System dependencies
# weasyprint runtime libs (libpango/cairo/gdk-pixbuf + fonts) are needed for
# `app/services/autenti/pdf_renderer.py` which converts the contract draft
# HTML to PDF before uploading to Autenti. fonts-dejavu is a fallback for
# Polish diacritics that liberation-fonts doesn't fully cover.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    fonts-liberation \
    fonts-dejavu \
    tesseract-ocr \
    tesseract-ocr-pol \
    tesseract-ocr-eng \
    poppler-utils \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
# BuildKit cache mount: wheels persist across deploys so subsequent builds
# reuse them. --no-cache-dir on pip itself keeps the image layer clean.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Build metadata for /api/health endpoint (see ~/.claude/rules/deployment.md).
# Defaults to "unknown" so local docker build works without explicit args.
ARG GIT_SHA=unknown
ARG BUILT_AT=unknown
ENV GIT_SHA=$GIT_SHA
ENV BUILT_AT=$BUILT_AT

# Copy application code
COPY . .

# Create uploads directory
RUN mkdir -p /tmp/nexus/uploads

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Security: drop root. If any dependency has an RCE / path-traversal bug,
# the attacker lands as `appuser` (UID 10001) instead of root, limiting
# blast radius on the candidate-CV upload directory and other writable
# paths. The uploads + app dir are chowned so the entrypoint can write logs
# and Alembic can apply migrations at boot.
#
# We intentionally keep the runtime user as root at the ENTRYPOINT level
# (no `USER appuser` here): the entrypoint script must run a privileged
# `chown -R appuser:appgroup /tmp/nexus/uploads` first, then self-re-exec
# via `gosu appuser:appgroup`. This is required because Docker named
# volumes (e.g. `uploads_data` mounted at /tmp/nexus/uploads) created
# under earlier images that ran as root retain root ownership on first
# mount, and `appuser` cannot create subdirectories there. The actual
# Python process still runs as appuser thanks to the gosu drop in
# entrypoint.sh — see that file for the privilege handoff.
RUN groupadd --system --gid 10001 appgroup \
 && useradd  --system --uid 10001 --gid appgroup --no-create-home --shell /usr/sbin/nologin appuser \
 && chown -R appuser:appgroup /app /tmp/nexus

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
