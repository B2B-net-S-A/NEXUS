"""Resztki danych osoby, które przeżywały twarde usunięcie kandydata (art. 17).

Runda 6 audytu — każda pozycja to miejsce, do którego kaskada FK nie sięga:

* RODO-01: nagrobek ``(external_source, HMAC(external_id))`` — bez niego
  nocny sync Traffita zakładał usuniętą osobę od nowa;
* wygenerowane CV i pliki CV ZOSTAJĄ — nigdy ich nie kasujemy (decyzja
  Artura 26.09.2026: „nie usuwać nigdy żadnych CV”);
* RODO-03: powiadomienia z imieniem i nazwiskiem (``notifications`` nie ma FK
  na kandydata);
* RODO-06: ``integration_run_events.candidate_name`` / ``traffit_id``;
* RODO-07: załączniki CV z maili tej osoby — bez stempla próby odczytu
  worker M365 zakładał ją od nowa z niesparsowanego CV.

Wołane z ``DELETE /api/candidates/{id}`` pod blokadą wiersza kandydata, przed
``db.delete``; zwraca liczby do dowodu wykonania (lista kluczy plików jest
zawsze pusta — CV zostają). Niczego nie commituje.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, or_, select, update
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
    counts["notifications_deleted"] = await _erase_notifications(db, candidate_id)
    counts["integration_events_scrubbed"] = await _scrub_integration_events(
        db, candidate_id
    )
    counts["email_cv_attachments_closed"] = await _stamp_email_cv_attachments(
        db, candidate_id
    )
    # CV zostają zawsze (decyzja Artura 26.09.2026) — żadnych kluczy plików
    # do kasowania.
    return counts, []
