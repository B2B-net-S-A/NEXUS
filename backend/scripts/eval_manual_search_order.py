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

* ``--weights semantic=60,skills=30,location=5[,threshold=70]`` (21.10.2026)
  — pomiar szkicu wag z panelu „Ranking kandydatów”: opublikowane wagi
  i szkic na tych samych zamkniętych rekrutacjach, kolejność produkcji
  (wektor „Dop.” → 200 pierwszych wg „Dop.”). Ten sam kod co zadanie w tle
  z trasy ``POST /api/scoring-weights/panel/measurements``
  (``services/ranking_lab.py``).

Nic nie zapisuje: wektor zapytania idzie prosto do Voyage (bez tabeli
``embedding_cache``), baza w ``SET TRANSACTION READ ONLY``::

    cd /app && python -m scripts.eval_manual_search_order --jobs 120
    cd /app && python -m scripts.eval_manual_search_order --weights skills=30
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
    head = ordered[:top]
    if not head:
        return ordered
    score = await _fit_scores(db, context, head, reviewed=reviewed)
    position = {cid: i for i, cid in enumerate(head)}
    reranked = sorted(head, key=lambda cid: (-score.get(cid, -1.0), position[cid]))
    return reranked + ordered[top:]


_CITY_SPLIT = re.compile(r"[/,;|\n]+|\s+(?:lub|albo|or|i|and)\s+", re.IGNORECASE)
_NOT_CITY = {
    "zdalnie",
    "zdalna",
    "remote",
    "hybryda",
    "hybrydowo",
    "hybrid",
    "stacjonarnie",
    "onsite",
    "on-site",
    "biuro",
    "polska",
    "poland",
    "pl",
    "cała polska",
}


def _job_cities(location: str | None) -> list[str]:
    """Uproszczone lustro ``parseJobLocationCities`` (front) — miasta rekrutacji,
    które „Szukaj w bazie” wysyła jako „Mile widziane”."""
    if not location:
        return []
    cities: list[str] = []
    for part in _CITY_SPLIT.split(re.sub(r"\([^)]*\)", " ", location)):
        city = part.strip()
        if not city or city.lower() in _NOT_CITY or any(ch.isdigit() for ch in city):
            continue
        if city.lower() not in {c.lower() for c in cities}:
            cities.append(city)
        if len(cities) >= 5:
            break
    return cities


async def _preferred_points(db, job, ids: list[int], must_words) -> tuple[dict, dict]:
    """Punkty grup „Mile widziane” jak w ``api.candidates._preferred_rank``:
    +1 za każde słowo must spoza wycinających, +1 za którekolwiek miasto
    rekrutacji, +1 za kategorię. Zwraca (dziś: must+miasto+kategoria, B: must)."""
    from sqlalchemy import case, cast, func, literal, literal_column, or_
    from sqlalchemy.dialects.postgresql import TSQUERY

    from app.models.candidate import Candidate
    from app.services import candidate_search_predicates as predicates

    must_parts = []
    for query, variants in must_words:
        tsq = func.to_tsquery("simple", query)
        if variants:
            tsq = tsq.op("||")(cast(literal(variants), TSQUERY))
        must_parts.append(
            case((literal_column("candidates.keyword_fts").op("@@")(tsq), 1), else_=0)
        )
    place_parts = []
    cities = _job_cities(job.location)
    if cities:
        place_parts.append(
            case((or_(*predicates.city_match_clauses(cities)), 1), else_=0)
        )
    if job.competence_category_id:
        clause = predicates.competence_category_clause(
            [job.competence_category_id], predicates.semantics_for("list", 2, False)
        )
        if clause is not None:
            place_parts.append(case((clause, 1), else_=0))
    zero = literal(0)
    must_sum = sum(must_parts[1:], must_parts[0]) if must_parts else zero
    place_sum = sum(place_parts[1:], place_parts[0]) if place_parts else zero
    today: dict[int, int] = {}
    must_only: dict[int, int] = {}
    for start in range(0, len(ids), 5000):
        chunk = ids[start : start + 5000]
        rows = (
            await db.execute(
                select(Candidate.id, must_sum, place_sum).where(Candidate.id.in_(chunk))
            )
        ).all()
        for cid, m, p in rows:
            must_only[int(cid)] = int(m or 0)
            today[int(cid)] = int(m or 0) + int(p or 0)
    return today, must_only


async def _grouped_then_fit(
    db, context, vector_order: list[int], groups: dict, top: int, *, reviewed: bool
) -> list[int]:
    """Kolejność produkcji „Szukaj w bazie”: grupy malejąco (stabilnie po
    wektorze — jak ``order_rows``), potem ``rerank_within_groups`` pełnym „Dop.”."""
    from app.services.candidate_match_order import rerank_within_groups

    ordered = sorted(vector_order, key=lambda cid: -groups.get(cid, 0))
    fits = await _fit_scores(db, context, ordered[:top], reviewed=reviewed)
    return rerank_within_groups(ordered, groups, fits, top)


async def _fit_scores(
    db, context, head: list[int], *, reviewed: bool = False
) -> dict[int, float]:
    from app.models.candidate import Candidate
    from app.services import requirement_verification as rv
    from app.services.canonical_fit import score_candidates

    if not head:
        return {}
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
    return {
        int(f.breakdown.candidate_id): f.fit_score
        for f in fits
        if f.fit_score is not None
    }


async def main(
    max_jobs: int,
    rerank_top: int = 0,
    reviewed: bool = False,
    ai_top: int = 0,
    groups: bool = False,
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
    # 19.10.2026 (zgłoszenie „najpierw najbardziej dopasowani”): dzisiejsze
    # grupy „Mile widziane” przed „Dop.” vs grupy tylko po must vs sam „Dop.”
    # (= orders[5]). Wycinają dwa pierwsze must (jak krytyczne), reszta must
    # to wiersze „Mile widziane”.
    groups_today = f"dziś: grupy must+miasto+kategoria → top {rerank_top} wg Dop."
    groups_must = f"B: grupy must → top {rerank_top} wg Dop."
    if groups and rerank_top:
        orders += [groups_today, groups_must]
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
                if len(words) == 10:
                    break
            if len(words) < 2:
                continue
            words, extra_must = words[:2], words[2:]
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
            if groups and rerank_top:
                today_pts, must_pts = await _preferred_points(db, job, ids, extra_must)
                ranked[groups_today] = await _grouped_then_fit(
                    db,
                    context,
                    ranked[orders[2]],
                    today_pts,
                    rerank_top,
                    reviewed=reviewed,
                )
                ranked[groups_must] = await _grouped_then_fit(
                    db,
                    context,
                    ranked[orders[2]],
                    must_pts,
                    rerank_top,
                    reviewed=reviewed,
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


def _parse_weights(raw: str, published: dict) -> dict:
    values = dict(published)
    for part in raw.split(","):
        if not part.strip():
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        if name not in values:
            raise SystemExit(
                f"nieznana waga {name!r} — dozwolone: {', '.join(sorted(values))}"
            )
        values[name] = int(value)
    return values


async def measure_weights(raw: str, max_jobs: int) -> None:
    """Szkic z ``--weights`` kontra opublikowane — miary panelu."""
    from app.core.database import AsyncSessionLocal
    from app.services import ranking_lab
    from app.services import ranking_weights as rw
    from app.services.ranking_publish import current_baseline

    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        baseline = await current_baseline(db)
    draft = rw.PanelWeights.from_dict(_parse_weights(raw, baseline["panel"]))
    error = rw.validation_error(draft)
    if error:
        raise SystemExit(error)

    async def progress(done: int, target: int) -> None:
        print(f"\r{done}/{target}", end="", flush=True)

    result = await ranking_lab.measure(
        baseline["weights"],
        float(baseline["threshold"]),
        draft,
        target=max_jobs,
        progress=progress,
    )
    print(
        f"\n\nRekrutacje: {result['jobs']}, czas {result['duration_s']} s; "
        f"opublikowane {baseline['panel']} → szkic {draft.as_dict()}\n"
    )
    print("| miara | teraz | szkic |")
    print("|---|---:|---:|")
    for key in ("page1_hit", "median_first", "top50_share", "mrr", "proposals"):
        print(f"| {key} | {result['before'][key]} | {result['after'][key]} |")
    print(
        f"\nNajwiększy spadek: {result['max_drop_pt']} pkt; "
        f"powód wymagany: {result['needs_reason']}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=120)
    parser.add_argument("--rerank-top", type=int, default=0)
    parser.add_argument("--include-reviewed-evidence", action="store_true")
    parser.add_argument("--ai-top", type=int, default=0)
    parser.add_argument(
        "--groups",
        action="store_true",
        help="dziś (grupy „Mile widziane”) i B (grupy must) obok samego „Dop.” — wymaga --rerank-top",
    )
    parser.add_argument(
        "--weights",
        default="",
        help="szkic panelu, np. semantic=60,skills=30,location=5,threshold=70 — "
        "pomiar szkicu kontra opublikowane (zamknięte rekrutacje)",
    )
    args = parser.parse_args()
    if args.weights:
        asyncio.run(measure_weights(args.weights, args.jobs))
        raise SystemExit(0)
    asyncio.run(
        main(
            args.jobs,
            args.rerank_top,
            args.include_reviewed_evidence,
            args.ai_top,
            args.groups,
        )
    )
