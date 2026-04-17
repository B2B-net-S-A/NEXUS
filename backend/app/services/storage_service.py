"""Local filesystem storage for contract documents.

Coolify production mounts `/tmp/nexus/uploads` as a persistent volume
(see docker-compose.yml `uploads_data` volume). For local dev the same
path is used inside the container via docker-compose override.

If we ever need S3 we swap out save/read/delete without changing the
callers — only this module talks to the filesystem directly.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path(os.environ.get("UPLOADS_DIR", "/tmp/nexus/uploads"))
CONTRACTS_DIR = STORAGE_ROOT / "contracts"

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename(name: str) -> str:
    """Strip path separators and dodgy chars; preserve extension."""
    base = os.path.basename(name or "file")
    base = _SAFE_RE.sub("_", base).strip("._") or "file"
    return base[:200]


def save_contract_document(
    contract_id: int, upload_filename: str, source: BinaryIO
) -> tuple[str, int]:
    """Save a file stream under /{contract_id}/{uuid}-{safe_filename}.

    Returns (relative_path, size_bytes).
    """
    safe = _sanitize_filename(upload_filename)
    target_dir = CONTRACTS_DIR / str(contract_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"{uuid.uuid4().hex[:8]}-{safe}"
    target_path = target_dir / stored_name

    size = 0
    with target_path.open("wb") as dst:
        while True:
            chunk = source.read(1024 * 64)
            if not chunk:
                break
            dst.write(chunk)
            size += len(chunk)

    rel = str(target_path.relative_to(STORAGE_ROOT))
    logger.info("Saved contract document: %s (%d bytes)", rel, size)
    return rel, size


def get_contract_document_path(relative_path: str) -> Path:
    """Resolve the stored relative path back to an absolute path.

    Raises FileNotFoundError if the file isn't on disk (stale DB row).
    """
    abs_path = (STORAGE_ROOT / relative_path).resolve()
    # Guard path-traversal — must stay under STORAGE_ROOT.
    try:
        abs_path.relative_to(STORAGE_ROOT.resolve())
    except ValueError as exc:
        raise FileNotFoundError(f"Invalid storage path: {relative_path}") from exc
    if not abs_path.is_file():
        raise FileNotFoundError(f"File missing on disk: {relative_path}")
    return abs_path


def delete_contract_document(relative_path: str) -> None:
    """Best-effort delete — doesn't raise when file is already gone."""
    try:
        abs_path = get_contract_document_path(relative_path)
    except FileNotFoundError:
        logger.warning("Delete requested for missing file: %s", relative_path)
        return
    try:
        abs_path.unlink()
        logger.info("Deleted contract document: %s", relative_path)
    except OSError:
        logger.exception("Failed to delete %s", relative_path)
