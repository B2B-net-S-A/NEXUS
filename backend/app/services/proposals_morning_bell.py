"""Poranny dzwonek „Do przejrzenia” dla zespołu rekrutacji (audyt 06.10.2026, R3).

Do 06.10.2026 propozycje miały dwa sygnały i oba trafiały obok:

* dzienny skrót z nowych CV (``auto_match_service._notify_proposals``) — tylko
  do ``recruiter_id``/``tac_id`` (nie reguła zespołu), z treścią odsyłającą do
  skrzynki „Propozycje”, której na ekranie już nie ma (53 wysłane,
  1 przeczytany);
* nocny przegląd bazy (``full_base``) — żadnego sygnału dla rekrutera.

Teraz JEDEN poranny dzwonek na (rekrutacja, osoba): ile osób z nocnego
przeglądu i z nowych CV czeka od wczoraj w „Do przejrzenia”, z trzema
pierwszymi nazwiskami. Odbiorcy = Rekruterzy rekrutacji (``job_team`` —
prowadzący, aktywne przypisanie, ręczny współpracownik). Uczestnicy kategorii
go nie dostają (D7).

Liczba to te same pary co skrzynka (``job_proposals.fresh_open_pairs``):
bez osób już w rekrutacji, bez czarnej listy, bez pominiętych i dodanych.

Kiedy: dni robocze, 8–17 (Europe/Warsaw), pierwszy tick dnia. Okno propozycji
liczy się od POPRZEDNIEGO dzwonka (``app_settings[STATE_KEY]``), a bez niego
od 8:00 poprzedniego dnia roboczego — stałe 24 h gubiło w poniedziałek
propozycje z weekendu, a po święcie z dnia wolnego. Sufit 7 dni. Stan
``last_sent_on`` przeżywa restart, więc drugi dzwonek tego dnia nie wychodzi.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import is_business_day
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.job import Job, JobStatus
from app.models.notification import NotificationType
from app.services.request_work_state import IN_WORK_STATES

logger = logging.getLogger(__name__)

SOURCES = ("full_base", "new_cv")
FROM_HOUR = 8
UNTIL_HOUR = 17
MAX_WINDOW = timedelta(days=7)
NAMES_IN_MESSAGE = 3
STATE_KEY = "proposals_morning_bell_state"


def window_start(now: datetime, *, last_sent_at: Optional[datetime]) -> datetime:
    """Od kiedy liczą się propozycje tego dzwonka.

    Poprzedni dzwonek, a bez niego 8:00 poprzedniego dnia roboczego (strefa
    ``now``); nigdy dawniej niż ``MAX_WINDOW``.
    """
    floor = now - MAX_WINDOW
    if last_sent_at is not None:
        return max(last_sent_at, floor)
    previous = now - timedelta(days=1)
    for _ in range(6):
        if is_business_day(previous):
            break
        previous -= timedelta(days=1)
    start = datetime.combine(previous.date(), time(FROM_HOUR), tzinfo=now.tzinfo)
    return max(start, floor)


async def _load_state(db: AsyncSession) -> dict[str, Any]:
    row = await db.get(AppSetting, STATE_KEY)
    return dict(row.value or {}) if row is not None else {}


async def _save_state(db: AsyncSession, value: dict[str, Any]) -> None:
    await db.execute(
        pg_insert(AppSetting)
        .values(key=STATE_KEY, value=value)
        .on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": value, "updated_at": datetime.now(timezone.utc)},
        )
    )


def _parse(raw: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None
    if parsed is not None and parsed.tzinfo is None:
        return None
    return parsed


def people_phrase(count: int) -> str:
    """„1 nowa osoba”, „3 nowe osoby”, „12 nowych osób”."""
    if count == 1:
        return "1 nowa osoba"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} nowe osoby"
    return f"{count} nowych osób"


def bell_title(count: int, job_title: str) -> str:
    return f"Do przejrzenia: {people_phrase(count)} — {job_title}"[:255]


def bell_message(names: list[str], count: int) -> str:
    shown = ", ".join(names[:NAMES_IN_MESSAGE])
    rest = count - min(len(names), NAMES_IN_MESSAGE)
    tail = f" i {rest} {'inna' if rest == 1 else 'innych'}" if rest > 0 else ""
    return (
        f"Od wczoraj w „Do przejrzenia”: {shown}{tail}. "
        "Dodaj do „Nowych” albo pomiń z powodem."
    )


async def _plan(db: AsyncSession, since: datetime) -> dict[int, list[int]]:
    """Rekrutacja → kandydaci (najlepszy wynik pierwszy) zaproponowani od ``since``."""
    from app.services.job_proposals import fresh_open_pairs  # noqa: PLC0415

    jobs = select(Job.id).where(
        Job.status == JobStatus.published, Job.work_state.in_(IN_WORK_STATES)
    )
    pairs = await fresh_open_pairs(
        db, since=since, sources=SOURCES, job_ids_subquery=jobs
    )
    plan: dict[int, list[int]] = {}
    for job_id, candidate_id in pairs:
        plan.setdefault(job_id, []).append(candidate_id)
    return plan


async def send_morning_bells(db: AsyncSession, now: datetime) -> int:
    """Wysyła dzwonki (raz dziennie, 8–17). Nie commituje — robi to wołający.

    Błąd jednej rekrutacji (savepoint) nie zatrzymuje pozostałych.
    """
    local = now.astimezone(ZoneInfo(settings.BUSINESS_TZ))
    if not (FROM_HOUR <= local.hour < UNTIL_HOUR) or not is_business_day(local):
        return 0
    from app.services.job_team import recruiters_for_jobs, working  # noqa: PLC0415
    from app.services.job_working_title import (  # noqa: PLC0415
        job_display_title_expr,
    )
    from app.services.notification_triggers import emit  # noqa: PLC0415

    try:
        async with db.begin_nested():
            state = await _load_state(db)
            if state.get("last_sent_on") == local.date().isoformat():
                return 0
            since = window_start(local, last_sent_at=_parse(state.get("last_sent_at")))
            plan = await _plan(db, since)
            # Stan zapisany razem z planem: wywrotka wysyłki w połowie nie
            # powtórzy dzwonków (dedup dobowy i tak by je połknął), a jutrzejsze
            # okno zaczyna się od tej chwili.
            await _save_state(
                db,
                {
                    "last_sent_on": local.date().isoformat(),
                    "last_sent_at": now.astimezone(timezone.utc).isoformat(),
                    "jobs": len(plan),
                },
            )
            if not plan:
                return 0
            titles = dict(
                (
                    await db.execute(
                        select(Job.id, job_display_title_expr()).where(
                            Job.id.in_(sorted(plan))
                        )
                    )
                ).all()
            )
            first = {cid for ids in plan.values() for cid in ids[:NAMES_IN_MESSAGE]}
            names = {
                cid: " ".join(p for p in (name, lastname) if p).strip() or "Kandydat"
                for cid, name, lastname in (
                    await db.execute(
                        select(Candidate.id, Candidate.name, Candidate.lastname).where(
                            Candidate.id.in_(sorted(first))
                        )
                    )
                ).all()
            }
            teams = await recruiters_for_jobs(db, sorted(plan))
    except Exception:  # noqa: BLE001 — dzwonek nigdy nie psuje ticku
        logger.exception("proposals_morning_bell: nie udało się policzyć planu")
        return 0

    sent = 0
    for job_id, candidate_ids in sorted(plan.items()):
        recipients = sorted({p.user_id for p in working(teams.get(job_id, []))})
        if not recipients:
            continue
        title = bell_title(len(candidate_ids), titles.get(job_id) or f"#{job_id}")
        message = bell_message(
            [names[cid] for cid in candidate_ids[:NAMES_IN_MESSAGE] if cid in names],
            len(candidate_ids),
        )
        for user_id in recipients:
            try:
                async with db.begin_nested():
                    created = await emit(
                        db,
                        user_id=user_id,
                        title=title,
                        message=message,
                        ntype=NotificationType.auto_match_proposals,
                        related_entity_type="job",
                        related_entity_id=job_id,
                        link=f"/jobs/{job_id}?tab=similar",
                    )
                sent += int(created is not None)
            except Exception:  # noqa: BLE001 — jeden odbiorca nie blokuje reszty
                logger.exception(
                    "proposals_morning_bell: dzwonek nie wyszedł job=%s", job_id
                )
    return sent


__all__ = [
    "SOURCES",
    "STATE_KEY",
    "window_start",
    "bell_message",
    "bell_title",
    "people_phrase",
    "send_morning_bells",
]
