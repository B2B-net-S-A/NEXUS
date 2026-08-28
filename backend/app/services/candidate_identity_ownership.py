"""Per-field ownership for candidate names imported from Traffit.

The legacy Traffit importer refreshes candidate identity every night.  A
recruiter can still correct either field in NEXUS; the correction becomes a
manual lock for that field while the other field remains source-managed.

Metadata lives in ``Candidate.custom_fields`` rather than
``cv_extracted_data``.  The latter is legacy JSON and can contain a list on
production, while ``custom_fields`` is the canonical non-null object intended
for integration metadata.  No schema migration is required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Mapping

from app.models.candidate import Candidate

IdentityField = Literal["name", "lastname"]

IDENTITY_META_KEY = "_nexus_identity"
_FIELD_CONFIG: dict[IdentityField, tuple[str, str, str, str, str]] = {
    "name": (
        "name_manual",
        "traffit_name",
        "name_set_at",
        "name_set_by",
        "name_ownership_reason",
    ),
    "lastname": (
        "lastname_manual",
        "traffit_lastname",
        "lastname_set_at",
        "lastname_set_by",
        "lastname_ownership_reason",
    ),
}


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _metadata(candidate: Candidate) -> tuple[dict[str, Any], dict[str, Any]]:
    custom_fields = _object(candidate.custom_fields)
    metadata = _object(custom_fields.get(IDENTITY_META_KEY))
    return custom_fields, metadata


def lock_changed_traffit_identity_fields(
    candidate: Candidate,
    updates: Mapping[str, Any],
    *,
    user_id: int | None,
    changed_at: datetime | None = None,
) -> list[IdentityField]:
    """Lock only identity fields whose effective value really changed.

    Both candidate edit UIs historically send ``name`` and ``lastname`` on
    every PATCH, even when the user edited only another field.  Comparing to
    the row value here prevents an unrelated edit from accidentally taking
    ownership of both names.
    """

    if candidate.external_source != "traffit":
        return []

    changed: list[IdentityField] = []
    for field in _FIELD_CONFIG:
        if field in updates and updates[field] != getattr(candidate, field):
            changed.append(field)
    if not changed:
        return []

    custom_fields, metadata = _metadata(candidate)
    stamp = (changed_at or datetime.now(timezone.utc)).isoformat()
    for field in changed:
        manual_key, _source_key, at_key, by_key, reason_key = _FIELD_CONFIG[field]
        metadata[manual_key] = True
        metadata[at_key] = stamp
        metadata[by_key] = user_id
        metadata[reason_key] = "manual_edit"
    custom_fields[IDENTITY_META_KEY] = metadata
    candidate.custom_fields = custom_fields
    return changed


def identity_sync_state(candidate: Candidate) -> dict[str, Any] | None:
    """Return the typed API projection consumed by the profile editor."""

    if candidate.external_source != "traffit":
        return None

    _custom_fields, metadata = _metadata(candidate)
    out: dict[str, Any] = {}
    for field, (
        manual_key,
        source_key,
        at_key,
        by_key,
        reason_key,
    ) in _FIELD_CONFIG.items():
        source_value = metadata.get(source_key)
        if not isinstance(source_value, str) or not source_value.strip():
            source_value = None
        manual = metadata.get(manual_key) is True
        override_token = metadata.get(at_key)
        if not isinstance(override_token, str) or not override_token.strip():
            override_token = None
        out[field] = {
            "owner": "nexus" if manual else "traffit",
            "manual_lock": manual,
            "traffit_value": source_value,
            "can_restore": manual
            and source_value is not None
            and override_token is not None,
            "overridden_at": override_token if manual else None,
            # Opaque round-trip token for optimistic concurrency.  Keep it
            # separate from ``overridden_at`` because response serializers may
            # canonicalise the same UTC instant from ``+00:00`` to ``Z``.
            "override_token": override_token if manual else None,
            "overridden_by": metadata.get(by_key) if manual else None,
            "ownership_reason": metadata.get(reason_key) if manual else None,
        }
    return out


def restore_traffit_identity_fields(
    candidate: Candidate,
    fields: Iterable[IdentityField],
    *,
    expected_current_values: Mapping[IdentityField, str],
    expected_source_values: Mapping[IdentityField, str],
    expected_override_tokens: Mapping[IdentityField, str],
) -> list[IdentityField]:
    """Restore selected fields from the last observed Traffit snapshot.

    Raises ``ValueError`` with a stable reason code when the request is stale or
    the importer has not observed a source value yet.  The API maps these codes
    to an actionable 409 response.
    """

    if candidate.external_source != "traffit":
        raise ValueError("identity_not_linked_to_traffit")

    requested = list(dict.fromkeys(fields))
    if not requested:
        raise ValueError("identity_restore_fields_required")
    if (
        set(expected_current_values) != set(requested)
        or set(expected_source_values) != set(requested)
        or set(expected_override_tokens) != set(requested)
    ):
        raise ValueError("identity_restore_expected_values_must_match_fields")

    custom_fields, metadata = _metadata(candidate)
    for field in requested:
        manual_key, source_key, _at_key, _by_key, _reason_key = _FIELD_CONFIG[field]
        if metadata.get(manual_key) is not True:
            raise ValueError(f"identity_field_not_manually_owned:{field}")
        if expected_override_tokens[field] != metadata.get(_at_key):
            raise ValueError(f"identity_override_version_changed:{field}")
        if expected_current_values[field] != getattr(candidate, field):
            raise ValueError(f"nexus_identity_value_changed:{field}")
        source_value = metadata.get(source_key)
        if not isinstance(source_value, str) or not source_value.strip():
            raise ValueError(f"traffit_identity_value_unavailable:{field}")
        if expected_source_values[field] != source_value:
            raise ValueError(f"traffit_identity_value_changed:{field}")

    for field in requested:
        manual_key, source_key, at_key, by_key, reason_key = _FIELD_CONFIG[field]
        setattr(candidate, field, metadata[source_key])
        metadata.pop(manual_key, None)
        metadata.pop(at_key, None)
        metadata.pop(by_key, None)
        metadata.pop(reason_key, None)

    custom_fields[IDENTITY_META_KEY] = metadata
    candidate.custom_fields = custom_fields
    return requested
