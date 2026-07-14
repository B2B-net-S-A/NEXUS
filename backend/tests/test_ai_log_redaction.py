"""Regression tests for PII-safe diagnostics in AI/CV paths."""

from __future__ import annotations

import json

from app.services.cv_generator_b2b.standalone_service import _json_error_context


def test_invalid_provider_json_context_contains_metadata_not_response() -> None:
    raw = '{"email":"anna.private@example.com","experience": invalid}'
    try:
        json.loads(raw)
    except json.JSONDecodeError as exc:
        context = _json_error_context(raw, exc)
    else:  # pragma: no cover - fixture must remain malformed
        raise AssertionError("test fixture unexpectedly became valid JSON")

    assert "anna.private@example.com" not in context
    assert "experience" not in context
    assert f"len={len(raw)}" in context
    assert "pos=" in context
    assert "sha256=" in context
