"""Unit tests for the webhook state machine + idempotency layer.

Tests the pure helper functions that map Autenti event_type/status fields
to NEXUS SignatureStatus transitions. The full integration path (DB
inserts, signed PDF download) lives in ``test_autenti_webhook.py``.
"""

from __future__ import annotations

from app.models.document_signature import SignatureStatus
from app.services.autenti.webhook_handler import (
    _extract_event_id,
    _extract_event_type,
    _extract_process_id,
    _intermediate_status_for_event,
    _terminal_status_for_event,
)


# ── Field extraction ───────────────────────────────────────────────────────


def test_extract_process_id_top_level():
    assert _extract_process_id({"processId": "abc-123"}) == "abc-123"


def test_extract_process_id_snake_case():
    assert _extract_process_id({"process_id": "snake-id"}) == "snake-id"


def test_extract_process_id_nested():
    assert _extract_process_id({"data": {"id": "nested-id"}}) == "nested-id"


def test_extract_process_id_returns_none_when_missing():
    assert _extract_process_id({}) is None


def test_extract_event_id_prefers_jti():
    assert _extract_event_id({"jti": "j1", "eventId": "e1"}) == "j1"


def test_extract_event_id_falls_back_to_event_id():
    assert _extract_event_id({"event_id": "alt"}) == "alt"


def test_extract_event_type_falls_back_to_status():
    assert _extract_event_type({"status": "COMPLETED"}) == "STATUS:COMPLETED"


def test_extract_event_type_returns_unknown_when_missing():
    assert _extract_event_type({}) == "UNKNOWN"


# ── Terminal status mapping ────────────────────────────────────────────────


def test_terminal_signing_completed_maps_to_completed():
    assert (
        _terminal_status_for_event("SIGNING_PROCESS_COMPLETED", None)
        == SignatureStatus.completed
    )


def test_terminal_status_completed_maps_to_completed():
    assert (
        _terminal_status_for_event("UNKNOWN", "COMPLETED") == SignatureStatus.completed
    )


def test_terminal_rejected_maps_to_rejected():
    assert (
        _terminal_status_for_event("UNKNOWN", "DOCUMENT_PROCESS_REJECTED")
        == SignatureStatus.rejected
    )


def test_terminal_withdrawn_maps_to_withdrawn():
    assert (
        _terminal_status_for_event("UNKNOWN", "DOCUMENT_PROCESS_WITHDRAWN")
        == SignatureStatus.withdrawn
    )


def test_terminal_expired_maps_to_expired():
    assert (
        _terminal_status_for_event("UNKNOWN", "DOCUMENT_PROCESS_EXPIRED")
        == SignatureStatus.expired
    )


def test_terminal_returns_none_for_unrelated_event():
    assert _terminal_status_for_event("APPROVAL_PROCESS_CONSENTED", None) is None


# ── Intermediate status mapping ────────────────────────────────────────────


def test_intermediate_consent_maps_to_in_progress():
    assert (
        _intermediate_status_for_event("APPROVAL_PROCESS_CONSENTED")
        == SignatureStatus.in_progress
    )


def test_intermediate_review_completed_maps_to_in_progress():
    assert (
        _intermediate_status_for_event("REVIEW_PROCESS_COMPLETED")
        == SignatureStatus.in_progress
    )


def test_intermediate_handed_over_maps_to_in_progress():
    assert _intermediate_status_for_event("HANDED_OVER") == SignatureStatus.in_progress


def test_intermediate_returns_none_for_unrelated():
    assert _intermediate_status_for_event("UNKNOWN") is None
    assert _intermediate_status_for_event("SIGNING_PROCESS_COMPLETED") is None
