"""Every LLM call must be declared, and there must be exactly one gate.

Two things went wrong here and they reinforced each other:

* A route-level check could never have worked. Three of the five paths that
  reached Claude without charging a quota are not routes — a background sync
  loop, a `BackgroundTask`, and a CloudTalk webhook. Every *handler* looked
  correctly wrapped while those three spent money the master toggle could not
  stop and `ai_usage_log` never saw.
* There were two implementations of the gate with the OPPOSITE answer for a
  missing `ai_features` row (`ai_quota` blocked, `match_justification_service`
  allowed), so behaviour depended on which copy a request happened to reach.

DB-free except where marked.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.core.config import settings
from app.services import claude_client
from app.services.ai_quota import AIQuotaUngated, current_ai_call

BACKEND = pathlib.Path(__file__).resolve().parent.parent


# ── One gate, not two ────────────────────────────────────────────────────────


def test_the_parallel_quota_implementation_is_gone():
    """`_gate_and_count` duplicated `check_and_increment` and disagreed with it.

    Whether an unseeded feature worked depended on which of the two a request
    reached — the worst kind of bug, because both copies looked correct.
    """
    path = BACKEND / "app/services/match_justification_service.py"
    src = path.read_text()
    tree = ast.parse(src)
    defined = {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    # Definitions, not mentions: the comment explaining why it was removed is
    # the most useful line in that file and must not trip its own test.
    assert "_gate_and_count" not in defined
    assert "ai_feature(" in src, "the surviving gate must actually be used here"


def test_missing_feature_row_is_treated_as_enabled_without_a_ceiling():
    """Fail-open, matching `AIFeatureConfig.enabled`'s own default.

    Pinned because it is a deliberate trade, not an accident: an unseeded
    feature also has NO monthly limit, which is why `/api/health` reports the
    missing keys as a spend warning.
    """
    src = (BACKEND / "app/services/ai_quota.py").read_text()
    assert "if config is not None and not config.enabled:" in src, (
        "quota went back to fail-closed on a missing row — that contradicts "
        "the documented default and the health probe built around it"
    )


# ── Nothing reaches the provider undeclared ──────────────────────────────────


def test_no_declared_call_in_scope_by_default():
    assert current_ai_call() is None


def test_ungated_call_is_refused_under_strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "AI_QUOTA_STRICT", True)
    with pytest.raises(AIQuotaUngated):
        claude_client._assert_declared("claude-sonnet-5")


def test_ungated_call_is_only_logged_by_default(monkeypatch, caplog):
    """Ships permissive on purpose: enabling the gate and enforcing it in one
    deploy would 500 every path we happened to miss — and paths being missed is
    the entire reason this exists."""
    monkeypatch.setattr(settings, "AI_QUOTA_STRICT", False)
    with caplog.at_level("ERROR"):
        claude_client._assert_declared("claude-sonnet-5")
    assert any("UNGATED" in r.message for r in caplog.records)


def test_declared_call_passes_in_strict_mode(monkeypatch):
    from app.models.ai_feature import AIFeatureKey
    from app.services import ai_quota

    monkeypatch.setattr(settings, "AI_QUOTA_STRICT", True)
    token = ai_quota._AI_CALL_CONTEXT.set(
        ai_quota.AiCallContext(
            feature=AIFeatureKey.scoring,
            user_id=1,
            state=ai_quota.QuotaState(used=1, limit=0, period_start=None),
        )
    )
    try:
        claude_client._assert_declared("claude-sonnet-5")  # must not raise
    finally:
        ai_quota._AI_CALL_CONTEXT.reset(token)


# ── Raw provider clients ─────────────────────────────────────────────────────
#
# Constructing `anthropic.Anthropic(...)` directly bypasses FOUR things at once:
# the explicit timeout, the transient-retry backoff, the health telemetry and
# now the quota. One rule covers all four.
#
# The three entries below are pre-existing and each needs its own migration
# (the CV generator carries a bespoke retry loop and prompt caching), so they
# are frozen rather than pretended away. The list must only ever shrink.
_RAW_CLIENT_BASELINE = {
    "app/api/ai_writer.py",
    "app/services/cv_parser.py",
    "app/services/cv_generator_b2b/ai_client.py",
}


def _files_constructing_a_raw_client() -> set[str]:
    found: set[str] = set()
    for path in (BACKEND / "app").rglob("*.py"):
        rel = str(path.relative_to(BACKEND))
        if rel == "app/services/claude_client.py":
            continue  # the one legitimate place
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "Anthropic"
            ):
                found.add(rel)
    return found


def test_no_new_raw_provider_client_appears():
    new = _files_constructing_a_raw_client() - _RAW_CLIENT_BASELINE
    assert not new, (
        "These construct anthropic.Anthropic() directly, so they bypass the "
        "timeout, the retry backoff, the health window AND the quota:\n"
        + "\n".join(f"  {p}" for p in sorted(new))
        + "\n\nRoute the call through app/services/claude_client.call_claude."
    )


def test_raw_client_baseline_has_no_stale_entries():
    """Guard the guard: a stale entry hides a file that was already migrated,
    and makes the baseline look larger than the real debt."""
    stale = _RAW_CLIENT_BASELINE - _files_constructing_a_raw_client()
    assert not stale, (
        f"already migrated, remove from the baseline: {sorted(stale)}"
    )
