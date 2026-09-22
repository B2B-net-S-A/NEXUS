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
    #
    # INT-08: błąd LISTOWANIA propaguje się do syncu. Do 09.2026 zwracał pustą
    # listę, więc mail był zapisany, delta potwierdzona, a CV nie powstawało
    # nigdy (żaden wiersz załącznika = nic do ponowienia). Teraz przebieg
    # liczy błąd strony i kursor delty stoi — następny przebieg wraca po mail.
    page = await gc.get(f"/me/messages/{email_row.m365_message_id}/attachments")

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
            if download_attempts(row.parse_error):
                # Udane pobranie po wcześniejszej porażce — parser CV czeka
                # na wiersz bez błędu pobrania.
                row.parse_error = None
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Failed to persist attachment %s for email %s", m365_id, email_row.id
            )
            mark_download_failed(row, exc)

        results.append(row)

    await db.flush()
    return results


# INT-08 — licznik prób pobrania żyje w samym ``parse_error``
# (``download_failed[n]: …``), bez migracji. Stary zapis ``download_failed: …``
# to pierwsza próba. Pętla ``m365_cv_parse`` ponawia do ``MAX_DOWNLOAD_ATTEMPTS``.
DOWNLOAD_FAILED_PREFIX = "download_failed"
MAX_DOWNLOAD_ATTEMPTS = 5
_DOWNLOAD_ATTEMPTS_RE = re.compile(r"^download_failed(?:\[(\d+)\])?")


def download_attempts(parse_error: Optional[str]) -> int:
    """Liczba nieudanych prób pobrania zapisana w ``parse_error`` (0 = brak)."""
    if not parse_error:
        return 0
    match = _DOWNLOAD_ATTEMPTS_RE.match(parse_error)
    if match is None:
        return 0
    return int(match.group(1)) if match.group(1) else 1


def mark_download_failed(row: EmailAttachment, exc: BaseException) -> None:
    attempts = download_attempts(row.parse_error) + 1
    row.parse_error = f"{DOWNLOAD_FAILED_PREFIX}[{attempts}]: {exc!r}"[:500]


async def retry_attachment_download(
    gc: GraphClient, email_row: Email, row: EmailAttachment
) -> bool:
    """Ponów pobranie jednego załącznika (INT-08). ``True`` = plik zapisany.

    Sukces czyści ``parse_error`` — dopiero wtedy parser CV (który wymaga
    ``storage_path``) bierze załącznik. Porażka podbija licznik prób.
    """
    try:
        content = await gc.download(
            f"/me/messages/{email_row.m365_message_id}/attachments/"
            f"{row.m365_attachment_id}/$value"
        )
        rel_path = await asyncio.to_thread(
            _persist_bytes, email_row, row.filename, content
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "m365 attachment retry failed: attachment=%s (%s)",
            row.id,
            type(exc).__name__,
        )
        mark_download_failed(row, exc)
        return False
    row.storage_path = rel_path
    row.sha256 = (await asyncio.to_thread(hashlib.sha256, content)).hexdigest()
    row.parse_error = None
    return True


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
    db: AsyncSession,
    attachment: EmailAttachment,
    email_row: Email,
    *,
    preparsed: Optional[tuple[str, dict]] = None,
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
    # A delta page contains existing messages as well as new ones.  Re-running
    # the paid parser for an attachment already applied to the same candidate
    # made every M365 pass spend minutes on unchanged CVs.  A rematch remains
    # eligible because its candidate id differs.
    if attachment.parsed_candidate_id == email_row.candidate_id:
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

    if preparsed is not None:
        # Odczyt zrobiony już przy zakładaniu kandydata z maila — drugie płatne
        # wywołanie modelu na tym samym pliku niczego by nie dodało.
        text, parsed = preparsed
    else:
        parsed_pair = await _extract_and_parse(db, attachment, abs_path)
        if parsed_pair is None:
            return
        text, parsed = parsed_pair

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
        # A deleted, reclassified or rematched source can retain is_primary.
        # Restore it as non-primary until the identity gate has accepted it;
        # that gate flushes and must not collide with the current primary CV.
        document.is_primary = False
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

    from app.services.cv_enrichment import CvWritePolicy
    from app.services.cv_ingest_service import finish_cv_ingest

    candidate.raw_cv_text = text
    candidate.cv_filename = attachment.filename
    # Wspólna ścieżka po odczycie CV: pola, kategoria, wektor, cache i
    # auto-dopasowanie. Do 17.09.2026 ta gałąź zapisywała same pola — CV z maila
    # nie trafiało do wektora, więc wyszukiwanie semantyczne go nie widziało.
    await finish_cv_ingest(
        db,
        candidate=candidate,
        parsed=parsed,
        source_document_id=document.id,
        source_hash=content_hash,
        policy=CvWritePolicy.FILL_EMPTY,
        trigger="email",
        language_source_ref=content_hash,
    )

    attachment.parsed_candidate_id = candidate.id
    attachment.parse_error = None


async def _extract_and_parse(
    db: AsyncSession, attachment: EmailAttachment, abs_path: Path
) -> Optional[tuple[str, dict]]:
    """Tekst i odczyt CV z załącznika albo None (powód w `parse_error`)."""
    from app.services.cv_parser import parse_cv
    from app.services.cv_text_extractor import extract_text

    try:
        text = await asyncio.to_thread(extract_text, str(abs_path), attachment.filename)
        if not text.strip():
            attachment.parse_error = "text_extraction_empty"
            return None
        # `db=` podpina wywołanie pod licznik kosztów AI (bez limitów).
        parsed = await parse_cv(text, prefer_llm=True, db=db)
    except Exception as exc:  # noqa: BLE001
        logger.exception("CV parse failed for attachment %s", attachment.id)
        attachment.parse_error = f"parse_failed: {exc!r}"[:500]
        return None
    return text, parsed


_STRONG_IDENTITY_REASONS = frozenset(
    {"email_exact", "phone_exact", "linkedin_slug_match"}
)


async def try_create_candidate_from_cv(
    db: AsyncSession, attachment: EmailAttachment, email_row: Email
) -> Optional[int]:
    """CV z maila od nadawcy spoza bazy: podepnij do istniejącego albo załóż kandydata.

    Decyzja Artura z 17.09.2026: CV przysłane mailem nie może zginąć tylko dlatego,
    że nadawca nie jest jeszcze kandydatem. Tożsamość bierzemy z TREŚCI CV, nie
    z adresu nadawcy — rekruterzy przesyłają CV dalej ze swoich skrzynek.

    - e-mail / telefon / LinkedIn z CV pasuje do kandydata → mail podpięty
      (`cv_identity`) i odczyt jak dla znanego kandydata;
    - pasuje wyłącznie imię i nazwisko → nic nie zakładamy
      (`possible_duplicate_name`): dwóch Janów Kowalskich to nie ta sama osoba;
    - brak dopasowania, a CV ma imię, nazwisko i dane kontaktowe → nowy kandydat
      (`source="email"`) i ta sama wspólna ścieżka co upload;
    - CV bez imienia, nazwiska albo kontaktu → `identity_insufficient`.

    Zwraca id kandydata albo None. Nie rzuca.
    """
    from datetime import datetime, timezone

    if not (
        settings.M365_AUTO_PARSE_CV and settings.M365_AUTO_CREATE_CANDIDATE_FROM_CV
    ):
        return None
    if email_row.candidate_id is not None or email_row.is_private_filtered:
        return None
    if not attachment.is_cv_candidate or not attachment.storage_path:
        return None

    # Świadomie BEZ `cv_parse_attempted_at`: ten znacznik wyłącza załącznik
    # z kolejki znanych kandydatów. Mail, który tu nikogo nie założył (np. tylko
    # zbieżne imię i nazwisko), rekruter może podpiąć ręcznie — wtedy CV musi się
    # sparsować. Próbę tej ścieżki znaczy `parse_error`.
    abs_path = STORAGE_ROOT / attachment.storage_path
    if not abs_path.is_file():
        attachment.parse_error = "file_missing_on_disk"
        return None
    parsed_pair = await _extract_and_parse(db, attachment, abs_path)
    if parsed_pair is None:
        return None
    text, parsed = parsed_pair

    first_name = str(parsed.get("first_name") or "").strip()
    last_name = str(parsed.get("last_name") or "").strip()
    email = str(parsed.get("email") or "").strip().lower() or None
    phone = str(parsed.get("phone") or "").strip() or None
    linkedin = str(parsed.get("linkedin_url") or "").strip() or None
    if email and _is_internal_email(email):
        # CV z kontaktem naszego pracownika (CV wygenerowane przez NEXUS, które
        # klient odesłał, albo szablon agencji z danymi rekrutera) nie opisuje
        # kontaktu kandydata — nie wolno po nim łączyć ani zakładać.
        email = None
    if not (first_name and last_name and (email or phone or linkedin)):
        attachment.parse_error = "identity_insufficient"
        return None

    from app.services.dedup_service import find_candidate_duplicates

    duplicates = await find_candidate_duplicates(
        db,
        email=email,
        phone=phone,
        linkedin=linkedin,
        name=first_name,
        lastname=last_name,
    )
    strong = [
        d
        for d in duplicates
        if _STRONG_IDENTITY_REASONS & set(d.get("match_reasons") or [])
    ]
    now = datetime.now(timezone.utc)
    if len({int(d["candidate_id"]) for d in strong}) > 1:
        # E-mail z CV wskazuje jedną osobę, telefon drugą: podpięcie do którejś
        # wpisałoby jej cudzy kontakt (i łamało unikalność e-maila w bazie).
        attachment.parse_error = "conflicting_identity"
        return None
    if strong:
        candidate_id = int(strong[0]["candidate_id"])
        _link_email(email_row, candidate_id, float(strong[0]["match_score"]), now)
        await try_parse_cv(db, attachment, email_row, preparsed=(text, parsed))
        return candidate_id
    if duplicates:
        attachment.parse_error = "possible_duplicate_name"
        return None

    from app.models.activity import Activity

    candidate = Candidate(
        name=first_name[:100],
        lastname=last_name[:100],
        email=email[:255] if email else None,
        phone=phone[:30] if phone else None,
        source="email",
        created_by=email_row.user_id,
    )
    db.add(candidate)
    await db.flush()
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="created_from_email",
            user_id=email_row.user_id,
            details={
                "email_id": email_row.id,
                "attachment_id": attachment.id,
                "filename": attachment.filename,
                "source": parsed.get("_source"),
            },
        )
    )
    _link_email(email_row, candidate.id, 1.0, now)
    await try_parse_cv(db, attachment, email_row, preparsed=(text, parsed))
    if attachment.parsed_candidate_id != candidate.id or attachment.parse_error:
        # Profil nie przeszedł wspólnej ścieżki (np. kolizja dokumentu), więc
        # nikt go nie zaindeksował — a kandydat bez wektora nie istnieje
        # w rekomendacjach ani w auto-dopasowaniu.
        from app.services.index_outbox_service import schedule_or_embed_candidate

        await schedule_or_embed_candidate(candidate.id, db)
    return candidate.id


def _is_internal_email(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].strip().lower()
    raw = getattr(settings, "SSO_ALLOWED_DOMAINS", "") or ""
    domains = (
        {d.strip().lower() for d in raw.split(",") if d.strip()}
        if isinstance(raw, str)
        else {str(d).strip().lower() for d in raw}
    )
    return bool(domain) and domain in domains


def _link_email(email_row: Email, candidate_id: int, confidence: float, now) -> None:
    from app.models.m365 import EmailMatchMethod

    email_row.candidate_id = candidate_id
    email_row.match_method = EmailMatchMethod.cv_identity
    email_row.match_confidence = confidence
    email_row.matched_at = now
