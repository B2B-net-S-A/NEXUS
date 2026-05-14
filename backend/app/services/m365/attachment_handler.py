"""Download Graph attachments and optionally auto-parse CVs.

Responsibilities:
- Download a message's attachments (skipping those above the configured size cap).
- Persist the bytes under `UPLOAD_DIR/microsoft365/{user_id}/{email_id}/`.
- Detect PDF/DOCX named like a CV and pipe through the existing cv_parser.
- Dedupe by SHA256 so repeated attachments (reply chains) don't rebuild state.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.m365 import Email, EmailAttachment
from app.services.m365.graph_client import GraphClient
from app.services.storage_service import _sanitize_filename

logger = logging.getLogger(__name__)

# Root directory for M365 attachment storage (docker volume `uploads_data`).
STORAGE_ROOT = Path(
    settings.UPLOAD_DIR if hasattr(settings, "UPLOAD_DIR") else "/tmp/nexus/uploads"
)
M365_ROOT = STORAGE_ROOT / "microsoft365"

# Match "cv"/"resume"/... as the trailing-most token before the extension.
# `\b` doesn't help here — PL/EN underscores defeat it (`Resume_2025.pdf`)
# and so does CamelCase (`MyCV.pdf` — `y→C` is letter↔letter, no boundary).
# We instead require a non-letter (or end of string) AFTER the keyword. The
# left side is intentionally permissive — `MyCV.pdf` and `becv.pdf` both
# match; the MIME guard in `is_cv_candidate_attachment` rules out junk.
_CV_FILENAME_RE = re.compile(
    r"(cv|resume|życiorys|zyciorys|lebenslauf)"
    r"(?![a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ])",
    re.I,
)
_CV_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    }
)


def is_cv_candidate_attachment(filename: str, content_type: str) -> bool:
    """Heuristic — filename hints at CV AND MIME type is a document format."""
    if content_type not in _CV_CONTENT_TYPES:
        return False
    return bool(_CV_FILENAME_RE.search(filename or ""))


async def download_for_email(
    db: AsyncSession,
    gc: GraphClient,
    email_row: Email,
) -> list[EmailAttachment]:
    """Fetch every attachment for the given email, persist rows + bytes.

    Returns the list of created/updated EmailAttachment rows. On any per-
    attachment failure we record `parse_error` and continue.
    """
    if not email_row.has_attachments:
        return []

    # Graph gives us metadata + (for fileAttachment) contentBytes inline.
    try:
        page = await gc.get(
            f"/me/messages/{email_row.m365_message_id}/attachments",
            params={
                # NOTE: `@odata.type` was previously in $select, but Graph returns
                # 400 BadRequest ("Term '@odata.type' is not valid in a $select or
                # $expand expression"). The discriminator comes back automatically
                # in the response payload, so reading it from the response (line 94
                # below) is enough — no need to ask for it.
                "$select": "id,name,contentType,size,isInline,contentBytes"
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to list attachments for email %s", email_row.m365_message_id
        )
        return []

    results: list[EmailAttachment] = []
    max_bytes = settings.M365_MAX_ATTACHMENT_MB * 1024 * 1024

    for att in page.get("value", []):
        m365_id = att.get("id")
        if not m365_id:
            continue

        filename = _sanitize_filename(att.get("name") or f"attachment-{m365_id[:8]}")
        content_type = att.get("contentType") or "application/octet-stream"
        size = int(att.get("size") or 0)
        is_inline = bool(att.get("isInline"))
        odata_type = att.get("@odata.type", "")

        # Upsert row by (email_id, m365_attachment_id).
        existing = await db.scalar(
            select(EmailAttachment).where(
                EmailAttachment.email_id == email_row.id,
                EmailAttachment.m365_attachment_id == m365_id,
            )
        )
        if existing is None:
            row = EmailAttachment(
                email_id=email_row.id,
                m365_attachment_id=m365_id,
                filename=filename,
                content_type=content_type,
                size_bytes=size,
                is_inline=is_inline,
                is_cv_candidate=is_cv_candidate_attachment(filename, content_type),
            )
            db.add(row)
            await db.flush()
        else:
            row = existing
            row.filename = filename
            row.content_type = content_type
            row.size_bytes = size
            row.is_inline = is_inline
            row.is_cv_candidate = is_cv_candidate_attachment(filename, content_type)

        # Skip if oversized.
        if size > max_bytes:
            row.parse_error = f"size_exceeded: {size} > {max_bytes}"
            results.append(row)
            continue

        # Skip re-download if we already have the file on disk.
        if row.storage_path and (STORAGE_ROOT / row.storage_path).is_file():
            results.append(row)
            continue

        try:
            content_b64 = att.get("contentBytes")
            if not content_b64 and "referenceAttachment" in odata_type:
                # Link to OneDrive/SharePoint — skip for Phase 1.
                row.parse_error = "reference_attachment_skipped"
                results.append(row)
                continue
            if not content_b64:
                # Large file — fetch via $value endpoint.
                content = await gc.download(
                    f"/me/messages/{email_row.m365_message_id}/attachments/{m365_id}/$value"
                )
            else:
                content = base64.b64decode(content_b64)

            rel_path = _persist_bytes(email_row, filename, content)
            row.storage_path = rel_path
            row.sha256 = hashlib.sha256(content).hexdigest()
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Failed to persist attachment %s for email %s", m365_id, email_row.id
            )
            row.parse_error = f"download_failed: {exc!r}"[:500]

        results.append(row)

    await db.flush()
    return results


def _persist_bytes(email_row: Email, filename: str, content: bytes) -> str:
    """Write bytes to UPLOAD_DIR/microsoft365/{user_id}/{email_id}/{uuid8}-{safe}.

    Returns path relative to STORAGE_ROOT (matches storage_service convention).
    """
    target_dir = M365_ROOT / str(email_row.user_id) / str(email_row.id)
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex[:8]}-{filename}"
    target_path = target_dir / stored_name
    with target_path.open("wb") as fh:
        fh.write(content)
    return str(target_path.relative_to(STORAGE_ROOT))


async def try_parse_cv(
    db: AsyncSession, attachment: EmailAttachment, email_row: Email
) -> None:
    """If this attachment looks like a CV and the email is linked to a candidate,
    run it through cv_parser and merge results into the candidate profile.

    Swallows all exceptions into `attachment.parse_error` — never raises.
    """
    if not settings.M365_AUTO_PARSE_CV:
        return
    if not attachment.is_cv_candidate or not attachment.storage_path:
        return
    if email_row.candidate_id is None:
        return

    from datetime import datetime, timezone

    attachment.cv_parse_attempted_at = datetime.now(timezone.utc)

    # Dedup: same SHA for same candidate → don't reparse (cheapest win).
    if attachment.sha256:
        existing = await db.scalar(
            select(EmailAttachment)
            .where(
                EmailAttachment.sha256 == attachment.sha256,
                EmailAttachment.parsed_candidate_id == email_row.candidate_id,
                EmailAttachment.id != attachment.id,
            )
            .limit(1)
        )
        if existing is not None:
            attachment.parsed_candidate_id = email_row.candidate_id
            return

    abs_path = STORAGE_ROOT / attachment.storage_path
    if not abs_path.is_file():
        attachment.parse_error = "file_missing_on_disk"
        return

    try:
        # Lazy import to keep cold-start light.
        from app.services.cv_parser import parse_cv
        from app.services.cv_text_extractor import extract_text

        text = await asyncio.to_thread(extract_text, str(abs_path), attachment.filename)
        if not text.strip():
            attachment.parse_error = "text_extraction_empty"
            return
        parsed = await parse_cv(text, prefer_llm=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("CV parse failed for attachment %s", attachment.id)
        attachment.parse_error = f"parse_failed: {exc!r}"[:500]
        return

    # Merge into candidate — but NEVER overwrite a more recent manual/upload parse.
    candidate: Optional[Candidate] = await db.get(Candidate, email_row.candidate_id)
    if candidate is None:
        attachment.parse_error = "candidate_missing"
        return
    if candidate.cv_parsed_at and email_row.received_at:
        if candidate.cv_parsed_at > email_row.received_at:
            # A newer CV already on file.
            attachment.parsed_candidate_id = candidate.id
            return

    candidate.raw_cv_text = text
    candidate.cv_filename = attachment.filename
    candidate.cv_parsed_at = attachment.cv_parse_attempted_at
    if parsed.get("skills"):
        candidate.skills = parsed["skills"]
    if parsed.get("years_it_experience") is not None:
        candidate.years_it_experience = parsed["years_it_experience"]
    if parsed.get("education"):
        candidate.education = parsed["education"]
    if parsed.get("languages"):
        candidate.languages = parsed["languages"]

    attachment.parsed_candidate_id = candidate.id
    attachment.parse_error = None
