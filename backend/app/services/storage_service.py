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
CLIENT_ONE_PAGERS_DIR = STORAGE_ROOT / "client_one_pagers"
BRANDED_CVS_DIR = STORAGE_ROOT / "branded_cvs"

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


# ── Client one-pagers (sales materials) ──────────────────────────────────────


def save_client_one_pager(
    client_id: int, upload_filename: str, source: BinaryIO
) -> tuple[str, int]:
    """Save a sales-material file under /client_one_pagers/{client_id}/{uuid}-{name}.

    Returns (relative_path, size_bytes).
    """
    safe = _sanitize_filename(upload_filename)
    target_dir = CLIENT_ONE_PAGERS_DIR / str(client_id)
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
    logger.info("Saved client one-pager: %s (%d bytes)", rel, size)
    return rel, size


def get_client_one_pager_path(relative_path: str) -> Path:
    """Resolve the stored relative path back to an absolute path.

    Raises FileNotFoundError if the file isn't on disk (stale DB row).
    Guards against path traversal — must stay under STORAGE_ROOT.
    """
    abs_path = (STORAGE_ROOT / relative_path).resolve()
    try:
        abs_path.relative_to(STORAGE_ROOT.resolve())
    except ValueError as exc:
        raise FileNotFoundError(f"Invalid storage path: {relative_path}") from exc
    if not abs_path.is_file():
        raise FileNotFoundError(f"File missing on disk: {relative_path}")
    return abs_path


def delete_client_one_pager(relative_path: str) -> None:
    """Best-effort delete — doesn't raise when file is already gone."""
    try:
        abs_path = get_client_one_pager_path(relative_path)
    except FileNotFoundError:
        logger.warning("Delete requested for missing file: %s", relative_path)
        return
    try:
        abs_path.unlink()
        logger.info("Deleted client one-pager: %s", relative_path)
    except OSError:
        logger.exception("Failed to delete %s", relative_path)


# ── Branded CVs (per CandidateStage finalize) ────────────────────────────────


def save_branded_cv(
    candidate_stage_id: int, upload_filename: str, source: BinaryIO
) -> tuple[str, int]:
    """Save finalized branded CV under /branded_cvs/{stage_id}/{uuid}-{name}.

    Mirror `save_contract_document` — the snapshot is wrapped HTML produced by
    `POST /cv/branded/finalize`. Returns (relative_path, size_bytes).
    """
    safe = _sanitize_filename(upload_filename)
    target_dir = BRANDED_CVS_DIR / str(candidate_stage_id)
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
    logger.info("Saved branded CV: %s (%d bytes)", rel, size)
    return rel, size


def get_branded_cv_path(relative_path: str) -> Path:
    """Resolve stored relative path to absolute, guarding traversal."""
    abs_path = (STORAGE_ROOT / relative_path).resolve()
    try:
        abs_path.relative_to(STORAGE_ROOT.resolve())
    except ValueError as exc:
        raise FileNotFoundError(f"Invalid storage path: {relative_path}") from exc
    if not abs_path.is_file():
        raise FileNotFoundError(f"File missing on disk: {relative_path}")
    return abs_path


def delete_branded_cv(relative_path: str) -> None:
    """Best-effort delete — doesn't raise when file is already gone."""
    try:
        abs_path = get_branded_cv_path(relative_path)
    except FileNotFoundError:
        logger.warning("Delete requested for missing file: %s", relative_path)
        return
    try:
        abs_path.unlink()
        logger.info("Deleted branded CV: %s", relative_path)
    except OSError:
        logger.exception("Failed to delete %s", relative_path)
