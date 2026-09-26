"""``eval_ab_run --arms text|text-notes`` — A/B tekstu embeddingu (26.09.2026).

Ramiona różnią się WYŁĄCZNIE kolekcją wektorów kandydatów (i flagami schematu,
od których zależy sprawdzenie świeżości punktu). Scorer i pula muszą być te
same — metryk między scorerami nie porównujemy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import eval_ab_run

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/coolify-ops.yml"


def _runner(calls, *, manual_output=True):
    def runner(argv, env, log):
        calls.append((list(argv), dict(env)))
        if "--output" in argv:
            Path(argv[argv.index("--output") + 1]).write_text(
                "# Matching eval\n", encoding="utf-8"
            )
            log.write_text("ok\n", encoding="utf-8")
        elif manual_output:
            log.write_text(
                "start\nRekrutacje: 120, czas 300 s\n\n| kolejność | x |\n|---|---:|\n"
                "| najnowsi | 1 |\n",
                encoding="utf-8",
            )
        else:
            log.write_text("Traceback: boom\n", encoding="utf-8")
        return 0

    return runner


def _run(tmp_path, *, arms, harness="matching", jobs=50, runner=None):
    calls, lines = [], []
    rc = eval_ab_run.run(
        arms=arms,
        eval_set="A",
        jobs=jobs,
        pool=2000,
        lock=tmp_path / "nexus-eval-7",
        harness=harness,
        runner=runner or _runner(calls),
        out=lines.append,
    )
    return rc, calls, lines


def _scorer(argv):
    return argv[argv.index("--scorer") + 1]


def test_text_arms_differ_only_by_candidate_vectors(tmp_path):
    rc, calls, _ = _run(tmp_path, arms="text")

    assert rc == 0
    (off_argv, off_env), (on_argv, on_env) = calls
    assert _scorer(off_argv) == _scorer(on_argv) == "canonical"
    # Pula identyczna (bez hybrydy i rerankera) w obu ramionach.
    for env in (off_env, on_env):
        assert env["HYBRID_POOL_ENABLED"] == "false"
        assert env["RERANKER_ENABLED"] == "false"
    assert off_env["AI_TEXT_SCHEMA_V3"] == "false"
    # Ramię v1 zostaje na kolekcji, którą ma produkcja — bez naszego założenia.
    assert "QDRANT_COLLECTION" not in off_env
    assert on_env["AI_TEXT_SCHEMA_V3"] == "true"
    assert on_env["AI_TEXT_SCHEMA_V3_NOTES"] == "true"
    assert on_env["QDRANT_COLLECTION"] == eval_ab_run.SHADOW_V3
    # Poza przełącznikami tekstu argumenty ramion są identyczne.
    out = off_argv.index("--output")
    assert off_argv[:out] == on_argv[:out]


def test_text_notes_arms_isolate_the_notes_section(tmp_path):
    _, calls, _ = _run(tmp_path, arms="text-notes")

    (_off_argv, off_env), (_on_argv, on_env) = calls
    assert off_env["QDRANT_COLLECTION"] == eval_ab_run.SHADOW_V3
    assert off_env["AI_TEXT_SCHEMA_V3_NOTES"] == "true"
    assert on_env["QDRANT_COLLECTION"] == eval_ab_run.SHADOW_V3_NO_NOTES
    assert on_env["AI_TEXT_SCHEMA_V3_NOTES"] == "false"
    assert {
        k: v
        for k, v in off_env.items()
        if k not in {"QDRANT_COLLECTION", "AI_TEXT_SCHEMA_V3_NOTES"}
    } == {
        k: v
        for k, v in on_env.items()
        if k not in {"QDRANT_COLLECTION", "AI_TEXT_SCHEMA_V3_NOTES"}
    }


def test_shadow_names_match_the_runbook():
    runbook = (
        Path(__file__).resolve().parents[2] / "docs/embedding-v3-ab-runbook.md"
    ).read_text(encoding="utf-8")
    assert eval_ab_run.SHADOW_V3 in runbook
    assert eval_ab_run.SHADOW_V3_NO_NOTES in runbook


def test_manual_harness_runs_the_manual_order_eval_per_arm(tmp_path):
    rc, calls, lines = _run(tmp_path, arms="text", harness="manual", jobs=120)

    assert rc == 0
    for argv, _env in calls:
        assert argv[1:] == ["-m", "scripts.eval_manual_search_order", "--jobs", "120"]
    off = lines.index("===NEXUS-EVAL-OFF===")
    assert lines[off + 1] == "Rekrutacje: 120, czas 300 s"
    assert "| najnowsi | 1 |" in lines[off : lines.index("===NEXUS-EVAL-BM25-OFF===")]
    assert lines[-1] == eval_ab_run.SENTINEL


def test_manual_harness_crash_leaves_an_empty_section_and_the_tail(tmp_path):
    calls = []
    _, _, lines = _run(
        tmp_path,
        arms="text",
        harness="manual",
        runner=_runner(calls, manual_output=False),
    )
    off = lines.index("===NEXUS-EVAL-OFF===")
    assert lines[off + 1] == "===NEXUS-EVAL-BM25-OFF==="
    tail = lines.index("===NEXUS-EVAL-TAIL-OFF===")
    assert "Traceback: boom" in lines[tail + 1 : lines.index("===NEXUS-EVAL-ON===")]


def test_manual_harness_refuses_non_text_arms(tmp_path):
    with pytest.raises(ValueError):
        _run(tmp_path, arms="scorer", harness="manual")


@pytest.mark.parametrize(
    "argv",
    [
        # eval_matching trzyma limit 50 ofert (zamrożony zbiór).
        ["--arms", "text", "--jobs", "51"],
        ["--arms", "scorer", "--harness", "manual", "--jobs", "50"],
        ["--arms", "text", "--harness", "manual", "--jobs", "301"],
        ["--arms", "text", "--harness", "other", "--jobs", "50"],
    ],
)
def test_cli_rejects_text_arms_outside_the_contract(argv):
    base = ["--set", "A", "--pool", "2000", "--lock", "/tmp/nexus-eval-1"]
    with pytest.raises(SystemExit):
        eval_ab_run.main(argv + base)


def test_workflow_maps_the_text_actions_to_the_text_arms():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "eval-ab-text) ARMS=text;;" in text
    assert "eval-ab-text-notes) ARMS=text-notes;;" in text
    for action in ("eval-ab-text", "eval-ab-text-notes"):
        assert f"inputs.action == '{action}'" in text
