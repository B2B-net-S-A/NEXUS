"""`current_version_trace` musi widzieć schemat tekstu v3 (26.09.2026).

Do tej daty ślad znał tylko v1/v2, więc po przełączeniu `AI_TEXT_SCHEMA_V3`
telemetria i odciski requestów (`request_matching_context`) nosiłyby stempel
v1 przy wektorach z zupełnie innej przestrzeni.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import canonical_text as ct
from app.services.matching_contracts import current_version_trace


@pytest.mark.parametrize(
    "v2,v3,notes,expected",
    [
        (False, False, True, ct.TEXT_SCHEMA_V1),
        (True, False, True, ct.TEXT_SCHEMA_V2),
        (False, True, True, ct.TEXT_SCHEMA_V3),
        # v3 wygrywa z v2 — jak w dyspozytorze tekstu kandydata.
        (True, True, True, ct.TEXT_SCHEMA_V3),
        (False, True, False, ct.TEXT_SCHEMA_V3_NO_NOTES),
        # Flaga notatek bez v3 nic nie zmienia.
        (False, False, False, ct.TEXT_SCHEMA_V1),
    ],
)
def test_version_trace_reports_the_active_text_schema(
    monkeypatch, v2, v3, notes, expected
):
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V2", v2)
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3", v3)
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3_NOTES", notes)

    assert current_version_trace().text_schema_version == expected


def test_switching_to_v3_changes_the_request_fingerprint_inputs(monkeypatch):
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V2", False)
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3", False)
    before = current_version_trace().as_dict()
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3", True)
    after = current_version_trace().as_dict()

    assert before["text_schema_version"] != after["text_schema_version"]
