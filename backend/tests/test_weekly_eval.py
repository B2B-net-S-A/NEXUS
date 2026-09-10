"""Strażnik cotygodniowy — kontrakty harmonogramu i detekcji regresu."""

from datetime import datetime, timedelta, timezone

from app.tasks.weekly_eval import _is_due, detect_regression
from scripts.eval_frozen_set import (
    FROZEN_JOB_IDS_2026_08,
    FROZEN_JOB_IDS_2026_08_B,
    frozen_ids_csv,
    frozen_ids_csv_b,
)


def test_frozen_set_is_stable():
    assert len(FROZEN_JOB_IDS_2026_08) == 50
    assert len(set(FROZEN_JOB_IDS_2026_08)) == 50, "duplikaty psują porównywalność"
    csv = frozen_ids_csv()
    assert csv.count(",") == 49 and csv.split(",")[0] == "1394"


def test_holdout_b_is_stable_and_disjoint():
    """Holdout B potwierdza flipy — nie może dzielić ofert ze zbiorem A,
    na którym decyzje były strojone (runda 2, higiena pomiarowa)."""
    assert len(FROZEN_JOB_IDS_2026_08_B) == 50
    assert len(set(FROZEN_JOB_IDS_2026_08_B)) == 50
    assert set(FROZEN_JOB_IDS_2026_08_B).isdisjoint(FROZEN_JOB_IDS_2026_08)
    csv = frozen_ids_csv_b()
    assert csv.count(",") == 49 and csv.split(",")[0] == "3242"


def test_is_due_weekly_window(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "WEEKLY_EVAL_WEEKDAY", 6, raising=False)
    monkeypatch.setattr(settings, "WEEKLY_EVAL_HOUR_UTC", 5, raising=False)

    sunday_6am = datetime(2026, 8, 23, 6, 0, tzinfo=timezone.utc)  # niedziela
    assert sunday_6am.weekday() == 6
    assert _is_due(None, sunday_6am) is True, "pierwszy bieg od razu"
    week_ago = sunday_6am - timedelta(days=7)
    assert _is_due(week_ago, sunday_6am) is True

    # Bieg o 05:10 tydzień temu NIE przesuwa okna (>=6 dni, nie pełne 7).
    six_days_23h = sunday_6am - timedelta(days=6, hours=23)
    assert _is_due(six_days_23h, sunday_6am) is True

    saturday = datetime(2026, 8, 22, 6, 0, tzinfo=timezone.utc)
    assert _is_due(week_ago, saturday) is False, "zły dzień tygodnia"
    sunday_4am = datetime(2026, 8, 23, 4, 0, tzinfo=timezone.utc)
    assert _is_due(week_ago, sunday_4am) is False, "przed godziną okna"
    three_days = sunday_6am - timedelta(days=3)
    assert _is_due(three_days, sunday_6am) is False, "za świeży poprzedni bieg"


def test_regression_detection_thresholds():
    prev = {"p5": 0.240, "r20n": 0.189, "mrr": 0.442, "ndcg10": 0.160}

    # Spadek o 20% na P@5 → regres; R@20n stabilny.
    cur = {"p5": 0.190, "r20n": 0.188, "mrr": 0.442, "ndcg10": 0.160}
    assert detect_regression(cur, prev) == ["p5"]

    # Szum 3% → cisza.
    noisy = {"p5": 0.233, "r20n": 0.184, "mrr": 0.430, "ndcg10": 0.157}
    assert detect_regression(noisy, prev) == []

    # Oba w dół >15% → obie nazwy.
    bad = {"p5": 0.150, "r20n": 0.120, "mrr": 0.300, "ndcg10": 0.100}
    assert detect_regression(bad, prev) == ["p5", "r20n"]

    # Brak historii / zepsuta historia → brak alarmu (pierwszy pomiar).
    assert detect_regression(cur, None) == []
    assert detect_regression(cur, {"p5": "zepsute"}) == []
    assert detect_regression(cur, {"p5": 0}) == []


def test_regression_is_only_read_within_one_scorer():
    """Legacy and canonical are two different instruments. The first canonical
    run after the switch must not be compared with the last legacy one: the
    difference is the scale changing, not quality dropping."""
    legacy_prev = {"p5": 0.240, "r20n": 0.189}  # stored before the switch: no key
    canonical_drop = {"p5": 0.100, "r20n": 0.050, "scorer": "canonical"}
    assert detect_regression(canonical_drop, legacy_prev) == []
    assert detect_regression(canonical_drop, {**legacy_prev, "scorer": "legacy"}) == []

    canonical_prev = {"p5": 0.240, "r20n": 0.189, "scorer": "canonical"}
    assert detect_regression(canonical_drop, canonical_prev) == ["p5", "r20n"]


def test_baseline_status_says_why_there_was_no_comparison():
    from app.tasks.weekly_eval import _baseline_status

    current = {"p5": 0.2, "scorer": "canonical"}
    assert _baseline_status(current, None) == "none"
    assert _baseline_status(current, {"p5": 0.2}) == "scorer_changed"
    assert _baseline_status(current, {"p5": 0.2, "scorer": "canonical"}) == (
        "same_scorer"
    )


def test_metrics_carry_the_scorer_that_actually_produced_them():
    from app.tasks.weekly_eval import _extract_metrics

    profile = {
        "mean_precision_at_5": 0.25,
        "mean_recall_at_20_normalized": 0.2,
        "mean_mrr": 0.4,
        "mean_ndcg_at_10": 0.16,
        "per_job": [{}, {}],
    }
    canonical = _extract_metrics(
        {"manifest": {"scorer": "canonical"}, "profiles": [profile]}
    )
    assert canonical["scorer"] == "canonical" and canonical["jobs"] == 2
    # An artefact from before the switch has no key and was legacy by definition.
    assert _extract_metrics({"profiles": [profile]})["scorer"] == "legacy"


def test_weekly_guard_measures_the_scorer_users_see():
    """The command must select canonical AND be accepted by the harness parser
    — a flag the harness rejects would turn every Sunday into harness_failed."""
    from app.tasks.weekly_eval import WEEKLY_SCORER, _harness_command
    from scripts.eval_matching import _parse_args

    cmd = _harness_command()
    assert WEEKLY_SCORER == "canonical"
    assert cmd[cmd.index("--scorer") + 1] == "canonical"
    assert cmd[1:3] == ["-m", "scripts.eval_matching"]
    args = _parse_args(cmd[3:])
    assert args.scorer == "canonical" and args.json and args.pool == 1000


def test_failure_statuses_do_not_advance_watermark():
    from app.tasks.weekly_eval import _ADVANCING_STATUSES

    assert "ok" in _ADVANCING_STATUSES and "regression" in _ADVANCING_STATUSES
    for failure in ("timeout", "harness_failed", "parse_failed"):
        assert failure not in _ADVANCING_STATUSES, (
            "awaria nie może wyciszyć strażnika na tydzień"
        )
