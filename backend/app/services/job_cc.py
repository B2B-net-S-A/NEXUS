"""Deterministic Job title → Competence Category (CC) classifier + resolver.

Why this exists
---------------
The /jobs list has a "Kategoria" (CC) filter in the UI and the API supports
``competence_category_id``, but on production *every* job had
``competence_category_id = NULL`` — so the filter always returned 0 results.
The hybrid classifier (``cc_classifier.classify_job_to_cc``) alone could not
fix this at creation time: with the noisy centroid signal and the
ratio-of-all-keywords scoring, even unambiguous titles ("Tester Middle",
"Senior DevOps Engineer") landed below the tie threshold and were never
assigned.

Job titles — like talent-pool names — are a controlled vocabulary of role
titles, so the title itself is a strong, dependency-free signal. This module
extends the ordered keyword rules from ``talent_pool_cc`` with patterns seen
in the production job catalogue (Polish role names: "Programista",
"Analityk", "Kierownik", "Architekt Chmurowy"; spelling variants: "Dev-ops",
"Front-end"; plus domain tokens like ETL / Power BI / cyber).

Resolution order (``resolve_job_cc_id``):
  1. deterministic title rules (this module) — pure, no I/O,
  2. hybrid keyword+embedding classifier (``classify_job_to_cc``) as a
     fallback, accepted only when confident (no tie, score ≥ 0.30),
  3. ``None`` — non-role buckets ("Opportunity", "Stara kadencja") stay NULL.

Rule ordering is load-bearing and mirrors ``talent_pool_cc``:
security → data → management → infrastructure → software. E.g. "Tester
Automatyzujący (ETL)" must stay *security_quality*, "Architekt Chmurowy" must
resolve to *infrastructure_operations* before the generic "architekt" rule in
*software_development* fires.
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competence_category import CompetenceCategory
from app.services.talent_pool_cc import BASE_CC_RULES

# Hybrid-fallback acceptance floor — below this the embedding/keyword blend is
# too weak to trust for silent auto-assignment.
HYBRID_MIN_SCORE = 0.30

# Job-specific pattern extensions per CC slug, applied ON TOP of the shared
# talent-pool rules. Same regex conventions: case-insensitive, ``\b`` anchors
# around short/ambiguous tokens.
_JOB_EXTRA_PATTERNS: dict[str, tuple[str, ...]] = {
    # Polish security stems ("bezpieczeństwa chmury" must win before the
    # infra "chmur" rule) + offensive-security roles.
    "security_quality": (
        r"bezpiecze",
        r"cyber",
        r"red team",
        r"blue team",
        r"malware",
        r"exploit",
        r"vulnerabilit",
        r"\bcsirt\b",
        # noun forms only ("inżynieria testów", "automatyzacja testowania") —
        # NOT the adjective "testowy" ("Projekt testowy: ..." is metadata).
        r"testów|testowani",
    ),
    # Explicit data/BI tokens — checked before management so "Analityk danych"
    # and "Power BI Analyst" don't fall through to the generic analyst rule.
    "data_ai": (
        r"\betl\b",
        r"power\s*bi",
        r"analityk danych",
        r"tableau",
        r"\bqlik\b",
        r"business intel",
    ),
    # Polish analyst/manager family + tech-lead roles.
    "management_delivery": (
        r"analityk",
        r"kierownik",
        r"koordynator",
        r"coordinator",
        r"\blider\b",
        r"tech lead",
        r"team lead",
        r"zarządzan",
    ),
    # Polish infra stems + spelling/cloud variants.
    "infrastructure_operations": (
        r"chmur",
        r"infrastruktur",
        r"administrator",
        r"dev[\s-]?ops",
        r"\bsupport\b",
        r"wsparci",
        r"\boperations\b",
        r"storage",
        r"\bsieci\b",
        r"\bazure\b",
        r"\baws\b",
        r"\bgcp\b",
        r"vmware",
        r"database",
    ),
    # Polish developer/designer roles + spelling variants. "architekt"
    # (generic) is last-resort here, mirroring the English "architect" rule —
    # Cloud/Data/Security architects are claimed by earlier categories.
    "software_development": (
        r"programist",
        r"projektant",
        r"ui\s*/\s*ux",
        r"\bux\b",
        r"front[\s-]?end",
        r"back[\s-]?end",
        r"salesforce",
        r"architekt",
    ),
}

_RULES: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (
        slug,
        tuple(
            re.compile(p, re.IGNORECASE)
            for p in (*patterns, *_JOB_EXTRA_PATTERNS.get(slug, ()))
        ),
    )
    for slug, patterns in BASE_CC_RULES
)


def classify_job_title_to_cc_slug(title: Optional[str]) -> Optional[str]:
    """Map a job title to a CC slug, or None if no rule matches.

    Pure and deterministic — no DB / network. The FIRST category (in rule
    order) with any matching pattern wins.
    """
    if not title:
        return None
    # Prod titles use "_" as a separator ("Specjalista PMO_moduł VI") — "_" is
    # a word character, so it would defeat the \b anchors on short tokens.
    text = title.strip().lower().replace("_", " ")
    if not text:
        return None
    for slug, patterns in _RULES:
        if any(p.search(text) for p in patterns):
            return slug
    return None


async def resolve_job_cc_id(
    job,
    db: AsyncSession,
    *,
    min_hybrid_score: float = HYBRID_MIN_SCORE,
) -> Optional[int]:
    """Resolve the CompetenceCategory.id for ``job`` (title-first, hybrid fallback).

    Used by the job create path and the ``scripts.backfill_job_cc`` backfill.
    Returns None when neither tier produces a confident answer — callers leave
    ``competence_category_id`` NULL in that case.
    """
    slug = classify_job_title_to_cc_slug(getattr(job, "title", None))
    if slug is not None:
        cc_id = await db.scalar(
            select(CompetenceCategory.id).where(CompetenceCategory.slug == slug)
        )
        if cc_id is not None:
            return cc_id

    from app.services.cc_classifier import classify_job_to_cc

    result = await classify_job_to_cc(job, db)
    if result.top and not result.tie and result.top.score >= min_hybrid_score:
        return result.top.cc_id
    return None
