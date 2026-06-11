"""Deterministic Talent-Pool name → Competence Category (CC) classifier.

Why this exists
---------------
The 5 Competence Categories are the backbone of NEXUS matching, but on
production *every* talent pool had ``competence_category_id = NULL`` — the CC
dimension was never populated (no Job carries a CC either, so the lineage-based
heal in ``talent_pool_auto_add`` / ``scripts.backfill_talent_pools`` could never
fire). The ``/talents`` category filter is purely client-side
(``p.competence_category_id !== null && selectedCcIds.includes(...)``), so with
every pool NULL, selecting *any* category showed "Brak pul w wybranych
kategoriach".

Talent-pool names are a small, controlled vocabulary of role titles
("DevOps Engineers", "QA Automation", "Java Backend Senior", …). That makes the
name itself a reliable, dependency-free signal — no Qdrant / embeddings needed.
This module maps a pool name to one of the 5 CC slugs with ordered keyword
rules.

Rule ordering is load-bearing: e.g. "Tester Automatyzujący (ETL, bazy danych)"
must resolve to *security_quality* (it's a tester), not *data_ai* (ETL), so the
QA rules are checked before the data rules; "Service Manager" must be
*management_delivery* while "Service Desk" is *infrastructure_operations*, so
management is checked before infrastructure. ``tests/test_talent_pool_cc.py``
locks the full name→slug expectation across the live pool catalogue.
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competence_category import CompetenceCategory

# Ordered (slug, patterns) rules — the FIRST category with any matching pattern
# wins. Patterns are case-insensitive regexes; short or ambiguous tokens use
# ``\b`` word-boundary anchors so e.g. "ai" matches "AI Engineer" but not the
# "ai" inside "Mainframe".
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # 1) Security & Quality — QA/testers + security. Checked first so a
    #    "Tester (ETL...)" stays QA rather than leaking into data_ai, and
    #    "Test Manager" stays QA rather than management_delivery.
    (
        "security_quality",
        (
            r"\bqa\b",
            r"quality assurance",
            r"tester",
            r"\btest\b",
            r"pentest",
            r"penetration",
            r"\bsecurity\b",
            r"\bsoc\b",
            r"\bsiem\b",
            r"\biam\b",
            r"vulnerability",
            r"appsec",
            r"owasp",
        ),
    ),
    # 2) Data & AI — explicit data/ML/AI roles only (no bare "data", so
    #    "IT Analyst - Data Focus" falls through to the analyst rule).
    (
        "data_ai",
        (
            r"data scientist",
            r"data science",
            r"data engineer",
            r"data architect",
            r"data analyst",
            r"big data",
            r"hadoop",
            r"\bml\b",
            r"mlops",
            r"machine learning",
            r"deep learning",
            r"\bai\b",
            r"\bnlp\b",
            r"\bllm\b",
        ),
    ),
    # 3) Management & Delivery — analysts, PM/PO, scrum, the "* Manager"
    #    family, GRC/compliance. Checked before infrastructure so
    #    "Service Manager" != "Service Desk".
    (
        "management_delivery",
        (
            r"\banalyst\b",
            r"\bpm\b",
            r"\bpmo\b",
            r"product owner",
            r"product manager",
            r"\bproduct\b",
            r"project",
            r"scrum",
            r"agile",
            r"\brte\b",
            r"release train",
            r"\bmanager\b",
            r"transition",
            r"rollout",
            r"\bprogram\b",
            r"\brisk\b",
            r"\bgrc\b",
            r"compliance",
            r"\bdora\b",
            r"delivery",
            r"coach",
        ),
    ),
    # 4) Infrastructure & Operations — DevOps/cloud/network/admin/helpdesk/DBA.
    #    "platform engineer" (not bare "platform") so "Power Platform" stays SW.
    (
        "infrastructure_operations",
        (
            r"devops",
            r"\bsre\b",
            r"\bcloud\b",
            r"infrastructure",
            r"\binfra\b",
            r"platform engineer",
            r"network",
            r"\bnoc\b",
            r"linux",
            r"windows",
            r"virtualization",
            r"helpdesk",
            r"service desk",
            r"\bdba\b",
            r"mainframe",
            r"sysadmin",
            r"kubernetes",
        ),
    ),
    # 5) Software Development — broad tech catch-all + generic "architect"
    #    (Cloud/Network/Data/Test architects are already claimed above).
    (
        "software_development",
        (
            r"developer",
            r"\bdev\b",
            r"backend",
            r"frontend",
            r"full[\s-]?stack",
            r"\bjava\b",
            r"javascript",
            r"typescript",
            r"python",
            r"\bnode\b",
            r"node\.js",
            r"\.net\b",
            r"dotnet",
            r"\bc#",
            r"csharp",
            r"\bphp\b",
            r"\breact\b",
            r"angular",
            r"\bvue\b",
            r"android",
            r"\bios\b",
            r"mobile",
            r"\bgo\b",
            r"golang",
            r"cobol",
            r"abap",
            r"pega",
            r"low[\s-]?code",
            r"power\s*apps",
            r"power platform",
            r"ux\s*/\s*ui",
            r"c/c\+\+",
            r"\bc\+\+",
            r"\brpa\b",
            r"\bsap\b",
            r"\berp\b",
            r"architect",
        ),
    ),
)

# Public alias — `services.job_cc` extends these shared rules with
# job-title-specific patterns (Polish role names etc.) in the same order.
BASE_CC_RULES = _RULES

_COMPILED: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (slug, tuple(re.compile(p, re.IGNORECASE) for p in pats)) for slug, pats in _RULES
)


def classify_pool_name_to_cc_slug(name: Optional[str]) -> Optional[str]:
    """Map a talent-pool name to a CC slug, or None if no rule matches.

    Pure and deterministic — no DB / network. Returns one of the 5 seed slugs
    (``infrastructure_operations`` / ``software_development`` / ``data_ai`` /
    ``security_quality`` / ``management_delivery``) or ``None`` for names that
    are not role categories (e.g. "Targ kandydatów", "POWER CALLING").
    """
    if not name:
        return None
    text = name.strip().lower()
    if not text:
        return None
    for slug, patterns in _COMPILED:
        if any(p.search(text) for p in patterns):
            return slug
    return None


async def resolve_cc_id_for_pool_name(
    db: AsyncSession, name: Optional[str]
) -> Optional[int]:
    """Classify ``name`` and resolve the matching ``CompetenceCategory.id``.

    Returns None when the name matches no rule, or the slug is absent from the
    ``competence_categories`` table. One lightweight indexed lookup — callers
    invoke this only on pool *creation*/heal, never on the hot list path.
    """
    slug = classify_pool_name_to_cc_slug(name)
    if slug is None:
        return None
    return await db.scalar(
        select(CompetenceCategory.id).where(CompetenceCategory.slug == slug)
    )
