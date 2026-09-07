"""Champion → kolumny oferty: FILL_EMPTY dla trzech rubryk rekrutacji (0278).

Profil Championa (`jobs.champion_profile`, JSONB) jest tam, gdzie Delivery
Lead faktycznie wpisuje budżet, dni w biurze, tryb pracy i lokalizację —
ale do tej migracji te fakty czytał wyłącznie generator uzasadnień
dopasowania. Scoring, dealbreakery i bramka handoffu patrzą na KOLUMNY
oferty (`rate_budget_hourly`, `onsite_days_per_week`, `remote_policy`,
`location`), więc profil bez synchronizacji był martwy dla całego silnika
matchingu poza jednym ekranem.

`fill_job_columns_from_champion` jest jedynym miejscem, które robi ten
zapis — wołane przy każdym zapisie profilu z UI (`update_champion_profile`)
i przy ingest z pliku (`champion_profile_ingest`), oraz w migracji 0278 / jej
lustrze w `entrypoint.sh` (jako SQL — logika MUSI się zgadzać, pilnuje tego
`tests/test_office_presence_rubric_mirror.py::test_sql_work_mode_prefixes_match_python_map`).

FILL_EMPTY, nigdy nadpisanie: kolumna, którą ktoś (człowiek albo wcześniejszy
zapis Championa) już wypełnił, zostaje taka, jaka jest. Późniejsza zmiana
stawki w Championie NIE podąża więc do `rate_budget_hourly`, gdy ta jest już
ustawiona — `resolve_job_budget_hourly` i tak preferuje kolumnę nad
Championem, więc rozjazd nie ma efektu na scoring, tylko na to, co widać
w formularzu oferty.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from app.models.job import Job, RemotePolicy

# Tryb pracy z profilu Championa jest wolnym tekstem wpisywanym przez
# Delivery Leada (placeholder edytora: „stacjonarnie / hybrydowo / zdalnie”),
# nie enumem — stąd dopasowanie po PREFIKSIE, nie po równości. Lustro SQL-owe
# (`CASE WHEN wm LIKE 'zdaln%' …`) w migracji 0278 i w `entrypoint.sh` MUSI
# używać dokładnie tych samych trzech prefiksów.
WORK_MODE_PREFIXES: dict[str, str] = {
    "zdaln": RemotePolicy.remote.value,
    "hybryd": RemotePolicy.hybrid.value,
    "stacjonar": RemotePolicy.onsite.value,
}

# Budżet Championa jest stawką DLA KANDYDATA w PLN/h (patrz
# `scoring_service._champion_hourly_rate`) — ten sam sufit (0, 2000] co tam
# i co Field(gt=0, le=2000) na `JobCreate.rate_budget_hourly`.
_MAX_RATE_BUDGET_HOURLY = 2000
_MAX_LOCATION_LENGTH = 255


_NUMERIC_TEXT = re.compile(r"^[0-9]+(\.[0-9]+)?$")


def _as_number(value: Any) -> Optional[float]:
    """Liczba z JSONB — także zapisana jako string („122.50”).

    Parser Championa zwraca natywne liczby, ale `champion_view.basics()` czyta
    surowy JSONB, gdzie historyczne profile trzymają część pól jako tekst. Bez
    tej koercji ścieżka pythonowa POMIJAŁABY takie stawki po cichu, podczas gdy
    backfill SQL w migracji 0278 wypełnia je regexem `^[0-9]+(\\.[0-9]+)?$` —
    czyli ta sama oferta dostawałaby budżet z migracji, ale nie z zapisu
    profilu. Wzorzec jest DOKŁADNIE tym samym co w SQL, żeby oba źródła
    kwalifikowały ten sam zbiór wartości.

    `bool` jest odrzucany jawnie: w Pythonie `True` jest instancją `int`,
    a „tryb włączony” nie jest stawką.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and _NUMERIC_TEXT.match(value.strip()):
        return float(value.strip())
    return None


def champion_work_mode_to_remote(value: Any) -> Optional[str]:
    """Wolny tekst trybu pracy Championa → wartość `RemotePolicy` (strip+prefiks).

    Zwraca `None`, gdy `value` nie jest niepustym stringiem albo żaden
    z trzech prefiksów nie pasuje — wołający wtedy po prostu nie wypełnia
    `remote_policy` (FILL_EMPTY, nie błąd).
    """
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    for prefix, remote in WORK_MODE_PREFIXES.items():
        if normalized.startswith(prefix):
            return remote
    return None


def fill_job_columns_from_champion(job: Job, basics: dict[str, Any]) -> list[str]:
    """FILL_EMPTY: przenosi to, co Champion już wie, do kolumn oferty.

    `basics` to sekcja „1. Podstawowe informacje” profilu (kształt
    `ChampionBasics` — patrz `schemas/champion.py`), czy to świeżo
    zwalidowana przez Pydantic (`update_champion_profile`), czy odczytana
    wprost z JSONB przez `champion_view.basics()` (ingest z pliku).

    Nigdy nie nadpisuje kolumny, która ma już wartość — ani ręcznie wpisaną,
    ani wypełnioną wcześniej z tego samego profilu. Zwraca nazwy KOLUMN
    faktycznie zapisanych w tym wywołaniu; pusta lista mówi wołającemu
    „nic się nie zmieniło”, więc nie warto płacić za `refresh_job_matching`.
    """
    if not isinstance(basics, dict):
        return []

    filled: list[str] = []

    rate_value = _as_number(basics.get("rate_value"))
    if (
        job.rate_budget_hourly is None
        and rate_value is not None
        and 0 < rate_value <= _MAX_RATE_BUDGET_HOURLY
    ):
        job.rate_budget_hourly = rate_value
        filled.append("rate_budget_hourly")

    # Dni muszą być całkowite: „2.5 dnia w biurze” nie jest deklaracją, którą
    # umiemy porównać z `candidates.max_onsite_days_per_week` (też int). SQL
    # kwalifikuje tu `^[0-7]$`, więc ułamek odpada po obu stronach.
    days_raw = _as_number(basics.get("onsite_days_per_week"))
    days = int(days_raw) if days_raw is not None and days_raw.is_integer() else None
    if job.onsite_days_per_week is None and days is not None and 0 <= days <= 7:
        job.onsite_days_per_week = days
        filled.append("onsite_days_per_week")

    if job.remote_policy is None:
        remote = champion_work_mode_to_remote(basics.get("work_mode"))
        if remote is not None:
            job.remote_policy = RemotePolicy(remote)
            filled.append("remote_policy")

    location_pref = basics.get("candidate_location_pref")
    if (
        job.location is None
        and isinstance(location_pref, str)
        and location_pref.strip()
    ):
        job.location = location_pref.strip()[:_MAX_LOCATION_LENGTH]
        filled.append("location")

    return filled
