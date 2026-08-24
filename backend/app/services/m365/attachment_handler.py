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

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
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
    r"(cv|resume|życiorys|zyciorys|lebenslauf)" r"(?![a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ])",
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

    # No $select here — Graph's `/messages/{id}/attachments` returns a
    # polymorphic collection (fileAttachment / itemAttachment / referenceAttachment)
    # and $select rejects any field that doesn't exist on the BASE
    # `microsoft.graph.attachment` type. Two production fires came from this:
    #   • NEXUS-BE-2 (2026-05): `@odata.type` is not selectable on the base type.
    #   • NEXUS-BE-C (2026-05): `contentBytes` exists only on fileAttachment.
    # Without $select Graph returns every standard field per subtype, including
    # `contentBytes` for fileAttachment — exactly what we need below. The extra
    # payload is small (attachments are typically <10 per email and metadata is
    # tiny next to the bytes themselves).
    try:
        page = await gc.get(f"/me/messages/{email_row.m365_message_id}/attachments")
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

            # Sync disk write + hashing — offload off the event loop.
            rel_path = await asyncio.to_thread(
                _persist_bytes, email_row, filename, content
            )
            row.storage_path = rel_path
            row.sha256 = (await asyncio.to_thread(hashlib.sha256, content)).hexdigest()
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

    content = await asyncio.to_thread(abs_path.read_bytes)
    content_hash = attachment.sha256 or hashlib.sha256(content).hexdigest()
    external_id = (attachment.m365_attachment_id or "")[:100] or None

    # Szukamy po TYM SAMYM kluczu, na którym stoi UNIQUE
    # (`ux_candidate_documents_external_source_id` = external_source + external_id,
    # migracja 0076). Poprzednia wersja szukała po `(candidate_id,
    # content_sha256, source_deleted_at IS NULL)` — trzy warunki, z których
    # ŻADEN nie występuje w indeksie. Skutkiem były 3 800 zdarzeń w Sentry
    # (NEXUS-BE-2Y/2X) na dwóch drogach:
    #
    #   * dokument MIĘKKO USUNIĘTY (`source_deleted_at` ustawione) wypadał
    #     z lookupu, ale nadal zajmował klucz w indeksie — więc każda kolejna
    #     synchronizacja tego załącznika próbowała INSERT-a i trwale padała;
    #   * ten sam załącznik dopasowany do INNEGO kandydata (rematch) też omijał
    #     lookup, bo ten filtruje po `candidate_id`, a indeks jest globalny.
    #
    # Bez savepointu IntegrityError zatruwa CAŁĄ sesję, więc padał nie ten jeden
    # załącznik, tylko cały dalszy przebieg synchronizacji.
    document = None
    if external_id is not None:
        document = await db.scalar(
            select(CandidateDocument).where(
                CandidateDocument.external_source == "m365",
                CandidateDocument.external_id == external_id,
            )
        )

    if document is None:
        # Dokumenty bez `external_id` (starsze wpisy, inne źródła) nie są objęte
        # indeksem — dla nich zostaje dotychczasowe dopasowanie po treści.
        document = await db.scalar(
            select(CandidateDocument).where(
                CandidateDocument.candidate_id == candidate.id,
                CandidateDocument.content_sha256 == content_hash,
                CandidateDocument.source_deleted_at.is_(None),
            )
        )

    if document is None:
        document = CandidateDocument(
            candidate_id=candidate.id,
            filename=attachment.filename,
            file_content=content,
            content_type=attachment.content_type,
            size_bytes=len(content),
            document_kind=CandidateDocumentKind.cv,
            is_primary=False,
            uploaded_at=email_row.received_at or attachment.cv_parse_attempted_at,
            external_source="m365",
            external_id=external_id,
            content_sha256=content_hash,
        )
        try:
            # SAVEPOINT — ten sam wzorzec, co przy `emails.m365_message_id`
            # w `sync.py`. Nawet z poprawionym lookupem zostaje wyścig: dwa
            # równoległe przebiegi widzą brak wiersza i oba wstawiają.
            # Savepoint ogranicza szkodę do jednego załącznika zamiast ubijać
            # sesję i cały przebieg.
            async with db.begin_nested():
                db.add(document)
                await db.flush()
        except IntegrityError:
            logger.info(
                "m365 attachment %s: dokument wstawiony równolegle — przechodzę na update",
                attachment.id,
            )
            db.expunge(document)
            document = await db.scalar(
                select(CandidateDocument).where(
                    CandidateDocument.external_source == "m365",
                    CandidateDocument.external_id == external_id,
                )
            )
            if document is None:
                # Kolizja na innym kluczu niż nasz — nie zgadujemy, co to było.
                attachment.parse_error = "document_insert_conflict"
                return
            document.document_kind = CandidateDocumentKind.cv
    else:
        document.document_kind = CandidateDocumentKind.cv
        # Wskrzeszenie miękko usuniętego wpisu: skoro załącznik wrócił
        # w synchronizacji, dokument znów jest aktualny.
        document.source_deleted_at = None
        document.candidate_id = candidate.id
        document.content_sha256 = content_hash

    from app.services.candidate_identity_quarantine import record_detected_identity

    review = await record_detected_identity(
        db,
        candidate=candidate,
        source_kind="document",
        source_id=document.id,
        observed_first_name=parsed.get("first_name"),
        observed_last_name=parsed.get("last_name"),
        provenance="cv_parser:m365",
    )
    if review.is_quarantined:
        document.is_primary = False
        attachment.parsed_candidate_id = candidate.id
        attachment.parse_error = "identity_mismatch_quarantined"
        return

    # Only a source that passed the identity gate may replace the active CV.
    await db.execute(
        update(CandidateDocument)
        .where(
            CandidateDocument.candidate_id == candidate.id,
            CandidateDocument.id != document.id,
            CandidateDocument.document_kind == CandidateDocumentKind.cv,
            CandidateDocument.source_deleted_at.is_(None),
        )
        .values(is_primary=False)
    )
    document.is_primary = True

    from app.services.cv_enrichment import _apply_cv_enrichment

    candidate.raw_cv_text = text
    candidate.cv_filename = attachment.filename
    _apply_cv_enrichment(
        candidate,
        parsed,
        source_document_id=document.id,
        source_hash=content_hash,
    )
    if parsed.get("languages"):
        from app.services.candidate_language_writer import (
            sync_candidate_languages_from_source,
        )

        await sync_candidate_languages_from_source(
            db,
            candidate_id=candidate.id,
            raw_languages=parsed["languages"],
            provenance="cv",
            source_ref=content_hash,
        )

    attachment.parsed_candidate_id = candidate.id
    attachment.parse_error = None
