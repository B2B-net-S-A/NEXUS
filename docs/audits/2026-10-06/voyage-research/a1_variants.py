"""Etap 1: warianty zapytania, centrowanie, fuzje. Bez uczenia."""
import json, sys
import numpy as np
sys.path.insert(0, "/vr")
from common import *

cids, C, pos, gt, t0, _ = load()
qids = np.load(f"{D}/q_ids.npy")
keep = [i for i, j in enumerate(qids) if int(j) in gt]
qids = qids[keep]
Qs = {}
for k in ("prod", "title", "req_short", "req_long", "nochamp", "hyde", "prod_asdoc"):
    try:
        Qs[k] = np.load(f"{D}/q_{k}.npy")[keep]
    except FileNotFoundError:
        pass
jd_ids = np.load(f"{D}/jobdoc_ids.npy"); JD = np.load(f"{D}/jobdoc_vecs.npy")
JD /= np.linalg.norm(JD, axis=1, keepdims=True)
jdpos = {int(j): i for i, j in enumerate(jd_ids)}
have = np.array([int(j) in jdpos for j in qids])
Qs["jobdoc"] = np.stack([JD[jdpos[int(j)]] if int(j) in jdpos else Qs["prod"][i] for i, j in enumerate(qids)])

def nrm(x):
    return x / np.linalg.norm(x, axis=1, keepdims=True)

if "req_short" in Qs:
    Qs["prod+req_short"] = nrm(Qs["prod"] + Qs["req_short"])
    Qs["prod+title"] = nrm(Qs["prod"] + Qs["title"])
    Qs["prod+hyde"] = nrm(Qs["prod"] + Qs["hyde"])
res = {k: rank_metrics(C, Q, qids, gt) for k, Q in Qs.items()}

# centrowanie korpusu (huby): odejmij średni wektor kandydata od obu stron
mu = C.mean(axis=0)
Cc = nrm(C - mu)
res["prod_centered"] = rank_metrics(Cc, nrm(Qs["prod"] - mu), qids, gt)
# all-but-the-top: usuń D głównych składowych
X = C[np.random.default_rng(0).choice(len(C), 20000, replace=False)] - mu
_, _, Vt = np.linalg.svd(X, full_matrices=False)
for dd in (1, 3, 10):
    P = Vt[:dd]
    Cp = nrm((C - mu) - ((C - mu) @ P.T) @ P)
    Qp = Qs["prod"] - mu
    Qp = nrm(Qp - (Qp @ P.T) @ P)
    res[f"prod_abtt{dd}"] = rank_metrics(Cp, Qp, qids, gt)

alljobs = [int(j) for j in qids]
test = [j for j in alljobs if split_of(t0[j]) == "test"]
rep = ["# Etap 1 — warianty zapytania (cały zbiór)", table(res, "prod", alljobs),
       "", "# Etap 1 — tylko test (2026)", table(res, "prod", test)]
open("/vr/reports/a1_variants.md", "w").write("\n".join(rep))
json.dump({k: {str(j): {kk: vv for kk, vv in m.items()} for j, m in r.items()} for k, r in res.items()},
          open("/vr/data/a1_res.json", "w"))
print("\n".join(rep))
