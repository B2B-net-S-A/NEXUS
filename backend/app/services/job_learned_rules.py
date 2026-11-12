"""Reguła rekrutacji z powtarzanych braków (R1, decyzja Artura 12.11.2026).

Raport: https://claude.ai/artifact/PqmctW9taWS8mXwmGfrFSM. Do 12.11 powód
odrzucenia nie zmieniał tego, kogo system doda jutro do tej samej rekrutacji:
w Expert Full Stack 13× „brak Angular”, w analizie systemowej 17× „produkty
inwestycyjne”. Reguła: ``docs/claude/rekrutacja-tablica/porcja-regula-z-odrzucen.md``.

Gdy w jednej rekrutacji co najmniej ``RULE_MIN`` odrzuceń „Brak umiejętności”
wskaże tę samą pozycję (``autofill_feedback.gaps``), silnik „Nowych” od
następnego doboru wymaga jej śladu:

* same „brak” → osoba musi mieć pozycję choć w CV albo umiejętnościach;
* choć raz „tylko wzmianka” → osoba musi mieć doświadczenie (oś technologii
  z CV z miesiącami stanowisk; fraza spoza słownika — tekst CV tego nie da).

„Za mało lat” nie tworzy reguły: nie wiemy, ile lat wystarczy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import select

RULE_MIN = 3
MAX_RULES = 3
COUNTED_KINDS = ("missing", "mention")


@dataclass(frozen=True)
class LearnedRule:
    label: str
    level: str  # "trace" | "experience"
    count: int

    def passes(self, state: str) -> bool:
        if self.level == "experience":
            return state == "experience"
        return state != "none"

    def as_dict(self) -> dict[str, Any]:
        return {"label": self.label, "level": self.level, "count": self.count}


def rules_from_gaps(rows: Iterable[Any]) -> list[LearnedRule]:
    """Reguły z list braków jednej rekrutacji (każdy wiersz = jedno odrzucenie)."""
    counts: dict[str, int] = {}
    mentions: dict[str, int] = {}
    display: dict[str, str] = {}
    for gaps in rows:
        seen: set[str] = set()
        for gap in gaps or []:
            if not isinstance(gap, dict) or gap.get("kind") not in COUNTED_KINDS:
                continue
            label = str(gap.get("label") or "").strip()
            key = label.casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            display.setdefault(key, label)
            counts[key] = counts.get(key, 0) + 1
            if gap.get("kind") == "mention":
                mentions[key] = mentions.get(key, 0) + 1
    rules = [
        LearnedRule(
            label=display[key],
            level="experience" if mentions.get(key) else "trace",
            count=count,
        )
        for key, count in counts.items()
        if count >= RULE_MIN
    ]
    rules.sort(key=lambda r: (-r.count, r.label.casefold()))
    return rules[:MAX_RULES]


async def rules_for_jobs(db, job_ids: Iterable[int]) -> dict[int, list[LearnedRule]]:
    from app.models.autofill_feedback import AutofillFeedback

    ids = sorted({int(j) for j in job_ids})
    if not ids:
        return {}
    by_job: dict[int, list[Any]] = {}
    for job_id, gaps in (
        await db.execute(
            select(AutofillFeedback.job_id, AutofillFeedback.gaps).where(
                AutofillFeedback.job_id.in_(ids),
                AutofillFeedback.gaps.is_not(None),
            )
        )
    ).all():
        by_job.setdefault(job_id, []).append(gaps)
    return {
        job_id: rules
        for job_id, rows in by_job.items()
        if (rules := rules_from_gaps(rows))
    }


async def keep_passing(db, job_id: int, candidates: list[Any]) -> set[int]:
    """Id osób, które spełniają reguły rekrutacji (wszystkie, gdy reguł brak)."""
    from app.services.review_batch_facts import evidence_for

    rules = (await rules_for_jobs(db, [job_id])).get(job_id) or []
    ids = {c.id for c in candidates}
    if not rules or not ids:
        return ids
    evidence = await evidence_for(db, candidates, [r.label for r in rules])
    return {
        c.id
        for c in candidates
        if all(r.passes(evidence.get((c.id, r.label), ("none", 0))[0]) for r in rules)
    }
