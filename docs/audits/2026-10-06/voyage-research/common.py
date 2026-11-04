"""Wspólne: ładowanie danych, ocena rankingu, bootstrap."""
import json, os
import numpy as np

D = "/vr/data"
T_VAL = 1751328000.0   # 2025-07-01
T_TEST = 1767225600.0  # 2026-01-01


def load():
    cids = np.load(f"{D}/cand_ids.npy")
    C = np.load(f"{D}/cand_vecs.npy")
    C /= np.linalg.norm(C, axis=1, keepdims=True)
    gt_raw = json.load(open(f"{D}/gt.json"))
    pos = {int(c): i for i, c in enumerate(cids)}
    gt = {}
    t0 = {}
    for j, rows in gt_raw.items():
        idx = [pos[c] for c, rel, fa in rows if c in pos]
        if len(idx) >= 3:
            gt[int(j)] = np.array(idx)
            t0[int(j)] = min(fa for c, rel, fa in rows)
    return cids, C, pos, gt, t0, gt_raw


def split_of(t):
    return "test" if t >= T_TEST else ("val" if t >= T_VAL else "train")


def rank_metrics(C, Q, qids, gt, chunk=192, ks=(50, 100, 500, 1000), cand_mask=None, return_ranks=False):
    """Dla każdej rekrutacji: ranga każdej osoby z prawdy wśród wszystkich kandydatów (1 = najwyżej)."""
    out = {}
    N = C.shape[0]
    for s in range(0, len(qids), chunk):
        S = C @ Q[s:s + chunk].T   # N x b
        if cand_mask is not None:
            S[~cand_mask] = -9.0
        for b, jid in enumerate(qids[s:s + chunk]):
            g = gt.get(int(jid))
            if g is None:
                continue
            col = S[:, b]
            gs = col[g]
            ranks = (col[None, :] > gs[:, None]).sum(axis=1) + 1 if len(g) < 64 else np.searchsorted(-np.sort(-col), -gs, side="left") + 1
            m = {f"R@{k}": float((ranks <= k).mean()) for k in ks}
            m["MRR"] = float(1.0 / ranks.min())
            m["medpct"] = float(np.median(ranks) / N)
            if return_ranks:
                m["ranks"] = ranks
            out[int(jid)] = m
    return out


def mean_of(res, key, jobs):
    v = [res[j][key] for j in jobs if j in res]
    return float(np.mean(v)) if v else float("nan")


def paired_ci(a, b, key, jobs, n=2000, seed=0):
    """Średnia różnicy b-a i 95% CI z bootstrapu par rekrutacji."""
    js = [j for j in jobs if j in a and j in b]
    d = np.array([b[j][key] - a[j][key] for j in js])
    rng = np.random.default_rng(seed)
    bs = d[rng.integers(0, len(d), (n, len(d)))].mean(axis=1)
    return float(d.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)), len(js)


KEYS = ("R@100", "R@500", "R@1000", "MRR", "medpct")


def table(results, base, jobs, keys=KEYS):
    lines = ["| wariant | n | " + " | ".join(keys) + " |", "|---|---|" + "---|" * len(keys)]
    for name, r in results.items():
        cells = []
        for k in keys:
            m = mean_of(r, k, jobs)
            if name == base:
                cells.append(f"{m:.4f}")
            else:
                d, lo, hi, n = paired_ci(results[base], r, k, jobs)
                star = "*" if (lo > 0 or hi < 0) else ""
                cells.append(f"{m:.4f} ({d:+.4f}{star} [{lo:+.4f};{hi:+.4f}])")
        lines.append(f"| {name} | {len([j for j in jobs if j in r])} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
