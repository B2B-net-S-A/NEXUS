FROM python:3.14-slim@sha256:a7185a8e40af01bf891414a4df16ef10fc6000cee460a404a13da9029fe41604

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
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
RUN groupadd --system --gid 10001 appgroup \
 && useradd  --system --uid 10001 --gid appgroup --no-create-home --shell /usr/sbin/nologin appuser \
 && chown -R appuser:appgroup /app /tmp/nexus
USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
