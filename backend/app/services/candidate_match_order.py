"""Kolejność „Dopasowanie” listy kandydatów (``sort=match``).

Audyt 25.09.2026 (test na 120 rekrutacjach z ostatnich 24 miesięcy): przy
„najnowsi” pierwsza strona wyszukiwania ręcznego zawierała osobę, którą zespół
potem zweryfikował, w 33% rekrutacji. Ułożenie TYCH SAMYCH wyników według
podobieństwa wektora rekrutacji do wektorów kandydatów — 83%
(``scripts/eval_manual_search_order.py``). Filtr się nie zmienia, zmienia się
tylko kolejność.

Wektor:

* „Szukaj ręcznie” (jedna rekrutacja + ``recruitment_match=not_assigned``) —
  ``request_vector(build_request_context(job, profile).query_text)``, ten sam
  co kolumna „Dop.” (``/api/search/candidates/scores``), więc kolejność zgadza
  się z liczbami w kolumnie;
* lista z wierszami wymagań — wektor zapytania z samych słów wymagań.

Kolejność (decyzje Artura 25.09.2026): „Mile widziane” najpierw, potem osoby
z danymi przed osobami z brakami (jak przy każdym sortowaniu), potem osoby
z wektorem według podobieństwa, na końcu reszta od najnowszych.

Podobieństwo liczy Qdrant (wyszukiwanie dokładne z filtrem po id, paczki po
``_CHUNK``). Zbiór większy niż ``MAX_EXACT_IDS`` (np. cała baza w „Szukaj
ręcznie” bez wymagań) dostaje ``ANN_TOP`` najbliższych z indeksu, reszta idzie
od najnowszych. Gotowa kolejność trzymana ``CACHE_TTL_SECONDS`` (najwyżej
``CACHE_MAX_ENTRIES`` wpisów) — bez tego
kolejne strony mogłyby się przetasować. Awaria Voyage/Qdranta = ``None``
(wołający wraca do „najnowsi” i mówi to w odpowiedzi); taki wynik nie trafia
do pamięci.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MAX_EXACT_IDS = 30_000
ANN_TOP = 3_000
_CHUNK = 5_000
# Wektor zapytania to dodatek do kolejności, nigdy bramka: wiszący Voyage
# (klient HTTP ma 60 s) wywracał listę po 30 s przeglądarki zamiast dać
# „najnowsi” (runda 6 audytu).
QUERY_VECTOR_TIMEOUT_SECONDS = 3.0
CACHE_TTL_SECONDS = 300
# Własna, OGRANICZONA pamięć: kolejność bywa listą ~60 tys. id (cała baza
# w „Szukaj ręcznie”), a klucz zmienia się przy każdym ruchu w rekrutacji.
# `app/core/cache.py` nie ma limitu ani sprzątania wygasłych wpisów, więc
# porzucone klucze zostawałyby w procesie do restartu (przegląd PR 25.09.2026).
CACHE_MAX_ENTRIES = 32
_order_cache: OrderedDict[str, tuple[float, tuple[int, ...]]] = OrderedDict()


def _cache_get(key: str) -> Optional[tuple[int, ...]]:
    hit = _order_cache.get(key)
    if hit is None:
        return None
    expires, ordered = hit
    if expires <= time.monotonic():
        del _order_cache[key]
        return None
    _order_cache.move_to_end(key)
    return ordered


def _cache_set(key: str, ordered: tuple[int, ...]) -> None:
    now = time.monotonic()
    for stale in [k for k, (expires, _) in _order_cache.items() if expires <= now]:
        del _order_cache[stale]
    _order_cache[key] = (now + CACHE_TTL_SECONDS, ordered)
    _order_cache.move_to_end(key)
    while len(_order_cache) > CACHE_MAX_ENTRIES:
        _order_cache.popitem(last=False)


def clear_cache() -> None:
    _order_cache.clear()


@dataclass(frozen=True)
class MatchVector:
    vector: list[float]
    key: str
    kind: str  # "job" | "rows"


def job_scope(filters: Any) -> Optional[int]:
    """Rekrutacja „Szukaj ręcznie” — dokładnie jedna i kierunek „nie w niej”."""
    ids = list(getattr(filters, "recruitment_id", None) or [])
    if len(ids) == 1 and getattr(filters, "recruitment_match", None) == "not_assigned":
        return int(ids[0])
    return None


def requirement_words(filters: Any, q_any_groups: Sequence[Sequence[str]]) -> str:
    """Tekst wektora zapytania z wierszy wymagań (bez „Wyklucz”)."""
    words: list[str] = []
    for group in q_any_groups or []:
        words.extend(group)
    for field in ("q_all", "q_any"):
        words.extend(getattr(filters, field, None) or [])
    cleaned = [" ".join(str(w).replace("*", " ").split()) for w in words]
    return " ".join(dict.fromkeys(w for w in cleaned if w))


async def resolve_vector(
    db: AsyncSession, user: Any, filters: Any, q_any_groups: Sequence[Sequence[str]]
) -> Optional[MatchVector]:
    """Wektor dla kolejności albo ``None`` (brak kontekstu, brak dostępu, awaria)."""
    from app.services.full_search_measurement import request_vector

    job_id = job_scope(filters)
    if job_id is not None:
        from fastapi import HTTPException

        from app.api.candidate_search import _authorized_job
        from app.services.request_matching_context import build_request_context
        from app.services.scoring_service import resolve_active_profile

        try:
            job = await _authorized_job(db, user, job_id)
        except HTTPException:
            return None
        profile = await resolve_active_profile(
            db, user_id=getattr(user, "id", None), client_id=job.client_id
        )
        text = build_request_context(job, profile).query_text
        kind = "job"
    else:
        text = requirement_words(filters, q_any_groups)
        kind = "rows"
    if not text:
        return None
    try:
        vector = await asyncio.wait_for(
            request_vector(text), timeout=QUERY_VECTOR_TIMEOUT_SECONDS
        )
    except Exception as exc:  # noqa: BLE001 — kolejność to dodatek, nie bramka
        logger.warning("match order: query vector failed (%s)", type(exc).__name__)
        return None
    if not vector:
        return None
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    return MatchVector(vector=vector, key=f"{kind}:{job_id or ''}:{digest}", kind=kind)


def _qdrant_scores(vector: list[float], ids: list[int]) -> dict[int, float]:
    """Blokujące: podobieństwo dla ``ids`` (dokładne, paczkami) albo ANN."""
    from qdrant_client.models import (
        Filter,
        HasIdCondition,
        QuantizationSearchParams,
        SearchParams,
    )

    from app.services import embedding_service as embeddings

    client = embeddings._get_qdrant_client()
    if client is None:
        raise RuntimeError("Vector store unavailable")
    try:
        scores: dict[int, float] = {}
        if len(ids) > MAX_EXACT_IDS:
            allowed = set(ids)
            hits = client.search(
                collection_name=embeddings._collection(),
                query_vector=vector,
                limit=ANN_TOP,
                with_payload=False,
                with_vectors=False,
            )
            return {int(h.id): float(h.score) for h in hits if int(h.id) in allowed}
        for start in range(0, len(ids), _CHUNK):
            chunk = ids[start : start + _CHUNK]
            hits = client.search(
                collection_name=embeddings._collection(),
                query_vector=vector,
                query_filter=Filter(must=[HasIdCondition(has_id=chunk)]),
                search_params=SearchParams(
                    exact=True, quantization=QuantizationSearchParams(ignore=True)
                ),
                limit=len(chunk),
                with_payload=False,
                with_vectors=False,
            )
            scores.update({int(h.id): float(h.score) for h in hits})
        return scores
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


def order_rows(
    rows: Sequence[tuple[int, float, float, float]], scores: dict[int, float]
) -> list[int]:
    """``rows`` = (id, mile_widziane, braki, znacznik_czasu_dodania).

    „Mile widziane” malejąco, braki rosnąco, osoby z wektorem przed resztą,
    podobieństwo malejąco, najnowsi, id malejąco (stabilnie jak „najnowsi”).
    """

    def key(row: tuple[int, float, float, float]):
        cid, preferred, unknown, created = row
        score = scores.get(cid)
        return (
            -preferred,
            unknown,
            0 if score is not None else 1,
            -(score or 0.0),
            -created,
            -cid,
        )

    return [row[0] for row in sorted(rows, key=key)]


async def _cache_key(db: AsyncSession, filters: Any, vector_key: str, user: Any) -> str:
    from app.models.recruitment_pipeline import CandidateStage

    payload = filters.model_dump(mode="json", exclude={"page", "sort"})
    salt = ""
    job_id = job_scope(filters)
    if job_id is not None:
        # Osoba dodana do rekrutacji znika z „Szukaj ręcznie” od razu, nie po TTL.
        last_stage = await db.scalar(
            select(func.max(CandidateStage.id)).where(CandidateStage.job_id == job_id)
        )
        salt = str(last_stage or 0)
    raw = json.dumps(
        [payload, vector_key, getattr(user, "id", None), salt],
        sort_keys=True,
        default=str,
    )
    return "candidate-match-order:" + hashlib.sha256(raw.encode()).hexdigest()


async def ordered_ids(
    db: AsyncSession,
    user: Any,
    filters: Any,
    ids_query,
    q_any_groups: Sequence[Sequence[str]],
    prefix: Sequence[Any],
) -> Optional[list[int]]:
    """Pełna kolejność identyfikatorów albo ``None`` (wołający: „najnowsi”).

    ``ids_query`` — przefiltrowany ``select(Candidate.id)``; ``prefix`` — dwa
    wyrażenia SQL („Mile widziane”, braki danych) albo ``None`` w ich miejscu.
    """
    from app.models.candidate import Candidate
    from app.services import embedding_service as embeddings

    match_vector = await resolve_vector(db, user, filters, q_any_groups)
    if match_vector is None:
        return None
    key = await _cache_key(db, filters, match_vector.key, user)
    cached = _cache_get(key)
    if cached is not None:
        return list(cached)

    preferred_expr, unknown_expr = prefix
    columns = [
        Candidate.id,
        preferred_expr if preferred_expr is not None else literal(0),
        unknown_expr if unknown_expr is not None else literal(0),
        func.extract("epoch", Candidate.created_at),
    ]
    rows = [
        (int(r[0]), float(r[1] or 0), float(r[2] or 0), float(r[3] or 0))
        for r in (await db.execute(ids_query.with_only_columns(*columns))).all()
    ]
    if not rows:
        return []
    ids = [r[0] for r in rows]
    try:
        scores = await embeddings._run_qdrant(
            lambda: _qdrant_scores(match_vector.vector, ids)
        )
    except Exception as exc:  # noqa: BLE001 — awaria = „najnowsi” z komunikatem
        logger.warning("match order: qdrant failed (%s)", type(exc).__name__)
        return None
    ordered = order_rows(rows, scores)
    _cache_set(key, tuple(ordered))
    return ordered
