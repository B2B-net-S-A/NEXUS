"""Pomiar: kontrakty, których stawka w NEXUSIE różni się od stałej stawki z faktur KSeF.

    python -m scripts.contract_rate_history_report [--from 2026-01] [--to 2026-10] [--json plik]

Tylko odczyt. Wypisuje liczby per kategoria (``infer``: brak historii, rozjazd
bieżący, rozjazd w przeszłości) i ile kroków przeszłoby jako wpis automatyczny;
``--json`` zapisuje wiersze per kontrakt (id, kroki, miesiące, powody) — bez
nazwisk, ale ze stawkami, więc plik nie trafia do repo ani logów Actions.
Reguła: ``docs/claude/kontrakty/historia-stawek-z-faktur-ksef.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.services.contract_rate_history import collect, infer


def _row(result: infer.ContractResult) -> dict:
    return {
        "contract_id": result.contract_id,
        "category": result.category,
        "automatic": result.automatic,
        "steps": [
            {
                "leg": s.leg,
                "from": s.effective_from.isoformat(),
                "rate": str(s.rate),
                "nexus": str(s.nexus_rate) if s.nexus_rate is not None else None,
                "months": list(s.months),
                "reasons": list(s.reasons),
                "evidence": list(s.evidence),
                "impact": str(s.impact),
                "baseline": s.baseline,
            }
            for s in result.steps
        ],
    }


async def main(first: str, last: str, out: str | None) -> None:
    async with AsyncSessionLocal() as db:
        inputs = await collect.load_inputs(db, first_month=first, last_month=last)
    today = business_today()
    results = [infer.infer(i, today) for i in inputs]
    by_cat = Counter(r.category for r in results)
    auto = [r for r in results if r.automatic]
    reasons = Counter(x for r in results for s in r.steps for x in s.reasons)
    legs = Counter(s.leg for r in results for s in r.steps if not s.baseline)
    with_client = sum(1 for i in inputs if i.client_obs)
    with_cost = sum(1 for i in inputs if i.cost_obs)
    print(
        f"miesiące {first}…{last}; kontrakty z obserwacją: {len(inputs)} "
        f"(klient {with_client}, koszt {with_cost})"
    )
    for cat in (infer.OK, infer.NO_HISTORY, infer.CURRENT_GAP, infer.PAST_ONE_LEG):
        print(f"  {cat}: {by_cat.get(cat, 0)}")
    print(
        f"kroki: {sum(legs.values())} (klient {legs[infer.CLIENT]}, koszt {legs[infer.COST]})"
    )
    print(f"kontrakty z wpisem w całości automatycznym: {len(auto)}")
    for label, chosen in (("wszystkie", results), ("automatyczne", auto)):
        client = sum(s.impact for r in chosen for s in r.steps if s.leg == infer.CLIENT)
        cost = sum(s.impact for r in chosen for s in r.steps if s.leg == infer.COST)
        print(
            f"  skutek ({label}): przychód {client:+.2f} zł, koszt {cost:+.2f} zł, "
            f"marża {client - cost:+.2f} zł"
        )
    for cat in (infer.NO_HISTORY, infer.CURRENT_GAP, infer.PAST_ONE_LEG):
        n = sum(1 for r in auto if r.category == cat)
        print(f"  automatyczne w kategorii {cat}: {n}")
    for reason, n in reasons.most_common():
        print(f"  do sprawdzenia ({n}): {reason}")
    if out:
        with open(out, "w") as fh:
            json.dump(
                [_row(r) for r in results if r.steps], fh, ensure_ascii=False, indent=1
            )


if __name__ == "__main__":
    today = business_today()
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="first", default=f"{today.year}-01")
    parser.add_argument(
        "--to", dest="last", default=collect.shift(collect.month_key(today), -1)
    )
    parser.add_argument("--json", dest="out")
    args = parser.parse_args()
    asyncio.run(main(args.first, args.last, args.out))
