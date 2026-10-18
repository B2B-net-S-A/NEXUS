"""Ręczne uzupełnienie statystyk sprzed 12.10.2026 w tabelach DynaReportera.

Decyzja Artura 18.10.2026 (`docs/claude/finanse-insights/insights-insights-parytet-z-dynareporterem-na.md`,
sekcja „Statystyki sprzed 12.10.2026 wyłącznie z DynaReportera”): dni do
11.10.2026 NEXUS liczy tylko z tabel `dr_*`, a czego DynaReporter nie
prowadził, zespół uzupełnia ręcznie. Arkusz robi i czyta
`scripts/dr_manual_fill_sheet.py` (lokalnie); ten skrypt wgrywa jego JSON do
tych samych tabel, z których liczą ekrany:

* `dr_kpi_body_leasing` — tydzień rekrutera (widok `analytics_kpi_milestones`,
  od 0472 także przed 2026); tydzień przechodzący przez koniec miesiąca to dwa
  wpisy, drugi od 1. dnia miesiąca — jak w DynaReporterze;
* `dr_placement_details` — placement z klientem 1.01–11.10.2026 (klienci
  w Analizie placementów i Roku do roku);
* `dr_kpi_delivery_lead` — miesiąc Delivery Leada; październik 2026 = 1–11.10;
* `dr_board_monthly_report.placements` — placementy firmy w miesiącu przed
  2026 (inne kolumny raportu Rady zostają);
* `dr_board_placement_clients` — placementy klienta w miesiącu przed 2026.

Wejście na stdin (JSON, same id kont — repo i logi są publiczne)::

    {"weeks": [{"user_id": 86, "report_date": "2025-03-03", "verifications": 6,
                "recommendations": 4, "interviews": 2, "placements": 1,
                "days_worked": 5}],
     "placements": [{"user_id": 86, "placement_date": "2026-03-05",
                     "client": "Nordea", "count": 1}],
     "dl_months": [{"user_id": 86, "report_month": "2026-03", "requests": 3,
                    "placements": 2, "vacancies": 4, "open_requests": 1,
                    "open_vacancies": 2}],
     "board_months": [{"report_month": "2025-03", "placements": 12}],
     "board_clients": [{"report_month": "2025-03", "client_name": "Nordea",
                        "placement_count": 4}]}

Wgrywa tylko przekazane wiersze: liczba zastępuje zapisaną, puste pole
(`null`) zostawia zapisaną (w nowym wierszu 0, dni przepracowane 5).
Placement z klientem i placementy klienta w miesiącu ustawiają liczbę dla
klucza (osoba, dzień, klient) / (miesiąc, klient) — 0 usuwa. Odmawia dni od
12.10.2026 (od tego dnia liczy NEXUS), kont bez odpowiednika w NEXUS-ie
i nieznanych klientów — wtedy nic nie zapisuje.

Przebieg (kontener backendu produkcji)::

    docker exec -i <backend> python -m scripts.import_dr_manual_fill < dane.json
    docker exec -i <backend> python -m scripts.import_dr_manual_fill --apply < dane.json
    docker exec <backend> python -m scripts.import_dr_manual_fill --gaps
    docker exec <backend> python -m scripts.import_dr_manual_fill --lists > listy.json

Bez `--apply` transakcja jest tylko do odczytu i wypisuje „przed → po”
(id, daty, liczby). `--apply` zapisuje w jednej transakcji z paragonem
`dr_manual_fill_<czas z mikrosekundami>` (każdy zmieniony wiersz przed i po). `--gaps` liczy
luki do zakładki „Braki” (same id); `--lists` wypisuje konta i klientów do
list wyboru arkusza — Z NAZWISKAMI, tylko do pliku lokalnie, nigdy do logów.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.scheduling import DEFAULT_TZ  # noqa: E402
from app.services import competition_history as history  # noqa: E402

RECEIPT_PREFIX = "dr_manual_fill_"
SECTIONS = ("weeks", "placements", "dl_months", "board_months", "board_clients")
WEEK_FIELDS = ("verifications", "recommendations", "interviews", "placements")
DL_FIELDS = ("requests", "placements", "vacancies", "open_requests", "open_vacancies")
# Wartość nowego wiersza, gdy pole zostało puste (jak domyślne w tabelach).
WEEK_DEFAULTS = {**{f: 0 for f in WEEK_FIELDS}, "days_worked": 5}
MAX_COUNT = 10_000
# Luki do zakładki „Braki”: tygodnie rekruterów i wpisy DL od tego miesiąca.
GAPS_FROM = date(2025, 1, 1)
# Miesiące rozliczone i zamrożone (Liga Mistrzów, wyścigi, Liga DL Q1–Q3).
SETTLED_UNTIL = date(2026, 10, 1)
SETTLED_NOTE = (
    "Miesiące 1–9.2026 są rozliczone i zamrożone (Liga Mistrzów i wyścigi — "
    "paragon dynareporter_settlement_2026, Liga DL Q1–Q3 — "
    "dynareporter_dl_league_2026): zmiana wpisu zmienia statystyki, "
    "nie zamrożone wyniki konkursów."
)


class InputError(ValueError):
    """Dane wejściowe nie nadają się do zapisu — nic nie zapisujemy."""


def _month_key(day: date) -> str:
    return day.isoformat()[:7]


class _Rows:
    """Walidacja jednej sekcji: zbiera wszystkie błędy, zamiast stawać na pierwszym."""

    def __init__(self, errors: list[str], section: str) -> None:
        self.errors = errors
        self.section = section

    def fail(self, index: int, message: str) -> None:
        self.errors.append(f"{self.section}[{index}]: {message}")

    def user(self, index: int, row: dict) -> Optional[int]:
        value = row.get("user_id")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            self.fail(index, "brak id konta NEXUS-a (user_id)")
            return None
        return value

    def day(self, index: int, row: dict, field: str) -> Optional[date]:
        try:
            return date.fromisoformat(str(row[field]))
        except (KeyError, TypeError, ValueError):
            self.fail(index, f"{field}: oczekiwano daty RRRR-MM-DD")
            return None

    def month(self, index: int, row: dict, field: str) -> Optional[date]:
        raw = str(row.get(field) or "")
        try:
            if len(raw) == 7:
                return date.fromisoformat(f"{raw}-01")
            day = date.fromisoformat(raw)
        except ValueError:
            day = None
        if day is None or day.day != 1:
            self.fail(index, f"{field}: oczekiwano miesiąca RRRR-MM")
            return None
        return day

    def count(
        self, index: int, row: dict, field: str, *, required: bool = False
    ) -> Optional[int]:
        value = row.get(field)
        if value is None:
            if required:
                self.fail(index, f"{field}: brak liczby")
            return None
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= MAX_COUNT
        ):
            self.fail(index, f"{field}: oczekiwano liczby całkowitej 0–{MAX_COUNT}")
            return None
        return value

    def name(self, index: int, row: dict, field: str) -> Optional[str]:
        value = str(row.get(field) or "").strip()
        if not value or len(value) > 255:
            self.fail(index, f"{field}: brak nazwy klienta")
            return None
        return value


def _cutover_refusal(day: date) -> str:
    return (
        f"{day.isoformat()} — od {history.RESULTS_CUTOVER.isoformat()} liczy "
        "NEXUS, tych dni nie uzupełniamy"
    )


def _parse_weeks(rows: list, errors: list[str]) -> list[dict]:
    v = _Rows(errors, "weeks")
    out: list[dict] = []
    seen: dict[tuple[int, date], int] = {}
    week_of: dict[tuple[int, tuple[int, int], str], date] = {}
    for i, row in enumerate(rows):
        uid, day = v.user(i, row), v.day(i, row, "report_date")
        counts = {f: v.count(i, row, f) for f in WEEK_FIELDS}
        days_worked = v.count(i, row, "days_worked")
        if days_worked is not None and days_worked > 7:
            v.fail(i, "days_worked: najwyżej 7 dni w tygodniu")
        if uid is None or day is None:
            continue
        if day >= history.RESULTS_CUTOVER:
            v.fail(i, _cutover_refusal(day))
            continue
        if day.weekday() >= 5:
            v.fail(
                i,
                f"{day.isoformat()} to dzień wolny — wpis zaczyna się w dzień roboczy",
            )
            continue
        if all(c is None for c in counts.values()) and days_worked is None:
            v.fail(i, "wiersz bez żadnej liczby")
            continue
        if (uid, day) in seen:
            v.fail(i, f"ten sam wpis co weeks[{seen[(uid, day)]}]")
            continue
        seen[(uid, day)] = i
        iso_week = day.isocalendar()[:2]
        other = week_of.setdefault((uid, iso_week, _month_key(day)), day)
        if other != day:
            v.fail(
                i,
                f"drugi wpis tego samego tygodnia i miesiąca ({other.isoformat()}) — "
                "tydzień ma jeden wpis, a przez koniec miesiąca dwa",
            )
            continue
        out.append(
            {
                "user_id": uid,
                "report_date": day,
                "week_number": day.isocalendar()[1],
                **counts,
                "days_worked": days_worked,
            }
        )
    return out


def _parse_placements(rows: list, errors: list[str]) -> list[dict]:
    v = _Rows(errors, "placements")
    out: list[dict] = []
    seen: dict[tuple[int, date, str], int] = {}
    for i, row in enumerate(rows):
        uid, day = v.user(i, row), v.day(i, row, "placement_date")
        client = v.name(i, row, "client")
        count = 1 if row.get("count") is None else v.count(i, row, "count")
        if uid is None or day is None or client is None or count is None:
            continue
        if day >= history.RESULTS_CUTOVER:
            v.fail(i, _cutover_refusal(day))
            continue
        if day < history.DR_HISTORY_START:
            v.fail(
                i,
                f"{day.isoformat()} — przed 2026 klientów liczy raport Rady: "
                "wpisz placementy klienta w miesiącu (board_clients)",
            )
            continue
        key = (uid, day, client.lower())
        if key in seen:
            v.fail(i, f"ten sam placement co placements[{seen[key]}] — podaj liczbę")
            continue
        seen[key] = i
        out.append(
            {"user_id": uid, "placement_date": day, "client": client, "count": count}
        )
    return out


def _parse_dl_months(rows: list, errors: list[str]) -> list[dict]:
    v = _Rows(errors, "dl_months")
    out: list[dict] = []
    seen: dict[tuple[int, date], int] = {}
    last_month = history.RESULTS_CUTOVER.replace(day=1)
    for i, row in enumerate(rows):
        uid, month = v.user(i, row), v.month(i, row, "report_month")
        counts = {f: v.count(i, row, f) for f in DL_FIELDS}
        if uid is None or month is None:
            continue
        if month > last_month:
            v.fail(i, _cutover_refusal(month))
            continue
        if all(c is None for c in counts.values()):
            v.fail(i, "wiersz bez żadnej liczby")
            continue
        if (uid, month) in seen:
            v.fail(i, f"ten sam miesiąc co dl_months[{seen[(uid, month)]}]")
            continue
        seen[(uid, month)] = i
        out.append({"user_id": uid, "report_month": month, **counts})
    return out


def _before_2026(v: _Rows, index: int, month: date) -> bool:
    if month < history.DR_HISTORY_START:
        return True
    v.fail(
        index,
        f"{_month_key(month)} — od 2026 placementy firmy i klientów liczą się "
        "z tygodni rekruterów (weeks) i placementów z klientem (placements)",
    )
    return False


def _parse_board_months(rows: list, errors: list[str]) -> list[dict]:
    v = _Rows(errors, "board_months")
    out: list[dict] = []
    seen: dict[date, int] = {}
    for i, row in enumerate(rows):
        month = v.month(i, row, "report_month")
        placements = v.count(i, row, "placements", required=True)
        if month is None or placements is None or not _before_2026(v, i, month):
            continue
        if month in seen:
            v.fail(i, f"ten sam miesiąc co board_months[{seen[month]}]")
            continue
        seen[month] = i
        out.append({"report_month": month, "placements": placements})
    return out


def _parse_board_clients(rows: list, errors: list[str]) -> list[dict]:
    v = _Rows(errors, "board_clients")
    out: list[dict] = []
    seen: dict[tuple[date, str], int] = {}
    for i, row in enumerate(rows):
        month = v.month(i, row, "report_month")
        client = v.name(i, row, "client_name")
        count = v.count(i, row, "placement_count", required=True)
        if month is None or client is None or count is None:
            continue
        if not _before_2026(v, i, month):
            continue
        key = (month, client.lower())
        if key in seen:
            v.fail(i, f"ten sam klient i miesiąc co board_clients[{seen[key]}]")
            continue
        seen[key] = i
        out.append(
            {"report_month": month, "client_name": client, "placement_count": count}
        )
    return out


_PARSERS = {
    "weeks": _parse_weeks,
    "placements": _parse_placements,
    "dl_months": _parse_dl_months,
    "board_months": _parse_board_months,
    "board_clients": _parse_board_clients,
}


def parse_payload(payload: Any) -> dict[str, list[dict]]:
    """Waliduje wejście bez bazy. Odmawia całości przy pierwszym błędnym wierszu."""
    if not isinstance(payload, dict):
        raise InputError("wejście to obiekt JSON z sekcjami " + ", ".join(SECTIONS))
    unknown = sorted(set(payload) - set(SECTIONS))
    if unknown:
        raise InputError(f"nieznane sekcje: {unknown}")
    errors: list[str] = []
    parsed: dict[str, list[dict]] = {}
    for section, parser in _PARSERS.items():
        rows = payload.get(section) or []
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            errors.append(f"{section}: oczekiwano listy wierszy")
            parsed[section] = []
            continue
        parsed[section] = parser(rows, errors)
    if errors:
        raise InputError("; ".join(errors))
    if not any(parsed.values()):
        raise InputError("brak wierszy do wgrania")
    return parsed


# ── Baza ────────────────────────────────────────────────────────────────


async def _rows(db, sql: str, params: Optional[dict] = None) -> list:
    return (await db.execute(text(sql), params or {})).mappings().all()


async def _check_accounts(db, parsed: dict[str, list[dict]]) -> None:
    ids = sorted(
        {r["user_id"] for s in ("weeks", "placements", "dl_months") for r in parsed[s]}
    )
    if not ids:
        return
    found = {
        r["id"]: r["dynareporter_legacy_id"]
        for r in await _rows(
            db,
            "SELECT id, dynareporter_legacy_id FROM users WHERE id = ANY(:ids)",
            {"ids": ids},
        )
    }
    missing = [i for i in ids if i not in found]
    if missing:
        raise InputError(f"konta bez odpowiednika w NEXUS-ie: {missing}")
    duplicates = [i for i in ids if found[i] is not None]
    if duplicates:
        # Konta z `dynareporter_legacy_id` to nieaktywne duplikaty sprzed
        # scalenia — wpis na nich rozdzieliłby wynik jednej osoby na dwa konta.
        raise InputError(f"konta-duplikaty z DynaReportera: {duplicates}")


async def _resolve_clients(db, parsed: dict[str, list[dict]]) -> dict[str, dict]:
    """Nazwa klienta → klient DynaReportera albo NEXUS-a (bez wielkości liter).

    Statystyki łączą klienta DynaReportera z klientem NEXUS-a po nazwie
    (`history_client_placements`), więc nazwa spoza obu list byłaby osobnym
    wycinkiem z literówką — odmawiamy.
    """
    names = {r["client"].lower() for r in parsed["placements"]} | {
        r["client_name"].lower() for r in parsed["board_clients"]
    }
    if not names:
        return {}
    resolved: dict[str, dict] = {}
    for r in await _rows(
        db,
        "SELECT id, name FROM dr_clients WHERE lower(name) = ANY(:names) ORDER BY id",
        {"names": sorted(names)},
    ):
        resolved.setdefault(
            r["name"].lower(), {"dr_client_id": r["id"], "name": r["name"]}
        )
    for r in await _rows(
        db,
        """
        SELECT DISTINCT ON (lower(client_name)) client_name AS name
        FROM dr_board_placement_clients
        WHERE lower(client_name) = ANY(:names)
        ORDER BY lower(client_name), report_month DESC
        """,
        {"names": sorted(names - set(resolved))},
    ):
        resolved.setdefault(
            r["name"].lower(), {"dr_client_id": None, "name": r["name"]}
        )
    for r in await _rows(
        db,
        """
        SELECT c.name, lower(c.name) AS k1, lower(c.display_name) AS k2
        FROM clients c
        WHERE c.deleted_at IS NULL
          AND (lower(c.name) = ANY(:names) OR lower(c.display_name) = ANY(:names))
        ORDER BY c.id
        """,
        {"names": sorted(names - set(resolved))},
    ):
        for key in (r["k1"], r["k2"]):
            if key in names:
                resolved.setdefault(key, {"dr_client_id": None, "name": r["name"]})
    unknown = sorted(names - set(resolved))
    if unknown:
        raise InputError(
            f"nieznani klienci (ani w DynaReporterze, ani w NEXUS-ie): {unknown}"
        )
    return resolved


async def _check_week_starts(db, weeks: list[dict]) -> None:
    """Ten sam tydzień i miesiąc nie może mieć drugiego wpisu z innym dniem."""
    if not weeks:
        return
    existing: dict[tuple[int, tuple[int, int], str], date] = {}
    for r in await _rows(
        db,
        """
        SELECT user_id, report_date FROM dr_kpi_body_leasing
        WHERE is_draft IS FALSE AND user_id = ANY(:ids) AND report_date < :cut
        """,
        {"ids": sorted({w["user_id"] for w in weeks}), "cut": history.RESULTS_CUTOVER},
    ):
        day = r["report_date"]
        existing[(r["user_id"], day.isocalendar()[:2], _month_key(day))] = day
    clashes = []
    for w in weeks:
        day = w["report_date"]
        other = existing.get((w["user_id"], day.isocalendar()[:2], _month_key(day)))
        if other is not None and other != day:
            clashes.append(
                f"konto {w['user_id']}: {day.isoformat()} — ten tydzień ma już wpis "
                f"od {other.isoformat()}"
            )
    if clashes:
        raise InputError("; ".join(clashes))


def _merge(
    before: Optional[dict], new: dict, fields: tuple[str, ...], defaults: dict
) -> dict:
    return {
        f: (
            new[f]
            if new.get(f) is not None
            else (before[f] if before is not None else defaults.get(f, 0))
        )
        for f in fields
    }


def _plan_row(key: dict, before: Optional[dict], after: dict) -> Optional[dict]:
    if before == after:
        return None
    return {**key, "before": before, "after": after}


async def _plan(db, parsed: dict[str, list[dict]], clients: dict[str, dict]) -> dict:
    """Co się zmieni: wiersz po wierszu, przed → po (bez zapisu)."""
    plan: dict[str, list[dict]] = {s: [] for s in SECTIONS}
    unchanged: Counter = Counter()

    week_fields = (*WEEK_FIELDS, "days_worked")
    if parsed["weeks"]:
        stored = {
            (r["user_id"], r["report_date"]): {f: int(r[f] or 0) for f in week_fields}
            for r in await _rows(
                db,
                """
                SELECT user_id, report_date, verifications, recommendations,
                       interviews, placements, days_worked
                FROM dr_kpi_body_leasing
                WHERE is_draft IS FALSE AND user_id = ANY(:ids)
                  AND report_date = ANY(:days)
                """,
                {
                    "ids": sorted({w["user_id"] for w in parsed["weeks"]}),
                    "days": sorted({w["report_date"] for w in parsed["weeks"]}),
                },
            )
        }
        for w in parsed["weeks"]:
            before = stored.get((w["user_id"], w["report_date"]))
            after = _merge(before, w, week_fields, WEEK_DEFAULTS)
            row = _plan_row(
                {
                    "user_id": w["user_id"],
                    "report_date": w["report_date"],
                    "week_number": w["week_number"],
                },
                before,
                after,
            )
            if row:
                plan["weeks"].append(row)
            else:
                unchanged["weeks"] += 1

    if parsed["placements"]:
        stored_counts = Counter(
            {
                (r["user_id"], r["placement_date"], r["client_id"]): int(r["n"])
                for r in await _rows(
                    db,
                    """
                    SELECT user_id, placement_date, client_id, count(*) AS n
                    FROM dr_placement_details
                    WHERE user_id = ANY(:ids) AND placement_date = ANY(:days)
                    GROUP BY 1, 2, 3
                    """,
                    {
                        "ids": sorted({p["user_id"] for p in parsed["placements"]}),
                        "days": sorted(
                            {p["placement_date"] for p in parsed["placements"]}
                        ),
                    },
                )
            }
        )
        for p in parsed["placements"]:
            client = clients[p["client"].lower()]
            before = stored_counts[
                (p["user_id"], p["placement_date"], client["dr_client_id"])
            ]
            if before == p["count"]:
                unchanged["placements"] += 1
                continue
            plan["placements"].append(
                {
                    "user_id": p["user_id"],
                    "placement_date": p["placement_date"],
                    "client": client["name"],
                    "dr_client_id": client["dr_client_id"],
                    "before": before,
                    "after": p["count"],
                }
            )

    if parsed["dl_months"]:
        stored = {
            (r["user_id"], r["report_month"]): {f: int(r[f] or 0) for f in DL_FIELDS}
            for r in await _rows(
                db,
                """
                SELECT user_id, report_month, requests, placements, vacancies,
                       open_requests, open_vacancies
                FROM dr_kpi_delivery_lead
                WHERE user_id = ANY(:ids) AND report_month = ANY(:months)
                """,
                {
                    "ids": sorted({d["user_id"] for d in parsed["dl_months"]}),
                    "months": sorted({d["report_month"] for d in parsed["dl_months"]}),
                },
            )
        }
        for d in parsed["dl_months"]:
            before = stored.get((d["user_id"], d["report_month"]))
            row = _plan_row(
                {"user_id": d["user_id"], "report_month": d["report_month"]},
                before,
                _merge(before, d, DL_FIELDS, {}),
            )
            if row:
                plan["dl_months"].append(row)
            else:
                unchanged["dl_months"] += 1

    if parsed["board_months"]:
        stored = {
            r["report_month"]: int(r["placements"] or 0)
            for r in await _rows(
                db,
                "SELECT report_month, placements FROM dr_board_monthly_report "
                "WHERE report_month = ANY(:months)",
                {"months": [b["report_month"] for b in parsed["board_months"]]},
            )
        }
        for b in parsed["board_months"]:
            before = stored.get(b["report_month"])
            if before == b["placements"]:
                unchanged["board_months"] += 1
                continue
            plan["board_months"].append(
                {
                    "report_month": b["report_month"],
                    "before": before,
                    "after": b["placements"],
                }
            )

    if parsed["board_clients"]:
        stored_counts = Counter(
            {
                (r["report_month"], r["k"]): int(r["n"])
                for r in await _rows(
                    db,
                    """
                    SELECT report_month, lower(client_name) AS k,
                           sum(placement_count) AS n
                    FROM dr_board_placement_clients
                    WHERE report_month = ANY(:months)
                    GROUP BY 1, 2
                    """,
                    {
                        "months": sorted(
                            {b["report_month"] for b in parsed["board_clients"]}
                        )
                    },
                )
            }
        )
        for b in parsed["board_clients"]:
            name = clients[b["client_name"].lower()]["name"]
            before = stored_counts[(b["report_month"], name.lower())]
            if before == b["placement_count"]:
                unchanged["board_clients"] += 1
                continue
            plan["board_clients"].append(
                {
                    "report_month": b["report_month"],
                    "client_name": name,
                    "before": before,
                    "after": b["placement_count"],
                }
            )
    return {"rows": plan, "unchanged": unchanged}


def _months_summary(plan: dict[str, list[dict]]) -> dict[str, dict]:
    """Suma przed → po w miesiącu, tylko dla zmienionych pól."""
    out: dict[str, dict] = {}
    for section, day_key, fields in (
        ("weeks", "report_date", (*WEEK_FIELDS, "days_worked")),
        ("dl_months", "report_month", DL_FIELDS),
    ):
        sums: dict[str, dict[str, list[int]]] = defaultdict(
            lambda: defaultdict(lambda: [0, 0])
        )
        for row in plan[section]:
            month = _month_key(row[day_key])
            for f in fields:
                sums[month][f][0] += (row["before"] or {}).get(f, 0)
                sums[month][f][1] += row["after"][f]
        out[section] = {
            m: {f: v for f, v in per.items() if v[0] != v[1]}
            for m, per in sorted(sums.items())
        }
    for section, day_key in (
        ("placements", "placement_date"),
        ("board_months", "report_month"),
        ("board_clients", "report_month"),
    ):
        sums2: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for row in plan[section]:
            month = _month_key(row[day_key])
            sums2[month][0] += row["before"] or 0
            sums2[month][1] += row["after"]
        out[section] = dict(sorted(sums2.items()))
    return out


def _report(plan: dict, receipt: Optional[str]) -> dict[str, Any]:
    rows = plan["rows"]
    settled = sorted(
        {
            _month_key(r[k])
            for s, k in (("weeks", "report_date"), ("dl_months", "report_month"))
            for r in rows[s]
            if history.DR_HISTORY_START <= r[k] < SETTLED_UNTIL
        }
    )
    report: dict[str, Any] = {
        "cutover": history.RESULTS_CUTOVER.isoformat(),
        "applied": receipt is not None,
        "changes": {s: len(rows[s]) for s in SECTIONS},
        "unchanged": {s: plan["unchanged"][s] for s in SECTIONS},
        "new_dr_clients": sorted(
            {r["client"] for r in rows["placements"] if r["dr_client_id"] is None}
        ),
        "months": _months_summary(rows),
        "rows": rows,
    }
    if settled:
        report["settled_months_touched"] = settled
        report["settled_note"] = SETTLED_NOTE
    if receipt:
        report["receipt"] = receipt
    return report


async def _write(db, rows: dict[str, list[dict]], receipt: str) -> None:
    for w in rows["weeks"]:
        params = {
            "user_id": w["user_id"],
            "report_date": w["report_date"],
            "week_number": w["week_number"],
            **w["after"],
        }
        if w["before"] is None:
            await db.execute(
                text(
                    """
                    INSERT INTO dr_kpi_body_leasing
                        (user_id, report_date, week_number, verifications,
                         recommendations, interviews, placements, days_worked,
                         is_draft)
                    VALUES (:user_id, :report_date, :week_number, :verifications,
                            :recommendations, :interviews, :placements,
                            :days_worked, false)
                    """
                ),
                params,
            )
        else:
            await db.execute(
                text(
                    """
                    UPDATE dr_kpi_body_leasing
                    SET verifications = :verifications,
                        recommendations = :recommendations,
                        interviews = :interviews,
                        placements = :placements,
                        days_worked = :days_worked
                    WHERE user_id = :user_id AND report_date = :report_date
                      AND is_draft IS FALSE
                    """
                ),
                params,
            )

    created: dict[str, int] = {}
    for p in rows["placements"]:
        client_id = p["dr_client_id"]
        if client_id is None:
            key = p["client"].lower()
            if key not in created:
                created[key] = (
                    await db.execute(
                        text(
                            "INSERT INTO dr_clients (name, is_active) "
                            "VALUES (:name, true) RETURNING id"
                        ),
                        {"name": p["client"]},
                    )
                ).scalar_one()
            client_id = created[key]
        params = {
            "user_id": p["user_id"],
            "client_id": client_id,
            "placement_date": p["placement_date"],
        }
        if p["after"] > p["before"]:
            for _ in range(p["after"] - p["before"]):
                await db.execute(
                    text(
                        """
                        INSERT INTO dr_placement_details
                            (user_id, client_id, placement_date, week_number, notes)
                        VALUES (:user_id, :client_id, :placement_date, :week_number,
                                :notes)
                        """
                    ),
                    {
                        **params,
                        "week_number": p["placement_date"].isocalendar()[1],
                        "notes": receipt,
                    },
                )
        else:
            # Najpierw znikają najmłodsze wiersze — oryginał z DynaReportera zostaje.
            await db.execute(
                text(
                    """
                    DELETE FROM dr_placement_details
                    WHERE id IN (
                        SELECT id FROM dr_placement_details
                        WHERE user_id = :user_id AND client_id = :client_id
                          AND placement_date = :placement_date
                        ORDER BY id DESC
                        LIMIT :n
                    )
                    """
                ),
                {**params, "n": p["before"] - p["after"]},
            )

    for d in rows["dl_months"]:
        params = {
            "user_id": d["user_id"],
            "report_month": d["report_month"],
            **d["after"],
        }
        await db.execute(
            text(
                """
                INSERT INTO dr_kpi_delivery_lead
                    (user_id, report_month, requests, placements, vacancies,
                     open_requests, open_vacancies)
                VALUES (:user_id, :report_month, :requests, :placements, :vacancies,
                        :open_requests, :open_vacancies)
                ON CONFLICT (user_id, report_month) DO UPDATE
                SET requests = EXCLUDED.requests,
                    placements = EXCLUDED.placements,
                    vacancies = EXCLUDED.vacancies,
                    open_requests = EXCLUDED.open_requests,
                    open_vacancies = EXCLUDED.open_vacancies,
                    updated_at = now()
                """
            ),
            params,
        )

    for b in rows["board_months"]:
        await db.execute(
            text(
                """
                INSERT INTO dr_board_monthly_report (report_month, placements)
                VALUES (:report_month, :placements)
                ON CONFLICT (report_month) DO UPDATE
                SET placements = EXCLUDED.placements, updated_at = now()
                """
            ),
            {"report_month": b["report_month"], "placements": b["after"]},
        )

    for b in rows["board_clients"]:
        params = {"report_month": b["report_month"], "name": b["client_name"]}
        await db.execute(
            text(
                "DELETE FROM dr_board_placement_clients "
                "WHERE report_month = :report_month AND lower(client_name) = lower(:name)"
            ),
            params,
        )
        if b["after"] > 0:
            await db.execute(
                text(
                    """
                    INSERT INTO dr_board_placement_clients
                        (report_month, client_name, placement_count)
                    VALUES (:report_month, :name, :n)
                    """
                ),
                {**params, "n": b["after"]},
            )


async def run(payload: Any, *, apply: bool) -> dict[str, Any]:
    from app.core.database import AsyncSessionLocal

    parsed = parse_payload(payload)
    async with AsyncSessionLocal() as db:
        if not apply:
            await db.execute(text("SET TRANSACTION READ ONLY"))
        await _check_accounts(db, parsed)
        clients = await _resolve_clients(db, parsed)
        await _check_week_starts(db, parsed["weeks"])
        plan = await _plan(db, parsed, clients)
        if not apply:
            return _report(plan, None)

        now = datetime.now(tz=ZoneInfo(DEFAULT_TZ))
        receipt = f"{RECEIPT_PREFIX}{now:%Y%m%d-%H%M%S-%f}"
        report = _report(plan, receipt)
        await _write(db, plan["rows"], receipt)
        await db.execute(
            text(
                "INSERT INTO app_settings (key, value) VALUES (:k, CAST(:v AS jsonb))"
            ),
            {
                "k": receipt,
                "v": json.dumps({"applied_at": now.isoformat(), **report}, default=str),
            },
        )
        await db.commit()
        return report


# ── Luki i listy do arkusza ─────────────────────────────────────────────


async def gaps() -> dict[str, Any]:
    """Luki do zakładki „Braki” — same id i liczby, bez nazwisk."""
    from app.core.database import AsyncSessionLocal

    cut = history.RESULTS_CUTOVER
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        months = await _rows(
            db,
            """
            SELECT m::date AS month,
                   (SELECT count(*) FROM dr_kpi_body_leasing k
                    WHERE k.is_draft IS FALSE AND k.report_date >= m
                      AND k.report_date < m + INTERVAL '1 month') AS weeks,
                   (SELECT count(*) FROM dr_kpi_delivery_lead d
                    WHERE d.report_month = m) AS dl_entries,
                   (SELECT b.placements FROM dr_board_monthly_report b
                    WHERE b.report_month = m) AS board_placements
            FROM generate_series(CAST(:start AS date), CAST(:last AS date),
                                 INTERVAL '1 month') m
            ORDER BY 1
            """,
            {"start": GAPS_FROM, "last": cut.replace(day=1)},
        )
        dl_missing = await _rows(
            db,
            """
            WITH dls AS (
                SELECT u.id FROM users u
                WHERE u.is_active IS TRUE AND u.dynareporter_legacy_id IS NULL
                  AND (u.role::text = 'delivery_lead' OR u.roles ? 'delivery_lead'
                       OR EXISTS (SELECT 1 FROM dr_kpi_delivery_lead d
                                  WHERE d.user_id = u.id
                                    AND d.report_month >= :dr_start))
            )
            SELECT dls.id AS user_id, m::date AS month
            FROM dls
            CROSS JOIN generate_series(CAST(:dr_start AS date), CAST(:last AS date),
                                       INTERVAL '1 month') m
            WHERE NOT EXISTS (SELECT 1 FROM dr_kpi_delivery_lead d
                              WHERE d.user_id = dls.id AND d.report_month = m)
            ORDER BY 1, 2
            """,
            {"dr_start": history.DR_HISTORY_START, "last": cut.replace(day=1)},
        )
        # Tygodnie 1–11.10.2026: osoby z wpisami we wrześniu, bez wpisu w części
        # tygodnia 28.09–4.10 od 1.10 albo w tygodniu 5–11.10.
        october_missing = await _rows(
            db,
            """
            WITH people AS (
                SELECT DISTINCT k.user_id FROM dr_kpi_body_leasing k
                JOIN users u ON u.id = k.user_id
                WHERE k.is_draft IS FALSE AND u.is_active IS TRUE
                  AND k.report_date >= :september AND k.report_date < :october
            ),
            parts (start_day, end_day) AS (
                VALUES (CAST(:october AS date), CAST(:october AS date) + 4),
                       (CAST(:october AS date) + 4, CAST(:cut AS date))
            )
            SELECT people.user_id, parts.start_day AS report_date
            FROM people CROSS JOIN parts
            WHERE NOT EXISTS (SELECT 1 FROM dr_kpi_body_leasing k
                              WHERE k.user_id = people.user_id
                                AND k.is_draft IS FALSE
                                AND k.report_date >= parts.start_day
                                AND k.report_date < parts.end_day)
            ORDER BY 1, 2
            """,
            {
                "september": date(2026, 9, 1),
                "october": cut.replace(day=1),
                "cut": cut,
            },
        )
    return {
        "cutover": cut.isoformat(),
        "months": [
            {
                "month": _month_key(r["month"]),
                "weeks": int(r["weeks"]),
                "dl_entries": int(r["dl_entries"]),
                "board_placements": (
                    None
                    if r["board_placements"] is None
                    else int(r["board_placements"])
                ),
            }
            for r in months
        ],
        "dl_missing": [
            {"user_id": r["user_id"], "month": _month_key(r["month"])}
            for r in dl_missing
        ],
        "recruiter_october_missing": [
            {"user_id": r["user_id"], "report_date": r["report_date"].isoformat()}
            for r in october_missing
        ],
    }


async def lists() -> dict[str, Any]:
    """Konta i klienci do list wyboru arkusza — Z NAZWISKAMI, tylko do pliku."""
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        # Mapa kont jak przy wgraniu historii: aktywne konto, a osoby, które
        # odeszły — konto z importu Traffita (id < 160); duplikaty z
        # DynaReportera (`dynareporter_legacy_id`) pomijamy.
        people = await _rows(
            db,
            """
            SELECT u.id, u.name, u.role::text AS role, u.is_active
            FROM users u
            WHERE u.dynareporter_legacy_id IS NULL
              AND (u.is_active IS TRUE OR u.id < 160
                   OR EXISTS (SELECT 1 FROM dr_kpi_body_leasing k WHERE k.user_id = u.id)
                   OR EXISTS (SELECT 1 FROM dr_kpi_delivery_lead d WHERE d.user_id = u.id))
            ORDER BY u.is_active DESC, u.name, u.id
            """,
        )
        clients = await _rows(
            db,
            """
            SELECT name FROM dr_clients
            UNION
            SELECT client_name FROM dr_board_placement_clients
            ORDER BY 1
            """,
        )
    return {
        "people": [
            {
                "id": r["id"],
                "name": r["name"],
                "role": r["role"],
                "active": r["is_active"],
            }
            for r in people
        ],
        "clients": [r["name"] for r in clients],
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply", action="store_true", help="zapisz (domyślnie na sucho)"
    )
    mode.add_argument("--gaps", action="store_true", help="luki do zakładki „Braki”")
    mode.add_argument(
        "--lists", action="store_true", help="konta i klienci do arkusza (z nazwiskami)"
    )
    args = parser.parse_args(argv)
    try:
        if args.gaps:
            result = asyncio.run(gaps())
        elif args.lists:
            result = asyncio.run(lists())
        else:
            result = asyncio.run(run(json.load(sys.stdin), apply=args.apply))
    except (InputError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
