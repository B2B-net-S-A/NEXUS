"""Unit testy dla pure-function mappers Traffit→Nexus.

Fixtures: backend/tests/fixtures/traffit/ (anonymized w Faza 0).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.traffit.mappers import (
    normalize_client_status,
    traffit_client_to_nexus,
    traffit_crm_person_to_nexus,
)

FIXTURES = Path(__file__).parent / "fixtures" / "traffit"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


class TestNormalizeClientStatus:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Aktywny", "active"),
            ("aktywny", "active"),
            ("active", "active"),
            ("Active", "active"),
            ("Nieaktywny", "inactive"),
            ("inactive", "inactive"),
            ("Prospekt", "prospect"),
            ("Lead", "prospect"),
            ("nieznany_status", "active"),  # fallback
            ("", "active"),
            (None, "active"),
        ],
    )
    def test_known_and_unknown(self, raw, expected):
        assert normalize_client_status(raw) == expected


class TestTraffitClientToNexus:
    def test_minimal_fixture(self):
        # clients_detail.json: id=26, name="Sample", status="Aktywny"
        payload = _load("clients_detail.json")
        result = traffit_client_to_nexus(payload)
        assert result["external_id"] == "26"
        assert result["external_source"] == "traffit"
        assert result["name"] == "Sample"
        assert result["status"] == "active"
        assert result["notes"] is None  # "Aktywny" maps cleanly, no audit hint

    def test_unknown_status_lands_in_notes(self):
        payload = {"id": 99, "name": "ACME", "status": "OnHold"}
        result = traffit_client_to_nexus(payload)
        assert result["status"] == "active"
        assert result["notes"] == "[traffit] status: OnHold"

    def test_missing_id_raises(self):
        with pytest.raises(ValueError, match="missing 'id'"):
            traffit_client_to_nexus({"name": "ACME"})

    def test_empty_name_falls_back(self):
        payload = {"id": 7, "name": "", "status": "active"}
        result = traffit_client_to_nexus(payload)
        assert result["name"] == "Klient bez nazwy #7"

    def test_long_name_truncated(self):
        payload = {"id": 1, "name": "x" * 500, "status": "active"}
        result = traffit_client_to_nexus(payload)
        assert len(result["name"]) == 255


class TestTraffitCrmPersonToNexus:
    def test_full_fixture(self):
        # crm_persons_detail.json: id=24, name=Sample, lastname=User, email=user@example.com,
        # client.id=8, status=active
        payload = _load("crm_persons_detail.json")
        client_map = {"8": 100}  # Traffit client_id=8 → Nexus client.id=100
        orphan_id = 999

        result = traffit_crm_person_to_nexus(payload, client_map, orphan_id)
        assert result["external_id"] == "24"
        assert result["external_source"] == "traffit"
        assert result["client_id"] == 100  # mapped from client_map
        assert result["name"] == "Sample User"  # name + lastname concat
        assert result["email"] == "user@example.com"

    def test_orphan_when_no_client(self):
        payload = {
            "id": 50,
            "name": "John",
            "lastname": "Doe",
            "email": "john@example.com",
            "client": None,  # explicit no client
        }
        result = traffit_crm_person_to_nexus(payload, {}, orphan_client_nexus_id=999)
        assert result["client_id"] == 999

    def test_orphan_when_unknown_client(self):
        payload = {
            "id": 50,
            "name": "John",
            "lastname": "Doe",
            "client": {"id": 9999},  # not in client_map
        }
        result = traffit_crm_person_to_nexus(
            payload, {"1": 10}, orphan_client_nexus_id=999
        )
        assert result["client_id"] == 999

    def test_name_fallback_to_email_localpart(self):
        payload = {
            "id": 50,
            "name": "",
            "lastname": "",
            "email": "alice@example.com",
            "client": {"id": 1},
        }
        result = traffit_crm_person_to_nexus(payload, {"1": 10}, 999)
        assert result["name"] == "alice"

    def test_name_fallback_to_question_mark(self):
        payload = {
            "id": 50,
            "name": "",
            "lastname": "",
            "email": "",
            "client": {"id": 1},
        }
        result = traffit_crm_person_to_nexus(payload, {"1": 10}, 999)
        assert result["name"] == "?"

    def test_phone_picks_first_nonempty_from_phone_or_mobile(self):
        # phone empty, mobile has value
        payload = {
            "id": 1,
            "name": "X",
            "lastname": "Y",
            "phone": "",
            "mobile": "+48123",
            "client": {"id": 1},
        }
        result = traffit_crm_person_to_nexus(payload, {"1": 10}, 999)
        assert result["phone"] == "+48123"

    def test_missing_id_raises(self):
        with pytest.raises(ValueError, match="missing 'id'"):
            traffit_crm_person_to_nexus({"name": "X"}, {}, 999)
