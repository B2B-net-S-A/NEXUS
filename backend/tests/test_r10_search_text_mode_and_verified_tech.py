"""Runda 10 (Codex, manualne testy UI 26–27.09.2026) — wyszukiwanie kandydatów.

* F06: jedno słowo z cyframi („UIAZ20260926”), które jest CAŁYM nazwiskiem
  kandydata, szło w trybie auto od razu po znaczeniu (199 osób zamiast 1).
  Teraz o trybie rozstrzyga baza, jak przy zwykłym pojedynczym słowie.
* F17: „Zweryfikowane technologie” (``verified_tech``) — profil pokazuje je
  w sekcji „Umiejętności”, filtr „Umiejętności” je znajduje, a słowa kluczowe
  ich nie widziały (kolumny nie było w korpusie ani w zakresie „Umiejętności”).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

from app.services import candidate_search_predicates as p
from app.services import keyword_corpus as kc

# ── F06: tryb tekstu ────────────────────────────────────────────────────────


@pytest.mark.parametrize("q", ["UIAZ20260926", "Kowalski2", "abc123", "Nowak-2"])
def test_slowo_z_cyframi_czeka_na_sprawdzenie_w_bazie(q: str) -> None:
    found = p.detect_text_mode(q)
    assert found.rule == "single_word_unchecked"
    assert found.name_tokens == (q,)


@pytest.mark.parametrize("q", ["12345", "2026", "UIAZ 2026", "a1 b2 c3 d4"])
def test_same_cyfry_i_kilka_slow_z_cyframi_zostaja_opisem(q: str) -> None:
    found = p.detect_text_mode(q)
    assert found.mode == "semantic"


@pytest.mark.asyncio
async def test_nazwisko_z_cyframi_w_bazie_idzie_doslownie(monkeypatch) -> None:
    async def exists(_db: Any, token: str) -> bool:
        return token == "UIAZ20260926"

    monkeypatch.setattr(p, "person_token_exists", exists)
    found = await p.interpret_text(object(), "UIAZ20260926")
    assert found.rule == "single_word_person_exists"
    assert found.mode == "literal"
    v2 = p.semantics_for("list", 2)
    assert p.text_mode_to_apply(v2, "auto", found) == "literal"

    missing = await p.interpret_text(object(), "ABC123")
    assert missing.rule == "single_word_no_person"
    assert missing.mode == "semantic"


# ── F17: korpus słów kluczowych ─────────────────────────────────────────────


def test_korpus_obejmuje_zweryfikowane_technologie() -> None:
    assert ("verified_tech", kc.VERIFIED_TECH_KEYS) in kc.JSON_COLUMNS
    assert "verified_tech" in kc.SOURCE_COLUMNS
    assert (
        f"{kc.JSON_TEXT_FUNCTION}(NEW.verified_tech, ARRAY['name', 'tech', 'skill'])"
        in kc.TRIGGER_FUNCTION_DDL
    )
    assert "verified_tech" in kc.TRIGGER_DDL
    assert kc.CORPUS_SOURCES_MARKER_COLUMN in kc.TRIGGER_FUNCTION_DDL


def test_lustro_w_pythonie_bierze_zweryfikowane_technologie() -> None:
    cand = SimpleNamespace(
        skills=[{"name": "Java", "level": "junior"}],
        verified_tech=["Python", {"name": "PostgreSQL", "level": "confirmed"}],
        cv_extracted_data={"traffit_technologie": "Kafka"},
    )
    assert kc.skills_text(cand) == "Java · Python PostgreSQL · Kafka"
    assert kc.skills_text(SimpleNamespace(skills=None, verified_tech=None)) == ""


def test_zakres_umiejetnosci_czyta_verified_tech() -> None:
    from sqlalchemy.dialects import postgresql

    from app.services.advanced_candidate_search import _skill_names_text

    sql = str(_skill_names_text().compile(dialect=postgresql.dialect()))
    assert "verified_tech" in sql
    assert "$[*].tech" in sql and "$[*].skill" in sql


# ── Przez prawdziwy endpoint i Postgresa ────────────────────────────────────

NONCE = "zv" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])
_IDS: dict[str, int] = {}


async def _seed() -> dict[str, int]:
    if _IDS:
        return _IDS
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    def person(key: str, **kw: Any) -> Candidate:
        return Candidate(
            name=key.capitalize(),
            lastname=f"Zweryfikowany{key}",
            email=f"{key}-{uuid.uuid4().hex[:10]}@example.com",
            status=CandidateStatus.active,
            linkedin_current_company=NONCE,
            raw_cv_text="",
            **kw,
        )

    async with AsyncSessionLocal() as db:
        rows = {
            "verified": person("verified", verified_tech=["Python", "PostgreSQL"]),
            "objects": person("objects", verified_tech=[{"name": "Kotlin"}]),
            "other": person("other", skills=[{"name": "Java"}]),
        }
        db.add_all(rows.values())
        await db.commit()
        for key, row in rows.items():
            _IDS[key] = row.id
    return _IDS


async def _keys(client, headers, **params: Any) -> set[str]:
    await _seed()
    query: list[tuple[str, Any]] = [
        ("q", NONCE),
        ("text_mode", "literal"),
        ("page_size", 100),
        ("semantics_version", 2),
    ]
    for key, value in params.items():
        if isinstance(value, (list, tuple)):
            query.extend((key, v) for v in value)
        else:
            query.append((key, value))
    resp = await client.get("/api/candidates", params=query, headers=headers)
    assert resp.status_code == 200, resp.text
    by_id = {v: k for k, v in _IDS.items()}
    return {by_id[i["id"]] for i in resp.json()["items"] if i["id"] in by_id}


@pytest.fixture(params=[False, True], ids=["stara-sciezka", "korpus-zlozony"])
def mode(request, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "KEYWORD_SEARCH_FOLDED_FTS", request.param)
    monkeypatch.setattr(kc, "_ready", True)
    monkeypatch.setattr(kc, "_fold_ready", request.param)
    monkeypatch.setattr(kc, "_notes_ready", request.param)
    return request.param


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["all", "skills"])
async def test_slowo_kluczowe_znajduje_zweryfikowana_technologie(
    app_client, app_auth_headers, mode, scope
):
    found = await _keys(
        app_client, app_auth_headers, q_any_group="python", q_scope=scope
    )
    assert "verified" in found
    assert "other" not in found
    both = await _keys(
        app_client,
        app_auth_headers,
        q_any_group=["python", "postgresql"],
        q_scope=scope,
    )
    assert "verified" in both
    assert "verified" not in await _keys(
        app_client, app_auth_headers, q_any_group="java", q_scope=scope
    )
    assert "objects" in await _keys(
        app_client, app_auth_headers, q_any_group="kotlin", q_scope=scope
    )


@pytest.mark.asyncio
async def test_przeliczenie_starych_wierszy_doklada_verified_tech(monkeypatch):
    """Wiersz z korpusem policzonym starą listą pól dostaje nowe słowa."""
    from app.core.database import AsyncSessionLocal
    from app.tasks import keyword_corpus_backfill as loop

    ids = await _seed()
    async with AsyncSessionLocal() as db:
        # Korpus „sprzed” rundy 10: bez słów z verified_tech. Kolumny korpusu
        # nie są na liście ``UPDATE OF`` triggera, więc zapis przeżywa.
        await db.execute(
            text(
                "UPDATE candidates SET keyword_fts = to_tsvector('simple', 'stary'),"
                " keyword_fold_fts = to_tsvector('simple', 'stary') WHERE id = :id"
            ),
            {"id": ids["verified"]},
        )
        await db.commit()

    async def never_done() -> None:
        return None

    monkeypatch.setattr(loop, "_stored_sources_version", never_done)
    await loop._sources_phase()

    async with AsyncSessionLocal() as db:
        fts, fold = (
            await db.execute(
                text(
                    "SELECT keyword_fts::text, keyword_fold_fts::text"
                    " FROM candidates WHERE id = :id"
                ),
                {"id": ids["verified"]},
            )
        ).one()
    assert "'python'" in fts and "'python'" in fold
    assert "'postgresql'" in fold


@pytest.mark.asyncio
async def test_faza_zrodel_staje_przy_starym_triggerze(monkeypatch):
    from app.tasks import keyword_corpus_backfill as loop

    async def never_done() -> None:
        return None

    async def old_trigger() -> bool:
        return False

    monkeypatch.setattr(loop, "_stored_sources_version", never_done)
    monkeypatch.setattr(loop, "_db_trigger_has_sources", old_trigger)
    with pytest.raises(loop.CorpusTriggerOutdated):
        await loop._sources_phase()
