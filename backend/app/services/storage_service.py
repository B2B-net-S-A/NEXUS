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
CLIENT_REQUIRED_DOCS_DIR = STORAGE_ROOT / "client_required_docs"
CLIENT_FRAMEWORK_CONTRACTS_DIR = STORAGE_ROOT / "client_framework_contracts"
CLIENT_CONTRACT_AMENDMENTS_DIR = STORAGE_ROOT / "client_contract_amendments"
CLIENT_ORDER_POS_DIR = STORAGE_ROOT / "client_orders"

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename(name: str) -> str:
    """Strip path separators and dodgy chars; preserve extension."""
    base = os.path.basename(name or "file")
    base = _SAFE_RE.sub("_", base).strip("._") or "file"
    return base[:200]


def save_contract_document(
    contract_id: int,
    upload_filename: str,
    source: BinaryIO,
    stored_name: str | None = None,
) -> tuple[str, int]:
    """Save a file stream under /{contract_id}/{uuid}-{safe_filename}.

    Returns (relative_path, size_bytes).

    ``stored_name`` overrides the random prefix with a caller-chosen, stable
    key. Use it for machine-generated documents that a background job may have
    to write more than once (crash between the file write and the DB commit):
    the retry then overwrites the same path instead of leaving the first,
    unreferenced copy orphaned in storage. Human uploads leave it None — two
    uploads of ``umowa.pdf`` are genuinely two documents.
    """
    safe = _sanitize_filename(upload_filename)
    target_dir = CONTRACTS_DIR / str(contract_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    if stored_name is not None:
        stored_name = _sanitize_filename(stored_name)
    else:
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


# ── Client required documents (NDA, RODO, ...) ───────────────────────────────


def save_client_required_doc(
    client_id: int, upload_filename: str, source: BinaryIO
) -> tuple[str, int]:
    """Save under /client_required_docs/{client_id}/{uuid}-{name}.

    Returns (relative_path, size_bytes).
    """
    safe = _sanitize_filename(upload_filename)
    target_dir = CLIENT_REQUIRED_DOCS_DIR / str(client_id)
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
    logger.info("Saved client required doc: %s (%d bytes)", rel, size)
    return rel, size


def get_client_required_doc_path(relative_path: str) -> Path:
    """Resolve relative path back to absolute path. Guards against traversal."""
    abs_path = (STORAGE_ROOT / relative_path).resolve()
    try:
        abs_path.relative_to(STORAGE_ROOT.resolve())
    except ValueError as exc:
        raise FileNotFoundError(f"Invalid storage path: {relative_path}") from exc
    if not abs_path.is_file():
        raise FileNotFoundError(f"File missing on disk: {relative_path}")
    return abs_path


def delete_client_required_doc(relative_path: str) -> None:
    """Best-effort delete — doesn't raise when file is already gone."""
    try:
        abs_path = get_client_required_doc_path(relative_path)
    except FileNotFoundError:
        logger.warning("Delete requested for missing file: %s", relative_path)
        return
    try:
        abs_path.unlink()
        logger.info("Deleted client required doc: %s", relative_path)
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


# ── Generic storage helpers (factor for new doc types) ───────────────────────


def _save_to(
    target_dir: Path, upload_filename: str, source: BinaryIO
) -> tuple[str, int]:
    """Stream-save into ``target_dir`` with sanitized name + uuid prefix."""
    safe = _sanitize_filename(upload_filename)
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
    return str(target_path.relative_to(STORAGE_ROOT)), size


def _resolve_under_root(relative_path: str) -> Path:
    """Resolve ``relative_path`` under STORAGE_ROOT with traversal guard."""
    abs_path = (STORAGE_ROOT / relative_path).resolve()
    try:
        abs_path.relative_to(STORAGE_ROOT.resolve())
    except ValueError as exc:
        raise FileNotFoundError(f"Invalid storage path: {relative_path}") from exc
    if not abs_path.is_file():
        raise FileNotFoundError(f"File missing on disk: {relative_path}")
    return abs_path


def _delete_relative(relative_path: str, label: str) -> None:
    """Best-effort delete by relative path — never raises."""
    try:
        abs_path = _resolve_under_root(relative_path)
    except FileNotFoundError:
        logger.warning("Delete requested for missing %s: %s", label, relative_path)
        return
    try:
        abs_path.unlink()
        logger.info("Deleted %s: %s", label, relative_path)
    except OSError:
        logger.exception("Failed to delete %s", relative_path)


# ── Client framework contracts (MSA PDFs) ────────────────────────────────────


def save_client_framework_contract(
    client_id: int, upload_filename: str, source: BinaryIO
) -> tuple[str, int]:
    """Save MSA PDF under /client_framework_contracts/{client_id}/{uuid}-{name}."""
    rel, size = _save_to(
        CLIENT_FRAMEWORK_CONTRACTS_DIR / str(client_id), upload_filename, source
    )
    logger.info("Saved client framework contract: %s (%d bytes)", rel, size)
    return rel, size


def get_client_framework_contract_path(relative_path: str) -> Path:
    return _resolve_under_root(relative_path)


def delete_client_framework_contract(relative_path: str) -> None:
    _delete_relative(relative_path, "client framework contract")


# ── Client contract amendments (aneksy PDF) ──────────────────────────────────


def save_client_contract_amendment(
    framework_contract_id: int, upload_filename: str, source: BinaryIO
) -> tuple[str, int]:
    """Save aneks under /client_contract_amendments/{fc_id}/{uuid}-{name}."""
    rel, size = _save_to(
        CLIENT_CONTRACT_AMENDMENTS_DIR / str(framework_contract_id),
        upload_filename,
        source,
    )
    logger.info("Saved client contract amendment: %s (%d bytes)", rel, size)
    return rel, size


def get_client_contract_amendment_path(relative_path: str) -> Path:
    return _resolve_under_root(relative_path)


def delete_client_contract_amendment(relative_path: str) -> None:
    _delete_relative(relative_path, "client contract amendment")


# ── Client orders (PO PDFs from clients) ─────────────────────────────────────


def save_client_order_po(
    order_id: int, upload_filename: str, source: BinaryIO
) -> tuple[str, int]:
    """Save PO PDF under /client_orders/{order_id}/{uuid}-{name}."""
    rel, size = _save_to(CLIENT_ORDER_POS_DIR / str(order_id), upload_filename, source)
    logger.info("Saved client order PO: %s (%d bytes)", rel, size)
    return rel, size


def get_client_order_po_path(relative_path: str) -> Path:
    return _resolve_under_root(relative_path)


def delete_client_order_po(relative_path: str) -> None:
    _delete_relative(relative_path, "client order PO")
