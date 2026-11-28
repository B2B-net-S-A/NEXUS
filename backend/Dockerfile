# syntax=docker/dockerfile:1
# Python 3.15 od 24.11.2026 (z 3.13, decyzja Artura, #3425). Sprawdzone przed
# zmianą: pełny pytest na 3.15 (12 shardów na Postgresie), budowa obrazu
# linux/amd64, import app.main, SaxonC-HE. Jedyny bloker wheeli: rapidfuzz
# 3.14.5 bez cp315 -> 3.14.6. Do 3.16: slowapi woła
# asyncio.iscoroutinefunction (usunięte w 3.16, DeprecationWarning przy imporcie).
# Keep this digest in sync with `python-version` in .github/workflows/*.yml.
FROM python:3.15-slim@sha256:08a4c22c92b79ec821a7ad49768480039ee5b7accac3955228e75366e30abc8e

WORKDIR /app

# System dependencies
# weasyprint runtime libs (libpango/cairo/gdk-pixbuf + fonts) are needed for
# `app/services/autenti/pdf_renderer.py` which converts the contract draft
# HTML to PDF before uploading to Autenti. fonts-dejavu is a fallback for
# Polish diacritics that liberation-fonts doesn't fully cover.
# `apt-get upgrade`: łatki bezpieczeństwa Debiana, których digest obrazu bazowego
# jeszcze nie ma (28.11.2026 libzstd1 z deb13u1 — Trivy obrazów produkcji,
# docs/claude/podstawy/skanery-bezpieczenstwa.md).
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
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
    libreoffice-writer-nogui \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Edytor CV 3 (J2, 14.10.2026): podgląd CV jako strony PDF z pliku Word
# (`app/services/cv_pdf_preview.py`) — LibreOffice bez GUI powyżej. Czcionka
# szablonu CV (Montserrat, SIL OFL) z repo, bo pakiet `fonts-montserrat` nie
# jest pewny w każdej wersji Debiana obrazu bazowego; pliki mają nazwy rodzin,
# które piszą pliki CV („Montserrat SemiBold”, „Montserrat Medium”…).
COPY app/assets/fonts/montserrat/ /usr/share/fonts/truetype/montserrat/
RUN fc-cache -f

# Install Python dependencies
# BuildKit cache mount: wheels persist across deploys so subsequent builds
# reuse them. --no-cache-dir on pip itself keeps the image layer clean.
COPY requirements.txt .
# Po instalacji pip wychodzi z obrazu: jego wbudowane kopie urllib3, msgpack
# i pkg_resources (pip/_vendor/vendor.txt) to 5 znalezisk HIGH w Trivy obrazów
# produkcji (28.11.2026), a w runtime nikt pipa nie woła. Doraźnie w kontenerze:
# `python -m ensurepip` (koło pipa zostaje w ensurepip/_bundled).
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt \
    && pip uninstall -y pip

# Build metadata for /api/health endpoint (see ~/.claude/rules/deployment.md).
# Defaults to "unknown" so local docker build works without explicit args.
ARG GIT_SHA=unknown
ARG BUILT_AT=unknown
ENV GIT_SHA=$GIT_SHA
ENV BUILT_AT=$BUILT_AT

# Copy application code
COPY . .
RUN printf '%s\n' "$GIT_SHA" > /app/.nexus-build-sha

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
