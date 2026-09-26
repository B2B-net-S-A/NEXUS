"""Raporty KPI mailem (plan PR3, 23.09.2026).

Dwa rodzaje, oba w `notification_delivery.CATALOG` i domyślnie WYŁĄCZONE
(poczta M365 aplikacji ma dziś 403 — włączenie to decyzja admina
w Ustawieniach → Powiadomienia):

* ``kpi_weekly_report`` — **poniedziałek od 8:00** (`BUSINESS_TZ`): KPI zespołu
  za zamknięty tydzień ISO do Head of Recruitment (rola główna ALBO
  dodatkowa). Zespół = zakres pulpitu odbiorcy (`resolve_dashboard_scope`),
  liczony `metrics.team_kpis(..., operational_roles_only=False)` — roster jest
  ustalony po WSZYSTKICH rolach, filtr głównej roli wyciąłby np. TCM
  z dodatkową rolą recruiter (reaudyt 14.09, R01).
* ``board_monthly_report`` — **1. dzień roboczy miesiąca od 8:00**:
  podsumowanie Rady za zamknięty miesiąc (`insights_board.compute_board`
  + tabela rok-do-roku) do admina i Finansów (= `BoardReader`; Head of
  Recruitment nie dostaje kwot od 24.09.2026).

Bez duplikatu po restarcie: przed wysyłką pętla ZAKŁADA wiersz
`kpi_email_report_runs` (UNIQUE kind+period_key). Deploy w trakcie wysyłki
zostawia wiersz `claimed` — raport przepada zamiast wyjść drugi raz.
Wyłączony rodzaj niczego nie zakłada, więc włączenie go tego samego dnia
wyśle raport przy następnym ticku. `send_email` jest synchroniczne →
`asyncio.to_thread(guarded_send, ...)`; `guarded_send` sprawdza politykę
jeszcze raz tuż przed wysyłką.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import DEFAULT_TZ, is_business_day, local_now
from app.models.app_setting import AppSetting
from app.models.kpi_email_report_run import KpiEmailReportRun
from app.models.user import User, UserRole
from app.services import loop_heartbeat
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)

logger = logging.getLogger(__name__)

WEEKLY_KIND = "kpi_weekly_report"
MONTHLY_KIND = "board_monthly_report"
SEND_HOUR = 8
CHECK_INTERVAL_SECONDS = 600

# Bez Head of Recruitment (decyzja Artura 24.09.2026): mail niesie przychód
# i marżę, a HoR nie widzi pieniędzy — lustro `BoardReader`.
_BOARD_ROLES = (UserRole.admin, UserRole.finance)
_MONTHS_PL = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)


# ── Kiedy raport jest należny ────────────────────────────────────────────────


def weekly_period_key(now_local: datetime) -> Optional[str]:
    """Klucz ZAMKNIĘTEGO tygodnia ISO, gdy dziś poniedziałek po 8:00."""
    if now_local.weekday() != 0 or now_local.hour < SEND_HOUR:
        return None
    reported = now_local.date() - timedelta(days=7)
    year, week, _ = reported.isocalendar()
    return f"{year}-W{week:02d}"


def first_business_day(year: int, month: int, tz: str = DEFAULT_TZ) -> date:
    day = date(year, month, 1)
    while not is_business_day(datetime.combine(day, time(12), tzinfo=ZoneInfo(tz))):
        day += timedelta(days=1)
    return day


def monthly_period_key(now_local: datetime) -> Optional[str]:
    """Klucz ZAMKNIĘTEGO miesiąca, gdy dziś 1. dzień roboczy miesiąca po 8:00."""
    today = now_local.date()
    if now_local.hour < SEND_HOUR:
        return None
    if today != first_business_day(today.year, today.month):
        return None
    previous = today.replace(day=1) - timedelta(days=1)
    return f"{previous.year}-{previous.month:02d}"


# ── Treść ────────────────────────────────────────────────────────────────────


def _link(path: str) -> str:
    base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    return f"{base}{path}" if base else path


def render_weekly(team: dict, period_label: str) -> tuple[str, str]:
    """Treść raportu tygodniowego (czysta funkcja — test bez bazy)."""
    totals = team.get("totals") or {}
    lines = [
        f"KPI zespołu za tydzień {period_label}.",
        "",
        "Razem:",
        f"  Weryfikacje: {totals.get('first_verifications', 0)}",
        f"  Rekomendacje (CV wysłane): {totals.get('first_recommendations', 0)}",
        f"  Placementy: {totals.get('first_placements', 0)}",
        f"  Nowi kandydaci: {totals.get('candidates_added', 0)}",
        "",
        "Per osoba (weryfikacje / rekomendacje / placementy / nowi kandydaci):",
    ]
    rows = team.get("rows") or []
    if not rows:
        lines.append("  Brak osób w zespole w tym tygodniu.")
    for row in rows:
        lines.append(
            f"  {row.get('user_name') or '—'}: "
            f"{row.get('first_verifications', 0)} / "
            f"{row.get('first_recommendations', 0)} / "
            f"{row.get('first_placements', 0)} / "
            f"{row.get('candidates_added', 0)}"
        )
    lines += [
        "",
        f"Szczegóły: {_link('/insights?tab=zespol')}",
        "",
        "— Nexus ATS (raport automatyczny; wyłączysz go w Ustawieniach → Powiadomienia)",
    ]
    return f"KPI zespołu — tydzień {period_label}", "\n".join(lines)


def _fmt(value, unit: Optional[str]) -> str:
    if value is None:
        return "—"
    if unit == "pln":
        return f"{float(value):,.0f} zł".replace(",", " ")
    if unit in ("pct", "percent"):
        return f"{float(value):.1f}%"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def render_board(
    board: dict, yoy: Optional[dict], year: int, month: int
) -> tuple[str, str]:
    """Treść miesięcznego podsumowania Rady (czysta funkcja)."""
    label = f"{_MONTHS_PL[month - 1]} {year}"
    kpis = board.get("kpis") or {}
    fin = kpis.get("finance") or {}
    lines = [
        f"Podsumowanie Rady za {label}.",
        "",
        f"Placementy: {kpis.get('placements', 0)}",
        f"Weryfikacje: {kpis.get('verified', 0)} · CV wysłane: {kpis.get('cv_sent', 0)}",
        f"Hit ratio (rekrutacje zamknięte z placementem): "
        f"{_fmt(kpis.get('hit_ratio_pct'), 'pct')}",
        f"Przychód / mc: {_fmt(fin.get('revenue_monthly_pln'), 'pln')}",
        f"Marża / mc: {_fmt(fin.get('margin_monthly_pln'), 'pln')}",
        f"Aktywni konsultanci: {fin.get('active_consultants', 0)}",
    ]
    degraded = board.get("degraded") or {}
    if degraded.get("message"):
        lines += ["", f"Uwaga: {degraded['message']}"]
    if yoy and yoy.get("metrics"):
        prev_year = str(year - 1)
        lines += ["", f"Rok do roku ({label} vs {_MONTHS_PL[month - 1]} {prev_year}):"]
        for metric in yoy["metrics"]:
            series = metric.get("series") or {}
            now_v = (series.get(str(year)) or [None] * 12)[month - 1]
            prev_v = (series.get(prev_year) or [None] * 12)[month - 1]
            unit = metric.get("unit")
            lines.append(
                f"  {metric.get('label')}: {_fmt(now_v, unit)} "
                f"(rok wcześniej {_fmt(prev_v, unit)})"
            )
        lines.append(
            "  Kwoty z kontraktów: ewidencja kontraktów jest młodsza niż firma — "
            "porównania pieniędzy sprzed jej pełnego pokrycia są zaniżone."
        )
    lines += [
        "",
        f"Szczegóły: {_link('/insights?tab=firma')}",
        "",
        "— Nexus ATS (raport automatyczny; wyłączysz go w Ustawieniach → Powiadomienia)",
    ]
    return f"Podsumowanie Rady — {label}", "\n".join(lines)


# ── Odbiorcy, znacznik i wysyłka ─────────────────────────────────────────────


def _has_any_role(roles: tuple[UserRole, ...]):
    return or_(User.role.in_(roles), *(User.roles.contains([r.value]) for r in roles))


async def _recipients(db: AsyncSession, roles: tuple[UserRole, ...]) -> list[User]:
    """Aktywne osoby z rolą (główną albo dodatkową) i odczytem sekcji Insights.

    Sekcja jest sprawdzana, bo raport niesie te same liczby co ekran —
    konto, któremu admin odebrał Insights, nie może dostać ich mailem.
    """
    users = (
        (
            await db.execute(
                select(User)
                .where(
                    User.is_active.is_(True),
                    User.email.is_not(None),
                    _has_any_role(roles),
                )
                .order_by(User.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        u
        for u in users
        if section_access_for_user(u, ProductSection.insights) >= SectionAccess.read
    ]


async def claim_report(db: AsyncSession, kind: str, period_key: str) -> Optional[int]:
    """Załóż znacznik raportu; `None` = inny kontener albo wcześniejszy bieg już go ma."""
    run_id = await db.scalar(
        pg_insert(KpiEmailReportRun)
        .values(kind=kind, period_key=period_key, status="claimed")
        .on_conflict_do_nothing(constraint="uq_kpi_email_report_runs")
        .returning(KpiEmailReportRun.id)
    )
    await db.commit()
    return run_id


async def _finish(
    db: AsyncSession, run_id: int, *, status: str, recipients: int, sent: int
) -> None:
    await db.execute(
        update(KpiEmailReportRun)
        .where(KpiEmailReportRun.id == run_id)
        .values(
            status=status,
            recipients=recipients,
            sent=sent,
            finished_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()


@dataclass(frozen=True)
class _Mail:
    to: str
    subject: str
    text: str


async def _weekly_mails(db: AsyncSession, now_local: datetime) -> list[_Mail]:
    from app.analytics import metrics
    from app.analytics.periods import resolve_period
    from app.services.access_scope import resolve_dashboard_scope

    period = resolve_period("week", offset=-1, now=now_local)
    zone = ZoneInfo(DEFAULT_TZ)
    first_day = period.start.astimezone(zone).date()
    last_day = period.end.astimezone(zone).date() - timedelta(days=1)
    label = f"{first_day:%d.%m}–{last_day:%d.%m.%Y}"
    mails: list[_Mail] = []
    for user in await _recipients(db, (UserRole.head_of_recruitment,)):
        scope = await resolve_dashboard_scope(user, db)
        team = await metrics.team_kpis(
            db,
            period,
            user_ids=frozenset(scope.allowed_operator_user_ids or ()),
            operational_roles_only=False,
        )
        subject, text = render_weekly(team, label)
        mails.append(_Mail(user.email, subject, text))
    return mails


async def _monthly_mails(
    db: AsyncSession, now_local: datetime, period_key: str
) -> list[_Mail]:
    from app.analytics.periods import resolve_period
    from app.services.insights_board import compute_board
    from app.services.insights_board_yoy import compute_board_yoy, resolve_years

    recipients = await _recipients(db, _BOARD_ROLES)
    if not recipients:
        return []
    year, month = (int(part) for part in period_key.split("-"))
    today = now_local.date()
    period = resolve_period("month", anchor=date(year, month, 1))
    board = await compute_board(db, period, today=today)
    try:
        yoy = await compute_board_yoy(db, resolve_years(year, 2, today), today)
    except Exception:  # noqa: BLE001 — tabela r/r jest dodatkiem do raportu
        logger.exception("kpi_email_reports: rok do roku niedostępny")
        yoy = None
    subject, text = render_board(board, yoy, year, month)
    return [_Mail(u.email, subject, text) for u in recipients]


# Runda 7 (R7-N5-2): mail, którego nadawca na pewno NIE wysłał z przejściowego
# powodu (bezpiecznik zamknięty po 429/503, 403 w trakcie incydentu), czeka
# w `app_settings` na kolejny tick tego samego dnia. Znacznik raportu zostaje
# (bez duplikatu po restarcie); ponawiamy wyłącznie tych odbiorców.
_SENT, _DEFERRED, _FAILED = "sent", "deferred", "failed"
_PENDING_PREFIX = "kpi_email_report_pending:"


def _pending_key(kind: str, period_key: str) -> str:
    return f"{_PENDING_PREFIX}{kind}:{period_key}"


def _deliver(kind: str, now_utc: datetime, mail: _Mail) -> str:
    """Jedna wysyłka w wątku roboczym (flagi nadawcy są per wątek)."""
    from app.services.email import send_email
    from app.services.notification_delivery import (
        guarded_send,
        last_send_policy_blocked,
    )

    if guarded_send(kind, now_utc, send_email, mail.to, mail.subject, mail.text, None):
        return _SENT
    if settings.M365_APP_MAIL_ENABLED and not last_send_policy_blocked():
        from app.services.m365.app_mail import last_delivery_deferred

        if last_delivery_deferred():
            return _DEFERRED
    return _FAILED


async def _send_mails(
    kind: str, now_utc: datetime, mails: list[_Mail]
) -> tuple[int, list[str]]:
    sent = 0
    deferred: list[str] = []
    for mail in mails:
        try:
            outcome = await asyncio.to_thread(_deliver, kind, now_utc, mail)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "kpi_email_reports: wysyłka %s: %s", kind, type(exc).__name__
            )
            outcome = _FAILED
        if outcome == _SENT:
            sent += 1
        elif outcome == _DEFERRED:
            deferred.append(mail.to)
    return sent, deferred


async def _store_deferred(
    db: AsyncSession, kind: str, period_key: str, addresses: list[str]
) -> None:
    stmt = pg_insert(AppSetting).values(
        key=_pending_key(kind, period_key), value={"to": addresses}
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[AppSetting.key], set_={"value": stmt.excluded.value}
        )
    )
    await db.commit()
    logger.warning(
        "kpi_email_reports %s %s: %s mail(e) do ponowienia",
        kind,
        period_key,
        len(addresses),
    )


async def _drop_stale_pending(db: AsyncSession, kind: str, period_key: str) -> None:
    """Runda 8 (R8-V3-10): odroczeni odbiorcy STAREGO okresu nie mają już
    ponowienia (klucz okresu się zmienił), a wpis zostawał w `app_settings`
    na zawsze. Nowy okres danego raportu sprząta poprzednie."""
    await db.execute(
        delete(AppSetting).where(
            AppSetting.key.startswith(f"{_PENDING_PREFIX}{kind}:", autoescape=True),
            AppSetting.key != _pending_key(kind, period_key),
        )
    )
    await db.commit()


async def _retry_deferred(
    db: AsyncSession,
    kind: str,
    period_key: str,
    build: Callable[[AsyncSession], Awaitable[list[_Mail]]],
    now_utc: datetime,
) -> str:
    """Ponowienie odroczonych odbiorców; brak odroczonych = `already_claimed`."""
    # DELETE … RETURNING = jedno przejęcie listy nawet przy dwóch kontenerach.
    value = await db.scalar(
        delete(AppSetting)
        .where(AppSetting.key == _pending_key(kind, period_key))
        .returning(AppSetting.value)
    )
    await db.commit()
    addresses = set((value or {}).get("to") or [])
    if not addresses:
        return "already_claimed"
    try:
        mails = [m for m in await build(db) if m.to in addresses]
    except Exception:
        logger.exception(
            "kpi_email_reports: %s %s — liczenie padło (ponowienie)", kind, period_key
        )
        await db.rollback()
        await _store_deferred(db, kind, period_key, sorted(addresses))
        return _FAILED
    sent, deferred = await _send_mails(kind, now_utc, mails)
    if sent:
        await db.execute(
            update(KpiEmailReportRun)
            .where(
                KpiEmailReportRun.kind == kind,
                KpiEmailReportRun.period_key == period_key,
            )
            .values(
                status="sent",
                sent=KpiEmailReportRun.sent + sent,
                finished_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    if deferred:
        await _store_deferred(db, kind, period_key, deferred)
    logger.info(
        "kpi_email_reports %s %s (ponowienie): %s/%s",
        kind,
        period_key,
        sent,
        len(mails),
    )
    return _SENT if sent else (_DEFERRED if deferred else _FAILED)


async def _send_report(
    kind: str,
    period_key: str,
    build: Callable[[AsyncSession], Awaitable[list[_Mail]]],
    now_utc: datetime,
) -> str:
    from app.services.email import email_channel_enabled
    from app.services.notification_delivery import load_policy

    async with AsyncSessionLocal() as db:
        policy = await load_policy(db)
        if not policy.kind_enabled(kind):
            return "disabled"
        if not email_channel_enabled():
            return "no_channel"
        run_id = await claim_report(db, kind, period_key)
        if run_id is None:
            return await _retry_deferred(db, kind, period_key, build, now_utc)
        await _drop_stale_pending(db, kind, period_key)
        try:
            mails = await build(db)
        except Exception:
            logger.exception(
                "kpi_email_reports: %s %s — liczenie padło", kind, period_key
            )
            await db.rollback()
            await _finish(db, run_id, status="failed", recipients=0, sent=0)
            return "failed"
        sent, deferred = await _send_mails(kind, now_utc, mails)
        status = "skipped" if not mails else ("sent" if sent else "failed")
        await _finish(db, run_id, status=status, recipients=len(mails), sent=sent)
        if deferred:
            await _store_deferred(db, kind, period_key, deferred)
        logger.info(
            "kpi_email_reports %s %s: %s/%s", kind, period_key, sent, len(mails)
        )
        return status


async def run_once(now: Optional[datetime] = None) -> dict[str, str]:
    """Jeden tick: wyślij należne raporty. Zwraca `{kind: wynik}` (testy, logi)."""
    now_local = (now or local_now()).astimezone(ZoneInfo(DEFAULT_TZ))
    now_utc = now_local.astimezone(timezone.utc)
    out: dict[str, str] = {}
    weekly_key = weekly_period_key(now_local)
    if weekly_key:
        out[WEEKLY_KIND] = await _send_report(
            WEEKLY_KIND,
            weekly_key,
            lambda db: _weekly_mails(db, now_local),
            now_utc,
        )
    monthly_key = monthly_period_key(now_local)
    if monthly_key:
        out[MONTHLY_KIND] = await _send_report(
            MONTHLY_KIND,
            monthly_key,
            lambda db: _monthly_mails(db, now_local, monthly_key),
            now_utc,
        )
    return out


async def kpi_email_reports_loop() -> None:
    """Tick co 10 min; raport i tak wychodzi raz dzięki znacznikowi w bazie."""
    beat = loop_heartbeat.register(
        "kpi_email_reports", max_silence_seconds=CHECK_INTERVAL_SECONDS + 3600
    )
    while True:
        beat.tick()
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("kpi_email_reports_loop iteration failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
