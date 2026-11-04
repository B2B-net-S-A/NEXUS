"""Historia sprzed NEXUS-a: placementy z klientem, Rada i Delivery Leadzi z DynaReportera.

Decyzja Artura 18.10.2026 (`docs/claude/finanse-insights/insights-insights-parytet-z-dynareporterem-na.md`,
sekcja „Statystyki sprzed 12.10.2026 tylko z DynaReportera”): przed 12.10.2026
statystyki nie biorą ruchów Tablicy (import z Traffita), tylko DynaReportera.
Tabele `dr_*` w NEXUS-ie to kopia z maja 2026 — ten skrypt podmienia je na
komplet z bazy DynaReportera (zrzut 15.10.2026) w JEDNEJ transakcji:

* `dr_clients` — dopisuje brakujących klientów, poprawia nazwy (po `id`);
* `dr_placement_details` — placementy z klientem i rekruterem sprzed cutoveru;
* `dr_board_monthly_report` — placementy firmy, odejścia, konsultanci, hit
  ratio (po `report_month`; kwot DynaReporter nie prowadził, nie ruszamy ich);
* `dr_board_placement_clients` — placementy klientów w miesiącu;
* `dr_kpi_delivery_lead` — miesięczne wpisy Delivery Leadów;
* `dr_delivery_lead_client_assignments` — klienci Delivery Leadów.

Wejście na stdin (JSON, bez nazwisk — repo i logi są publiczne)::

    {"user_map": {"<id w DynaReporterze>": <users.id w NEXUS-ie>, ...},
     "clients": [{"id": 1, "name": "…", "is_active": true}, ...],
     "placements": [{"user_id": <id DR>, "client_id": 1,
                     "placement_date": "2026-03-02", "week_number": 10}, ...],
     "board": [{"report_month": "2025-06-01", "placements": 18, "departures": 17,
                "active_consultants": 369, "hit_ratio": 0}, ...],
     "board_clients": [{"report_month": "2025-06-01", "client_name": "…",
                        "placement_count": 4}, ...],
     "dl_kpi": [{"user_id": <id DR>, "report_month": "2026-03-01", "requests": 3,
                 "placements": 2, "vacancies": 4, "open_requests": 5,
                 "open_vacancies": 6}, ...],
     "dl_assignments": [{"delivery_lead_user_id": <id DR>, "client_id": 13,
                         "is_head": true}, ...]}

Mapa kont nie musi być różnowartościowa: ta sama osoba miała w DynaReporterze
konto rekrutera i konto DL — wpisy DL tego samego miesiąca sumujemy.

Przebieg (kontener backendu produkcji)::

    docker exec -i <backend> python -m scripts.load_dynareporter_history < dane.json
    docker exec -i <backend> python -m scripts.load_dynareporter_history --apply < dane.json

Bez `--apply` nic nie zapisuje — wypisuje „dziś → po wgraniu” (liczby, bez
nazwisk). `--apply` odmawia, gdy paragon `dynareporter_history_load_2026` już
istnieje.
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

RECEIPT_KEY = "dynareporter_history_load_2026"
_DL_FIELDS = ("requests", "placements", "vacancies", "open_requests", "open_vacancies")


class InputError(ValueError):
    """Dane wejściowe nie nadają się do zapisu — nic nie zapisujemy."""


def _day(value: Any) -> date:
    return date.fromisoformat(str(value)[:10])


def parse_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Waliduje wejście i przekłada konta DynaReportera na konta NEXUS-a."""
    cut = history.RESULTS_CUTOVER
    try:
        user_map = {int(k): int(v) for k, v in payload["user_map"].items()}
        clients = [
            {
                "id": int(c["id"]),
                "name": str(c["name"]).strip(),
                "is_active": bool(c.get("is_active", True)),
            }
            for c in payload["clients"]
        ]
        client_ids = {c["id"] for c in clients}
        unmapped: set[int] = set()

        def account(dr_id: Any) -> Optional[int]:
            uid = user_map.get(int(dr_id))
            if uid is None:
                unmapped.add(int(dr_id))
            return uid

        placements = []
        for row in payload["placements"]:
            day = _day(row["placement_date"])
            if day >= cut:
                continue
            if int(row["client_id"]) not in client_ids:
                raise InputError(f"placement u nieznanego klienta {row['client_id']}")
            placements.append(
                {
                    "user_id": account(row["user_id"]),
                    "client_id": int(row["client_id"]),
                    "placement_date": day,
                    "week_number": (
                        int(row["week_number"]) if row.get("week_number") else None
                    ),
                }
            )
        board = [
            {
                "report_month": _day(b["report_month"]),
                "placements": int(b["placements"]),
                "departures": int(b["departures"]),
                "active_consultants": int(b["active_consultants"]),
                "hit_ratio": float(b["hit_ratio"]),
            }
            for b in payload["board"]
            if _day(b["report_month"]) < cut.replace(day=1)
        ]
        board_clients = [
            {
                "report_month": _day(b["report_month"]),
                "client_name": str(b["client_name"]).strip(),
                "placement_count": int(b["placement_count"]),
            }
            for b in payload["board_clients"]
            if _day(b["report_month"]) < cut.replace(day=1)
        ]
        dl_sums: dict[tuple[int, date], Counter] = defaultdict(Counter)
        for row in payload["dl_kpi"]:
            month = _day(row["report_month"])
            if month >= cut.replace(day=1):
                continue
            uid = account(row["user_id"])
            if uid is None:
                continue
            dl_sums[(uid, month)].update({f: int(row[f] or 0) for f in _DL_FIELDS})
        dl_kpi = [
            {"user_id": uid, "report_month": month, **{f: c[f] for f in _DL_FIELDS}}
            for (uid, month), c in sorted(dl_sums.items())
        ]
        heads: dict[tuple[int, int], bool] = {}
        for row in payload["dl_assignments"]:
            uid = account(row["delivery_lead_user_id"])
            if uid is None:
                continue
            key = (uid, int(row["client_id"]))
            heads[key] = heads.get(key, False) or bool(row.get("is_head"))
        dl_assignments = [
            {"delivery_lead_user_id": uid, "client_id": cid, "is_head": head}
            for (uid, cid), head in sorted(heads.items())
        ]
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError(f"niepoprawny format wejścia: {exc!r}") from exc
    if unmapped:
        raise InputError(f"konta DynaReportera bez konta NEXUS-a: {sorted(unmapped)}")
    if len({b["report_month"] for b in board}) != len(board):
        raise InputError("raport Rady ma dwa wiersze tego samego miesiąca")
    return {
        "clients": clients,
        "placements": placements,
        "board": board,
        "board_clients": board_clients,
        "dl_kpi": dl_kpi,
        "dl_assignments": dl_assignments,
    }


def _by_month(rows: list[dict], key: str, value: Optional[str] = None) -> dict:
    out: Counter = Counter()
    for row in rows:
        out[row[key].isoformat()[:7]] += int(row[value]) if value else 1
    return dict(sorted(out.items()))


async def _scalar(db, sql: str, params: Optional[dict] = None) -> int:
    return int((await db.execute(text(sql), params or {})).scalar_one() or 0)


async def _state(db) -> dict[str, Any]:
    cut = history.RESULTS_CUTOVER
    return {
        "dr_clients": await _scalar(db, "SELECT count(*) FROM dr_clients"),
        "dr_placement_details": await _scalar(
            db,
            "SELECT count(*) FROM dr_placement_details WHERE placement_date < :cut",
            {"cut": cut},
        ),
        "dr_board_monthly_report": await _scalar(
            db, "SELECT count(*) FROM dr_board_monthly_report"
        ),
        "dr_board_placement_clients": await _scalar(
            db, "SELECT count(*) FROM dr_board_placement_clients"
        ),
        "dr_kpi_delivery_lead": await _scalar(
            db,
            "SELECT count(*) FROM dr_kpi_delivery_lead WHERE report_month < :month",
            {"month": cut.replace(day=1)},
        ),
        "dr_delivery_lead_client_assignments": await _scalar(
            db, "SELECT count(*) FROM dr_delivery_lead_client_assignments"
        ),
    }


async def run(payload: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    from app.core.database import AsyncSessionLocal

    parsed = parse_payload(payload)
    cut = history.RESULTS_CUTOVER
    accounts = (
        {r["user_id"] for r in parsed["placements"]}
        | {r["user_id"] for r in parsed["dl_kpi"]}
        | {r["delivery_lead_user_id"] for r in parsed["dl_assignments"]}
    )
    async with AsyncSessionLocal() as db:
        found = {
            row[0]
            for row in (
                await db.execute(
                    text("SELECT id FROM users WHERE id = ANY(:ids)"),
                    {"ids": sorted(accounts)},
                )
            ).all()
        }
        missing = sorted(accounts - found)
        if missing:
            raise InputError(f"konta NEXUS-a nie istnieją: {missing}")

        report: dict[str, Any] = {
            "cutover": cut.isoformat(),
            "before": await _state(db),
            "after": {
                "dr_clients": len(parsed["clients"]),
                "dr_placement_details": len(parsed["placements"]),
                "dr_board_monthly_report_upserted": len(parsed["board"]),
                "dr_board_placement_clients_months": len(
                    {b["report_month"] for b in parsed["board_clients"]}
                ),
                "dr_kpi_delivery_lead": len(parsed["dl_kpi"]),
                "dr_delivery_lead_client_assignments": len(parsed["dl_assignments"]),
            },
            "placements_by_month": _by_month(parsed["placements"], "placement_date"),
            "board_placements_by_month": _by_month(
                parsed["board"], "report_month", "placements"
            ),
            "dl_placements_by_month": _by_month(
                parsed["dl_kpi"], "report_month", "placements"
            ),
        }
        if not apply:
            report["applied"] = False
            return report

        already = (
            await db.execute(
                text("SELECT 1 FROM app_settings WHERE key = :k"), {"k": RECEIPT_KEY}
            )
        ).scalar_one_or_none()
        if already:
            raise InputError(f"paragon {RECEIPT_KEY} już istnieje — dane były wgrane")

        for client in parsed["clients"]:
            await db.execute(
                text(
                    """
                    INSERT INTO dr_clients (id, name, is_active)
                    VALUES (:id, :name, :is_active)
                    ON CONFLICT (id) DO UPDATE
                    SET name = EXCLUDED.name, is_active = EXCLUDED.is_active
                    """
                ),
                client,
            )
        await db.execute(
            text(
                "SELECT setval('dr_clients_id_seq', "
                "GREATEST((SELECT max(id) FROM dr_clients), 1))"
            )
        )
        await db.execute(
            text("DELETE FROM dr_placement_details WHERE placement_date < :cut"),
            {"cut": cut},
        )
        for row in parsed["placements"]:
            await db.execute(
                text(
                    """
                    INSERT INTO dr_placement_details
                        (user_id, client_id, placement_date, week_number)
                    VALUES (:user_id, :client_id, :placement_date, :week_number)
                    """
                ),
                row,
            )
        for row in parsed["board"]:
            await db.execute(
                text(
                    """
                    INSERT INTO dr_board_monthly_report
                        (report_month, placements, departures, active_consultants,
                         hit_ratio)
                    VALUES (:report_month, :placements, :departures,
                            :active_consultants, :hit_ratio)
                    ON CONFLICT (report_month) DO UPDATE
                    SET placements = EXCLUDED.placements,
                        departures = EXCLUDED.departures,
                        active_consultants = EXCLUDED.active_consultants,
                        hit_ratio = EXCLUDED.hit_ratio,
                        updated_at = now()
                    """
                ),
                row,
            )
        months = sorted({b["report_month"] for b in parsed["board_clients"]})
        await db.execute(
            text(
                "DELETE FROM dr_board_placement_clients "
                "WHERE report_month = ANY(:months)"
            ),
            {"months": months},
        )
        for row in parsed["board_clients"]:
            await db.execute(
                text(
                    """
                    INSERT INTO dr_board_placement_clients
                        (report_month, client_name, placement_count)
                    VALUES (:report_month, :client_name, :placement_count)
                    """
                ),
                row,
            )
        await db.execute(
            text("DELETE FROM dr_kpi_delivery_lead WHERE report_month < :month"),
            {"month": cut.replace(day=1)},
        )
        for row in parsed["dl_kpi"]:
            await db.execute(
                text(
                    """
                    INSERT INTO dr_kpi_delivery_lead
                        (user_id, report_month, requests, placements, vacancies,
                         open_requests, open_vacancies)
                    VALUES (:user_id, :report_month, :requests, :placements,
                            :vacancies, :open_requests, :open_vacancies)
                    """
                ),
                row,
            )
        await db.execute(text("DELETE FROM dr_delivery_lead_client_assignments"))
        for row in parsed["dl_assignments"]:
            await db.execute(
                text(
                    """
                    INSERT INTO dr_delivery_lead_client_assignments
                        (delivery_lead_user_id, client_id, is_head)
                    VALUES (:delivery_lead_user_id, :client_id, :is_head)
                    """
                ),
                row,
            )

        now = datetime.now(tz=ZoneInfo(DEFAULT_TZ)).isoformat()
        receipt = {"applied_at": now, **report}
        await db.execute(
            text(
                "INSERT INTO app_settings (key, value) VALUES (:k, CAST(:v AS jsonb))"
            ),
            {"k": RECEIPT_KEY, "v": json.dumps(receipt, default=str)},
        )
        await db.commit()
        report["applied"] = True
        return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply", action="store_true", help="zapisz (domyślnie na sucho)"
    )
    args = parser.parse_args(argv)
    payload = json.load(sys.stdin)
    try:
        report = asyncio.run(run(payload, apply=args.apply))
    except InputError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
