import json, sys, collections
import numpy as np
sys.path.insert(0, "/vr")
from common import *
cids, C, pos, gt, t0, _ = load()
meta = json.load(open(f"{D}/cand_meta.json"))
alive = np.array([str(int(c)) in meta for c in cids])
print("punkty w Qdrancie:", len(cids), "sieroty (brak kandydata w bazie):", int((~alive).sum()))
Q = np.load(f"{D}/q_prod.npy"); qids = np.load(f"{D}/q_ids.npy")
cnt = np.zeros(len(cids), int)
for s in range(0, len(Q), 256):
    S = C @ Q[s:s+256].T
    top = np.argpartition(-S, 100, axis=0)[:100]
    np.add.at(cnt, top.ravel(), 1)
J = len(Q)
order = np.argsort(-cnt)
print(f"rekrutacji: {J}; kandydaci w top100 ≥10% rekrutacji: {(cnt >= 0.1*J).sum()}, ≥5%: {(cnt >= 0.05*J).sum()}")
share = cnt[order[:100]].sum() / (100 * J)
print(f"100 najczęstszych kandydatów zajmuje {share:.1%} wszystkich miejsc w top100")
gtset = set(int(i) for v in gt.values() for i in v)
L = np.array([meta.get(str(int(c)), {}).get("txt_wo_name_len", -1) for c in cids])
for k in (20, 100, 500):
    idx = order[:k]
    print(f"top{k} hubów: mediana dł. tekstu {int(np.median(L[idx]))} (cała baza {int(np.median(L[L>=0]))}); "
          f"w prawdzie jakiejkolwiek rekrutacji: {np.mean([i in gtset for i in idx]):.0%}; sieroty: {int((~alive[idx]).sum())}")
# czy huby to cienkie teksty?
thin = (L >= 0) & (L < 500)
print("kandydaci z tekstem <500: średnia obecność w top100 =", round(cnt[thin].mean(), 2), "vs reszta", round(cnt[~thin & (L>=0)].mean(), 2))
