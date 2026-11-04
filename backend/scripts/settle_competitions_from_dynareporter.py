"""Wyniki 2026 sprzed NEXUS-a: wpisy DynaReportera + rozliczenie Ligi i wyścigów.

Decyzja Artura 15.10.2026 (`docs/claude/finanse-insights/insights-insights-parytet-z-dynareporterem-na.md`,
sekcja „Wyniki 2026 sprzed NEXUS-a”):
do 11.10.2026 wynik rekrutera to jego tygodniowy wpis w DynaReporterze, od
12.10.2026 liczy NEXUS. Skrypt robi dwie rzeczy w JEDNEJ transakcji:

1. podmienia wpisy 2026 w `dr_kpi_body_leasing` na komplet z bazy DynaReportera,
   przypisany do właściwych kont NEXUS-a (stara kopia z czerwca wisiała na
   nieaktywnych duplikatach kont) — z nich Q4 2026 i październik biorą dni
   do 11.10;
2. rozlicza Ligę Mistrzów rekruterów Q1–Q3 2026 i oba wyścigi 2026-01…2026-09
   regułami DynaReportera (`competition_history.settle_dr_period`) i zapisuje
   je jako zamrożone okresy w miejsce podiów policzonych z historii Traffita.
   Remis, którego regulamin nie rozstrzyga, zostaje `tie_pending` — rozstrzyga
   admin w panelu remisów na ekranie Rywalizacja.

Wejście na stdin (JSON, same identyfikatory — repo i logi są publiczne)::

    {"mapping": {"<id w DynaReporterze>": <users.id w NEXUS-ie>, ...},
     "kpi": [{"user_id": <id DR>, "report_date": "2026-01-05", "week_number": 2,
              "verifications": 0, "recommendations": 0, "interviews": 0,
              "placements": 0, "requests": 0, "days_worked": 5, "is_draft": false,
              "linkedin_cv_added": 0, "linkedin_messages_sent": 0,
              "linkedin_responses_received": 0}, ...],
     "official": [{"competition_type": "quarterly" | "monthly_recommendations"
                   | "monthly_placements", "period": "Q1 2026" | "2026-01",
                   "rank": 1, "user_id": <id DR>}, ...],
     "weights": {"placement": 150, "interview": 15, "recommendation": 5}}

Przebieg (kontener backendu produkcji)::

    docker exec -i <backend> python -m scripts.settle_competitions_from_dynareporter < dane.json
    docker exec -i <backend> python -m scripts.settle_competitions_from_dynareporter --apply < dane.json

Bez `--apply` NIC nie zapisuje: wypisuje porównanie „dziś → po rozliczeniu”
(identyfikatory, wyniki, remisy). `--apply` odmawia, gdy paragon
`dynareporter_settlement_2026` już istnieje albo ogłoszone podium nie zgadza
się z policzonym. Cache rankingów w procesie serwera wygasa sam (do 5 min).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
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

RECEIPT_KEY = "dynareporter_settlement_2026"
FIRST_DAY = date(2026, 1, 1)
LEAGUE = "quarterly_champions_recruiter"
RACES = ("monthly_recommendations", "monthly_placements")
# Typ ligi w DynaReporterze nazywał się po prostu „quarterly”.
_OFFICIAL_TYPE = {"quarterly": LEAGUE, **{race: race for race in RACES}}
_KPI_FIELDS = (
    "verifications",
    "recommendations",
    "interviews",
    "placements",
    "requests",
    "days_worked",
    "linkedin_cv_added",
    "linkedin_messages_sent",
    "linkedin_responses_received",
)


class InputError(ValueError):
    """Dane wejściowe nie nadają się do zapisu — nic nie zapisujemy."""


def settlement_periods() -> list[tuple[str, str]]:
    """Okresy 2026 kończące się przed cutoverem: liga Q1–Q3, wyścigi I–IX."""
    out: list[tuple[str, str]] = []
    cut = history.RESULTS_CUTOVER
    for quarter in range(1, 5):
        last_month = quarter * 3
        end = date(2026, last_month + 1, 1) if last_month < 12 else date(2027, 1, 1)
        if end <= cut:
            out.append((LEAGUE, f"Q{quarter} 2026"))
    for month in range(1, 13):
        end = date(2026, month + 1, 1) if month < 12 else date(2027, 1, 1)
        if end <= cut:
            out.extend((race, f"2026-{month:02d}") for race in RACES)
    return out


def parse_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Waliduje wejście i przekłada identyfikatory DynaReportera na konta NEXUS-a."""
    try:
        mapping = {int(k): int(v) for k, v in payload["mapping"].items()}
        kpi = list(payload["kpi"])
        official = list(payload.get("official") or [])
        weights = {
            key: int(payload["weights"][key])
            for key in ("placement", "interview", "recommendation")
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise InputError(f"niepoprawny format wejścia: {exc!r}") from exc
    if len(set(mapping.values())) != len(mapping):
        raise InputError(
            "mapa kont nie jest różnowartościowa (dwie osoby → jedno konto)"
        )

    rows: list[dict[str, Any]] = []
    unmapped: set[int] = set()
    seen: set[tuple[int, date]] = set()
    # Szkice nie liczyły się też w DynaReporterze; wpisy od 12.10 liczy NEXUS.
    # Oba liczymy w raporcie, żeby nikt nie zgubił tygodnia po cichu.
    skipped = {"drafts": 0, "after_cutover": 0}
    for raw in kpi:
        day = date.fromisoformat(str(raw["report_date"])[:10])
        if day < FIRST_DAY:
            continue
        if day >= history.RESULTS_CUTOVER:
            skipped["after_cutover"] += 0 if raw.get("is_draft") else 1
            continue
        if raw.get("is_draft"):
            skipped["drafts"] += 1
            continue
        dr_user = int(raw["user_id"])
        if dr_user not in mapping:
            unmapped.add(dr_user)
            continue
        key = (mapping[dr_user], day)
        if key in seen:
            raise InputError(f"dwa wpisy tej samej osoby z dnia {day}")
        seen.add(key)
        row = {"user_id": mapping[dr_user], "report_date": day}
        row["week_number"] = int(raw.get("week_number") or day.isocalendar()[1])
        for field_name in _KPI_FIELDS:
            value = raw.get(field_name)
            row[field_name] = (
                int(value)
                if value is not None
                else (
                    history.DR_DEFAULT_DAYS_WORKED if field_name == "days_worked" else 0
                )
            )
        rows.append(row)
    if unmapped:
        raise InputError(f"wpisy osób bez konta w mapie: {sorted(unmapped)}")

    podiums: dict[tuple[str, str], list[int]] = defaultdict(list)
    for entry in sorted(
        official, key=lambda e: (e["competition_type"], e["period"], e["rank"])
    ):
        ctype = _OFFICIAL_TYPE.get(entry["competition_type"])
        if ctype is None:
            continue
        dr_user = int(entry["user_id"])
        if dr_user not in mapping:
            raise InputError(f"ogłoszony zwycięzca bez konta w mapie: {dr_user}")
        podiums[(ctype, entry["period"])].append(mapping[dr_user])
    # Ostatni okres, który DynaReporter rozliczył (także „bez zwycięzcy”).
    settled_through = {
        "quarterly": max(
            (p for (t, p) in podiums if t == LEAGUE),
            key=lambda p: (p[-4:], p[:2]),
            default=None,
        ),
        "monthly": max((p for (t, p) in podiums if t in RACES), default=None),
    }
    return {
        "rows": rows,
        "weights": weights,
        "official": dict(podiums),
        "settled_through": settled_through,
        "skipped": skipped,
    }


def monthly_counts(
    rows: list[dict[str, Any]],
) -> dict[str, dict[int, history.DrCounts]]:
    monthly: dict[str, dict[int, history.DrCounts]] = defaultdict(dict)
    for row in rows:
        month = row["report_date"].isoformat()[:7]
        counts = history.DrCounts(
            verifications=row["verifications"],
            recommendations=row["recommendations"],
            interviews=row["interviews"],
            placements=row["placements"],
            days_worked=row["days_worked"],
        )
        bucket = monthly[month]
        bucket[row["user_id"]] = bucket.get(row["user_id"], history.DrCounts()).plus(
            counts
        )
    return monthly


def _is_settled(
    ctype: str, period: str, settled_through: dict[str, Optional[str]]
) -> bool:
    if ctype == LEAGUE:
        last = settled_through["quarterly"]
        return last is not None and (period[-4:], period[:2]) <= (last[-4:], last[:2])
    last = settled_through["monthly"]
    return last is not None and period <= last


def build_settlements(
    parsed: dict[str, Any], names: dict[int, str]
) -> list[history.DrSettlement]:
    monthly = monthly_counts(parsed["rows"])
    out = []
    for ctype, period in settlement_periods():
        settled = _is_settled(ctype, period, parsed["settled_through"])
        out.append(
            history.settle_dr_period(
                ctype,
                period,
                monthly,
                names=names,
                weights=parsed["weights"],
                official=parsed["official"].get((ctype, period), []),
                official_settled=settled,
            )
        )
    return out


def _month_totals(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        month = row["report_date"].isoformat()[:7]
        for key in ("verifications", "recommendations", "interviews", "placements"):
            totals[month][key] += row[key]
    return {month: dict(values) for month, values in sorted(totals.items())}


def _without_names(value: Any) -> Any:
    """Migawka do paragonu — same ID i wyniki, bez nazwisk."""
    if isinstance(value, dict):
        return {k: _without_names(v) for k, v in value.items() if k != "name"}
    if isinstance(value, list):
        return [_without_names(v) for v in value]
    return value


async def _current_state(db, ctype: str, period: str) -> dict[str, Any]:
    from app.models.competition_period_closure import CompetitionPeriodClosure
    from app.models.competition_winner import CompetitionWinner

    winners = (
        await db.execute(
            select(
                CompetitionWinner.rank,
                CompetitionWinner.user_id,
                CompetitionWinner.metric_value,
                CompetitionWinner.prize_pln,
            )
            .where(
                CompetitionWinner.competition_type == ctype,
                CompetitionWinner.period == period,
            )
            .order_by(CompetitionWinner.rank)
        )
    ).all()
    closure = (
        await db.execute(
            select(
                CompetitionPeriodClosure.status, CompetitionPeriodClosure.details
            ).where(
                CompetitionPeriodClosure.competition_type == ctype,
                CompetitionPeriodClosure.period == period,
            )
        )
    ).first()
    return {
        "closure_status": closure.status if closure is not None else None,
        # Do paragonu (bez nazwisk), nie do wydruku.
        "closure_details": _without_names(closure.details) if closure else None,
        "winners": [
            {
                "rank": w.rank,
                "user_id": w.user_id,
                "metric_value": w.metric_value,
                "prize_pln": w.prize_pln,
            }
            for w in winners
        ],
    }


async def run(payload: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    from app.core.database import AsyncSessionLocal
    from app.models.competition_period_closure import CompetitionPeriodClosure
    from app.models.competition_winner import CompetitionType, CompetitionWinner
    from app.models.dr_kpi_body_leasing import DrKpiBodyLeasing
    from app.models.user import User
    from app.services import competitions

    parsed = parse_payload(payload)
    account_ids = {row["user_id"] for row in parsed["rows"]} | {
        uid for podium in parsed["official"].values() for uid in podium
    }
    async with AsyncSessionLocal() as db:
        found = {
            r.id: r.name
            for r in (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(account_ids))
                )
            ).all()
        }
        missing = sorted(account_ids - set(found))
        if missing:
            raise InputError(f"konta NEXUS-a nie istnieją: {missing}")

        settlements = build_settlements(parsed, found)
        report: dict[str, Any] = {
            "cutover": history.RESULTS_CUTOVER.isoformat(),
            "dr_rows": len(parsed["rows"]),
            "skipped": parsed["skipped"],
            "month_totals": _month_totals(parsed["rows"]),
            "periods": [],
        }
        mismatches = []
        before_details: dict[str, Any] = {}
        for s in settlements:
            before = await _current_state(db, s.competition_type, s.period)
            before_details[f"{s.competition_type} {s.period}"] = before.pop(
                "closure_details"
            )
            report["periods"].append(
                {
                    "type": s.competition_type,
                    "period": s.period,
                    "source_note": s.details["source_note"],
                    "before": before,
                    "after": {"closure_status": s.status, "winners": s.winners},
                    "ties": [tie["user_ids"] for tie in s.details["ties"]],
                    "excluded_user_ids": s.details["excluded_user_ids"],
                }
            )
            if s.official_mismatch:
                mismatches.append(
                    f"{s.competition_type} {s.period}: {s.official_mismatch}"
                )
        report["official_mismatches"] = mismatches
        report["existing_dr_rows_2026"] = int(
            (
                await db.execute(
                    text(
                        "SELECT count(*) FROM dr_kpi_body_leasing "
                        "WHERE report_date >= :first AND report_date < :cut"
                    ),
                    {"first": FIRST_DAY, "cut": history.RESULTS_CUTOVER},
                )
            ).scalar_one()
        )
        if not apply:
            report["applied"] = False
            return report

        if mismatches:
            raise InputError(
                "ogłoszone podium różni się od policzonego: " + "; ".join(mismatches)
            )
        already = (
            await db.execute(
                text("SELECT 1 FROM app_settings WHERE key = :k"), {"k": RECEIPT_KEY}
            )
        ).scalar_one_or_none()
        if already:
            raise InputError(
                f"paragon {RECEIPT_KEY} już istnieje — rozliczenie było zapisane"
            )

        deleted = (
            await db.execute(
                delete(DrKpiBodyLeasing).where(
                    DrKpiBodyLeasing.report_date >= FIRST_DAY,
                    DrKpiBodyLeasing.report_date < history.RESULTS_CUTOVER,
                )
            )
        ).rowcount
        for row in parsed["rows"]:
            db.add(DrKpiBodyLeasing(is_draft=False, **row))

        now = datetime.now(tz=ZoneInfo(DEFAULT_TZ)).isoformat()
        for s in settlements:
            ctype = CompetitionType(s.competition_type)
            await competitions._lock_period(db, ctype, s.period)
            await db.execute(
                delete(CompetitionWinner).where(
                    CompetitionWinner.competition_type == s.competition_type,
                    CompetitionWinner.period == s.period,
                )
            )
            await db.execute(
                delete(CompetitionPeriodClosure).where(
                    CompetitionPeriodClosure.competition_type == s.competition_type,
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
                        competition_type=s.competition_type,
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
                    competition_type=s.competition_type,
                    period=s.period,
                    status=s.status,
                    details={**s.details, "frozen_at": now},
                )
            )

        receipt = {
            "applied_at": now,
            "cutover": report["cutover"],
            "dr_rows_deleted": int(deleted or 0),
            "dr_rows_inserted": len(parsed["rows"]),
            "month_totals": report["month_totals"],
            # Same identyfikatory i wyniki — stan sprzed podmiany zostaje tu na zawsze.
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
        report["dr_rows_deleted"] = receipt["dr_rows_deleted"]
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
