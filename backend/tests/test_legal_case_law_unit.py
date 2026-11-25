"""Orzecznictwo asystenta prawnego (część C): klienci źródeł, parser, wyszukiwanie.

Bez bazy i bez sieci: odpowiedzi SAOS z ``tests/fixtures/legal_case_law``
(dane fikcyjne), transport ``httpx.MockTransport``, baza podmieniona.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.services.legal_case_law import http as source_http
from app.services.legal_case_law import index, ingest, links, saos, schema, search
from app.services.legal_case_law.passage import SourcePassage

FIXTURES = Path(__file__).parent / "fixtures" / "legal_case_law"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(source_http, "BACKOFF_SECONDS", 0.0)


def _client(handler: Any) -> source_http.PoliteClient:
    return source_http.PoliteClient(
        name="saos",
        min_interval=0.0,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


# ── parser SAOS ─────────────────────────────────────────────────────────────


def test_supreme_court_judgment_is_parsed_from_plain_text() -> None:
    record = saos.parse_judgment(_fixture("saos_judgment_sn.json")["data"])
    assert record is not None
    assert record.source == "saos"
    assert record.source_id == "900001"
    assert record.signature == "IV CSK 999/09"
    assert record.court == "Sąd Najwyższy — Izba Cywilna"
    assert record.court_type == "supreme"
    assert record.kind == "judgment"
    assert record.judgment_date == date(2010, 4, 16)
    assert record.url == "https://www.saos.org.pl/judgments/900001"
    assert record.summary is None
    assert "art. 484 § 2 k.c." in record.text
    assert len(record.content_sha256) == 64


def test_common_court_judgment_html_becomes_text() -> None:
    record = saos.parse_judgment(_fixture("saos_judgment_cc.json")["data"])
    assert record is not None
    assert record.court == "Sąd Apelacyjny w Mieście X"
    assert record.court_type == "common"
    assert "<" not in record.text
    assert "Sąd Apelacyjny w Mieście X & Y" in record.text
    assert "o zapłatę" in record.text
    assert record.summary == "Teza: kara umowna za zwłokę podlega miarkowaniu."


@pytest.mark.parametrize(
    "change",
    [
        {"textContent": ""},
        {"courtCases": []},
        {"courtType": "UNKNOWN"},
        {"id": None},
    ],
)
def test_judgment_without_text_signature_or_known_court_is_skipped(
    change: dict[str, Any],
) -> None:
    data = {**_fixture("saos_judgment_sn.json")["data"], **change}
    assert saos.parse_judgment(data) is None


def test_content_hash_follows_text_and_summary() -> None:
    record = saos.parse_judgment(_fixture("saos_judgment_sn.json")["data"])
    assert record is not None
    from dataclasses import replace

    assert replace(record, topics=("x",)).content_sha256 == record.content_sha256
    assert replace(record, text=record.text + ".").content_sha256 != record.content_sha256


def test_search_params_map_court_and_date() -> None:
    params = saos.search_params(
        "kara umowna", court_type="supreme", since=date(2020, 1, 1), page_size=500
    )
    assert params["courtType"] == "SUPREME"
    assert params["judgmentDateFrom"] == "2020-01-01"
    assert params["pageSize"] == saos.MAX_PAGE_SIZE
    assert params["sortingField"] == "REFERENCING_JUDGMENTS_COUNT"


def test_search_ids_skip_items_without_id() -> None:
    assert saos.parse_search_ids(_fixture("saos_search.json")) == [900001, 900002]
    assert saos.parse_search_ids(None) == []


# ── klient HTTP: awaria źródła = pusta lista, nie wyjątek ──────────────────


async def test_search_and_fetch_use_recorded_responses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/search/judgments":
            assert request.url.params["all"] == "kara umowna"
            return httpx.Response(200, json=_fixture("saos_search.json"))
        number = request.url.path.rsplit("/", 1)[-1]
        name = {"900001": "saos_judgment_sn.json", "900002": "saos_judgment_cc.json"}
        return httpx.Response(200, json=_fixture(name[number]))

    async with _client(handler) as client:
        ids = await saos.search_ids(client, "kara umowna", court_type="supreme")
        records = await saos.fetch_many(client, ids)
    assert [r.signature for r in records] == ["IV CSK 999/09", "I AGa 999/23"]


async def test_server_error_is_retried_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=_fixture("saos_search.json"))

    async with _client(handler) as client:
        ids = await saos.search_ids(client, "kara umowna")
    assert ids == [900001, 900002]
    assert calls["n"] == 2


@pytest.mark.parametrize(
    "response",
    [
        lambda: httpx.Response(500),
        lambda: httpx.Response(429, headers={"Retry-After": "0"}),
        lambda: httpx.Response(200, text="<html>nie JSON</html>"),
        lambda: httpx.Response(403),
    ],
)
async def test_source_failure_gives_empty_list_not_exception(response: Any) -> None:
    async with _client(lambda request: response()) as client:
        assert await saos.search_ids(client, "kara umowna") == []
        assert await saos.fetch_judgment(client, 900001) is None
        assert client.errors >= 1


async def test_network_error_gives_empty_list_after_retries() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("brak połączenia", request=request)

    async with _client(handler) as client:
        assert await saos.search_ids(client, "kara umowna") == []
    assert calls["n"] == source_http.RETRIES + 1


async def test_missing_judgment_is_none_without_error() -> None:
    async with _client(lambda request: httpx.Response(404)) as client:
        assert await saos.fetch_judgment(client, 1) is None
        assert client.errors == 0


def test_retry_after_is_capped() -> None:
    response = httpx.Response(429, headers={"Retry-After": "3600"})
    assert source_http._retry_after(response, 1.0) == source_http.MAX_RETRY_AFTER
    assert source_http._retry_after(httpx.Response(429), 1.5) == 1.5


async def test_own_client_sends_application_user_agent_without_personal_data() -> None:
    async with saos.new_client() as client:
        assert client.client is not None
        agent = client.client.headers["User-Agent"]
    assert agent == source_http.USER_AGENT
    assert "@" not in agent and "http" not in agent


# ── wyszukiwanie w pamięci ─────────────────────────────────────────────────


def _row(case_id: int, **extra: Any) -> SimpleNamespace:
    base = {
        "id": case_id,
        "signature": f"I ABC {case_id}/24",
        "court": "Sąd Apelacyjny w Mieście X — Izba Fikcyjna",
        "court_type": "common",
        "judgment_date": date(2024, 5, 24),
        "kind": "judgment",
        "url": f"https://www.saos.org.pl/judgments/{case_id}",
        "summary": None,
        "text": f"Krótki tekst nr {case_id} o miarkowaniu kary umownej.",
        "content_sha256": f"hash-{case_id}",
    }
    return SimpleNamespace(**{**base, **extra})


class _Result:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> list[Any]:
        return self._items


class _FakeDb:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    async def execute(self, _stmt: Any) -> _Result:
        return _Result(self.rows)


async def test_query_without_words_returns_nothing_without_touching_db() -> None:
    outcome = await search.search_case_law_outcome(None, "i a w", limit=5)  # type: ignore[arg-type]
    assert outcome.passages == [] and outcome.retrieval == search.RETRIEVAL_NONE


async def test_keywords_only_when_vectors_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def keywords(*_args: Any) -> list[int]:
        return [2, 1]

    async def no_vectors(_query: str) -> None:
        return None

    monkeypatch.setattr(search, "keyword_ranking", keywords)
    monkeypatch.setattr(index, "vector_ranking", no_vectors)
    db = _FakeDb([_row(1), _row(2)])
    passages = await search.search_case_law(db, "kara umowna miarkowanie", limit=5)  # type: ignore[arg-type]
    assert [p.ref for p in passages] == ["I ABC 2/24", "I ABC 1/24"]
    assert all(isinstance(p, SourcePassage) and p.kind == "case" for p in passages)
    assert passages[0].label == "Sąd Apelacyjny w Mieście X, wyrok z 24.05.2024 r., I ABC 2/24"


async def test_vectors_fuse_with_keywords(monkeypatch: pytest.MonkeyPatch) -> None:
    async def keywords(*_args: Any) -> list[int]:
        return [1, 2]

    async def vectors(_query: str) -> list[int]:
        return [3, 1]

    monkeypatch.setattr(search, "keyword_ranking", keywords)
    monkeypatch.setattr(index, "vector_ranking", vectors)

    class _Db(_FakeDb):
        calls = 0

        async def execute(self, _stmt: Any) -> _Result:
            self.calls += 1
            if self.calls == 1:  # filtr id z wektorów
                return _Result([1, 3])
            return _Result(self.rows)

    db = _Db([_row(1), _row(2), _row(3)])
    outcome = await search.search_case_law_outcome(db, "zakaz konkurencji", limit=2)  # type: ignore[arg-type]
    assert outcome.retrieval == search.RETRIEVAL_HYBRID
    assert [p.ref for p in outcome.passages] == ["I ABC 1/24", "I ABC 3/24"]


def test_supreme_court_label_and_summary_first() -> None:
    row = _row(
        7,
        court="Sąd Najwyższy — Izba Pracy",
        court_type="supreme",
        kind="resolution",
        summary="Teza fikcyjna.",
    )
    passage = search.to_passage(row, ["kara"])  # type: ignore[arg-type]
    assert passage.label == "SN, uchwała z 24.05.2024 r., I ABC 7/24"
    assert passage.text.startswith("Teza fikcyjna.\n\n")


def test_excerpt_centres_on_first_query_word() -> None:
    text = ("Wstęp bez znaczenia. " * 120) + "Sąd uznał, że miarkowanie kary umownej jest możliwe. " + (
        "Dalszy tekst. " * 120
    )
    piece = search.excerpt(text, ["miark"], size=300)
    assert "miarkowanie kary umownej" in piece
    assert piece.startswith("… ") and piece.endswith(" …")
    assert len(piece) <= 300 + 4


def test_excerpt_prefers_window_with_most_query_words() -> None:
    header = "Sąd w składzie: przewodniczący, protokolant Kara. " + ("Tekst wstępny. " * 80)
    body = "Sąd uznał, że miarkowanie kary umownej rażąco wygórowanej jest zasadne. "
    text = header + body + ("Dalszy tekst. " * 80)
    piece = search.excerpt(text, ["kar", "umown", "miark"], size=300)
    assert "miarkowanie kary umownej" in piece
    assert "protokolant" not in piece


async def test_same_text_under_two_signatures_is_shown_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def keywords(*_args: Any) -> list[int]:
        return [1, 4, 2, 3]

    async def no_vectors(_query: str) -> None:
        return None

    monkeypatch.setattr(search, "keyword_ranking", keywords)
    monkeypatch.setattr(index, "vector_ranking", no_vectors)
    db = _FakeDb([_row(1), _row(2, content_sha256="hash-1"), _row(3)])
    # Ten sam tekst pod inną sygnaturą też odpada (skrót treści bywa inny o spację).
    long_text = "Uzasadnienie o miarkowaniu kary umownej. " * 40
    db.rows[0] = _row(1, text=long_text)
    db.rows.append(_row(4, text=long_text + "\n\nDopisek  sądu I instancji."))
    passages = await search.search_case_law(db, "kara umowna", limit=2)  # type: ignore[arg-type]
    assert [p.ref for p in passages] == ["I ABC 1/24", "I ABC 3/24"]


def test_excerpt_survives_characters_that_fold_longer() -> None:
    text = ("Wstęp… " * 200) + "miarkowanie kary umownej " + ("koniec… " * 200)
    piece = search.excerpt(text, ["miark", "kar"], size=200)
    assert "miarkowanie kary umownej" in piece
    assert len(search.fold_same_length(text)) == len(text)


def test_excerpt_without_hit_starts_at_beginning() -> None:
    text = "Początek. " + ("słowo " * 400)
    piece = search.excerpt(text, ["zzzz"], size=100)
    assert piece.startswith("Początek.")


def test_unknown_court_filter_values_are_dropped() -> None:
    assert search.normalize_courts(["supreme", "nieznany"]) == frozenset({"supreme"})
    assert search.normalize_courts(["nieznany"]) is None
    assert search.normalize_courts(None) is None


def test_links_for_sources_without_api() -> None:
    assert {link.source for link in links.search_links(None)} == {"cbosa", "eureka", "sn"}
    assert {link.source for link in links.search_links(frozenset({"administrative"}))} == {
        "cbosa",
        "eureka",
    }
    assert [link.source for link in links.search_links(frozenset({"common"}))] == []
    for link in links.LINKS:
        assert link.url.startswith("https://") and "?" not in link.url


# ── zasilenie ──────────────────────────────────────────────────────────────


async def test_ingest_topic_tags_records_and_skips_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored: list[Any] = []

    async def fake_store(_db: Any, records: Any) -> Any:
        stored.extend(records)
        return SimpleNamespace(inserted=len(records), updated=0, unchanged=0)

    monkeypatch.setattr(ingest, "store_records", fake_store)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/search/judgments":
            return httpx.Response(200, json=_fixture("saos_search.json"))
        number = request.url.path.rsplit("/", 1)[-1]
        name = {"900001": "saos_judgment_sn.json", "900002": "saos_judgment_cc.json"}
        return httpx.Response(200, json=_fixture(name[number]))

    class _Db:
        commits = 0

        async def commit(self) -> None:
            self.commits += 1

    db = _Db()
    topic = ingest.TOPICS[2]
    async with _client(handler) as client:
        report = await ingest.ingest_topic(db, client, topic, per_query=5)  # type: ignore[arg-type]
    # Trzy zapytania tematu zwracają te same dwa orzeczenia — pobrane raz.
    assert report.found == 6 and report.fetched == 2 and report.inserted == 2
    assert {r.topics for r in stored} == {(topic.key,)}
    assert db.commits == 1


async def test_ingest_survives_dead_source(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_store(_db: Any, records: Any) -> Any:
        assert records == []
        return SimpleNamespace(inserted=0, updated=0, unchanged=0)

    monkeypatch.setattr(ingest, "store_records", fake_store)

    class _Db:
        async def commit(self) -> None:
            return None

    async with _client(lambda request: httpx.Response(502)) as client:
        report = await ingest.ingest_topic(_Db(), client, ingest.TOPICS[0])  # type: ignore[arg-type]
    assert report.found == 0 and report.fetched == 0


def test_topics_cover_plan_and_use_known_courts() -> None:
    keys = {topic.key for topic in ingest.TOPICS}
    assert keys == {
        "b2b_employment",
        "copyright_transfer",
        "penalty_reduction",
        "service_termination",
        "non_compete",
    }
    for topic in ingest.TOPICS:
        assert len(topic.key) <= schema.TOPIC_MAX
        for query in topic.queries:
            assert query.court_type in saos.COURT_TYPES


# ── schemat ────────────────────────────────────────────────────────────────


def test_schema_is_mirrored_in_entrypoint_bundle_and_model() -> None:
    from app.models.legal_case_law import LegalCase
    from app.services import hr_schema_bundle

    for stmt in schema.TABLE_DDL + schema.INDEX_DDL:
        assert stmt in hr_schema_bundle.COLUMN_DDL
    checks = {
        c.name: str(c.sqltext)
        for c in LegalCase.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint"
    }
    assert checks == {
        "ck_legal_cases_source": schema.CK_SOURCE,
        "ck_legal_cases_court_type": schema.CK_COURT_TYPE,
        "ck_legal_cases_kind": schema.CK_KIND,
        "ck_legal_cases_topics": schema.CK_TOPICS,
    }
    for value in saos.COURT_TYPES:
        assert value in schema.COURT_TYPES
    assert set(saos._KINDS.values()) <= set(schema.KINDS)


def test_migration_reads_the_same_ddl() -> None:
    import importlib.util

    path = Path(__file__).parents[1] / "alembic" / "versions" / "0786_legal_case_law.py"
    spec = importlib.util.spec_from_file_location("m0781", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    assert module.revision == "0786_legal_case_law"
    assert module.down_revision == "0785_custom_document_templates"
    assert module.schema.ALL_DDL is schema.ALL_DDL


def test_route_is_gated_like_the_rest_of_legal_api() -> None:
    from app.api import legal_case_law as api

    route = next(r for r in api.router.routes if r.path == "/cases/search")
    names = {getattr(d.call, "__qualname__", "") for d in route.dependant.dependencies}
    assert any("require_b2b_generator_access" in name for name in names)
    assert any("require_section_access" in name for name in {
        getattr(d.dependency, "__qualname__", "") for d in api.router.dependencies
    })
