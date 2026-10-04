"""Zmiana stawki kandydata w trakcie procesu — JEDNA reguła zapisu (0418).

Decyzje Artura 04.10.2026 (makiety https://claude.ai/artifact/2bJy59VoHb67EcX5wj1tz9):

* D1 — powiadomienia dopiero od kolumny „Zweryfikowany”; wcześniej stawka się
  dopiero ustala (wiersz ``noted``, bez dzwonków).
* D2 — każdy aktywny Head of Recruitment dostaje dzwonek informacyjny.
* D3 — wzrost stawki po wysłaniu CV („CV wysłane” i dalej) to ZADANIE Delivery
  Leada (typ ``candidate_rate_change_task``, kategoria obowiązkowa, mail).
* D5 — spadek stawki to tylko informacja (marża rośnie).
* „Pomyłka przy wpisie” poprawia liczbę bez zadania.
* D7 — zgłoszona stawka od razu staje się stawką kandydata w tej rekrutacji
  (``expected_rate_*`` najnowszego wiersza etapu); negocjację i decyzję
  o stawce do klienta prowadzi sprawa.

Każdy zapis stawki kandydata w procesie idzie przez ``change_rate`` —
debrief, panel osoby, profil (Rekrutacje), ruch z powrotem na „Zweryfikowany”.
Stawka do klienta i marża trafiają do treści powiadomienia WYŁĄCZNIE dla ról,
które widzą stawkę do klienta (``user_can_view_client_rate``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_rate_change import CandidateRateChange
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services.board_stage_badges import board_column_for
from app.services.candidate_rate_change_schema import OPEN_STATUSES
from app.services.candidate_rate_observations import hourly_from_unit
from app.services.notification_access import notification_recipient_has_access
from app.services.notification_delivery import guarded_send, load_policy
from app.services.recruitment_process_commands import update_latest_expected_rate

logger = logging.getLogger(__name__)

# Kolumny Tablicy (lustro ``board_stage_badges._COLUMN_*``).
NOTIFY_COLUMNS = frozenset(
    {"verified", "cv_qc", "cv_sent", "client_interview", "contract"}
)
DECISION_COLUMNS = frozenset({"cv_sent", "client_interview", "contract"})

SOURCE_LABELS = {
    "debrief": "debrief po rozmowie u klienta",
    "manual": "panel osoby",
    "recruitments_tab": "profil kandydata",
    "profile": "profil kandydata",
    "card": "karta rekomendacji",
    "move": "ponowna weryfikacja",
}
REASON_LABELS = {
    "conversation": "rozmowa z kandydatem",
    "email": "mail od kandydata",
    "typo": "poprawka pomyłki",
    "other": "inne",
}
UNIT_LABELS = {"hourly": "h", "daily": "dzień", "monthly": "mies."}

EMAIL_KIND = "rate_change"


@dataclass(frozen=True)
class PendingRateEmail:
    """Mail do wysłania PO commicie (wysyłka nie może cofnąć zapisu)."""

    to: str
    subject: str
    text: str
    event_at: object = None


@dataclass
class RateChangeResult:
    change: Optional[CandidateRateChange]
    emails: list[PendingRateEmail] = field(default_factory=list)
    notified_user_ids: list[int] = field(default_factory=list)


def _value(raw: object) -> Optional[str]:
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


def format_rate(
    amount: Optional[Decimal], unit: Optional[str], currency: Optional[str]
) -> str:
    if amount is None:
        return "brak"
    text = f"{Decimal(amount).normalize():f}".rstrip(".")
    cur = (currency or "PLN").upper()
    money = "zł" if cur == "PLN" else cur
    return f"{text} {money}/{UNIT_LABELS.get(unit or '', unit or '?')}"


def _short(amount: Optional[Decimal]) -> str:
    if amount is None:
        return "?"
    return f"{Decimal(amount).normalize():f}"


async def _stage_column(db: AsyncSession, stage: CandidateStage) -> str:
    stage_def = (
        await db.get(PipelineStageDef, stage.stage_def_id)
        if stage.stage_def_id is not None
        else None
    )
    if stage_def is None:
        return board_column_for(None, _value(stage.stage))
    return board_column_for(
        stage_def.name,
        _value(stage.stage) or _value(stage_def.legacy_enum_value),
        category=_value(stage_def.category),
        terminal_type=_value(stage_def.terminal_type),
    )


async def pair_rates(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> dict[str, Optional[object]]:
    """Najnowsza niepusta stawka kandydata i do klienta pary — ta sama reguła
    co ``carried_expected_rate`` na Tablicy (stawka „idzie” z wcześniejszego
    wiersza, gdy najnowszy jej nie ma)."""

    rows = (
        await db.execute(
            select(
                CandidateStage.expected_rate_value,
                CandidateStage.expected_rate_unit,
                CandidateStage.expected_rate_currency,
                CandidateStage.client_rate_value,
                CandidateStage.client_rate_unit,
                CandidateStage.client_rate_currency,
            )
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        )
    ).all()
    out: dict[str, Optional[object]] = {
        "amount": None,
        "unit": None,
        "currency": None,
        "client_amount": None,
        "client_unit": None,
        "client_currency": None,
    }
    for row in rows:
        if out["amount"] is None and row[0] is not None:
            out.update(amount=row[0], unit=_value(row[1]), currency=row[2] or "PLN")
        if out["client_amount"] is None and row[3] is not None:
            out.update(
                client_amount=row[3],
                client_unit=_value(row[4]),
                client_currency=row[5] or "PLN",
            )
    return out


def _hourly(
    amount: object, unit: Optional[str], currency: Optional[str]
) -> Optional[Decimal]:
    value = hourly_from_unit(amount, unit, currency)
    return value.quantize(Decimal("0.01")) if value is not None else None


def _same_rate(
    a_amount: object,
    a_unit: Optional[str],
    a_cur: Optional[str],
    b_amount: object,
    b_unit: Optional[str],
    b_cur: Optional[str],
) -> bool:
    if a_amount is None or b_amount is None:
        return False
    if (a_unit, (a_cur or "PLN").upper()) == (b_unit, (b_cur or "PLN").upper()):
        return Decimal(str(a_amount)) == Decimal(str(b_amount))
    a_h = _hourly(a_amount, a_unit, a_cur)
    b_h = _hourly(b_amount, b_unit, b_cur)
    return a_h is not None and a_h == b_h


async def _open_change(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[CandidateRateChange]:
    return await db.scalar(
        select(CandidateRateChange)
        .where(
            CandidateRateChange.candidate_id == candidate_id,
            CandidateRateChange.job_id == job_id,
            CandidateRateChange.status.in_(OPEN_STATUSES),
        )
        .with_for_update()
    )


def _candidate_name(candidate: Optional[Candidate]) -> str:
    if candidate is None:
        return "Kandydat"
    parts = [getattr(candidate, "name", None), getattr(candidate, "lastname", None)]
    return " ".join(p for p in parts if p) or f"Kandydat #{candidate.id}"


async def change_rate(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    amount: Decimal,
    unit: str,
    currency: str,
    source: str,
    reason: str,
    actor: User,
    note: Optional[str] = None,
    negotiable: Optional[str] = None,
    feedback_id: Optional[int] = None,
    notify: bool = True,
) -> RateChangeResult:
    """Zapisz nową stawkę kandydata w tej rekrutacji i otwórz sprawę zmiany.

    Zwraca ``RateChangeResult`` z wierszem sprawy (``None`` = ta sama stawka,
    nic się nie zmieniło) i mailami do wysłania po commicie
    (``send_pending_emails``). Dzwonki są zapisane w tej samej transakcji.
    """

    unit = _value(unit) or "hourly"
    currency = (currency or "PLN")[:3].upper()
    note = (note or "").strip() or None
    before = await pair_rates(db, candidate_id=candidate_id, job_id=job_id)
    if _same_rate(
        before["amount"], before["unit"], before["currency"], amount, unit, currency
    ):
        return RateChangeResult(change=None)

    stage, _job = await update_latest_expected_rate(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        rate_value=amount,
        rate_unit=unit,
        rate_currency=currency,
    )
    column = await _stage_column(db, stage)
    previous_hourly = (
        _hourly(before["amount"], before["unit"], before["currency"])
        if before["amount"] is not None
        else None
    )
    requested_hourly = _hourly(amount, unit, currency)
    went_up = (
        previous_hourly is not None
        and requested_hourly is not None
        and requested_hourly > previous_hourly
    )
    tracked = column in NOTIFY_COLUMNS
    requires_decision = (
        tracked and column in DECISION_COLUMNS and went_up and reason != "typo"
    )

    if tracked:
        open_change = await _open_change(db, candidate_id=candidate_id, job_id=job_id)
        if open_change is not None:
            open_change.status = "superseded"
            await db.flush()

    change = CandidateRateChange(
        candidate_id=candidate_id,
        job_id=job_id,
        stage_id=stage.id,
        previous_amount=before["amount"],
        previous_unit=before["unit"],
        previous_currency=before["currency"],
        previous_hourly=previous_hourly,
        requested_amount=amount,
        requested_unit=unit,
        requested_currency=currency,
        requested_hourly=requested_hourly,
        source=source,
        reason=reason,
        note=note,
        negotiable=negotiable,
        feedback_id=feedback_id,
        status="requested" if requires_decision else "noted",
        requires_decision=requires_decision,
        board_column=column,
        created_by=actor.id,
        # Jawnie, nie z bazy: odczyt domyślnej wartości po flushu w sesji
        # async to MissingGreenlet (mail i dzwonek czytają tę datę).
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(change)
    await db.flush()

    # Stawka kandydata jest jawna dla wszystkich ról (23.09.2026) — wpis
    # w historii profilu niesie ją; stawki do klienta nigdy.
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action="candidate_rate_change_requested",
            user_id=actor.id,
            details={
                "change_id": change.id,
                "job_id": job_id,
                "previous": format_rate(
                    before["amount"], before["unit"], before["currency"]
                )
                if before["amount"] is not None
                else None,
                "requested": format_rate(amount, unit, currency),
                "source": source,
                "reason": reason,
                "status": change.status,
            },
        )
    )
    await db.flush()

    result = RateChangeResult(change=change)
    if notify and tracked:
        try:
            await _notify(db, change=change, before=before, actor=actor, result=result)
        except Exception:  # noqa: BLE001 — dzwonek nie cofa zapisu stawki
            logger.exception("rate change notify failed change=%s", change.id)

    from app.services.candidate_rate_from import recompute_safely  # noqa: PLC0415

    await recompute_safely(db, [candidate_id])
    return result


async def _recipients(
    db: AsyncSession, *, job: Job, candidate_id: int, actor_id: int
) -> list[tuple[int, str]]:
    """``[(user_id, rola_w_sprawie)]`` — DL, HoR, rekruter; bez autora i
    bez powtórzeń (osoba z dwiema rolami dostaje ważniejszy wpis)."""

    from app.services.notification_triggers import (  # noqa: PLC0415 — cykl
        _hor_user_ids,
    )
    from app.services.stage_handoff_recipients import (  # noqa: PLC0415
        _dl_reviewers,
        pair_recruiter_id,
    )

    out: list[tuple[int, str]] = []
    seen: set[int] = {actor_id}
    for uid in await _dl_reviewers(db, job):
        if uid not in seen:
            seen.add(uid)
            out.append((uid, "dl"))
    for uid in await _hor_user_ids(db):
        if uid not in seen:
            seen.add(uid)
            out.append((uid, "hor"))
    recruiter = await pair_recruiter_id(db, candidate_id=candidate_id, job_id=job.id)
    if recruiter is not None and recruiter not in seen:
        out.append((recruiter, "recruiter"))
    return out


async def _notify(
    db: AsyncSession,
    *,
    change: CandidateRateChange,
    before: dict[str, Optional[object]],
    actor: User,
    result: RateChangeResult,
) -> None:
    from app.api.candidate_access import user_can_view_client_rate  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415

    job = await db.get(Job, change.job_id)
    candidate = await db.get(Candidate, change.candidate_id)
    if job is None:
        return
    recipients = await _recipients(
        db, job=job, candidate_id=change.candidate_id, actor_id=actor.id
    )
    if not recipients:
        return
    name = _candidate_name(candidate)
    rate_line = (
        f"{format_rate(change.previous_amount, change.previous_unit, change.previous_currency)}"
        f" → {format_rate(change.requested_amount, change.requested_unit, change.requested_currency)}"
    )
    who = f"{actor.name or actor.email}, {SOURCE_LABELS.get(change.source, change.source)}"
    client_line = _client_line(change, before)
    link = f"/jobs/{change.job_id}?candidate={change.candidate_id}"
    policy = await load_policy(db) if change.requires_decision else None

    for user_id, role in recipients:
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            continue
        task = change.requires_decision and role == "dl"
        if task:
            title = "Kandydat podniósł stawkę po wysłaniu CV"
        elif role == "recruiter":
            title = "Ktoś zmienił stawkę Twojego kandydata"
        else:
            title = "Zmiana stawki kandydata"
        parts = [f"{name} · {job.title}: {rate_line}."]
        if client_line and user_can_view_client_rate(user):
            parts.append(client_line)
        if change.note:
            parts.append(f"„{change.note}”")
        parts.append(f"Zgłosił(a): {who}.")
        if task:
            parts.append("Zdecyduj o stawce do klienta albo zleć negocjację.")
        elif change.requires_decision:
            parts.append("Decyzję podejmuje Delivery Lead.")
        message = " ".join(parts)
        ntype = (
            NotificationType.candidate_rate_change_task
            if task
            else NotificationType.candidate_rate_change
        )
        notif = await emit(
            db,
            user_id=user_id,
            title=title,
            message=message,
            ntype=ntype,
            related_entity_type="candidate_rate_change",
            related_entity_id=change.id,
            link=link,
        )
        if notif is not None:
            result.notified_user_ids.append(user_id)
        if (
            task
            and user.email
            and policy is not None
            and policy.allows(EMAIL_KIND, change.created_at)
            and await notification_recipient_has_access(
                db,
                user_id,
                ntype,
                related_entity_type="candidate_rate_change",
                link=link,
            )
        ):
            base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
            result.emails.append(
                PendingRateEmail(
                    to=user.email,
                    subject=f"{title}: {name}",
                    text=f"{message}\n\n{base}{link}",
                    event_at=change.created_at,
                )
            )


def _client_line(
    change: CandidateRateChange, before: dict[str, Optional[object]]
) -> Optional[str]:
    client_amount = before.get("client_amount")
    if client_amount is None:
        return None
    client_unit = before.get("client_unit")
    client_currency = before.get("client_currency")
    line = f"Do klienta {format_rate(client_amount, client_unit, client_currency)}"
    client_hourly = _hourly(client_amount, client_unit, client_currency)
    if (
        client_hourly is not None
        and change.previous_hourly is not None
        and change.requested_hourly is not None
    ):
        line += (
            f", marża {_short(client_hourly - change.previous_hourly)} → "
            f"{_short(client_hourly - change.requested_hourly)} zł/h"
        )
    return line + "."


def _send_one(email: PendingRateEmail) -> None:
    from app.services.email import send_email  # noqa: PLC0415

    guarded_send(
        EMAIL_KIND, email.event_at, send_email, email.to, email.subject, email.text
    )


async def send_pending_emails(emails: list[PendingRateEmail]) -> None:
    """Wyślij maile po commicie — błąd wysyłki tylko w logu."""

    for email in emails:
        try:
            await run_in_threadpool(_send_one, email)
        except Exception as exc:  # noqa: BLE001
            logger.warning("rate change email failed: %s", type(exc).__name__)


async def open_badges_for_job(
    db: AsyncSession, *, job_id: int, viewer: Optional[User] = None
) -> dict[int, dict]:
    """Otwarte sprawy zmiany stawki w rekrutacji — plakietka karty Tablicy.

    Jedno zapytanie na tablicę. ``{candidate_id: {...}}``; tylko sprawy
    otwarte (zgłoszona, w negocjacji, ustalona), bo po zamknięciu na karcie
    zostaje sama kwota.
    """

    rows = (
        await db.execute(
            select(CandidateRateChange, User.name)
            .outerjoin(User, User.id == CandidateRateChange.negotiator_id)
            .where(
                CandidateRateChange.job_id == job_id,
                CandidateRateChange.status.in_(OPEN_STATUSES),
            )
        )
    ).all()
    out: dict[int, dict] = {}
    for change, negotiator_name in rows:
        out[change.candidate_id] = {
            "id": change.id,
            "status": change.status,
            "requires_decision": change.requires_decision,
            "previous_hourly": float(change.previous_hourly)
            if change.previous_hourly is not None
            else None,
            "requested_hourly": float(change.requested_hourly)
            if change.requested_hourly is not None
            else None,
            "requested_label": format_rate(
                change.requested_amount,
                change.requested_unit,
                change.requested_currency,
            ),
            "agreed_hourly": float(change.agreed_hourly)
            if change.agreed_hourly is not None
            else None,
            "negotiator_name": negotiator_name,
            "negotiation_due": change.negotiation_due.isoformat()
            if change.negotiation_due
            else None,
            "created_at": change.created_at.isoformat() if change.created_at else None,
        }
    return out
