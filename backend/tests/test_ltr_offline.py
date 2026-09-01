"""Narzędzia offline rundy 2: cechy w simpleksie + trener GBDT.

Syntetyczny zrzut, deterministyczne asercje — te skrypty wydają NOMINACJE
pomiarowe, więc ich mechanika (ładowanie cech, CV po ofertach, uczenie progu)
musi być zamrożona testem, nie zaufaniem.
"""

from __future__ import annotations

import json

from scripts.ltr_train import evaluate_cv, train_gbdt
from scripts.weight_search import load_dump, metrics_for_weights, simplex_grid


def _write_dump(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _row(job_id, cid, gt, sem, feat):
    return {
        "job_id": job_id,
        "candidate_id": cid,
        "gt": gt,
        "total": 0.0,
        "layers": {
            "semantic": {"points": sem * 60.0, "max": 60.0},
            "skills": {"points": 0.0, "max": 10.0},
            "salary": {"points": 0.0, "max": 15.0},
            "location": {"points": 0.0, "max": 5.0},
            "availability": {"points": 0.0, "max": 0.0},
        },
        "features": {"title_match": feat},
    }


def test_load_dump_reads_features(tmp_path):
    p = tmp_path / "d.jsonl"
    _write_dump(p, [_row(1, 10, True, 0.5, 0.7)])
    jobs = load_dump(str(p), features=("title_match",))
    (cid, gt, fr) = jobs[1][0]
    assert (cid, gt) == (10, True)
    assert fr["title_match"] == 0.7
    # Starszy zrzut bez pola features → 0.0, nie wybuch.
    _write_dump(
        p, [{k: v for k, v in _row(1, 10, True, 0.5, 0.7).items() if k != "features"}]
    )
    jobs = load_dump(str(p), features=("title_match",))
    assert jobs[1][0][2]["title_match"] == 0.0


def test_simplex_grid_extra_dimension_sums_hold():
    vecs = list(simplex_grid(50, 100, extra=("title_match",)))
    assert all(sum(v.values()) == 100 for v in vecs)
    assert any(v["title_match"] > 0 for v in vecs)
    # 6 wymiarów, krok 50, suma 100 → C(2+5,5)=21 wektorów.
    assert len(vecs) == 21


def test_feature_weight_changes_ranking(tmp_path):
    """Cecha z sygnałem musi realnie wpływać na metryki, gdy dostaje wagę."""
    p = tmp_path / "d.jsonl"
    rows = []
    for job in (1, 2):
        # GT ma słabą semantykę, ale silny title_match; szum odwrotnie.
        rows.append(_row(job, 100 + job, True, 0.2, 1.0))
        for i in range(5):
            rows.append(_row(job, 10 * job + i, False, 0.8, 0.0))
    _write_dump(p, rows)
    jobs = load_dump(str(p), features=("title_match",))
    semantic_only = metrics_for_weights(
        jobs,
        {
            "semantic": 100.0,
            "skills": 0.0,
            "salary": 0.0,
            "location": 0.0,
            "availability": 0.0,
            "title_match": 0.0,
        },
    )
    with_feature = metrics_for_weights(
        jobs,
        {
            "semantic": 0.0,
            "skills": 0.0,
            "salary": 0.0,
            "location": 0.0,
            "availability": 0.0,
            "title_match": 100.0,
        },
    )
    assert semantic_only["mrr"] < with_feature["mrr"]
    assert with_feature["p5"] == 0.2  # 1 GT w top-5 z 5 pozycji


def test_gbdt_learns_threshold_and_beats_wrong_linear(tmp_path):
    """Deterministyczny próg: gt ⇔ semantic>0.5. GBDT ma go znaleźć w CV."""
    p = tmp_path / "d.jsonl"
    rows = []
    for job in range(1, 11):
        for i in range(12):
            sem = (i % 6) / 5.0  # 0, .2, .4, .6, .8, 1.0
            gt = sem > 0.5
            rows.append(_row(job, job * 100 + i, gt, sem, 0.0))
    _write_dump(p, rows)
    jobs = load_dump(str(p))

    metrics = evaluate_cv(
        jobs,
        ("semantic", "skills", "salary", "location", "availability"),
        folds=2,
        trees=20,
        depth=2,
        lr=0.3,
        min_leaf=5,
    )
    assert metrics["jobs"] == 10
    assert metrics["p5"] > 0.9, "próg semantic>0.5 jest wyuczalny stumpem"

    # Anty-model liniowy (waga tylko na availability=0) rankuje losowo/gorzej.
    anti = metrics_for_weights(
        jobs,
        {
            "semantic": 0.0,
            "skills": 0.0,
            "salary": 0.0,
            "location": 0.0,
            "availability": 100.0,
        },
    )
    assert metrics["p5"] > anti["p5"]


def test_gbdt_is_deterministic():
    xs = [[i / 10.0] for i in range(10)] * 5
    ys = ([0] * 5 + [1] * 5) * 5
    m1, b1 = train_gbdt(xs, ys, trees=5, depth=1, lr=0.1, min_leaf=2)
    m2, b2 = train_gbdt(xs, ys, trees=5, depth=1, lr=0.1, min_leaf=2)
    assert b1 == b2
    from scripts.ltr_train import predict

    for x in ([0.15], [0.75]):
        assert predict(m1, b1, x, lr=0.1) == predict(m2, b2, x, lr=0.1)
