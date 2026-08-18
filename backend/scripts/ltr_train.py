"""Offline'owy test LTR właściwego: czy nieliniowość bije liniowe wagi?

Runda 2, punkt 5. Liniowy simpleks (`weight_search`) znalazł optimum w klasie
kombinacji liniowych frakcji warstw — regresja logistyczna na tych samych
cechach dałaby TEN SAM ranking (sigmoida jest monotoniczna), więc jedyny
potencjalny zysk siedzi w NIELINIOWOŚCI (progi, interakcje). Ten skrypt
odpowiada na to pytanie tanio i uczciwie:

- model: gradient boosting (drzewa głębokości 2, histogramy 32 koszyki,
  logloss) — czysty stdlib, deterministyczny (fold po job_id % k, zero
  losowości), bieg na zrzucie 19 MB w pojedyncze minuty;
- walidacja: k-fold PO OFERTACH (para z oferty testowej nigdy nie uczy
  modelu, który ją rankuje);
- porównanie: te same metryki rankingowe (P@5, R@20n, MRR) co harness,
  liczone na foldach testowych dla modelu ORAZ dla liniowego baseline'u
  z wag podanych w --baseline.

Kontrakt werdyktu jest ten sam co przy simpleksie: ten skrypt NOMINUJE
(offline, na przybliżonych frakcjach); zysk musiałby się jeszcze potwierdzić
prawdziwym biegiem, a wdrożenie modelu w serwingu to osobna decyzja
inżynierska. Brak zysku offline = NO-GO bez dalszych kosztów.

Użycie:
    python -m scripts.ltr_train --dump /tmp/layers.jsonl
    python -m scripts.ltr_train --dump /tmp/layers.jsonl \
        --with-feature title_match --trees 80 --baseline 60,10,15,5,0
"""

from __future__ import annotations

import argparse
import math
import sys

from scripts.weight_search import LAYERS, load_dump, metrics_for_weights

_N_BINS = 32


def _to_matrix(jobs: dict, names: tuple[str, ...]):
    """-> (rows, X, y, job_of_row) w porządku deterministycznym."""
    xs: list[list[float]] = []
    ys: list[int] = []
    job_of: list[int] = []
    cids: list[int] = []
    for job_id in sorted(jobs):
        for cid, gt, fr in jobs[job_id]:
            xs.append([float(fr.get(n, 0.0)) for n in names])
            ys.append(1 if gt else 0)
            job_of.append(job_id)
            cids.append(cid)
    return xs, ys, job_of, cids


def _bin_edges(xs: list[list[float]], dim: int) -> list[float]:
    vals = sorted(x[dim] for x in xs)
    if not vals:
        return []
    edges = []
    for b in range(1, _N_BINS):
        q = vals[min(len(vals) - 1, (b * len(vals)) // _N_BINS)]
        if not edges or q > edges[-1]:
            edges.append(q)
    return edges


def _digitize(v: float, edges: list[float]) -> int:
    lo, hi = 0, len(edges)
    while lo < hi:
        mid = (lo + hi) // 2
        if v <= edges[mid]:
            hi = mid
        else:
            lo = mid + 1
    return lo


class _Node:
    __slots__ = ("feature", "threshold_bin", "left", "right", "value")

    def __init__(self):
        self.feature = -1
        self.threshold_bin = -1
        self.left: _Node | None = None
        self.right: _Node | None = None
        self.value = 0.0


def _best_split(idx, binned, grad, hess, n_features, min_leaf):
    """Największy zysk logloss (formuła XGBoost, lambda=1)."""
    g_tot = sum(grad[i] for i in idx)
    h_tot = sum(hess[i] for i in idx)
    best = (0.0, -1, -1)  # gain, feature, bin
    parent = (g_tot * g_tot) / (h_tot + 1.0)
    for f in range(n_features):
        g_bins = [0.0] * _N_BINS
        h_bins = [0.0] * _N_BINS
        c_bins = [0] * _N_BINS
        for i in idx:
            b = binned[i][f]
            g_bins[b] += grad[i]
            h_bins[b] += hess[i]
            c_bins[b] += 1
        g_left = h_left = 0.0
        c_left = 0
        for b in range(_N_BINS - 1):
            g_left += g_bins[b]
            h_left += h_bins[b]
            c_left += c_bins[b]
            c_right = len(idx) - c_left
            if c_left < min_leaf or c_right < min_leaf:
                continue
            g_right = g_tot - g_left
            h_right = h_tot - h_left
            gain = (
                (g_left * g_left) / (h_left + 1.0)
                + (g_right * g_right) / (h_right + 1.0)
                - parent
            )
            if gain > best[0]:
                best = (gain, f, b)
    return best


def _build_tree(idx, binned, grad, hess, n_features, depth, min_leaf) -> _Node:
    node = _Node()
    g = sum(grad[i] for i in idx)
    h = sum(hess[i] for i in idx)
    node.value = -g / (h + 1.0)
    if depth == 0 or len(idx) < 2 * min_leaf:
        return node
    gain, f, b = _best_split(idx, binned, grad, hess, n_features, min_leaf)
    if f < 0 or gain <= 1e-9:
        return node
    node.feature, node.threshold_bin = f, b
    left_idx = [i for i in idx if binned[i][f] <= b]
    right_idx = [i for i in idx if binned[i][f] > b]
    node.left = _build_tree(
        left_idx, binned, grad, hess, n_features, depth - 1, min_leaf
    )
    node.right = _build_tree(
        right_idx, binned, grad, hess, n_features, depth - 1, min_leaf
    )
    return node


def _predict_tree(node: _Node, row_bins) -> float:
    while node.feature >= 0:
        node = node.left if row_bins[node.feature] <= node.threshold_bin else node.right
    return node.value


def train_gbdt(
    xs, ys, *, trees: int, depth: int, lr: float, min_leaf: int
) -> tuple[list, list[list[float]]]:
    """-> (lista drzew, krawędzie koszyków per cecha)."""
    n = len(xs)
    n_features = len(xs[0]) if xs else 0
    edges = [_bin_edges(xs, f) for f in range(n_features)]
    binned = [tuple(_digitize(x[f], edges[f]) for f in range(n_features)) for x in xs]
    base = math.log(max(sum(ys), 1) / max(n - sum(ys), 1))
    scores = [base] * n
    model: list[_Node] = []
    all_idx = list(range(n))
    for _ in range(trees):
        grad = [0.0] * n
        hess = [0.0] * n
        for i in range(n):
            p = 1.0 / (1.0 + math.exp(-scores[i]))
            grad[i] = p - ys[i]
            hess[i] = p * (1.0 - p)
        tree = _build_tree(all_idx, binned, grad, hess, n_features, depth, min_leaf)
        model.append(tree)
        for i in range(n):
            scores[i] += lr * _predict_tree(tree, binned[i])
    return (model, edges), base


def predict(model_pack, base: float, x: list[float], *, lr: float) -> float:
    model, edges = model_pack
    row_bins = tuple(_digitize(x[f], edges[f]) for f in range(len(x)))
    s = base
    for tree in model:
        s += lr * _predict_tree(tree, row_bins)
    return s


def _rank_metrics(rows: list[tuple[int, bool, float]]) -> tuple[float, float, float]:
    """rows: (candidate_id, gt, score) jednej oferty -> (p5, r20n, mrr)."""
    gt_ids = {cid for cid, gt, _ in rows if gt}
    if not gt_ids:
        return 0.0, 0.0, 0.0
    ranked = [
        cid for _s, cid in sorted(((s, cid) for cid, _g, s in rows), reverse=True)
    ]
    p5 = sum(1 for c in ranked[:5] if c in gt_ids) / 5.0
    ceiling = min(1.0, 20.0 / len(gt_ids))
    r20 = sum(1 for c in ranked[:20] if c in gt_ids) / len(gt_ids)
    r20n = (r20 / ceiling) if ceiling else 0.0
    mrr = 0.0
    for rank, cid in enumerate(ranked, start=1):
        if cid in gt_ids:
            mrr = 1.0 / rank
            break
    return p5, r20n, mrr


def evaluate_cv(
    jobs: dict,
    names: tuple[str, ...],
    *,
    folds: int,
    trees: int,
    depth: int,
    lr: float,
    min_leaf: int,
) -> dict[str, float]:
    """K-fold po ofertach; zwraca średnie metryki modelu na foldach testowych."""
    p5s: list[float] = []
    r20ns: list[float] = []
    mrrs: list[float] = []
    job_ids = sorted(jobs)
    for fold in range(folds):
        test_jobs = {j for j in job_ids if j % folds == fold}
        train = {j: jobs[j] for j in job_ids if j not in test_jobs}
        test = {j: jobs[j] for j in test_jobs}
        if not train or not test:
            continue
        xs, ys, _job_of, _cids = _to_matrix(train, names)
        if not xs or len(set(ys)) < 2:
            continue
        model_pack, base = train_gbdt(
            xs, ys, trees=trees, depth=depth, lr=lr, min_leaf=min_leaf
        )
        for _job_id, rows in test.items():
            scored = [
                (
                    cid,
                    gt,
                    predict(
                        model_pack,
                        base,
                        [float(fr.get(n, 0.0)) for n in names],
                        lr=lr,
                    ),
                )
                for cid, gt, fr in rows
            ]
            if not any(gt for _c, gt, _s in scored):
                continue
            p5, r20n, mrr = _rank_metrics(scored)
            p5s.append(p5)
            r20ns.append(r20n)
            mrrs.append(mrr)
    n = len(p5s)
    if n == 0:
        return {"p5": 0.0, "r20n": 0.0, "mrr": 0.0, "jobs": 0}
    return {
        "p5": round(sum(p5s) / n, 4),
        "r20n": round(sum(r20ns) / n, 4),
        "mrr": round(sum(mrrs) / n, 4),
        "jobs": n,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", required=True, help="JSONL z --dump-layers")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--trees", type=int, default=60)
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--lr", type=float, default=0.1)
    parser.add_argument("--min-leaf", type=int, default=50)
    parser.add_argument(
        "--with-feature",
        action="append",
        default=[],
        metavar="NAME",
        help="Cecha z pola 'features' zrzutu jako dodatkowe wejście modelu.",
    )
    parser.add_argument(
        "--baseline",
        default="60,10,15,5,0",
        help="Wagi liniowe sem,sk,sal,loc,av do porównania (default: prod).",
    )
    args = parser.parse_args()

    extra = tuple(args.with_feature)
    names = LAYERS + extra
    jobs = load_dump(args.dump, features=extra)
    if not jobs:
        print("pusty zrzut", file=sys.stderr)
        return 1

    baseline_vals = [float(v) for v in args.baseline.split(",")]
    if len(baseline_vals) != len(LAYERS):
        print("--baseline musi mieć 5 wartości", file=sys.stderr)
        return 1
    baseline = dict(zip(LAYERS, baseline_vals))
    for name in extra:
        baseline[name] = 0.0
    lin = metrics_for_weights(jobs, baseline)

    gbdt = evaluate_cv(
        jobs,
        names,
        folds=args.folds,
        trees=args.trees,
        depth=args.depth,
        lr=args.lr,
        min_leaf=args.min_leaf,
    )

    print(
        f"ofert: {len(jobs)} | cechy: {', '.join(names)} | "
        f"drzewa: {args.trees}x d{args.depth} | foldy: {args.folds}"
    )
    print(f"{'model':24} {'P@5':>7} {'R@20n':>7} {'MRR':>7} {'ofert':>6}")
    print(
        f"{'linear ' + args.baseline:24} {lin['p5']:>7.3f} "
        f"{lin['r20n']:>7.3f} {lin['mrr']:>7.3f} {lin['jobs']:>6}"
    )
    print(
        f"{'gbdt (cv po ofertach)':24} {gbdt['p5']:>7.3f} "
        f"{gbdt['r20n']:>7.3f} {gbdt['mrr']:>7.3f} {gbdt['jobs']:>6}"
    )
    # Uwaga interpretacyjna: linear jest liczony na CAŁYM zbiorze (to jego
    # optimum in-sample z simpleksu), gbdt na foldach testowych — porównanie
    # jest więc KONSERWATYWNE dla gbdt. Gdy mimo tego gbdt nie wygrywa
    # wyraźnie, nieliniowość nie niesie sygnału wartego serwingu.
    return 0


if __name__ == "__main__":
    sys.exit(main())
