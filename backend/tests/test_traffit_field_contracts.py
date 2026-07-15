"""Tenant metadata and candidate field adapter contract tests."""

from __future__ import annotations

from app.services.traffit.field_contracts import (
    candidate_to_traffit,
    normalize_metadata,
)


def test_metadata_maps_unknown_system_and_sid_fields_to_custom_storage() -> None:
    contracts = normalize_metadata(
        {
            "properties": {
                "owner": {"type": "object"},
                "_SID": {"type": "string"},
                "candidate_about": {"type": "textarea"},
            }
        },
        "patch",
    )

    by_name = {contract.remote_name: contract for contract in contracts}
    assert by_name["owner"].local_path == "custom_fields.owner"
    assert by_name["_SID"].local_path == "custom_fields._SID"
    assert by_name["candidate_about"].local_path == "profile_about"
    assert all(contract.capability == "patch" for contract in contracts)

    payload, quarantined = candidate_to_traffit(
        {
            "profile_about": "Backend engineer",
            "custom_fields": {
                "owner": {"id": 17, "name": "Recruiter"},
                "_SID": "platform",
            },
        },
        contracts,
    )
    assert payload == {
        "owner": 17,
        "_SID": "platform",
        "candidate_about": "Backend engineer",
    }
    assert quarantined == []


def test_sid_adapter_reads_migrated_legacy_traffit_key() -> None:
    contracts = normalize_metadata(
        [{"name": "_12345", "type": "string"}],
        "patch",
    )

    payload, quarantined = candidate_to_traffit(
        {"custom_fields": {"traffit_12345": "legacy value"}},
        contracts,
    )

    assert payload == {"_12345": "legacy value"}
    assert quarantined == []


def test_create_and_patch_contracts_form_separate_write_allow_lists() -> None:
    create_contracts = normalize_metadata(
        {
            "fields": [
                {"name": "name", "type": "string", "required": True},
                {"name": "source", "type": "choice"},
            ]
        },
        "create",
    )
    patch_contracts = normalize_metadata(
        {
            "data": [
                {"key": "email", "input_type": "email"},
                {"key": "owner", "input_type": "object"},
            ]
        },
        "patch",
    )
    snapshot = {
        "name": "Ada",
        "email": "ada@example.com",
        "source": {"id": 5, "name": "Referral"},
        "custom_fields": {"owner": {"id": 17}},
    }

    create_payload, create_quarantine = candidate_to_traffit(
        snapshot, create_contracts
    )
    patch_payload, patch_quarantine = candidate_to_traffit(snapshot, patch_contracts)

    assert create_payload == {"name": "Ada", "source": 5}
    assert patch_payload == {"email": "ada@example.com", "owner": 17}
    assert create_contracts[0].required is True
    assert {item.capability for item in create_contracts} == {"create"}
    assert {item.capability for item in patch_contracts} == {"patch"}
    assert create_quarantine == patch_quarantine == []


def test_unknown_adapter_quarantines_only_affected_field() -> None:
    contracts = normalize_metadata(
        {
            "metadata": [
                {"name": "mobile", "type": "phone"},
                {"name": "_vector", "type": "quantum-widget"},
            ]
        },
        "patch",
    )

    payload, quarantined = candidate_to_traffit(
        {
            "phone": "+48123123123",
            "custom_fields": {"_vector": "do-not-send"},
        },
        contracts,
    )

    assert payload == {"mobile": "+48123123123"}
    assert quarantined == ["_vector"]


def test_changed_fields_limits_patch_without_losing_custom_remote_name() -> None:
    contracts = normalize_metadata(
        [
            {"name": "email", "type": "email"},
            {"name": "owner", "type": "object"},
            {"name": "candidate_about", "type": "text"},
        ],
        "patch",
    )

    payload, quarantined = candidate_to_traffit(
        {
            "email": "ada@example.com",
            "profile_about": "Local copy",
            "custom_fields": {"owner": {"id": 17}},
        },
        contracts,
        changed_fields={"owner"},
    )

    assert payload == {"owner": 17}
    assert quarantined == []
