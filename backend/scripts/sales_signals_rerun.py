#!/usr/bin/env python3
"""Ponowne zlecenie biegów bota, które nie dały wyniku (24.11.2026).

Biegi Research 261–718 wygasły bez raportu, bo treść webhooka z całym zleceniem
docierała do bota ucięta; biegi Cognism z 22.11 wróciły z firmami
``not_processed``. Ich tokeny są nieważne, więc skrypt zakłada nowe biegi
(webhook v2) dla firm, które nadal czekają na wynik:

* bieg wygasły albo nieudany: jego firmy w tym samym trybie (``modes``);
* bieg Cognism z raportem: firmy z ``unprocessed_company_ids``;
* bez firm, które później trafiły do biegu tego samego rodzaju i trybu (w toku
  albo z raportem; Cognism: przetworzone), i bez firm ze świeżym haczykiem.

Paczki jak w pętli: haczyk po 5, punkty po 25, Cognism po 5 i jeden bieg
Cognism naraz. Domyślnie tylko plan (liczby). ``--start`` zakłada najwyżej
``--max-runs`` biegów na uruchomienie, żeby bot dostawał zlecenia stopniowo;
kolejne uruchomienie pomija firmy z biegów już założonych.

Uruchomienie (z ``backend/``, po wdrożeniu webhooka v2)::

    python -m scripts.sales_signals_rerun --run-ids 598,639,648
    python -m scripts.sales_signals_rerun --run-ids 598,639,648 --start --max-runs 3

Wynik to same liczby i identyfikatory (logi są publiczne).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.models.sales import SalesSignalRun
from app.services.sales import signal_targets, signals
from app.services.sales.bot_tasks import call_hook
from app.services.sales.hook_prep_targets import HOOK_BATCH_SIZE

COGNISM_REQUEST = {"source": "cognism"}
#: (rodzaj, Cognism, tryb) — tryb pusty dla rodzajów bez ``modes``.
Group = tuple[str, bool, str]


@dataclass(frozen=True)
class Source:
    run_id: int
    started_at: datetime
    kind: str
    cognism: bool
    #: firma → tryb w biegu ("" bez trybu)
    firms: dict[int, str]
    skipped: str = ""


@dataclass
class Plan:
    batches: list[tuple[Group, list[int]]] = field(default_factory=list)
    skipped_runs: dict[int, str] = field(default_factory=dict)
    covered: int = 0
    fresh_hook: int = 0


def _is_cognism(run: SalesSignalRun) -> bool:
    return run.kind == "people" and (run.request or {}).get("source") == "cognism"


def source_of(run: SalesSignalRun) -> Source:
    """Firmy biegu, które nie dostały wyniku."""

    cognism = _is_cognism(run)
    modes = run.modes or {}
    ids = [int(cid) for cid in run.company_ids]
    skipped = ""
    if run.status == "received":
        if cognism:
            ids = [
                int(c) for c in (run.report or {}).get("unprocessed_company_ids") or []
            ]
        else:
            ids, skipped = [], "bieg ma raport"
    elif run.status == "started":
        ids, skipped = [], "bieg jeszcze trwa"
    return Source(
        run_id=run.id,
        started_at=run.started_at,
        kind=run.kind,
        cognism=cognism,
        firms={cid: str(modes.get(str(cid), "")) for cid in ids},
        skipped=skipped,
    )


def covering(runs: Sequence[SalesSignalRun]) -> dict[tuple[Group, int], datetime]:
    """Najpóźniejszy bieg, który objął firmę w danym rodzaju i trybie."""

    latest: dict[tuple[Group, int], datetime] = {}
    for run in runs:
        if run.status not in ("started", "received"):
            continue
        cognism = _is_cognism(run)
        unprocessed = {
            int(c) for c in (run.report or {}).get("unprocessed_company_ids") or []
        }
        modes = run.modes or {}
        for raw in run.company_ids:
            cid = int(raw)
            if cognism and run.status == "received" and cid in unprocessed:
                continue
            key = ((run.kind, cognism, str(modes.get(str(cid), ""))), cid)
            if key not in latest or latest[key] < run.started_at:
                latest[key] = run.started_at
    return latest


def batch_size(group: Group) -> int:
    kind, cognism, mode = group
    if cognism:
        return signal_targets.COGNISM_BATCH_SIZE
    if mode == call_hook.CALL_HOOK:
        return HOOK_BATCH_SIZE
    return signal_targets.MAX_BRIEFING_FIRMS


def plan(
    sources: Sequence[Source],
    covered: dict[tuple[Group, int], datetime],
    fresh_hooks: set[int],
) -> Plan:
    result = Plan()
    pending: dict[Group, list[int]] = defaultdict(list)
    for source in sources:
        if source.skipped:
            result.skipped_runs[source.run_id] = source.skipped
            continue
        for cid, mode in source.firms.items():
            group: Group = (source.kind, source.cognism, mode)
            later = covered.get((group, cid))
            if later is not None and later > source.started_at:
                result.covered += 1
                continue
            if mode == call_hook.CALL_HOOK and cid in fresh_hooks:
                result.fresh_hook += 1
                continue
            if cid not in pending[group]:
                pending[group].append(cid)
    for group, ids in pending.items():
        size = batch_size(group)
        result.batches.extend(
            (group, ids[start : start + size]) for start in range(0, len(ids), size)
        )
    return result


def summary(result: Plan) -> dict[str, Any]:
    by_group: dict[str, dict[str, int]] = {}
    for (kind, cognism, mode), ids in result.batches:
        label = "people/cognism" if cognism else f"{kind}/{mode or '-'}"
        entry = by_group.setdefault(label, {"firms": 0, "runs": 0})
        entry["firms"] += len(ids)
        entry["runs"] += 1
    return {
        "groups": by_group,
        "skipped_runs": result.skipped_runs,
        "covered_later": result.covered,
        "fresh_hook": result.fresh_hook,
    }


async def run(run_ids: list[int], *, start: bool, max_runs: int) -> dict[str, Any]:
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            rows = (
                await db.execute(
                    select(SalesSignalRun)
                    .where(SalesSignalRun.id.in_(run_ids))
                    .order_by(SalesSignalRun.id)
                )
            ).scalars()
            sources = [source_of(row) for row in rows]
            if not sources:
                return {"started": [], "reason": "brak takich biegów"}
            oldest = min(source.started_at for source in sources)
            later = (
                await db.execute(
                    select(SalesSignalRun).where(
                        SalesSignalRun.started_at > oldest,
                        SalesSignalRun.kind.in_({s.kind for s in sources}),
                    )
                )
            ).scalars()
            fresh = await call_hook.fresh_company_ids(db, now=now)
            result = plan(sources, covering(list(later)), fresh)
            out: dict[str, Any] = {**summary(result), "started": []}
            if not start:
                return out
            for group, ids in result.batches[:max_runs]:
                kind, cognism, mode = group
                if cognism:
                    await signal_targets.lock_people_starts(db)
                    if await signal_targets.cognism_run_active(db, now=now):
                        out["stopped"] = (
                            "bieg Cognism już trwa; uruchom ponownie później"
                        )
                        await db.commit()
                        break
                started: Optional[SalesSignalRun] = await signals.start_run(
                    db,
                    kind,
                    ids,
                    now=now,
                    modes={cid: mode for cid in ids} if mode else None,
                    request=COGNISM_REQUEST if cognism else None,
                )
                if started is None:
                    out["stopped"] = (
                        "start odrzucony (flaga, pauza bota albo brak webhooka)"
                    )
                    break
                out["started"].append(
                    {"run_id": started.id, "status": started.status, "firms": len(ids)}
                )
            out["remaining_runs"] = max(0, len(result.batches) - len(out["started"]))
            return out
    finally:
        await engine.dispose()


def _ids(value: str) -> list[int]:
    ids = [int(part) for part in value.split(",") if part.strip()]
    if not ids:
        raise argparse.ArgumentTypeError("Podaj numery biegów po przecinku.")
    return ids


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ponowne zlecenie biegów bota")
    parser.add_argument("--run-ids", type=_ids, required=True)
    parser.add_argument("--start", action="store_true", help="Załóż biegi")
    parser.add_argument("--max-runs", type=int, default=3)
    args = parser.parse_args(argv)
    if args.max_runs < 1:
        parser.error("--max-runs od 1.")
    result = asyncio.run(run(args.run_ids, start=args.start, max_runs=args.max_runs))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
