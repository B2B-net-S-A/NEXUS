"""Etap 2: sygnały z historii i uczenie na parach. Strojenie na val (2025-H2), wynik na test (2026).
Każdy sygnał używa WYŁĄCZNIE danych sprzed startu ocenianej rekrutacji (t0 = pierwszy ruch osoby z prawdy)."""
import json, sys, itertools
import numpy as np
sys.path.insert(0, "/vr")
from common import *

cids, C, pos, gt, t0, gt_raw = load()
N = len(cids)
qids_all = np.load(f"{D}/q_ids.npy")
Qall = np.load(f"{D}/q_prod.npy")
qrow = {int(j): i for i, j in enumerate(qids_all)}
JDids = np.load(f"{D}/jobdoc_ids.npy"); JD = np.load(f"{D}/jobdoc_vecs.npy")
JD /= np.linalg.norm(JD, axis=1, keepdims=True)
jdrow = {int(j): i for i, j in enumerate(JDids)}
anyp = json.load(open(f"{D}/any_pipeline.json"))
meta = json.load(open(f"{D}/cand_meta.json"))

# historia: wszystkie pary prawdy (rel>=1) z czasem
pairs = []  # (job, cand_idx, t)
for j, rows in gt_raw.items():
    for c, rel, fa in rows:
        if c in pos:
            pairs.append((int(j), pos[c], fa))
P_job = np.array([p[0] for p in pairs]); P_c = np.array([p[1] for p in pairs]); P_t = np.array([p[2] for p in pairs])
apairs = [(int(j), pos[c], fa) for j, rows in anyp.items() for c, fa in rows if c in pos]
A_job = np.array([p[0] for p in apairs]); A_c = np.array([p[1] for p in apairs]); A_t = np.array([p[2] for p in apairs])

evaljobs = [int(j) for j in qids_all if int(j) in gt and int(j) in jdrow]
val = [j for j in evaljobs if split_of(t0[j]) == "val"]
test = [j for j in evaljobs if split_of(t0[j]) == "test"]
train = [j for j in evaljobs if split_of(t0[j]) == "train"]
print("train/val/test", len(train), len(val), len(test), flush=True)


def nrm(x):
    return x / np.linalg.norm(x, axis=-1, keepdims=True)


def evaluate(jobs, qfun, boostfun=None, ks=(100, 500, 1000)):
    out = {}
    for j in jobs:
        q = qfun(j)
        s = C @ q
        if boostfun is not None:
            b = boostfun(j)
            if b is not None:
                idx, val_ = b
                np.add.at(s, idx, val_)
        g = gt[j]
        ranks = (s[None, :] > s[g][:, None]).sum(axis=1) + 1
        m = {f"R@{k}": float((ranks <= k).mean()) for k in ks}
        m["MRR"] = float(1 / ranks.min()); m["medpct"] = float(np.median(ranks) / N)
        out[j] = m
    return out

base_q = lambda j: Qall[qrow[j]]

# --- wspólne: podobieństwo rekrutacji (wektory dokumentów ofert) i ich czasy
job_t0_all = {}
for j, rows in gt_raw.items():
    job_t0_all[int(j)] = min(fa for c, rel, fa in rows)
JDT = np.array([job_t0_all.get(int(j), 1e18) for j in JDids])


def knn_past(j, k):
    sims = JD @ JD[jdrow[j]]
    ok = (JDT < t0[j]) & (JDids != j)
    sims = np.where(ok, sims, -9)
    top = np.argpartition(-sims, k)[:k]
    top = top[sims[top] > -9]
    return JDids[top], sims[top]


def hist_pos(jobids, before):
    m = np.isin(P_job, jobids) & (P_t < before)
    return P_job[m], P_c[m]

results = {"prod": None}
R = {}

# F1: wektorowe sprzężenie zwrotne z k podobnych przeszłych rekrutacji
def make_F1(k, a):
    def qf(j):
        jj, ss = knn_past(j, k)
        _, cs = hist_pos(jj, t0[j])
        q = base_q(j)
        if len(cs) == 0:
            return q
        return nrm(q + a * nrm(C[cs].mean(axis=0)))
    return qf

# F2: bezpośredni bonus dla osób z prawdy podobnych przeszłych rekrutacji
def make_F2(k, beta, minsim):
    def bf(j):
        jj, ss = knn_past(j, k)
        keep = ss >= minsim
        jj, ss = jj[keep], ss[keep]
        if len(jj) == 0:
            return None
        w = dict(zip(jj.tolist(), ss.tolist()))
        pj, pc = hist_pos(jj, t0[j])
        if len(pc) == 0:
            return None
        return pc, beta * np.array([w[x] for x in pj])
    return bf

# G: aktywność kandydata — był w jakimkolwiek pipeline w oknie przed startem rekrutacji
def make_G(days, delta, gt_only=False):
    def bf(j):
        if gt_only:
            m = (P_t < t0[j]) & (P_t >= t0[j] - days * 86400)
            idx = np.unique(P_c[m])
        else:
            m = (A_t < t0[j]) & (A_t >= t0[j] - days * 86400)
            idx = np.unique(A_c[m])
        return idx, np.full(len(idx), delta)
    return bf

# H: adapter liniowy (ridge) uczony na train: q -> średni wektor osób z prawdy
Xtr = np.stack([Qall[qrow[j]] for j in train]).astype(np.float64)
Ytr = np.stack([nrm(C[gt[j]].mean(axis=0)) for j in train]).astype(np.float64)
def make_H(lam, a):
    W = np.linalg.solve(Xtr.T @ Xtr + lam * np.eye(Xtr.shape[1]), Xtr.T @ Ytr)
    def qf(j):
        q = base_q(j)
        return nrm(q + a * nrm(q @ W)).astype(np.float32)
    return qf

grids = {
    "F1": [(k, a) for k in (5, 10, 25) for a in (0.25, 0.5, 1.0)],
    "F2": [(k, b, ms) for k in (10, 25, 50) for b in (0.02, 0.05, 0.1) for ms in (0.0, 0.8)],
    "G": [(d, dl, g) for d in (30, 90, 365) for dl in (0.01, 0.03, 0.06) for g in (False, True)],
    "H": [(l, a) for l in (1.0, 10.0, 100.0) for a in (0.25, 0.5, 1.0)],
}
makers = {"F1": lambda p: (make_F1(*p), None), "F2": lambda p: (base_q, make_F2(*p)),
          "G": lambda p: (base_q, make_G(*p)), "H": lambda p: (make_H(*p), None)}

base_val = evaluate(val, base_q)
base_test = evaluate(test, base_q)
lines = []
best = {}
for fam, grid in grids.items():
    scored = []
    for p in grid:
        qf, bf = makers[fam](p)
        r = evaluate(val, qf, bf)
        scored.append((mean_of(r, "R@500", val) + mean_of(r, "MRR", val), p, r))
        print(fam, p, f"val R@100 {mean_of(r,'R@100',val):.4f} R@500 {mean_of(r,'R@500',val):.4f} MRR {mean_of(r,'MRR',val):.4f}", flush=True)
    scored.sort(key=lambda x: -x[0])
    p = scored[0][1]
    best[fam] = p
    qf, bf = makers[fam](p)
    R[f"{fam} {p}"] = evaluate(test, qf, bf)

# kombinacja najlepszych: H + F2 + G
qf = make_H(*best["H"])[0] if False else make_H(*best["H"])
f2 = make_F2(*best["F2"]); g = make_G(*best["G"])
def both(j):
    out = [x for x in (f2(j), g(j)) if x is not None]
    if not out: return None
    return np.concatenate([o[0] for o in out]), np.concatenate([o[1] for o in out])
R["H+F2+G"] = evaluate(test, qf, both)
R2 = {"prod": base_test, **R}
rep = [f"# Etap 2 — historia i uczenie (test 2026, n={len(test)}; strojenie na val n={len(val)}, uczenie na train n={len(train)})",
       f"Najlepsze parametry z val: {best}", "", table(R2, "prod", test),
       "", "Val baseline: " + ", ".join(f"{k} {mean_of(base_val,k,val):.4f}" for k in KEYS)]
open("/vr/reports/a2_history.md", "w").write("\n".join(rep))
print("\n".join(rep))
