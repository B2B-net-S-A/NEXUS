"""Etap 2c: połączenie sygnałów (bez przecieku) + kontrola: obecna premia legacy (podobne rekrutacje >=0.70/0.55)."""
import json, sys
import numpy as np
sys.path.insert(0, "/vr")
exec(open("/vr/a2b.py").read().split("# baza: ilu osób")[0])

def combo(*fs):
    def bf(j):
        out = [x for x in (f(j) for f in fs) if x is not None]
        if not out: return None
        return np.concatenate([o[0] for o in out]), np.concatenate([o[1] for o in out])
    return bf

# imitacja premii legacy: podobne rekrutacje z progami 0.70 (A) / 0.55 (B), ostatnie 18 mies., min(count,3)*stała
def make_legacy(beta):
    def bf(j):
        sims = JD @ JD[jdrow[j]]
        ok = (JDT < t0[j]) & (JDids != j) & (JDT >= t0[j] - 548 * 86400)
        a = np.flatnonzero(ok & (sims >= 0.70))
        jj = a if len(a) else np.flatnonzero(ok & (sims >= 0.55))
        jj = JDids[jj[np.argsort(-sims[jj])[:20]]]
        pj, pc = hist_pos(jj, t0[j])
        if len(pc) == 0: return None
        u, cnt = np.unique(pc, return_counts=True)
        return u, beta * np.minimum(cnt, 3)
    return bf

cands = {
    "legacy_boost(0.02)": (base_q, make_legacy(0.02)),
    "legacy_boost(0.04)": (base_q, make_legacy(0.04)),
    "F2+G2": (base_q, combo(make_F2(25, 0.05, 0.0), make_G2(30, 0.06, True))),
    "F2+G2(0.03)": (base_q, combo(make_F2(25, 0.05, 0.0), make_G2(30, 0.03, True))),
    "F1+F2+G2": (make_F1(5, 1.0), combo(make_F2(25, 0.05, 0.0), make_G2(30, 0.03, True))),
    "H+F2+G2": (make_H(1.0, 1.0), combo(make_F2(25, 0.05, 0.0), make_G2(30, 0.03, True))),
}
for name, (qf, bf) in cands.items():
    r = evaluate(val, qf, bf)
    print(name, f"val R@100 {mean_of(r,'R@100',val):.4f} R@500 {mean_of(r,'R@500',val):.4f} MRR {mean_of(r,'MRR',val):.4f}", flush=True)
R = {"prod": base_test}
for name, (qf, bf) in cands.items():
    R[name] = evaluate(test, qf, bf)
# kto zyskuje: osoby z prawdy NOWE dla firmy (nigdy wcześniej w żadnym pipeline) — czy premia im szkodzi?
new_people = {j: np.array([c for c in gt[j] if not ((A_c == c) & (A_t < t0[j]) & (A_job != j)).any()]) for j in test}
def recall_new(res_q, k=500):
    vals_b, vals_n = [], []
    for j in test:
        g = new_people[j]
        if len(g) == 0: continue
        for (qf, bf), store in ((cands_base, vals_b), (res_q, vals_n)):
            q = qf(j); s = C @ q
            if bf is not None:
                b = bf(j)
                if b is not None: np.add.at(s, b[0], b[1])
            ranks = (s[None, :] > s[g][:, None]).sum(axis=1) + 1
            store.append((ranks <= k).mean())
    return np.mean(vals_b), np.mean(vals_n), len(vals_b)
cands_base = (base_q, None)
print(table(R, "prod", test), flush=True)
rb, rn, n = recall_new(cands["F2+G2"])
rep = ["# Etap 2c — połączenia sygnałów (test 2026)", table(R, "prod", test), "",
       f"Osoby z prawdy NOWE dla firmy (wcześniej w żadnym pipeline), {n} rekrutacji: R@500 prod {rb:.4f} → F2+G2 {rn:.4f}"]
open("/vr/reports/a2c.md", "w").write("\n".join(rep)); print("\n".join(rep))
