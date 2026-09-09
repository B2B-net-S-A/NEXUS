"""CV-19: reject rules that can only silently fall back at generation time."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.api.client_cv_rules import ClientCvRulePayload
from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot, build_filename


@pytest.mark.parametrize(
    "pattern",
    [
        "B2B.NET_STANOWISKO_IMIE_NAZWISKO_DATA",
        "B2B_{STANOWISKO}_{DATA}",
        "B2B_{IMIE_NAZWISKO}_{DATA",
        "B2B_{{IMIE_NAZWISKO}}",
        "B2B_{IMIE_NAZWISKO}_{DATA2}",
        "B2B_{IMIE_NAZWISKO}_{STANOWISKA}",
    ],
)
def test_unusable_or_malformed_pattern_rejected_before_save(pattern):
    with pytest.raises(ValidationError):
        ClientCvRulePayload(filename_pattern=pattern)


@pytest.mark.parametrize("pattern", [None, "", "   "])
def test_default_filename_remains_an_explicit_option(pattern):
    assert ClientCvRulePayload(filename_pattern=pattern).filename_pattern is None


def test_validated_credit_agricole_shape_renders_candidate_identity():
    payload = ClientCvRulePayload(
        filename_pattern="B2B.NET_{STANOWISKO}_{IMIE_NAZWISKO}_{DATA}",
        spaces_to_underscores=True,
    )
    snapshot = CvRuleSnapshot(
        filename_pattern=payload.filename_pattern,
        spaces_to_underscores=True,
        cv_language="pl",
        requires_en_copy=False,
        requires_rodo_consent_block=False,
    )
    result = build_filename(
        snapshot,
        position="Python Developer",
        candidate_name="Jan Testowy",
        today=date(2026, 9, 9),
    )
    assert result is not None
    assert result.filename == "B2B.NET_Python_Developer_Jan_Testowy_2026-09-09.docx"
    assert result.warnings == ()


async def test_confirm_rejects_legacy_invalid_pattern_without_publishing(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    from app.api import client_cv_rules as api

    rule = SimpleNamespace(
        filename_pattern="B2B.NET_STANOWISKO_IMIE_NAZWISKO_DATA",
        confirmed_at=None,
        edit_revision=1,
        draft_payload={"filename_pattern": "B2B.NET_STANOWISKO_IMIE_NAZWISKO_DATA"},
    )
    db = AsyncMock()
    monkeypatch.setattr(
        api, "_client_or_404", AsyncMock(return_value=SimpleNamespace(id=26))
    )
    monkeypatch.setattr(api, "_require_client_rule_access", AsyncMock())
    monkeypatch.setattr(api, "_lock_rule_edit", AsyncMock(return_value=rule))
    with pytest.raises(HTTPException) as error:
        await api.confirm_client_cv_rule(
            26, SimpleNamespace(id=1), db, expected_revision=1
        )
    assert error.value.status_code == 422
    assert rule.confirmed_at is None
    db.commit.assert_not_awaited()
