"""``scripts.eval_ab_run`` — A/B matchingu jedną krótką komendą Coolify.

Coolify trzyma komendę zadania w ``VARCHAR(255)``; stara komenda A/B z
``coolify-ops.yml`` (dwie listy 50 ofert + potok) miała ~1,6 tys. znaków i każde
założenie zadania kończyło się HTTP 500 (11.09.2026). Testy pilnują obu stron:
ramion liczonych w skrypcie i długości komendy wysyłanej przez workflow.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import eval_ab_run
from scripts.eval_frozen_set import frozen_ids_csv, frozen_ids_csv_b

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/coolify-ops.yml"
POOL_OFF = {"HYBRID_POOL_ENABLED": "false", "RERANKER_ENABLED": "false"}


def _fake_runner(calls, *, write_report=True):
    def runner(argv, env, log):
        calls.append((list(argv), dict(env)))
        if write_report:
            output = Path(argv[argv.index("--output") + 1])
            output.write_text("# Matching eval\nScorer: x\n", encoding="utf-8")
        log.write_text(
            "start\n[retrieval-pool] hybryda: bm25=7/50\nTraceback: boom\n",
            encoding="utf-8",
        )
        return 0 if write_report else 1

    return runner


def _run(tmp_path, *, arms="scorer", eval_set="A", runner=None):
    calls, lines = [], []
    rc = eval_ab_run.run(
        arms=arms,
        eval_set=eval_set,
        jobs=50,
        pool=2000,
        lock=tmp_path / "nexus-eval-1",
        runner=runner or _fake_runner(calls),
        out=lines.append,
    )
    return rc, calls, lines


def _arg(argv, flag):
    return argv[argv.index(flag) + 1]


def test_scorer_arms_share_the_vector_pool_and_differ_only_by_scorer(tmp_path):
    rc, calls, _ = _run(tmp_path)

    assert rc == 0
    (off_argv, off_env), (on_argv, on_env) = calls
    assert off_env == on_env == POOL_OFF
    assert (_arg(off_argv, "--scorer"), _arg(on_argv, "--scorer")) == (
        "legacy",
        "canonical",
    )
    assert _arg(off_argv, "--job-ids") == _arg(on_argv, "--job-ids") == frozen_ids_csv()
    assert _arg(off_argv, "--pool") == "2000" and _arg(off_argv, "--min-gt") == "3"


def test_hybrid_arms_flip_only_the_pool_flag(tmp_path):
    rc, calls, _ = _run(tmp_path, arms="hybrid")

    assert rc == 0
    (off_argv, off_env), (on_argv, on_env) = calls
    assert off_env == POOL_OFF
    assert on_env == {"HYBRID_POOL_ENABLED": "true", "RERANKER_ENABLED": "false"}
    assert "--scorer" not in off_argv and "--scorer" not in on_argv


def test_holdout_set_b_reads_its_own_frozen_list(tmp_path):
    _, calls, _ = _run(tmp_path, eval_set="B")

    assert _arg(calls[0][0], "--job-ids") == frozen_ids_csv_b() != frozen_ids_csv()


def test_sections_come_in_the_order_the_workflow_reads_them(tmp_path):
    _, _, lines = _run(tmp_path)

    assert [line for line in lines if line.startswith("===NEXUS-EVAL")] == [
        "===NEXUS-EVAL-OFF===",
        "===NEXUS-EVAL-BM25-OFF===",
        "===NEXUS-EVAL-TAIL-OFF===",
        "===NEXUS-EVAL-ON===",
        "===NEXUS-EVAL-BM25-ON===",
        "===NEXUS-EVAL-TAIL-ON===",
        eval_ab_run.SENTINEL,
    ]
    assert lines[-1] == eval_ab_run.SENTINEL
    assert lines[lines.index("===NEXUS-EVAL-OFF===") + 1] == "# Matching eval"
    bm25 = lines.index("===NEXUS-EVAL-BM25-OFF===")
    assert lines[bm25 + 1 : bm25 + 3] == ["1", "[retrieval-pool] hybryda: bm25=7/50"]


def test_a_crashed_arm_still_prints_its_log_tail(tmp_path):
    """Awaria harnessu ma wyglądać jak awaria, nie jak „zero wyników"."""
    calls = []
    _, _, lines = _run(tmp_path, runner=_fake_runner(calls, write_report=False))

    tail = lines.index("===NEXUS-EVAL-TAIL-OFF===")
    assert "Traceback: boom" in lines[tail + 1 : lines.index("===NEXUS-EVAL-ON===")]
    assert lines[-1] == eval_ab_run.SENTINEL


def test_the_next_cron_firing_does_not_rerun_the_eval(tmp_path):
    (tmp_path / "nexus-eval-1").mkdir()

    rc, calls, lines = _run(tmp_path)

    assert (rc, calls, lines) == (3, [], [])


@pytest.mark.parametrize(
    "overrides",
    [
        {"--jobs": "0"},
        {"--jobs": "51"},
        {"--pool": "99"},
        {"--pool": "5001"},
        {"--set": "C"},
        {"--arms": "rerank"},
        {"--lock": "/tmp/nexus-eval-1; rm -rf /"},
        {"--lock": "/app"},
    ],
)
def test_cli_rejects_anything_outside_the_contract(overrides):
    args = {
        "--arms": "scorer",
        "--set": "A",
        "--jobs": "50",
        "--pool": "2000",
        "--lock": "/tmp/nexus-eval-1",
        **overrides,
    }
    with pytest.raises(SystemExit):
        eval_ab_run.main([part for pair in args.items() for part in pair])


def test_workflow_command_fits_coolifys_varchar_255():
    text = WORKFLOW.read_text(encoding="utf-8")
    cmd_lines = [
        line.strip()
        for line in text.splitlines()
        if "CMD=" in line and "scripts.eval_ab_run" in line
    ]
    assert len(cmd_lines) == 1, cmd_lines
    template = cmd_lines[0].split('CMD="', 1)[1].rsplit('"', 1)[0]
    worst = (
        template.replace("${ARMS}", "scorer")
        .replace("${EVAL_SET}", "A")
        .replace("${EVAL_JOBS}", "50")
        .replace("${EVAL_POOL}", "5000")
        .replace("${LOCK}", "/tmp/nexus-eval-" + "9" * 20)
    )
    assert "${" not in worst, worst
    assert len(worst) <= 255, len(worst)
    # Stara, długa komenda z listą ofert w YAML-u nie może wrócić.
    assert "python -m scripts.eval_matching ${OFF_ARGS}" not in text
