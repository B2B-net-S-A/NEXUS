import json, glob, os, sys
import numpy as np
sys.path.insert(0, "/vr")
from common import *
OUTD = "/vr/data/a3"
cids, C, pos, gt, t0, _ = load()
sub = np.load(f"{OUTD}/sub_idx.npy"); jobs = json.load(open(f"{OUTD}/jobs.json"))
remap = {int(g): i for i, g in enumerate(sub)}
gts = {j: np.array([remap[int(i)] for i in gt[j]]) for j in jobs}
qids = np.array(jobs)
qprod = np.load(f"{D}/q_prod.npy"); qall = np.load(f"{D}/q_ids.npy"); qr = {int(j): i for i, j in enumerate(qall)}
res = {"stored(prod)": rank_metrics(C[sub], qprod[[qr[j] for j in jobs]], qids, gts, ks=(10, 50, 100, 500))}
for p in sorted(glob.glob(f"{OUTD}/c__*.npy")):
    _, model, var = os.path.basename(p)[:-4].split("__")
    Cs = np.load(p); Q = np.load(f"{OUTD}/q__{model}.npy")
    res[f"{model}:{var}"] = rank_metrics(Cs, Q, qids, gts, ks=(10, 50, 100, 500))
keys = ("R@10", "R@50", "R@100", "R@500", "MRR")
rep = [f"# Etap 3 — tekst kandydata i model (300 rekrutacji z 2026, pula {len(sub)} kandydatów)",
       "Długości tekstów (średnio znaków): " + open(f"{OUTD}/lens.json").read(), "",
       table(res, "voyage-3:v1", jobs, keys=keys)]
open("/vr/reports/a3_candtext.md", "w").write("\n".join(rep)); print("\n".join(rep))
