"""Retencja e-teczki po odejściu: lista „do usunięcia po terminie” dla Kadr.

Nic nie kasuje się samo. Dokument osoby, która odeszła (kartoteka
``exited``), trafia na listę, gdy minął okres przechowywania jego rodzaju
(``documents_rules.load_retention``), liczony od końca roku kalendarzowego
ostatniego dnia pracy (bez daty — dzień odejścia z kartoteki). Usuwa
człowiek: Kadry zaznaczają pozycje i potwierdzają; serwer sprawdza każdą
jeszcze raz (osoba mogła wrócić, okres mógł się wydłużyć). Usunięcie kasuje
plik, wiersz zostaje jako ślad.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date, business_today
from app.models.hr_document import HrDocument
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr import audit
from app.services.hr.documents import mark_deleted
from app.services.hr.documents_rules import delete_from, load_retention
from app.services.hr_foundation_schema import EmploymentStatus

MAX_BATCH = 500


@dataclass(frozen=True)
class DueDocument:
    document: HrDocument
    person_name: str
    last_day: date
    delete_from: date


def last_day_of(profile: EmployeeProfile) -> Optional[date]:
    if profile.last_working_day is not None:
        return profile.last_working_day
    if profile.exited_at is not None:
        return business_date(profile.exited_at)
    return None


async def _candidates(
    db: AsyncSession, ids: Optional[Iterable[int]] = None
) -> list[tuple[HrDocument, EmployeeProfile, str]]:
    query = (
        select(HrDocument, EmployeeProfile, User.name)
        .join(EmployeeProfile, EmployeeProfile.user_id == HrDocument.user_id)
        .join(User, User.id == HrDocument.user_id)
        .where(
            HrDocument.deleted_at.is_(None),
            EmployeeProfile.employment_status == EmploymentStatus.exited,
        )
        .order_by(User.name, HrDocument.id)
    )
    if ids is not None:
        query = query.where(HrDocument.id.in_(list(ids)))
    return [
        (doc, profile, name) for doc, profile, name in (await db.execute(query)).all()
    ]


async def due(db: AsyncSession, *, today: Optional[date] = None) -> list[DueDocument]:
    """Dokumenty po terminie przechowywania (do decyzji Kadr)."""

    today = today or business_today()
    years = await load_retention(db)
    out: list[DueDocument] = []
    for document, profile, name in await _candidates(db):
        last_day = last_day_of(profile)
        if last_day is None:
            continue
        start = delete_from(last_day, years[document.kind])
        if today >= start:
            out.append(DueDocument(document, name, last_day, start))
    return out


def due_payload(item: DueDocument) -> dict[str, Any]:
    document = item.document
    return {
        "id": document.id,
        "user_id": document.user_id,
        "person_name": item.person_name,
        "kind": document.kind,
        "title": document.title,
        "source": document.source,
        "created_at": document.created_at,
        "last_day": item.last_day,
        "delete_from": item.delete_from,
    }


async def delete_due(
    db: AsyncSession,
    document_ids: Iterable[int],
    *,
    actor_id: int,
    today: Optional[date] = None,
) -> tuple[list[int], list[dict[str, Any]], list[str]]:
    """Usuwa wskazane dokumenty, które dalej są po terminie.

    Zwraca (usunięte, pominięte z powodem, pliki do skasowania po commicie).
    """

    wanted = list(dict.fromkeys(int(value) for value in document_ids))
    today = today or business_today()
    due_now = {item.document.id: item for item in await due(db, today=today)}
    deleted: list[int] = []
    skipped: list[dict[str, Any]] = []
    orphans: list[str] = []
    for document_id in wanted:
        item = due_now.get(document_id)
        if item is None:
            skipped.append({"id": document_id, "reason": "not_due"})
            continue
        document = item.document
        orphan = await mark_deleted(
            db, document, reason="retention", note=None, actor_id=actor_id
        )
        if orphan:
            orphans.append(orphan)
        audit.record(
            db,
            actor_user_id=actor_id,
            subject_user_id=document.user_id,
            entity_type="hr_document",
            entity_id=document.id,
            action="document_retention_deleted",
            details={
                "kind": document.kind,
                "last_day": item.last_day.isoformat(),
                "delete_from": item.delete_from.isoformat(),
            },
        )
        deleted.append(document_id)
    return deleted, skipped, orphans


__all__ = [
    "MAX_BATCH",
    "DueDocument",
    "delete_due",
    "due",
    "due_payload",
    "last_day_of",
]
