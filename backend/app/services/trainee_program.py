"""Praktykant — dzień pracy, zapis rozmowy, panel Head of Recruitment (0374).

Zapis rozmowy to jedna transakcja pod blokadą wiersza kandydata: fakty
w profilu (minimalna stawka przez ``write_profile_rate``), notatka w historii,
wiersz ``calls`` i audyt. Po zapisie bramki dopasowań czytają nowe fakty
(``dealbreaker_filters``) — dlatego ``mark_stale_for_candidate``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.call import Call, CallDirection, CallStatus
from app.models.candidate import AvailabilityStatus, Candidate
from app.models.job import Job, JobStatus
from app.models.job_proposal import JobProposal
from app.models.note import Note, NoteType
from app.models.recruitment_pipeline import CandidateStage
from app.models.trainee import TraineeCallItem, TraineeCallList, TraineeProgram
from app.models.user import User, UserRole
from app.services import trainee_call_list as lists
from app.services import trainee_rules as rules_mod

logger = logging.getLogger(__name__)

NOTE_SOURCE = "trainee_call"
CONTACT_SOURCE = "trainee"
DECISION_NOTICE_WORKDAYS = 5
QUALITY_SAMPLE_SIZE = 5

B2B_VALUES = ("b2b", "would_switch", "employment_only")
WORK_TIME_VALUES = ("full_time_only", "also_part_time", "part_time_only")
AVAILABILITY_DAYS = {"now": 0, "within_1m": 30, "within_3m": 90}
OPEN_TO_STATUS = {
    "yes": AvailabilityStatus.actively_looking,
    "maybe": AvailabilityStatus.open_to_offers,
    "no": AvailabilityStatus.not_looking,
}
_B2B_LABEL = {
    "b2b": "pracuje na B2B",
    "would_switch": "przejdzie z etatu na B2B",
    "employment_only": "tylko umowa o pracę — nie przejdzie na B2B",
}
_WORK_TIME_LABEL = {
    "full_time_only": "tylko full-time",
    "also_part_time": "też part-time",
    "part_time_only": "tylko part-time",
}
_MODE_LABEL = {"remote": "zdalnie", "hybrid": "hybrydowo", "onsite": "biuro"}
_AVAILABILITY_LABEL = {
    "now": "od zaraz",
    "within_1m": "do 1 miesiąca",
    "within_3m": "1–3 miesiące",
    "later": "później",
}
_OPEN_LABEL = {"yes": "szuka projektu", "maybe": "rozważy", "no": "nie teraz"}
_UNIT_LABEL = {"hour": "zł/h", "day": "zł/dzień", "month": "zł/mies."}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _http(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


# ── Program ───────────────────────────────────────────────────────────────


async def program_for(db: AsyncSession, user_id: int) -> Optional[TraineeProgram]:
    return await db.scalar(
        select(TraineeProgram).where(TraineeProgram.user_id == user_id)
    )


def program_view(program: TraineeProgram, *, today: date) -> dict[str, Any]:
    total = program.total_workdays
    end = rules_mod.program_end_date(program.start_date, total)
    day = min(rules_mod.workdays_between(program.start_date, today), total)
    left = rules_mod.workdays_left(today, end) if today <= end else 0
    return {
        "start_date": program.start_date.isoformat(),
        "workdays": program.workdays,
        "extended_days": program.extended_days,
        "daily_list_size": program.daily_list_size,
        "status": program.status,
        "day": day,
        "total_days": total,
        "end_date": end.isoformat(),
        "days_left": left,
        "decision_due": program.status == "active" and left < DECISION_NOTICE_WORKDAYS,
        "decision": program.decision,
        "decided_at": program.decided_at.isoformat() if program.decided_at else None,
    }


async def start_program(
    db: AsyncSession, user_id: int, *, today: Optional[date] = None
) -> TraineeProgram:
    """Program przy nadaniu roli praktykanta (idempotentnie; ponowne nadanie
    zakończonego programu zaczyna go od nowa)."""
    today = today or business_today()
    start = rules_mod.next_workday(today)
    program = await program_for(db, user_id)
    if program is None:
        # Dwa równoległe pierwsze GET-y konta bez programu (rola z AAD) — drugi
        # czeka na unikalności i nic nie wstawia, zamiast kończyć się 500.
        await db.execute(
            pg_insert(TraineeProgram)
            .values(user_id=user_id, start_date=start)
            .on_conflict_do_nothing(index_elements=[TraineeProgram.user_id])
        )
        return await program_for(db, user_id)
    if program.status != "active":
        program.start_date = start
        program.extended_days = 0
        program.status = "active"
        program.decision = None
        program.decided_at = None
        program.decided_by_user_id = None
        program.decision_notified_at = None
    await db.flush()
    return program


async def close_program_on_role_change(
    db: AsyncSession, user_id: int, *, actor_id: Optional[int]
) -> None:
    """Rola zmieniona z praktykanta poza panelem → program zakończony awansem."""
    program = await program_for(db, user_id)
    if program is None or program.status != "active":
        return
    program.status = "completed"
    program.decision = "promoted"
    program.decided_at = _now()
    program.decided_by_user_id = actor_id


async def sync_program_for_roles(
    db: AsyncSession,
    user_id: int,
    *,
    before: list[str],
    after: list[str],
    actor_id: Optional[int],
) -> None:
    trainee = UserRole.trainee.value
    if trainee in after and trainee not in before:
        await start_program(db, user_id)
    elif trainee in before and trainee not in after:
        await close_program_on_role_change(db, user_id, actor_id=actor_id)


# ── Dzień praktykanta ─────────────────────────────────────────────────────


def _first_experience(candidate: Candidate) -> dict[str, Any]:
    experience = candidate.experience
    if isinstance(experience, list):
        for entry in experience:
            if isinstance(entry, dict):
                return entry
    return {}


def _facts(candidate: Candidate) -> dict[str, Any]:
    prefs = candidate.preferences if isinstance(candidate.preferences, dict) else {}
    availability = candidate.availability_status
    return {
        "min_rate_hourly": float(candidate.expected_rate_hourly)
        if candidate.expected_rate_hourly is not None
        else None,
        "rate_updated_at": candidate.profile_rate_updated_at.isoformat()
        if candidate.profile_rate_updated_at
        else None,
        "b2b_willingness": candidate.b2b_willingness,
        "accepts_below_min_rate": candidate.accepts_below_min_rate,
        "remote_modes": list(prefs.get("remote_modes") or []),
        "max_onsite_days": candidate.max_onsite_days_per_week,
        "accepts_more_office_days": candidate.accepts_more_office_days,
        "office_cities": list(prefs.get("office_cities") or []),
        "work_time_preference": candidate.work_time_preference,
        "availability_status": availability.value if availability else None,
        "availability_date": candidate.availability_date.isoformat()
        if candidate.availability_date
        else None,
    }


def item_row(item: TraineeCallItem, candidate: Candidate) -> dict[str, Any]:
    first = _first_experience(candidate)
    name = " ".join(p for p in (candidate.name, candidate.lastname) if p).strip()
    reasons = dict(item.reasons or {})
    reasons.pop("job_ids", None)
    return {
        "id": item.id,
        "candidate_id": candidate.id,
        "position": item.position,
        "name": name or f"Kandydat #{candidate.id}",
        "role": first.get("role")
        or first.get("title")
        or candidate.linkedin_current_title,
        "company": first.get("company") or candidate.linkedin_current_company,
        "city": candidate.city or candidate.location,
        "phone": candidate.phone,
        "in_base_since": candidate.created_at.year if candidate.created_at else None,
        "last_contact_at": candidate.last_contacted_at.isoformat()
        if candidate.last_contacted_at
        else None,
        "attempts": item.attempts,
        "retry_after": item.retry_after.isoformat() if item.retry_after else None,
        "outcome": item.outcome,
        "closed_at": item.closed_at.isoformat() if item.closed_at else None,
        "later_date": item.later_date.isoformat() if item.later_date else None,
        "reasons": reasons,
        "facts": _facts(candidate),
    }


def _sort_key(item: TraineeCallItem, now: datetime) -> tuple:
    if item.outcome is not None:
        return (2, -(item.closed_at.timestamp() if item.closed_at else 0), item.id)
    if item.retry_after is not None and item.retry_after > now:
        return (1, item.retry_after.timestamp(), item.position)
    return (0, item.position, item.id)


def _counts(items: list[TraineeCallItem]) -> dict[str, int]:
    counts = {
        "total": len(items),
        "closed": 0,
        "open": 0,
        "call": 0,
        "noanswer": 0,
        "later": 0,
        "wrong": 0,
        "declined": 0,
    }
    for item in items:
        if item.outcome is None:
            counts["open"] += 1
        else:
            counts["closed"] += 1
            counts[item.outcome] += 1
    return counts


async def _answered(db: AsyncSession, user_id: Optional[int]) -> Optional[float]:
    connected = func.count().filter(
        TraineeCallItem.outcome.in_(("call", "declined", "later"))
    )
    missed = func.count().filter(TraineeCallItem.outcome == "noanswer")
    stmt = select(connected, missed)
    if user_id is not None:
        stmt = stmt.where(TraineeCallItem.user_id == user_id)
    else:
        stmt = stmt.where(
            TraineeCallItem.list_date >= business_today() - timedelta(days=30)
        )
    row = (await db.execute(stmt)).one()
    return rules_mod.answered_pct(int(row[0] or 0), int(row[1] or 0))


async def today_view(
    db: AsyncSession, user: User, *, read_only: bool = False
) -> dict[str, Any]:
    """Dzień praktykanta. ``read_only`` (admin w „podglądzie jako”) niczego nie
    zapisuje: nie zakłada programu ani listy — podgląd nie może zjadać
    kandydatów z puli ani uruchamiać programu za praktykanta."""
    today = business_today()
    program = await program_for(db, user.id)
    base: dict[str, Any] = {
        "list_date": today.isoformat(),
        "program": None,
        "counts": _counts([]),
        "day_completed": False,
        "answered_pct": None,
        "team_answered_pct": None,
        "items": [],
    }
    if program is None:
        if read_only:
            return {**base, "status": "no_program"}
        # Rola nadana poza panelem admina (np. grupa AAD przy logowaniu SSO).
        program = await start_program(db, user.id, today=today)
        await db.commit()
    view = program_view(program, today=today)
    base["program"] = {
        "day": view["day"],
        "total_days": view["total_days"],
        "status": program.status,
    }
    if program.status != "active":
        return {**base, "status": "program_finished"}
    call_list = await lists.list_for(db, user.id, today)
    if call_list is None or not call_list.size:
        if not rules_mod.is_workday(today) or program.start_date > today:
            return {**base, "status": "not_workday"}
        if read_only:
            if call_list is None:
                return {**base, "status": "preview_not_generated"}
        else:
            # Pusta lista nie jest ostateczna — próbujemy ją uzupełnić.
            call_list = await lists.ensure_list(db, program, today=today)
        if call_list is None:
            return {**base, "status": "not_workday"}
    rows = (
        await db.execute(
            select(TraineeCallItem, Candidate)
            .join(Candidate, Candidate.id == TraineeCallItem.candidate_id)
            .where(TraineeCallItem.list_id == call_list.id)
        )
    ).all()
    now = _now()
    ordered = sorted(rows, key=lambda pair: _sort_key(pair[0], now))
    items = [item for item, _ in ordered]
    counts = _counts(items)
    return {
        **base,
        "status": "ready",
        "counts": counts,
        "day_completed": counts["total"] > 0 and counts["open"] == 0,
        "answered_pct": await _answered(db, user.id),
        "team_answered_pct": await _answered(db, None),
        "items": [item_row(item, cand) for item, cand in ordered],
    }


async def _own_item(
    db: AsyncSession, user: User, item_id: int, *, lock: bool = False
) -> TraineeCallItem:
    stmt = select(TraineeCallItem).where(
        TraineeCallItem.id == item_id, TraineeCallItem.user_id == user.id
    )
    if lock:
        stmt = stmt.with_for_update()
    item = await db.scalar(stmt)
    if item is None:
        raise _http(
            status.HTTP_404_NOT_FOUND, "Nie ma takiej pozycji na Twojej liście."
        )
    return item


def _ensure_open_today(item: TraineeCallItem) -> None:
    if item.outcome is not None:
        raise _http(status.HTTP_409_CONFLICT, "item_closed")
    if item.list_date != business_today():
        raise _http(status.HTTP_409_CONFLICT, "item_expired")


async def _locked_candidate(db: AsyncSession, candidate_id: int) -> Candidate:
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    if candidate is None:
        raise _http(status.HTTP_404_NOT_FOUND, "Kandydat nie istnieje.")
    return candidate


def _add_call(
    db: AsyncSession,
    *,
    candidate: Candidate,
    user: User,
    status_: CallStatus,
    outcome: str,
    summary: str,
    callback_at: Optional[datetime] = None,
) -> Call:
    now = _now()
    call = Call(
        candidate_id=candidate.id,
        user_id=user.id,
        direction=CallDirection.outbound,
        status=status_,
        started_at=now,
        contact_outcome=outcome,
        contact_source=CONTACT_SOURCE,
        callback_at=callback_at,
        summary=summary,
    )
    db.add(call)
    return call


async def _add_note(
    db: AsyncSession,
    *,
    candidate: Candidate,
    user: User,
    item: TraineeCallItem,
    content: str,
) -> Note:
    note = Note(
        content=content,
        note_type=NoteType.call,
        candidate_id=candidate.id,
        author_id=user.id,
        external_source=NOTE_SOURCE,
        external_id=str(item.id),
        source_ref=f"{NOTE_SOURCE}:{item.id}",
    )
    db.add(note)
    candidate.notes_count = (candidate.notes_count or 0) + 1
    await db.flush()
    return note


def _close(item: TraineeCallItem, outcome: str, candidate: Candidate) -> None:
    now = _now()
    item.outcome = outcome
    item.closed_at = now
    item.attempts = (item.attempts or 0) + 1
    item.last_attempt_at = now
    item.retry_after = None
    item.phone_snapshot = candidate.phone


@dataclass(frozen=True)
class CallFacts:
    b2b_willingness: str
    min_rate_value: Any = None
    min_rate_unit: str = "hour"
    accepts_below_min_rate: Optional[bool] = None
    remote_modes: tuple[str, ...] = ()
    max_onsite_days: Optional[int] = None
    accepts_more_office_days: Optional[bool] = None
    office_cities: tuple[str, ...] = ()
    work_time_preference: Optional[str] = None
    availability: Optional[str] = None
    open_to_offers: Optional[str] = None
    wants: Optional[str] = None


def call_note(facts: CallFacts, *, hourly: Any) -> str:
    """Treść notatki z rozmowy — to, co rekruter przeczyta w historii."""
    lines = ["Telefon praktykanta — weryfikacja profilu."]
    lines.append(f"B2B: {_B2B_LABEL.get(facts.b2b_willingness, '—')}.")
    if facts.b2b_willingness == "employment_only":
        lines.append(
            "Nie bierzemy pod uwagę przy rekrutacjach (pracujemy wyłącznie na B2B)."
        )
        return "\n".join(lines)
    if facts.min_rate_value is not None:
        unit = _UNIT_LABEL.get(facts.min_rate_unit, "")
        suffix = f" (= {hourly} zł/h)" if facts.min_rate_unit != "hour" else ""
        lines.append(
            f"Minimalna stawka B2B netto: {facts.min_rate_value} {unit}{suffix}."
        )
    else:
        lines.append("Minimalnej stawki nie podał.")
    if facts.accepts_below_min_rate is not None:
        lines.append(
            "Oferta poniżej minimum: "
            + ("można dzwonić." if facts.accepts_below_min_rate else "nie dzwonić.")
        )
    if facts.remote_modes:
        modes = ", ".join(_MODE_LABEL.get(m, m) for m in facts.remote_modes)
        lines.append(f"Tryb pracy: {modes}.")
    if facts.max_onsite_days is not None:
        lines.append(f"Maks. dni w biurze: {facts.max_onsite_days}.")
    if facts.accepts_more_office_days is not None:
        lines.append(
            "Więcej dni w biurze: "
            + ("można dzwonić." if facts.accepts_more_office_days else "nie dzwonić.")
        )
    if facts.office_cities:
        lines.append("Dojazd: " + ", ".join(facts.office_cities) + ".")
    if facts.work_time_preference:
        lines.append(
            f"Wymiar pracy: {_WORK_TIME_LABEL.get(facts.work_time_preference)}."
        )
    if facts.availability:
        lines.append(f"Może zacząć: {_AVAILABILITY_LABEL.get(facts.availability)}.")
    if facts.open_to_offers:
        lines.append(f"Projekt: {_OPEN_LABEL.get(facts.open_to_offers)}.")
    if facts.wants:
        lines.append(f"Czego szuka: {facts.wants}")
    return "\n".join(lines)


def _apply_facts(candidate: Candidate, facts: CallFacts, user: User) -> dict[str, Any]:
    """Fakty z rozmowy → profil. Zwraca audyt stawki (albo pusty słownik)."""
    from app.services.candidate_notes_facts import (  # noqa: PLC0415
        _set_preference,
        modes_for_office_days,
        set_profile_work_mode,
    )
    from app.services.candidate_profile_rate import write_profile_rate  # noqa: PLC0415

    candidate.b2b_willingness = facts.b2b_willingness
    candidate.call_facts_verified_at = _now()
    candidate.call_facts_verified_by_user_id = user.id
    if facts.b2b_willingness == "employment_only":
        return {}
    rate_audit: dict[str, Any] = {}
    if facts.min_rate_value is not None:
        try:
            hourly = rules_mod.hourly_min_rate(
                facts.min_rate_value, facts.min_rate_unit
            )
        except ValueError as exc:
            raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        rate_audit = write_profile_rate(candidate, hourly, source=NOTE_SOURCE)
        rate_audit.update(
            {
                "rate_meaning": "minimum",
                "entered_value": str(facts.min_rate_value),
                "entered_unit": facts.min_rate_unit,
            }
        )
        current = candidate.cv_extracted_data
        extracted = dict(current) if isinstance(current, dict) else {}
        extracted["_manual_override_rate"] = True
        candidate.cv_extracted_data = extracted
        flag_modified(candidate, "cv_extracted_data")
    if facts.accepts_below_min_rate is not None:
        candidate.accepts_below_min_rate = facts.accepts_below_min_rate
    if facts.remote_modes or facts.max_onsite_days is not None:
        modes = list(facts.remote_modes) or modes_for_office_days(
            facts.max_onsite_days or 0
        )
        days = facts.max_onsite_days
        if days is None:
            days = candidate.max_onsite_days_per_week
        set_profile_work_mode(candidate, modes=modes, max_onsite_days=days)
    if facts.accepts_more_office_days is not None:
        candidate.accepts_more_office_days = facts.accepts_more_office_days
    if facts.office_cities:
        _set_preference(candidate, "office_cities", list(facts.office_cities)[:10])
    if facts.work_time_preference is not None:
        candidate.work_time_preference = facts.work_time_preference
    if facts.availability in AVAILABILITY_DAYS:
        candidate.availability_date = business_today() + timedelta(
            days=AVAILABILITY_DAYS[facts.availability]
        )
    if facts.open_to_offers in OPEN_TO_STATUS:
        candidate.availability_status = OPEN_TO_STATUS[facts.open_to_offers]
    return rate_audit


async def save_call(
    db: AsyncSession, user: User, item_id: int, facts: CallFacts
) -> dict[str, Any]:
    from app.services import candidate_audit  # noqa: PLC0415
    from app.services.match_score_cache import mark_stale_for_candidate  # noqa: PLC0415

    item = await _own_item(db, user, item_id, lock=True)
    _ensure_open_today(item)
    candidate = await _locked_candidate(db, item.candidate_id)
    rate_audit = _apply_facts(candidate, facts, user)
    hourly = rate_audit.get("new_amount")
    note = await _add_note(
        db,
        candidate=candidate,
        user=user,
        item=item,
        content=call_note(facts, hourly=hourly),
    )
    call = _add_call(
        db,
        candidate=candidate,
        user=user,
        status_=CallStatus.completed,
        outcome="connected",
        summary="Weryfikacja profilu przez praktykanta",
    )
    await db.flush()
    candidate.last_contacted_at = _now()
    _close(item, "call", candidate)
    item.call_id = call.id
    item.note_id = note.id
    if rate_audit:
        candidate_audit.record_candidate_audit(
            db,
            action=candidate_audit.PROFILE_RATE_CHANGED,
            user_id=user.id,
            entity_id=candidate.id,
            details=rate_audit,
        )
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.TRAINEE_CALL_SAVED,
        user_id=user.id,
        entity_id=candidate.id,
        details={
            "item_id": item.id,
            "b2b_willingness": facts.b2b_willingness,
            "accepts_below_min_rate": facts.accepts_below_min_rate,
            "accepts_more_office_days": facts.accepts_more_office_days,
            "work_time_preference": facts.work_time_preference,
            "rate_changed": bool(rate_audit),
        },
    )
    await mark_stale_for_candidate(db, candidate.id)
    await db.commit()
    return await _item_response(db, item)


async def _item_response(db: AsyncSession, item: TraineeCallItem) -> dict[str, Any]:
    candidate = await db.get(Candidate, item.candidate_id)
    open_left = await db.scalar(
        select(func.count()).where(
            TraineeCallItem.list_id == item.list_id,
            TraineeCallItem.outcome.is_(None),
        )
    )
    return {"item": item_row(item, candidate), "day_completed": not open_left}


OUTCOMES = ("noanswer", "later", "wrong", "declined")


async def record_outcome(
    db: AsyncSession,
    user: User,
    item_id: int,
    outcome: str,
    later_date: Optional[date],
) -> dict[str, Any]:
    if outcome not in OUTCOMES:
        raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nieznany wynik telefonu.")
    item = await _own_item(db, user, item_id, lock=True)
    _ensure_open_today(item)
    candidate = await _locked_candidate(db, item.candidate_id)
    now = _now()
    if outcome == "noanswer":
        call = _add_call(
            db,
            candidate=candidate,
            user=user,
            status_=CallStatus.missed,
            outcome="no_answer",
            summary="Praktykant: nie odbiera",
        )
        await db.flush()
        item.call_id = call.id
        if (item.attempts or 0) >= 1:
            _close(item, "noanswer", candidate)
        else:
            item.attempts = 1
            item.last_attempt_at = now
            item.retry_after = now + rules_mod.RETRY_AFTER
    elif outcome == "later":
        today = business_today()
        if later_date is None or later_date <= today:
            raise _http(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Wybierz dzień po dzisiejszym.",
            )
        if not rules_mod.is_workday(later_date):
            raise _http(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Wybierz dzień roboczy.",
            )
        call = _add_call(
            db,
            candidate=candidate,
            user=user,
            status_=CallStatus.completed,
            outcome="callback_requested",
            summary=f"Praktykant: prosi o telefon {later_date.isoformat()}",
            callback_at=datetime(
                later_date.year,
                later_date.month,
                later_date.day,
                9,
                tzinfo=ZoneInfo(settings.BUSINESS_TZ),
            ),
        )
        await db.flush()
        item.call_id = call.id
        candidate.last_contacted_at = now
        _close(item, "later", candidate)
        item.later_date = later_date
    elif outcome == "wrong":
        call = _add_call(
            db,
            candidate=candidate,
            user=user,
            status_=CallStatus.failed,
            outcome="wrong_number",
            summary="Praktykant: zły numer",
        )
        await db.flush()
        item.call_id = call.id
        _close(item, "wrong", candidate)
    else:
        call = _add_call(
            db,
            candidate=candidate,
            user=user,
            status_=CallStatus.completed,
            outcome="connected",
            summary="Praktykant: niezainteresowany",
        )
        note = await _add_note(
            db,
            candidate=candidate,
            user=user,
            item=item,
            content=(
                "Telefon praktykanta: kandydat niezainteresowany. "
                "Praktykanci nie dzwonią do niego ponownie."
            ),
        )
        await db.flush()
        item.call_id = call.id
        item.note_id = note.id
        candidate.last_contacted_at = now
        _close(item, "declined", candidate)
    await db.commit()
    return await _item_response(db, item)


# ── Przekazanie rekruterowi ───────────────────────────────────────────────


def _ensure_handover_allowed(item: TraineeCallItem) -> None:
    """Przekazać rekruterowi można tylko osobę, z którą praktykant DZIŚ
    rozmawiał (wynik „Rozmowa”) — nie „niezainteresowanego” ani zły numer."""
    if item.outcome != "call":
        raise _http(
            status.HTTP_409_CONFLICT,
            "Przekazać rekruterowi możesz tylko osobę, z którą zapisałeś rozmowę.",
        )
    if item.list_date != business_today():
        raise _http(
            status.HTTP_409_CONFLICT,
            "Przekazać rekruterowi możesz tylko osobę z dzisiejszej listy.",
        )


async def open_jobs(db: AsyncSession, user: User, item_id: int) -> list[dict[str, Any]]:
    from app.services.job_similarity import _load_pool  # noqa: PLC0415

    item = await _own_item(db, user, item_id)
    _ensure_handover_allowed(item)
    candidate = await db.get(Candidate, item.candidate_id)
    skills, display = lists._candidate_skills(candidate.skills if candidate else None)
    pool = await _load_pool(db)
    matched: list[tuple[int, list[str]]] = []
    for job in pool.jobs.values():
        if job.status != JobStatus.published.value:
            continue
        demand_job = rules_mod.DemandJob(
            id=job.id,
            skills=job.skills,
            competence_category_id=job.competence_category_id,
            is_open=True,
        )
        if rules_mod.job_fits(
            skills, candidate.competence_category_id if candidate else None, demand_job
        ):
            names = sorted(display.get(s, s) for s in job.skills & skills)
            matched.append((job.id, names))
    if not matched:
        return []
    ids = [job_id for job_id, _ in matched]
    recruiter = User.__table__.alias("recruiter")
    rows = (
        await db.execute(
            select(Job.id, Job.title, recruiter.c.name)
            .outerjoin(recruiter, recruiter.c.id == Job.recruiter_id)
            .where(Job.id.in_(ids), Job.status == JobStatus.published)
        )
    ).all()
    names_by_job = dict(matched)
    out = [
        {
            "job_id": job_id,
            "title": title,
            "recruiter_name": recruiter_name,
            "matched_skills": names_by_job.get(job_id, []),
        }
        for job_id, title, recruiter_name in rows
    ]
    out.sort(key=lambda row: (-len(row["matched_skills"]), row["title"] or ""))
    return out[:20]


async def handover(
    db: AsyncSession, user: User, item_id: int, job_id: int, note: Optional[str]
) -> dict[str, Any]:
    from app.services import candidate_audit  # noqa: PLC0415
    from app.services.job_proposals import upsert_proposals  # noqa: PLC0415

    allowed = {row["job_id"] for row in await open_jobs(db, user, item_id)}
    if job_id not in allowed:
        raise _http(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Tej rekrutacji nie ma na liście pasujących otwartych rekrutacji.",
        )
    item = await _own_item(db, user, item_id)
    statuses = set(
        (
            await db.scalars(
                select(JobProposal.status).where(
                    JobProposal.job_id == job_id,
                    JobProposal.candidate_id == item.candidate_id,
                )
            )
        ).all()
    )
    if "added" in statuses:
        raise _http(
            status.HTTP_409_CONFLICT,
            "Ta osoba jest już dodana do tej rekrutacji.",
        )
    await upsert_proposals(
        db,
        job_id,
        [
            {
                "candidate_id": item.candidate_id,
                "evidence": {"trainee": {"user_id": user.id, "note": note or ""}},
            }
        ],
        source="trainee",
    )
    # Odrzucona wcześniej propozycja tej pary wraca do „Do przejrzenia”:
    # praktykant przynosi świeżą rozmowę. Bez tego `upsert_proposals` zostawiał
    # status „pominięty”, a endpoint zwracał ok bez żadnego skutku.
    reopened = 0
    if "dismissed" in statuses:
        result = await db.execute(
            text(
                """
                UPDATE job_proposals AS p
                SET status = 'proposed',
                    first_seen_at = now(),
                    dismissed_at = NULL,
                    dismissed_by = NULL,
                    dismissed_cv_revision = NULL,
                    evidence = (CASE WHEN jsonb_typeof(p.evidence) = 'object'
                                     THEN p.evidence ELSE '{}'::jsonb END)
                               || '{"previously_dismissed": true}'::jsonb
                WHERE p.job_id = :job_id
                  AND p.candidate_id = :candidate_id
                  AND p.status = 'dismissed'
                """
            ),
            {"job_id": job_id, "candidate_id": item.candidate_id},
        )
        reopened = int(result.rowcount or 0)
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.TRAINEE_HANDOVER,
        user_id=user.id,
        entity_id=item.candidate_id,
        details={
            "item_id": item.id,
            "job_id": job_id,
            "reopened_dismissed": bool(reopened),
        },
    )
    await db.commit()
    return {"ok": True, "reopened_dismissed": bool(reopened)}


# ── Panel Head of Recruitment ─────────────────────────────────────────────


async def _trainee_users(db: AsyncSession) -> list[tuple[User, TraineeProgram]]:
    recent = _now() - timedelta(days=30)
    rows = (
        await db.execute(
            select(User, TraineeProgram)
            .join(TraineeProgram, TraineeProgram.user_id == User.id)
            .where(
                or_(
                    TraineeProgram.status == "active",
                    TraineeProgram.decided_at >= recent,
                )
            )
            .order_by(TraineeProgram.start_date, User.name)
        )
    ).all()
    return [(user, program) for user, program in rows]


async def _item_stats(db: AsyncSession, user_ids: list[int], today: date) -> dict:
    if not user_ids:
        return {}
    connected = TraineeCallItem.outcome.in_(("call", "declined", "later"))
    rows = (
        await db.execute(
            select(
                TraineeCallItem.user_id,
                func.count().filter(TraineeCallItem.outcome == "call"),
                func.count().filter(connected),
                func.count().filter(TraineeCallItem.outcome == "noanswer"),
                func.count().filter(TraineeCallItem.quality_verdict.is_not(None)),
                func.count().filter(TraineeCallItem.quality_verdict == "issue"),
            )
            .where(
                TraineeCallItem.user_id.in_(user_ids),
                TraineeCallItem.list_date <= today,
            )
            .group_by(TraineeCallItem.user_id)
        )
    ).all()
    stats = {
        uid: {
            "calls": calls,
            "connected": conn,
            "noanswer": miss,
            "checked": checked,
            "issues": issues,
        }
        for uid, calls, conn, miss, checked, issues in rows
    }
    per_list = (
        await db.execute(
            select(
                TraineeCallList.user_id,
                TraineeCallList.list_date,
                func.count(TraineeCallItem.id),
                func.count(TraineeCallItem.id).filter(
                    TraineeCallItem.outcome.is_(None)
                ),
            )
            .outerjoin(TraineeCallItem, TraineeCallItem.list_id == TraineeCallList.id)
            .where(
                TraineeCallList.user_id.in_(user_ids),
                TraineeCallList.list_date <= today,
            )
            .group_by(TraineeCallList.user_id, TraineeCallList.list_date)
        )
    ).all()
    for uid, list_date, total, open_n in per_list:
        entry = stats.setdefault(uid, {})
        entry["days_with_list"] = entry.get("days_with_list", 0) + 1
        if total and not open_n:
            entry["days_completed"] = entry.get("days_completed", 0) + 1
    complete = (
        await db.execute(
            select(TraineeCallItem.user_id, func.count(func.distinct(Candidate.id)))
            .join(Candidate, Candidate.id == TraineeCallItem.candidate_id)
            .where(
                TraineeCallItem.user_id.in_(user_ids),
                TraineeCallItem.outcome == "call",
                or_(
                    Candidate.b2b_willingness == "employment_only",
                    and_(
                        Candidate.expected_rate_hourly.is_not(None),
                        Candidate.b2b_willingness.is_not(None),
                        Candidate.work_time_preference.is_not(None),
                        Candidate.accepts_below_min_rate.is_not(None),
                        Candidate.accepts_more_office_days.is_not(None),
                    ),
                ),
            )
            .group_by(TraineeCallItem.user_id)
        )
    ).all()
    for uid, count in complete:
        stats.setdefault(uid, {})["complete"] = count
    return stats


async def _handover_stats(
    db: AsyncSession, user_ids: list[int], *, since: Optional[datetime] = None
) -> dict[int, tuple[int, int]]:
    if not user_ids:
        return {}
    by_user = JobProposal.evidence["trainee"]["user_id"].as_integer()
    in_process = or_(
        JobProposal.status == "added",
        select(CandidateStage.id)
        .where(
            CandidateStage.candidate_id == JobProposal.candidate_id,
            CandidateStage.job_id == JobProposal.job_id,
        )
        .exists(),
    )
    stmt = (
        select(
            by_user,
            func.count(),
            func.count().filter(in_process),
        )
        .where(JobProposal.source == "trainee", by_user.in_(user_ids))
        .group_by(by_user)
    )
    if since is not None:
        stmt = stmt.where(JobProposal.first_seen_at >= since)
    return {
        int(uid): (int(total), int(done))
        for uid, total, done in (await db.execute(stmt)).all()
        if uid is not None
    }


def _pct(part: int, whole: int) -> Optional[float]:
    return round(part * 100 / whole, 1) if whole else None


async def overview(db: AsyncSession) -> dict[str, Any]:
    today = business_today()
    pairs = await _trainee_users(db)
    ids = [user.id for user, _ in pairs]
    stats = await _item_stats(db, ids, today)
    handovers = await _handover_stats(db, ids)
    team = await _answered(db, None)
    trainees = []
    for user, program in pairs:
        entry = stats.get(user.id, {})
        days = int(entry.get("days_with_list", 0))
        answered = rules_mod.answered_pct(
            int(entry.get("connected", 0)), int(entry.get("noanswer", 0))
        )
        handed, handed_in = handovers.get(user.id, (0, 0))
        trainees.append(
            {
                "user_id": user.id,
                "name": user.name,
                "is_active": user.is_active,
                "program": program_view(program, today=today),
                "days_with_list": days,
                "days_completed": int(entry.get("days_completed", 0)),
                "calls_per_day": round(entry.get("calls", 0) / days, 1)
                if days
                else None,
                "answered_pct": answered,
                "complete_profiles_pct": _pct(
                    int(entry.get("complete", 0)), int(entry.get("calls", 0))
                ),
                "handed_over": handed,
                "handed_in_process": handed_in,
                "quality": {
                    "checked": int(entry.get("checked", 0)),
                    "issues": int(entry.get("issues", 0)),
                },
                "flag_low_answer": bool(
                    days >= 5
                    and answered is not None
                    and team is not None
                    and answered < team / 2
                ),
            }
        )
    month_start = datetime(
        today.year, today.month, 1, tzinfo=ZoneInfo(settings.BUSINESS_TZ)
    )
    verified = await db.scalar(
        select(func.count(func.distinct(TraineeCallItem.candidate_id)))
        .join(Candidate, Candidate.id == TraineeCallItem.candidate_id)
        .where(
            TraineeCallItem.outcome == "call",
            TraineeCallItem.closed_at >= month_start,
            Candidate.expected_rate_hourly.is_not(None),
        )
    )
    month_handovers = await _handover_stats(
        db,
        [
            uid
            for uid, _ in (
                await db.execute(select(TraineeProgram.user_id, TraineeProgram.id))
            ).all()
        ],
        since=month_start,
    )
    return {
        "trainees": trainees,
        "team_answered_pct": team,
        "pool": await _pool_stats_or_compute(db, today),
        "month": {
            "verified_rates": int(verified or 0),
            "handed_over": sum(total for total, _ in month_handovers.values()),
            "in_process": sum(done for _, done in month_handovers.values()),
        },
    }


async def _pool_stats_or_compute(db: AsyncSession, today: date) -> dict[str, Any]:
    """Statystyki puli z nocnego biegu; bez nich (pierwsze wejście po
    wdrożeniu, zero praktykantów) liczymy raz i zapisujemy."""
    stats = await lists.load_pool_stats(db)
    if stats is None:
        stats = await lists.pool_stats(db, await lists.load_rules(db), today=today)
        await lists.store_pool_stats(db, stats)
        await db.commit()
    return stats


async def _program_or_404(db: AsyncSession, user_id: int) -> TraineeProgram:
    program = await program_for(db, user_id)
    if program is None:
        raise _http(status.HTTP_404_NOT_FOUND, "Ta osoba nie ma programu praktykanta.")
    return program


async def update_program(
    db: AsyncSession,
    user_id: int,
    *,
    start_date: Optional[date],
    workdays: Optional[int],
    daily_list_size: Optional[int],
) -> dict[str, Any]:
    program = await _program_or_404(db, user_id)
    if start_date is not None:
        program.start_date = start_date
    if workdays is not None:
        program.workdays = workdays
    if daily_list_size is not None:
        program.daily_list_size = daily_list_size
    await db.commit()
    return program_view(program, today=business_today())


async def _pin_people(db: AsyncSession, trainee_id: int) -> int:
    """Rozmówcy „szuka / rozważy” → przypięci w „Moich ludziach” awansowanej osoby.

    Pomija osoby, które są już na liście innego rekrutera (wyliczonej albo
    przypiętej) — przejmowanie cudzych relacji to decyzja człowieka.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: PLC0415

    from app.models.my_people import MyPeopleOverride  # noqa: PLC0415
    from app.services.my_people import owners_by_candidate  # noqa: PLC0415

    rows = (
        await db.execute(
            select(func.distinct(TraineeCallItem.candidate_id))
            .join(Candidate, Candidate.id == TraineeCallItem.candidate_id)
            .where(
                TraineeCallItem.user_id == trainee_id,
                TraineeCallItem.outcome == "call",
                Candidate.b2b_willingness.in_(("b2b", "would_switch")),
                Candidate.availability_status.in_(
                    (
                        AvailabilityStatus.actively_looking,
                        AvailabilityStatus.open_to_offers,
                    )
                ),
            )
        )
    ).scalars()
    ids = set(rows.all())
    if not ids:
        return 0
    owners = await owners_by_candidate(db)
    free = sorted(cid for cid in ids if not (owners.get(cid, set()) - {trainee_id}))
    if not free:
        return 0
    await db.execute(
        pg_insert(MyPeopleOverride)
        .values(
            [
                {"user_id": trainee_id, "candidate_id": cid, "kind": "pinned"}
                for cid in free
            ]
        )
        .on_conflict_do_nothing()
    )
    return len(free)


PROMOTE_ROLES = (UserRole.sourcer, UserRole.recruiter)


async def decide(
    db: AsyncSession,
    actor: User,
    user_id: int,
    *,
    action: str,
    role: Optional[str],
    add_to_my_people: bool,
    extend_days: int,
) -> dict[str, Any]:
    program = await _program_or_404(db, user_id)
    target = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None:
        raise _http(status.HTTP_404_NOT_FOUND, "Użytkownik nie istnieje.")
    now = _now()
    result: dict[str, Any] = {"action": action}
    if action == "extend":
        if program.status != "active":
            raise _http(status.HTTP_409_CONFLICT, "Program jest już zakończony.")
        program.extended_days = (program.extended_days or 0) + extend_days
        program.decision = "extended"
        program.decided_at = now
        program.decided_by_user_id = actor.id
        program.decision_notified_at = None
    elif action == "end":
        program.status = "ended"
        program.decision = "ended"
        program.decided_at = now
        program.decided_by_user_id = actor.id
    elif action == "promote":
        try:
            new_role = UserRole(role or "")
        except ValueError as exc:
            raise _http(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Awans tylko na sourcera albo rekrutera.",
            ) from exc
        if new_role not in PROMOTE_ROLES:
            raise _http(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Awans tylko na sourcera albo rekrutera.",
            )
        if {r.value for r in target.get_all_roles()} != {UserRole.trainee.value}:
            raise _http(status.HTTP_409_CONFLICT, "Ta osoba nie jest już praktykantem.")
        original = target.role
        target.role = new_role
        target.roles = [new_role.value]
        target.profile_completed = False
        target.profile_completed_at = None
        target.authorization_version += 1
        target.tokens_valid_after = now
        db.add(
            Activity(
                entity_type="user",
                entity_id=target.id,
                action="role_changed",
                user_id=actor.id,
                details={
                    "from": original.value
                    if hasattr(original, "value")
                    else str(original),
                    "to": new_role.value,
                    "target_email": target.email,
                    "via": "trainee_program",
                },
            )
        )
        program.status = "completed"
        program.decision = "promoted"
        program.decided_at = now
        program.decided_by_user_id = actor.id
        if add_to_my_people:
            result["pinned"] = await _pin_people(db, target.id)
    else:
        raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nieznana decyzja.")
    db.add(
        Activity(
            entity_type="user",
            entity_id=target.id,
            action="trainee_program_decision",
            user_id=actor.id,
            details={
                **result,
                "extend_days": extend_days if action == "extend" else None,
            },
        )
    )
    await db.commit()
    result["program"] = program_view(program, today=business_today())
    return result


# ── Próbka jakości ────────────────────────────────────────────────────────


async def quality_sample(db: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    since = business_today() - timedelta(days=7)
    rows = (
        await db.execute(
            select(TraineeCallItem, Candidate)
            .join(Candidate, Candidate.id == TraineeCallItem.candidate_id)
            .where(
                TraineeCallItem.user_id == user_id,
                TraineeCallItem.outcome == "call",
                TraineeCallItem.list_date >= since,
            )
            .order_by(
                TraineeCallItem.quality_verdict.is_not(None),
                func.md5(func.concat(TraineeCallItem.id, "|", since)),
            )
            .limit(QUALITY_SAMPLE_SIZE)
        )
    ).all()
    out = []
    for item, candidate in rows:
        row = item_row(item, candidate)
        out.append(
            {
                "item_id": item.id,
                "candidate_id": candidate.id,
                "name": row["name"],
                "phone": candidate.phone,
                "called_at": row["closed_at"],
                "facts": row["facts"],
                "verdict": item.quality_verdict,
                "note": item.quality_note,
            }
        )
    return out


async def set_quality(
    db: AsyncSession, actor: User, item_id: int, verdict: str, note: Optional[str]
) -> dict[str, Any]:
    item = await db.scalar(
        select(TraineeCallItem).where(TraineeCallItem.id == item_id).with_for_update()
    )
    if item is None or item.outcome != "call":
        raise _http(status.HTTP_404_NOT_FOUND, "Nie ma takiej rozmowy.")
    item.quality_verdict = verdict
    item.quality_note = (note or "").strip()[:1000] or None
    item.quality_by_user_id = actor.id
    item.quality_at = _now()
    await db.commit()
    return {
        "item_id": item.id,
        "verdict": item.quality_verdict,
        "note": item.quality_note,
    }


# ── Powiadomienie o decyzji ───────────────────────────────────────────────


async def notify_due_decisions(db: AsyncSession, *, today: date) -> int:
    """Raz na program: 5 dni roboczych przed końcem → Head of Recruitment i admin."""
    from app.models.notification import NotificationType  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415

    programs = (
        await db.scalars(
            select(TraineeProgram).where(
                TraineeProgram.status == "active",
                TraineeProgram.decision_notified_at.is_(None),
            )
        )
    ).all()
    recipients = (
        await db.scalars(
            select(User.id).where(
                User.is_active.is_(True),
                or_(
                    User.roles.contains([UserRole.admin.value]),
                    User.roles.contains([UserRole.head_of_recruitment.value]),
                ),
            )
        )
    ).all()
    sent = 0
    for program in programs:
        view = program_view(program, today=today)
        if not view["decision_due"]:
            continue
        trainee = await db.get(User, program.user_id)
        if trainee is None:
            continue
        for recipient in recipients:
            await emit(
                db,
                user_id=recipient,
                ntype=NotificationType.trainee_program_decision,
                title=f"{trainee.name} kończy program praktykanta",
                message=(
                    f"Program kończy się {view['end_date']}. "
                    "Zdecyduj: awans, przedłużenie albo koniec programu."
                ),
                link="/trainees",
                related_entity_type="user",
                related_entity_id=trainee.id,
            )
        program.decision_notified_at = _now()
        sent += 1
    return sent
