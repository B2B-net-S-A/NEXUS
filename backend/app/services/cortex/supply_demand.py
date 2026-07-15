"""Cortex — podaż kompetencji vs popyt klientów + normalizacja job-title.

Etap 2, wartość biznesowa z discovery: „mamy 12 Reactów, a otwarte są 3 role
React" — zestawienie podaży (rozwiązane fakty skilli) z popytem (skille z
otwartych ``published`` jobów). Plus lekka (bez LLM) normalizacja tytułu
stanowiska → seniority + technologie z taksonomii.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobStatus
from app.models.skill import Skill
from app.services.cortex.fact_store import Taxonomy, load_taxonomy, normalize_token
from app.services.cortex.resolved import resolved_subquery

_SENIORITY_KEYWORDS = [
    ("architect", "architect"),
    ("principal", "senior"),
    ("staff", "senior"),
    ("lead", "lead"),
    ("senior", "senior"),
    ("sr.", "senior"),
    ("mid", "mid"),
    ("regular", "mid"),
    ("junior", "junior"),
    ("jr.", "junior"),
    ("intern", "junior"),
    ("trainee", "junior"),
]

_TITLE_TOKEN_RE = re.compile(r"[^a-z0-9.+#/]+")


async def supply_vs_demand(db: AsyncSession, *, only_must: bool = False) -> dict:
    """Zestaw podaż (kandydaci z rozwiązanym faktem) vs popyt (otwarte joby)."""
    r = resolved_subquery()
    supply_rows = (
        await db.execute(
            select(
                func.lower(Skill.canonical_name),
                func.count(distinct(r.c.candidate_id)),
            )
            .select_from(r)
            .join(Skill, Skill.id == r.c.skill_id)
            .group_by(func.lower(Skill.canonical_name))
        )
    ).all()
    supply = {name: cnt for name, cnt in supply_rows}

    # Popyt: skille z otwartych (published) jobów, znormalizowane taksonomią.
    from app.services.scoring_service import canonical_skill_names

    job_rows = (
        await db.execute(
            select(Job.must_skills, Job.nice_skills).where(
                Job.status == JobStatus.published
            )
        )
    ).all()
    demand: dict[str, int] = defaultdict(int)
    for must, nice in job_rows:
        names = {n.lower() for n in canonical_skill_names(must or [])}
        if not only_must:
            names |= {n.lower() for n in canonical_skill_names(nice or [])}
        for name in names:
            demand[name] += 1

    all_skills = set(supply) | set(demand)
    rows = [
        {
            "skill": s,
            "supply": supply.get(s, 0),
            "demand": demand.get(s, 0),
            "gap": demand.get(s, 0) - supply.get(s, 0),
        }
        for s in all_skills
    ]
    # Sortuj: najpierw największy niedobór (gap), potem popyt.
    rows.sort(key=lambda x: (-x["gap"], -x["demand"], x["skill"]))
    return {
        "skills": rows,
        "open_jobs": len(job_rows),
        "only_must": only_must,
    }


def _normalize_title(title: str, taxonomy: Taxonomy) -> dict:
    lowered = (title or "").lower()

    seniority: Optional[str] = None
    for needle, canonical in _SENIORITY_KEYWORDS:
        if needle in lowered:
            seniority = canonical
            break

    tokens = [t for t in _TITLE_TOKEN_RE.split(lowered) if t]
    technologies: list[str] = []
    seen: set[int] = set()
    # unigramy + bigramy (np. „apache kafka", „spring boot")
    candidates = list(tokens) + [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]
    for cand in candidates:
        skill_id, _ = normalize_token(taxonomy, cand)
        if skill_id is not None and skill_id not in seen:
            seen.add(skill_id)
            technologies.append(cand)

    return {
        "title": title,
        "seniority": seniority,
        "technologies": technologies,
    }


async def normalize_title(db: AsyncSession, title: str) -> dict:
    taxonomy = await load_taxonomy(db)
    return _normalize_title(title, taxonomy)
