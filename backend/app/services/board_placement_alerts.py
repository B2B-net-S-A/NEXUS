"""Mail „Nowy placement” do Rady nadzorczej (decyzja Artura 22.10.2026).

Przy każdym placemencie członkowie Rady dostają krótki mail: klient,
rekrutacja, rekruter, Delivery Lead, start i marża na godzinę, który to
placement w miesiącu i ile akceptacji jeszcze jest w drodze. **Bez danych
kandydata** — Rada nie ma dostępu do kartotek (0490).

* Placement = pierwsze „Zatrudniony” pary (kandydat, rekrutacja) z widoku
  `analytics_first_milestones` (reguła D2, bez wykluczonych placementów), więc
  powrót karty na etap nie wysyła drugiego maila.
* Jeden mail na parę: pętla raportów (`tasks/kpi_email_reports`) zakłada
  znacznik `kpi_email_report_runs` z kluczem ``<kandydat>:<rekrutacja>``.
* Bez historii: mail idzie tylko za placementy po dacie „wysyłaj od” tego
  rodzaju w Ustawieniach → Powiadomienia i nie starsze niż `LOOKBACK`.
* Marża/h — `competition_rules.placement_margin_per_hour_by_user`, ta sama
  funkcja pieniędzy co kafel Rady i remis wyścigu placementów; bez kontraktu
  albo kursu — linii nie ma, zamiast zgadywać.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.contract import Contract, ContractStatus
from app.models.user import User, UserRole

KIND = "board_placement_alert"
# Placement starszy niż tyle nie dostaje maila (np. po dłuższej przerwie poczty).
LOOKBACK = timedelta(days=3)
# Ile placementów jeden tick wysyła najwyżej — reszta czeka na następny.
BATCH = 20

_MONTHS_GENITIVE = (
    "stycznia",
    "lutego",
    "marca",
    "kwietnia",
    "maja",
    "czerwca",
    "lipca",
    "sierpnia",
    "września",
    "października",
    "listopada",
    "grudnia",
)
_MONTHS_LOCATIVE = (
    "styczniu",
    "lutym",
    "marcu",
    "kwietniu",
    "maju",
    "czerwcu",
    "lipcu",
    "sierpniu",
    "wrześniu",
    "październiku",
    "listopadzie",
    "grudniu",
)


def pair_key(candidate_id: int, job_id: int) -> str:
    """Klucz znacznika wysyłki. `kpi_email_report_runs.period_key` ma 16 znaków —
    mieści dwa identyfikatory do 7 cyfr każdy (dziś 5–6)."""
    return f"{candidate_id}:{job_id}"


@dataclass(frozen=True)
class PendingPlacement:
    candidate_id: int
    job_id: int
    reached_at: datetime


@dataclass(frozen=True)
class PlacementFacts:
    client_name: Optional[str]
    job_title: str
    recruiter_name: Optional[str]
    delivery_lead_name: Optional[str]
    reached_on: date
    start_date: Optional[date]
    margin_per_hour: Optional[float]
    month_number: int
    open_acceptances: int
    forecast_low: Optional[int]
    forecast_high: Optional[int]


async def pending_placements(
    db: AsyncSession, *, since: datetime, now: datetime
) -> list[PendingPlacement]:
    """Placementy po `since` (i nie starsze niż `LOOKBACK`) bez wysłanego maila."""

    floor = max(since, now - LOOKBACK)
    rows = (
        await db.execute(
            text(
                """
                SELECT fm.candidate_id, fm.job_id, fm.first_reached_at
                FROM analytics_first_milestones fm
                WHERE fm.stage::text = 'hired'
                  AND fm.first_reached_at >= :floor
                  AND fm.first_reached_at <= :now
                  AND NOT EXISTS (
                    SELECT 1 FROM kpi_email_report_runs r
                    WHERE r.kind = :kind
                      AND r.period_key = fm.candidate_id::text || ':' || fm.job_id::text
                  )
                ORDER BY fm.first_reached_at, fm.candidate_id, fm.job_id
                LIMIT :batch
                """
            ),
            {"floor": floor, "now": now, "kind": KIND, "batch": BATCH},
        )
    ).all()
    return [PendingPlacement(int(c), int(j), at) for c, j, at in rows]


async def _credit_user(
    db: AsyncSession, candidate_id: int, job_id: int
) -> Optional[int]:
    """Komu zalicza się placement — ta sama zasługa co wyścigi i „Mój miesiąc”."""
    from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

    return await db.scalar(
        text(
            VERIFIER_ANCHORED_CTE
            + """
            SELECT c.credit_user FROM credited c
            WHERE c.stage = 'hired'
              AND c.candidate_id = :cand
              AND c.job_id = :job
            ORDER BY c.reached_at
            LIMIT 1
            """
        ),
        {"cand": candidate_id, "job": job_id},
    )


async def _margin_per_hour(
    db: AsyncSession, *, credit_user: Optional[int], placement: PendingPlacement
) -> Optional[float]:
    from app.services.competition_rules import placement_margin_per_hour_by_user

    if credit_user is None:
        return None
    tz = ZoneInfo(DEFAULT_TZ)
    day = placement.reached_at.astimezone(tz).date()
    start = datetime.combine(day, time.min, tzinfo=tz)
    by_user = await placement_margin_per_hour_by_user(
        db, user_ids=[credit_user], start=start, end=start + timedelta(days=1)
    )
    for entry in by_user.get(credit_user, {}).get("placements", []):
        if (
            entry["candidate_id"] == placement.candidate_id
            and entry["job_id"] == placement.job_id
        ):
            return entry["margin_per_hour"]
    return None


async def placement_facts(
    db: AsyncSession, placement: PendingPlacement, *, today: date, now: datetime
) -> PlacementFacts:
    from app.services.insights_in_flight import compute_in_flight

    tz = ZoneInfo(DEFAULT_TZ)
    job = (
        (
            await db.execute(
                text(
                    """
                SELECT j.title,
                       COALESCE(NULLIF(cl.display_name, ''), cl.name) AS client_name,
                       dl.name AS dl_name, j.client_id
                FROM jobs j
                LEFT JOIN clients cl ON cl.id = j.client_id
                LEFT JOIN users dl ON dl.id = j.delivery_lead_id
                WHERE j.id = :job
                """
                ),
                {"job": placement.job_id},
            )
        )
        .mappings()
        .one()
    )
    credit_user = await _credit_user(db, placement.candidate_id, placement.job_id)
    recruiter_name = (
        await db.scalar(select(User.name).where(User.id == credit_user))
        if credit_user is not None
        else None
    )
    start_date = await db.scalar(
        select(Contract.start_date)
        .where(
            Contract.candidate_id == placement.candidate_id,
            Contract.status != ContractStatus.void,
            (Contract.job_id == placement.job_id)
            | (Contract.client_id == job["client_id"]),
        )
        .order_by((Contract.job_id == placement.job_id).desc(), Contract.id.desc())
        .limit(1)
    )
    reached_local = placement.reached_at.astimezone(tz)
    month_start = datetime.combine(
        reached_local.date().replace(day=1), time.min, tzinfo=tz
    )
    month_number = int(
        await db.scalar(
            text(
                """
                SELECT count(*) FROM analytics_kpi_milestones fm
                WHERE fm.stage::text = 'hired'
                  AND fm.first_reached_at >= :start
                  AND fm.first_reached_at <= :at
                """
            ),
            {"start": month_start, "at": placement.reached_at},
        )
        or 0
    )
    in_flight = await compute_in_flight(
        db, today=today, now=now, with_acceptances=False
    )
    forecast = in_flight["forecast"]
    return PlacementFacts(
        client_name=job["client_name"],
        job_title=job["title"],
        recruiter_name=recruiter_name,
        delivery_lead_name=job["dl_name"],
        reached_on=reached_local.date(),
        start_date=start_date,
        margin_per_hour=await _margin_per_hour(
            db, credit_user=credit_user, placement=placement
        ),
        month_number=max(month_number, 1),
        open_acceptances=int(forecast["open"]),
        forecast_low=forecast["low"],
        forecast_high=forecast["high"],
    )


def _day(d: date) -> str:
    return f"{d.day} {_MONTHS_GENITIVE[d.month - 1]} {d.year}"


def _pln(value: float) -> str:
    whole, frac = f"{value:,.2f}".split(".")
    return f"{whole.replace(',', ' ')},{frac} zł"


def _acceptances(n: int) -> str:
    if n == 1:
        return "1 akceptacja"
    last, last_two = n % 10, n % 100
    if 2 <= last <= 4 and not 12 <= last_two <= 14:
        return f"{n} akceptacje"
    return f"{n} akceptacji"


def render_placement_alert(facts: PlacementFacts, link: str) -> tuple[str, str]:
    """Temat i treść maila (czysta funkcja — test bez bazy). Bez kandydata."""

    client = facts.client_name or "klient bez nazwy"
    subject = f"Nowy placement: {client} · {facts.job_title}"
    lines = [
        f"Nowy placement — {_day(facts.reached_on)}.",
        "",
        f"Klient: {client}",
        f"Rekrutacja: {facts.job_title}",
        f"Rekruter: {facts.recruiter_name or '—'}",
        f"Delivery Lead: {facts.delivery_lead_name or '—'}",
        f"Start: {_day(facts.start_date) if facts.start_date else 'do ustalenia'}",
    ]
    if facts.margin_per_hour is not None:
        lines.append(f"Marża na godzinę: {_pln(facts.margin_per_hour)}")
    lines += [
        "",
        f"To {facts.month_number}. placement w {_MONTHS_LOCATIVE[facts.reached_on.month - 1]}.",
    ]
    if facts.open_acceptances > 0:
        tail = ""
        if facts.forecast_low is not None and facts.forecast_high is not None:
            span = (
                str(facts.forecast_low)
                if facts.forecast_low == facts.forecast_high
                else f"{facts.forecast_low}–{facts.forecast_high}"
            )
            tail = (
                f" — przy dotychczasowej skuteczności ok. {span} kolejnych placementów"
            )
        lines.append(
            f"W drodze: {_acceptances(facts.open_acceptances)} do domknięcia{tail}."
        )
    lines += [
        "",
        f"Insights → Firma: {link}",
        "",
        "— Nexus ATS. Bez danych kandydata. Wyłączysz ten mail w Ustawieniach → Maile do Ciebie.",
    ]
    return subject, "\n".join(lines)


async def board_members(db: AsyncSession) -> list[User]:
    """Aktywne konta Rady nadzorczej z adresem (rola główna albo dodatkowa)."""
    users = (
        (
            await db.execute(
                select(User)
                .where(User.is_active.is_(True), User.email.is_not(None))
                .order_by(User.id)
            )
        )
        .scalars()
        .all()
    )
    return [u for u in users if u.has_role(UserRole.board)]
