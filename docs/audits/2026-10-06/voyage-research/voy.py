"""Wspólne wywołanie Voyage z ponowieniami i licznikiem tokenów."""
import asyncio, json, os, time
import httpx
import numpy as np

URL = "https://api.voyageai.com/v1/embeddings"
LEDGER = "/vr/logs/tokens.jsonl"


async def embed(client, texts, *, input_type, model="voyage-3", dim=1024):
    texts = [t if t and t.strip() else " " for t in texts]
    body = {"model": model, "input": texts, "input_type": input_type, "truncation": True}
    if dim:
        body["output_dimension"] = dim
    for attempt in range(1, 9):
        try:
            r = await client.post(URL, json=body, timeout=180,
                                  headers={"Authorization": "Bearer " + os.environ["VOYAGE_API_KEY"]})
            if r.status_code in (429, 500, 502, 503, 504):
                await asyncio.sleep(min(90, 4 * attempt * attempt)); continue
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            d = r.json()
            by = {int(i["index"]): i["embedding"] for i in d["data"]}
            tok = int((d.get("usage") or {}).get("total_tokens") or 0)
            with open(LEDGER, "a") as f:
                f.write(json.dumps({"t": time.time(), "model": model, "n": len(texts), "tokens": tok}) + "\n")
            return [by[i] for i in range(len(texts))]
        except (httpx.TransportError, RuntimeError) as e:
            if attempt == 8:
                raise
            await asyncio.sleep(5 * attempt)


def batches(texts, max_items=64, max_chars=220_000):
    cur, size = [], 0
    for i, t in enumerate(texts):
        if cur and (len(cur) >= max_items or size + len(t) > max_chars):
            yield cur; cur, size = [], 0
        cur.append(i); size += len(t)
    if cur:
        yield cur


async def embed_all(texts, *, input_type, model="voyage-3", dim=1024, chunk=8000):
    """Długie teksty: kawałki po `chunk` znaków, średnia i normalizacja — jak `request_vector`."""
    pieces, owner = [], []
    for i, t in enumerate(texts):
        parts = [t[k:k + chunk] for k in range(0, len(t), chunk)] or [" "]
        for p in parts:
            pieces.append(p); owner.append(i)
    out = [None] * len(pieces)
    async with httpx.AsyncClient() as client:
        for n, b in enumerate(batches(pieces)):
            vecs = await embed(client, [pieces[i] for i in b], input_type=input_type, model=model, dim=dim)
            for i, v in zip(b, vecs):
                out[i] = v
            if n % 20 == 0:
                print(f"  batch {n} ({len(b)})", flush=True)
            await asyncio.sleep(0.3)
    d = len(out[0])
    acc = np.zeros((len(texts), d), dtype=np.float64)
    cnt = np.zeros(len(texts))
    for o, v in zip(owner, out):
        acc[o] += v; cnt[o] += 1
    acc /= cnt[:, None]
    acc /= np.linalg.norm(acc, axis=1, keepdims=True)
    return acc.astype(np.float32)
