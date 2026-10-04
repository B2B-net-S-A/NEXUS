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
    open_change = (
        await _open_change(db, candidate_id=candidate_id, job_id=job_id)
        if tracked
        else None
    )
    # Sprawa czekająca na decyzję DL porównuje się ze stawką, którą widział
    # klient (``previous`` tej sprawy), nie z kwotą zgłoszoną przed chwilą —
    # korekta 180 → 170 przy CV wysłanym za 150 nadal czeka na DL.
    pending = (
        open_change
        if open_change is not None and open_change.requires_decision
        else None
    )
    still_above_client_rate = (
        pending is not None
        and pending.previous_hourly is not None
        and requested_hourly is not None
        and requested_hourly > pending.previous_hourly
    )
    requires_decision = (
        tracked
        and column in DECISION_COLUMNS
        and ((went_up and reason != "typo") or still_above_client_rate)
    )
    carry = pending if (pending is not None and requires_decision) else None
    if open_change is not None:
        open_change.status = "superseded"
        await db.flush()

    change = CandidateRateChange(
        candidate_id=candidate_id,
        job_id=job_id,
        stage_id=stage.id,
        previous_amount=carry.previous_amount if carry else before["amount"],
        previous_unit=carry.previous_unit if carry else before["unit"],
        previous_currency=carry.previous_currency if carry else before["currency"],
        previous_hourly=carry.previous_hourly if carry else previous_hourly,
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


# ── Negocjacja i decyzja Delivery Leada (PR 3, D3/D6) ─────────────────────────

INTERNAL_ROLES_FOR_NEGOTIATOR = (
    "admin",
    "head_of_recruitment",
    "delivery_lead",
    "talent_community_manager",
    "recruiter",
)
# Akcje działają wyłącznie na OTWARTEJ sprawie pary. Wpisy „noted” nie są
# zastępowane, więc para bywa ich pełna — stary wpis nie może nadpisać
# nowszej stawki ani wejść na unikalny indeks otwartej sprawy.
NEGOTIABLE_STATUSES = ("requested",)
OUTCOME_STATUSES = ("requested", "negotiating")
DECIDABLE_STATUSES = ("requested", "agreed")


async def lock_change(db: AsyncSession, change_id: int) -> CandidateRateChange:
    """Blokuje sprawę w tej samej kolejności co ``change_rate``: kandydat →
    najnowszy wiersz etapu pary → sprawa. Odwrotna kolejność dawała zakleszczenie
    z równoległym zapisem stawki (debrief, panel osoby)."""

    from fastapi import HTTPException  # noqa: PLC0415

    from app.services.recruitment_process_commands import (  # noqa: PLC0415
        _lock_latest_stage,
    )

    pair = (
        await db.execute(
            select(CandidateRateChange.candidate_id, CandidateRateChange.job_id).where(
                CandidateRateChange.id == change_id
            )
        )
    ).first()
    if pair is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej zmiany stawki.")
    await _lock_latest_stage(db, candidate_id=pair[0], job_id=pair[1])
    change = await db.scalar(
        select(CandidateRateChange)
        .where(CandidateRateChange.id == change_id)
        .with_for_update()
    )
    if change is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej zmiany stawki.")
    return change


async def change_still_active(db: AsyncSession, change: CandidateRateChange) -> bool:
    """Sprawa ma sens, dopóki rekrutacja jest otwarta, a kandydat stoi między
    „Zweryfikowany” a „Umową” — po odrzuceniu, rezygnacji, zatrudnieniu albo
    zamknięciu rekrutacji nie ma już o czym decydować."""

    from app.models.job import JobStatus  # noqa: PLC0415

    job = await db.get(Job, change.job_id)
    if job is None or job.status != JobStatus.published:
        return False
    stage = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == change.candidate_id,
            CandidateStage.job_id == change.job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    return stage is not None and await _stage_column(db, stage) in NOTIFY_COLUMNS


async def job_delivery_leads(db: AsyncSession, job: Job) -> list[int]:
    from app.services.stage_handoff_recipients import (  # noqa: PLC0415
        _dl_reviewers,
    )

    return await _dl_reviewers(db, job)


async def can_decide(db: AsyncSession, user: User, job: Job) -> bool:
    """O stawce do klienta decyduje Delivery Lead rekrutacji albo admin (D6)."""

    if user.has_any_role("admin"):
        return True
    return user.id in await job_delivery_leads(db, job)


async def can_manage(db: AsyncSession, user: User, job: Job) -> bool:
    """Negocjację zleca DL rekrutacji, Head of Recruitment albo admin (D6)."""

    if user.has_any_role("admin", "head_of_recruitment"):
        return True
    return user.id in await job_delivery_leads(db, job)


async def can_record_outcome(
    db: AsyncSession, user: User, change: CandidateRateChange, job: Job
) -> bool:
    return change.negotiator_id == user.id or await can_manage(db, user, job)


def _forbidden(detail: str):  # noqa: ANN202
    from fastapi import HTTPException  # noqa: PLC0415

    return HTTPException(status_code=403, detail=detail)


def _conflict(detail: str):  # noqa: ANN202
    from fastapi import HTTPException  # noqa: PLC0415

    return HTTPException(status_code=409, detail=detail)


def _invalid(detail: str):  # noqa: ANN202
    from fastapi import HTTPException  # noqa: PLC0415

    return HTTPException(status_code=422, detail=detail)


async def _notify_simple(
    db: AsyncSession,
    *,
    change: CandidateRateChange,
    user_ids: list[int],
    actor: User,
    title: str,
    message: str,
    task: bool = False,
    result: Optional[RateChangeResult] = None,
) -> None:
    from app.services.notification_triggers import emit  # noqa: PLC0415

    link = f"/jobs/{change.job_id}?candidate={change.candidate_id}"
    seen: set[int] = {actor.id}
    for uid in user_ids:
        if uid in seen:
            continue
        seen.add(uid)
        try:
            notif = await emit(
                db,
                user_id=uid,
                title=title,
                message=message,
                ntype=(
                    NotificationType.candidate_rate_change_task
                    if task
                    else NotificationType.candidate_rate_change
                ),
                related_entity_type="candidate_rate_change",
                related_entity_id=change.id,
                link=link,
            )
        except Exception:  # noqa: BLE001 — dzwonek nie cofa zapisu
            logger.exception("rate change notify failed change=%s", change.id)
            continue
        if notif is not None and result is not None:
            result.notified_user_ids.append(uid)


async def _pair_label(db: AsyncSession, change: CandidateRateChange) -> str:
    job = await db.get(Job, change.job_id)
    candidate = await db.get(Candidate, change.candidate_id)
    return f"{_candidate_name(candidate)} · {job.title if job else 'rekrutacja'}"


async def start_negotiation(
    db: AsyncSession,
    *,
    change: CandidateRateChange,
    negotiator_id: int,
    target_hourly: Optional[Decimal],
    due: Optional[object],
    actor: User,
) -> RateChangeResult:
    job = await db.get(Job, change.job_id)
    if job is None or not await can_manage(db, actor, job):
        raise _forbidden(
            "Negocjację stawki zleca Delivery Lead rekrutacji albo Head of Recruitment."
        )
    if change.status not in NEGOTIABLE_STATUSES:
        raise _conflict("Ta zmiana stawki nie czeka już na negocjację.")
    negotiator = await db.get(User, negotiator_id)
    if (
        negotiator is None
        or not negotiator.is_active
        or not negotiator.has_any_role(*INTERNAL_ROLES_FOR_NEGOTIATOR)
    ):
        raise _invalid(
            "Wybierz aktywną osobę z zespołu, która porozmawia z kandydatem."
        )
    change.status = "negotiating"
    change.negotiator_id = negotiator_id
    change.negotiation_target_hourly = target_hourly
    change.negotiation_due = due  # type: ignore[assignment]
    change.updated_at = datetime.now(timezone.utc)
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=change.candidate_id,
            action="candidate_rate_change_negotiation",
            user_id=actor.id,
            details={
                "change_id": change.id,
                "job_id": change.job_id,
                "negotiator_id": negotiator_id,
            },
        )
    )
    await db.flush()
    result = RateChangeResult(change=change)
    label = await _pair_label(db, change)
    target = f" Cel: do {_short(target_hourly)} zł/h." if target_hourly else ""
    await _notify_simple(
        db,
        change=change,
        user_ids=[negotiator_id],
        actor=actor,
        title="Porozmawiaj z kandydatem o stawce",
        message=(
            f"{label}: kandydat chce "
            f"{format_rate(change.requested_amount, change.requested_unit, change.requested_currency)}."
            f"{target} Zleca: {actor.name or actor.email}. Po rozmowie zapisz wynik w panelu osoby."
        ),
        task=True,
        result=result,
    )
    return result


async def record_outcome(
    db: AsyncSession,
    *,
    change: CandidateRateChange,
    outcome: str,
    agreed_amount: Optional[Decimal],
    note: Optional[str],
    actor: User,
) -> RateChangeResult:
    job = await db.get(Job, change.job_id)
    if job is None or not await can_record_outcome(db, actor, change, job):
        raise _forbidden(
            "Wynik negocjacji zapisuje osoba, która rozmawia z kandydatem, "
            "Delivery Lead albo Head of Recruitment."
        )
    if change.status not in OUTCOME_STATUSES:
        raise _conflict("Ta zmiana stawki ma już zapisany wynik.")
    now = datetime.now(timezone.utc)
    change.outcome = outcome
    change.outcome_note = (note or "").strip() or None
    change.outcome_by = actor.id
    change.outcome_at = now
    change.updated_at = now
    if outcome == "lower":
        if agreed_amount is None or agreed_amount <= 0:
            raise _invalid("Wpisz ustaloną stawkę.")
        agreed_hourly = _hourly(agreed_amount, "hourly", "PLN")
        if (
            change.requested_hourly is not None
            and agreed_hourly >= change.requested_hourly
        ):
            raise _invalid("Ustalona stawka musi być niższa niż zgłoszona.")
        await update_latest_expected_rate(
            db,
            candidate_id=change.candidate_id,
            job_id=change.job_id,
            rate_value=agreed_amount,
            rate_unit="hourly",
            rate_currency="PLN",
        )
        change.agreed_amount = agreed_amount
        change.agreed_unit = "hourly"
        change.agreed_currency = "PLN"
        change.agreed_hourly = agreed_hourly
    elif outcome == "kept":
        change.agreed_amount = change.requested_amount
        change.agreed_unit = change.requested_unit
        change.agreed_currency = change.requested_currency
        change.agreed_hourly = change.requested_hourly
    if outcome == "withdrew":
        change.status = "closed"
        change.decision = "withdraw"
        change.decided_by = actor.id
        change.decided_at = now
    elif (
        change.agreed_hourly is not None
        and change.previous_hourly is not None
        and change.agreed_hourly <= change.previous_hourly
    ):
        # Kandydat zszedł do stawki sprzed zmiany — stawka do klienta bez
        # zmian, sprawa zamyka się sama.
        change.status = "closed"
        change.decision = "auto"
        change.decided_at = now
    elif change.requires_decision:
        change.status = "agreed"
    else:
        change.status = "closed"
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=change.candidate_id,
            action="candidate_rate_change_agreed",
            user_id=actor.id,
            details={
                "change_id": change.id,
                "job_id": change.job_id,
                "outcome": outcome,
                "agreed": format_rate(
                    change.agreed_amount, change.agreed_unit, change.agreed_currency
                )
                if change.agreed_amount is not None
                else None,
            },
        )
    )
    await db.flush()
    result = RateChangeResult(change=change)
    label = await _pair_label(db, change)
    requested = format_rate(
        change.requested_amount, change.requested_unit, change.requested_currency
    )
    if outcome == "withdrew":
        text = f"{label}: kandydat rezygnuje po rozmowie o stawce ({requested})."
        title = "Kandydat rezygnuje po rozmowie o stawce"
    elif outcome == "kept":
        text = f"{label}: kandydat nie ustąpił — zostaje {requested}."
        title = "Stawka po negocjacji bez zmian"
    else:
        agreed = format_rate(
            change.agreed_amount, change.agreed_unit, change.agreed_currency
        )
        text = f"{label}: zgłoszona {requested} → ustalona {agreed}."
        title = "Stawka ustalona po negocjacji"
    if change.outcome_note:
        text += f" „{change.outcome_note}”"
    if change.status == "agreed":
        text += " Decyzja o stawce do klienta należy do Delivery Leada."
    from app.services.notification_triggers import _hor_user_ids  # noqa: PLC0415
    from app.services.stage_handoff_recipients import pair_recruiter_id  # noqa: PLC0415

    recipients: list[int] = []
    if job is not None:
        recipients.extend(await job_delivery_leads(db, job))
    recipients.extend(await _hor_user_ids(db))
    recruiter = await pair_recruiter_id(
        db, candidate_id=change.candidate_id, job_id=change.job_id
    )
    if recruiter is not None:
        recipients.append(recruiter)
    if change.created_by is not None:
        recipients.append(change.created_by)
    await _notify_simple(
        db,
        change=change,
        user_ids=recipients,
        actor=actor,
        title=title,
        message=text,
        task=False,
        result=result,
    )
    from app.services.candidate_rate_from import recompute_safely  # noqa: PLC0415

    await recompute_safely(db, [change.candidate_id])
    return result


async def decide(
    db: AsyncSession,
    *,
    change: CandidateRateChange,
    decision: str,
    client_rate_amount: Optional[Decimal],
    client_rate_unit: Optional[str],
    client_rate_currency: Optional[str],
    actor: User,
) -> RateChangeResult:
    from app.api.candidate_access import (  # noqa: PLC0415
        client_rate_write_denied,
        resolve_client_rate_write,
    )
    from app.services import candidate_audit  # noqa: PLC0415
    from app.services.recruitment_process_commands import (  # noqa: PLC0415
        update_latest_client_rate,
    )

    job = await db.get(Job, change.job_id)
    if job is None or not await can_decide(db, actor, job):
        raise _forbidden("O stawce do klienta decyduje Delivery Lead rekrutacji.")
    if change.status not in DECIDABLE_STATUSES or not change.requires_decision:
        raise _conflict("Ta zmiana stawki nie czeka na decyzję.")
    if decision == "raise_client":
        if client_rate_amount is None or client_rate_amount <= 0:
            raise _invalid("Wpisz nową stawkę do klienta.")
        if not await resolve_client_rate_write(db, actor, job):
            raise client_rate_write_denied()
        stage, previous = await update_latest_client_rate(
            db,
            candidate_id=change.candidate_id,
            job_id=change.job_id,
            rate_value=client_rate_amount,
            rate_unit=client_rate_unit or "hourly",
            rate_currency=(client_rate_currency or "PLN")[:3].upper(),
        )
        candidate_audit.record_candidate_audit(
            db,
            action=candidate_audit.CLIENT_RATE_CHANGED,
            user_id=actor.id,
            entity_id=change.candidate_id,
            details={
                "job_id": change.job_id,
                "stage_id": stage.id,
                "old_client_rate": float(previous[0])
                if previous[0] is not None
                else None,
                "old_client_rate_unit": previous[1],
                "old_client_rate_currency": previous[2],
                "new_client_rate": float(client_rate_amount),
                "new_client_rate_unit": client_rate_unit or "hourly",
                "new_client_rate_currency": (client_rate_currency or "PLN")[:3].upper(),
                "rate_change_id": change.id,
            },
        )
    now = datetime.now(timezone.utc)
    change.status = "closed"
    change.decision = decision
    change.decided_by = actor.id
    change.decided_at = now
    change.updated_at = now
    # Stawka do klienta nie trafia do dziennika kandydata (oś czasu jest jawna);
    # zmiana stawki do klienta ma własny, ukryty wpis `client_rate_changed`.
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=change.candidate_id,
            action="candidate_rate_change_decided",
            user_id=actor.id,
            details={
                "change_id": change.id,
                "job_id": change.job_id,
                "decision": decision,
            },
        )
    )
    await db.flush()
    result = RateChangeResult(change=change)
    label = await _pair_label(db, change)
    texts = {
        "raise_client": "DL podnosi stawkę do klienta.",
        "keep_client": "DL zostawia stawkę do klienta bez zmian.",
        "withdraw": "DL wycofuje kandydata z procesu.",
    }
    from app.services.stage_handoff_recipients import pair_recruiter_id  # noqa: PLC0415

    recipients = []
    recruiter = await pair_recruiter_id(
        db, candidate_id=change.candidate_id, job_id=change.job_id
    )
    if recruiter is not None:
        recipients.append(recruiter)
    if change.created_by is not None:
        recipients.append(change.created_by)
    if change.negotiator_id is not None:
        recipients.append(change.negotiator_id)
    await _notify_simple(
        db,
        change=change,
        user_ids=recipients,
        actor=actor,
        title="Decyzja o zmianie stawki",
        message=f"{label}: {texts.get(decision, decision)}",
        result=result,
    )
    return result


# ── Przypomnienia (raz dziennie, 8–17 czasu firmy) ──────────────────────────

_REMINDERS_DONE_FOR: Optional[object] = None
REMINDER_FROM_HOUR = 8
REMINDER_UNTIL_HOUR = 17


async def send_reminders(db: AsyncSession, now: datetime) -> int:
    """DL: decyzja czeka od poprzedniego dnia; negocjator: termin rozmowy
    minął albo jest dziś. Jeden dzwonek na sprawę dziennie (dedup ``emit``)."""

    from zoneinfo import ZoneInfo  # noqa: PLC0415

    from app.core.scheduling import is_business_day  # noqa: PLC0415

    global _REMINDERS_DONE_FOR
    local = now.astimezone(ZoneInfo(settings.BUSINESS_TZ))
    if not (REMINDER_FROM_HOUR <= local.hour < REMINDER_UNTIL_HOUR):
        return 0
    if _REMINDERS_DONE_FOR == local.date() or not is_business_day(
        now, settings.BUSINESS_TZ
    ):
        return 0
    today = local.date()
    sent = 0
    try:
        async with db.begin_nested():
            changes = (
                await db.scalars(
                    select(CandidateRateChange).where(
                        CandidateRateChange.status.in_(
                            ("requested", "agreed", "negotiating")
                        )
                    )
                )
            ).all()
            for change in changes:
                job = await db.get(Job, change.job_id)
                if job is None:
                    continue
                if not await change_still_active(db, change):
                    # Proces się skończył (odrzucenie, rezygnacja, zatrudnienie,
                    # zamknięta rekrutacja) — sprawa zamyka się sama, bez
                    # decyzji, i znika z „Czeka na Ciebie”.
                    change.status = "closed"
                    change.updated_at = now
                    await db.flush()
                    continue
                label = await _pair_label(db, change)
                requested = format_rate(
                    change.requested_amount,
                    change.requested_unit,
                    change.requested_currency,
                )
                if change.status == "negotiating" and change.negotiator_id:
                    if change.negotiation_due is None or change.negotiation_due > today:
                        continue
                    targets = [change.negotiator_id]
                    title = "Przypomnienie: rozmowa z kandydatem o stawce"
                    message = (
                        f"{label}: kandydat chce {requested}. Termin rozmowy: "
                        f"{change.negotiation_due:%d.%m}. Zapisz wynik w panelu osoby."
                    )
                elif change.requires_decision and change.status in (
                    "requested",
                    "agreed",
                ):
                    since = (change.updated_at or change.created_at).astimezone(
                        ZoneInfo(settings.BUSINESS_TZ)
                    )
                    if since.date() >= today:
                        continue
                    targets = await job_delivery_leads(db, job)
                    shown = (
                        format_rate(
                            change.agreed_amount,
                            change.agreed_unit,
                            change.agreed_currency,
                        )
                        if change.agreed_amount is not None
                        else requested
                    )
                    title = "Przypomnienie: decyzja o stawce kandydata"
                    message = (
                        f"{label}: kandydat chce {shown}, CV jest u klienta. "
                        "Zdecyduj o stawce do klienta albo zleć negocjację."
                    )
                else:
                    continue
                from app.services.notification_triggers import emit  # noqa: PLC0415

                for uid in targets:
                    notif = await emit(
                        db,
                        user_id=uid,
                        title=title,
                        message=message,
                        ntype=NotificationType.candidate_rate_change_task,
                        related_entity_type="candidate_rate_change",
                        related_entity_id=change.id,
                        link=f"/jobs/{change.job_id}?candidate={change.candidate_id}",
                    )
                    if notif is not None:
                        sent += 1
    except Exception:  # noqa: BLE001 — przypomnienia nie zatrzymują ticku
        logger.exception("rate change reminders failed")
        return sent
    _REMINDERS_DONE_FOR = today
    return sent


# ── Trwające procesy kandydata (D4: zmiana stawki w profilu) ────────────────


@dataclass(frozen=True)
class ActiveProcess:
    job_id: int
    job_title: str
    client_name: Optional[str]
    board_column: str
    current_label: Optional[str]


async def active_processes(
    db: AsyncSession, *, candidate_id: int
) -> list[ActiveProcess]:
    """Rekrutacje kandydata od „Zweryfikowany” do „Umowy” (opublikowane) —
    okno stawki w profilu pyta, w których z nich zmienić stawkę (D4)."""

    from app.models.client import Client  # noqa: PLC0415
    from app.models.job import JobStatus  # noqa: PLC0415

    latest = (
        select(CandidateStage)
        .where(CandidateStage.candidate_id == candidate_id)
        .order_by(CandidateStage.job_id, CandidateStage.id.desc())
        .distinct(CandidateStage.job_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(CandidateStage, Job, Client.name)
            .join(latest, latest.c.id == CandidateStage.id)
            .join(Job, Job.id == CandidateStage.job_id)
            .outerjoin(Client, Client.id == Job.client_id)
            .where(Job.status == JobStatus.published)
            .order_by(CandidateStage.id.desc())
        )
    ).all()
    out: list[ActiveProcess] = []
    for stage, job, client_name in rows:
        column = await _stage_column(db, stage)
        if column not in NOTIFY_COLUMNS:
            continue
        rates = await pair_rates(db, candidate_id=candidate_id, job_id=job.id)
        out.append(
            ActiveProcess(
                job_id=job.id,
                job_title=job.working_title or job.title,
                client_name=client_name,
                board_column=column,
                current_label=format_rate(
                    rates["amount"], rates["unit"], rates["currency"]
                )
                if rates["amount"] is not None
                else None,
            )
        )
    return out


async def pair_column(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[str]:
    """Kolumna Tablicy najnowszego wiersza pary (``None`` = pary nie ma)."""

    stage = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.id.desc())
        .limit(1)
    )
    return await _stage_column(db, stage) if stage is not None else None
