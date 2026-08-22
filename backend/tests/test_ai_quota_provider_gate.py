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


def _files_defining_a_parallel_gate() -> set[str]:
    """Any file under app/ that reimplements the quota gate.

    Two shapes count: a function literally named `_gate_and_count`, and an
    `AIUsageLog` upsert outside `ai_quota` (the increment half of the gate).
    """
    found: set[str] = set()
    for path in (BACKEND / "app").rglob("*.py"):
        rel = str(path.relative_to(BACKEND))
        if rel == "app/services/ai_quota.py":
            continue  # the one legitimate implementation
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "_gate_and_count"
            ):
                found.add(rel)
            # `pg_insert(AIUsageLog)` — the counter upsert, wherever it is spelled.
            if (
                isinstance(node, ast.Call)
                and any(
                    isinstance(a, ast.Name) and a.id == "AIUsageLog" for a in node.args
                )
                and isinstance(node.func, ast.Name)
                and "insert" in node.func.id.lower()
            ):
                found.add(rel)
    return found


def test_the_parallel_quota_implementation_is_gone():
    """`_gate_and_count` duplicated `check_and_increment` and disagreed with it.

    Whether an unseeded feature worked depended on which of the two a request
    reached — the worst kind of bug, because both copies looked correct.

    Walks every file under app/, not one hard-coded path. The single-path
    version passed while asserting a global property it had verified in exactly
    one file — a second copy survived in `candidate_activity_summary_service`
    for the whole time this test was green.
    """
    assert not _files_defining_a_parallel_gate(), (
        "these reimplement the quota gate instead of using "
        "`async with ai_feature(...)`:\n"
        + "\n".join(f"  {p}" for p in sorted(_files_defining_a_parallel_gate()))
    )

    src = (BACKEND / "app/services/match_justification_service.py").read_text()
    assert "ai_feature(" in src, "the surviving gate must actually be used here"


# ── Charging without declaring ───────────────────────────────────────────────
#
# `check_and_increment` charges the quota but does NOT set the AI-call context,
# so a caller that uses it directly is charged correctly and still reaches
# `claude_client._assert_declared` undeclared: it logs as "UNGATED" (poisoning
# the detector that `AI_QUOTA_STRICT` is built on) and, under STRICT, raises on
# a path that actually paid. `async with ai_feature(...)` does both in one step.
#
# The entries below are pre-existing and each needs its own migration. The list
# must only ever shrink — z JEDNYM wyjątkiem opisanym niżej.
_BARE_CHARGE_BASELINE = {
    "app/api/jobs.py",
    "app/api/client_orders.py",
    "app/services/cv_generator_b2b/requirement_map.py",
    "app/services/cv_generator_b2b/interactive_chat.py",
    # Dopisane świadomie, nie żeby uciszyć strażnika: ta ścieżka jest INNEGO
    # RODZAJU niż cztery powyższe i nie da się jej zmigrować do `ai_feature()`.
    #
    # Dwa powody, oba sprawdzone w kodzie:
    #
    # 1. Deklaracja by nie dożyła do wydatku. `ai_feature` ustawia contextvar
    #    i KASUJE go w `finally` przy wyjściu z bloku, a Claude jest tu wołany
    #    z `BackgroundTasks`, czyli PO odesłaniu 202 i zamknięciu handlera.
    #    Bramka musi zostać w handlerze — odmowa w tle zostawiłaby wiersz
    #    „failed" zamiast czytelnego 503 (patrz `_charge_cv_generation_quota`).
    # 2. Szkoda opisana w nagłówku tej sekcji tu NIE ZACHODZI. `requirement_map`
    #    i `interactive_chat` wołają `claude_client.call_claude`, więc realnie
    #    trafiają w `_assert_declared` i logują się jako UNGATED. Generacja CV
    #    idzie `standalone_service` → `ai_client.analyze_with_ai`, które buduje
    #    `anthropic.Anthropic(...)` wprost (stąd wpis w `_RAW_CLIENT_BASELINE`)
    #    — bramka na granicy dostawcy nigdy jej nie ogląda. Deklaracja byłaby
    #    obietnicą pokrycia, którego nie ma.
    #
    # Migracja tego wpisu ma sens dopiero PO zdjęciu `ai_client.py` z
    # `_RAW_CLIENT_BASELINE` — wtedy jednym ruchem wraca i deklaracja, i sens.
    "app/api/cv_generator_b2b.py",
}


def _files_charging_without_declaring() -> set[str]:
    found: set[str] = set()
    for path in (BACKEND / "app").rglob("*.py"):
        rel = str(path.relative_to(BACKEND))
        if rel == "app/services/ai_quota.py":
            continue  # defines it
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            # Calls, not imports or mentions in comments/docstrings.
            if isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name) and node.func.id == "check_and_increment")
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "check_and_increment"
                )
            ):
                found.add(rel)
    return found


def test_no_new_bare_quota_charge_appears():
    new = _files_charging_without_declaring() - _BARE_CHARGE_BASELINE
    assert not new, (
        "These charge the quota with `check_and_increment` but never declare "
        "the call, so the provider-boundary gate still logs them as UNGATED "
        "and `AI_QUOTA_STRICT` would refuse them:\n"
        + "\n".join(f"  {p}" for p in sorted(new))
        + "\n\nUse `async with ai_feature(...)` — it charges and declares."
    )


def test_bare_charge_baseline_has_no_stale_entries():
    """Guard the guard: a stale entry makes the debt look bigger than it is."""
    stale = _BARE_CHARGE_BASELINE - _files_charging_without_declaring()
    assert not stale, f"already migrated, remove from the baseline: {sorted(stale)}"


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
    with caplog.at_level("WARNING"):
        claude_client._assert_declared("claude-sonnet-5")
    ungated = [r for r in caplog.records if "UNGATED" in r.message]
    assert ungated, "an undeclared call must still leave a trace"
    # WARNING, not ERROR, and that is load-bearing: `LoggingIntegration` turns
    # every `error` into a Sentry event, so one forgotten call site would emit
    # one per invocation and bury real errors for the whole observation window
    # — the window whose entire purpose is spotting forgotten call sites.
    # Promoting this back to `error` should fail here and be argued for.
    assert all(r.levelname == "WARNING" for r in ungated), (
        "UNGATED notice raised above WARNING — floods Sentry during the "
        "deliberate log-only cycle (AI_QUOTA_STRICT=false)"
    )


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
    # `ai_writer` migrated to `call_claude`; the CV generator keeps its own
    # client because it carries a bespoke retry loop, prompt caching and a
    # model fallback chain the shared helper does not have — it now at least
    # feeds `record_provider_call` and shares the retry predicate.
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
