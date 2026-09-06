"""Hybrid retrieval: BM25 (Postgres FTS) + dense (Voyage/Qdrant) + RRF fusion.

Research benchmark (2026): hybrid hits 91% recall@10 vs dense-only 78% / BM25-only
65%. We fuse with Reciprocal Rank Fusion (k=60), the de-facto standard for
ensembling retrievers with mismatched score scales.

Pipeline (jobs → candidates):
    1. BM25 over `candidates.fts_doc` (top 100)
    2. Dense Qdrant over `nexus_candidates` (top 100)
    3. RRF fusion → ordered list of candidate ids
    4. Voyage Rerank 2.5 on top 100 → top K (when feature flag on)

Same orchestrator works for jobs (CV → matching jobs) — pass a different
table/collection pair via the helpers.

Critical files reused:
- backend/app/api/search.py — already has FTS query helpers for candidates
- backend/app/services/embedding_service.py — search_candidates_semantic /
  search_jobs_semantic
- backend/app/services/reranker_service.py — Voyage Rerank 2.5 wrapper (Item 3)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# RRF constant — k=60 from the original RRF paper, robust to outlier ranks.
RRF_K = 60


@dataclass(frozen=True)
class HybridResult:
    """Outcome of a hybrid (BM25 + dense + RRF) retrieval.

    ``pairs`` is the ranked ``[(doc_id, score), ...]``. ``degraded`` is True when
    the dense (Voyage/Qdrant) leg FAILED for this request — the ranking then
    leans on BM25 alone, so a short or empty list must NOT be presented as
    "nothing matched" (it may be a provider outage). This is deliberately
    distinct from a healthy empty result (``degraded=False`` and ``pairs == []``),
    which really does mean "no candidates".
    """

    pairs: list[tuple[int, float]] = field(default_factory=list)
    degraded: bool = False
    # ── telemetria nogi BM25 ────────────────────────────────────────────────
    # `degraded` znaczy DOKŁADNIE „noga gęsta padła" i tak jest mapowane na
    # komunikat użytkownika w `api/search.py` („wyszukiwanie semantyczne
    # niedostępne"). Rozszerzenie go o awarie BM25 kazałoby aplikacji
    # twierdzić coś nieprawdziwego o Voyage/Qdrant, więc BM25 dostaje własne
    # pola. To jest naturalna „prosta" zmiana przy następnym refaktorze —
    # stąd ten komentarz zamiast samej nazwy.
    #
    #   bm25_hits is None  → nogi NIE pytano (brak `bm25_query`) — LEGALNE
    #   bm25_hits == 0     → pytano, nie trafiła w nikogo        — LEGALNE
    #   bm25_failed        → noga rzuciła                        — DEFEKT
    bm25_hits: Optional[int] = None
    bm25_failed: bool = False


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[int]], *, k: int = RRF_K
) -> list[tuple[int, float]]:
    """RRF over multiple ranked lists of doc ids.

    Returns [(doc_id, fused_score), ...] sorted desc. Score is sum of
    1/(k + rank_i) across rankings; ids absent from a list contribute 0.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# Sufit liczby terminów w jednej alternatywie. Cap ścina od końca, a `nice`
# idzie po `must` — więc przy przepełnieniu tracimy najpierw to, co mniej waży.
_BM25_TERM_CAP = 24
# Minimalna liczba znaków alfanumerycznych w terminie. Broni przed
# DEGENERACJĄ LEKSEMU, nie przed operatorami (od tych jest cudzysłów).
_BM25_MIN_ALNUM = 2


def bm25_or_query(terms: Iterable[str]) -> str:
    """Zbuduj wejście dla `websearch_to_tsquery` z listy terminów — ALTERNATYWA.

    Każdy termin idzie w cudzysłowie — nie dla estetyki, tylko dlatego, że
    cudzysłów jest JEDYNYM totalnym neutralizatorem operatorów websearch:
    `"-junior"` przestaje być NOT, `"or"` przestaje być OR, a termin
    wielowyrazowy staje się frazą (`'sql' <-> 'server'`) zamiast koniunkcji.
    Sprawdzone na Postgresie 16, nie wydedukowane.

    `"` MUSI wypaść z treści terminu: `'"a"b" or "java"'` parsuje się jako
    `'a' & 'b' & 'or' & 'java'` — jeden zabłąkany cudzysłów przywraca AND
    i cała alternatywa przestaje zwracać cokolwiek.

    NIE budujemy `to_tsquery`: rzuca `syntax error` na „sql server" i „c++",
    czyli na większości rodzin aliasów. `websearch_to_tsquery` jest totalna
    i produkuje DOKŁADNIE te lekseny, które `to_tsvector` zapisała w
    `fts_doc` (ta sama konfiguracja `simple`, ten sam parser) — dlatego
    dopasowanie działa bez replikowania parsera po stronie Pythona.
    `plainto_tsquery` odpada z tego samego powodu co dzisiejsze wejście: ANDuje.

    `_BM25_MIN_ALNUM` jest o degeneracji leksemu, nie o operatorach: „C++"
    i „C#" zapadają się do `'c'`, które trafia w każde CV z samotnym „C" — to
    nie sygnał, to zalew, więc taki termin odpada. „.NET" (→`'net'`),
    „node.js" i „or" przechodzą; „or" jest bezpieczne właśnie dlatego, że
    w cudzysłowie jest leksemem, a nie operatorem.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in terms:
        if not isinstance(raw, str):
            continue
        term = " ".join(raw.replace('"', " ").split())
        if sum(1 for ch in term if ch.isalnum()) < _BM25_MIN_ALNUM:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(f'"{term}"')
        if len(out) >= _BM25_TERM_CAP:
            break
    return " or ".join(out)


def build_job_bm25_query(job) -> str:
    """Terminy, których noga BM25 ma szukać dla tej oferty — ALTERNATYWA.

    Źródło jest CELOWO to samo, na którym warstwa `skills` liczy punkty
    (`_extract_skills_from_champion`). Gdyby pula pytała o inne umiejętności
    niż ranking, kandydat wpuszczony przez BM25 dostawałby zero za skills —
    pula i ranking spierałyby się o to, czego oferta wymaga.

    Rozwijamy RODZINY aliasów (`skill_name_variants`), nie zwijamy do nazwy
    kanonicznej: dane kandydatów NIE są kanonizowane. Pomiar z 2026-07-28
    (prod, 55 428 kandydatów) — rodzina „Microsoft SQL Server" żyje w bazie
    jako mssql=21, ms sql=18, sql server=18, microsoft sql server=9. Filtr po
    nazwie kanonicznej znajdował 9 z ponad 60. Terminy łączy ALTERNATYWA, więc
    rozwinięcie rodziny jest tu poprawne — przy AND byłoby żądaniem wszystkich
    pisowni naraz (od tego jest `skill_variant_groups`).

    Tytuł NIE wchodzi jako wolne tokeny: „Senior", „Developer", „Specjalista"
    w alternatywie trafiają w każde CV. Tytuł jest już złożony do środka przez
    `_extract_skills_from_champion` (Tier 3), ale WYŁĄCZNIE przez taksonomię —
    czyli jako umiejętności, nie jako proza.

    Pusty wynik ("") jest poprawną odpowiedzią: oferta bez umiejętności i bez
    Championa nie ma o co zapytać BM25. Wtedy hybryda degeneruje się do samego
    wektora, czyli do dzisiejszego zachowania produkcji.
    """
    from app.services.scoring_service import (  # noqa: PLC0415
        _extract_skills_from_champion,
        skill_name_variants,
    )

    terms = skill_name_variants(getattr(job, "must_skills", None))
    terms += skill_name_variants(getattr(job, "nice_skills", None))
    if not terms:
        terms = skill_name_variants(_extract_skills_from_champion(job))
    return bm25_or_query(terms)


async def bm25_candidates(
    db: AsyncSession, query: str, *, limit: int = 100
) -> list[int]:
    """Top-N candidate ids by Postgres ts_rank over `candidates.fts_doc`.

    ``query`` MUSI być ZAPYTANIEM, nie dokumentem. `websearch_to_tsquery`
    ANDuje słowa, więc podanie tu `_build_job_text(job)` (setki leksemów)
    zwraca ZERO wierszy dla każdej oferty i każdego kandydata — nie „mało",
    tylko zawsze zero, cicho i bez awarii. Wejście dla ścieżki ofertowej
    buduje :func:`build_job_bm25_query` / :func:`bm25_or_query`.
    """
    if not query or not query.strip():
        return []
    sql = text(
        """
        SELECT id
        FROM candidates
        WHERE fts_doc @@ websearch_to_tsquery('simple', :q)
        ORDER BY ts_rank(fts_doc, websearch_to_tsquery('simple', :q)) DESC,
                 updated_at DESC
        LIMIT :limit
        """
    ).bindparams(bindparam("q", value=query), bindparam("limit", value=limit))
    rows = (await db.execute(sql)).all()
    return [int(r[0]) for r in rows]


async def bm25_jobs(db: AsyncSession, query: str, *, limit: int = 100) -> list[int]:
    """Top-N job ids by Postgres ts_rank over `jobs.fts_doc`.

    Ta sama pułapka co w :func:`bm25_candidates`: ``query`` musi być
    zapytaniem, nie dokumentem.

    DŁUG (świadomy, zapisany, nie przemilczany): odwrotne dopasowanie
    (CV → oferty) nie ma dziś ŻADNEGO buildera terminów — odpowiednika
    `build_job_bm25_query` po stronie kandydata nie piszemy, bo `hybrid_jobs`
    i `bm25_jobs` nie mają dziś żadnego callera (odwrotne dopasowanie idzie
    przez `search_jobs_semantic`). Koszt dziś zerowy; builder bez konsumenta
    i bez pomiaru byłby spekulacją. Parametr `bm25_query` w `hybrid_jobs`
    istnieje po to, żeby następny caller nie odtworzył defektu przez
    przypadek — ale musi go WYPEŁNIĆ.
    """
    if not query or not query.strip():
        return []
    sql = text(
        """
        SELECT id
        FROM jobs
        WHERE fts_doc @@ websearch_to_tsquery('simple', :q)
        ORDER BY ts_rank(fts_doc, websearch_to_tsquery('simple', :q)) DESC,
                 updated_at DESC
        LIMIT :limit
        """
    ).bindparams(bindparam("q", value=query), bindparam("limit", value=limit))
    rows = (await db.execute(sql)).all()
    return [int(r[0]) for r in rows]


async def dense_candidates(
    query: str, *, limit: int = 100, raise_on_error: bool = False
) -> list[int]:
    """Top-N candidate ids from Qdrant dense semantic search.

    With ``raise_on_error=True`` a provider outage raises
    :class:`~app.services.embedding_service.SemanticSearchUnavailable` instead of
    being swallowed to ``[]`` — see :func:`hybrid_candidates`.
    """
    from app.services.embedding_service import search_candidates_semantic

    hits = await search_candidates_semantic(
        query, top_k=limit, raise_on_error=raise_on_error
    )
    return [int(h["candidate_id"]) for h in hits]


async def dense_jobs(
    query: str, *, limit: int = 100, raise_on_error: bool = False
) -> list[int]:
    """Top-N job ids from Qdrant dense semantic search."""
    from app.services.embedding_service import search_jobs_semantic

    hits = await search_jobs_semantic(query, top_k=limit, raise_on_error=raise_on_error)
    return [int(h["job_id"]) for h in hits]


async def _dense_ids_or_degraded(
    coro,
) -> tuple[list[int], bool]:
    """Await a dense-retrieval coroutine, converting a provider outage into a
    ``(ids, degraded)`` pair instead of propagating.

    Returns ``([], True)`` when the dense leg raised ``SemanticSearchUnavailable``
    so the surrounding ``asyncio.gather`` (with the BM25 leg) is never aborted —
    hybrid retrieval degrades to BM25-only while still flagging the outage.
    """
    from app.services.embedding_service import SemanticSearchUnavailable

    try:
        return await coro, False
    except SemanticSearchUnavailable as exc:
        logger.error("[Hybrid] dense retrieval unavailable — BM25-only: %s", exc)
        return [], True


async def _bm25_ids_or_failed(
    leg, db: AsyncSession, query: str, *, limit: int
) -> tuple[list[int], bool]:
    """Awaria BM25 nie może wywracać całego `gather` — lustro nogi gęstej.

    Dziś wyjątek z Postgresa przerywa `asyncio.gather`, więc trafienia gęste
    (już policzone, opłacone wywołaniem Voyage) lecą do kosza, a fasada woła
    Voyage DRUGI raz w ścieżce zapasowej. Po zmianie hybryda oddaje wynik
    dense-only z ``bm25_failed=True``, bez powtórki.

    ⚠️ NIEZMIENNIK, który trzyma testy uczciwymi: `leg` jest przekazywana
    W MIEJSCU WYWOŁANIA, więc globalna nazwa modułu (`bm25_candidates` /
    `bm25_jobs`) jest odczytywana DOPIERO w czasie wywołania. Tylko dzięki
    temu `monkeypatch.setattr(hybrid_search, "bm25_candidates", ...)`
    z `test_hybrid_search_degraded.py` dosięga produkcyjnej ścieżki. Nigdy nie
    wiązać tej funkcji przez `from ... import`, alias modułowy ani argument
    domyślny — testy zzielenieją wtedy na STUBIE, którego produkcja nie używa.
    """
    if not query or not query.strip():
        return [], False  # nogi nie pytano — to NIE jest awaria
    try:
        return await leg(db, query, limit=limit), False
    except Exception as exc:  # noqa: BLE001 — patrz docstring
        logger.error("[Hybrid] noga BM25 padła — dense-only: %s", exc)
        return [], True


def _bm25_pool_limit(pool: int) -> int:
    """Sufit członkostwa nogi BM25 w puli (zawór na zalew).

    Przy puli 1000 termin trafiający w dziesiątki tysięcy CV („java") mógłby
    zająć całą pulę i wypchnąć trafienia gęste — to jest mechanizm, który
    zabił pasaże CV (pomiar 2026-08-12: sufit −1,8 p.p. przy rosnących
    P@5/MRR). 200 = najwyżej 1/5 puli 1000, na pozycjach o wadze RRF ≤ 1/61.

    `HYBRID_BM25_POOL_LIMIT` JEST zadeklarowane w `core/config.py` (od 09.2026),
    więc pokrętło naprawdę działa: zmienna środowiskowa je przestawia. Wcześniej
    ten sam `getattr` czytał pole NIEISTNIEJĄCE — Pydantic wczytuje env wyłącznie
    dla pól zadeklarowanych, więc wartość była stała, mimo że kod wyglądał na
    konfigurowalny. `getattr` zostaje jako zabezpieczenie dla wywołań z podmienioną
    atrapą ustawień w testach, a nie dlatego, że pola brakuje.
    """
    from app.core.config import settings  # noqa: PLC0415

    return min(pool, int(getattr(settings, "HYBRID_BM25_POOL_LIMIT", 200)))


async def hybrid_candidates(
    db: AsyncSession,
    query: str,
    *,
    pool: int = 100,
    final_top_k: int = 20,
    use_rerank: Optional[bool] = None,
    bm25_query: Optional[str] = None,
) -> HybridResult:
    """Hybrid (BM25 + dense + RRF) candidate retrieval.

    Returns a :class:`HybridResult` carrying ``pairs`` = [(candidate_id, score),
    ...] and a ``degraded`` flag. When `use_rerank` is True (or None and
    settings.RERANKER_ENABLED is True), the top `pool` after RRF is re-ordered
    by Voyage rerank-2.5 — `score` then becomes the rerank score.

    If the dense (Voyage/Qdrant) leg is *down*, the ranking falls back to BM25
    alone and ``degraded=True`` so the API can tell the user "semantic search
    unavailable" instead of misreporting an outage as "no candidates".

    ``bm25_query`` (C12) rozdziela wejścia obu nóg, bo mają różne wymagania:
    noga gęsta chce DOKUMENTU (embedding), noga BM25 chce ZAPYTANIA.
      * ``None`` ⇒ noga BM25 dostaje ``query``. To zachowanie ręcznej
        wyszukiwarki (`api/search.py`), gdzie ``query`` NAPRAWDĘ jest
        zapytaniem rekrutera i AND na 2-4 słowach jest intencją, a ``-junior``
        udokumentowanym wykluczeniem.
      * ``""`` ⇒ nogi nie pytamy wcale. Lepsze niż nakarmienie jej dokumentem,
        bo dokument daje zawsze zero, tyle że wygląda jak działająca hybryda.
      * niepusty string ⇒ alternatywa terminów z `build_job_bm25_query`.
    """
    bm25_input = query if bm25_query is None else bm25_query
    bm25_asked = bool(bm25_input and bm25_input.strip())

    (bm25_ids, bm25_failed), (dense_ids, degraded) = await asyncio.gather(
        # `bm25_candidates` przekazywana W MIEJSCU WYWOŁANIA — patrz niezmiennik
        # w docstringu `_bm25_ids_or_failed`.
        _bm25_ids_or_failed(
            bm25_candidates, db, bm25_input, limit=_bm25_pool_limit(pool)
        ),
        _dense_ids_or_degraded(
            dense_candidates(query, limit=pool, raise_on_error=True)
        ),
    )

    def _result(pairs) -> HybridResult:
        # Jedno miejsce składania wyniku. Przy trzech osobnych
        # `return HybridResult(...)` nowe pole trafiłoby do dwóch z nich,
        # a trzecia gałąź milcząco oddawałaby wartości domyślne — czyli
        # telemetrię, która kłamie akurat w gałęzi rerankera.
        return HybridResult(
            pairs=list(pairs),
            degraded=degraded,
            bm25_hits=len(bm25_ids) if bm25_asked else None,
            bm25_failed=bm25_failed,
        )

    fused = reciprocal_rank_fusion([bm25_ids, dense_ids])
    if not fused:
        return _result([])

    cand_ids = [doc_id for doc_id, _ in fused[:pool]]

    # Resolve flag (allow caller override for testing).
    if use_rerank is None:
        from app.core.config import settings  # noqa: PLC0415

        use_rerank = bool(getattr(settings, "RERANKER_ENABLED", False))

    if not use_rerank:
        return _result(fused[:final_top_k])

    # Rerank: load minimal candidate text, send to cross-encoder.
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.candidate import Candidate  # noqa: PLC0415
    from app.services.embedding_service import _build_candidate_text  # noqa: PLC0415
    from app.services.reranker_service import rerank_or_passthrough  # noqa: PLC0415

    rows = (
        (await db.execute(select(Candidate).where(Candidate.id.in_(cand_ids))))
        .scalars()
        .all()
    )
    by_id = {c.id: c for c in rows}
    ordered = [by_id[cid] for cid in cand_ids if cid in by_id]
    docs = [_build_candidate_text(c)[:4000] for c in ordered]
    pairs = await rerank_or_passthrough(query, docs, top_k=final_top_k)

    # Map rerank pairs back to candidate ids.
    return _result([(ordered[idx].id, float(score)) for idx, score in pairs])


async def hybrid_jobs(
    db: AsyncSession,
    query: str,
    *,
    pool: int = 100,
    final_top_k: int = 20,
    use_rerank: Optional[bool] = None,
    bm25_query: Optional[str] = None,
) -> HybridResult:
    """Hybrid retrieval for jobs (e.g. CV-upload-preview reverse matching).

    Same contract as :func:`hybrid_candidates`: returns a :class:`HybridResult`
    whose ``degraded`` flag is True when the dense leg was down (BM25-only
    fallback), so an outage is never mistaken for "no matching jobs".

    ``bm25_query`` jak w :func:`hybrid_candidates`. Ta funkcja nie ma dziś
    żadnego callera, więc domyślna ``None`` (= „użyj ``query``") zachowuje
    dzisiejsze zachowanie zamiast go zmieniać w ciemno — ale pierwszy caller,
    który poda tu dokument CV, dostanie zero trafień BM25. Patrz dług opisany
    w :func:`bm25_jobs`.
    """
    bm25_input = query if bm25_query is None else bm25_query
    bm25_asked = bool(bm25_input and bm25_input.strip())

    (bm25_ids, bm25_failed), (dense_ids, degraded) = await asyncio.gather(
        _bm25_ids_or_failed(bm25_jobs, db, bm25_input, limit=_bm25_pool_limit(pool)),
        _dense_ids_or_degraded(dense_jobs(query, limit=pool, raise_on_error=True)),
    )

    def _result(pairs) -> HybridResult:
        return HybridResult(
            pairs=list(pairs),
            degraded=degraded,
            bm25_hits=len(bm25_ids) if bm25_asked else None,
            bm25_failed=bm25_failed,
        )

    fused = reciprocal_rank_fusion([bm25_ids, dense_ids])
    if not fused:
        return _result([])

    job_ids = [doc_id for doc_id, _ in fused[:pool]]

    if use_rerank is None:
        from app.core.config import settings  # noqa: PLC0415

        use_rerank = bool(getattr(settings, "RERANKER_ENABLED", False))

    if not use_rerank:
        return _result(fused[:final_top_k])

    from sqlalchemy import select  # noqa: PLC0415

    from app.models.job import Job  # noqa: PLC0415
    from app.services.embedding_service import _build_job_text  # noqa: PLC0415
    from app.services.reranker_service import rerank_or_passthrough  # noqa: PLC0415

    rows = (await db.execute(select(Job).where(Job.id.in_(job_ids)))).scalars().all()
    by_id = {j.id: j for j in rows}
    ordered = [by_id[jid] for jid in job_ids if jid in by_id]
    docs = [_build_job_text(j)[:4000] for j in ordered]
    pairs = await rerank_or_passthrough(query, docs, top_k=final_top_k)
    return _result([(ordered[idx].id, float(score)) for idx, score in pairs])
