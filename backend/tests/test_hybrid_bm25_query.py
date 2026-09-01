"""C12 — noga BM25 dostawała DOKUMENT, a `websearch_to_tsquery` ANDuje leksemy.

Zweryfikowane na Postgresie 16 PRZED napisaniem tych testów (nie z pamięci):

    websearch_to_tsquery('simple','senior java kraków')  => 'senior' & 'java' & 'kraków'
    websearch_to_tsquery('simple','"sql server" or java') => 'sql' <-> 'server' | 'java'
    websearch_to_tsquery('simple','"or" or "java"')       => 'or' | 'java'
    websearch_to_tsquery('simple','"-junior" or "java"')  => 'junior' | 'java'
    websearch_to_tsquery('simple','"c++"')                => 'c'
    websearch_to_tsquery('simple','"a"b" or "java"')      => 'a' & 'b' & 'or' & 'java'

Czyli: karmienie tej funkcji tekstem oferty (setki leksemów) to koniunkcja
setek słów — ZERO trafień dla każdej oferty i każdego kandydata, zawsze, a nie
„mało". Fuzja RRF z pustą listą zwraca czysty porządek nogi gęstej, `degraded`
zostaje `False` i cała hybryda wygląda na działającą.

Dlaczego mock nie wystarcza: cała hipoteza dotyczy tego, co Postgres robi
z długim tekstem i tego, że lekseny zapytania są SYMETRYCZNE z leksemami
`to_tsvector` w kolumnie `fts_doc`. Zaślepka nie odtworzy ani jednego, ani
drugiego — dlatego testy A/B/C/E chodzą po realnej bazie.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text

# Termin, którego nie ma nikt inny w bazie — inaczej test „znalazł kandydata"
# przechodziłby przez przypadkowe trafienie w cudzy wiersz.
NONCE_SKILL = f"zorbatech{uuid.uuid4().hex[:8]}"
# Słowo obecne WYŁĄCZNIE w prozie oferty. To ono zabija koniunkcję: kandydat
# go nie ma, więc dokument-jako-zapytanie nie może go dopasować.
NONCE_JD = f"marglodyna{uuid.uuid4().hex[:8]}"

_JD_PROSE = (
    "Poszukujemy doświadczonego inżyniera do zespołu, który zbuduje i utrzyma "
    "platformę danych dla klienta z sektora finansowego. Praca w modelu "
    "hybrydowym, dwa dni w tygodniu w biurze, pozostałe zdalnie. Oczekujemy "
    "samodzielności, dobrej komunikacji po polsku i angielsku oraz gotowości "
    "do pracy w zespole rozproszonym. Projekt jest długoterminowy, z opcją "
    "przedłużenia współpracy na kolejne lata. Mile widziane doświadczenie "
    f"w migracjach oraz znajomość {NONCE_SKILL} i narzędzi klasy {NONCE_JD}, "
    "a także umiejętność pracy z dokumentacją techniczną."
)


async def _seed() -> tuple[int, int]:
    """Kandydat z NONCE_SKILL w CV + oferta z NONCE_SKILL w `must_skills`
    i długą prozą zawierającą NONCE_JD, którego w CV NIE MA.

    Zwraca `(job_id, candidate_id)`.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"BM25Client-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        job = Job(
            title=f"BM25-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=client.id,
            description=_JD_PROSE,
            must_skills=[{"name": NONCE_SKILL, "level": None}],
        )
        candidate = Candidate(
            name="Bemdwadziescia",
            lastname=f"Piatka-{uuid.uuid4().hex[:6]}",
            email=f"bm25-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus.active,
            raw_cv_text=(
                f"Doświadczenie komercyjne: {NONCE_SKILL}. "
                "Projekty wdrożeniowe, utrzymanie, dokumentacja."
            ),
        )
        db.add_all([job, candidate])
        await db.commit()
        await db.refresh(job)
        await db.refresh(candidate)
        return job.id, candidate.id


# ── A. Charakteryzacja defektu — zielony DZIŚ i po naprawie ──────────────────


@pytest.mark.asyncio
async def test_document_as_bm25_query_matches_nobody():
    """Dokument w roli zapytania nie trafia w NIKOGO — nawet w idealny wiersz.

    Ten test jest zamrożeniem POWODU całej zmiany, nie jej dowodem. Broni przed
    „uproszczeniem" polegającym na powrocie do karmienia nogi BM25 tekstem
    oferty: jeśli kiedyś przejdzie na zielono z asercją odwrotną, ktoś zmienił
    semantykę `websearch_to_tsquery` albo znowu karmi ją dokumentem — obie
    rzeczy trzeba zobaczyć, a nie odkryć po pomiarze bez różnicy.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.embedding_service import _build_job_text
    from app.services.hybrid_search import bm25_candidates

    job_id, candidate_id = await _seed()
    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == job_id))
        document = _build_job_text(job)
        assert NONCE_SKILL in document.lower(), (
            "dokument MUSI zawierać ten termin — inaczej test dowodzi tylko, "
            "że szukaliśmy nie tego słowa"
        )
        ids = await bm25_candidates(db, document, limit=100)

    assert candidate_id not in ids, (
        "koniunkcja setek leksemów nie może trafić w kandydata, który ma "
        "tylko jeden z nich"
    )


# ── B. Builder + SQL: te same lekseny po obu stronach ────────────────────────


@pytest.mark.asyncio
async def test_bm25_finds_candidate_by_required_skill():
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.hybrid_search import bm25_candidates, build_job_bm25_query

    job_id, candidate_id = await _seed()
    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == job_id))
        query = build_job_bm25_query(job)
        assert NONCE_SKILL in query.lower()
        assert NONCE_JD not in query.lower(), (
            "proza oferty nie może wejść do terminów — to jest cały defekt"
        )
        ids = await bm25_candidates(db, query, limit=100)

    assert candidate_id in ids


# ── C. Dowód przez realnie zepsutą ścieżkę: fasada → hybryda → Postgres ──────


@pytest.mark.asyncio
async def test_hybrid_pool_admits_candidate_the_vector_leg_missed(monkeypatch):
    """Noga gęsta ZDROWA i pusta („wektor tego kandydata przeoczył").

    Dziś pula jest w tym scenariuszu pusta: BM25 dostaje dokument i zwraca zero,
    więc hybryda nie ma czego dołożyć. Po naprawie kandydat wchodzi do puli ze
    `score == 0.0` — czyli z semantyką „brak sygnału semantycznego", nie
    z wykluczeniem.
    """
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services import embedding_service as emb
    from app.services import retrieval_pool as rp
    from app.services.canonical_text import build_job_query_variants
    from app.services.embedding_service import _build_job_text
    from app.services.hybrid_search import build_job_bm25_query

    async def _healthy_but_empty(query, top_k=20, *, raise_on_error=False):
        return []

    async def _no_cosines(query, ids):
        return {}

    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: True)
    monkeypatch.setattr(emb, "search_candidates_semantic", _healthy_but_empty)
    monkeypatch.setattr(emb, "similarity_for_candidate_ids", _no_cosines)
    # RERANKER_ENABLED jest domyślnie True — bez tego hybryda poszłaby do Voyage.
    monkeypatch.setattr(settings, "RERANKER_ENABLED", False, raising=False)

    job_id, candidate_id = await _seed()
    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == job_id))
        query_text = _build_job_text(job)
        pool = await rp.retrieve_candidate_pool(
            db,
            query_text,
            top_k=100,
            query_variants=build_job_query_variants(job, query_text),
            bm25_query=build_job_bm25_query(job),
        )

    by_id = {row["candidate_id"]: row["score"] for row in pool}
    assert candidate_id in by_id, (
        "noga BM25 z terminami MUSI wnieść do puli kandydata, którego wektor "
        "przeoczył — inaczej hybryda jest kosztem bez wkładu"
    )
    assert by_id[candidate_id] == 0.0


@pytest.mark.asyncio
async def test_facade_without_bm25_query_does_not_feed_the_document(monkeypatch):
    """Brak `bm25_query` na callsicie ⇒ nogi BM25 się NIE PYTA.

    Świadomie inna domyślna niż w `hybrid_candidates`: `query_text` fasady jest
    zawsze dokumentem, a dokument nie jest poprawnym wejściem tsquery. „Bez
    BM25" jest uczciwsze niż „nakarm dokumentem", bo to drugie wygląda
    identycznie jak działająca hybryda.
    """
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services import embedding_service as emb
    from app.services import retrieval_pool as rp
    from app.services.embedding_service import _build_job_text

    async def _healthy_but_empty(query, top_k=20, *, raise_on_error=False):
        return []

    async def _no_cosines(query, ids):
        return {}

    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: True)
    monkeypatch.setattr(emb, "search_candidates_semantic", _healthy_but_empty)
    monkeypatch.setattr(emb, "similarity_for_candidate_ids", _no_cosines)
    monkeypatch.setattr(settings, "RERANKER_ENABLED", False, raising=False)

    job_id, candidate_id = await _seed()
    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == job_id))
        pool = await rp.retrieve_candidate_pool(db, _build_job_text(job), top_k=100)

    assert candidate_id not in {row["candidate_id"] for row in pool}


# ── D. Telemetria — trzy stany rozróżnialne (czysto jednostkowy) ─────────────


def _stub_bm25(monkeypatch, ids: list[int]) -> None:
    from app.services import hybrid_search

    async def _fake(db, query, *, limit: int = 100):
        return list(ids)

    monkeypatch.setattr(hybrid_search, "bm25_candidates", _fake)


def _stub_semantic(monkeypatch, hits: list[dict]) -> None:
    from app.services import embedding_service

    async def _ok(query, top_k=20, *, raise_on_error=False):
        return list(hits)

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _ok)


@pytest.mark.asyncio
async def test_bm25_telemetry_distinguishes_unasked_empty_and_failed(monkeypatch):
    """„Nie pytano", „pytano i zero" i „padło" to TRZY różne diagnozy.

    Bez tego rozróżnienia log fasady nie odpowiada na jedyne pytanie, które
    ma sens po flipie flagi: czy noga w ogóle dostała o co pytać.
    """
    from app.services import hybrid_search
    from app.services.hybrid_search import hybrid_candidates

    _stub_semantic(monkeypatch, [])
    _stub_bm25(monkeypatch, [5])

    # (1) nogi nie pytano — pusty `bm25_query` NIE jest awarią
    result = await hybrid_candidates(
        db=None, query="x", bm25_query="", use_rerank=False
    )
    assert result.bm25_hits is None and result.bm25_failed is False

    # (2) pytano, zero trafień — stan LEGALNY, nie defekt
    _stub_bm25(monkeypatch, [])
    result = await hybrid_candidates(
        db=None, query="x", bm25_query='"java"', use_rerank=False
    )
    assert result.bm25_hits == 0
    assert result.bm25_failed is False
    assert result.degraded is False

    # (3) noga rzuciła — DEFEKT, ale `degraded` NIE zapala się: to komunikat
    #     o Voyage/Qdrant i nie wolno nim kłamać o innej warstwie.
    async def _boom(db, query, *, limit: int = 100):
        raise RuntimeError("Postgres w awarii")

    monkeypatch.setattr(hybrid_search, "bm25_candidates", _boom)
    _stub_semantic(monkeypatch, [{"candidate_id": 7, "score": 0.9}])
    result = await hybrid_candidates(
        db=None, query="x", bm25_query='"java"', use_rerank=False
    )
    assert result.bm25_failed is True
    assert result.degraded is False
    assert [cid for cid, _ in result.pairs] == [7], (
        "trafienia gęste — już policzone i opłacone wywołaniem Voyage — muszą "
        "przeżyć awarię drugiej nogi"
    )


@pytest.mark.asyncio
async def test_bm25_query_defaults_to_query_for_the_manual_search(monkeypatch):
    """`bm25_query=None` ⇒ noga dostaje `query`.

    To jest kontrakt ręcznej wyszukiwarki (`api/search.py`), gdzie `query`
    NAPRAWDĘ jest zapytaniem rekrutera: AND na 2-4 słowach jest tam intencją,
    a `-junior` udokumentowaną funkcją. Zmiana tej domyślnej po cichu zabrałaby
    użytkownikowi wykluczanie.
    """
    from app.services import hybrid_search
    from app.services.hybrid_search import hybrid_candidates

    seen: dict = {}

    async def _capture(db, query, *, limit: int = 100):
        seen["query"] = query
        return [11]

    monkeypatch.setattr(hybrid_search, "bm25_candidates", _capture)
    _stub_semantic(monkeypatch, [])

    result = await hybrid_candidates(
        db=None, query="python fastapi -junior", use_rerank=False
    )

    assert seen["query"] == "python fastapi -junior"
    assert result.bm25_hits == 1


# ── E. Escapowanie — jednostkowo + jeden dowód przez Postgresa ───────────────


@pytest.mark.parametrize(
    "terms,expected",
    [
        # frazy wielowyrazowe: cudzysłów robi z nich frazę, nie koniunkcję
        (["SQL Server", "Java"], '"SQL Server" or "Java"'),
        # myślnik na początku jest operatorem NOT — cudzysłów go neutralizuje
        (["-junior"], '"-junior"'),
        # słowo-operator też przeżywa w cudzysłowie jako zwykły leksem
        (["or"], '"or"'),
        # cudzysłów WYCIĘTY z treści — jeden zabłąkany przywraca AND
        (['a"b'], '"a b"'),
        # „c++"/„c#" zapadają się do leksemu 'c', który trafia w każde CV
        # z samotnym „C" — to nie sygnał, to zalew
        (["c++", "c#", "Java"], '"Java"'),
        ([".NET", "node.js"], '".NET" or "node.js"'),
        # deduplikacja bez względu na wielkość liter
        (["Java", "java"], '"Java"'),
        # nie-stringi i śmieci bez znaków alfanumerycznych odpadają
        ([None, 42, "---", "Go"], '"Go"'),
    ],
)
def test_bm25_or_query_escaping(terms, expected):
    from app.services.hybrid_search import bm25_or_query

    assert bm25_or_query(terms) == expected


def test_bm25_or_query_caps_the_term_count():
    from app.services.hybrid_search import _BM25_TERM_CAP, bm25_or_query

    out = bm25_or_query([f"skill{i}" for i in range(_BM25_TERM_CAP + 10)])
    assert out.count(" or ") == _BM25_TERM_CAP - 1


@pytest.mark.asyncio
async def test_or_query_is_a_disjunction_in_postgres():
    """Jedyny wiarygodny dowód, że zbudowany string NIE jest koniunkcją.

    Gdyby ktoś zamienił `or` na spację albo zgubił cudzysłowy, testy stringowe
    dalej przechodzą, a produkcja wraca do zera trafień — cicho.
    """
    from app.core.database import AsyncSessionLocal
    from app.services.hybrid_search import bm25_or_query

    async with AsyncSessionLocal() as db:
        query = bm25_or_query(["kubernetes", "nieobecnytokenzorba"])
        matched = await db.scalar(
            text(
                "SELECT to_tsvector('simple','kubernetes docker') @@ "
                "websearch_to_tsquery('simple', :q)"
            ),
            {"q": query},
        )
        # „or" przechodzi przez próg alfanumeryczny (2 znaki) i to jest
        # POPRAWNE: w cudzysłowie przestaje być operatorem i staje się
        # zwykłym leksemem. Próg pilnuje degeneracji „c++"→'c', nie operatorów
        # — od nich jest cudzysłowowanie.
        operator_as_lexeme = await db.scalar(
            text("SELECT websearch_to_tsquery('simple', :q)::text"),
            {"q": bm25_or_query(["or", "java"])},
        )

    assert matched is True
    assert operator_as_lexeme == "'or' | 'java'"
