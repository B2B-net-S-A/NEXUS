"""Runda 12 (SEARCH): umiejętności potwierdzone w screeningu poza samym korpusem.

Runda 11 dołożyła ``screening_notes.verified_skills`` (poziom „confirmed”) do
korpusu słów kluczowych. Zostały trzy miejsca, które ich nie widziały:

1. zakres słów kluczowych „Umiejętności” (``q_scope=skills``) — indeks wybierał
   osobę, a warunek pola ją odrzucał;
2. filtr „Umiejętności” (trzy kubełki) — WYŁĄCZNIE w semantyce v2; v1 ma dawać
   dokładnie te same wyniki co dotąd (zapisane wyszukiwania i alerty);
3. wycinki pod wynikiem — trafienie tylko w umiejętność ze screeningu nie
   dawało żadnego wycinka.

Jedna reguła źródła: ``keyword_corpus._screening_skills_from`` (element-obiekt,
poziom „confirmed”, sama nazwa) — korpus, zakres, filtr i wycinki.
"""

from __future__ import annotations

import random
import string
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.candidate import Candidate
from app.services import advanced_candidate_search as acs
from app.services import candidate_search_predicates as predicates
from app.services import keyword_corpus as kc
from app.services.candidate_snippets import extract_field_snippets
from app.services.keyword_terms import parse_keyword


def _sql(clause, *, literal: bool = True) -> str:
    kwargs = {"literal_binds": True} if literal else {}
    return str(
        select(Candidate.id)
        .where(clause)
        .compile(dialect=postgresql.dialect(), compile_kwargs=kwargs)
    )


# ── Bez bazy: jedna reguła źródła ───────────────────────────────────────────


def test_wiersze_i_korpus_czytaja_te_sama_regule() -> None:
    rows = kc.screening_skill_rows_sql()
    assert kc._screening_skills_from("TRUE") in rows
    assert kc._screening_skills_from("sn.candidate_id = NEW.id") in (
        kc.screening_skills_sql("NEW.id")
    )
    assert "e ->> 'level' = 'confirmed'" in rows
    assert "e ->> 'skill'" in rows
    # Bez surowego JSON-a (poziomy, notatki) i bez innych poziomów.
    assert "::text" not in rows
    assert "'basic'" not in rows and "'none'" not in rows


def test_lustro_w_pythonie_bierze_tylko_potwierdzone_nazwy() -> None:
    assert kc.screening_confirmed_skill_names(
        [
            {"skill": " Kafka ", "level": "confirmed", "notes": "notatka"},
            {"skill": "Go", "level": "basic"},
            {"skill": "Rust", "level": "none"},
            {"skill": "", "level": "confirmed"},
            "Python",
            {"skill": ["x"], "level": "confirmed"},
        ]
    ) == ["Kafka"]
    assert kc.screening_confirmed_skill_names(None) == []
    assert kc.screening_confirmed_skill_names("[]") == []


def test_skills_text_doklada_umiejetnosci_ze_screeningu() -> None:
    cand = SimpleNamespace(
        skills=[{"name": "Java", "level": "junior"}],
        verified_tech=None,
        cv_extracted_data=None,
    )
    assert kc.skills_text(cand) == "Java"
    assert kc.skills_text(cand, ["Kafka", "Spring Boot"]) == (
        "Java · Kafka, Spring Boot"
    )


# ── Bez bazy: filtr „Umiejętności” tylko w v2 ───────────────────────────────


def test_filtr_umiejetnosci_v1_bez_screeningu() -> None:
    """Kontrakt: v1 (i wołający bez semantyki) — dokładnie dotychczasowy SQL."""
    legacy_list = predicates.semantics_for("list", None)
    legacy_search = predicates.semantics_for("search", 1)
    baseline = _sql(
        predicates._json_token_match(
            predicates.func.lower(predicates.skills_text()), ["python"]
        )
    )
    for sem in (None, legacy_list, legacy_search):
        sql = _sql(predicates.skill_match("Python", sem))
        assert "screening_notes" not in sql
        assert sql == baseline


def test_filtr_umiejetnosci_v2_czyta_screening() -> None:
    for engine in ("list", "search"):
        sem = predicates.semantics_for(engine, 2)
        sql = _sql(predicates.skill_match("Python", sem))
        assert "FROM screening_notes AS sn" in sql
        assert "e ->> 'level' = 'confirmed'" in sql
        assert "lower(btrim(screening_skills.skill)) IN ('python')" in sql
        # Nieskorelowane: podzapytanie nie sięga po wiersz kandydata.
        assert "sn.candidate_id = candidates.id" not in sql


def test_kubelki_przekazuja_semantyke() -> None:
    buckets = predicates.skill_buckets_from_list(
        skills_required=["Python"],
        skills_excluded=["Rust"],
        skills_preferred=["Go"],
    )
    v2 = predicates.semantics_for("list", 2)
    v1 = predicates.semantics_for("list", None)
    for sem, expected in ((v1, False), (v2, True)):
        parts = [
            *predicates.skills_required_clauses(buckets, sem),
            *predicates.skills_excluded_clauses(buckets, sem),
            predicates.skills_preferred_rank(buckets, sem),
        ]
        for part in parts:
            assert ("screening_notes" in _sql(part)) is expected


# ── Bez bazy: zakres słów kluczowych „Umiejętności” ─────────────────────────


@pytest.mark.parametrize("folded", [False, True])
def test_zakres_umiejetnosci_widzi_screening(folded: bool) -> None:
    term = parse_keyword("kafka")
    assert term is not None
    with kc.force_folded_search(folded):
        skills = _sql(acs._whole_word_match(term, "skills"), literal=False)
        cv = _sql(acs._whole_word_match(term, "cv"), literal=False)
        title = _sql(acs._whole_word_match(term, "title"), literal=False)
    assert "FROM screening_notes AS sn" in skills
    assert "screening_skills.skill ~*" in skills
    assert "screening_notes" not in cv
    assert "screening_notes" not in title


# ── Bez bazy: wycinki ───────────────────────────────────────────────────────


def _candidate_stub(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        name: None
        for name in (
            "raw_cv_text",
            "experience",
            "skills",
            "verified_tech",
            "cv_extracted_data",
            "profile_about",
            "engagement_notes",
            "tags",
            "education",
            "languages",
            "linkedin_current_title",
            "linkedin_current_company",
            "location",
            "city",
            "email",
            "name",
            "lastname",
        )
    }
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("scope", ["all", "skills"])
def test_wycinek_z_umiejetnosci_ze_screeningu(scope: str) -> None:
    cand = _candidate_stub(name="Anna", lastname="Test")
    assert extract_field_snippets(cand, ["kafka"], scope=scope) == []
    snippets = extract_field_snippets(
        cand, ["kafka"], scope=scope, screening_skills=["Kafka"]
    )
    assert [s["field"] for s in snippets] == ["Umiejętności"]
    field = snippets[0]
    assert [field["text"][a:b] for a, b in field["highlights"]] == ["Kafka"]


def test_wycinek_innego_zakresu_nie_pokazuje_screeningu() -> None:
    cand = _candidate_stub()
    assert (
        extract_field_snippets(cand, ["kafka"], scope="cv", screening_skills=["Kafka"])
        == []
    )


# ── Przez Postgresa i prawdziwe endpointy ───────────────────────────────────


def _word(prefix: str) -> str:
    return prefix + "".join(random.choices(string.ascii_lowercase, k=10))


NONCE = _word("zr")


async def _candidate(**kw: Any) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import CandidateStatus

    async with AsyncSessionLocal() as db:
        row = Candidate(
            name="Screening",
            lastname=f"Zakres{uuid.uuid4().hex[:6]}",
            email=f"r12-screening-{uuid.uuid4().hex[:10]}@example.com",
            status=CandidateStatus.active,
            linkedin_current_company=NONCE,
            raw_cv_text="",
            **kw,
        )
        db.add(row)
        await db.commit()
        return row.id


async def _screening(client, headers, candidate_id: int, skills: list[dict]) -> None:
    resp = await client.post(
        "/api/screenings",
        json={"candidate_id": candidate_id, "verified_skills": skills},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text


async def _list(client, headers, params: list[tuple[str, Any]]) -> dict:
    resp = await client.get(
        "/api/candidates",
        params=[("q", NONCE), ("text_mode", "literal"), ("page_size", 100), *params],
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture(params=[False, True], ids=["stara-sciezka", "korpus-zlozony"])
def mode(request, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "KEYWORD_SEARCH_FOLDED_FTS", request.param)
    monkeypatch.setattr(kc, "_ready", True)
    monkeypatch.setattr(kc, "_fold_ready", request.param)
    monkeypatch.setattr(kc, "_notes_ready", request.param)
    return request.param


@pytest.mark.asyncio
async def test_zakres_umiejetnosci_i_wycinek_przez_liste(
    app_client, app_auth_headers, mode
):
    skill = _word("zq")
    with_skill = await _candidate()
    basic_only = await _candidate()
    await _screening(
        app_client,
        app_auth_headers,
        with_skill,
        [{"skill": skill.capitalize(), "level": "confirmed"}],
    )
    await _screening(
        app_client, app_auth_headers, basic_only, [{"skill": skill, "level": "basic"}]
    )

    body = await _list(
        app_client,
        app_auth_headers,
        [("semantics_version", 2), ("q_any_group", skill), ("q_scope", "skills")],
    )
    items = {item["id"]: item for item in body["items"]}
    assert with_skill in items
    assert basic_only not in items
    fields = {s["field"]: s for s in items[with_skill]["match_snippets"] or []}
    assert "Umiejętności" in fields
    field = fields["Umiejętności"]
    assert [field["text"][a:b] for a, b in field["highlights"]] == [skill.capitalize()]


@pytest.mark.asyncio
async def test_filtr_umiejetnosci_v2_znajduje_screening_v1_nie(
    app_client, app_auth_headers
):
    skill = _word("zw")
    with_skill = await _candidate()
    basic_only = await _candidate()
    # Kontrola, że zapytanie v1 w ogóle kogoś znajduje (zbiór pusty nie dowodzi
    # niczego): umiejętność zapisana w profilu.
    in_profile = await _candidate(skills=[{"name": skill.capitalize()}])
    await _screening(
        app_client,
        app_auth_headers,
        with_skill,
        [{"skill": skill.capitalize(), "level": "confirmed"}],
    )
    await _screening(
        app_client, app_auth_headers, basic_only, [{"skill": skill, "level": "basic"}]
    )

    v2 = await _list(
        app_client,
        app_auth_headers,
        [("semantics_version", 2), ("skills_required", skill)],
    )
    assert {i["id"] for i in v2["items"]} & {with_skill, basic_only, in_profile} == {
        with_skill,
        in_profile,
    }

    # v1 — dokładnie dotychczasowy wynik: screening się nie liczy.
    v1 = await _list(app_client, app_auth_headers, [("skills", skill)])
    assert {i["id"] for i in v1["items"]} & {with_skill, basic_only, in_profile} == {
        in_profile
    }

    # „Wyklucz” w v2 wycina osobę z potwierdzoną umiejętnością.
    excluded = await _list(
        app_client,
        app_auth_headers,
        [("semantics_version", 2), ("skills_excluded", skill)],
    )
    ids = {i["id"] for i in excluded["items"]}
    assert with_skill not in ids and basic_only in ids

    # Wyszukiwarka (S): ta sama reguła w v2, bez zmian w v1.
    def payload(version: int | None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "q_all": [NONCE],
            "page": 1,
            "page_size": 200,
            "skills_required": [skill],
        }
        if version is not None:
            body["semantics_version"] = version
        return body

    s2 = await app_client.post(
        "/api/search/candidates", json=payload(2), headers=app_auth_headers
    )
    assert s2.status_code == 200, s2.text
    assert {i["id"] for i in s2.json()["items"]} & {
        with_skill,
        basic_only,
        in_profile,
    } == {with_skill, in_profile}
    s1 = await app_client.post(
        "/api/search/candidates", json=payload(None), headers=app_auth_headers
    )
    assert s1.status_code == 200, s1.text
    assert {i["id"] for i in s1.json()["items"]} & {
        with_skill,
        basic_only,
        in_profile,
    } == {in_profile}
