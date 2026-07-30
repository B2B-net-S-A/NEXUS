"""Pure helpers that fold a ``parse_cv()`` result into a Candidate row.

Extracted from ``app.api.candidates`` so the Traffit importer and the
name-backfill job can reuse the exact same enrichment contract without
importing the API layer (which would risk circular imports). ``candidates.py``
re-exports these names, so existing call-sites and tests keep working.

Contract (unchanged from the original upload path):
  * Contact fields (email/phone/first_name/last_name/city) are only backfilled
    when the candidate row is empty — the recruiter's typed values always win.
  * ``_manual_override_<field>`` flags in ``cv_extracted_data`` lock a field.
  * A rich ``experience`` record (entries with roles) is never downgraded to a
    flat company-name list — bulk Traffit imports are protected.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.candidate import Candidate
from app.services.candidate_quick_view import format_cv_highlight_bullets
from app.services.candidate_location_writer import (
    apply_candidate_location_from_source,
)

_CV_CONTACT_FIELDS = ("first_name", "last_name", "email", "phone", "city")

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
) -> int:
    """Pure function: mutate `candidate` fields from a `parse_cv()` result.

    Returns the number of companies that were written into `experience`
    (zero when the recruiter has manually curated it, or the AI returned no
    companies). This function is the unit-testable seam for Phase D4 — it
    has zero DB or async concerns.

    Contract:
      * Never clobbers recruiter-curated data (`_manual_override_experience`
        for employment; `_manual_override_<field>` for scalar contact fields).
      * Never downgrades a rich `experience` record (with roles) to a flat
        company-name list — bulk imports from Traffit are protected.
      * Preserves the manual-override flag across writes so the guard
        survives future uploads.
      * Preserves `traffit_*`-namespaced custom fields stored at import time —
        they do not collide with parse_cv keys and must survive enrichment.
      * Contact fields (email/phone/first_name/last_name/city) are only
        backfilled when the candidate row has them empty — the recruiter's
        typed values always win.
    """
    existing_extracted = dict(candidate.cv_extracted_data or {})
    manual_override = bool(existing_extracted.get("_manual_override_experience", False))

    if parsed.get("years_it_experience") is not None:
        candidate.years_it_experience = parsed["years_it_experience"]
    if parsed.get("skills"):
        candidate.skills = parsed["skills"]
    if parsed.get("education"):
        candidate.education = parsed["education"]
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
    if bullets:
        candidate.ai_summary = "\n".join(bullets)

    next_extracted = dict(parsed)
    next_extracted["cv_highlights"] = cv_highlights
    if manual_override:
        next_extracted["_manual_override_experience"] = True
    # Preserve any per-field manual overrides already recorded.
    for field in _CV_CONTACT_FIELDS:
        key = f"_manual_override_{field}"
        if existing_extracted.get(key):
            next_extracted[key] = True
    # Preserve Traffit custom fields (`traffit_*`) carried in cv_extracted_data
    # at import time — parse_cv never emits these keys, so a plain dict(parsed)
    # would silently drop them.
    for key, value in existing_extracted.items():
        if key.startswith("traffit_"):
            next_extracted.setdefault(key, value)
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
