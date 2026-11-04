"""Liga Mistrzów DL za Q1–Q3 2026 z wpisów Delivery Leadów w DynaReporterze.

Decyzja Artura 18.10.2026: przed 12.10.2026 statystyki biorą wyłącznie
DynaReportera, także Liga DL — zamrożone podia Q2 i Q3 policzone z ruchów
Tablicy (import Traffita) przeliczamy z miesięcznych wpisów DL
(`dr_kpi_delivery_lead`, wgrane `scripts.load_dynareporter_history`).
Reguła (`competition_history.dr_dl_league`): placementy z wpisów, próg
3 placementów, bez progu hit ratio (DynaReporter nie prowadził rekrutacji
zamkniętych). Remis na płatnym miejscu → `tie_pending`, decyduje admin.

Dane czyta z bazy — bez wejścia na stdin::

    docker exec -i <backend> python -m scripts.settle_dl_league_from_dynareporter
    docker exec -i <backend> python -m scripts.settle_dl_league_from_dynareporter --apply

Bez `--apply` nic nie zapisuje (porównanie „dziś → po rozliczeniu”, same ID).
`--apply` w jednej transakcji, paragon `dynareporter_dl_league_2026` ze stanem
sprzed podmiany; odmawia, gdy paragon już jest.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import delete, select, text  # noqa: E402

from app.core.scheduling import DEFAULT_TZ  # noqa: E402
from app.services import competition_history as history  # noqa: E402
from scripts.settle_competitions_from_dynareporter import (  # noqa: E402
    _current_state,
)

RECEIPT_KEY = "dynareporter_dl_league_2026"
LEAGUE = "quarterly_champions_dl"


class InputError(ValueError):
    """Stan bazy nie pozwala rozliczyć — nic nie zapisujemy."""


def settlement_periods() -> list[str]:
    """Kwartały 2026 zakończone przed cutoverem (Q1–Q3)."""
    out = []
    for quarter in range(1, 5):
        last = quarter * 3
        end = date(2026, last + 1, 1) if last < 12 else date(2027, 1, 1)
        if end <= history.RESULTS_CUTOVER:
            out.append(f"Q{quarter} 2026")
    return out


async def _monthly(db) -> dict[str, dict[int, history.DrCounts]]:
    rows = (
        await db.execute(
            text(
                """
                SELECT user_id, report_month, placements
                FROM dr_kpi_delivery_lead
                WHERE report_month >= :first AND report_month < :cut
                """
            ),
            {"first": history.DR_HISTORY_START, "cut": history.RESULTS_CUTOVER},
        )
    ).all()
    monthly: dict[str, dict[int, history.DrCounts]] = {}
    for r in rows:
        month = r.report_month.isoformat()[:7]
        bucket = monthly.setdefault(month, {})
        bucket[r.user_id] = bucket.get(r.user_id, history.DrCounts()).plus(
            history.DrCounts(placements=int(r.placements or 0))
        )
    return monthly


async def run(*, apply: bool) -> dict[str, Any]:
    from app.core.database import AsyncSessionLocal
    from app.models.competition_period_closure import CompetitionPeriodClosure
    from app.models.competition_winner import CompetitionType, CompetitionWinner
    from app.models.user import User
    from app.services import competitions

    async with AsyncSessionLocal() as db:
        loaded = (
            await db.execute(
                text("SELECT 1 FROM app_settings WHERE key = :k"),
                {"k": "dynareporter_history_load_2026"},
            )
        ).scalar_one_or_none()
        if not loaded:
            raise InputError(
                "brak paragonu dynareporter_history_load_2026 — najpierw "
                "scripts.load_dynareporter_history --apply"
            )
        monthly = await _monthly(db)
        user_ids = {uid for bucket in monthly.values() for uid in bucket}
        names = {
            r.id: r.name
            for r in (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(user_ids))
                )
            ).all()
        }
        settlements = [
            history.settle_dr_period(LEAGUE, period, monthly, names=names, weights={})
            for period in settlement_periods()
        ]
        report: dict[str, Any] = {"periods": []}
        before_details: dict[str, Any] = {}
        for s in settlements:
            before = await _current_state(db, s.competition_type, s.period)
            before_details[s.period] = before.pop("closure_details")
            report["periods"].append(
                {
                    "period": s.period,
                    "before": before,
                    "after": {"closure_status": s.status, "winners": s.winners},
                    "ties": [tie["user_ids"] for tie in s.details["ties"]],
                    "ranking": [
                        {"user_id": e["user_id"], "placements": e["metric_value"]}
                        for e in s.details["ranking"]
                    ],
                }
            )
        if not apply:
            report["applied"] = False
            return report

        already = (
            await db.execute(
                text("SELECT 1 FROM app_settings WHERE key = :k"), {"k": RECEIPT_KEY}
            )
        ).scalar_one_or_none()
        if already:
            raise InputError(f"paragon {RECEIPT_KEY} już istnieje")

        now = datetime.now(tz=ZoneInfo(DEFAULT_TZ)).isoformat()
        ctype = CompetitionType(LEAGUE)
        for s in settlements:
            await competitions._lock_period(db, ctype, s.period)
            await db.execute(
                delete(CompetitionWinner).where(
                    CompetitionWinner.competition_type == LEAGUE,
                    CompetitionWinner.period == s.period,
                )
            )
            await db.execute(
                delete(CompetitionPeriodClosure).where(
                    CompetitionPeriodClosure.competition_type == LEAGUE,
                    CompetitionPeriodClosure.period == s.period,
                )
            )
            snapshot = {
                key: s.details[key]
                for key in (
                    "top",
                    "freeze_reason",
                    "closure_status",
                    "excluded_user_ids",
                    "exclusion_source",
                    "exclusion_quarter",
                    "tie_break_rule",
                    "ties",
                    "source",
                    "source_note",
                )
            }
            for winner in s.winners:
                db.add(
                    CompetitionWinner(
                        competition_type=LEAGUE,
                        period=s.period,
                        user_id=winner["user_id"],
                        rank=winner["rank"],
                        metric_value=winner["metric_value"],
                        points=winner["metric_value"],
                        prize_pln=winner["prize_pln"],
                        frozen_snapshot=snapshot,
                    )
                )
            db.add(
                CompetitionPeriodClosure(
                    competition_type=LEAGUE,
                    period=s.period,
                    status=s.status,
                    details={**s.details, "frozen_at": now},
                )
            )
        receipt = {
            "applied_at": now,
            "periods": report["periods"],
            "closure_details_before": before_details,
        }
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
    try:
        report = asyncio.run(run(apply=args.apply))
    except InputError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
