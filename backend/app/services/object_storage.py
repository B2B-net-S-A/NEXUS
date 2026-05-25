"""Hetzner Object Storage (S3-compatible) wrapper.

Single source of truth dla CV / candidate documents. Backend nie trzyma
binary content w postgres — w `candidate_documents.file_content` po migracji
(scripts/migrate_cvs_to_object_storage.py) jest NULL, a w `storage_key` jest
klucz S3 w Hetzner Object Storage.

Configuration via env vars (set in Coolify Application > Environment Variables):
    OBJECT_STORAGE_ENDPOINT     https://nbg1.your-objectstorage.com
    OBJECT_STORAGE_ACCESS_KEY   <z Hetzner panel S3 credentials>
    OBJECT_STORAGE_SECRET_KEY   <z Hetzner panel S3 credentials>
    OBJECT_STORAGE_BUCKET       nexus-candidate-documents

Bucket region: NBG1 (Nuremberg) — ten sam DC co serwer prod (zero traffic fees).

Patrz: docs/audit-2026-05-07.md (Faza 3 migracji CV).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Literal, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


def _bucket_name() -> str:
    return os.environ.get("OBJECT_STORAGE_BUCKET", "nexus-candidate-documents")


def _is_configured() -> bool:
    """True jeśli wszystkie wymagane env vars są ustawione."""
    return all(
        os.environ.get(k)
        for k in (
            "OBJECT_STORAGE_ENDPOINT",
            "OBJECT_STORAGE_ACCESS_KEY",
            "OBJECT_STORAGE_SECRET_KEY",
        )
    )


@lru_cache(maxsize=1)
def _client():
    """Lazy boto3 client. Cached żeby nie tworzyć socket connection per request."""
    import boto3
    from botocore.client import Config

    return boto3.client(
        "s3",
        endpoint_url=os.environ["OBJECT_STORAGE_ENDPOINT"],
        aws_access_key_id=os.environ["OBJECT_STORAGE_ACCESS_KEY"],
        aws_secret_access_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def _safe_filename(name: str) -> str:
    """Sanitize filename dla S3 key (zachowaj literki/cyfry/.- bez ścieżek)."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    return name[:200] or "file"


def upload_cv(
    content: bytes,
    filename: str,
    content_type: Optional[str] = None,
) -> str:
    """Upload bytes do object storage.

    Returns storage_key (np. 'cv/2026/05/abc-123.pdf') do zapisania w
    candidate_documents.storage_key.
    """
    today = datetime.now(timezone.utc)
    safe = _safe_filename(filename)
    key = f"cv/{today.year}/{today.month:02d}/{uuid4().hex}-{safe}"
    extra = {"ContentType": content_type} if content_type else {}
    _client().put_object(Bucket=_bucket_name(), Key=key, Body=content, **extra)
    logger.info("uploaded %d bytes to s3://%s/%s", len(content), _bucket_name(), key)
    return key


def get_presigned_download_url(
    storage_key: str,
    expires_in: int = 300,
    filename: Optional[str] = None,
    disposition: Literal["attachment", "inline"] = "attachment",
) -> str:
    """Return URL z TTL — klient ściąga bezpośrednio z Hetzner.

    `filename` pozwala wymusić Content-Disposition (browser zapisze pod
    oryginalną nazwą zamiast UUID-key). `disposition` decyduje czy plik ma
    zostać zapisany jako attachment, czy wyrenderowany inline (preview PDF/img
    w nowej karcie przeglądarki).
    """
    params: dict = {"Bucket": _bucket_name(), "Key": storage_key}
    if filename:
        safe = _safe_filename(filename)
        params["ResponseContentDisposition"] = f'{disposition}; filename="{safe}"'
    return _client().generate_presigned_url(
        "get_object", Params=params, ExpiresIn=expires_in
    )


def download_cv(storage_key: str) -> bytes:
    """Direct download (proxy mode — używać tylko gdy presigned URL nie pasuje).

    Najczęściej preferowane: get_presigned_download_url() + 302 redirect, bo
    klient ściąga bezpośrednio z Hetzner CDN, omijając backend.
    """
    obj = _client().get_object(Bucket=_bucket_name(), Key=storage_key)
    return obj["Body"].read()


def delete_cv(storage_key: str) -> None:
    """Permanent delete object. Idempotent — nie raisuje gdy key już nie istnieje."""
    _client().delete_object(Bucket=_bucket_name(), Key=storage_key)
    logger.info("deleted s3://%s/%s", _bucket_name(), storage_key)


def is_available() -> bool:
    """Health check helper — True jeśli env skonfigurowany.

    Faktyczny ping do storage NIE jest wykonany (trzymamy /api/health szybkie).
    """
    return _is_configured()
