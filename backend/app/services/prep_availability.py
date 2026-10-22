"""Podpowiedź godzin Prepu 1 i Prepu 2 z kalendarzy (20.10.2026, PR 2).

Rekruter wybiera z kandydatem termin rozmowy u klienta i w tym samym oknie
dostaje wolne godziny na oba prepy: Prep 1 z kalendarza Delivery Leada,
Prep 2 ze swojego, z uwzględnieniem tego, kiedy kandydat może. Do tej pory
okno prepu podpowiadało „dzień roboczy przed, 10:00” bez patrzenia w kalendarz
i DL z rekruterem uzgadniali godzinę na Teams.

* **Zajętość czyta aplikacja „NEXUS Teams Prep”** (app-only, ``getSchedule``)
  — ta sama, która zakłada prepy w kalendarzach organizatorów, z zakresem
  ograniczonym do grupy ``NEXUS-Meetings-Scope`` (decyzja Artura 20.10.2026;
  sonda na produkcji: 200, bloki zajętości bez błędu). Widzimy tylko
  „zajęte / wolne”, nie tytuły. Konto M365 połączone z NEXUSEM ma ok. 2 z 30
  osób, więc delegowane ``/me/calendar/getSchedule`` tu się nie nadaje.
* Kalendarz, którego aplikacja nie przeczyta (osoba spoza grupy, błąd
  Grapha, wyłączone prepy w Teams), to ``None`` — podpowiedź liczy się wtedy
  bez zajętości, a ekran mówi „kalendarz niedostępny”. Nic się nie blokuje.
* Godziny wybiera czysta funkcja ``suggest`` (testy bez bazy i Grapha).
* „Inna godzina…” (22.10.2026): rekruter wpisuje prep spoza podpowiedzi.
  Okno dostaje zajętość prowadzącego razem z podpowiedziami, a zapis prepu
  sprawdza ją jeszcze raz (``busy_overlap``) — kolizja to ostrzeżenie, nie
  blokada (decyzja Artura).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from app.core.scheduling import DEFAULT_TZ, is_business_day
from app.services.m365.calendar import parse_free_busy_response

logger = logging.getLogger(__name__)

Interval = tuple[datetime, datetime]

PREP_MINUTES = 45
STEP_MINUTES = 30
# Najwcześniej tyle przed startem prepu od teraz — kandydat musi zdążyć
# odebrać zaproszenie.
MIN_LEAD = timedelta(hours=2)
WORK_START = time(8, 0)
WORK_END = time(18, 0)
# Kandydat po pracy: okno kandydata może sięgać do 20:00.
LATE_END = time(20, 0)
# Prep 1 kończy się co najmniej tyle przed rozmową, Prep 2 — tyle.
PREP1_GAP = timedelta(hours=2)
PREP2_GAP = timedelta(minutes=30)
OPTIONS = 3
_BUSY = {"busy", "tentative", "oof", "unknown"}
_INTERVAL_MINUTES = 30


@dataclass(frozen=True)
class Option:
    start: datetime
    end: datetime


def _business_days_before(day: date, count: int, zone: ZoneInfo) -> list[date]:
    out: list[date] = []
    cursor = day
    while len(out) < count:
        cursor -= timedelta(days=1)
        if is_business_day(datetime.combine(cursor, time(12, 0), tzinfo=zone)):
            out.append(cursor)
    return out


def _overlaps(start: datetime, end: datetime, blocks: Sequence[Interval]) -> bool:
    return any(start < b_end and b_start < end for b_start, b_end in blocks)


def _in_window(
    start: datetime, end: datetime, windows: Sequence[tuple[time, time]], zone: ZoneInfo
) -> bool:
    local_start, local_end = start.astimezone(zone), end.astimezone(zone)
    if local_start.date() != local_end.date():
        return False
    return any(
        w_from <= local_start.time() and local_end.time() <= w_to
        for w_from, w_to in windows
    )


def suggest(
    *,
    prep_no: int,
    interview_start: datetime,
    now: datetime,
    busy: Optional[Sequence[Interval]],
    candidate_windows: Optional[Sequence[tuple[time, time]]] = None,
    avoid: Sequence[Interval] = (),
    minutes: int = PREP_MINUTES,
    tz: str = DEFAULT_TZ,
    limit: int = OPTIONS,
) -> list[Option]:
    """Najlepsze godziny prepu przed rozmową, od najbardziej polecanej.

    Prep 1 (DL): dzień roboczy przed rozmową, potem dwa dni przed, potem rano
    w dniu rozmowy (≥ 2 h przed). Prep 2 (rekruter): w dniu rozmowy jak
    najbliżej „2 h przed”, potem dzień roboczy przed, od najpóźniejszej
    godziny. ``busy=None`` = kalendarz nieznany (nie odrzucamy niczego).
    ``avoid`` — inne terminy pary (np. wybrany Prep 1), z którymi prep nie
    może się pokrywać.
    """
    zone = ZoneInfo(tz)
    length = timedelta(minutes=minutes)
    interview_local = interview_start.astimezone(zone)
    day_of = interview_local.date()
    gap = PREP1_GAP if prep_no == 1 else PREP2_GAP
    latest_end = interview_start - gap
    earliest_start = now + MIN_LEAD
    windows = list(candidate_windows or [])
    day_end = LATE_END if windows else WORK_END
    blocks = [*(busy or []), *avoid]

    def day_slots(day: date) -> list[datetime]:
        first = datetime.combine(day, WORK_START, tzinfo=zone)
        last = datetime.combine(day, day_end, tzinfo=zone) - length
        out: list[datetime] = []
        cursor = first
        while cursor <= last:
            out.append(cursor)
            cursor += timedelta(minutes=STEP_MINUTES)
        return out

    before = _business_days_before(day_of, 2, zone)
    if prep_no == 1:
        ordered: list[datetime] = [*day_slots(before[0]), *day_slots(before[1])]
        ordered += day_slots(day_of)
    else:
        target = interview_start - timedelta(hours=2)
        same_day = sorted(
            day_slots(day_of), key=lambda s: abs((s - target).total_seconds())
        )
        ordered = [*same_day, *reversed(day_slots(before[0]))]

    picked: list[Option] = []
    for start in ordered:
        end = start + length
        if start < earliest_start or end > latest_end:
            continue
        if windows and not _in_window(start, end, windows, zone):
            continue
        if _overlaps(start, end, blocks):
            continue
        if any(_overlaps(start, end, [(o.start, o.end)]) for o in picked):
            continue
        picked.append(
            Option(
                start=start.astimezone(timezone.utc), end=end.astimezone(timezone.utc)
            )
        )
        if len(picked) >= limit:
            break
    return picked


def busy_overlap(
    start: datetime, end: datetime, busy: Optional[Sequence[Interval]]
) -> Optional[Interval]:
    """Zajęty przedział prowadzącego, na który wpada prep — albo ``None``.

    Bloki, które nachodzą na prep, łączy w jeden (komunikat mówi „ma wtedy
    zajęte 11:30–13:00”, a nie trzy kawałki). ``busy=None`` = kalendarz
    nieznany, więc kolizji nie ma czym potwierdzić.
    """
    hits = [(s, e) for s, e in busy or [] if start < e and s < end]
    if not hits:
        return None
    return min(s for s, _ in hits), max(e for _, e in hits)


def span_label(span: Interval, tz: str = DEFAULT_TZ) -> str:
    """„11:30–13:00” w strefie firmy."""
    zone = ZoneInfo(tz)
    return f"{span[0].astimezone(zone):%H:%M}–{span[1].astimezone(zone):%H:%M}"


def busy_from_schedule(
    payload: dict, *, window_start: datetime
) -> dict[str, Optional[list[Interval]]]:
    """Odpowiedź ``getSchedule`` → zajęte przedziały per adres (małe litery).

    Harmonogram z błędem (osoba spoza zakresu aplikacji) = ``None``.
    """
    errors = {
        (s.get("scheduleId") or "").strip().lower()
        for s in payload.get("value") or []
        if s.get("error")
    }
    parsed = parse_free_busy_response(
        payload, window_start=window_start, interval_minutes=_INTERVAL_MINUTES
    )
    out: dict[str, Optional[list[Interval]]] = {}
    for email, slots in parsed.items():
        key = email.lower()
        if key in errors:
            out[key] = None
            continue
        out[key] = [(s["start"], s["end"]) for s in slots if s["status"] in _BUSY]
    return out


async def busy_blocks(
    emails: Sequence[str], *, start: datetime, end: datetime
) -> dict[str, Optional[list[Interval]]]:
    """Zajętość osób z kalendarzy (app-only). Nigdy nie rzuca.

    Adres w ścieżce musi być skrzynką z zakresu aplikacji — próbujemy po kolei
    każdej z podanych, aż Graph odpowie.
    """
    from app.services import prep_meetings  # noqa: PLC0415 — cykl importów
    from app.services.m365 import teams_prep_graph as tpg  # noqa: PLC0415
    from app.services.m365.graph_client import GraphRequestError  # noqa: PLC0415

    wanted = [e.strip().lower() for e in emails if e and e.strip()]
    result: dict[str, Optional[list[Interval]]] = {e: None for e in wanted}
    if not wanted or not prep_meetings.app_only_ready():
        return result
    payload = {
        "schedules": wanted[:20],
        "startTime": {
            "dateTime": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "UTC",
        },
        "endTime": {
            "dateTime": end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "UTC",
        },
        "availabilityViewInterval": _INTERVAL_MINUTES,
    }
    for anchor in wanted:
        try:
            async with tpg._client() as gc:
                res = await gc.post(
                    f"{tpg._user(anchor)}/calendar/getSchedule",
                    json=payload,
                    # getSchedule tylko czyta — powtórka jest bezpieczna.
                    retry_unsafe=True,
                )
        except GraphRequestError as exc:
            logger.info("[prep_availability] getSchedule status=%s", exc.status)
            continue
        except Exception as exc:  # noqa: BLE001 — kalendarz to podpowiedź
            logger.warning(
                "[prep_availability] getSchedule failed (%s)", type(exc).__name__
            )
            return result
        result.update(busy_from_schedule(res or {}, window_start=start))
        return result
    return result
