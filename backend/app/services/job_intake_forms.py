"""Niedokończone formularze „Nowa rekrutacja” na koncie autora (0416).

Rekrutacja nie bywa już szkicem (decyzja Artura 04.10.2026): utworzenie =
przekazanie do searchu = publikacja. To, czego Delivery Lead nie skończył,
leży tutaj — widzi to wyłącznie autor, najwyżej ``MAX_FORMS_PER_USER``
formularzy, a formularz bez zmian przez ``RETENTION_DAYS`` dni znika
(``tasks/queue_retention.py``).

Treść formularza i maila klienta nie trafia do logów — to dane klienta
i często nazwiska.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.job_intake_form import JobIntakeForm

MAX_FORMS_PER_USER = 20
MAX_FORM_BYTES = 200 * 1024
MAX_REQUEST_TEXT_CHARS = 100_000
RETENTION_DAYS = 30
# Pulpit przypomina o formularzu dopiero, gdy leży dłużej niż tyle dni —
# świeży formularz to praca w toku, nie zaległość.
STALE_AFTER_DAYS = 2

FORMS_LIMIT_MESSAGE = (
    f"Masz już {MAX_FORMS_PER_USER} niedokończonych formularzy. Dokończ albo "
    "usuń któryś z nich, zanim zapiszesz kolejny."
)

# Retencja (`queue_retention`): formularz bez zmian przez RETENTION_DAYS dni.
PRUNE_STATEMENT = text(
    """
    DELETE FROM job_intake_forms
     WHERE id IN (
        SELECT id FROM job_intake_forms
         WHERE updated_at < :cutoff
         ORDER BY updated_at
         LIMIT :batch
     )
    """
)


def form_size_bytes(form: Any) -> int:
    """Rozmiar formularza tak, jak zapisze go Postgres (JSON w UTF-8)."""
    return len(json.dumps(form, ensure_ascii=False, separators=(",", ":")).encode())


def expires_at(updated_at: datetime) -> datetime:
    return updated_at + timedelta(days=RETENTION_DAYS)


@dataclass(frozen=True)
class FormSummary:
    id: int
    label: str
    client_id: Optional[int]
    client_name: Optional[str]
    source: str
    updated_at: datetime


async def list_forms(
    db: AsyncSession, user_id: int, *, older_than: Optional[datetime] = None
) -> list[FormSummary]:
    """Formularze tej osoby, od ostatnio zmienianego."""
    stmt = (
        select(
            JobIntakeForm.id,
            JobIntakeForm.label,
            JobIntakeForm.client_id,
            Client.name.label("client_name"),
            JobIntakeForm.source,
            JobIntakeForm.updated_at,
        )
        .outerjoin(Client, Client.id == JobIntakeForm.client_id)
        .where(JobIntakeForm.user_id == user_id)
        .order_by(JobIntakeForm.updated_at.desc(), JobIntakeForm.id.desc())
        .limit(MAX_FORMS_PER_USER * 2)
    )
    if older_than is not None:
        stmt = stmt.where(JobIntakeForm.updated_at < older_than)
    return [FormSummary(**row._mapping) for row in (await db.execute(stmt)).all()]


async def count_forms(db: AsyncSession, user_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count(JobIntakeForm.id)).where(JobIntakeForm.user_id == user_id)
        )
        or 0
    )


async def lock_user_forms(db: AsyncSession, user_id: int) -> None:
    """Blokada doradcza na formularze osoby — limit liczony bez wyścigu."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('job_intake_forms'), :uid)"),
        {"uid": user_id},
    )


async def delete_own_form(db: AsyncSession, *, user_id: int, form_id: int) -> bool:
    """Usuń formularz tej osoby (bez commita). ``False`` = nie ma takiego.

    Woła też ``POST /api/jobs`` z ``intake_form_id`` — formularz, z którego
    powstała rekrutacja, znika w tej samej transakcji.
    """
    result = await db.execute(
        delete(JobIntakeForm).where(
            JobIntakeForm.id == form_id, JobIntakeForm.user_id == user_id
        )
    )
    return bool(result.rowcount)


__all__ = [
    "FORMS_LIMIT_MESSAGE",
    "MAX_FORMS_PER_USER",
    "MAX_FORM_BYTES",
    "MAX_REQUEST_TEXT_CHARS",
    "PRUNE_STATEMENT",
    "RETENTION_DAYS",
    "STALE_AFTER_DAYS",
    "FormSummary",
    "count_forms",
    "delete_own_form",
    "expires_at",
    "form_size_bytes",
    "list_forms",
    "lock_user_forms",
]
