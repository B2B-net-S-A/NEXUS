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

Ułożenie „Dop.” w „Szukaj ręcznie” (26.09.2026): samo podobieństwo wektorów
nie zgadzało się z kolumną „Dop.” (tylko 10 z 19 sąsiednich par na stronie
malało według „Dop.”). Test na 120 rekrutacjach: ułożenie pierwszych 100 osób
pełną oceną (``canonical_fit.score_candidates``, ta sama co
``/api/search/candidates/scores``) podniosło MRR z 0,283 do 0,472, kosztem
~160 ms dla 100 i ~350 ms dla 200 osób. Reguła: pierwsze
``CANDIDATE_MATCH_RERANK_TOP`` osób (0 = wyłączone) układa się według
``fit_score`` malejąco WYŁĄCZNIE w obrębie grup („Mile widziane”, braki
danych) — grupy zostają w swojej kolejności; osoby bez pomiaru idą na koniec
grupy, remisy zostają w kolejności wektorowej, reszta listy bez zmian.
Awaria oceny = kolejność wektorowa (ostrzeżenie w logu). Lista z wierszami
wymagań nie ma rekrutacji, więc nie ma czym liczyć „Dop.” — zostaje wektor.
Odcisk kontekstu (``RequestMatchingContext.fingerprint``, w tym wagi profilu)
wchodzi do klucza pamięci.
"""

from __future__ import annotations

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
    # `RequestMatchingContext` rekrutacji (tylko `kind == "job"`) — to z nim
    # liczy się „Dop.” przy układaniu początku listy.
    context: Optional[Any] = None


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
        context = build_request_context(job, profile)
        text = context.query_text
        kind = "job"
    else:
        context = None
        text = requirement_words(filters, q_any_groups)
        kind = "rows"
    if not text:
        return None
    try:
        vector = await request_vector(text)
    except Exception as exc:  # noqa: BLE001 — kolejność to dodatek, nie bramka
        logger.warning("match order: query vector failed (%s)", type(exc).__name__)
        return None
    if not vector:
        return None
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    return MatchVector(
        vector=vector,
        key=f"{kind}:{job_id or ''}:{digest}",
        kind=kind,
        context=context,
    )


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


def rerank_within_groups(
    order: Sequence[int],
    group_of: dict[int, Any],
    score_of: dict[int, Optional[float]],
    top: int,
) -> list[int]:
    """Pierwsze ``top`` id ułożone według oceny w obrębie grup, reszta bez zmian.

    Grupa to ciągły odcinek ``order`` o tym samym ``group_of`` (``order_rows``
    sortuje najpierw po grupie), więc grupy nie zamieniają się miejscami. W
    grupie: ocena malejąco, osoby bez oceny (``None`` / brak klucza) na końcu,
    remisy w dotychczasowej kolejności.
    """
    head = list(order[: max(top, 0)])
    position = {cid: i for i, cid in enumerate(head)}

    def key(cid: int):
        score = score_of.get(cid)
        return (score is None, -(score or 0.0), position[cid])

    result: list[int] = []
    start = 0
    while start < len(head):
        group = group_of.get(head[start])
        end = start + 1
        while end < len(head) and group_of.get(head[end]) == group:
            end += 1
        result.extend(sorted(head[start:end], key=key))
        start = end
    return result + list(order[len(head) :])


async def _fit_scores(
    db: AsyncSession, context: Any, ids: Sequence[int]
) -> dict[int, Optional[float]]:
    """``fit_score`` („Dop.”) dla ``ids`` — jak ``POST /candidates/scores``."""
    from app.models.candidate import Candidate
    from app.services import canonical_fit

    # Klucze tożsamości, nie atrybuty: obiekt wygasły po commicie przy
    # odczycie `.id` ładowałby się leniwie (async = błąd).
    already_loaded = {
        key[1][0] for key in db.sync_session.identity_map.keys() if key[0] is Candidate
    }
    candidates = list(
        (await db.execute(select(Candidate).where(Candidate.id.in_(list(ids)))))
        .scalars()
        .all()
    )
    try:
        fits = await canonical_fit.score_candidates(db, context, candidates)
    finally:
        # Wiersze bez relacji listy nie mogą zostać w sesji: strona ładuje te
        # same osoby z `_candidate_list_options()`, a obiekt już obecny
        # w sesji mógłby wrócić bez nich (leniwe ładowanie w async = błąd).
        # Obiektów, które ktoś załadował wcześniej, nie ruszamy.
        for candidate in candidates:
            if candidate.id not in already_loaded and candidate in db:
                db.expunge(candidate)
    return {int(fit.breakdown.candidate_id): fit.fit_score for fit in fits}


async def _cache_key(
    db: AsyncSession,
    filters: Any,
    vector_key: str,
    user: Any,
    fingerprint: Optional[str] = None,
    rerank_top: int = 0,
) -> str:
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
        [
            payload,
            vector_key,
            getattr(user, "id", None),
            salt,
            fingerprint,
            rerank_top,
        ],
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
    from app.core.config import settings
    from app.models.candidate import Candidate
    from app.services import embedding_service as embeddings

    match_vector = await resolve_vector(db, user, filters, q_any_groups)
    if match_vector is None:
        return None
    context = match_vector.context if match_vector.kind == "job" else None
    rerank_top = int(settings.CANDIDATE_MATCH_RERANK_TOP or 0) if context else 0
    key = await _cache_key(
        db,
        filters,
        match_vector.key,
        user,
        getattr(context, "fingerprint", None),
        rerank_top,
    )
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
    if rerank_top > 0:
        head = ordered[:rerank_top]
        try:
            # Savepoint: błąd SQL w ocenie nie może zepsuć transakcji, na
            # której wołający ładuje zaraz stronę.
            async with db.begin_nested():
                fits = await _fit_scores(db, context, head)
            groups = {row[0]: (row[1], row[2]) for row in rows}
            ordered = rerank_within_groups(ordered, groups, fits, rerank_top)
        except Exception as exc:  # noqa: BLE001 — ocena to dodatek, nie bramka
            logger.warning("match order: fit rerank failed (%s)", type(exc).__name__)
    _cache_set(key, tuple(ordered))
    return ordered
