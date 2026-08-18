"""Wyczerpujące przeszukiwanie wag na zrzucie warstw (LTR-lite, punkt 5).

Wejście: JSONL z `eval_matching --dump-layers` (per para oferta×kandydat:
punkty/max sześciu warstw + flaga GT). Rekombinacja jest DOKŁADNA dla
kompozytu bez renormalizacji-per-kandydat*, więc tysiące wektorów wag liczy
się w sekundy bez ponownego scoringu — zamiast 7-punktowej siatki z ręcznych
biegów harnessu.

*Uwaga o wierności: zrzut niesie frakcje warstw policzone przy KONKRETNYM
profilu biegu (punkty zależą od max warstwy tylko liniowo — frakcja
points/max jest niezmiennicza względem wag), ale renormalizacja warstw
bez sygnału i mnożniki (seniority) są już WPIECZONE w total, nie w frakcje.
Rekombinacja: total(w) = Σ w_i * frac_i po warstwach z max>0 — to przybliżenie
pomijające renormalizację unscored. Dlatego kontrakt użycia jest dwustopniowy:
przeszukanie wskazuje KANDYDATÓW na zwycięzcę, a werdykt wydaje wyłącznie
prawdziwy bieg harnessu z --weights na zamrożonym zbiorze.

Użycie:
    python -m scripts.weight_search --dump /tmp/layers.jsonl --top 10
    python -m scripts.weight_search --dump /tmp/layers.jsonl --step 5 --champion 10
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

LAYERS = ("semantic", "skills", "salary", "location", "availability")


def load_dump(path: str):
    """-> {job_id: [(candidate_id, gt, {layer: frac})]}"""
    jobs: dict[int, list] = defaultdict(list)
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            fracs = {}
            for name in LAYERS:
                layer = row.get("layers", {}).get(name) or {}
                mx = layer.get("max") or 0
                fracs[name] = (layer.get("points", 0.0) / mx) if mx else 0.0
            jobs[int(row["job_id"])].append(
                (int(row["candidate_id"]), bool(row.get("gt")), fracs)
            )
    return dict(jobs)


def metrics_for_weights(jobs: dict, weights: dict[str, float]) -> dict[str, float]:
    p5_sum = r20n_sum = mrr_sum = 0.0
    n = 0
    for rows in jobs.values():
        gt_ids = {cid for cid, gt, _ in rows if gt}
        if not gt_ids:
            continue
        scored = sorted(
            (
                (sum(weights[name] * fr[name] for name in LAYERS), cid)
                for cid, _gt, fr in rows
            ),
            reverse=True,
        )
        ranked = [cid for _s, cid in scored]
        top5, top20 = ranked[:5], ranked[:20]
        p5_sum += sum(1 for c in top5 if c in gt_ids) / 5.0
        ceiling = min(1.0, 20.0 / len(gt_ids))
        r20 = sum(1 for c in top20 if c in gt_ids) / len(gt_ids)
        r20n_sum += (r20 / ceiling) if ceiling else 0.0
        mrr = 0.0
        for rank, cid in enumerate(ranked, start=1):
            if cid in gt_ids:
                mrr = 1.0 / rank
                break
        mrr_sum += mrr
        n += 1
    if n == 0:
        return {"p5": 0.0, "r20n": 0.0, "mrr": 0.0, "jobs": 0}
    return {
        "p5": round(p5_sum / n, 4),
        "r20n": round(r20n_sum / n, 4),
        "mrr": round(mrr_sum / n, 4),
        "jobs": n,
    }


def simplex_grid(step: int, total: int):
    """Wszystkie wektory 5 nieujemnych wielokrotności `step` sumujące się do total."""
    for a in range(0, total + 1, step):
        for b in range(0, total + 1 - a, step):
            for c in range(0, total + 1 - a - b, step):
                for d in range(0, total + 1 - a - b - c, step):
                    e = total - a - b - c - d
                    yield {
                        "semantic": float(a),
                        "skills": float(b),
                        "salary": float(c),
                        "location": float(d),
                        "availability": float(e),
                    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", required=True, help="JSONL z --dump-layers")
    parser.add_argument(
        "--step", type=int, default=5, help="Krok siatki simpleksu (domyślnie 5)."
    )
    parser.add_argument(
        "--champion",
        type=int,
        default=10,
        help="Stały budżet champion_fit odejmowany od 100 (eval i tak go zeruje).",
    )
    parser.add_argument("--top", type=int, default=10, help="Ile wektorów pokazać.")
    args = parser.parse_args()

    jobs = load_dump(args.dump)
    if not jobs:
        print("pusty zrzut — nic do przeszukania", file=sys.stderr)
        return 1
    total_budget = 100 - args.champion

    results = []
    for weights in simplex_grid(args.step, total_budget):
        m = metrics_for_weights(jobs, weights)
        results.append((m, weights))

    # Ranking kandydatów na zwycięzcę: R@20n bez zapaści + P@5/MRR w górę.
    # Sortujemy po sumie znormalizowanych metryk — prosty skalarny kompromis;
    # finalny werdykt i tak wydaje prawdziwy bieg harnessu.
    results.sort(
        key=lambda item: item[0]["p5"] + item[0]["r20n"] + item[0]["mrr"],
        reverse=True,
    )

    print(f"ofert: {len(jobs)} | wektorów: {len(results)} | krok: {args.step}")
    print(f"{'wagi (sem/sk/sal/loc/av)':30} {'P@5':>7} {'R@20n':>7} {'MRR':>7}")
    for m, w in results[: args.top]:
        label = "/".join(str(int(w[name])) for name in LAYERS)
        print(f"{label:30} {m['p5']:>7.3f} {m['r20n']:>7.3f} {m['mrr']:>7.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
