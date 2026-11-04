"""Etap 2b: poprawione G (bez wierszy tej samej rekrutacji), rozbicie F2 na tego samego klienta / innych,
okres przed uruchomieniem przepięć (22.09.2026)."""
import json, sys
import numpy as np
sys.path.insert(0, "/vr")
exec(open("/vr/a2_history.py").read().split("grids = {")[0])  # wspólne ładowanie i funkcje
R = {}
base_val = evaluate(val, base_q)
base_test = evaluate(test, base_q)
R["F2 (25, 0.05, 0.0)"] = evaluate(test, base_q, make_F2(25, 0.05, 0.0))
jm = json.load(open(f"{D}/jobs_meta.json"))
client = {int(k): v["client"] for k, v in jm.items()}

def make_G2(days, delta, gt_only=False):
    def bf(j):
        if gt_only:
            m = (P_t < t0[j]) & (P_t >= t0[j] - days * 86400) & (P_job != j)
            idx = np.unique(P_c[m])
        else:
            m = (A_t < t0[j]) & (A_t >= t0[j] - days * 86400) & (A_job != j)
            idx = np.unique(A_c[m])
        return idx, np.full(len(idx), delta)
    return bf

def make_F2c(k, beta, scope):
    def bf(j):
        jj, ss = knn_past(j, k)
        cl = client.get(j)
        keep = np.array([(client.get(int(x)) == cl) == (scope == "same") for x in jj]) if scope != "all" else np.ones(len(jj), bool)
        jj, ss = jj[keep], ss[keep]
        if len(jj) == 0: return None
        w = dict(zip(jj.tolist(), ss.tolist()))
        pj, pc = hist_pos(jj, t0[j])
        if len(pc) == 0: return None
        return pc, beta * np.array([w[x] for x in pj])
    return bf

# baza: ilu osób z prawdy testu było WCZEŚNIEJ gdziekolwiek pozytywnie / w jakimkolwiek pipeline
prev_pos = prev_any = tot = 0
for j in test:
    for c in gt[j]:
        tot += 1
        prev_pos += bool(((P_c == c) & (P_t < t0[j]) & (P_job != j)).any())
        prev_any += bool(((A_c == c) & (A_t < t0[j]) & (A_job != j)).any())
print(f"osoby z prawdy testu: {tot}; wcześniej zweryfikowane+ gdzie indziej: {prev_pos/tot:.1%}; wcześniej w jakimkolwiek pipeline: {prev_any/tot:.1%}", flush=True)

lines = []
for name, grid, mk in (
    ("G2", [(d, dl, g) for d in (30, 90, 180) for dl in (0.02, 0.04, 0.06) for g in (False, True)], make_G2),
    ("F2c", [(25, b, s) for b in (0.05, 0.1) for s in ("same", "other")], make_F2c),
):
    best = {}
    for p in grid:
        r = evaluate(val, base_q, mk(*p))
        sc = mean_of(r, "R@500", val) + mean_of(r, "MRR", val)
        key = p[-1]
        if key not in best or sc > best[key][0]:
            best[key] = (sc, p)
        print(name, p, f"val R@100 {mean_of(r,'R@100',val):.4f} MRR {mean_of(r,'MRR',val):.4f}", flush=True)
    for key, (sc, p) in best.items():
        R[f"{name} {p}"] = evaluate(test, base_q, mk(*p))

pre = [j for j in test if t0[j] < 1790035200]  # przed 22.09.2026
R2 = {"prod": base_test, **{k: v for k, v in R.items() if k.startswith(("G2", "F2c", "F2 ", "F1", "H "))}}
rep = ["# Etap 2b — poprawione G, rozbicie F2", table(R2, "prod", test), "",
       f"## Test tylko przed uruchomieniem przepięć (n={len(pre)})", table(R2, "prod", pre)]
open("/vr/reports/a2b.md", "w").write("\n".join(rep)); print("\n".join(rep))
