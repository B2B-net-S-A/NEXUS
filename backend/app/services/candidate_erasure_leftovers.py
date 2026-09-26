"""Resztki danych osoby, które przeżywały twarde usunięcie kandydata (art. 17).

Runda 6 audytu — każda pozycja to miejsce, do którego kaskada FK nie sięga:

* RODO-01: nagrobek ``(external_source, HMAC(external_id))`` — bez niego
  nocny sync Traffita zakładał usuniętą osobę od nowa;
* RODO-02: wygenerowane CV (``cv_generated_documents.candidate_id`` to
  ``SET NULL``, więc pełne CV zostawało czytelne i do pobrania) razem ze
  zrzutem zgody RODO z magazynu;
* RODO-03: powiadomienia z imieniem i nazwiskiem (``notifications`` nie ma FK
  na kandydata);
* RODO-06: ``integration_run_events.candidate_name`` / ``traffit_id``;
* RODO-07: załączniki CV z maili tej osoby — bez stempla próby odczytu
  worker M365 zakładał ją od nowa z niesparsowanego CV.

Wołane z ``DELETE /api/candidates/{id}`` pod blokadą wiersza kandydata, przed
``db.delete``; zwraca liczby do dowodu wykonania i klucze plików do rejestru
kasowań. Niczego nie commituje.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

# Wzorce linków powiadomień wskazujących osobę (składnia ARE Postgresa):
# (wzorzec dla ``{id}``, zamiennik dla ``{s}`` przy scalaniu). ``(?![0-9])``
# odcina „/candidates/12” od „/candidates/123”; ``\1`` w Postgresie to jedna
# cyfra, więc „\15” znaczy „grupa 1, potem 5”.
_LINK_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"/candidates/{id}(?![0-9])", "/candidates/{s}"),
    (r"([?&]candidate=){id}(?![0-9])", r"\1{s}"),
    (r"([?&]cycle=){id}-", r"\1{s}-"),
)


def candidate_link_patterns(candidate_id: int) -> list[str]:
    """Wzorce linków powiadomień prowadzących do tej osoby."""
    return [pattern.format(id=int(candidate_id)) for pattern, _ in _LINK_PATTERNS]


def candidate_link_rewrites(
    duplicate_id: int, survivor_id: int
) -> list[tuple[str, str]]:
    """(wzorzec, zamiennik) do przepięcia linków przy scalaniu duplikatów."""
    return [
        (pattern.format(id=int(duplicate_id)), replacement.format(s=int(survivor_id)))
        for pattern, replacement in _LINK_PATTERNS
    ]


def notification_link_clause(candidate_id: int):
    """Powiadomienie, którego link wskazuje tę osobę (dowolny typ encji)."""
    from app.models.notification import Notification

    return or_(
        *(
            Notification.link.op("~")(pattern)
            for pattern in candidate_link_patterns(candidate_id)
        )
    )


def is_detached_generated_document(row: Any) -> bool:
    """CV powstało dla kandydata, którego już nie ma (runda 6, RODO-02).

    Tryb „new” zawsze startuje z istniejącego kandydata, a ``stage_id`` upload
    przyjmuje wyłącznie razem z kandydatem — pusty FK przy którymś z nich
    znaczy, że osobę usunięto (wiersz sprzed poprawki albo przyszła ścieżka
    odpinająca dokument). Upload „Generuj bez dodawania” (bez kandydata i bez
    etapu) jest legalny i zostaje.
    """
    # Obiekt bez pola kandydata (np. lekka projekcja wiersza) nie jest „odpięty”
    # — odpięcie stwierdza tylko pusty FK prawdziwego wiersza.
    if not hasattr(row, "candidate_id") or row.candidate_id is not None:
        return False
    return (
        getattr(row, "mode", None) == "new"
        or getattr(row, "stage_id", None) is not None
    )


def detached_generated_document_clause():
    """Lustro ``is_detached_generated_document`` w SQL (lista CV)."""
    from app.models.cv_generated_document import CvGeneratedDocument

    return CvGeneratedDocument.candidate_id.is_(None) & or_(
        CvGeneratedDocument.mode == "new",
        CvGeneratedDocument.stage_id.is_not(None),
    )


async def _write_tombstone(db: AsyncSession, candidate: Any) -> int:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.purged_candidate import PurgedCandidate
    from app.services.candidate_audit import candidate_source_tombstone

    source = (candidate.external_source or "").strip()
    external_id = (candidate.external_id or "").strip()
    # Wiersz bez identyfikatora źródłowego (ręczny, z CV) — żaden sync go nie
    # odtworzy, więc nagrobek nie ma czego chronić.
    if not source or not external_id or source == "manual":
        return 0
    result = await db.execute(
        pg_insert(PurgedCandidate)
        .values(
            external_source=source,
            external_id_hash=candidate_source_tombstone(source, external_id),
        )
        .on_conflict_do_nothing(constraint="uq_purged_candidates_source_hash")
    )
    return result.rowcount or 0


async def _erase_generated_documents(
    db: AsyncSession, candidate_id: int
) -> tuple[int, list[str]]:
    from app.models.cv_generated_document import CvGeneratedDocument

    rows = (
        await db.execute(
            select(CvGeneratedDocument.id, CvGeneratedDocument.render_payload).where(
                CvGeneratedDocument.candidate_id == candidate_id
            )
        )
    ).all()
    if not rows:
        return 0, []
    ids = [row.id for row in rows]
    consent_keys: set[str] = set()
    for row in rows:
        payload = row.render_payload if isinstance(row.render_payload, dict) else {}
        consent = payload.get("consent_screenshot")
        if isinstance(consent, dict):
            key = str(consent.get("storage_key") or "").strip()
            if key:
                consent_keys.add(key)
    keys: list[str] = []
    for key in sorted(consent_keys):
        # Zrzut zgody bywa wspólny dla wersji PL i EN tego samego CV. Inny
        # dokument (np. upload bez kandydata) z tym samym kluczem zatrzymuje
        # plik — kasujemy wyłącznie obiekt, którego nikt już nie wskazuje.
        still_used = await db.scalar(
            select(func.count())
            .select_from(CvGeneratedDocument)
            .where(
                CvGeneratedDocument.id.not_in(ids),
                CvGeneratedDocument.render_payload["consent_screenshot"][
                    "storage_key"
                ].as_string()
                == key,
            )
        )
        if not still_used:
            keys.append(key)
    # Wersje zatwierdzone (`cv_document_versions.generated_owner_id`), szkice
    # edytora, linki publiczne i kontrole zatwierdzenia kaskadują z dokumentu.
    await db.execute(delete(CvGeneratedDocument).where(CvGeneratedDocument.id.in_(ids)))
    return len(ids), keys


async def _erase_notifications(db: AsyncSession, candidate_id: int) -> int:
    from app.models.notification import Notification
    from app.models.recruitment_pipeline import CandidateStage

    result = await db.execute(
        delete(Notification).where(
            or_(
                (Notification.related_entity_type == "candidate")
                & (Notification.related_entity_id == candidate_id),
                (Notification.related_entity_type == "candidate_stage")
                & Notification.related_entity_id.in_(
                    select(CandidateStage.id).where(
                        CandidateStage.candidate_id == candidate_id
                    )
                ),
                notification_link_clause(candidate_id),
            )
        )
    )
    return result.rowcount or 0


async def _scrub_integration_events(db: AsyncSession, candidate_id: int) -> int:
    from app.models.integration_run import IntegrationRunEvent

    # `external_id` (id aplikacji w portalu) i akcja zostają — to liczniki
    # biegu, nie dane osoby; nazwisko i id osoby w Traffit znikają.
    result = await db.execute(
        update(IntegrationRunEvent)
        .where(IntegrationRunEvent.candidate_id == candidate_id)
        .values(candidate_name=None, traffit_id=None)
    )
    return result.rowcount or 0


async def _stamp_email_cv_attachments(db: AsyncSession, candidate_id: int) -> int:
    from app.models.m365 import Email, EmailAttachment

    # Tylko stempel próby: `Email.candidate_id` to SET NULL, a worker
    # `m365_cv_parse._create_from_unknown_sender_once` zakłada kandydata
    # z załącznika maila bez osoby i bez stempla.
    result = await db.execute(
        update(EmailAttachment)
        .where(
            EmailAttachment.email_id.in_(
                select(Email.id).where(Email.candidate_id == candidate_id)
            ),
            EmailAttachment.cv_parse_attempted_at.is_(None),
        )
        .values(cv_parse_attempted_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


async def erase_candidate_leftovers(
    db: AsyncSession, candidate: Any
) -> tuple[dict[str, int], list[str]]:
    """Sprząta resztki (runda 6 audytu); zwraca (liczby, klucze plików)."""
    candidate_id = int(candidate.id)
    counts: dict[str, int] = {}
    counts["source_tombstones"] = await _write_tombstone(db, candidate)
    documents, keys = await _erase_generated_documents(db, candidate_id)
    counts["generated_cvs_deleted"] = documents
    counts["notifications_deleted"] = await _erase_notifications(db, candidate_id)
    counts["integration_events_scrubbed"] = await _scrub_integration_events(
        db, candidate_id
    )
    counts["email_cv_attachments_closed"] = await _stamp_email_cv_attachments(
        db, candidate_id
    )
    return counts, keys
