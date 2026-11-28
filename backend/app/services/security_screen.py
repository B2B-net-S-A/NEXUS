"""Reguły ekranu Ustawienia → Bezpieczeństwo (0800): stan znaleziska, rutyny, przegląd.

Wszystko, co zależy od „dziś”, bierze datę z kalendarza firmy
(``business_today``) albo z parametru — testy nie zależą od zegara.

* Wyjątek ma powód i termin. Po terminie znalezisko liczy się jako otwarte
  od razu przy odczycie (``effective_status``), a pętla przestawia mu status
  i zostawia zdarzenie (``expire_exceptions``) — ekran nie czeka na pętlę.
* Rutyna: termin następnego przebiegu = wykonanie + rytm (tydzień, miesiąc,
  kwartał). Po terminie dzwonek i mail do adminów, raz dziennie.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_today, local_now
from app.models.notification import NotificationType
from app.models.security import (
    SecurityEvent,
    SecurityFinding,
    SecurityRoutine,
    SecuritySourceState,
)
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
SEVERITY_LABEL = {
    "critical": "krytyczna",
    "high": "wysoka",
    "medium": "średnia",
    "low": "niska",
    "info": "informacja",
}
#: Najdłuższy wyjątek — po roku znalezisko i tak trzeba obejrzeć od nowa.
MAX_EXCEPTION_DAYS = 365
ROUTINES_LINK = "/settings?area=sys&item=security&zakladka=rutyny"
ROUTINE_ENTITY = "security_routine"
#: Źródło bez zdarzenia przez tyle godzin nie jest już „na żywo”.
LIVE_HOURS = 24
LOGIN_OK = "login_ok"
LOGIN_DENIED = "login_denied"
BREAK_GLASS_LOGIN = "break_glass_login"
SECURITY_LINK = "/settings?area=sys&item=security"
EVENT_ENTITY = "security_event"
TRAFFIC_KINDS = ("ban", "appsec_block")


def effective_status(finding: SecurityFinding, today: date) -> str:
    """``excepted`` po terminie liczy się jak ``open``."""
    if (
        finding.status == "excepted"
        and finding.exception_until is not None
        and finding.exception_until < today
    ):
        return "open"
    return finding.status


def _waiting_clause(today: date):
    return or_(
        SecurityFinding.status == "open",
        and_(
            SecurityFinding.status == "excepted",
            SecurityFinding.exception_until < today,
        ),
    )


def add_cadence(start: date, cadence: str) -> date:
    if cadence == "week":
        return start + timedelta(days=7)
    months = {"month": 1, "quarter": 3}[cadence]
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def routine_state(routine: SecurityRoutine, today: date) -> str:
    if routine.next_due_on < today:
        return "overdue"
    if routine.next_due_on <= today + timedelta(days=3):
        return "soon"
    return "ok"


def mark_routine_done(
    routine: SecurityRoutine,
    done_on: date,
    *,
    note: Optional[str] = None,
    user_id: Optional[int] = None,
) -> None:
    routine.last_done_on = done_on
    routine.next_due_on = add_cadence(done_on, routine.cadence)
    routine.last_note = note
    routine.updated_by_user_id = user_id
    routine.updated_at = datetime.now(timezone.utc)


# ── Pętla: wyjątki po terminie i rutyny po terminie ─────────────────────────


async def expire_exceptions(db: AsyncSession, today: date) -> int:
    rows = list(
        await db.scalars(
            select(SecurityFinding).where(
                SecurityFinding.status == "excepted",
                SecurityFinding.exception_until < today,
            )
        )
    )
    now = datetime.now(timezone.utc)
    for row in rows:
        row.status = "open"
        row.updated_at = now
        db.add(
            SecurityEvent(
                source="nexus",
                kind="exception_expired",
                severity=row.severity,
                summary=f"Wyjątek minął {row.exception_until:%d.%m}: {row.title}"[:300],
                ref=f"exception_expired:{row.id}:{row.exception_until.isoformat()}",
                occurred_at=now,
            )
        )
    if rows:
        await db.flush()
    return len(rows)


async def _admin_ids(db: AsyncSession) -> list[int]:
    return list(
        await db.scalars(
            select(User.id).where(
                User.is_active.is_(True),
                or_(User.role == UserRole.admin, User.roles.contains(["admin"])),
            )
        )
    )


async def notify_overdue_routines(db: AsyncSession, today: date) -> int:
    """Dzwonek (i mail, kategoria awarii) do każdego admina; dedup dzienny w ``emit``."""
    from app.services.notification_triggers import emit  # noqa: PLC0415 — cykl importów

    overdue = list(
        await db.scalars(
            select(SecurityRoutine)
            .where(SecurityRoutine.next_due_on < today)
            .order_by(SecurityRoutine.position)
        )
    )
    if not overdue:
        return 0
    admins = await _admin_ids(db)
    sent = 0
    for routine in overdue:
        days = (today - routine.next_due_on).days
        title = f"Rutyna bezpieczeństwa po terminie: {routine.title}"[:255]
        message = (
            f"Termin minął {routine.next_due_on:%d.%m.%Y} ({days} dni temu). "
            f"Kto: {routine.owner_label}. Po wykonaniu odhacz ją w Ustawienia → "
            "Bezpieczeństwo → Rutyny."
        )
        for admin_id in admins:
            created = await emit(
                db,
                user_id=admin_id,
                title=title,
                message=message,
                ntype=NotificationType.security_routine_overdue,
                related_entity_type=ROUTINE_ENTITY,
                related_entity_id=routine.id,
                link=ROUTINES_LINK,
            )
            sent += int(created is not None)
    return sent


# ── Logowania (kafelek „Logowania, 24 h”) ───────────────────────────────────


async def record_login(db: AsyncSession, ok: bool, reason: str) -> None:
    """Zdarzenie logowania bez osoby: tylko wynik i kod odmowy.

    Woła je trasa po zakończeniu logowania (sesja trasy jest już po commicie);
    błąd zapisu nie psuje logowania, idzie do logu.
    """
    try:
        db.add(
            SecurityEvent(
                source="nexus",
                kind=LOGIN_OK if ok else LOGIN_DENIED,
                severity="info" if ok else "low",
                summary=(
                    "Logowanie przez Microsoft"
                    if ok
                    else f"Logowanie odrzucone: {reason}"
                )[:300],
                occurred_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    except Exception:  # noqa: BLE001 — logowanie ma przejść mimo braku śladu
        logger.exception("security: login event not recorded")
        await db.rollback()


async def alert_break_glass_login(
    db: AsyncSession, user: User, ip: Optional[str]
) -> int:
    """Logowanie hasłem z listy awaryjnej: zdarzenie na ekranie i dzwonek adminom.

    Decyzja Artura z 27.11.2026: konto awaryjne zostaje (chroni przed awarią
    Microsoftu), ale omija MFA Entra, więc każde logowanie nim widzą wszyscy
    aktywni admini — dzwonek i mail od razu, osobny na każde logowanie
    (encja = zdarzenie, więc dzienny dedup ``emit`` niczego nie skleja).
    Konto „Automatyzacje” (E2E po każdym wdrożeniu i co noc) zostawia samo
    zdarzenie: ma podgląd bez kwot i eksportu, a codzienny mail uczyłby
    ignorować ten alert.

    Zdarzenie bez osoby (``security_events`` nie trzyma danych osobowych);
    imię, adres i IP są tylko w dzwonku dla adminów. Błąd nie psuje logowania:
    savepoint cofa ślad, reszta transakcji trasy idzie dalej, wpis w logu.
    Zwraca liczbę utworzonych dzwonków.
    """
    from app.services.notification_triggers import emit  # noqa: PLC0415 — cykl importów

    # Rola „Automatyzacje” nie łączy się z innymi (ck_users_exclusive_finance_viewer_roles).
    automation = user.has_role(UserRole.automation)
    try:
        async with db.begin_nested():
            event = SecurityEvent(
                source="nexus",
                kind=BREAK_GLASS_LOGIN,
                severity="info" if automation else "high",
                summary=(
                    f"Logowanie hasłem awaryjnym: konto {user.id} ({user.role.value})"
                )[:300],
                occurred_at=datetime.now(timezone.utc),
            )
            db.add(event)
            await db.flush()
            if automation:
                return 0
            title = f"Logowanie hasłem awaryjnym: {user.name or user.email}"[:255]
            message = (
                f"{user.email} zalogował(a) się hasłem z listy awaryjnej "
                f"{local_now():%d.%m.%Y %H:%M}"
                f"{f' z adresu {ip}' if ip else ''} — bez MFA Microsoftu. "
                "Jeśli nikt z Was się nie logował: zablokuj konto (Ustawienia → "
                "Użytkownicy), zmień hasło i działaj według runbooka incydentu."
            )
            sent = 0
            for admin_id in await _admin_ids(db):
                created = await emit(
                    db,
                    user_id=admin_id,
                    title=title,
                    message=message,
                    ntype=NotificationType.break_glass_password_login,
                    related_entity_type=EVENT_ENTITY,
                    related_entity_id=event.id,
                    link=SECURITY_LINK,
                )
                sent += int(created is not None)
            return sent
    except Exception:  # noqa: BLE001 — logowanie ma przejść mimo braku alertu
        logger.exception("security: break-glass login alert failed user_id=%s", user.id)
        return 0


# ── Przegląd ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SourceRow:
    key: str
    name: str
    where: str
    state: str  # ok | live | quiet | failing | unconfigured | due | overdue
    state_label: str
    last_at: Optional[datetime]
    detail: Optional[str] = None
    # Źródło z samą datą (rutyna) — ekran pokazuje dzień bez godziny.
    last_on: Optional[date] = None
    link: Optional[str] = None


def _failed_jobs(detail: dict) -> Optional[str]:
    failed = [
        j.get("name")
        for j in detail.get("jobs") or []
        if j.get("conclusion") not in (None, "success", "skipped")
    ]
    return f"czerwone: {', '.join(failed)}"[:300] if failed else None


def _ago_label(when: datetime, now: datetime) -> str:
    hours = int((now - when).total_seconds() // 3600)
    if hours < 48:
        return f"cisza od {max(hours, 1)} h"
    return f"cisza od {hours // 24} dni"


async def _last_event(db: AsyncSession, source: str) -> Optional[datetime]:
    return await db.scalar(
        select(func.max(SecurityEvent.occurred_at)).where(
            SecurityEvent.source == source
        )
    )


async def build_sources(
    db: AsyncSession, now: datetime, today: date, routines: list[SecurityRoutine]
) -> list[SourceRow]:
    states = {s.source: s for s in await db.scalars(select(SecuritySourceState))}
    rows: list[SourceRow] = []

    ci = states.get("ci")
    detail = (ci.detail or {}) if ci else {}
    conclusion = detail.get("conclusion")
    if ci is None or ci.last_ok_at is None:
        state, label = (
            ("failing", "błąd odczytu")
            if ci and ci.last_error
            else ("unconfigured", "brak danych")
        )
    elif conclusion == "success":
        state, label = "ok", "zielony"
    elif conclusion in ("failure", "timed_out", "startup_failure"):
        state, label = "failing", "czerwony"
    else:
        state, label = "quiet", conclusion or "w toku"
    run_at = detail.get("run_started_at")
    rows.append(
        SourceRow(
            key="ci",
            name="Semgrep, pip-audit, npm audit (security-weekly)",
            where="GitHub Actions",
            state=state,
            state_label=label,
            last_at=datetime.fromisoformat(run_at) if run_at else None,
            detail=(ci.last_error if ci and ci.last_error else _failed_jobs(detail)),
            link=detail.get("html_url"),
        )
    )

    pentest = next((r for r in routines if r.key == "pentest_staging"), None)
    if pentest is not None:
        days = (pentest.next_due_on - today).days
        state = "overdue" if days < 0 else ("due" if days <= 3 else "ok")
        label = f"po terminie {-days} dni" if days < 0 else f"za {days} dni"
        rows.append(
            SourceRow(
                key="pentest",
                name="Pentest stagingu",
                where="sesja Claude, raport prywatny",
                state=state,
                state_label=label,
                last_at=None,
                last_on=pentest.last_done_on,
            )
        )

    for key, name, where in (
        ("crowdsec", "CrowdSec", "serwer NEXUSA"),
        ("falco", "Falco", "serwer NEXUSA"),
        ("wazuh", "Wazuh", "osobny serwer"),
        ("grafana", "Grafana Cloud", "alerty Grafany"),
    ):
        last = await _last_event(db, key)
        if last is None:
            state, label = "unconfigured", "nieskonfigurowane"
        elif now - last <= timedelta(hours=LIVE_HOURS):
            state, label = "live", "na żywo"
        else:
            state, label = "quiet", _ago_label(last, now)
        rows.append(
            SourceRow(
                key=key,
                name=name,
                where=where,
                state=state,
                state_label=label,
                last_at=last,
            )
        )

    # DefectDojo wypycha aktywne znaleziska co 30 min (także pustą paczką).
    dojo = states.get("defectdojo")
    if dojo is None or dojo.last_ok_at is None:
        state, label, last = "unconfigured", "nieskonfigurowane", None
    elif now - dojo.last_ok_at <= timedelta(hours=2):
        state, label, last = "live", "na żywo", dojo.last_ok_at
    else:
        state, label, last = "quiet", _ago_label(dojo.last_ok_at, now), dojo.last_ok_at
    rows.append(
        SourceRow(
            key="defectdojo",
            name="DefectDojo (Semgrep, audyty, zizmor, Trivy)",
            where="serwer bezpieczeństwa",
            state=state,
            state_label=label,
            last_at=last,
        )
    )
    rows.append(defender_source_row(states.get("defender"), now))

    last_login = await db.scalar(
        select(func.max(SecurityEvent.occurred_at)).where(
            SecurityEvent.source == "nexus",
            SecurityEvent.kind.in_((LOGIN_OK, LOGIN_DENIED)),
        )
    )
    rows.append(
        SourceRow(
            key="nexus",
            name="Logowania do NEXUSA",
            where="NEXUS (Microsoft)",
            state="live" if last_login else "quiet",
            state_label="na żywo" if last_login else "brak logowań",
            last_at=last_login,
        )
    )
    return rows


#: NEXUS czyta Defendera co 15 min — po godzinie ciszy źródło nie jest „na żywo”.
DEFENDER_LIVE = timedelta(hours=1)
DEFENDER_PORTAL = "https://security.microsoft.com/incidents"


def defender_source_row(
    state: Optional[SecuritySourceState], now: datetime
) -> SourceRow:
    """Bez rejestracji aplikacji „nieskonfigurowane”, nie błąd."""
    from app.services.m365.defender_auth import credentials_configured  # noqa: PLC0415

    last = state.last_ok_at if state else None
    error = state.last_error if state else None
    if not credentials_configured():
        st, label, detail = "unconfigured", "nieskonfigurowane", None
    elif error:
        st, label, detail = "failing", "błąd odczytu", error
    elif last is None:
        st, label, detail = "unconfigured", "czeka na pierwszy odczyt", None
    elif now - last <= DEFENDER_LIVE:
        st, label, detail = "live", "na żywo", None
    else:
        st, label, detail = "quiet", _ago_label(last, now), None
    return SourceRow(
        key="defender",
        name="Microsoft Defender",
        where="Microsoft Graph, co 15 min",
        state=st,
        state_label=label,
        last_at=last,
        detail=detail,
        link=DEFENDER_PORTAL,
    )


def defender_tile(
    state: Optional[SecuritySourceState], waiting: list[SecurityFinding]
) -> dict:
    """Kafelek: otwarte incydenty (te, które czekają na reakcję) i Secure Score."""
    from app.services.m365.defender_auth import credentials_configured  # noqa: PLC0415

    mine = [f for f in waiting if f.source == "defender"]
    detail = (state.detail or {}) if state else {}
    return {
        "configured": credentials_configured(),
        "connected": bool(state and state.last_ok_at),
        "open": len(mine),
        "urgent": sum(1 for f in mine if f.severity in ("high", "critical")),
        "secure_score": detail.get("secure_score"),
        "secure_score_on": detail.get("secure_score_on"),
    }


def workflow_url() -> str:
    return (
        f"https://github.com/{settings.SECURITY_GITHUB_REPO}/actions/workflows/"
        f"{settings.SECURITY_GITHUB_WORKFLOW}"
    )


async def build_overview(
    db: AsyncSession, *, now: Optional[datetime] = None, today: Optional[date] = None
) -> dict:
    now = now or datetime.now(timezone.utc)
    today = today or business_today()
    day_ago = now - timedelta(hours=24)

    waiting = list(
        await db.scalars(select(SecurityFinding).where(_waiting_clause(today)))
    )
    waiting.sort(key=lambda f: (SEVERITY_RANK.get(f.severity, 9), f.first_seen_at))
    excepted = list(
        await db.scalars(
            select(SecurityFinding)
            .where(
                SecurityFinding.status == "excepted",
                SecurityFinding.exception_until >= today,
            )
            .order_by(SecurityFinding.exception_until)
        )
    )
    recently_closed = list(
        await db.scalars(
            select(SecurityFinding)
            .where(SecurityFinding.status == "fixed")
            .order_by(SecurityFinding.closed_at.desc().nullslast())
            .limit(3)
        )
    )
    by_severity: dict[str, int] = {}
    for f in waiting:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1

    traffic = await db.execute(
        select(func.coalesce(func.sum(SecurityEvent.count), 0), func.count()).where(
            SecurityEvent.source == "crowdsec",
            SecurityEvent.kind.in_(TRAFFIC_KINDS),
            SecurityEvent.occurred_at >= day_ago,
        )
    )
    blocked, blocked_events = traffic.one()
    crowdsec_ever = await _last_event(db, "crowdsec")

    logins = dict(
        (
            await db.execute(
                select(
                    SecurityEvent.kind, func.coalesce(func.sum(SecurityEvent.count), 0)
                )
                .where(
                    SecurityEvent.source == "nexus",
                    SecurityEvent.kind.in_((LOGIN_OK, LOGIN_DENIED)),
                    SecurityEvent.occurred_at >= day_ago,
                )
                .group_by(SecurityEvent.kind)
            )
        ).all()
    )

    ci_state = await db.get(SecuritySourceState, "ci")
    ci_detail = (ci_state.detail or {}) if ci_state else {}
    ci_since = ci_detail.get("run_started_at")
    ci_new = 0
    if ci_since:
        ci_new = int(
            await db.scalar(
                select(func.count()).where(
                    SecurityFinding.source == "ci",
                    SecurityFinding.status != "fixed",
                    SecurityFinding.first_seen_at
                    >= datetime.fromisoformat(ci_since) - timedelta(days=7),
                )
            )
            or 0
        )

    events = list(
        await db.scalars(
            select(SecurityEvent)
            .where(SecurityEvent.kind != LOGIN_OK)
            .order_by(SecurityEvent.occurred_at.desc(), SecurityEvent.id.desc())
            .limit(25)
        )
    )
    routines = list(
        await db.scalars(
            select(SecurityRoutine).order_by(
                SecurityRoutine.position, SecurityRoutine.id
            )
        )
    )
    sources = await build_sources(db, now, today, routines)
    defender_state = await db.get(SecuritySourceState, "defender")
    return {
        "today": today,
        "workflow_url": workflow_url(),
        "tiles": {
            "ci": {
                "new": ci_new,
                "conclusion": ci_detail.get("conclusion"),
                "run_started_at": ci_since,
                "run_url": ci_detail.get("html_url"),
                "configured": bool(ci_state and ci_state.last_ok_at),
            },
            "waiting": {"total": len(waiting), "by_severity": by_severity},
            "traffic": {
                "blocked": int(blocked or 0),
                "events": int(blocked_events or 0),
                "configured": crowdsec_ever is not None,
            },
            "logins": {
                "ok": int(logins.get(LOGIN_OK, 0)),
                "denied": int(logins.get(LOGIN_DENIED, 0)),
            },
            "defender": defender_tile(defender_state, waiting),
        },
        "waiting": waiting,
        "excepted": excepted,
        "recently_closed": recently_closed,
        "events": events,
        "sources": sources,
        "routines_overdue": sum(
            1 for r in routines if routine_state(r, today) == "overdue"
        ),
    }
