"""The read-only `user` role gets a redacted jobs projection, not a 403.

The jobs list and detail sit behind the /jobs sidebar item, which is not
role-gated — a read-only `user` (which per deps.py may be a client-side account)
can reach them. Blanket-gating with a 403 would blank the main jobs screen and
read as "my data disappeared" (the #791 → #815 precedent). Instead the response
keeps its shape and the sensitive fields come back as None: money, the whole
champion sourcing profile, internal close notes, custom fields, the job
description/requirements, and the internal staff roster.

This is pinned because the failure mode is silent: someone adds a new sensitive
field to JobResponse, and it ships to every client viewer because nobody
remembered to add it to the redaction list. The test compares the redaction
list against the actual schema and fails when a plausibly-sensitive new field
appears unredacted.
"""

from __future__ import annotations

from app.api.candidate_access import _VIEWER_REDACTED_JOB_FIELDS, redact_job_for_viewer
from app.models.user import UserRole


class _StubUser:
    """Minimal stand-in — avoids initialising the full SQLAlchemy mapper graph
    (Skill/Cortex relationships) just to exercise role logic. Mirrors the real
    User.has_role / has_any_role over primary + secondary roles."""

    def __init__(self, role, roles=None):
        self.role = role
        self.roles = roles or [role.value]

    def has_role(self, r) -> bool:
        target = r.value if isinstance(r, UserRole) else str(r)
        if self.role is not None and self.role.value == target:
            return True
        return target in (self.roles or [])

    def has_any_role(self, *rs) -> bool:
        return any(self.has_role(r) for r in rs)


def _make_job_dict() -> dict:
    return {
        "id": 1,
        "title": "Senior Engineer",
        "status": "open",
        "client_name": "ACME",
        "deadline": "2026-08-01",
        "headcount": 2,
        "salary_min": 20000,
        "salary_max": 30000,
        "champion_profile": {"sourcing": {"target_companies": ["Rival Corp"]}},
        "close_notes": "internal only",
        "close_reason": "filled",
        "custom_fields": {"x": 1},
        "description": "long text",
        "requirements": "must-haves",
        "primary_owner": {"id": 9, "email": "rec@example.com", "name": "Rec"},
        "collaborators": [{"id": 10, "email": "c@example.com", "name": "Col"}],
    }


def _viewer():
    return _StubUser(UserRole.user)


def _recruiter():
    return _StubUser(UserRole.recruiter)


def test_viewer_loses_sensitive_fields_but_keeps_shape() -> None:
    original_keys = set(_make_job_dict().keys())
    redacted = redact_job_for_viewer(_make_job_dict(), _viewer())

    # Shape is preserved — no key removed, so the frontend never hits a missing
    # field. The values are blanked instead.
    assert set(redacted.keys()) == original_keys

    assert redacted["salary_min"] is None
    assert redacted["salary_max"] is None
    assert redacted["champion_profile"] is None
    assert redacted["close_notes"] is None
    assert redacted["custom_fields"] is None
    assert redacted["primary_owner"] is None
    assert redacted["collaborators"] == []

    # The viewer still gets what makes the board legible.
    assert redacted["title"] == "Senior Engineer"
    assert redacted["status"] == "open"
    assert redacted["client_name"] == "ACME"
    assert redacted["headcount"] == 2


def test_operational_role_sees_everything() -> None:
    full = _make_job_dict()
    result = redact_job_for_viewer(_make_job_dict(), _recruiter())
    # A recruiter (and every operational role above) is untouched.
    assert result == full


def test_secondary_operational_role_is_not_treated_as_viewer() -> None:
    """A user whose PRIMARY role is `user` but who also holds a secondary
    operational role must see the full projection — the multi-role trap that
    bit seven authorisation sites in this codebase must not reappear here."""
    hybrid = _StubUser(UserRole.user, [UserRole.user.value, UserRole.recruiter.value])
    result = redact_job_for_viewer(_make_job_dict(), hybrid)
    assert result["salary_min"] == 20000, "secondary recruiter role must lift redaction"


def test_redaction_list_covers_known_sensitive_schema_fields() -> None:
    """Guardrail: if a plausibly-sensitive field is added to JobResponse and not
    redacted, this fails so the omission is a conscious decision, not an oversight."""
    from app.schemas.job import JobResponse

    fields = set(JobResponse.model_fields)
    # Substrings that mark a field as something a client viewer should not see.
    # Whole-token markers, not substrings: an earlier "rate" matched
    # criteria_generated_at ("crite-RATE-d"), which is a timestamp, not money.
    sensitive_markers = ("salary", "margin", "rate_", "_rate", "_cost", "champion", "close_", "custom_")
    should_be_redacted = {
        f for f in fields if any(m in f for m in sensitive_markers)
    }
    missing = should_be_redacted - set(_VIEWER_REDACTED_JOB_FIELDS)
    assert not missing, (
        f"JobResponse gained sensitive field(s) not in the viewer redaction list: "
        f"{sorted(missing)}. Add them to _VIEWER_REDACTED_JOB_FIELDS or justify the "
        "exception."
    )
