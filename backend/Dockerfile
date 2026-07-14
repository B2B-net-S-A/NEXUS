# syntax=docker/dockerfile:1

# Pin the multi-architecture index so CI/production resolve the same audited
# Python 3.12.13 + Alpine 3.24 base. The arm64 manifest is selected by the
# deployment platform (and by the explicit ARM smoke build in CI).
FROM python:3.12-alpine@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df AS builder

WORKDIR /build

# Native toolchain is isolated in the builder and never copied to production.
# PostgreSQL headers cover asyncpg/psycopg2 source builds; Rust is a fallback
# for cryptography/pydantic wheels on musl/arm64.
RUN apk add --no-cache \
    build-base \
    cargo \
    libffi-dev \
    linux-headers \
    openssl-dev \
    postgresql18-dev

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --upgrade pip==26.1.2 \
    && /opt/venv/bin/python -m pip install -r requirements.txt


FROM python:3.12-alpine@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df AS runtime

WORKDIR /app

# Upgrade packages already present in the pinned base, then install only the
# runtime libraries. Pango/Cairo + both font families render Polish PDFs;
# Tesseract pol+eng and Poppler preserve the CV OCR/extraction pipeline.
RUN apk upgrade --no-cache \
    && apk add --no-cache \
        curl \
        font-dejavu \
        font-liberation \
        gdk-pixbuf \
        libffi \
        libpq \
        libstdc++ \
        pango \
        poppler-utils \
        shared-mime-info \
        su-exec \
        tesseract-ocr \
        tesseract-ocr-data-eng \
        tesseract-ocr-data-pol \
        tzdata \
    && python -m pip install --no-cache-dir --upgrade pip==26.1.2

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Immutable build metadata for /api/health. Production builds fail closed when
# release tooling does not provide an exact source SHA and real UTC timestamp.
ARG GIT_SHA
ARG BUILT_AT
ENV GIT_SHA=$GIT_SHA
ENV BUILT_AT=$BUILT_AT

RUN python -c "import datetime, os, re; sha = os.environ.get('GIT_SHA', ''); built_at = os.environ.get('BUILT_AT', ''); datetime.datetime.strptime(built_at, '%Y-%m-%dT%H:%M:%SZ'); raise SystemExit(0 if re.fullmatch(r'[0-9a-f]{40}', sha) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', built_at) else 1)"

COPY . .

RUN mkdir -p /tmp/nexus/uploads \
    && chmod +x /app/entrypoint.sh /app/migrate.sh \
    && addgroup -S -g 10001 appgroup \
    && adduser -S -D -H -u 10001 -G appgroup appuser \
    && chown -R appuser:appgroup /app /tmp/nexus

# The entrypoint starts as root only to repair ownership on named volumes left
# by legacy images. It immediately re-execs itself through su-exec as UID 10001;
# the Python application never runs with root privileges.
EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
