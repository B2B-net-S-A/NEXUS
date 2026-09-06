"""Integration API: "who from our base worked at this company?".

Consumed by ATLAS (lead-gen CRM) to answer, on a deal/company card, whether
NEXUS knows anyone connected to that company. First real consumer of the
OAuth2 client_credentials machinery in ``app.api.oauth_token`` — every route
here is guarded by ``require_scope``, never by a user JWT.

Three relationship buckets, strongest first:

- ``via_us``  — placed there through us (``Contract`` with that client, or a
  ``current_employment`` conflict flag). The strongest sales signal: it is a
  reference, not a coincidence.
- ``current`` — works there now (``linkedin_current_company`` or an
  ``experience[*]`` entry with ``end IS NULL``).
- ``past``    — worked there before (any other ``experience[*]`` entry).

Matching is EXACT on the canonical company name, not substring. The UI filters
in ``app.api.candidates`` use ``LIKE '%value%'`` because a human picks the
string from an autocomplete; here the caller is a machine passing a CRM
company name, and a false positive surfaces in a sales conversation as
"we told them we have people there" when we do not. The substring predicates
are still used as a cheap SQL prefilter — the exact decision happens in
``_match_experience`` against ``normalize_company_name``.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

# Reused deliberately: duplicating the JSONB predicates would create a second
# source of truth for tricky SQL that has already been debugged once (see the
# `end IS NULL` vs `experience[0]` note in candidates.py).
from app.api.candidates import (
    _current_company_predicate,
    _past_company_predicate,
    _worked_at_client_predicate,
)
from app.api.oauth_token import ClientPrincipal, require_scope
from app.core.config import settings
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.oauth_client import OAuthScope

router = APIRouter()

# Shortest canonical name we will look up. Two-letter tokens ("IT", "AB")
# match far too much even under exact comparison once a CRM name normalises
# down to them, and the SQL prefilter would scan the whole candidate table.
_MIN_NAME_LEN = 3

# Hard ceiling on returned people. A company like a large bank legitimately has
# hundreds of matches; the caller renders a panel, not an export.
_MAX_PEOPLE = 200

# Ported verbatim from ATLAS `src/services/company_service.py` so both sides
# agree byte-for-byte on what "the same company" means. Any change here MUST be
# mirrored there, otherwise matches silently diverge between the two systems.
_SUFFIXES = [
    " sp. z o.o.",
    " sp.z o.o.",
    " sp z oo",
    " sp. z o. o.",
    " spolka z o.o.",
    " sp. j.",
    " sp.j.",
    " s.a.",
    " sa",
    " s.k.",
    " sp k",
    " sp. k.",
    " s.c.",
    " s. c.",
    " sp. komandytowa",
    " spółka z ograniczoną odpowiedzialnością",
    " spolka z ograniczona odpowiedzialnoscia",
    " inc",
    " inc.",
    " ltd",
    " ltd.",
    " gmbh",
]


def normalize_company_name(name: str) -> str:
    """Canonical form used for cross-system company matching.

    Keep in lockstep with ATLAS ``src/services/company_service.py``.
    """
    if not name:
        return ""
    s = name.strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("ł", "l")
    for suf in _SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)].rstrip()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _normalize_nip(nip: Optional[str]) -> str:
    """Digits only — CRMs store NIP with dashes, spaces or a `PL` prefix."""
    return re.sub(r"\D", "", nip or "")


# ── Schemas ──────────────────────────────────────────────────────────────────


Relationship = Literal["via_us", "current", "past"]


class CompanyPeopleRequest(BaseModel):
    """Look up one company, optionally under several known aliases."""

    names: list[str] = Field(
        ...,
        min_length=1,
        max_length=10,
        description=(
            "Company name plus any aliases the caller has pinned. All are "
            "matched against the canonical form; the first non-empty one is "
            "echoed back as `query`."
        ),
    )
    nip: Optional[str] = Field(
        None,
        max_length=32,
        description=(
            "Optional NIP. When it matches a NEXUS client it resolves the "
            "`via_us` bucket deterministically, independent of name spelling."
        ),
    )
    limit: int = Field(100, ge=1, le=_MAX_PEOPLE)


class ExperiencePeriod(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None


class MatchedPerson(BaseModel):
    """One candidate connected to the queried company."""

    candidate_id: int
    name: str
    lastname: str
    relationship: Relationship
    title: Optional[str] = None
    company_matched: Optional[str] = Field(
        None, description="The raw company string as it appears in NEXUS."
    )
    period: Optional[ExperiencePeriod] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    profile_url: Optional[str] = None


class MatchedClient(BaseModel):
    id: int
    name: str


class CompanyPeopleResponse(BaseModel):
    query: str
    canonical: str
    matched_client: Optional[MatchedClient] = None
    counts: dict[str, int]
    truncated: bool = Field(
        False, description="True when more matches exist than `limit` returned."
    )
    people: list[MatchedPerson]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _candidate_columns():
    """Only the columns this endpoint reads.

    `select(Candidate)` is NOT safe here: `raw_cv_text` (Text) and
    `cv_file_content` (LargeBinary) are eagerly loaded by default, and a lookup
    for a large employer legitimately matches hundreds of candidates — that is
    hundreds of full CV bodies and binary blobs off the wire per uncached call.
    """
    return load_only(
        Candidate.id,
        Candidate.name,
        Candidate.lastname,
        Candidate.email,
        Candidate.phone,
        Candidate.linkedin,
        Candidate.experience,
        Candidate.linkedin_current_company,
        Candidate.linkedin_current_title,
        Candidate.linkedin_current_started_at,
    )


def _experience_entries(candidate: Candidate) -> list[dict[str, Any]]:
    """`experience` JSONB as a list of dicts.

    Legacy rows hold scalars or bare objects rather than an array — the SQL
    predicates guard with ``jsonb_typeof``, and so must we.
    """
    raw = candidate.experience
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict)]


def _match_experience(
    candidate: Candidate, canonical_names: set[str]
) -> tuple[Optional[Relationship], Optional[dict[str, Any]]]:
    """Decide this candidate's relationship to the company, exactly.

    Returns ``(relationship, matching_entry)`` where relationship is
    ``current`` or ``past``, or ``(None, None)`` when the SQL prefilter matched
    on a substring that does not survive canonical comparison.

    `via_us` is NOT decided here — it comes from contracts, not from CV text.
    """
    # LinkedIn is the freshest current-employment signal and has no period.
    linkedin_company = candidate.linkedin_current_company or ""
    if linkedin_company and normalize_company_name(linkedin_company) in canonical_names:
        return "current", {
            "company": linkedin_company,
            "role": candidate.linkedin_current_title,
            "start": (
                candidate.linkedin_current_started_at.isoformat()
                if candidate.linkedin_current_started_at
                else None
            ),
            "end": None,
        }

    fallback: Optional[dict[str, Any]] = None
    for entry in _experience_entries(candidate):
        company = entry.get("company")
        if not isinstance(company, str):
            continue
        if normalize_company_name(company) not in canonical_names:
            continue
        # `end IS NULL` is the canonical current-job marker (see candidates.py).
        if entry.get("end") in (None, ""):
            return "current", entry
        if fallback is None:
            fallback = entry
    if fallback is not None:
        return "past", fallback
    return None, None


def _profile_url(candidate_id: int) -> Optional[str]:
    """Deep link into the NEXUS UI, so ATLAS can hand the user a way back."""
    base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    return f"{base}/candidates/{candidate_id}" if base else None


def _to_person(
    candidate: Candidate,
    relationship: Relationship,
    entry: Optional[dict[str, Any]],
) -> MatchedPerson:
    period = None
    if entry is not None and (entry.get("start") or entry.get("end")):
        period = ExperiencePeriod(
            start=entry.get("start") or None, end=entry.get("end") or None
        )
    title = None
    if entry is not None:
        title = entry.get("role") or entry.get("title") or None
    return MatchedPerson(
        candidate_id=candidate.id,
        name=candidate.name,
        lastname=candidate.lastname,
        relationship=relationship,
        title=title or candidate.linkedin_current_title,
        company_matched=(entry or {}).get("company"),
        period=period,
        email=candidate.email,
        phone=candidate.phone,
        linkedin=candidate.linkedin,
        profile_url=_profile_url(candidate.id),
    )


async def _resolve_client(
    db: AsyncSession, canonical_names: set[str], nip: str
) -> Optional[MatchedClient]:
    """Find the NEXUS client for this company — NIP first, then exact name.

    NIP is authoritative when both sides have it. Name comparison is canonical,
    so "Nordea Bank Abp" and "Nordea Bank" collapse the way they do in the CV
    matcher. Only the four identity columns are selected: the client row is
    wide (contract terms, notes) and nothing else here is read.

    Merged-away clients are excluded and hidden duplicates deprioritised — see
    the query comment.
    """
    # `hidden` marks a duplicate spelling and `merged_into_client_id` a client
    # folded into another. Matching either would hand back an id whose contracts
    # live on the surviving row, so `via_us` would silently come back empty.
    # Ordering puts the canonical row first when a name still matches several.
    labels = (
        select(Client.id, Client.name, Client.legal_name, Client.display_name)
        .where(Client.merged_into_client_id.is_(None))
        .order_by(Client.hidden.asc(), Client.id.asc())
    )

    if nip:
        # Digits-only comparison in SQL — CRMs store NIP with dashes or a `PL`
        # prefix, so an equality test on the raw column silently misses.
        row = (
            await db.execute(
                labels.where(
                    func.regexp_replace(func.coalesce(Client.nip, ""), r"\D", "", "g")
                    == nip
                ).limit(1)
            )
        ).first()
        if row is not None:
            return MatchedClient(id=row.id, name=row.display_name or row.name)

    for row in (await db.execute(labels)).all():
        for label in (row.name, row.legal_name, row.display_name):
            if label and normalize_company_name(label) in canonical_names:
                return MatchedClient(id=row.id, name=row.display_name or row.name)
    return None


# ── Route ────────────────────────────────────────────────────────────────────


@router.post(
    "/companies/people",
    response_model=CompanyPeopleResponse,
    summary="People from the NEXUS base connected to a company",
)
async def company_people(
    payload: CompanyPeopleRequest,
    principal: ClientPrincipal = Depends(require_scope(OAuthScope.candidate_read)),
    db: AsyncSession = Depends(get_db),
) -> CompanyPeopleResponse:
    """Return candidates who work / worked at the given company.

    Buckets are mutually exclusive and ranked ``via_us > current > past`` — a
    candidate placed there through us is reported as ``via_us`` even when the
    CV also lists the company.
    """
    raw_names = [n.strip() for n in payload.names if n and n.strip()]
    if not raw_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="names_empty",
        )

    canonical_names = {
        c
        for c in (normalize_company_name(n) for n in raw_names)
        if len(c) >= _MIN_NAME_LEN
    }
    if not canonical_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "name_too_short",
                "min_length": _MIN_NAME_LEN,
                "hint": "Canonical company name must be at least 3 characters.",
            },
        )

    client = await _resolve_client(db, canonical_names, _normalize_nip(payload.nip))

    # ── via_us: authoritative, from contracts — independent of CV text ──────
    via_us_ids: set[int] = set()
    if client is not None:
        via_us_rows = (
            await db.execute(
                select(Candidate)
                .options(_candidate_columns())
                .where(_worked_at_client_predicate([client.id]))
            )
        ).scalars()
        via_us: list[Candidate] = list(via_us_rows)
        via_us_ids = {c.id for c in via_us}
    else:
        via_us = []

    # ── current / past: SQL prefilter (substring) then exact canonical match ─
    name_list = list(canonical_names) + raw_names
    cv_rows = (
        (
            await db.execute(
                select(Candidate)
                .options(_candidate_columns())
                .where(
                    or_(
                        _current_company_predicate(name_list),
                        _past_company_predicate(name_list),
                    )
                )
            )
        )
        .scalars()
        .all()
    )

    people: list[MatchedPerson] = []
    counts = {"via_us": 0, "current": 0, "past": 0}

    for candidate in via_us:
        _, entry = _match_experience(candidate, canonical_names)
        if entry is None and client is not None:
            # Placed there on a contract but the CV never mentions it — common
            # for body-leasing. Without this the row would render with a blank
            # company, which reads as a bug in exactly the bucket that matters.
            entry = {"company": client.name}
        people.append(_to_person(candidate, "via_us", entry))
        counts["via_us"] += 1

    for candidate in cv_rows:
        if candidate.id in via_us_ids:
            continue  # already reported under the stronger bucket
        relationship, entry = _match_experience(candidate, canonical_names)
        if relationship is None:
            continue  # substring prefilter hit, canonical comparison rejected
        people.append(_to_person(candidate, relationship, entry))
        counts[relationship] += 1

    order = {"via_us": 0, "current": 1, "past": 2}
    people.sort(key=lambda p: (order[p.relationship], p.lastname or "", p.name or ""))

    truncated = len(people) > payload.limit
    return CompanyPeopleResponse(
        query=raw_names[0],
        canonical=sorted(canonical_names)[0],
        matched_client=client,
        counts=counts,
        truncated=truncated,
        people=people[: payload.limit],
    )
