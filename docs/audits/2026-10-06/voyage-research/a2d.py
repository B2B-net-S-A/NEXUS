"""Etap 2d: adapter zapytania uczony z NEGATYWAMI (Rocchio-ridge) — czysta poprawa wektora, bez historii osób."""
import json, sys
import numpy as np
sys.path.insert(0, "/vr")
exec(open("/vr/a2_history.py").read().split("grids = {")[0])
rng = np.random.default_rng(0)

def targets(jobs, hard=200):
    Y = []
    for j in jobs:
        q = Qall[qrow[j]]
        s = C @ q
        top = np.argpartition(-s, 2000)[:2000]
        neg = np.setdiff1d(top, gt[j])
        neg = neg[np.argsort(-s[neg])[:hard]]
        Y.append(nrm(C[gt[j]].mean(0)) - nrm(C[neg].mean(0)))
    return np.stack(Y)

Xtr = np.stack([Qall[qrow[j]] for j in train]).astype(np.float64)
Ytr = targets(train).astype(np.float64)
print("targets ok", flush=True)
best = None
for lam in (0.3, 1.0, 3.0, 10.0):
    W = np.linalg.solve(Xtr.T @ Xtr + lam * np.eye(1024), Xtr.T @ Ytr)
    for a in (0.5, 1.0, 2.0, 4.0):
        qf = lambda j, W=W, a=a: nrm(Qall[qrow[j]] + a * (Qall[qrow[j]] @ W)).astype(np.float32)
        r = evaluate(val, qf)
        sc = mean_of(r, "R@500", val) + mean_of(r, "MRR", val)
        print("rocchio", lam, a, f"val R@100 {mean_of(r,'R@100',val):.4f} R@500 {mean_of(r,'R@500',val):.4f} MRR {mean_of(r,'MRR',val):.4f}", flush=True)
        if best is None or sc > best[0]:
            best = (sc, lam, a, W)
_, lam, a, W = best
R = {"prod": evaluate(test, base_q),
     f"rocchio-ridge lam={lam} a={a}": evaluate(test, lambda j: nrm(Qall[qrow[j]] + a * (Qall[qrow[j]] @ W)).astype(np.float32)),
     "ridge-pos (H 1,1)": evaluate(test, make_H(1.0, 1.0))}
rep = ["# Etap 2d — adapter zapytania z negatywami (test 2026)", table(R, "prod", test)]
open("/vr/reports/a2d.md", "w").write("\n".join(rep)); print("\n".join(rep))
