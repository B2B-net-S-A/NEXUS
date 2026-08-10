"""Pure helpers that fold a ``parse_cv()`` result into a Candidate row.

Extracted from ``app.api.candidates`` so the Traffit importer and the
name-backfill job can reuse the exact same enrichment contract without
importing the API layer (which would risk circular imports). ``candidates.py``
re-exports these names, so existing call-sites and tests keep working.

Contract:
  * Contact fields (email/phone/first_name/last_name/city) are only backfilled
    when the candidate row is empty — the recruiter's typed values always win.
  * ``_manual_override_<field>`` flags in ``cv_extracted_data`` lock a field.
  * A rich ``experience`` record (entries with roles) is never downgraded to a
    flat company-name list — bulk Traffit imports are protected.
  * ``skills`` / ``education`` / ``years_it_experience`` / ``ai_summary`` follow
    the caller's :class:`CvWritePolicy`, defaulting to fill-empty-only.

The last rule is new. Until 2026-08-10 those four were written unconditionally
while this docstring promised the opposite, so every CV upload silently replaced
whatever the recruiter had typed. The default is deliberately the safe one: a
call-site that forgets to pass a policy degrades to "backfill only", never to
"overwrite".
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from app.models.candidate import Candidate
from app.services.candidate_quick_view import format_cv_highlight_bullets
from app.services.candidate_location_writer import (
    apply_candidate_location_from_source,
)

_CV_CONTACT_FIELDS = ("first_name", "last_name", "email", "phone", "city")

# Fields an AI parse may author. Everything here is subject to `CvWritePolicy`
# and to a `_manual_override_<field>` lock.
_CV_AI_AUTHORED_FIELDS = (
    "skills",
    "education",
    "years_it_experience",
    "ai_summary",
)


class CvWritePolicy(str, enum.Enum):
    """How aggressively a parse result may write over existing column values.

    ``FILL_EMPTY`` — write only into empty slots. Correct for anything the user
    did not explicitly ask for: bulk backfills, mailbox attachments, first parse
    of a freshly created row.

    ``REFRESH`` — overwrite existing values, still honouring manual locks. Only
    for paths where a human just said "use this CV": a recruiter uploading a new
    file, or clicking re-parse.
    """

    FILL_EMPTY = "fill_empty"
    REFRESH = "refresh"


def _is_empty_value(value) -> bool:
    """True when a column holds nothing worth protecting.

    ``[]`` counts as empty and that is load-bearing, not incidental: 33 625 of
    56 783 candidate rows hold ``skills = '[]'`` (measured on prod 2026-08-10)
    against 273 with a real list. Treating ``[]`` as a value would make the
    backfill skip 99% of the rows it exists to fill.

    For integers, ``<= 0`` counts as empty — both zero and negatives. On prod
    that is 35 rows at 0 and none below it, but the rule covers both on purpose:
    "0 years of IT experience" is a parse artefact rather than something a
    recruiter typed, and a negative (a bad LLM parse) is corrupt outright. Either
    way the next backfill is free to replace it.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value <= 0
    return False


# Placeholder names that mean "no real value yet" even though the column is
# NOT NULL. ``/from-cv`` writes "Nieznane" when the LLM finds no name; the
# Traffit importer writes "?" when the source record has neither name nor a
# usable email. Both must be treated as blank so a later CV parse can fill them.
_CV_PLACEHOLDER_NAME = "Nieznane"
_CV_PLACEHOLDER_NAMES = frozenset({_CV_PLACEHOLDER_NAME, "?"})


def _is_blank_name(value) -> bool:
    """True when ``value`` is empty/None or a known placeholder ("?", "Nieznane")."""
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        return not stripped or stripped in _CV_PLACEHOLDER_NAMES
    return False


def _provenance_stamp(parsed: dict) -> dict:
    """Where a value came from, for the fields this run writes.

    Goes into `cv_extracted_data["_field_provenance"]` — already serialized to
    the frontend by `CandidateResponse`, so a badge needs no schema change and
    no migration across 56 783 rows.

    Deliberately **not** backfilled for pre-existing values: for legacy data we
    genuinely do not know who typed them, and inventing a stamp would fabricate
    an audit trail rather than record one.
    """
    confidence = parsed.get("_confidence")
    return {
        "source": parsed.get("_source") or "cv_parser",
        "at": datetime.now(timezone.utc).isoformat(),
        **(
            {"confidence": confidence}
            if isinstance(confidence, (int, float))
            else {"confidence_by_field": confidence}
            if isinstance(confidence, dict)
            else {}
        ),
    }


def _apply_cv_contact_fields(
    candidate: Candidate, parsed: dict, existing_extracted: dict
) -> None:
    """Backfill contact fields from a parse_cv() result.

    Each field is written only when:
      - the parsed value is truthy, AND
      - the candidate has no value yet (empty string / None / placeholder), AND
      - no `_manual_override_<field>` flag is set in `cv_extracted_data`.

    Location writes are delegated to the canonical city/country writer;
    ``location`` is rebuilt only as their compatibility projection.
    """

    def _locked(field: str) -> bool:
        return bool(existing_extracted.get(f"_manual_override_{field}"))

    first_name = parsed.get("first_name")
    if first_name and _is_blank_name(candidate.name) and not _locked("first_name"):
        candidate.name = str(first_name).strip()[:100]

    last_name = parsed.get("last_name")
    if last_name and _is_blank_name(candidate.lastname) and not _locked("last_name"):
        candidate.lastname = str(last_name).strip()[:100]

    email = parsed.get("email")
    if email and _is_blank_name(candidate.email) and not _locked("email"):
        candidate.email = str(email).strip().lower()[:255]

    phone = parsed.get("phone")
    if phone and _is_blank_name(candidate.phone) and not _locked("phone"):
        candidate.phone = str(phone).strip()[:30]

    city = parsed.get("city")
    if city:
        apply_candidate_location_from_source(
            candidate,
            city=city,
            overwrite_existing=False,
        )


def _apply_cv_enrichment(
    candidate: Candidate,
    parsed: dict,
    *,
    source_document_id: int | None = None,
    source_hash: str | None = None,
    policy: CvWritePolicy = CvWritePolicy.FILL_EMPTY,
) -> int:
    """Pure function: mutate `candidate` fields from a `parse_cv()` result.

    Returns the number of companies that were written into `experience`
    (zero when the recruiter has manually curated it, or the AI returned no
    companies). This function is the unit-testable seam for Phase D4 — it
    has zero DB or async concerns.

    Contract:
      * Never clobbers recruiter-curated data (`_manual_override_experience`
        for employment; `_manual_override_<field>` for scalar contact fields).
      * `skills` / `education` / `years_it_experience` / `ai_summary` obey
        `policy`: under the default `FILL_EMPTY` they are written only into
        empty slots, so a bulk run cannot erase curated values.
      * Never downgrades a rich `experience` record (with roles) to a flat
        company-name list — bulk imports from Traffit are protected.
      * Preserves **every** `_manual_override_*` flag across writes, not a
        hand-maintained subset.
      * Preserves `traffit_*`-namespaced custom fields stored at import time —
        they do not collide with parse_cv keys and must survive enrichment.
      * Contact fields (email/phone/first_name/last_name/city) are only
        backfilled when the candidate row has them empty — the recruiter's
        typed values always win.
      * Records `_field_provenance` in `cv_extracted_data` for the fields this
        call actually wrote, so the UI can mark them as AI-derived.
    """
    existing_extracted = dict(candidate.cv_extracted_data or {})
    manual_override = bool(existing_extracted.get("_manual_override_experience", False))
    provenance_stamp = _provenance_stamp(parsed)
    written_fields: list[str] = []

    def _may_write(field: str) -> bool:
        """Locks always win; otherwise REFRESH writes, FILL_EMPTY backfills."""
        if existing_extracted.get(f"_manual_override_{field}"):
            return False
        if policy is CvWritePolicy.REFRESH:
            return True
        return _is_empty_value(getattr(candidate, field, None))

    if parsed.get("years_it_experience") is not None and _may_write(
        "years_it_experience"
    ):
        candidate.years_it_experience = parsed["years_it_experience"]
        written_fields.append("years_it_experience")
    if parsed.get("skills") and _may_write("skills"):
        candidate.skills = parsed["skills"]
        written_fields.append("skills")
    if parsed.get("education") and _may_write("education"):
        candidate.education = parsed["education"]
        written_fields.append("education")
    # Language facts are persisted by the async canonical writer at each
    # caller.  This pure helper must not write the legacy JSONB column.
    # Only backfill LinkedIn URL when the recruiter hasn't set one manually —
    # we never want to clobber a curated value with a noisy regex hit.
    if parsed.get("linkedin_url") and not candidate.linkedin:
        from app.services.proxycurl import normalize_linkedin_url

        canonical = normalize_linkedin_url(parsed["linkedin_url"])
        if canonical:
            candidate.linkedin = canonical

    # v4: contact fields — only backfill empty slots, honour manual overrides.
    _apply_cv_contact_fields(candidate, parsed, existing_extracted)

    generated_at = datetime.now(timezone.utc)
    cv_highlights = {
        "profile": parsed.get("professional_profile") or parsed.get("career_summary"),
        "years_experience": parsed.get("years_it_experience"),
        "current_role": parsed.get("current_position"),
        "current_role_started_at": parsed.get("current_position_started_at"),
        "current_role_started_at_precision": parsed.get(
            "current_position_started_at_precision", "unknown"
        ),
        "technologies": list(parsed.get("technologies") or [])[:8],
        "sectors": list(parsed.get("sectors") or [])[:4],
        "source_document_id": source_document_id,
        "source_hash": source_hash,
        "extractor_version": parsed.get("_source"),
        "generated_at": generated_at.isoformat(),
    }
    bullets = format_cv_highlight_bullets(cv_highlights)
    if bullets and _may_write("ai_summary"):
        candidate.ai_summary = "\n".join(bullets)
        written_fields.append("ai_summary")

    next_extracted = dict(parsed)
    # `cv_highlights` is refreshed even when `ai_summary` was blocked above, and
    # that asymmetry is deliberate: `resolve_cv_highlights` exists precisely to
    # "return only CV-provenanced facts; never trust generic ai_summary". The two
    # are separate channels — highlights are what the newest CV says, `ai_summary`
    # is prose a recruiter may have rewritten. Freezing highlights alongside a
    # curated summary would stale the one field guaranteed to come from the CV.
    next_extracted["cv_highlights"] = cv_highlights
    # Preserve EVERY manual-override flag, not a hand-maintained list. The old
    # code copied only `_CV_CONTACT_FIELDS`, so `_manual_override_country` — set
    # by both importers and read by the location writer — was silently dropped on
    # every parse, quietly unlocking a field someone had locked on purpose.
    # Precedent for the prefix rule: candidate_identity_quarantine.
    for key, value in existing_extracted.items():
        if key.startswith("_manual_override_") and value:
            next_extracted[key] = value
    # Preserve Traffit custom fields (`traffit_*`) carried in cv_extracted_data
    # at import time — parse_cv never emits these keys, so a plain dict(parsed)
    # would silently drop them.
    for key, value in existing_extracted.items():
        if key.startswith("traffit_"):
            next_extracted.setdefault(key, value)
    # Merge, never replace: fields this run left alone keep whatever provenance
    # an earlier run recorded for them.
    provenance = dict(existing_extracted.get("_field_provenance") or {})
    for field in written_fields:
        provenance[field] = provenance_stamp
    if provenance:
        next_extracted["_field_provenance"] = provenance
    candidate.cv_extracted_data = next_extracted

    companies = parsed.get("companies") or []
    has_rich_experience = bool(candidate.experience) and any(
        isinstance(e, dict) and e.get("role") for e in (candidate.experience or [])
    )
    written = 0
    if companies and not manual_override and not has_rich_experience:
        candidate.experience = [
            {
                "company": name,
                "role": None,
                "start": None,
                "end": None,
                "desc": None,
            }
            for name in companies
        ]
        written = len(companies)

    candidate.cv_parsed_at = generated_at
    return written
