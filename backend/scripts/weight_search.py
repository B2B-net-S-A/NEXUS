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


def load_dump(path: str, features: tuple[str, ...] = ()):
    """-> {job_id: [(candidate_id, gt, {layer_or_feature: frac})]}

    `features` (runda 2): nazwy cech z pola "features" zrzutu (0..1),
    dokładane do frakcji pod własną nazwą — simpleks traktuje je jak
    dodatkową warstwę o max=1. Brak cechy w wierszu = 0.0 (starszy zrzut).
    """
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
            feats = row.get("features") or {}
            for name in features:
                try:
                    fracs[name] = float(feats.get(name) or 0.0)
                except (TypeError, ValueError):
                    fracs[name] = 0.0
            jobs[int(row["job_id"])].append(
                (int(row["candidate_id"]), bool(row.get("gt")), fracs)
            )
    return dict(jobs)


def metrics_for_weights(jobs: dict, weights: dict[str, float]) -> dict[str, float]:
    names = tuple(weights.keys())
    p5_sum = r20n_sum = mrr_sum = 0.0
    n = 0
    for rows in jobs.values():
        gt_ids = {cid for cid, gt, _ in rows if gt}
        if not gt_ids:
            continue
        scored = sorted(
            (
                (sum(weights[name] * fr.get(name, 0.0) for name in names), cid)
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


def _dump_has_nonzero_champion(path: str) -> bool:
    """Czy zrzut niesie realny (max>0) wkład champion_fit.

    Przy leakage guardzie eval zeruje max tej warstwy — wtedy stały budżet
    siatki niczego nie zmienia i nota byłaby szumem."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            layer = row.get("layers", {}).get("champion_fit") or {}
            if (layer.get("max") or 0) > 0:
                return True
    return False


def simplex_grid(step: int, total: int, extra: tuple[str, ...] = ()):
    """Wszystkie wektory nieujemnych wielokrotności `step` sumujące się do total.

    Wymiary: 5 warstw + opcjonalne cechy z `extra` (runda 2). Rekurencyjnie,
    żeby liczba wymiarów nie była zapieczona w zagnieżdżeniu pętli.
    """
    names = LAYERS + tuple(extra)

    def _rec(idx: int, remaining: int, acc: dict):
        if idx == len(names) - 1:
            acc[names[idx]] = float(remaining)
            yield dict(acc)
            return
        for v in range(0, remaining + 1, step):
            acc[names[idx]] = float(v)
            yield from _rec(idx + 1, remaining - v, acc)

    yield from _rec(0, total, {})


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
    parser.add_argument(
        "--with-feature",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "Dołóż cechę z pola 'features' zrzutu jako dodatkowy wymiar "
            "simpleksu (np. title_match). Można powtarzać."
        ),
    )
    args = parser.parse_args()

    extra = tuple(args.with_feature)
    jobs = load_dump(args.dump, features=extra)
    if not jobs:
        print("pusty zrzut — nic do przeszukania", file=sys.stderr)
        return 1
    # Jawna informacja zamiast cichego ignorowania: champion_fit jest w zrzucie,
    # ale siatka go nie przeszukuje (stały budżet --champion). Gdy eval biegł
    # z leakage guardem, max=0 i wkład i tak był zerowy; niezerowy max oznacza
    # bieg z --include-champion — wtedy wyniki modelują stan BEZ tej warstwy.
    if _dump_has_nonzero_champion(args.dump):
        print(
            f"uwaga: zrzut ma niezerowy champion_fit, a siatka trzyma go jako "
            f"stały budżet {args.champion} — wyniki modelują stan bez tej "
            "warstwy (bieg z --include-champion?)",
            file=sys.stderr,
        )
    total_budget = 100 - args.champion

    results = []
    for weights in simplex_grid(args.step, total_budget, extra=extra):
        m = metrics_for_weights(jobs, weights)
        results.append((m, weights))

    # Ranking kandydatów na zwycięzcę: R@20n bez zapaści + P@5/MRR w górę.
    # Sortujemy po sumie znormalizowanych metryk — prosty skalarny kompromis;
    # finalny werdykt i tak wydaje prawdziwy bieg harnessu.
    results.sort(
        key=lambda item: item[0]["p5"] + item[0]["r20n"] + item[0]["mrr"],
        reverse=True,
    )

    dims = LAYERS + extra
    header = "sem/sk/sal/loc/av" + ("/" + "/".join(extra) if extra else "")
    print(f"ofert: {len(jobs)} | wektorów: {len(results)} | krok: {args.step}")
    print(f"{('wagi (' + header + ')'):40} {'P@5':>7} {'R@20n':>7} {'MRR':>7}")
    for m, w in results[: args.top]:
        label = "/".join(str(int(w[name])) for name in dims)
        print(f"{label:40} {m['p5']:>7.3f} {m['r20n']:>7.3f} {m['mrr']:>7.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
