import json, collections
import numpy as np
D = "/vr/data"
meta = json.load(open(f"{D}/cand_meta.json"))
gt = json.load(open(f"{D}/gt.json"))
gtc = set(c for rows in gt.values() for c, rel, fa in rows)
N = len(meta)
def pct(n, d=N): return f"{n} ({100*n/d:.1f}%)"
idx = [m for m in meta.values() if m["indexed"]]
print("kandydaci", N, "z wektorem", pct(len(idx)))
print("wektor AKTUALNY (hash = obecny tekst)", pct(sum(m["fresh"] for m in idx), len(idx)))
print("modele w payloadzie", collections.Counter(m["model"] for m in idx).most_common(5))
L = np.array([m["txt_wo_name_len"] for m in meta.values()])
for th in (50, 200, 500, 1000):
    print(f"tekst bez imienia < {th} znaków:", pct(int((L < th).sum())))
print("mediana długości tekstu", int(np.median(L)), "p90", int(np.percentile(L, 90)))
print("bez CV (<200 zn.)", pct(sum(m["cv_len"] < 200 for m in meta.values())))
print("bez umiejętności", pct(sum(m["n_skills"] == 0 for m in meta.values())))
print("bez doświadczenia", pct(sum(m["n_exp"] == 0 for m in meta.values())))
print("z podsumowaniem AI", pct(sum(m["has_summary"] for m in meta.values())))
print("źródła", collections.Counter(m["src"] for m in meta.values()).most_common(6))
g = [meta[str(c)] for c in gtc if str(c) in meta]
print("--- osoby z prawdy (zweryfikowane+):", len(g))
print("  aktualny wektor", pct(sum(m["fresh"] for m in g), len(g)))
print("  tekst < 200", pct(sum(m["txt_wo_name_len"] < 200 for m in g), len(g)))
print("  bez CV", pct(sum(m["cv_len"] < 200 for m in g), len(g)))
stale = [m for m in idx if not m["fresh"]]
print("--- nieaktualne wektory wg źródła", collections.Counter(m["src"] for m in stale).most_common(5))
