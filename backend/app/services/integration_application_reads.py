"""Odczyty zgłoszeń z linku rekrutacji dla API v1 (``api/integrations_v1/applications``).

Zgłoszenie = wiersz ``application_submissions``: zapis tego, co osoba wysłała
formularzem (imię, kontakt, wiadomość, odpowiedzi, CV). Od 22.09.2026 powstaje
tylko wtedy, gdy e-mail był już w bazie, i od razu jest podpięte (``linked``);
``pending_review`` mają wyłącznie wiersze sprzed tej daty
(``rekrutacja-tworzenie/strona-kariery-dla-kandydatow.md``). Nowa osoba ze
zgłoszenia jest od razu kandydatem — widać ją w ``/candidates`` i na Tablicy,
nie tutaj. Ocenę AI (0404) niesie ``application_screenings`` przez
``submission_id``.

Reguły, które łatwo cofnąć:

* Lista jest firmowa, nie per osoba: ekran zawęża ją do rekrutacji wołającego
  (``job_read_scope_clause``), klucz widzi zgłoszenia każdej widocznej
  rekrutacji i zgłoszenia spoza rekrutacji. Rekrutacje klienta ukrytego albo
  usuniętego nie istnieją dla klucza (``jobs_register_base_clause``).
* Imię, e-mail, telefon i LinkedIn z formularza to dane kontaktowe — tylko
  z ``candidates:contact``. Bajty i nazwa pliku CV — tylko z ``candidates:cv``;
  cytaty z CV w powodach oceny AI także.
* Oczekiwana stawka z formularza to koszt — tylko z ``amounts:read``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, undefer

from app.models.application_screening import ApplicationScreening
from app.models.application_submission import ApplicationSubmission
from app.models.job import Job

_CONTACT_KEYS = ("first_name", "last_name", "email", "phone", "linkedin")


def aware(value: Optional[datetime]) -> Optional[datetime]:
    """Czas bez strefy z parametru zapytania = UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _visible_job_ids():
    from app.api.jobs import jobs_register_base_clause

    return select(Job.id).where(jobs_register_base_clause())


def visible_clause() -> ColumnElement:
    """Zgłoszenie spoza rekrutacji albo z rekrutacji widocznego klienta."""
    return or_(
        ApplicationSubmission.job_id.is_(None),
        ApplicationSubmission.job_id.in_(_visible_job_ids()),
    )


@dataclass(frozen=True)
class ApplicationFilters:
    job_id: Optional[int] = None
    statuses: tuple[str, ...] = ()
    updated_since: Optional[datetime] = None


def _screening_changed_since(since: datetime) -> ColumnElement:
    return (
        select(ApplicationScreening.id)
        .where(
            ApplicationScreening.submission_id == ApplicationSubmission.id,
            or_(
                ApplicationScreening.decided_at >= since,
                ApplicationScreening.overridden_at >= since,
            ),
        )
        .exists()
    )


def list_conditions(filters: ApplicationFilters) -> list[ColumnElement]:
    conditions = [visible_clause()]
    if filters.job_id is not None:
        conditions.append(ApplicationSubmission.job_id == filters.job_id)
    if filters.statuses:
        conditions.append(ApplicationSubmission.status.in_(filters.statuses))
    if filters.updated_since is not None:
        since = aware(filters.updated_since)
        conditions.append(
            or_(
                ApplicationSubmission.created_at >= since,
                ApplicationSubmission.reviewed_at >= since,
                _screening_changed_since(since),
            )
        )
    return conditions


def _submission_select():
    return (
        select(ApplicationSubmission, Job.title.label("job_title"))
        .options(defer(ApplicationSubmission.raw_cv_text))
        .outerjoin(Job, Job.id == ApplicationSubmission.job_id)
    )


async def list_page(
    db: AsyncSession, filters: ApplicationFilters, *, page: int, page_size: int
) -> tuple[list[Any], int]:
    """Strona zgłoszeń po id (bez bajtów i tekstu CV)."""
    conditions = list_conditions(filters)
    total = (
        await db.scalar(
            select(func.count()).select_from(ApplicationSubmission).where(*conditions)
        )
    ) or 0
    rows = (
        await db.execute(
            _submission_select()
            .where(*conditions)
            .order_by(ApplicationSubmission.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return list(rows), int(total)


async def load_visible(
    db: AsyncSession, submission_id: int, *, with_cv_bytes: bool = False
) -> Optional[Any]:
    """``(zgłoszenie, tytuł rekrutacji)`` albo ``None`` (brak albo ukryty klient).

    ``with_cv_bytes`` dociąga plik CV z bazy (zapas, gdy magazyn plików nie
    jest skonfigurowany) — tylko dla pobrania pliku."""
    query = _submission_select().where(
        ApplicationSubmission.id == submission_id, visible_clause()
    )
    if with_cv_bytes:
        query = query.options(undefer(ApplicationSubmission.cv_file_content))
    return (await db.execute(query)).first()


async def screenings_for(
    db: AsyncSession, submission_ids: Sequence[int]
) -> dict[int, ApplicationScreening]:
    """Najnowsza ocena AI każdego zgłoszenia (bez tekstu CV)."""
    if not submission_ids:
        return {}
    rows = (
        await db.scalars(
            select(ApplicationScreening)
            .options(defer(ApplicationScreening.cv_text))
            .where(ApplicationScreening.submission_id.in_(list(submission_ids)))
            .order_by(ApplicationScreening.id)
        )
    ).all()
    return {row.submission_id: row for row in rows}


# ── Projekcje (czyste) ───────────────────────────────────────────────────────


def contact_fields(submission: Any, *, visible: bool) -> dict[str, Any]:
    """Imię i kontakt z formularza — ``None`` bez ``candidates:contact``."""
    values = {
        "first_name": submission.submitted_first_name,
        "last_name": submission.submitted_last_name,
        "email": submission.submitted_email,
        "phone": submission.submitted_phone,
        "linkedin": submission.submitted_linkedin,
    }
    return {
        "contact_redacted": not visible,
        **{key: values[key] if visible else None for key in _CONTACT_KEYS},
    }


def screening_out(row: Optional[Any], *, show_quotes: bool) -> Optional[dict[str, Any]]:
    """Ocena AI: werdykt, wynik i powody po polsku; cytat z CV z ``candidates:cv``."""
    if row is None:
        return None
    reasons = []
    for item in row.reasons if isinstance(row.reasons, list) else []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        quote = str(item.get("quote") or "").strip() or None
        reasons.append({"text": text, "quote": quote if show_quotes else None})
    return {
        "status": row.status,
        "verdict": row.verdict,
        "outcome": row.outcome,
        "must_found": row.must_found,
        "must_total": row.must_total,
        "reasons": reasons,
        "decided_at": row.decided_at,
        "overridden_at": row.overridden_at,
    }


def updated_at(submission: Any, screening: Optional[Any]) -> datetime:
    """Ostatnia zmiana zgłoszenia lub jego oceny — to, co łapie ``updated_since``."""
    moments = [
        submission.created_at,
        submission.reviewed_at,
        getattr(screening, "decided_at", None),
        getattr(screening, "overridden_at", None),
    ]
    return max(m for m in moments if m is not None)


def _rate(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        rate = Decimal(str(value))
    except InvalidOperation:
        return None
    return rate if rate.is_finite() else None


def _text(value: Any) -> Optional[str]:
    return value.strip() or None if isinstance(value, str) else None


def _day(value: Any) -> Optional[date]:
    """Data z ``raw_payload`` — wiersz sprzed walidacji formularza nie wywraca odpowiedzi."""
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def answers_out(
    submission: Any, *, show_costs: bool, show_contact: bool
) -> dict[str, Any]:
    """Odpowiedzi z formularza (``raw_payload``) bez kontaktu i bez UTM-ów
    poza źródłem. Stawka oczekiwana to koszt — tylko przy ``show_costs``.
    Wiadomość kandydata to wolny tekst (zwykle z telefonem albo podpisem) —
    tylko przy ``show_contact``, jak pola kontaktowe."""
    payload = submission.raw_payload if isinstance(submission.raw_payload, dict) else {}
    utm = payload.get("utm") if isinstance(payload.get("utm"), dict) else {}
    return {
        "message": submission.submitted_message if show_contact else None,
        "message_redacted": not show_contact,
        "city": _text(payload.get("city")),
        "availability_date": _day(payload.get("availability_date")),
        "work_mode": _text(payload.get("work_mode")),
        "costs_redacted": not show_costs,
        "expected_rate_hourly": (
            _rate(payload.get("expected_rate_hourly")) if show_costs else None
        ),
        "link_kind": _text(payload.get("link_kind")),
        "via": _text(payload.get("via")),
        "utm_source": _text(utm.get("source")),
    }


def cv_fields(submission: Any, *, visible: bool) -> dict[str, Any]:
    return {
        "has_cv": bool(submission.cv_filename),
        "cv_file_name": submission.cv_filename if visible else None,
        "cv_mime_type": submission.cv_content_type if submission.cv_filename else None,
        "cv_size_bytes": submission.cv_size_bytes if submission.cv_filename else None,
    }


def item_out(
    submission: Any,
    job_title: Optional[str],
    screening: Optional[Any],
    *,
    contact: bool,
    cv: bool,
) -> dict[str, Any]:
    return {
        "id": submission.id,
        "status": submission.status,
        "job_id": submission.job_id,
        "job_title": job_title,
        "submitted_at": submission.created_at,
        "reviewed_at": submission.reviewed_at,
        "matched_candidate_id": submission.matched_candidate_id,
        **contact_fields(submission, visible=contact),
        "has_cv": bool(submission.cv_filename),
        "ai_screening": screening_out(screening, show_quotes=cv),
        "updated_at": updated_at(submission, screening),
    }
