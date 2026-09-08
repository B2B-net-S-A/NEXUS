"""Fasada puli — jeden flip dla pięciu powierzchni, skala semantyczna nietknięta.

Decyzja zamrożona tu testami: hybryda wybiera CZŁONKOSTWO puli, ale warstwa
semantyczna scoringu dalej dostaje KOSINUSY. Wyniki fuzji RRF (~1/60 na
pozycję) i rerankera żyją na innych skalach — wpuszczone do `similarity_map`
rozstroiłyby kalibrację (gamma, frakcja neutralna) i zatruły cache score'ów.

Drugi kontrakt (C12, 2026-08-20): każde wywołanie fasady podaje `bm25_query`.
Fasada dostaje DOKUMENT, a `websearch_to_tsquery` ANDuje leksemy — więc noga
BM25 karmiona `query_text` zwracała zero dla każdej oferty, przez cały czas
istnienia hybrydy, i nie było tego widać, bo fuzja RRF z pustą listą wygląda
identycznie jak porządek nogi gęstej.
"""

import ast
from pathlib import Path

import pytest

from app.services.hybrid_search import HybridResult

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_flag_off_is_a_verbatim_passthrough(monkeypatch):
    """Wyłączona flaga = dosłownie dzisiejsza ścieżka, wywołanie za wywołanie."""

    from app.services import retrieval_pool as rp

    sentinel = [{"candidate_id": 1, "score": 0.9}]
    seen: dict = {}

    async def fake_semantic(query, *, top_k, raise_on_error=False):
        seen.update(query=query, top_k=top_k, raise_on_error=raise_on_error)
        return sentinel

    async def exploding_hybrid(*a, **k):  # pragma: no cover - nie wolno
        raise AssertionError("hybryda nie może być wołana przy wyłączonej fladze")

    from app.services import embedding_service

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", fake_semantic)
    import app.services.hybrid_search as hybrid_module

    monkeypatch.setattr(hybrid_module, "hybrid_candidates", exploding_hybrid)
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: False)

    out = await rp.retrieve_candidate_pool(
        object(), "Senior Python", top_k=200, raise_on_error=True
    )

    assert out is sentinel
    assert seen == {"query": "Senior Python", "top_k": 200, "raise_on_error": True}


@pytest.mark.asyncio
async def test_flag_on_membership_from_hybrid_scores_from_cosine(monkeypatch):
    """SEDNO: kto wchodzi — decyduje hybryda; ile podobieństwa — kosinus.

    Wynik RRF kandydata 7 (0.032) NIE może trafić do `score` — tam ma być jego
    kosinus (0.81), ta sama pasażo-świadoma miara co przy wyłączonej fladze.
    """

    from app.services import retrieval_pool as rp

    # Atrapa zwraca PRAWDZIWY `HybridResult`, nie `SimpleNamespace`: fasada
    # czyta z niego telemetrię nogi BM25 (`bm25_hits`/`bm25_failed`), więc
    # atrapa o luźnym kształcie przepuściłaby zmianę, która na produkcji
    # wywala się na `AttributeError`.
    async def fake_hybrid(db, query, *, pool, final_top_k, use_rerank, bm25_query):
        assert bm25_query == "", (
            "brak `bm25_query` na callsicie ⇒ nogi BM25 się NIE PYTA — "
            "dokument w roli tsquery daje zero, tyle że niewidzialnie"
        )
        return HybridResult(pairs=[(7, 0.032), (9, 0.031), (4, 0.030)])

    async def fake_cosines(query, ids):
        assert ids == [7, 9, 4], "kosinusy liczone dokładnie dla wybranych"
        return {7: 0.81, 4: 0.55}  # 9 celowo bez wektora

    import app.services.hybrid_search as hybrid_module

    monkeypatch.setattr(hybrid_module, "hybrid_candidates", fake_hybrid)
    from app.services import embedding_service

    monkeypatch.setattr(embedding_service, "similarity_for_candidate_ids", fake_cosines)
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: True)

    out = await rp.retrieve_candidate_pool(object(), "Senior Python", top_k=3)

    assert [row["candidate_id"] for row in out] == [7, 9, 4], "kolejność z hybrydy"
    by_id = {row["candidate_id"]: row["score"] for row in out}
    assert by_id[7] == 0.81 and by_id[4] == 0.55, "score = kosinus, nie RRF"
    assert by_id[9] == 0.0, (
        "kandydat bez wektora zostaje w puli z zerowym sygnałem semantycznym — "
        "pozostałe warstwy scoringu wciąż mogą go wynieść"
    )


@pytest.mark.asyncio
async def test_hybrid_failure_falls_back_to_semantic_when_swallowing(monkeypatch):
    """`raise_on_error=False` obowiązuje też na gałęzi hybrydowej.

    Konsumenci (rekomendacje, Talent Radar) wołają z domyślnym `False` i liczą
    na łagodną degradację — flip flagi nie może zamienić awarii silnika w 500.
    Spadek idzie na ścieżkę semantyczną, nie w pustkę: awaria NOWEGO silnika
    nie może degradować puli poniżej stanu sprzed flagi.
    """

    from app.services import retrieval_pool as rp

    async def exploding_hybrid(*a, **k):
        raise RuntimeError("BM25 w awarii")

    sentinel = [{"candidate_id": 3, "score": 0.7}]
    seen: dict = {}

    async def fake_semantic(query, *, top_k, raise_on_error=False):
        seen.update(raise_on_error=raise_on_error)
        return sentinel

    import app.services.hybrid_search as hybrid_module

    monkeypatch.setattr(hybrid_module, "hybrid_candidates", exploding_hybrid)
    from app.services import embedding_service

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", fake_semantic)
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: True)

    out = await rp.retrieve_candidate_pool(object(), "Senior Python", top_k=5)

    assert out is sentinel
    assert seen == {"raise_on_error": False}, (
        "fallback sam też musi połykać — inaczej pierwotny kontrakt wraca bokiem"
    )


@pytest.mark.asyncio
async def test_hybrid_failure_propagates_when_raising(monkeypatch):
    """`raise_on_error=True` (harness ewaluacyjny) ma widzieć awarię, nie maskę."""

    from app.services import retrieval_pool as rp

    async def exploding_hybrid(*a, **k):
        raise RuntimeError("BM25 w awarii")

    async def forbidden_semantic(*a, **k):  # pragma: no cover - nie wolno
        raise AssertionError("przy raise_on_error=True nie ma fallbacku")

    import app.services.hybrid_search as hybrid_module

    monkeypatch.setattr(hybrid_module, "hybrid_candidates", exploding_hybrid)
    from app.services import embedding_service

    monkeypatch.setattr(
        embedding_service, "search_candidates_semantic", forbidden_semantic
    )
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: True)

    with pytest.raises(RuntimeError, match="BM25 w awarii"):
        await rp.retrieve_candidate_pool(
            object(), "Senior Python", top_k=5, raise_on_error=True
        )


@pytest.mark.asyncio
async def test_cosine_failure_after_bm25_gives_zero_score_pool(monkeypatch):
    """Voyage pada PO udanym BM25 → pula BM25-only z score=0.0, nie wyjątek.

    To ta sama semantyka co „kandydat bez wektora", tylko dla wszystkich naraz —
    dokładne tokeny wciąż działają, a pusta pula byłaby gorsza od uboższej.
    """

    from app.services import retrieval_pool as rp

    async def fake_hybrid(db, query, *, pool, final_top_k, use_rerank, bm25_query):
        return HybridResult(pairs=[(7, 0.032), (4, 0.030)])

    async def exploding_cosines(query, ids):
        raise RuntimeError("Voyage w awarii")

    import app.services.hybrid_search as hybrid_module

    monkeypatch.setattr(hybrid_module, "hybrid_candidates", fake_hybrid)
    from app.services import embedding_service

    monkeypatch.setattr(
        embedding_service, "similarity_for_candidate_ids", exploding_cosines
    )
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: True)

    out = await rp.retrieve_candidate_pool(object(), "Senior Python", top_k=2)

    assert [row["candidate_id"] for row in out] == [7, 4]
    assert all(row["score"] == 0.0 for row in out)

    with pytest.raises(RuntimeError, match="Voyage w awarii"):
        await rp.retrieve_candidate_pool(
            object(), "Senior Python", top_k=2, raise_on_error=True
        )


# ── structured (0278): pula SQL-first po must-have ───────────────────────────
#
# Trzecia strategia w tej fasadzie: zamiast wektora/hybrydy, CZŁONKOSTWO
# wybiera Postgres (AND-of-OR po jawnych rodzinach umiejętności must-have).
# Ten sam kontrakt co przy hybrydzie — patrz docstring modułu i
# `_structured_pool`: SQL decyduje KTO wchodzi, kosinus liczy się OSOBNO
# i identycznie jak dotąd.


@pytest.mark.asyncio
async def test_structured_flag_off_is_verbatim_passthrough(monkeypatch):
    """`STRUCTURED_POOL_ENABLED=False` (domyślne) = dosłownie dzisiejsza ścieżka.

    Pierwsza instrukcja strategii SQL-first to sprawdzenie flagi — PRZED
    dotknięciem `db`. Test woła fasadę z `db=object()`: gdyby strategia
    strukturalna spróbowała cokolwiek na nim wykonać, wywaliłby się na
    `AttributeError`, a nie na tej asercji — to jest jego prawdziwy dowód.
    """

    from app.services import retrieval_pool as rp

    sentinel = [{"candidate_id": 1, "score": 0.9}]
    seen: dict = {}

    async def fake_semantic(query, *, top_k, raise_on_error=False):
        seen.update(query=query, top_k=top_k, raise_on_error=raise_on_error)
        return sentinel

    async def exploding_hybrid(*a, **k):  # pragma: no cover - nie wolno
        raise AssertionError("hybryda nie może być wołana przy wyłączonej fladze")

    from app.services import embedding_service
    import app.services.hybrid_search as hybrid_module

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", fake_semantic)
    monkeypatch.setattr(hybrid_module, "hybrid_candidates", exploding_hybrid)
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: False)
    monkeypatch.setattr(rp, "structured_pool_enabled", lambda: False)

    out = await rp.retrieve_candidate_pool(
        object(),
        "Senior Python",
        top_k=200,
        raise_on_error=True,
        # Obecność `must_groups` NIE wystarcza, żeby cokolwiek uzbroić —
        # tylko flaga decyduje.
        must_groups=[["python"]],
    )

    assert out is sentinel
    assert seen == {"query": "Senior Python", "top_k": 200, "raise_on_error": True}


@pytest.mark.asyncio
async def test_structured_membership_from_sql_scores_from_cosine(monkeypatch):
    """SEDNO: kto wchodzi — decyduje SQL; ile podobieństwa — kosinus.

    Ten sam wzorzec co przy hybrydzie: `bm25_must_candidates` wybiera
    CZŁONKOSTWO, a `score` w wyniku to zawsze kosinus z
    `similarity_for_candidate_ids` — nigdy ranga SQL-a.
    """

    from app.core.config import settings
    from app.services import retrieval_pool as rp

    async def fake_bm25_must_candidates(db, groups, *, limit):
        assert groups == ['"Python"'], (
            "must_groups=[['Python']] MUSI dojść do SQL-a jako gotowy "
            "query-string tej rodziny — to buduje `hybrid_search.bm25_must_groups`"
        )
        assert limit == settings.STRUCTURED_POOL_LIMIT
        return [7, 9, 4]

    async def fake_cosines(query, ids):
        assert ids == [7, 9, 4], "kosinusy liczone dokładnie dla wybranych przez SQL"
        return {7: 0.81, 4: 0.55}  # 9 celowo bez wektora

    import app.services.hybrid_search as hybrid_module

    monkeypatch.setattr(
        hybrid_module, "bm25_must_candidates", fake_bm25_must_candidates
    )
    from app.services import embedding_service

    monkeypatch.setattr(embedding_service, "similarity_for_candidate_ids", fake_cosines)
    monkeypatch.setattr(rp, "structured_pool_enabled", lambda: True)
    # 3 trafienia < domyślny STRUCTURED_POOL_MIN_MEMBERS (20) — bez tego SQL-first
    # oddałby `None` (poniżej progu ufności) i test mierzyłby SPADEK na wektor,
    # nie sedno tego testu (kto wchodzi vs ile podobieństwa). Próg ma WŁASNY test
    # (`test_structured_falls_through_below_floor_or_without_groups`).
    monkeypatch.setattr(settings, "STRUCTURED_POOL_MIN_MEMBERS", 1, raising=False)

    out = await rp.retrieve_candidate_pool(
        object(), "Senior Python", top_k=3, must_groups=[["Python"]]
    )

    known = [row["candidate_id"] for row in out if not row.get("semantic_unknown")]
    unknown = [row["candidate_id"] for row in out if row.get("semantic_unknown")]
    assert known == [7, 4], "kosinus malejąco"
    assert unknown == [9], "bez zmierzonego kosinusu — na końcu, nie wykluczony"
    by_id = {row["candidate_id"]: row["score"] for row in out}
    assert by_id[7] == 0.81 and by_id[4] == 0.55, "score = kosinus, nie ranga SQL-a"
    assert by_id[9] == 0.0, "brak wektora ≠ wykluczenie — 0.0 to «nie wiem»"


@pytest.mark.asyncio
async def test_structured_falls_through_below_floor_or_without_groups(monkeypatch):
    """Trzy niezależne, nieszkodliwe powody, dla których SQL-first oddaje
    `None` i pula spada na wektor — dokładnie jakby flaga była wyłączona.

    (a) `must_groups` puste/`None`/złożone z samych zdegenerowanych rodzin —
        SQL nie ma o co pytać.
    (b) SQL trafił, ale mniej niż `STRUCTURED_POOL_MIN_MEMBERS` — zbyt wąskie
        członkostwo nie jest ufane jako CAŁA pula.
    """

    from app.core.config import settings
    from app.services import retrieval_pool as rp

    sentinel = [{"candidate_id": 1, "score": 0.9}]

    async def fake_semantic(query, *, top_k, raise_on_error=False):
        return sentinel

    async def exploding_sql(*a, **k):  # pragma: no cover - nie wolno
        raise AssertionError("SQL nie może być wołany bez rodzin must-have")

    from app.services import embedding_service
    import app.services.hybrid_search as hybrid_module

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", fake_semantic)
    monkeypatch.setattr(rp, "structured_pool_enabled", lambda: True)
    monkeypatch.setattr(hybrid_module, "bm25_must_candidates", exploding_sql)

    for empty_input in (None, [], [["c#"]]):
        out = await rp.retrieve_candidate_pool(
            object(), "Senior Python", top_k=5, must_groups=empty_input
        )
        assert out is sentinel, (
            f"must_groups={empty_input!r} nie ma o co pytać SQL-a — spadek na "
            "wektor bez dotykania bazy"
        )

    async def fake_few_hits(db, groups, *, limit):
        return [1, 2]

    monkeypatch.setattr(hybrid_module, "bm25_must_candidates", fake_few_hits)
    monkeypatch.setattr(settings, "STRUCTURED_POOL_MIN_MEMBERS", 20, raising=False)

    out = await rp.retrieve_candidate_pool(
        object(), "Senior Python", top_k=5, must_groups=[["Python"]]
    )
    assert out is sentinel, "2 trafienia < 20 — poniżej progu ufności, spadek na wektor"


@pytest.mark.asyncio
async def test_structured_sql_failure_swallows_or_raises_per_contract(monkeypatch):
    """`raise_on_error` obowiązuje TEŻ na ścieżce SQL-first.

    Ten sam kontrakt co przy hybrydzie: konsumenci fasady wołają z domyślnym
    `False` i liczą na łagodną degradację (awaria NOWEJ strategii nie może
    degradować puli poniżej stanu sprzed flagi); harness ewaluacyjny
    (`raise_on_error=True`) ma widzieć awarię, nie maskę.
    """

    from app.services import retrieval_pool as rp

    async def exploding_sql(db, groups, *, limit):
        raise RuntimeError("Postgres w awarii")

    sentinel = [{"candidate_id": 3, "score": 0.7}]

    async def fake_semantic(query, *, top_k, raise_on_error=False):
        return sentinel

    import app.services.hybrid_search as hybrid_module
    from app.services import embedding_service

    monkeypatch.setattr(hybrid_module, "bm25_must_candidates", exploding_sql)
    monkeypatch.setattr(embedding_service, "search_candidates_semantic", fake_semantic)
    monkeypatch.setattr(rp, "structured_pool_enabled", lambda: True)

    out = await rp.retrieve_candidate_pool(
        object(), "Senior Python", top_k=5, must_groups=[["Python"]]
    )
    assert out is sentinel, "raise_on_error=False (domyślne) — spadek na wektor"

    with pytest.raises(RuntimeError, match="Postgres w awarii"):
        await rp.retrieve_candidate_pool(
            object(),
            "Senior Python",
            top_k=5,
            raise_on_error=True,
            must_groups=[["Python"]],
        )


def test_structured_flags_absent_from_scoring_cache_inputs():
    """Zamrożona decyzja, nie przeoczenie — jak przy hybrydzie i multi-query.

    Wszystkie trzy pokrętła strategii SQL-first (`STRUCTURED_POOL_ENABLED`,
    `STRUCTURED_POOL_LIMIT`, `STRUCTURED_POOL_MIN_MEMBERS`) zmieniają
    wyłącznie CZŁONKOSTWO puli; kosinus per kandydat liczy dokładnie ta sama
    funkcja (`similarity_for_candidate_ids`) niezależnie od tego, która
    strategia go wybrała — więc istniejące wiersze cache score'ów zostają
    poprawne.
    """

    from app.services.scoring_service import _SCORING_CACHE_INPUTS

    assert "STRUCTURED_POOL_ENABLED" not in _SCORING_CACHE_INPUTS
    assert "STRUCTURED_POOL_LIMIT" not in _SCORING_CACHE_INPUTS
    assert "STRUCTURED_POOL_MIN_MEMBERS" not in _SCORING_CACHE_INPUTS


def test_hybrid_flag_is_deliberately_absent_from_scoring_cache_inputs():
    """Zamrożona decyzja, nie przeoczenie.

    Skala semantyczna przy włączonej hybrydzie NIE zmienia się (kosinusy są
    re-derywowane per kandydat), więc istniejące wiersze cache pozostają
    poprawne — inwalidacja całej tabeli byłaby czystym kosztem bez korekty.
    Jeśli kiedyś fasada zacznie wpuszczać do `score` coś innego niż kosinus,
    ten test trzeba ŚWIADOMIE usunąć i dopisać flagę do klucza.
    """

    from app.services.scoring_service import _SCORING_CACHE_INPUTS

    assert "HYBRID_POOL_ENABLED" not in _SCORING_CACHE_INPUTS
    # Ta sama decyzja, ten sam powód: sufit członkostwa nogi BM25 zmienia
    # KOGO oglądamy, nie JAK liczymy. Kosinusy dalej idą z
    # `similarity_for_candidate_ids`, więc istniejące wiersze cache zostają
    # poprawne — dopisanie klucza byłoby czystą inwalidacją bez korekty.
    assert "HYBRID_BM25_POOL_LIMIT" not in _SCORING_CACHE_INPUTS


# Callsite fasady, który jeszcze NIE przekazuje `bm25_query`. Skutek jest
# konkretny i trzeba go znać przed pomiarem: harness ewaluacyjny mierzy ramię
# „hybryda ON" z nogą BM25, o którą się nie pyta — czyli mierzy pulę
# wyłącznie wektorową i pokaże brak różnicy niezależnie od jakości terminów.
# Plik jest poza zakresem tej zmiany; wpis znika razem z uzupełnieniem
# `bm25_query=build_job_bm25_query(job)` w `scripts/eval_matching.py:518`.
_BM25_QUERY_PENDING = {"scripts/eval_matching.py"}


def test_all_pool_sites_go_through_the_facade():
    """Częściowy flip to jedyny naprawdę błędny stan — patrz pasaże.

    Każde z sześciu miejsc puli (rekomendacje, `/ai-matches`, Talent Radar,
    propozycje, digest, eval) woła fasadę; żadne nie woła `search_candidates_semantic`
    bezpośrednio dla PULI. (Inne użycia — np. `similarity_for_candidate_ids` —
    zostają.)

    Drugi wymóg (C12): każde wywołanie fasady podaje `bm25_query`. Zapomniany
    argument nie wywala niczego — po prostu wyłącza nogę BM25 dla tej
    powierzchni, cicho i bez awarii. To dokładnie ta klasa defektu, przez którą
    hybryda przez cały czas swojego istnienia była kosztem bez wkładu, więc
    strażnik pilnuje obecności argumentu, nie samego przejścia przez fasadę.

    Trzeci wymóg (0278): każde wywołanie fasady podaje TAKŻE `must_groups`.
    W odróżnieniu od `bm25_query` (który ma jeden świadomy wyjątek —
    `_BM25_QUERY_PENDING`), `must_groups` jest wymagany na WSZYSTKICH sześciu
    powierzchniach bez wyjątku: zapomniany argument nie wywala niczego — po
    prostu wyłącza strategię SQL-first dla tej powierzchni, cicho, i A/B na
    zamrożonym zbiorze ofert wyglądałby jak „strategia bez wpływu", mimo że
    po prostu nie dostała danych.
    """

    sites = {
        "app/api/recommendations.py",
        # `/ai-matches` — powierzchnia produktu na stronie rekrutacji. Dołożona
        # 09.2026: była jedyną, która pobierała pulę z pominięciem fasady, więc
        # żadna dźwignia retrievalu jej nie dotyczyła.
        "app/api/matching.py",
        "app/services/talent_radar_search.py",
        "app/tasks/compute_proposals.py",
        # Digest wołał fasadę od początku, ale nigdy nie był na tej liście —
        # istniejąca luka strażnika, nie nowy callsite.
        "app/tasks/match_digest.py",
        "scripts/eval_matching.py",
    }
    assert _BM25_QUERY_PENDING <= sites, "wyjątek na plik spoza listy callsite'ów"
    for rel in sites:
        source = (BACKEND / rel).read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "retrieve_candidate_pool" in calls, f"{rel}: pula poza fasadą"
        assert "search_candidates_semantic" not in calls, (
            f"{rel}: bezpośrednie wywołanie puli obok fasady — częściowy flip"
        )
        # Wariant atrybutowy (`embedding_service.search_candidates_semantic(...)`)
        # to inny węzeł AST (`ast.Attribute`, nie `ast.Name`) — bez tej gałęzi
        # strażnik przepuściłby refaktor na import modułu, chroniąc mniej, niż
        # obiecuje jego nazwa.
        attr_calls = [
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        assert "search_candidates_semantic" not in attr_calls, (
            f"{rel}: atrybutowe wywołanie puli obok fasady — częściowy flip"
        )

        pool_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "retrieve_candidate_pool"
        ]
        for call in pool_calls:
            assert any(kw.arg == "must_groups" for kw in call.keywords), (
                f"{rel}: pula bez `must_groups` — strategia SQL-first (0278) "
                f"nie dostanie jawnych must-have i cicho spadnie na starą ścieżkę"
            )

        if rel in _BM25_QUERY_PENDING:
            continue
        for call in pool_calls:
            assert any(kw.arg == "bm25_query" for kw in call.keywords), (
                f"{rel}: pula bez `bm25_query` — noga BM25 nie dostanie o co "
                f"pytać i zwróci zero, cicho i bez awarii"
            )


# ── multi-query (runda 2): unia wariantów, kosinusy z zapytania głównego ─────


@pytest.mark.asyncio
async def test_multi_query_union_membership_primary_similarity(monkeypatch):
    """Warianty dosypują CZŁONKOSTWO; podobieństwo dosypki liczy się względem
    zapytania GŁÓWNEGO (ta sama zasada co hybryda — jedna skala kosinusa)."""

    from app.services import embedding_service
    from app.services import retrieval_pool as rp

    calls: list[str] = []

    async def fake_semantic(query, *, top_k, raise_on_error=False):
        calls.append(query)
        if query == "PRIMARY":
            return [
                {"candidate_id": 1, "score": 0.9},
                {"candidate_id": 2, "score": 0.8},
            ]
        return [
            {"candidate_id": 2, "score": 0.99},  # duplikat — zostaje primary 0.8
            {"candidate_id": 3, "score": 0.95},  # nowy — kosinus z primary
        ]

    async def fake_similarity(query, ids):
        assert query == "PRIMARY", "kosinusy dosypki MUSZĄ iść z tekstu głównego"
        assert ids == [3]
        return {3: 0.55}

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", fake_semantic)
    monkeypatch.setattr(
        embedding_service, "similarity_for_candidate_ids", fake_similarity
    )
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: False)
    monkeypatch.setattr(rp, "multi_query_enabled", lambda: True)

    out = await rp.retrieve_candidate_pool(
        object(), "PRIMARY", top_k=10, query_variants=["wariant skillowy"]
    )

    assert calls == ["PRIMARY", "wariant skillowy"]
    assert out == [
        {"candidate_id": 1, "score": 0.9},
        {"candidate_id": 2, "score": 0.8},
        {"candidate_id": 3, "score": 0.55},
    ]


@pytest.mark.asyncio
async def test_multi_query_flag_off_single_call(monkeypatch):
    from app.services import embedding_service
    from app.services import retrieval_pool as rp

    calls: list[str] = []

    async def fake_semantic(query, *, top_k, raise_on_error=False):
        calls.append(query)
        return []

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", fake_semantic)
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: False)
    monkeypatch.setattr(rp, "multi_query_enabled", lambda: False)

    await rp.retrieve_candidate_pool(
        object(), "PRIMARY", top_k=10, query_variants=["w1", "w2"]
    )
    assert calls == ["PRIMARY"], "flaga OFF ⇒ warianty ignorowane"


@pytest.mark.asyncio
async def test_multi_query_variant_failure_does_not_kill_pool(monkeypatch):
    from app.services import embedding_service
    from app.services import retrieval_pool as rp

    async def fake_semantic(query, *, top_k, raise_on_error=False):
        if query == "PRIMARY":
            return [{"candidate_id": 1, "score": 0.9}]
        raise RuntimeError("wariant padł")

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", fake_semantic)
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: False)
    monkeypatch.setattr(rp, "multi_query_enabled", lambda: True)

    out = await rp.retrieve_candidate_pool(
        object(), "PRIMARY", top_k=10, query_variants=["zly"]
    )
    assert out == [{"candidate_id": 1, "score": 0.9}]


def test_multi_query_flag_is_deliberately_absent_from_scoring_cache_inputs():
    """Multi-query zmienia tylko CZŁONKOSTWO puli — kosinus per kandydat jest
    ten sam, więc cache score'ów pozostaje poprawny (jak przy hybrydzie)."""
    from app.services.scoring_service import _SCORING_CACHE_INPUTS

    assert "MULTI_QUERY_RETRIEVAL_ENABLED" not in _SCORING_CACHE_INPUTS
