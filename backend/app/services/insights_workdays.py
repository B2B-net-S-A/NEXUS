"""Zaciąganie dni roboczych z COMPASSA (decyzja D5).

Kontekst: NEXUS ocenia rekruterów wskaźnikami „na dzień" (Power Calling,
CV/MD), a nie zna nieobecności. Do 2026-08-31 dzielił przez sztywne ``5``
i publikował imienną listę „poniżej progu" — osoba na urlopie trafiała na nią
pod nazwiskiem. COMPASS zna urlopy, więc to on jest źródłem mianownika.

TRZY DECYZJE, KTÓRE TRZYMAJĄ TO UCZCIWYM
----------------------------------------
1. **Przenosimy wyłącznie LICZBY DNI.** Nigdy typu nieobecności ani notatki:
   ``leave_type`` przyjmuje ``sick_leave``/``parental_leave`` (dane o zdrowiu),
   a ``note`` zawiera w produkcji wolny tekst medyczny. Kontrakt jest wymuszony
   po obu stronach — endpoint w COMPASSIE też ich nie oddaje.

2. **Własny sekret, nie ``CRON_SECRET`` COMPASSA.** Tamten odblokowuje również
   ``/api/migrate-compliance``, czyli zdolność uruchomienia DDL na bazie
   COMPASSA. ``COMPASS_WORKDAYS_SECRET`` otwiera wyłącznie trasę eksportu.

3. **Niedopasowani są RAPORTOWANI, nie pomijani.** Osoba w COMPASSIE bez
   odpowiednika w NEXUSIE (albo odwrotnie) musi być policzona i pokazana.
   Ciche pominięcie daje mianownik, który wygląda kompletnie, a nie jest —
   i to jest dokładnie ta klasa błędu, którą D5 usuwa.

DLACZEGO JOIN PO E-MAILU JEST DZIŚ POPRAWNY — I KIEDY PRZESTANIE
----------------------------------------------------------------
Zmierzone 2026-08-31: wszystkie 46 profili w COMPASSIE ma domenę
``@b2bnetwork.pl``, a wszystkie 25 AKTYWNYCH kont rekruterskich w NEXUSIE
również (konta ``@inframinds.eu`` istnieją, ale są nieaktywne). Migracja
domenowa jest jednak w toku — w dniu, w którym aktywne konta przejdą na nową
domenę, ten join zacznie po cichu nie trafiać. Dlatego sync raportuje liczbę
niedopasowanych w OBIE strony: wzrost tej liczby jest sygnałem, że kończy się
okres, w którym e-mail wystarcza.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.models.user_workday_period import UserWorkdayPeriod

logger = logging.getLogger(__name__)

# Kopertowa etykieta znaczenia liczby. Musi zgadzać się z tym, co zwraca
# COMPASS — rozjazd oznaczałby, że UI podpisuje liczbę inaczej niż jej źródło.
EXPECTED_BASIS = "business_days_minus_approved_leave"

# Podłoga progu świeżości sondy. Domyślny odstęp pętli to 6 h, więc trzy
# odstępy to 18 h — mniej niż doba, czyli jeden nocny przestój dawałby alarm.
_STALE_FLOOR_SECONDS = 86_400


def workdays_sync_verdict(
    finished_at: datetime | None,
    last_status: str | None,
    interval_seconds: int,
    now: datetime,
) -> str:
    """``"healthy"`` albo ``"degraded"`` dla ``checks.compass_workdays``.

    Czysta funkcja, bo cała wartość tej sondy siedzi w tych warunkach, a wersja
    wpleciona w handler daje się przetestować wyłącznie przez gałąź
    ``except`` — czyli zwracałaby właściwy wynik z niewłaściwego powodu.

    **``healthy`` wymaga ``last_status == "ok"``, nie samej świeżości.**
    ``sync_workdays`` wraca z ``fetch_failed:`` i ``basis_mismatch:``
    NORMALNIE, nic nie zapisawszy i nie rzucając wyjątku. Gdyby liczyła się
    tylko data ostatniego biegu, niedostępny COMPASS raportowałby ``healthy``
    tak długo, jak długo pętla się budzi — czyli dokładnie ta ślepa plamka,
    dla której ta sonda powstała.

    ``running`` nie jest osobnym przypadkiem: to albo bieg w toku, albo bieg
    przerwany restartem (Coolify podmienia kontener przy każdym pushu na main).
    O świeżości mówi data ostatniego KOŃCA, więc ``running`` degraduje dopiero
    wtedy, gdy ten koniec jest stary.
    """
    if finished_at is None:
        return "degraded"
    stale_after = timedelta(
        seconds=max(3 * int(interval_seconds), _STALE_FLOOR_SECONDS)
    )
    if (now - finished_at) > stale_after:
        return "degraded"
    return "healthy" if last_status == "ok" else "degraded"


@dataclass
class WorkdaySyncResult:
    """Wynik jednego przebiegu — z jawnym rachunkiem niedopasowań."""

    months_requested: int = 0
    rows_received: int = 0
    rows_written: int = 0
    matched_users: int = 0
    unmatched_compass_emails: list[str] = field(default_factory=list)
    nexus_users_without_compass: list[str] = field(default_factory=list)
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
            "unmatched_compass_emails": sorted(self.unmatched_compass_emails),
            "nexus_users_without_compass": sorted(self.nexus_users_without_compass),
            "basis": self.basis,
            "error": self.error,
        }


def _parse_day(value: str) -> date | None:
    """``YYYY-MM-DD`` → data. ``None`` gdy nie da się sparsować."""
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, AttributeError, TypeError):
        return None


async def fetch_workdays(date_from: date, date_to: date, bucket: str = "month") -> dict:
    """Pobierz surową odpowiedź z COMPASSA. Rzuca przy błędzie HTTP."""
    url = settings.COMPASS_WORKDAYS_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            url,
            params={
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
                "bucket": bucket,
            },
            # Wyłącznie nagłówek — sekret w query stringu wylądowałby
            # w access logach pośredników, a ten ma żyć długo.
            headers={"Authorization": f"Bearer {settings.COMPASS_WORKDAYS_SECRET}"},
        )
    resp.raise_for_status()
    return resp.json()


async def sync_workdays(
    db: AsyncSession, date_from: date, date_to: date, bucket: str = "month"
) -> WorkdaySyncResult:
    """Zaciągnij dni robocze i zapisz je idempotentnie."""
    result = WorkdaySyncResult()
    result.months_requested = (
        (date_to.year - date_from.year) * 12 + (date_to.month - date_from.month) + 1
    )

    if not settings.COMPASS_WORKDAYS_ENABLED:
        result.error = "disabled"
        return result
    if not settings.COMPASS_WORKDAYS_URL or not settings.COMPASS_WORKDAYS_SECRET:
        result.error = "unconfigured"
        return result

    try:
        payload = await fetch_workdays(date_from, date_to, bucket)
    except Exception as exc:  # noqa: BLE001 — awaria COMPASSA nie może wywalić NEXUSA
        logger.warning("compass_workdays_fetch_failed error=%s", exc)
        result.error = f"fetch_failed: {exc}"
        return result

    result.basis = payload.get("basis")
    if result.basis and result.basis != EXPECTED_BASIS:
        # Rozjazd znaczenia liczby jest gorszy niż jej brak: UI podpisałby ją
        # etykietą, której źródło już nie potwierdza.
        logger.warning(
            "compass_workdays_basis_mismatch expected=%s got=%s",
            EXPECTED_BASIS,
            result.basis,
        )
        result.error = f"basis_mismatch: {result.basis}"
        return result

    rows = payload.get("people") or []
    result.rows_received = len(rows)

    # Mapa e-mail → user_id. Tylko AKTYWNI: importer Traffita zakłada
    # niedopasowanych operatorów jako nieaktywnych, a przypisanie im dni
    # roboczych tworzyłoby mianownik dla kont, które nie pracują.
    user_rows = (
        await db.execute(select(User.id, User.email).where(User.is_active.is_(True)))
    ).all()
    by_email = {(email or "").strip().lower(): uid for uid, email in user_rows if email}

    seen_emails: set[str] = set()
    matched_user_ids: set[int] = set()
    to_write: list[dict] = []

    for row in rows:
        email = str(row.get("email") or "").strip().lower()
        if not email:
            continue
        seen_emails.add(email)
        user_id = by_email.get(email)
        if user_id is None:
            result.unmatched_compass_emails.append(email)
            continue
        p_start = _parse_day(str(row.get("period_start") or ""))
        p_end = _parse_day(str(row.get("period_end") or ""))
        if p_start is None or p_end is None:
            continue
        matched_user_ids.add(user_id)
        to_write.append(
            {
                "user_id": user_id,
                "period_start": p_start,
                "period_end": p_end,
                "business_days": int(row.get("business_days") or 0),
                "absence_days": float(row.get("absence_days") or 0),
                "working_days": float(row.get("working_days") or 0),
                "basis": EXPECTED_BASIS,
                "source": "compass",
                "synced_at": datetime.now(timezone.utc),
            }
        )

    # Druga strona rachunku: kto w NEXUSIE nie ma odpowiednika w COMPASSIE.
    # Bez tej listy mianownik wyglądałby na kompletny przy 72% pokryciu.
    for email, _uid in by_email.items():
        if email not in seen_emails:
            result.nexus_users_without_compass.append(email)

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
