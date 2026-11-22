"""Dni robocze per osoba — mianownik wskaźników „na dzień” (decyzja D5).

Kontekst: NEXUS ocenia rekruterów wskaźnikami „na dzień" (Power Calling,
CV/MD). Do 2026-08-31 dzielił przez sztywne ``5`` i publikował imienną listę
„poniżej progu" — osoba na urlopie trafiała na nią pod nazwiskiem.

Źródłem są urlopy NEXUSA („Ludzie w NEXUSIE”, krok 6): pętla ``hr_workdays``
(``tasks/hr_loops.py``) liczy wiersze z ``local_workdays_payload``. Do
przełączenia liczby przychodziły z Compassa; Compass jest wygaszony od
22.11.2026, a jego pętla, sonda i ustawienia zniknęły z kodu. Wiersze
``user_workday_periods`` ze źródłem ``compass`` to historia sprzed przełączenia.

Przenosimy wyłącznie LICZBY DNI, nigdy rodzaju nieobecności ani notatki —
to dane o zdrowiu i nie wychodzą poza moduł urlopów.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_workday_period import UserWorkdayPeriod

logger = logging.getLogger(__name__)

# Etykieta znaczenia liczby zapisywana przy każdym wierszu.
EXPECTED_BASIS = "business_days_minus_approved_leave"


@dataclass
class WorkdaySyncResult:
    """Wynik jednego przebiegu — z jawnym rachunkiem niedopasowań."""

    months_requested: int = 0
    rows_received: int = 0
    rows_written: int = 0
    matched_users: int = 0
    unmatched_emails: list[str] = field(default_factory=list)
    users_without_rows: list[str] = field(default_factory=list)
    # Runda 9 (R9-N9-7): wiersze dla tego samego (osoba, okres) — powtórzone
    # z tymi samymi liczbami są zlewane, sprzeczne pomijane.
    duplicate_rows: int = 0
    conflicting_periods: int = 0
    basis: str | None = None
    error: str | None = None

    def as_payload(self) -> dict:
        return {
            "months_requested": self.months_requested,
            "rows_received": self.rows_received,
            "rows_written": self.rows_written,
            "matched_users": self.matched_users,
            # Obie listy jadą do odpowiedzi. Sama liczba nie wystarcza —
            # bez adresów nie da się naprawić konkretnego przypadku.
            "unmatched_emails": sorted(self.unmatched_emails),
            "users_without_rows": sorted(self.users_without_rows),
            "duplicate_rows": self.duplicate_rows,
            "conflicting_periods": self.conflicting_periods,
            "basis": self.basis,
            "error": self.error,
        }


def _parse_day(value: str) -> date | None:
    """``YYYY-MM-DD`` → data. ``None`` gdy nie da się sparsować."""
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, AttributeError, TypeError):
        return None


async def sync_workdays(
    db: AsyncSession,
    date_from: date,
    date_to: date,
    bucket: str = "month",
) -> WorkdaySyncResult:
    """Policz dni robocze z urlopów NEXUSA i zapisz je idempotentnie."""
    from app.services.hr.availability_local import local_workdays_payload

    result = WorkdaySyncResult()
    result.months_requested = (
        (date_to.year - date_from.year) * 12 + (date_to.month - date_from.month) + 1
    )
    payload = await local_workdays_payload(db, date_from, date_to, bucket)
    result.basis = payload.get("basis")

    rows = payload.get("people") or []
    result.rows_received = len(rows)

    # Mapa e-mail → user_id. Tylko AKTYWNI: przypisanie dni roboczych kontom
    # nieaktywnym tworzyłoby mianownik dla kont, które nie pracują.
    user_rows = (
        await db.execute(select(User.id, User.email).where(User.is_active.is_(True)))
    ).all()
    by_email = {(email or "").strip().lower(): uid for uid, email in user_rows if email}

    seen_emails: set[str] = set()
    matched_user_ids: set[int] = set()
    # Runda 9 (R9-N9-7): klucz = więz `uq_user_workday_period`. Dwa wiersze tej
    # samej osoby i okresu w jednym INSERT … ON CONFLICT dawały „ON CONFLICT DO
    # UPDATE command cannot affect row a second time” i cały przebieg padał.
    by_key: dict[tuple[int, date, date], dict] = {}
    conflicting: set[tuple[int, date, date]] = set()

    for row in rows:
        email = str(row.get("email") or "").strip().lower()
        if not email:
            continue
        seen_emails.add(email)
        user_id = by_email.get(email)
        if user_id is None:
            result.unmatched_emails.append(email)
            continue
        p_start = _parse_day(str(row.get("period_start") or ""))
        p_end = _parse_day(str(row.get("period_end") or ""))
        if p_start is None or p_end is None:
            continue
        matched_user_ids.add(user_id)
        values = {
            "user_id": user_id,
            "period_start": p_start,
            "period_end": p_end,
            "business_days": int(row.get("business_days") or 0),
            "absence_days": float(row.get("absence_days") or 0),
            "working_days": float(row.get("working_days") or 0),
            "basis": EXPECTED_BASIS,
            "source": "nexus",
            "synced_at": datetime.now(timezone.utc),
        }
        key = (user_id, p_start, p_end)
        previous = by_key.get(key)
        if previous is None:
            by_key[key] = values
            continue
        result.duplicate_rows += 1
        numbers = ("business_days", "absence_days", "working_days")
        if any(previous[n] != values[n] for n in numbers):
            conflicting.add(key)

    result.conflicting_periods = len(conflicting)
    to_write = [v for k, v in by_key.items() if k not in conflicting]

    # Druga strona rachunku: kto z aktywnych kont nie dostał wiersza (np. bez
    # kartoteki). Bez tej listy mianownik wyglądałby na kompletny.
    for email, _uid in by_email.items():
        if email not in seen_emails:
            result.users_without_rows.append(email)

    if to_write:
        stmt = pg_insert(UserWorkdayPeriod).values(to_write)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_user_workday_period",
            set_={
                "business_days": stmt.excluded.business_days,
                "absence_days": stmt.excluded.absence_days,
                "working_days": stmt.excluded.working_days,
                "basis": stmt.excluded.basis,
                "source": stmt.excluded.source,
                "synced_at": stmt.excluded.synced_at,
            },
        )
        await db.execute(stmt)
        await db.commit()

    result.rows_written = len(to_write)
    result.matched_users = len(matched_user_ids)
    return result


async def race_workdays_to_date(
    db: AsyncSession,
    user_ids: list[int],
    *,
    month_start: date,
    month_end: date,
    today: date,
    calendar_elapsed: int,
) -> dict[int, tuple[float, str]]:
    """Mianownik „X/dzień" wyścigu miesięcznego: `{user_id: (dni, źródło)}`.

    Decyzja Artura 23.09.2026 (plan PR3): plakietka ma liczbę ZAWSZE, a jej
    źródło mówi, ile wiemy. Każda osoba dostaje wpis:

    * ``"nexus"`` — urlopy NEXUSA (``hr_availability_source = local``): dni
      robocze, które upłynęły, minus zatwierdzona nieobecność na nich
      (``person_workdays``). Przy tym źródle dwie gałęzie niżej nie biegną.
    * ``"compass"`` — COMPASS zna nieobecności w tym oknie: miesiąc zamknięty
      (wiersz miesięczny = pełny miesiąc minus zatwierdzony urlop) albo miesiąc
      trwający, w którym COMPASS nie ma ŻADNEGO urlopu (wtedy dni kalendarzowe,
      które upłynęły, SĄ dniami pracy).
    * ``"calendar"`` — dni robocze kalendarza (Pon–Pt bez świąt), które
      upłynęły, BEZ urlopów. Tak jest przy braku wiersza z COMPASSA, a także
      w trwającym miesiącu z urlopem: wiersz miesięczny opisuje CAŁY miesiąc,
      więc nie wiemy, ile urlopu już minęło — odjęcie całości zaniżałoby
      mianownik za dni, które dopiero nadejdą. Front podpisuje to „bez urlopów".

    Wiersz miesięczny COMPASSA to zawsze pełny miesiąc
    (``nexus_workdays_export``, bucket ``month``) — stąd dopasowanie okna
    dokładnie po [pierwszy, ostatni dzień miesiąca].
    """
    if not user_ids:
        return {}
    from app.services.person_workdays import nexus_absences_known, workdays_by_user

    if await nexus_absences_known(db):
        # Urlopy NEXUSA znają każdy dzień, więc także trwający miesiąc liczy
        # dni pracy do dziś (decyzja Artura 28.10.2026, `person_workdays`).

        last = min(today, month_end)
        if last < month_start:
            return {uid: (0.0, "nexus") for uid in user_ids}
        worked = await workdays_by_user(db, user_ids, month_start, last)
        return {uid: (worked[int(uid)], "nexus") for uid in user_ids}
    rows = (
        await db.execute(
            select(
                UserWorkdayPeriod.user_id,
                UserWorkdayPeriod.working_days,
                UserWorkdayPeriod.absence_days,
            ).where(
                UserWorkdayPeriod.user_id.in_(user_ids),
                UserWorkdayPeriod.period_start == month_start,
                UserWorkdayPeriod.period_end == month_end,
            )
        )
    ).all()
    by_user = {int(uid): (float(work), float(absent)) for uid, work, absent in rows}
    month_closed = today > month_end
    # Dzień onboardingu nowej osoby nie jest dniem pracy przy żadnym źródle.
    from app.services.onboarding_day import onboarding_days
    from app.services.person_workdays import business_days

    last = min(today, month_end)
    onboarding = (
        await onboarding_days(db, user_ids, month_start, last)
        if last >= month_start
        else {}
    )
    business = set(business_days(month_start, last)) if onboarding else set()
    out: dict[int, tuple[float, str]] = {}
    for uid in user_ids:
        off = float(len(onboarding.get(int(uid), frozenset()) & business))
        compass = by_user.get(int(uid))
        if compass is not None:
            working, absent = compass
            if month_closed:
                out[uid] = (max(0.0, working - off), "compass")
                continue
            if absent <= 0:
                out[uid] = (max(0.0, calendar_elapsed - off), "compass")
                continue
        out[uid] = (max(0.0, calendar_elapsed - off), "calendar")
    return out


async def working_days_for(
    db: AsyncSession, user_ids: list[int], period_start: date, period_end: date
) -> dict[int, float]:
    """Dni robocze per user w DOKŁADNIE tym oknie. Brak wpisu = brak klucza.

    Świadomie NIE zwraca wartości domyślnej. Konsument MUSI odróżnić „ta osoba
    przepracowała N dni" od „nie wiemy" — podstawienie tu jakiejkolwiek stałej
    przywróciłoby defekt, dla którego ten moduł powstał.
    """
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(UserWorkdayPeriod.user_id, UserWorkdayPeriod.working_days).where(
                UserWorkdayPeriod.user_id.in_(user_ids),
                UserWorkdayPeriod.period_start == period_start,
                UserWorkdayPeriod.period_end == period_end,
            )
        )
    ).all()
    found = {uid: float(days) for uid, days in rows}

    if not found:
        # Bez tego logu pusty wynik jest NIEODRÓŻNIALNY od wyłączonej
        # integracji: raport w obu przypadkach mówi „nie wiem", ale w jednym
        # jest to prawda, a w drugim rozjazd granic okna (COMPASS zwraca
        # domknięty [start, end], Power Calling liczy tydzień ISO) albo
        # nieudany sync. Cisza w takiej sytuacji to ta sama klasa błędu,
        # którą ten moduł naprawia.
        logger.info(
            "workdays_lookup_empty users=%s window=%s..%s "
            "(sprawdź granice okna i status syncu)",
            len(user_ids),
            period_start,
            period_end,
        )
    return found
