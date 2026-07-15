"""Harness precision/recall ekstrakcji faktów Cortexa (Etap 2, item 2).

Mierzy jakość ekstrakcji skilli względem ręcznie oznaczonego GOLD SETU — tak jak
``scripts/eval_matching.py`` waliduje scoring. Uruchamiać przed włączeniem
``CORTEX_FACTS_IN_SCORING`` i przed pełnym backfillem cv_llm.

GOLD SET (JSON):
    {
      "<candidate_id>": ["python", "docker", "kubernetes"],
      "<candidate_id>": ["react", "typescript"]
    }
Nazwy = kanoniczne (lowercase). Oznacz ręcznie ~30-50 kandydatów z różnych ról.

Użycie:
    python -m scripts.eval_cortex_extraction gold.json
    python -m scripts.eval_cortex_extraction gold.json --source cv_llm

Raportuje: per-candidate + micro/macro Precision/Recall/F1. Brak gold setu →
skrypt wyjaśnia format i kończy (nie ma co mierzyć bez etykiet).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Optional

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.cortex import CortexSkillFact
from app.models.skill import Skill
from app.services.cortex.resolved import resolve_candidate_skills


async def _predicted_skills(
    db, candidate_id: int, source: Optional[str]
) -> set[str]:
    if source:
        rows = (
            await db.execute(
                select(Skill.canonical_name)
                .select_from(CortexSkillFact)
                .join(Skill, Skill.id == CortexSkillFact.skill_id)
                .where(
                    CortexSkillFact.candidate_id == candidate_id,
                    CortexSkillFact.source == source,
                )
            )
        ).all()
        return {r[0].lower() for r in rows}
    resolved = await resolve_candidate_skills(db, candidate_id)
    return {r["skill"].lower() for r in resolved}


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )
    return precision, recall, f1


async def main(gold_path: str, source: Optional[str]) -> int:
    with open(gold_path, encoding="utf-8") as fh:
        gold = json.load(fh)
    if not gold:
        print("Gold set jest pusty — oznacz kilku kandydatów (patrz docstring).")
        return 1

    micro_tp = micro_fp = micro_fn = 0
    per_p: list[float] = []
    per_r: list[float] = []
    async with AsyncSessionLocal() as db:
        for cid_str, expected_list in gold.items():
            cid = int(cid_str)
            expected = {s.lower() for s in expected_list}
            predicted = await _predicted_skills(db, cid, source)
            tp = len(expected & predicted)
            fp = len(predicted - expected)
            fn = len(expected - predicted)
            micro_tp += tp
            micro_fp += fp
            micro_fn += fn
            p, r, f1 = _prf(tp, fp, fn)
            per_p.append(p)
            per_r.append(r)
            print(
                f"cand {cid}: P={p:.2f} R={r:.2f} F1={f1:.2f} "
                f"(tp={tp} fp={fp} fn={fn})"
            )

    mp, mr, mf1 = _prf(micro_tp, micro_fp, micro_fn)
    macro_p = sum(per_p) / len(per_p)
    macro_r = sum(per_r) / len(per_r)
    print("\n=== SUMMARY ===")
    print(f"micro: P={mp:.3f} R={mr:.3f} F1={mf1:.3f}")
    print(f"macro: P={macro_p:.3f} R={macro_r:.3f}")
    print(f"candidates={len(gold)} source={source or 'resolved'}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gold", help="Ścieżka do gold-set JSON (candidate_id → skills).")
    parser.add_argument(
        "--source",
        default=None,
        choices=["traffit", "cv_llm", "screening"],
        help="Mierz jedno źródło (domyślnie: resolved facts).",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.gold, args.source)))
