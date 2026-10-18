"""Odczyt autoodpowiedzi (``automaticRepliesSetting``) — czyje jest i na kiedy.

Czyste funkcje (bez sieci i zegara) używane przez wykonawcę i uzgadnianie:

* „nasza” autoodpowiedź niesie znacznik NEXUSA albo Compassa — po
  przełączeniu NEXUS przejmuje autoodpowiedzi ustawione przez Compass,
* okno harmonogramu liczymy w DATACH warszawskich: Graph oddaje
  ``scheduled*DateTime`` w UTC (albo w strefie zapisu), a północ warszawska
  to 22:00 albo 23:00 UTC zależnie od czasu letniego,
* własna autoodpowiedź osoby (bez znacznika, aktywna albo zaplanowana) jest
  nietykalna — ale jej harmonogram mówi, kiedy osoby nie ma
  (``custom_absence_window``): uzgadnianie zakłada z niego wniosek, jeśli
  osoba ustawiła nieobecność w Outlooku bez wniosku (``leave_outlook``).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.scheduling import DEFAULT_TZ

NEXUS_OOF_MARKER = "<!-- nexus-managed-oof-v1 -->"
COMPASS_OOF_MARKER = "<!-- compass-managed-oof-v1 -->"
# Exchange potrafi przepisać HTML odpowiedzi — szukamy samego słowa znacznika.
_TOKENS: dict[str, str] = {
    "nexus": "nexus-managed-oof-v1",
    "compass": "compass-managed-oof-v1",
}

Owner = Literal["nexus", "compass"]

_WARSAW = ZoneInfo(DEFAULT_TZ)


def owner(setting: Optional[dict[str, Any]]) -> Optional[Owner]:
    """``nexus`` / ``compass`` dla autoodpowiedzi ze znacznikiem, inaczej ``None``."""

    if not setting:
        return None
    body = f"{setting.get('internalReplyMessage') or ''}{setting.get('externalReplyMessage') or ''}"
    for name, token in _TOKENS.items():
        if token in body:
            return name  # type: ignore[return-value]
    return None


def is_managed(setting: Optional[dict[str, Any]]) -> bool:
    return owner(setting) is not None


def is_disabled(setting: Optional[dict[str, Any]]) -> bool:
    return not setting or setting.get("status") == "disabled"


def _zone(name: str) -> ZoneInfo:
    if not name or name.upper() == "UTC":
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        # Windowsowa nazwa strefy („Central European Standard Time”): NEXUS
        # i Compass zapisują zawsze czas warszawski, więc to ta sama oś.
        return _WARSAW


def instant(value: Any) -> Optional[datetime]:
    """``{dateTime, timeZone}`` z Grapha → chwila (aware) albo ``None``."""

    if not isinstance(value, dict) or not value.get("dateTime"):
        return None
    raw = str(value["dateTime"])
    if raw.endswith("Z"):
        raw = raw[:-1]
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_zone(str(value.get("timeZone") or "UTC")))
    return parsed


def warsaw_date(value: Any) -> Optional[date]:
    moment = instant(value)
    return moment.astimezone(_WARSAW).date() if moment else None


def scheduled_window(setting: Optional[dict[str, Any]]) -> Optional[tuple[date, date]]:
    """Okno ``[pierwszy dzień, dzień po końcu)`` w datach warszawskich."""

    if not setting or setting.get("status") != "scheduled":
        return None
    start = warsaw_date(setting.get("scheduledStartDateTime"))
    end = warsaw_date(setting.get("scheduledEndDateTime"))
    if start is None or end is None:
        return None
    return start, end


def matches_leave(setting: Optional[dict[str, Any]], start: date, end: date) -> bool:
    """Nasza autoodpowiedź dokładnie dla urlopu ``start``–``end`` (włącznie)."""

    if is_disabled(setting) or not is_managed(setting):
        return False
    return scheduled_window(setting) == (start, end + timedelta(days=1))


def user_custom_active(setting: Optional[dict[str, Any]], now: datetime) -> bool:
    """Własna autoodpowiedź osoby, która trwa albo dopiero nadejdzie.

    Zaplanowana bez znacznika i już zakończona — wolno ją nadpisać. Nieznany
    status albo nieczytelny koniec — zostawiamy (lepiej nie ustawić naszej,
    niż skasować cudzą).
    """

    if is_disabled(setting) or is_managed(setting):
        return False
    status = setting.get("status") if setting else None
    if status == "scheduled":
        end = instant(setting.get("scheduledEndDateTime"))
        return end is None or end > now
    return True


def blocking_until(
    setting: Optional[dict[str, Any]], new_start: date, today: date
) -> Optional[datetime]:
    """Koniec naszej autoodpowiedzi innego urlopu, która blokuje nową.

    Graph trzyma JEDEN harmonogram: nadpisanie odebrałoby autoodpowiedź
    urlopowi, który trwa (albo nadejdzie wcześniej). Blokuje, gdy okno jeszcze
    się nie skończyło, a nowy urlop zaczyna się w dniu jego końca lub później;
    nowy urlop wcześniejszy niż koniec okna nadpisuje (pierwszeństwo ma
    wcześniejszy). Zwraca chwilę końca okna (UTC) — wtedy wolno ponowić.
    """

    if is_disabled(setting) or not is_managed(setting):
        return None
    window = scheduled_window(setting)
    if window is None:
        return None
    _, end_exclusive = window
    if end_exclusive <= today or new_start < end_exclusive:
        return None
    moment = instant(setting.get("scheduledEndDateTime")) if setting else None
    if moment is None:
        moment = datetime.combine(end_exclusive, datetime.min.time(), tzinfo=_WARSAW)
    return moment.astimezone(timezone.utc)


#: Dzień startu liczy się jako nieobecność tylko, gdy autoodpowiedź ruszyła
#: przed tą godziną (Warszawa) — „od 16:30 piszcie do Marcina” to nie dzień
#: wolny (Compass, ``lib/oof/oof-dates.ts``).
LATE_START_CUTOFF = time(15, 0)
#: Koniec o tej godzinie albo wcześniej nie obejmuje dnia końca: północ
#: (Graph zapisuje ``ostatni dzień + 1, 00:00``) i „wracam o 8:00”.
EARLY_END_CUTOFF = time(9, 0)


def custom_absence_window(
    setting: Optional[dict[str, Any]],
) -> Optional[tuple[date, date]]:
    """Dni nieobecności z harmonogramu WŁASNEJ autoodpowiedzi osoby.

    ``(pierwszy, ostatni)`` włącznie, w datach warszawskich. ``None``, gdy
    autoodpowiedź jest nasza, wyłączona, bez dat (``alwaysEnabled``),
    nieczytelna albo nie obejmuje żadnego pełnego dnia (jeden wieczór).
    Reguły godzin jak w Compassie: start od 15:00 przesuwa się na następny
    dzień, koniec do 9:00 włącznie wyklucza dzień końca.
    """

    if is_disabled(setting) or is_managed(setting):
        return None
    if not setting or setting.get("status") != "scheduled":
        return None
    start = instant(setting.get("scheduledStartDateTime"))
    end = instant(setting.get("scheduledEndDateTime"))
    if start is None or end is None:
        return None
    start_local = start.astimezone(_WARSAW)
    end_local = end.astimezone(_WARSAW)
    first = start_local.date()
    if start_local.time() >= LATE_START_CUTOFF:
        first += timedelta(days=1)
    last = end_local.date()
    if end_local.time() <= EARLY_END_CUTOFF:
        last -= timedelta(days=1)
    if last < first:
        return None
    return first, last
