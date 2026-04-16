"""
Duplicate detection for candidates.

Critical for IT staffing when importing 40k+ CVs — prevents double-entry.
Soft-warning semantics: callers (API endpoints, import flows) may choose to
block, warn, or auto-merge based on match_score.

Match score semantics:
  1.00 — email exact, or phone last-9-digits match
  0.95 — linkedin slug match (last path segment of profile URL)
  0.90 — exact (name, lastname) match after lower-case normalization
  0.00 — below threshold, not returned
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate


def _normalize_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    return email.strip().lower() or None


def _normalize_phone(phone: Optional[str]) -> Optional[str]:
    """Keep only digits, match by last 9 (handles +48 prefixes, spaces, dashes)."""
    if not phone:
        return None
    digits = re.sub(r"[^\d]", "", phone)
    return digits[-9:] if len(digits) >= 9 else digits or None


def _normalize_name(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return s.strip().lower() or None


def _linkedin_slug(url: Optional[str]) -> Optional[str]:
    """Extract the last path segment of a LinkedIn URL — stable cross-variants."""
    if not url:
        return None
    stripped = url.strip().rstrip("/")
    if not stripped:
        return None
    return stripped.split("/")[-1].lower() or None


async def find_candidate_duplicates(
    db: AsyncSession,
    *,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    linkedin: Optional[str] = None,
    name: Optional[str] = None,
    lastname: Optional[str] = None,
    exclude_candidate_id: Optional[int] = None,
    min_score: float = 0.85,
) -> list[dict]:
    """
    Return candidates that match any of the identifiers, sorted by match_score desc.

    Each entry: {candidate_id, name, lastname, email, match_score, match_reasons}
    """
    norm_email = _normalize_email(email)
    norm_phone = _normalize_phone(phone)
    norm_linkedin_slug = _linkedin_slug(linkedin)
    norm_name = _normalize_name(name)
    norm_lastname = _normalize_name(lastname)

    clauses = []
    if norm_email:
        clauses.append(func.lower(Candidate.email) == norm_email)
    if norm_phone:
        # Compare last-9-digits of stored phone after stripping non-digits
        clauses.append(
            func.regexp_replace(Candidate.phone, r"[^0-9]", "", "g").ilike(
                f"%{norm_phone}"
            )
        )
    if norm_linkedin_slug:
        clauses.append(Candidate.linkedin.ilike(f"%{norm_linkedin_slug}%"))
    if norm_name and norm_lastname:
        clauses.append(
            (func.lower(Candidate.name) == norm_name)
            & (func.lower(Candidate.lastname) == norm_lastname)
        )

    if not clauses:
        return []

    stmt = select(Candidate).where(or_(*clauses))
    if exclude_candidate_id is not None:
        stmt = stmt.where(Candidate.id != exclude_candidate_id)

    result = await db.execute(stmt)
    candidates = result.scalars().all()

    matches: list[dict] = []
    for c in candidates:
        reasons: list[str] = []
        score = 0.0

        if norm_email and c.email and c.email.strip().lower() == norm_email:
            reasons.append("email_exact")
            score = max(score, 1.0)

        if norm_phone and c.phone:
            cphone = _normalize_phone(c.phone)
            if cphone and cphone == norm_phone:
                reasons.append("phone_exact")
                score = max(score, 1.0)

        if norm_linkedin_slug and c.linkedin:
            c_slug = _linkedin_slug(c.linkedin)
            if c_slug and c_slug == norm_linkedin_slug:
                reasons.append("linkedin_slug_match")
                score = max(score, 0.95)

        if (
            norm_name
            and norm_lastname
            and c.name
            and c.lastname
            and c.name.strip().lower() == norm_name
            and c.lastname.strip().lower() == norm_lastname
        ):
            reasons.append("name_exact")
            score = max(score, 0.9)

        if score >= min_score:
            matches.append(
                {
                    "candidate_id": c.id,
                    "name": c.name,
                    "lastname": c.lastname,
                    "email": c.email,
                    "match_score": round(score, 2),
                    "match_reasons": reasons,
                }
            )

    matches.sort(key=lambda x: -x["match_score"])
    return matches
