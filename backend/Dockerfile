FROM python:3.12-slim

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

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
