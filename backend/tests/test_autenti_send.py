"""Unit tests for the Autenti sender module — payload builder + validations.

Integration tests for the full ``POST /api/autenti/contracts/{id}/send``
flow live elsewhere (Phase 2 will add ``test_autenti_send_endpoint.py``).
This file covers pure-function logic without DB / FastAPI surface so the
unit suite stays fast.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.models.candidate import Candidate
from app.models.document_signature import SignatureStatus
from app.services.autenti.sender import (
    _build_create_payload,
    _signature_constraints,
    _validate_signer_fields,
)


def _make_candidate(
    *, name="Anna", lastname="Kowalska", email="anna@example.com", phone="+48123456789"
) -> Candidate:
    c = Candidate()
    c.name = name
    c.lastname = lastname
    c.email = email
    c.phone = phone
    return c


# ── _validate_signer_fields ────────────────────────────────────────────────


def test_validate_signer_fields_ses_returns_snapshot():
    c = _make_candidate()
    email, first, last, phone = _validate_signer_fields(c, "SES")
    assert email == "anna@example.com"
    assert first == "Anna"
    assert last == "Kowalska"
    assert phone == "+48123456789"


def test_validate_signer_fields_ses_phone_optional():
    c = _make_candidate(phone=None)
    _, _, _, phone = _validate_signer_fields(c, "SES")
    assert phone is None


def test_validate_signer_fields_ades_requires_phone():
    c = _make_candidate(phone="")
    with pytest.raises(HTTPException) as exc_info:
        _validate_signer_fields(c, "AdES")
    assert exc_info.value.status_code == 422
    assert "candidate.phone" in str(exc_info.value.detail)


def test_validate_signer_fields_qes_phone_optional():
    """QES uses profil zaufany / mObywatel — phone not required."""
    c = _make_candidate(phone=None)
    _, _, _, phone = _validate_signer_fields(c, "QES")
    assert phone is None


def test_validate_signer_fields_missing_email():
    c = _make_candidate(email="")
    with pytest.raises(HTTPException) as exc_info:
        _validate_signer_fields(c, "SES")
    assert exc_info.value.status_code == 422
    assert "candidate.email" in str(exc_info.value.detail)


def test_validate_signer_fields_missing_lastname():
    c = _make_candidate(lastname="")
    with pytest.raises(HTTPException) as exc_info:
        _validate_signer_fields(c, "SES")
    assert exc_info.value.status_code == 422


# ── _signature_constraints ─────────────────────────────────────────────────


def test_constraints_ses_uses_basic_autenti():
    c = _signature_constraints("SES")
    assert len(c) == 1
    classifiers = c[0]["attributes"]["requiredClassifiers"]
    assert any("BASIC_AUTENTI" in cls for cls in classifiers)


def test_constraints_ades_uses_advanced_autenti():
    c = _signature_constraints("AdES")
    classifiers = c[0]["attributes"]["requiredClassifiers"]
    assert any("ADVANCED_AUTENTI" in cls for cls in classifiers)


def test_constraints_qes_uses_qualified():
    c = _signature_constraints("QES")
    classifiers = c[0]["attributes"]["requiredClassifiers"]
    assert any("QUALIFIED" in cls for cls in classifiers)


def test_constraints_action_is_signature_application():
    """All three signature types constrain the SIGNATURE_APPLICATION action."""
    for sig_type in ("SES", "AdES", "QES"):
        c = _signature_constraints(sig_type)
        assert c[0]["constrainedActions"] == ["ACTION:SIGNATURE_APPLICATION"]


# ── _build_create_payload ──────────────────────────────────────────────────


def _make_signature(
    *,
    sig_type="SES",
    signer_phone=None,
    signer_email="anna@example.com",
    signer_first="Anna",
    signer_last="Kowalska",
):
    sig = Mock()
    sig.contract_id = 42
    sig.autenti_signature_type = sig_type
    sig.signer_email = signer_email
    sig.signer_first_name = signer_first
    sig.signer_last_name = signer_last
    sig.signer_phone = signer_phone
    sig.status = SignatureStatus.draft
    return sig


def test_build_payload_minimal_ses():
    sig = _make_signature()
    payload = _build_create_payload(signature=sig, message_pl=None, return_url=None)

    assert payload["title"].startswith("Umowa B2B")
    assert "Anna" in payload["title"]
    assert len(payload["parties"]) == 1
    party = payload["parties"][0]
    assert party["role"] == "SIGNER"
    assert party["ordering"] == 1
    assert party["person"]["email"] == "anna@example.com"
    # Phone absent when not provided.
    assert "phone" not in party["person"]
    # Message field absent when not provided.
    assert "message" not in payload


def test_build_payload_includes_phone_for_ades():
    sig = _make_signature(sig_type="AdES", signer_phone="+48555111222")
    payload = _build_create_payload(signature=sig, message_pl=None, return_url=None)
    assert payload["parties"][0]["person"]["phone"] == "+48555111222"


def test_build_payload_includes_message_when_provided():
    sig = _make_signature()
    payload = _build_create_payload(
        signature=sig,
        message_pl="Cześć Anna, oto umowa którą omawialiśmy.",
        return_url=None,
    )
    assert payload["message"]["language"] == "pl"
    assert "Cześć" in payload["message"]["body"]


def test_build_payload_includes_return_url():
    sig = _make_signature()
    payload = _build_create_payload(
        signature=sig,
        message_pl=None,
        return_url="https://nexus.dynaminds.pl/signatures/return",
    )
    assert (
        payload["parties"][0]["returnUrl"]
        == "https://nexus.dynaminds.pl/signatures/return"
    )


def test_build_payload_qes_constraints_applied():
    sig = _make_signature(sig_type="QES")
    payload = _build_create_payload(signature=sig, message_pl=None, return_url=None)
    constraints = payload["parties"][0]["constraints"]
    classifiers = constraints[0]["attributes"]["requiredClassifiers"]
    assert any("QUALIFIED" in cls for cls in classifiers)
