import time
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateSearchAccess, user_has_candidate_read
from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.competence_category import CompetenceCategory
from app.models.contact import Contact
from app.models.job import Job
from app.models.match_score import CandidateJobMatchScore
from app.models.recruitment_pipeline import CandidateStage
from app.schemas.candidate_search import (
    CandidateSearchItem,
    CandidateSearchRequest,
    CandidateSearchResponse,
    CompetenceCategoryFacet,
    MatchScoresRequest,
    MatchScoresResponse,
    SearchDiagnosticsResponse,
    SearchFacets,
    SearchMeta,
    WaterfallStage,
)
from app.services.match_score_cache import fresh_score_conditions
from app.services.advanced_candidate_search import build_advanced_filter
from app.services.ai_health import ai_status
from app.services.candidate_profile_rate import canonical_profile_rate_amount
from app.services.client_access import resolve_client_visible_client_ids
from app.services.client_identity import (
    client_display_name,
    client_display_name_expression,
    resolve_visible_client,
    visible_client_predicates,
)
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)
from app.services.structured_candidate_search import (
    build_filter_groups,
    build_structured_filter,
    experience_soft_rank,
    location_soft_rank,
    skills_soft_rank,
)

router = APIRouter()


# Ile osób ogląda tryb semantyczny na jedno zapytanie. To jest SUFIT WYNIKU,
# nie tylko szczegół retrievalu: `total` w trybie hybrydowym nigdy nie przekroczy
# tej liczby, bo zbiór wynikowy jest przecięciem puli z filtrami. Zmiana tej
# wartości zmienia więc to, co rekruter widzi jako „liczbę wyników" — i koszt
# rerankera Voyage, który dostaje CAŁĄ pulę przy KAŻDYM żądaniu strony.
#
# Ten koszt jest większy, niż sugeruje konfiguracja: komentarz przy
# `RERANKER_ENABLED` budżetuje „~595 ms p95", ale docstring `reranker_service`
# mówi, że ta liczba dotyczy ~50 dokumentów. Przy 200 wysyłamy czterokrotność
# tego budżetu, do 200 pełnych wierszy ORM i do 800 KB tekstu — i płacimy to
# ponownie przy każdej zmianie strony, bo endpoint jest BEZSTANOWY. Dawny
# komentarz przy wywołaniu twierdził, że zapas 200 „oszczędza odpytywanie
# orchestratora przy zmianie strony"; nie oszczędza — nie ma czego zapamiętać
# między żądaniami.
#
# Czy 200 wygrywa ze 100, wie wyłącznie pomiar (`scripts/eval_matching.py`),
# a nie ten komentarz. Dlatego wartość jest teraz POKRĘTŁEM, nie stałą wbitą
# w kod: da się ją przestawić zmienną środowiskową i zmierzyć obie, bez deployu.
_HYBRID_POOL_DEFAULT = 200


def _hybrid_pool_size() -> int:
    from app.core.config import settings  # noqa: PLC0415

    # Wartość bezsensowna (0, ujemna, `None`) wraca do DOMYŚLNEJ, nie do 1.
    # Pierwsza wersja robiła `max(1, raw or 200)`, co dawało dwa różne
    # zachowania dla dwóch równie bezsensownych wejść: `0` → 200 (bo `or`
    # zwierał się przed `max`), a `-5` → 1. Pula równa 1 nie jest zresztą
    # sensowniejsza od zera — wyszukiwarka oglądałaby jedną osobę i wyglądałoby
    # to jak pusta baza, czyli ta sama pomyłka, przed którą broni
    # `search_degraded`.
    raw = getattr(settings, "SEARCH_HYBRID_POOL_SIZE", _HYBRID_POOL_DEFAULT)
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return _HYBRID_POOL_DEFAULT
    return parsed if parsed > 0 else _HYBRID_POOL_DEFAULT


def _can_read_section(user: Any, section: ProductSection) -> bool:
    """Non-raising section check for a mixed-entity search response."""

    return section_access_for_user(user, section) >= SectionAccess.read


def _apply_client_visibility(statement: Any, column: Any, client_ids: Any) -> Any:
    """Apply the canonical client graph; an empty graph is authoritative."""

    if client_ids is None:
        return statement
    return statement.where(column.in_(sorted(client_ids) or [-1]))


def _fts_clause(q: str) -> Any:
    """Match candidates whose ``fts_doc`` matches the user query.

    Uses ``websearch_to_tsquery`` (postgres 11+) so the user can pass natural
    multi-word input like ``"python fastapi -junior"`` without learning the
    raw tsquery syntax.
    """
    return text("fts_doc @@ websearch_to_tsquery('simple', :q)").bindparams(q=q)


def _fts_rank_order() -> Any:
    """ORDER BY fragment: ts_rank weighted with recency decay, descending.

    ``text()`` returns a ``TextClause`` which has no ``.desc()`` accessor,
    so we inline ``DESC`` in the SQL string and pass the clause directly
    to ``select.order_by``.
    """
    return text(
        "ts_rank(fts_doc, websearch_to_tsquery('simple', :q)) * 0.7"
        " + 1.0 / (1.0 + EXTRACT(epoch FROM (now() - candidates.updated_at))"
        " / 86400.0) * 0.3 DESC"
    )


def _candidate_to_item(c: Candidate, score: float) -> CandidateSearchItem:
    profile_rate = canonical_profile_rate_amount(
        c.expected_rate_hourly,
        c.expected_rate_currency,
    )
    return CandidateSearchItem(
        id=c.id,
        name=c.name,
        lastname=c.lastname,
        email=c.email,
        phone=c.phone,
        location=c.location,
        status=c.status.value if c.status else None,
        availability_status=(
            c.availability_status.value if c.availability_status else None
        ),
        source=c.source,
        competence_category=c.competence_category,
        competence_category_id=c.competence_category_id,
        expected_rate_hourly=profile_rate,
        availability_date=c.availability_date.isoformat()
        if c.availability_date
        else None,
        years_it_experience=c.years_it_experience,
        tags=c.tags,
        skills=c.skills,
        languages=c.languages,
        ai_summary=c.ai_summary,
        avatar_url=c.avatar_url,
        relevance_score=score,
        has_cv=bool(c.cv_filename),
        has_linkedin=bool(c.linkedin),
        is_champion=bool(c.champion),
        created_at=c.created_at.isoformat() if c.created_at else None,
        updated_at=c.updated_at.isoformat() if c.updated_at else None,
    )


async def _competence_facets(
    db: AsyncSession, candidate_filter: Any
) -> list[CompetenceCategoryFacet]:
    """Aggregate counts per competence category across the filtered set.

    The ``candidate_filter`` is the same WHERE clause applied to the main
    query (everything except CC itself); facets reflect what the user *would*
    see if they switched the CC chip — standard faceted-search semantics.
    """
    facet_query = (
        select(
            CompetenceCategory.id,
            CompetenceCategory.name_pl,
            func.count(Candidate.id).label("cnt"),
        )
        .join(
            Candidate,
            Candidate.competence_category_id == CompetenceCategory.id,
        )
        .where(candidate_filter)
        .group_by(CompetenceCategory.id, CompetenceCategory.name_pl)
        .order_by(CompetenceCategory.display_order)
    )
    result = await db.execute(facet_query)
    return [
        CompetenceCategoryFacet(id=row.id, name=row.name_pl, count=row.cnt)
        for row in result.all()
    ]


@router.post("/candidates/scores", response_model=MatchScoresResponse)
async def candidate_match_scores(
    body: MatchScoresRequest,
    current_user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
) -> MatchScoresResponse:
    """Read-only cached hybrid match scores (0-100) for candidates against a
    job (SEARCH-P1-03).

    Returns only candidates that already have a fresh cached score (computed by
    recommendations / kanban). This endpoint NEVER computes or writes a score,
    so it cannot pollute the shared cache with semantic-less values — it just
    surfaces the same numbers shown elsewhere on job-context search rows.
    """
    if not body.candidate_ids:
        return MatchScoresResponse(scores={})

    from app.services.scoring_service import DEFAULT_PROFILE  # noqa: PLC0415

    rows = (
        await db.execute(
            select(
                CandidateJobMatchScore.candidate_id,
                CandidateJobMatchScore.total_score,
                CandidateJobMatchScore.breakdown,
            ).where(
                *fresh_score_conditions(
                    job_id=body.job_id,
                    profile_id=DEFAULT_PROFILE.id,
                    candidate_ids=body.candidate_ids,
                )
            )
        )
    ).all()
    return MatchScoresResponse(
        scores={str(cid): round(total) for cid, total, _ in rows},
        breakdowns={str(cid): bd for cid, _, bd in rows if bd},
    )


async def _diagnostics_count(db: AsyncSession, clauses: list[Any]) -> int:
    where = and_(*clauses) if clauses else text("true")
    stmt = select(func.count(Candidate.id)).select_from(Candidate).where(where)
    return (await db.execute(stmt)).scalar() or 0


@router.post("/candidates/diagnostics", response_model=SearchDiagnosticsResponse)
async def candidate_search_diagnostics(
    body: CandidateSearchRequest,
    current_user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
) -> SearchDiagnosticsResponse:
    """Zero-result exclusion waterfall (SEARCH-P1-04).

    Applies the search's filters cumulatively and reports how many candidates
    survive each step, so a recruiter can see exactly which filter emptied the
    result set. Structural filters only — the semantic (hybrid) pool is not
    diagnosed here.
    """
    # Mirror the main search: a job context hides blacklisted candidates.
    if body.exclude_in_job_id is not None:
        body.exclude_blacklisted = True

    q_text = (body.q or "").strip() if body.q else ""

    base_count = await _diagnostics_count(db, [])
    applied: list[Any] = []
    stages: list[WaterfallStage] = []
    first_zeroing: Optional[str] = None

    async def step(key: str, label: str, new_clauses: list[Any]) -> None:
        nonlocal first_zeroing
        applied.extend(new_clauses)
        count = await _diagnostics_count(db, applied)
        stages.append(WaterfallStage(key=key, label=label, count=count))
        if count == 0 and first_zeroing is None:
            first_zeroing = key

    # Free-text / boolean buckets.
    query_clauses: list[Any] = []
    boolean = build_advanced_filter(
        body.q_all, body.q_any, body.q_none, body.q_any_groups
    )
    if boolean is not None:
        query_clauses.append(boolean)

    # Wodospad MUSI diagnozować TO zapytanie, które padło — a w trybie
    # semantycznym (domyślnym w `CandidateSearchView`) tekstu NIE filtruje
    # `websearch_to_tsquery`, tylko pula retrievalu. Do teraz obie ścieżki
    # dostawały tu FTS, czyli KONIUNKCJĘ leksemów: „senior python architekt
    # danych" pokazywało się jako etap zerujący i dostawało czerwony pasek
    # „to ten filtr", choć prawdziwe wyszukiwanie tej klauzuli w ogóle nie
    # użyło. Panel otwiera się WYŁĄCZNIE przy zerze wyników, więc to jedyny
    # ekran, na którym rekruter szuka przyczyny — i był kierowany pod zły adres.
    query_label = "Zapytanie tekstowe"
    if q_text and body.search_mode == "hybrid":
        from app.services.hybrid_search import hybrid_candidates  # noqa: PLC0415

        pool_size = _hybrid_pool_size()

        # `use_rerank=False`: wodospad pyta o CZŁONKOSTWO puli, nie o kolejność,
        # a przy `final_top_k == pool` reranker członkostwa nie zmienia. Ścieżka
        # zerowego wyniku nie musi płacić za przestawianie 200 dokumentów.
        pool = await hybrid_candidates(
            db,
            q_text,
            pool=pool_size,
            final_top_k=pool_size,
            use_rerank=False,
        )
        pool_ids = [cid for cid, _ in pool.pairs]
        query_clauses.append(Candidate.id.in_(pool_ids) if pool_ids else text("false"))
        query_label = "Zapytanie (dopasowanie semantyczne)"
    elif q_text:
        query_clauses.append(_fts_clause(q_text))

    if query_clauses:
        await step("query", query_label, query_clauses)

    # Structured filters, cumulative, in group order.
    for group in build_filter_groups(body):
        await step(group.key, group.label, list(group.clauses))

    # Already-in-job exclusion.
    if body.exclude_in_job_id is not None:
        already = (
            select(CandidateStage.candidate_id)
            .where(CandidateStage.job_id == body.exclude_in_job_id)
            .distinct()
        )
        await step(
            "already_in_job",
            "Nie dodani do tej rekrutacji",
            [Candidate.id.notin_(already)],
        )

    total = stages[-1].count if stages else base_count
    return SearchDiagnosticsResponse(
        base_count=base_count,
        stages=stages,
        total=total,
        first_zeroing_stage=first_zeroing,
    )


@router.post("/candidates", response_model=CandidateSearchResponse)
async def advanced_candidate_search(
    body: CandidateSearchRequest,
    current_user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
) -> CandidateSearchResponse:
    """Hybrid candidate search.

    Composes three filter layers (AND-ed together) and orders by either
    ``ts_rank`` (when a free-text query is present and ``sort=relevance``),
    ``updated_at DESC``, or ``lastname ASC`` — all postgres-side, so paging
    is consistent across pages.

    ``search_mode="hybrid"`` switches the free-text retrieval to the
    BM25 + Voyage dense + RRF fusion + Voyage Rerank 2.5 pipeline, which
    research benchmarks at 91% recall@10 vs 78% dense-only.
    """
    started_at = time.monotonic()

    clauses: list[Any] = []

    # === Layer 1: boolean buckets (Traffit-style ILIKE) ======================
    boolean_clause = build_advanced_filter(
        body.q_all, body.q_any, body.q_none, body.q_any_groups
    )
    if boolean_clause is not None:
        clauses.append(boolean_clause)

    # Job-context search hides globally-blacklisted candidates server-side
    # (eligibility visibility=hidden), regardless of what the client sent. The
    # global candidate list (no job context) still shows them for management.
    if body.exclude_in_job_id is not None:
        body.exclude_blacklisted = True

    # === Layer 2: structured chips ===========================================
    clauses.extend(build_structured_filter(body))

    # === Layer 3: free-text — FTS or hybrid (BM25+dense+RRF+rerank) ==========
    q_text = (body.q or "").strip() if body.q else ""
    hybrid_order: list[int] = []
    search_degraded = False
    use_hybrid = body.search_mode == "hybrid" and bool(q_text)
    # Wiązane BEZWARUNKOWO, choć używane tylko w gałęzi hybrydowej: `meta`
    # niżej czyta je w wyrażeniu `use_hybrid and ... >= pool_size`, które przy
    # trybie boolowskim ratuje wyłącznie skrócone obliczanie `and`. Nazwa
    # zdefiniowana w gałęzi znaczy, że przestawienie tych dwóch członów —
    # zmiana, która wygląda na czysto kosmetyczną — wywala `NameError` na
    # produkcji dla każdego wyszukiwania bez trybu semantycznego.
    pool_size = _hybrid_pool_size()
    if use_hybrid:
        # Pula jest zapasem na kilka stron wyników, ale NIE oszczędza wywołań:
        # endpoint jest bezstanowy, więc każda zmiana strony odpytuje retrieval
        # od nowa. Patrz `_hybrid_pool_size` — tam jest cały rachunek kosztu.
        from app.services.hybrid_search import hybrid_candidates  # noqa: PLC0415

        # ŚWIADOMY brak `bm25_query` (C12): tutaj `q_text` NAPRAWDĘ jest
        # zapytaniem rekrutera, więc koniunkcja 2-4 słów jest intencją,
        # a `-junior` udokumentowanym wykluczeniem (patrz `_fts_clause`).
        # Ścieżka OFERTOWA podaje terminy jawnie, bo tam „query" to dokument.
        # Nie ujednolicać tych dwóch wejść — to nie jest ta sama rzecz.
        hybrid = await hybrid_candidates(
            db,
            q_text,
            pool=pool_size,
            final_top_k=pool_size,
            use_rerank=None,
        )
        # Outage on the semantic leg: results fell back to BM25 alone. Surface
        # it in meta so the UI can say "semantic search unavailable" — an empty
        # or short list here must never read as "the database has no one".
        search_degraded = hybrid.degraded
        hybrid_order = [cid for cid, _ in hybrid.pairs]
        if hybrid_order:
            clauses.append(Candidate.id.in_(hybrid_order))
        else:
            # Empty hybrid result — short-circuit to no candidates so we don't
            # show the full base table when the user typed a specific query.
            clauses.append(text("false"))
    elif q_text:
        clauses.append(_fts_clause(q_text))

    # === Job-context exclusion — subquery on candidate_stages ================
    if body.exclude_in_job_id is not None:
        already_in_job = (
            select(CandidateStage.candidate_id)
            .where(CandidateStage.job_id == body.exclude_in_job_id)
            .distinct()
        )
        clauses.append(Candidate.id.notin_(already_in_job))

    where_clause = and_(*clauses) if clauses else text("true")

    # === Count total =========================================================
    count_query = (
        select(func.count(Candidate.id)).select_from(Candidate).where(where_clause)
    )
    if q_text:
        count_query = count_query.params(q=q_text)
    total = (await db.execute(count_query)).scalar() or 0

    # === Soft-chip breakdown =================================================
    # Experience and location no longer cut candidates whose field is blank
    # (NULL_POLICY), so the result count jumps from "45" to "11 091" and a
    # recruiter who typed a narrow band reasonably concludes the filter broke.
    # Report how many results actually state a matching value, so the UI can say
    # "45 with a stated 2-6 years, 11 046 unspecified" instead of leaving the
    # jump unexplained. One extra COUNT, and only when such a chip was sent.
    soft_counts: dict[str, int] = {}
    for key, expr in (
        ("experience", experience_soft_rank(body)),
        ("location", location_soft_rank(body)),
    ):
        if expr is None:
            continue
        soft_query = (
            select(func.count(Candidate.id))
            .select_from(Candidate)
            .where(where_clause, expr > 0)
        )
        if q_text:
            soft_query = soft_query.params(q=q_text)
        soft_counts[key] = (await db.execute(soft_query)).scalar() or 0

    # === Sort ================================================================
    if use_hybrid:
        # Hybrid path: respect the orchestrator's RRF/rerank ordering.
        #
        # Stronę wolno wycinać DOPIERO z listy przefiltrowanej. `hybrid_order`
        # to surowa pula retrievalu (do `_hybrid_pool_size()`), a `where_clause` niesie
        # WSZYSTKIE pozostałe filtry — chipy strukturalne, kubełki boolowskie,
        # wykluczenie z rekrutacji, blacklistę. `total` liczy przecięcie obu,
        # więc wycinanie strony z niefiltrowanej puli opisywało inny zbiór niż
        # licznik nad nią: strony wychodziły dziurawe, a przy chipie trafiającym
        # w koniec puli PIERWSZA strona bywała PUSTA przy `total > 0` — pustka
        # czyta się jak brak ludzi w bazie, nie jak zła paginacja.
        # Jedno dodatkowe zapytanie po same `id` (pula jest ograniczona do
        # rozmiaru puli, więc to skan po znanym, krótkim zbiorze).
        # Bez `.params(q=...)`, w odróżnieniu od `count_query` wyżej: w trybie
        # hybrydowym `where_clause` nie niesie bindparamu `:q` w ogóle (klauzula
        # FTS jest dodawana tylko w gałęzi `elif q_text`), a `_fts_clause` i tak
        # wiąże wartość w miejscu konstrukcji. Wywołanie byłoby więc martwe,
        # a martwe wywołanie w tym miejscu sugeruje następnemu czytelnikowi, że
        # ta ścieżka jest sterowana zapytaniem tekstowym — nie jest.
        surviving_query = select(Candidate.id).where(where_clause)
        surviving = set((await db.execute(surviving_query)).scalars().all())
        ranked_ids = [cid for cid in hybrid_order if cid in surviving]
        page_start = (body.page - 1) * body.page_size
        page_ids = ranked_ids[page_start : page_start + body.page_size]
        if page_ids:
            base = select(Candidate).where(Candidate.id.in_(page_ids))
            loaded = (await db.execute(base)).scalars().all()
            by_id = {c.id: c for c in loaded}
            candidates = [by_id[cid] for cid in page_ids if cid in by_id]
        else:
            candidates = []
    else:
        base = select(Candidate).where(where_clause)
        order_cols: list[Any] = []
        # SEARCH-P0-03: skill chips are a soft signal — they no longer cut, so
        # rank matchers to the top. Leads the sort whenever skill chips are
        # present (a skill search wants skill-relevant results first); the
        # requested sort is the tie-break below.
        # Soft signals lead the sort, strongest first: an explicit skill chip is
        # a stronger statement of intent than a location or seniority band.
        # Each is None when its chip was not sent, so nothing is added then.
        for soft in (
            skills_soft_rank(body),
            experience_soft_rank(body),
            location_soft_rank(body),
        ):
            if soft is not None:
                order_cols.append(soft.desc())
        if body.sort == "relevance" and q_text:
            order_cols.extend([_fts_rank_order(), Candidate.updated_at.desc()])
        elif body.sort == "name":
            order_cols.extend([Candidate.lastname.asc(), Candidate.name.asc()])
        else:
            order_cols.append(Candidate.updated_at.desc())
        base = base.order_by(*order_cols)

        base = base.offset((body.page - 1) * body.page_size).limit(body.page_size)
        if q_text:
            base = base.params(q=q_text)
        candidates = (await db.execute(base)).scalars().all()

    # Best-effort per-row score: use ts_rank when we have a query, otherwise 0.
    # Computing the score requires a second query if we want it on a populated
    # set — skip it for now since the postgres-side ORDER BY already returns
    # rows in score-descending order.
    items = [_candidate_to_item(c, 0.0) for c in candidates]

    facets_clause = where_clause  # facets reflect current filter set
    facets = SearchFacets(
        competence_categories=await _competence_facets(db, facets_clause)
        if not body.competence_category_ids
        else []
    )

    took_ms = int((time.monotonic() - started_at) * 1000)

    return CandidateSearchResponse(
        total=int(total),
        page=body.page,
        page_size=body.page_size,
        items=items,
        facets=facets,
        meta=SearchMeta(
            ai_status=ai_status(),
            took_ms=took_ms,
            search_degraded=search_degraded,
            soft_match_counts=soft_counts,
            # Pula wyczerpana ⇒ `total` jest sufitem retrievalu, nie liczbą
            # pasujących osób w bazie. UI ma to powiedzieć wprost.
            result_cap_reached=use_hybrid and len(hybrid_order) >= pool_size,
        ),
    )


@router.get("/")
async def unified_search(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=2),
    entity: Optional[str] = Query(
        None, description="candidates|jobs|clients — filter by entity type"
    ),
):
    """
    Full-text search across candidates, jobs, and clients.
    Falls back to PostgreSQL ILIKE. For semantic search use /search/semantic.
    """
    results: dict[str, List[Any]] = {}

    # M2 audit PR 1: candidates section only for roles with candidate read
    # capability — the viewer/client role keeps jobs/clients search but must
    # not enumerate the candidate base through the unified search bar.
    if (
        (not entity or entity == "candidates")
        and _can_read_section(current_user, ProductSection.sourcing)
        and user_has_candidate_read(current_user)
    ):
        result = await db.execute(
            select(Candidate)
            .where(
                or_(
                    Candidate.name.ilike(f"%{q}%"),
                    Candidate.lastname.ilike(f"%{q}%"),
                    Candidate.email.ilike(f"%{q}%"),
                    Candidate.location.ilike(f"%{q}%"),
                )
            )
            .limit(10)
        )
        results["candidates"] = [
            {
                "id": c.id,
                "name": f"{c.name} {c.lastname}",
                "email": c.email,
                "status": c.status,
            }
            for c in result.scalars().all()
        ]

    if (not entity or entity == "jobs") and _can_read_section(
        current_user, ProductSection.pipeline
    ):
        result = await db.execute(
            select(Job)
            .where(
                or_(
                    Job.title.ilike(f"%{q}%"),
                    Job.description.ilike(f"%{q}%"),
                )
            )
            .limit(10)
        )
        results["jobs"] = [
            {"id": j.id, "title": j.title, "status": j.status, "location": j.location}
            for j in result.scalars().all()
        ]

    if (not entity or entity == "clients") and _can_read_section(
        current_user, ProductSection.delivery
    ):
        client_name = client_display_name_expression()
        visible_client_ids = await resolve_client_visible_client_ids(db, current_user)
        clients_query = (
            select(Client, client_name.label("client_name"))
            .where(
                *visible_client_predicates(),
                or_(
                    client_name.ilike(f"%{q}%"),
                    Client.name.ilike(f"%{q}%"),
                    Client.industry.ilike(f"%{q}%"),
                ),
            )
            .order_by(func.lower(client_name).asc(), Client.id.asc())
            .limit(10)
        )
        clients_query = _apply_client_visibility(
            clients_query, Client.id, visible_client_ids
        )
        result = await db.execute(clients_query)
        results["clients"] = [
            {"id": client.id, "name": effective_name, "status": client.status}
            for client, effective_name in result.all()
        ]

    return {"query": q, "results": results}


@router.get("/global")
async def global_search(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=2),
):
    """
    Global live search — returns max 5 results per category (candidates, jobs, clients, contacts).
    Designed for the top search bar dropdown.
    GET /api/search/global?q=text
    """
    LIMIT = 5

    # Candidates
    # M2 audit PR 1: viewer/client role must not enumerate candidates from
    # the top search bar — the section is skipped, jobs/clients stay.
    candidates: list[dict[str, Any]] = []
    if _can_read_section(
        current_user, ProductSection.sourcing
    ) and user_has_candidate_read(current_user):
        cand_result = await db.execute(
            select(Candidate)
            .where(
                or_(
                    Candidate.name.ilike(f"%{q}%"),
                    Candidate.lastname.ilike(f"%{q}%"),
                    Candidate.email.ilike(f"%{q}%"),
                )
            )
            .limit(LIMIT)
        )
        candidates = [
            {
                "id": c.id,
                "name": f"{c.name} {c.lastname}",
                "subtitle": c.email or c.competence_category or "",
                "url": f"/candidates/{c.id}",
            }
            for c in cand_result.scalars().all()
        ]

    # Jobs
    jobs_list: list[dict[str, Any]] = []
    if _can_read_section(current_user, ProductSection.pipeline):
        jobs_result = await db.execute(
            select(Job)
            .where(
                Job.title.ilike(f"%{q}%"),
            )
            .limit(LIMIT)
        )
        for j in jobs_result.scalars().all():
            # Get client name via client_id
            job_client_name = ""
            if j.client_id:
                client = await resolve_visible_client(
                    db,
                    j.client_id,
                    follow_merge=True,
                )
                if client:
                    job_client_name = client_display_name(client)
            jobs_list.append(
                {
                    "id": j.id,
                    "name": j.title,
                    "subtitle": job_client_name or j.location or "",
                    "url": f"/jobs/{j.id}",
                }
            )

    # Clients
    clients_list: list[dict[str, Any]] = []
    visible_client_ids: frozenset[int] | None = frozenset()
    can_read_delivery = _can_read_section(current_user, ProductSection.delivery)
    if can_read_delivery:
        visible_client_ids = await resolve_client_visible_client_ids(db, current_user)
    if can_read_delivery:
        client_name = client_display_name_expression()
        clients_query = (
            select(Client, client_name.label("client_name"))
            .where(
                *visible_client_predicates(),
                or_(
                    client_name.ilike(f"%{q}%"),
                    Client.name.ilike(f"%{q}%"),
                    Client.industry.ilike(f"%{q}%"),
                ),
            )
            .order_by(func.lower(client_name).asc(), Client.id.asc())
            .limit(LIMIT)
        )
        clients_query = _apply_client_visibility(
            clients_query, Client.id, visible_client_ids
        )
        clients_result = await db.execute(clients_query)
        clients_list = [
            {
                "id": client.id,
                "name": effective_name,
                "subtitle": client.industry or "",
                "url": f"/clients/{client.id}",
            }
            for client, effective_name in clients_result.all()
        ]

    # Contacts — same containment as candidates above. Contact rows carry
    # client-side hiring-manager names, e-mails and phone numbers (PII), and
    # the candidates section is already skipped for the viewer/client role;
    # leaving contacts open would let the same role enumerate people from the
    # search bar through a different section.
    contacts_list: list[dict[str, Any]] = []
    if can_read_delivery:
        contacts_query = (
            select(Contact)
            .where(
                or_(
                    Contact.name.ilike(f"%{q}%"),
                    Contact.email.ilike(f"%{q}%"),
                )
            )
            .limit(LIMIT)
        )
        contacts_query = _apply_client_visibility(
            contacts_query, Contact.client_id, visible_client_ids
        )
        contacts_result = await db.execute(contacts_query)
        contacts_list = [
            {
                "id": c.id,
                "name": c.name,
                "subtitle": c.email or c.position or "",
                "url": "/contacts",
            }
            for c in contacts_result.scalars().all()
        ]

    return {
        "query": q,
        "candidates": candidates,
        "jobs": jobs_list,
        "clients": clients_list,
        "contacts": contacts_list,
    }


class SemanticSearchRequest(BaseModel):
    query: str
    top_k: int = 20
    filters: Optional[dict] = None


@router.post("/semantic")
async def semantic_search(
    body: SemanticSearchRequest,
    current_user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
):
    """
    Semantic candidate search using Voyage AI embeddings + Qdrant.
    POST /api/search/semantic
    Falls back to ILIKE text search when Qdrant/Voyage is unavailable.
    """
    from app.services.embedding_service import search_candidates_semantic

    q = body.query.strip()
    if not q:
        return {"query": q, "results": [], "total": 0, "search_type": "semantic"}

    # --- Semantic search via Qdrant ---
    hits = await search_candidates_semantic(q, top_k=body.top_k)

    if hits:
        candidate_ids = [h["candidate_id"] for h in hits]
        score_map = {h["candidate_id"]: h["score"] for h in hits}

        result = await db.execute(
            select(Candidate).where(Candidate.id.in_(candidate_ids))
        )
        candidates_by_id = {c.id: c for c in result.scalars().all()}

        results = []
        for cid in candidate_ids:
            c = candidates_by_id.get(cid)
            if not c:
                continue
            score = score_map.get(cid, 0.0)
            # Build a short highlight text
            highlight = ""
            if c.competence_category:
                highlight = c.competence_category
            elif c.ai_summary:
                highlight = c.ai_summary[:120]
            elif c.raw_cv_text:
                highlight = c.raw_cv_text[:120]

            results.append(
                {
                    "candidate": {
                        "id": c.id,
                        "name": c.name,
                        "lastname": c.lastname,
                        "email": c.email,
                        "phone": c.phone,
                        "location": c.location,
                        "status": c.status.value if c.status else None,
                        "competence_category": c.competence_category,
                        "expected_rate_hourly": canonical_profile_rate_amount(
                            c.expected_rate_hourly,
                            c.expected_rate_currency,
                        ),
                        "availability_date": c.availability_date.isoformat()
                        if c.availability_date
                        else None,
                        "tags": c.tags,
                        "skills": c.skills,
                        "ai_summary": c.ai_summary,
                        "avatar_url": c.avatar_url,
                        "created_at": c.created_at.isoformat()
                        if c.created_at
                        else None,
                    },
                    "score": score,
                    "highlight": highlight,
                }
            )

        return {
            "query": q,
            "results": results,
            "total": len(results),
            "search_type": "semantic",
        }

    # --- Fallback: ILIKE text search ---
    fallback_result = await db.execute(
        select(Candidate)
        .where(
            or_(
                Candidate.name.ilike(f"%{q}%"),
                Candidate.lastname.ilike(f"%{q}%"),
                Candidate.email.ilike(f"%{q}%"),
                Candidate.competence_category.ilike(f"%{q}%"),
                Candidate.raw_cv_text.ilike(f"%{q}%"),
            )
        )
        .limit(body.top_k)
    )
    fallback_candidates = fallback_result.scalars().all()
    results = []
    for c in fallback_candidates:
        highlight = c.competence_category or (
            c.ai_summary[:120] if c.ai_summary else ""
        )
        results.append(
            {
                "candidate": {
                    "id": c.id,
                    "name": c.name,
                    "lastname": c.lastname,
                    "email": c.email,
                    "phone": c.phone,
                    "location": c.location,
                    "status": c.status.value if c.status else None,
                    "competence_category": c.competence_category,
                    "expected_rate_hourly": canonical_profile_rate_amount(
                        c.expected_rate_hourly,
                        c.expected_rate_currency,
                    ),
                    "availability_date": c.availability_date.isoformat()
                    if c.availability_date
                    else None,
                    "tags": c.tags,
                    "skills": c.skills,
                    "ai_summary": c.ai_summary,
                    "avatar_url": c.avatar_url,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                },
                "score": None,
                "highlight": highlight,
            }
        )

    return {
        "query": q,
        "results": results,
        "total": len(results),
        "search_type": "text_fallback",
    }
