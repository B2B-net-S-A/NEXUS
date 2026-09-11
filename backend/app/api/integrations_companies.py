"""Integration API: "who from our base worked at this company?".

Consumed by ATLAS (lead-gen CRM) to answer, on a deal/company card, whether
NEXUS knows anyone connected to that company. First real consumer of the
OAuth2 client_credentials machinery in ``app.api.oauth_token`` — every route
here is guarded by ``require_scope``, never by a user JWT.

Three relationship buckets, strongest first:

- ``via_us``  — placed there through us: a ``Contract`` with that client that
  ran (``active``/``ending``/``ended``), or a ``draft`` /
  ``ready_for_signature`` one that carries a real engagement — an active
  order or the candidate's current ``hired`` stage in that client's
  recruitment (``contract_service.placed_contract_clause``, the contractor
  registry's liveness definition). Hiring creates a draft contract that
  Delivery completes later, so dropping every draft dropped real placements;
  a bare draft and a ``void`` contract still do not count — "we placed people
  there" must be a reference we can back up.
- ``current`` — works there now (``linkedin_current_company``, an
  ``experience[*]`` entry whose ``end`` marks a current job — empty or
  "present"/"obecnie"-like, ``experience_end`` — or an ACTIVE
  ``current_employment`` conflict flag — that flag says "employed there now",
  not "placed by us").
- ``past``    — worked there before (any other ``experience[*]`` entry, or a
  conflict flag that is no longer active).

Matching is EXACT on the canonical company name, not substring. The UI filters
in ``app.api.candidates`` use ``LIKE '%value%'`` because a human picks the
string from an autocomplete; here the caller is a machine passing a CRM
company name, and a false positive surfaces in a sales conversation as
"we told them we have people there" when we do not. The substring predicates
are still used as a cheap SQL prefilter — the exact decision happens in
``_match_experience`` against ``normalize_company_name``.

The prefilter is BOUNDED: every name handed to ``LIKE`` passes the canonical
minimum length (a raw alias whose canonical form is "it" used to slip through
as ``LIKE '%it%'`` and scan — and load — most of the table), every query has a
row cap, and the whole lookup runs under a transaction-local statement
timeout. When a cap is hit the answer is flagged ``truncated`` instead of
pretending to be complete.
"""

# NIE dodawaj tu `from __future__ import annotations`.
#
# Ten moduł łączy `@limiter.limit` z modelem Pydantic jako body (`payload:
# CompanyPeopleRequest`). Przy PEP 563 + slowapi #579 taka trójka potrafi
# skończyć się tym, że FastAPI weźmie body za parametr Query i odda 422 na
# każde poprawne żądanie (patrz CLAUDE.md oraz `talent_radar.py` /
# `service_accounts.py`, które unikają tego importu z tego samego powodu).
#
# Zmierzone 2026-09-06: z tym importem endpoint MIMO WSZYSTKO działał poprawnie
# (`openapi()` pokazywał `requestBody`, zero parametrów query) — warunkiem
# awarii jest dopiero `Annotated` guard jako parametr, nie sam import. Import
# usunięty mimo to: nic go tu nie potrzebuje (żadna adnotacja w tym pliku nie
# wymaga leniwej ewaluacji), a 25 z 28 modułów z limiterem go nie ma. Dołożenie
# `Annotated`-owego parametru w przyszłości nie powinno wysadzać endpointu.

import re
import unicodedata
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

# Reused deliberately: duplicating the JSONB predicates would create a second
# source of truth for tricky SQL that has already been debugged once (see the
# `end IS NULL` vs `experience[0]` note in candidates.py).
from app.api.candidates import (
    _current_company_predicate,
    _past_company_predicate,
)
from app.api.oauth_token import ClientPrincipal, require_scope
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.client import Client
from app.models.contract import Contract
from app.models.oauth_client import OAuthScope
from app.services.contract_service import placed_contract_clause
from app.services.experience_end import is_current_end

router = APIRouter()

# Shortest canonical name we will look up. Two-letter tokens ("IT", "AB")
# match far too much even under exact comparison once a CRM name normalises
# down to them, and the SQL prefilter would scan the whole candidate table.
_MIN_NAME_LEN = 3

# Row cap per query. The substring prefilter is deliberately loose (the exact
# decision happens in Python), so without a cap a short canonical name loads
# every candidate whose CV mentions it — for "ing" that is most of the table.
# Well above `_MAX_PEOPLE`, so the exact pass still has room to find a full
# page; hitting it flags the answer `truncated`.
_PREFILTER_ROW_CAP = 2000

# Transaction-local ceiling for the whole lookup. The JSONB predicates scan
# the candidate table; a pathological name must fail fast (503) instead of
# holding a worker and a connection for minutes.
_STATEMENT_TIMEOUT_MS = 8000

# Per-name character cap. `max_length` on the list bounds how MANY names arrive,
# not how long each one is — without this a single 50 000-char name becomes a
# `LIKE '%…%'` pattern handed to Postgres. Matches ATLAS `companies.name`
# (VARCHAR(500)), so no legitimate CRM name is rejected.
_MAX_NAME_CHARS = 500

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

    names: list[Annotated[str, Field(max_length=_MAX_NAME_CHARS)]] = Field(
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
    counts: dict[str, int] = Field(
        ...,
        description=(
            "Matches per bucket BEFORE `limit` is applied — so the caller can "
            "say 'we know 150 people there' while listing 100. When "
            "`truncated` is true, sum(counts) is larger than len(people); "
            "render the two from the same source or the UI contradicts itself. "
            "When a prefilter row cap was hit, counts are LOWER BOUNDS."
        ),
    )
    truncated: bool = Field(
        False,
        description=(
            "True when more matches exist than `limit` returned, or when a "
            "prefilter row cap was hit (the scan did not see every candidate)."
        ),
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
        # `end IS NULL` is the canonical current-job marker (see candidates.py);
        # an empty `end` and "present"/"obecnie"-like words mean the same
        # (`experience_end` — one rule with the candidate filters).
        if is_current_end(entry.get("end")):
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
# Every call scans candidates through the JSONB predicates, so the scope check
# alone is not a throughput bound. 60/min is far above a CRM panel's real need
# (ATLAS caches each answer for 5 minutes) and far below useful enumeration.
@limiter.limit("60/minute")
async def company_people(
    payload: CompanyPeopleRequest,
    request: Request,  # required by slowapi limiter
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

    canonical_by_raw = {n: normalize_company_name(n) for n in raw_names}
    canonical_names = {c for c in canonical_by_raw.values() if len(c) >= _MIN_NAME_LEN}
    if not canonical_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "name_too_short",
                "min_length": _MIN_NAME_LEN,
                "hint": "Canonical company name must be at least 3 characters.",
            },
        )

    try:
        return await _lookup_company_people(
            db,
            payload=payload,
            raw_names=raw_names,
            canonical_by_raw=canonical_by_raw,
            canonical_names=canonical_names,
        )
    except DBAPIError as exc:
        if not _is_statement_timeout(exc):
            raise
        # The aborted transaction must be rolled back before the dependency's
        # commit — otherwise the 503 turns into a PendingRollbackError 500.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "lookup_timeout",
                "hint": "Lookup exceeded the time budget — retry with a more specific company name.",
            },
        ) from exc


def _is_statement_timeout(exc: DBAPIError) -> bool:
    """`statement_timeout` fired (SQLSTATE 57014), not some other DB failure."""
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate == "57014":
        return True
    text_ = f"{type(orig).__name__} {orig}".lower() if orig is not None else ""
    return "querycanceled" in text_ or "statement timeout" in text_


async def _lookup_company_people(
    db: AsyncSession,
    *,
    payload: CompanyPeopleRequest,
    raw_names: list[str],
    canonical_by_raw: dict[str, str],
    canonical_names: set[str],
) -> CompanyPeopleResponse:
    """The bounded lookup itself — every query below runs under the timeout."""
    # Transaction-local: resets on commit/rollback, never leaks to the pool.
    await db.execute(
        select(func.set_config("statement_timeout", str(_STATEMENT_TIMEOUT_MS), True))
    )

    client = await _resolve_client(db, canonical_names, _normalize_nip(payload.nip))
    capped = False

    # ── via_us: authoritative, from contracts that ran — independent of CV ──
    via_us: list[Candidate] = []
    conflict_active: dict[int, bool] = {}
    if client is not None:
        via_us = list(
            (
                await db.execute(
                    select(Candidate)
                    .options(_candidate_columns())
                    .where(
                        select(1)
                        .where(
                            and_(
                                Contract.candidate_id == Candidate.id,
                                Contract.client_id == client.id,
                                placed_contract_clause(),
                            )
                        )
                        .exists()
                    )
                    .order_by(Candidate.id)
                    .limit(_PREFILTER_ROW_CAP + 1)
                )
            ).scalars()
        )
        # One row per candidate here (EXISTS, not a join), so rows == people.
        if len(via_us) > _PREFILTER_ROW_CAP:
            via_us, capped = via_us[:_PREFILTER_ROW_CAP], True

        # A `current_employment` flag says "employed there", not "placed by
        # us" — it belongs to `current` (active) or `past` (lifted), never to
        # the reference bucket.
        conflict_rows = (
            await db.execute(
                select(CandidateConflict.candidate_id, CandidateConflict.active)
                .where(
                    CandidateConflict.client_id == client.id,
                    CandidateConflict.type == ConflictType.current_employment,
                )
                .order_by(CandidateConflict.candidate_id)
                .limit(_PREFILTER_ROW_CAP + 1)
            )
        ).all()
        # The cap is on ROWS: a person with several lifted flags has several
        # rows. Counting distinct people (the dict below) hid a cut — cap+1
        # rows for fewer than cap people came back as a complete answer.
        if len(conflict_rows) > _PREFILTER_ROW_CAP:
            conflict_rows, capped = conflict_rows[:_PREFILTER_ROW_CAP], True
        for candidate_id, active in conflict_rows:
            conflict_active[candidate_id] = conflict_active.get(
                candidate_id, False
            ) or bool(active)
    via_us_ids = {c.id for c in via_us}

    # ── current / past: SQL prefilter (substring) then exact canonical match ─
    # Raw aliases stay in the prefilter — SQL `lower()` does not strip Polish
    # diacritics or punctuation the way `normalize_company_name` does, so
    # "Żabka" in a CV only matches the raw spelling — but ONLY when their
    # canonical twin passed the minimum length. Before, a raw alias bypassed
    # that rule and "IT" went out as `LIKE '%it%'`.
    name_list = sorted(canonical_names) + [
        raw
        for raw, canonical in canonical_by_raw.items()
        if canonical in canonical_names
    ]
    cv_rows = list(
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
                .order_by(Candidate.id)
                .limit(_PREFILTER_ROW_CAP + 1)
            )
        )
        .scalars()
        .all()
    )
    if len(cv_rows) > _PREFILTER_ROW_CAP:
        cv_rows, capped = cv_rows[:_PREFILTER_ROW_CAP], True

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

    reported: set[int] = set(via_us_ids)
    for candidate in cv_rows:
        if candidate.id in reported:
            continue  # already reported under the stronger bucket
        relationship, entry = _match_experience(candidate, canonical_names)
        if relationship is None:
            continue  # substring prefilter hit, canonical comparison rejected
        if relationship == "past" and conflict_active.get(candidate.id):
            # The CV lists an older stint, but the client flagged the person
            # as employed there NOW — the flag is the fresher signal.
            relationship = "current"
        people.append(_to_person(candidate, relationship, entry))
        counts[relationship] += 1
        reported.add(candidate.id)

    # Conflict-flagged people whose CV never names the company (or did not
    # survive the prefilter cap) — reported from the flag alone.
    missing_flagged = [cid for cid in conflict_active if cid not in reported]
    if missing_flagged:
        for candidate in (
            await db.execute(
                select(Candidate)
                .options(_candidate_columns())
                .where(Candidate.id.in_(missing_flagged))
                .order_by(Candidate.id)
            )
        ).scalars():
            relationship = "current" if conflict_active[candidate.id] else "past"
            people.append(
                _to_person(
                    candidate,
                    relationship,
                    {"company": client.name if client else None},
                )
            )
            counts[relationship] += 1
            reported.add(candidate.id)

    order = {"via_us": 0, "current": 1, "past": 2}
    people.sort(key=lambda p: (order[p.relationship], p.lastname or "", p.name or ""))

    truncated = capped or len(people) > payload.limit
    return CompanyPeopleResponse(
        query=raw_names[0],
        canonical=sorted(canonical_names)[0],
        matched_client=client,
        counts=counts,
        truncated=truncated,
        people=people[: payload.limit],
    )
