"""Ocena kolejności wyników „Szukaj ręcznie” na historii rekrutacji (tylko odczyt).

Punkt kontrolny przed włączeniem sortowania „Dopasowanie do rekrutacji”
(audyt 25.09.2026). Dla rekrutacji z ostatnich 24 miesięcy odtwarza
wyszukiwanie rekrutera — dwa pierwsze wymagania „musi mieć” jako wiersze
wymagań, baza cofnięta do dnia otwarcia — i sprawdza, na której pozycji
lądują osoby, które zespół potem zweryfikował albo wysłał klientowi.

Porównywane kolejności:

* ``najnowsi`` — dzisiejsza;
* ``wektor rekrutacji (nexus_jobs)`` — punkt oferty w Qdrancie;
* ``wektor kolumny Dop.`` — ``request_vector(build_request_context(...))``,
  ten sam co ``/api/search/candidates/scores`` (kolejność zgodna z kolumną);
* ``cała baza, wektor Dop.`` — bez filtra słów (rekrutacja bez wymagań
  w Championie): 3 000 najbliższych z indeksu, reszta od najnowszych.

Nic nie zapisuje: wektor zapytania idzie prosto do Voyage (bez tabeli
``embedding_cache``), baza w ``SET TRANSACTION READ ONLY``::

    cd /app && python -m scripts.eval_manual_search_order --jobs 120
"""

from __future__ import annotations

import argparse
import asyncio
import re
import statistics
import time

from sqlalchemy import select, text

ANN_TOP = 3000
PAGE = 50


def _fts(word: str):
    from app.services import keyword_terms as kt

    term = kt.parse_keyword(word)
    if term is None or term.open_start:
        return None
    query = kt.tsquery_text(term)
    return None if query is None else (query, kt.tsquery_path_variants(term))


def _exact_order(client, vector, ids: list[int]) -> list[int]:
    from qdrant_client.models import (
        Filter,
        HasIdCondition,
        QuantizationSearchParams,
        SearchParams,
    )

    from app.services import embedding_service as emb

    hits = client.search(
        collection_name=emb._collection(),
        query_vector=vector,
        query_filter=Filter(must=[HasIdCondition(has_id=ids)]),
        search_params=SearchParams(
            exact=True, quantization=QuantizationSearchParams(ignore=True)
        ),
        limit=len(ids),
        with_payload=False,
        with_vectors=False,
    )
    ordered = [int(h.id) for h in hits]
    seen = set(ordered)
    return ordered + [i for i in ids if i not in seen]


def _ann_order(client, vector, base_newest: list[int]) -> list[int]:
    from app.services import embedding_service as emb

    hits = client.search(
        collection_name=emb._collection(),
        query_vector=vector,
        limit=ANN_TOP,
        with_payload=False,
        with_vectors=False,
    )
    allowed = set(base_newest)
    top = [int(h.id) for h in hits if int(h.id) in allowed]
    seen = set(top)
    return top + [i for i in base_newest if i not in seen]


def _job_point_vector(client, job_id: int):
    from app.services import embedding_service as emb

    points = client.retrieve(
        collection_name=emb._jobs_collection(), ids=[job_id], with_vectors=True
    )
    if not points or points[0].vector is None:
        return None
    vector = points[0].vector
    return next(iter(vector.values())) if isinstance(vector, dict) else vector


def _report(name: str, rows: list[tuple[int, list[int]]]) -> None:
    ranks = [r for _, rs in rows for r in rs]
    top = sum(1 for r in ranks if r <= PAGE) / max(len(ranks), 1)
    jobs = sum(1 for _, rs in rows if any(r <= PAGE for r in rs)) / max(len(rows), 1)
    mrr = statistics.mean([max((1 / r for r in rs), default=0) for _, rs in rows])
    median = statistics.median(ranks) if ranks else "-"
    print(
        f"| {name} | {jobs:.1%} | {top:.1%} | {mrr:.3f} | {median} |",
        flush=True,
    )


async def main(max_jobs: int) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services import embedding_service as emb
    from app.services.full_search_measurement import request_vector
    from app.services.request_matching_context import build_request_context
    from app.services.scoring_service import resolve_active_profile

    client = emb._get_qdrant_client()
    orders = [
        "najnowsi (dziś)",
        "wektor rekrutacji (nexus_jobs)",
        "wektor kolumny Dop.",
        "cała baza, wektor Dop.",
        "cała baza, najnowsi",
    ]
    results: dict[str, list[tuple[int, list[int]]]] = {k: [] for k in orders}
    started = time.time()
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        await db.execute(text("SET LOCAL statement_timeout = '120s'"))
        jobs = (
            await db.execute(
                text(
                    """
            select j.id, coalesce(j.opened_at, j.created_at) t0, j.must_skills from jobs j
            where (case when jsonb_typeof(j.must_skills)='array'
                        then jsonb_array_length(j.must_skills) else 0 end) >= 2
              and coalesce(j.opened_at, j.created_at) > now() - interval '24 months'
              and (select count(*) from analytics_first_milestones m
                   join candidates c on c.id = m.candidate_id
                   where m.job_id = j.id and m.stage in ('verified','cv_sent')
                     and c.created_at < coalesce(j.opened_at, j.created_at)) >= 2
            order by j.id desc limit 400"""
                )
            )
        ).all()
        used = 0
        for job_id, t0, must in jobs:
            words = []
            for item in must:
                name = (
                    ((item.get("name") if isinstance(item, dict) else str(item)) or "")
                    .strip()
                    .lower()
                )
                if not re.fullmatch(r"[a-z0-9ąćęłńóśźż#+.]{2,20}", name):
                    continue
                parsed = _fts(name)
                if parsed:
                    words.append(parsed)
                if len(words) == 2:
                    break
            if len(words) < 2:
                continue
            parts, params = [], {"t0": t0, "jid": job_id}
            for i, (query, variants) in enumerate(words):
                params[f"q{i}"] = query
                part = f"to_tsquery('simple', :q{i})"
                if variants:
                    params[f"v{i}"] = variants
                    part = f"({part} || cast(:v{i} as tsquery))"
                parts.append(part)
            ids = list(
                (
                    await db.execute(
                        text(
                            "select id from candidates c where c.created_at < :t0 "
                            f"and c.keyword_fts @@ ({' && '.join(parts)}) "
                            "order by c.created_at desc, c.id desc"
                        ),
                        params,
                    )
                ).scalars()
            )
            if len(ids) < 100:
                continue
            positives = set(
                (
                    await db.execute(
                        text(
                            "select distinct m.candidate_id from analytics_first_milestones m "
                            "join candidates c on c.id = m.candidate_id "
                            "where m.job_id = :jid and m.stage in ('verified','cv_sent') "
                            "and c.created_at < :t0"
                        ),
                        params,
                    )
                ).scalars()
            )
            job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
            profile = await resolve_active_profile(db, client_id=job.client_id)
            context = build_request_context(job, profile)
            dop_vector = await request_vector(context.query_text)
            point_vector = await asyncio.to_thread(_job_point_vector, client, job_id)
            if dop_vector is None or point_vector is None:
                continue
            base_newest = list(
                (
                    await db.execute(
                        text(
                            "select id from candidates where created_at < :t0 "
                            "order by created_at desc, id desc"
                        ),
                        params,
                    )
                ).scalars()
            )
            ranked = {
                orders[0]: ids,
                orders[1]: await asyncio.to_thread(
                    _exact_order, client, point_vector, ids
                ),
                orders[2]: await asyncio.to_thread(
                    _exact_order, client, dop_vector, ids
                ),
                orders[3]: await asyncio.to_thread(
                    _ann_order, client, dop_vector, base_newest
                ),
                orders[4]: base_newest,
            }
            for name, order in ranked.items():
                position = {
                    cid: i + 1 for i, cid in enumerate(order) if cid in positives
                }
                results[name].append((len(positives), list(position.values())))
            used += 1
            if used >= max_jobs:
                break
    print(f"\nRekrutacje: {used}, czas {time.time() - started:.0f} s\n", flush=True)
    print(
        "| kolejność | rekrutacje z ≥1 właściwą osobą na 1. stronie | właściwe osoby w top 50 | MRR | mediana pozycji |"
    )
    print("|---|---:|---:|---:|---:|")
    for name in orders:
        _report(name, results[name])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=120)
    asyncio.run(main(parser.parse_args().jobs))
