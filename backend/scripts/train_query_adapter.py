"""Uczenie adaptera wektora zapytania (`app/services/query_adapter.py`).

Badanie 06.10.2026 (`docs/audits/2026-10-06/voyage-embeddings-research.md`):
macierz W taka, że ``q + a·q·W`` zbliża zapytanie rekrutacji do osób, które
zespół zweryfikował, a oddala od trudnych negatywów. Ridge w formie
zamkniętej, bez modelu językowego.

- Prawda: para (rekrutacja, osoba) co najmniej „Zweryfikowany”; rekrutacje
  z ≥ 3 takimi osobami, z wektorem kandydata w Qdrancie.
- Zamrożone zbiory ewaluacyjne (`scripts/eval_frozen_set.py`, A i B) NIGDY nie
  trafiają do uczenia — na nich mierzy A/B (`eval_ab_run --arms query-adapter`).
- Wybór λ i a na rekrutacjach z ostatnich ``--val-months`` miesięcy (uczenie
  na starszych), potem ostateczne uczenie na wszystkich poza zbiorami eval.
- Zapytanie = ten sam tekst i ta sama funkcja co produkcja
  (`build_request_context(...).query_text` → `request_vector`).

Tylko odczyt bazy i Qdranta; zapis wyłącznie pliku ``--out`` (macierz liczb,
bez danych osobowych). Koszt Voyage ≈ 1–2 mln tokenów (zapytania).

    python -m scripts.train_query_adapter --out /tmp/query_adapter.npz
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select, text

POSITIVE = (
    "verified",
    "cv_sent",
    "interview",
    "client_interview",
    "acceptance",
    "negotiation",
    "onboarding",
    "hired",
)


def _nrm(x: np.ndarray) -> np.ndarray:
    return x / np.linalg.norm(x, axis=-1, keepdims=True)


def _scroll_candidates():
    from app.services import embedding_service as es

    client = es._get_qdrant_client()
    ids, vecs, offset = [], [], None
    while True:
        pts, offset = client.scroll(
            collection_name=es.candidates_collection_name(),
            limit=2000,
            offset=offset,
            with_payload=False,
            with_vectors=True,
        )
        for p in pts:
            v = p.vector
            if isinstance(v, dict):
                v = next(iter(v.values()))
            ids.append(int(p.id))
            vecs.append(v)
        if offset is None:
            break
    return np.array(ids), _nrm(np.asarray(vecs, dtype=np.float32))


async def _queries(job_ids: list[int]) -> dict[int, np.ndarray]:
    """Wektory zapytań jak `request_vector` (kawałki po 8000 znaków, średnia,
    normalizacja), ale paczkami — po jednym trwało ~3 s na rekrutację."""
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.embedding_service import _voyage_embed_batch
    from app.services.request_matching_context import build_request_context
    from app.services.scoring_service import DEFAULT_PROFILE

    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        jobs = (
            (await db.execute(select(Job).where(Job.id.in_(job_ids)))).scalars().all()
        )
        texts = {}
        for job in jobs:
            try:
                texts[job.id] = build_request_context(job, DEFAULT_PROFILE).query_text
            except Exception as exc:  # noqa: BLE001 — pojedyncza rekrutacja odpada
                print(
                    f"pominięta rekrutacja {job.id}: {type(exc).__name__}", flush=True
                )
    pieces: list[tuple[int, str]] = [
        (jid, query[i : i + 8000])
        for jid, query in texts.items()
        for i in range(0, len(query), 8000)
        if query
    ]
    sums: dict[int, np.ndarray] = {}
    counts: dict[int, int] = {}
    batch: list[tuple[int, str]] = []
    size = 0

    async def flush() -> None:
        vectors = await _voyage_embed_batch([t for _, t in batch], input_type="query")
        if vectors is None:
            raise RuntimeError("Voyage nie odpowiedział")
        for (jid, _), vector in zip(batch, vectors):
            if vector:
                sums[jid] = sums.get(jid, 0) + np.asarray(vector, dtype=np.float64)
                counts[jid] = counts.get(jid, 0) + 1

    for n, piece in enumerate(pieces):
        if batch and (len(batch) >= 64 or size + len(piece[1]) > 200_000):
            await flush()
            batch, size = [], 0
        batch.append(piece)
        size += len(piece[1])
        if n % 500 == 0:
            print(f"kawałki zapytań {n}/{len(pieces)}", flush=True)
    if batch:
        await flush()
    return {
        jid: (v / counts[jid] / np.linalg.norm(v / counts[jid])).astype(np.float32)
        for jid, v in sums.items()
    }


def _targets(
    Q: np.ndarray, C: np.ndarray, gts: list[np.ndarray], hard: int
) -> np.ndarray:
    Y = []
    for q, g in zip(Q, gts):
        s = C @ q
        top = np.argpartition(-s, 2000)[:2000]
        neg = np.setdiff1d(top, g)
        neg = neg[np.argsort(-s[neg])[:hard]]
        Y.append(_nrm(C[g].mean(0)) - _nrm(C[neg].mean(0)))
    return np.stack(Y)


def _fit(X: np.ndarray, Y: np.ndarray, lam: float) -> np.ndarray:
    X = X.astype(np.float64)
    return np.linalg.solve(
        X.T @ X + lam * np.eye(X.shape[1]), X.T @ Y.astype(np.float64)
    )


def _metrics(Q: np.ndarray, C: np.ndarray, gts: list[np.ndarray]) -> dict:
    r500, mrr = [], []
    for q, g in zip(Q, gts):
        s = C @ q
        ranks = (s[None, :] > s[g][:, None]).sum(axis=1) + 1
        r500.append(float((ranks <= 500).mean()))
        mrr.append(float(1 / ranks.min()))
    return {"R@500": float(np.mean(r500)), "MRR": float(np.mean(mrr))}


def _adapt(Q: np.ndarray, W: np.ndarray, a: float) -> np.ndarray:
    return _nrm(Q + a * (Q @ W).astype(np.float32))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--val-months", type=int, default=9)
    ap.add_argument("--hard", type=int, default=200)
    args = ap.parse_args()

    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from scripts.eval_frozen_set import FROZEN_JOB_IDS_2026_08, FROZEN_JOB_IDS_2026_08_B

    frozen = set(FROZEN_JOB_IDS_2026_08) | set(FROZEN_JOB_IDS_2026_08_B)
    cids, C = _scroll_candidates()
    pos = {int(c): i for i, c in enumerate(cids)}
    print("kandydaci z wektorem", len(cids), flush=True)

    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        rows = (
            await db.execute(
                text(
                    "SELECT job_id, candidate_id, min(moved_at) FROM candidate_stages "
                    "WHERE stage::text = ANY(:pos) GROUP BY 1, 2"
                ),
                {"pos": list(POSITIVE)},
            )
        ).all()
    gt: dict[int, list[int]] = {}
    t0: dict[int, datetime] = {}
    for jid, cid, at in rows:
        if int(jid) in frozen or int(cid) not in pos:
            continue
        gt.setdefault(int(jid), []).append(pos[int(cid)])
        t0[int(jid)] = min(t0.get(int(jid), at), at)
    jobs = [j for j, g in gt.items() if len(g) >= 3]
    queries = await _queries(jobs)
    jobs = [j for j in jobs if j in queries]
    cut = datetime.now(timezone.utc) - timedelta(days=30 * args.val_months)
    train = [j for j in jobs if t0[j] < cut]
    val = [j for j in jobs if t0[j] >= cut]
    print(
        f"rekrutacje: uczenie {len(train)}, walidacja {len(val)}, wykluczone eval {len(frozen)}",
        flush=True,
    )

    def block(js):
        return np.stack([queries[j] for j in js]), [np.array(gt[j]) for j in js]

    Xtr, Gtr = block(train)
    Xva, Gva = block(val)
    Ytr = _targets(Xtr, C, Gtr, args.hard)
    base = _metrics(Xva, C, Gva)
    best = None
    for lam in (1.0, 3.0, 10.0):
        W = _fit(Xtr, Ytr, lam)
        for a in (1.0, 2.0, 3.0):
            m = _metrics(_adapt(Xva, W, a), C, Gva)
            print(f"λ={lam} a={a} walidacja {m}", flush=True)
            score = m["R@500"] + m["MRR"]
            if best is None or score > best[0]:
                best = (score, lam, a, m)
    _, lam, a, val_metrics = best
    Xall, Gall = block(jobs)
    W = _fit(Xall, _targets(Xall, C, Gall, args.hard), lam)
    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "jobs": len(jobs),
        "lambda": lam,
        "val_baseline": base,
        "val_adapter": val_metrics,
    }
    np.savez_compressed(
        args.out,
        W=W.astype(np.float16),
        alpha=np.float64(a),
        model=np.array(settings.VOYAGE_MODEL),
        meta=np.array(json.dumps(meta)),
    )
    print("zapisano", args.out, json.dumps(meta), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
