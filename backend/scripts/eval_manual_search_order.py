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
  w Championie): 3 000 najbliższych z indeksu, reszta od najnowszych;
* ``wektor Dop. → top N wg Dop.`` (``--rerank-top``, 26.09.2026) — kolejność
  wektorem, a ``N`` pierwszych przeliczone pełnym wynikiem kolumny „Dop.”
  (``canonical_fit.score_candidates``: umiejętności, staż, stawka, lokalizacja
  + wektor). Sam wektor nie zgadza się z liczbami w kolumnie (na produkcji
  10 z 19 sąsiednich par malejąco), więc sprawdzamy, czy pełny wynik trafia
  lepiej. Pełny wynik liczy dzisiejsze dane profilu, a wymagania zweryfikowane
  przez rekruterów są domyślnie MASKOWANE (jak w ``eval_matching``): powstają
  w trakcie procesu, więc to etykieta, nie dane, które rekruter miał na starcie.
  ``--include-reviewed-evidence`` je przywraca (pomiar przecieku).

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
    anywhere = len(ranks) / max(sum(n for n, _ in rows), 1)
    top = sum(1 for r in ranks if r <= PAGE) / max(len(ranks), 1)
    jobs = sum(1 for _, rs in rows if any(r <= PAGE for r in rs)) / max(len(rows), 1)
    mrr = statistics.mean([max((1 / r for r in rs), default=0) for _, rs in rows])
    median = statistics.median(ranks) if ranks else "-"
    print(
        f"| {name} | {anywhere:.1%} | {jobs:.1%} | {top:.1%} | {mrr:.3f} | {median} |",
        flush=True,
    )


async def _rerank_by_fit(
    db, context, ordered: list[int], top: int, *, reviewed: bool = False
) -> list[int]:
    from app.models.candidate import Candidate
    from app.services import requirement_verification as rv
    from app.services.canonical_fit import score_candidates

    head = ordered[:top]
    if not head:
        return ordered
    candidates = list(
        (await db.execute(select(Candidate).where(Candidate.id.in_(head))))
        .scalars()
        .all()
    )
    original = rv.load_verified_requirements

    async def masked(_db, job, cands):
        await original(None, job, cands)

    if not reviewed:
        rv.load_verified_requirements = masked
    try:
        fits = await score_candidates(db, context, candidates)
    finally:
        rv.load_verified_requirements = original
    score = {
        int(f.breakdown.candidate_id): f.fit_score
        for f in fits
        if f.fit_score is not None
    }
    position = {cid: i for i, cid in enumerate(head)}
    reranked = sorted(head, key=lambda cid: (-score.get(cid, -1.0), position[cid]))
    return reranked + ordered[top:]


async def main(
    max_jobs: int, rerank_top: int = 0, reviewed: bool = False, ai_top: int = 0
) -> None:
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
    if rerank_top:
        orders.append(f"wektor Dop. → top {rerank_top} wg Dop.")
    manual_or = "ręczne: wiersze LUB, wektor Dop."
    orders.append(manual_or)
    ai_name = f"AI: cała baza, {ai_top} najbliższych → wg Dop." if ai_top else ""
    if ai_top:
        orders.append(ai_name)
    manual_best = orders[5] if rerank_top else orders[2]
    overlap = {"tylko ręczne": 0, "tylko AI": 0, "oba": 0, "żadne": 0}
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
            if rerank_top:
                ranked[orders[5]] = await _rerank_by_fit(
                    db, context, ranked[orders[2]], rerank_top, reviewed=reviewed
                )
            or_ids = list(
                (
                    await db.execute(
                        text(
                            "select id from candidates c where c.created_at < :t0 "
                            f"and c.keyword_fts @@ ({' || '.join(parts)}) "
                            "order by c.created_at desc, c.id desc"
                        ),
                        params,
                    )
                ).scalars()
            )
            ranked[manual_or] = (
                await asyncio.to_thread(_exact_order, client, dop_vector, or_ids)
                if len(or_ids) <= 30_000
                else await asyncio.to_thread(_ann_order, client, dop_vector, or_ids)
            )
            if ai_top:
                ranked[ai_name] = await _rerank_by_fit(
                    db, context, ranked[orders[3]], ai_top, reviewed=reviewed
                )
                manual_top = set(ranked[manual_best][:PAGE])
                ai_top_set = set(ranked[ai_name][:PAGE])
                for cid in positives:
                    in_m, in_a = cid in manual_top, cid in ai_top_set
                    key = (
                        "oba"
                        if in_m and in_a
                        else "tylko ręczne"
                        if in_m
                        else "tylko AI"
                        if in_a
                        else "żadne"
                    )
                    overlap[key] += 1
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
        "| kolejność | właściwe osoby w wynikach w ogóle | rekrutacje z ≥1 właściwą osobą na 1. stronie | właściwe osoby w top 50 | MRR | mediana pozycji |"
    )
    print("|---|---:|---:|---:|---:|---:|")
    for name in orders:
        _report(name, results[name])
    if ai_top:
        print(
            f"\nWłaściwe osoby na 1. stronie (top {PAGE}): ręczne = „{manual_best}”, "
            f"AI = „{ai_name}”.\n"
        )
        print("| gdzie | osób |")
        print("|---|---:|")
        for key, value in overlap.items():
            print(f"| {key} | {value} |")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=120)
    parser.add_argument("--rerank-top", type=int, default=0)
    parser.add_argument("--include-reviewed-evidence", action="store_true")
    parser.add_argument("--ai-top", type=int, default=0)
    args = parser.parse_args()
    asyncio.run(
        main(args.jobs, args.rerank_top, args.include_reviewed_evidence, args.ai_top)
    )
