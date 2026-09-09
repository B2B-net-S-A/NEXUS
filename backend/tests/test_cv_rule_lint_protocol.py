import json
from unittest.mock import Mock

import pytest

from app.services.cv_generator_b2b import rule_lint


def item(index=0, **changes):
    return (
        dict(index=index, verdict="ok", reason="Reguła prezentacji.", suggestion="")
        | changes
    )


@pytest.mark.parametrize(
    "items",
    [
        None,
        [],
        [item(), item()],
        [item(index=True)],
        [item(index="0")],
        [item(index=1)],
        [item(verdict="approved")],
        [item(reason="")],
        [item(reason="x" * 501)],
        [item(suggestion=12)],
        [item(extra="ignored")],
    ],
)
def test_bad_protocol_never_returns_ok(items):
    findings = rule_lint._coerce(items, ["Krótki opis."])
    assert len(findings) == 1
    assert findings[0].verdict == "unclear"


def test_duplicate_does_not_hide_conflicting_adds_facts_verdict():
    findings = rule_lint._coerce(
        [item(), item(verdict="adds_facts"), item(1)],
        ["Dopisz Kubernetes.", "Krótki opis."],
    )
    assert [finding.verdict for finding in findings] == ["unclear", "unclear"]


def test_complete_out_of_order_review_preserves_decisions():
    findings = rule_lint._coerce(
        [
            item(1),
            item(
                verdict="adds_facts",
                suggestion="Pokazuj wyłącznie potwierdzone narzędzia.",
            ),
        ],
        ["Dopisz Kubernetes.", "Krótki opis."],
    )
    assert [finding.verdict for finding in findings] == ["adds_facts", "ok"]
    assert findings[0].line == "Dopisz Kubernetes."


@pytest.mark.parametrize("wrapper", ["valid", "fence", "extra", "invalid"])
def test_provider_schema_and_strict_envelope(monkeypatch, wrapper):
    response = {"items": [item()]}
    if wrapper == "extra":
        response["ignored"] = True
    raw = json.dumps(response)
    if wrapper == "fence":
        raw = "```json\n" + raw + "\n```"
    if wrapper == "invalid":
        raw = "not json"
    provider = Mock(return_value=raw)
    monkeypatch.setattr(rule_lint, "analyze_with_ai", provider)
    findings = rule_lint.lint_instructions("Krótki opis.", request_id="synthetic-lint")
    assert (
        provider.call_args.kwargs["response_schema"] is rule_lint.LINT_RESPONSE_SCHEMA
    )
    assert findings[0].verdict == ("ok" if wrapper == "valid" else "unclear")
