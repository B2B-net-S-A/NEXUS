"""Korpus złożony (migracja 0385) — przez prawdziwy endpoint i Postgresa.

Audyt szybkości wyszukiwania (25.09.2026): regex po ``keyword_doc`` zjadał
68% czasu słowa kluczowego. Nowa ścieżka (``KEYWORD_SEARCH_FOLDED_FTS``) ma
znajdować TE SAME osoby co stara, z trzema świadomymi różnicami na plus:

* „lodz” znajduje „Łódź” także w CV (dawniej wersja bez polskich znaków
  obejmowała tylko profil);
* „scrum” znajduje „Agile/Scrum” (parser tsvector trzymał to jako jedno słowo);
* notatka zapisana przez import z Traffita jako JSON (``Toru\\u0144``) jest
  przeszukiwalna po polskich literach.

Baza testowa jest wspólna: każde żądanie zawęża się frazą ``NONCE`` w ``q``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text

NONCE = "zf" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])
_IDS: dict[str, int] = {}


async def _seed() -> dict[str, int]:
    if _IDS:
        return _IDS
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.note import Note

    def person(key: str, cv: str = "", **kw: Any) -> Candidate:
        return Candidate(
            name=key.capitalize(),
            lastname=f"Zlozony{key}",
            email=f"{key}-{uuid.uuid4().hex[:10]}@example.com",
            status=CandidateStatus.active,
            linkedin_current_company=NONCE,
            raw_cv_text=cv,
            **kw,
        )

    async with AsyncSessionLocal() as db:
        rows = {
            "java": person("java", "Java 17, Spring Boot, Hibernate."),
            "javascript": person("javascript", "JavaScript, TypeScript, React."),
            "csharp": person("csharp", "Backend: C#/.NET 6, C++17, F#."),
            "cletter": person("cletter", "Języki: C i Python."),
            "aspnet": person("aspnet", "ASP.NET Core, VB.NET."),
            "consent": person(
                "consent", "Tester. Zgoda na przetwarzanie przez B2B.net S.A."
            ),
            "vue": person("vue", "Frontend: Vue.js, Node.js."),
            "krakow": person("krakow", "Analityk.", city="Kraków"),
            "cvcity": person("cvcity", "Lokalizacja: Łódź, praca zdalna."),
            "agile": person("agile", "Praca w Agile/Scrum, CI/CD w GitLab."),
            "hyphen": person("hyphen", "Operated within CI/CD-driven environments."),
            "noted": person("noted", "Programista."),
            # Litera + osobny znak akcentu (U+0301, U+0328) — tak zapisują CV
            # niektóre PDF-y; do 0387 składanie ich nie widziało.
            "decomposed": person(
                "decomposed",
                "Mieszkam w Lo\u0301dz\u0301, zarza\u0328dzanie projektami.",
            ),
            # Kandydat 34020 na produkcji: `<script>…</script>` w CV. Ukośnik jako
            # spacja zamieniał `</script>` w `< script>`, więc parser tsvector nie
            # znajdował końca „skryptu” i połykał resztę CV razem z „Łódź”.
            "script": person(
                "script",
                "Niebezpiecznik.pl <script>alert('Performance Test Engineer')</script>"
                " / trainer\nsierpien 2017 - czerwiec 2020\nArea, Poland / Łódź Area",
            ),
        }
        db.add_all(rows.values())
        await db.flush()
        wrapped = json.dumps(
            {
                "content": "<div><p>Kandydat z Toruń, zna Kotlin</p></div>",
                "state": {"id": 38, "name": "Przepuszczony"},
            }
        )
        db.add(Note(candidate_id=rows["noted"].id, content=wrapped))
        db.add(
            Note(
                candidate_id=rows["decomposed"].id,
                content="Kandydat z Gdan\u0301ska, zna Terraform.",
            )
        )
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


@pytest.fixture
def folded(monkeypatch):
    """Nowa ścieżka: przełącznik ON i obie kolumny „gotowe”."""
    from app.core.config import settings
    from app.services import keyword_corpus

    monkeypatch.setattr(settings, "KEYWORD_SEARCH_FOLDED_FTS", True)
    monkeypatch.setattr(keyword_corpus, "_ready", True)
    monkeypatch.setattr(keyword_corpus, "_fold_ready", True)
    monkeypatch.setattr(keyword_corpus, "_notes_ready", True)


@pytest.fixture(params=[False, True], ids=["stara-sciezka", "korpus-zlozony"])
def mode(request, monkeypatch):
    from app.core.config import settings
    from app.services import keyword_corpus

    monkeypatch.setattr(settings, "KEYWORD_SEARCH_FOLDED_FTS", request.param)
    monkeypatch.setattr(keyword_corpus, "_ready", True)
    monkeypatch.setattr(keyword_corpus, "_fold_ready", request.param)
    monkeypatch.setattr(keyword_corpus, "_notes_ready", request.param)
    return request.param


# ── Te same wyniki w obu ścieżkach ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_java_is_a_whole_word_not_javascript(app_client, app_auth_headers, mode):
    found = await _keys(app_client, app_auth_headers, q_any_group="java")
    assert "java" in found
    assert "javascript" not in found


@pytest.mark.asyncio
async def test_java_prefix_finds_javascript(app_client, app_auth_headers, mode):
    found = await _keys(app_client, app_auth_headers, q_any_group="java*")
    assert {"java", "javascript"} <= found


@pytest.mark.asyncio
async def test_phrase_spring_boot(app_client, app_auth_headers, mode):
    assert "java" in await _keys(
        app_client, app_auth_headers, q_any_group="spring boot"
    )


@pytest.mark.asyncio
async def test_special_tokens(app_client, app_auth_headers, mode):
    csharp = await _keys(app_client, app_auth_headers, q_any_group="c#")
    assert "csharp" in csharp
    assert "cletter" not in csharp
    assert "csharp" in await _keys(app_client, app_auth_headers, q_any_group="c++")
    assert "csharp" in await _keys(app_client, app_auth_headers, q_any_group="f#")


@pytest.mark.asyncio
async def test_dotnet_skips_the_consent_clause(app_client, app_auth_headers, mode):
    found = await _keys(app_client, app_auth_headers, q_any_group=".net")
    assert {"csharp", "aspnet"} <= found
    assert "consent" not in found
    assert "aspnet" in await _keys(app_client, app_auth_headers, q_any_group="asp.net")


@pytest.mark.asyncio
async def test_vue_finds_vue_js(app_client, app_auth_headers, mode):
    assert "vue" in await _keys(app_client, app_auth_headers, q_any_group="vue")
    assert "vue" in await _keys(app_client, app_auth_headers, q_any_group="node.js")


@pytest.mark.asyncio
async def test_city_in_profile_without_polish_letters(
    app_client, app_auth_headers, mode
):
    assert "krakow" in await _keys(app_client, app_auth_headers, q_any_group="krakow")
    assert "krakow" in await _keys(app_client, app_auth_headers, q_any_group="kraków")


@pytest.mark.asyncio
async def test_exclude_bucket(app_client, app_auth_headers, mode):
    found = await _keys(app_client, app_auth_headers, q_none="c#")
    assert "csharp" not in found
    assert "java" in found


@pytest.mark.asyncio
async def test_scope_cv_keeps_the_field_check(app_client, app_auth_headers, mode):
    assert "csharp" in await _keys(
        app_client, app_auth_headers, q_any_group="c#", q_scope="cv"
    )
    assert "krakow" not in await _keys(
        app_client, app_auth_headers, q_any_group="krakow", q_scope="cv"
    )


@pytest.mark.asyncio
async def test_notes_scope_plain_word(app_client, app_auth_headers, mode):
    assert "noted" in await _keys(
        app_client, app_auth_headers, q_any_group="kotlin", q_scope="notes"
    )


# ── Świadome różnice nowej ścieżki ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_folded_finds_polish_city_in_cv(app_client, app_auth_headers, folded):
    assert "cvcity" in await _keys(app_client, app_auth_headers, q_any_group="lodz")


@pytest.mark.asyncio
async def test_folded_splits_slash(app_client, app_auth_headers, folded):
    assert "agile" in await _keys(app_client, app_auth_headers, q_any_group="scrum")
    assert "agile" in await _keys(app_client, app_auth_headers, q_any_group="ci/cd")


@pytest.mark.asyncio
async def test_folded_joins_phrases_across_hyphens(
    app_client, app_auth_headers, folded
):
    """Wersja 2 składania (0386): myślnik to spacja — „CI/CD-driven” pasuje
    do „ci/cd”, a „spring-boot” do „Spring Boot”."""
    assert "hyphen" in await _keys(app_client, app_auth_headers, q_any_group="ci/cd")
    assert "java" in await _keys(
        app_client, app_auth_headers, q_any_group="spring-boot"
    )


@pytest.mark.asyncio
async def test_folded_reads_decomposed_polish_letters(
    app_client, app_auth_headers, folded
):
    """Wersja 3 składania (0387): NFC przed składaniem — „Łódź” zapisane jako
    litera i osobny akcent znajduje się po „łódź” i „lodz”."""
    assert "decomposed" in await _keys(app_client, app_auth_headers, q_any_group="łódź")
    assert "decomposed" in await _keys(app_client, app_auth_headers, q_any_group="lodz")
    assert "decomposed" in await _keys(
        app_client, app_auth_headers, q_any_group="zarządzanie"
    )
    assert "decomposed" in await _keys(
        app_client, app_auth_headers, q_any_group="gdańska", q_scope="notes"
    )


@pytest.mark.asyncio
async def test_folded_survives_script_tag_in_cv(app_client, app_auth_headers, folded):
    assert "script" in await _keys(app_client, app_auth_headers, q_any_group="lodz")


def test_python_mirror_strips_combining_marks():
    from app.services import keyword_corpus as kc

    assert kc.fold_text("Lo\u0301dz\u0301 zarza\u0328dzanie") == "lodz zarzadzanie"
    assert kc.fold_text("t\u0489\u0320e\u0315st") == "test"
    # Bez znaków łączących długość się nie zmienia (pozycje wycinków).
    assert kc.fold_text("< script> a<b") == "  script  a b"
    assert len(kc.fold_text("Łódź, CI/CD-driven")) == len("Łódź, CI/CD-driven")


@pytest.mark.asyncio
async def test_folded_reads_wrapped_traffit_note(app_client, app_auth_headers, folded):
    assert "noted" in await _keys(app_client, app_auth_headers, q_any_group="toruń")
    assert "noted" in await _keys(app_client, app_auth_headers, q_any_group="torun")
    # Nazwy znaczników HTML i klucze JSON nie są słowami notatki.
    for word in ("div", "state", "przepuszczony"):
        assert "noted" not in await _keys(
            app_client, app_auth_headers, q_any_group=word
        ), word


# ── Kolumny i funkcje w bazie ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_triggers_fill_both_columns():
    from app.core.database import AsyncSessionLocal

    ids = await _seed()
    async with AsyncSessionLocal() as db:
        cand = (
            await db.execute(
                text("SELECT keyword_fold_fts::text FROM candidates WHERE id = :id"),
                {"id": ids["csharp"]},
            )
        ).scalar_one()
        note = (
            await db.execute(
                text(
                    "SELECT content_fold_fts::text FROM notes WHERE candidate_id = :id"
                ),
                {"id": ids["noted"]},
            )
        ).scalar_one()
    for token in ("'csharp'", "'dotnet'", "'cplusplus'", "'fsharp'"):
        assert token in cand
    assert "'torun'" in note and "'kotlin'" in note
    assert "'div'" not in note and "'state'" not in note


@pytest.mark.asyncio
async def test_fold_function_matches_the_python_mirror_on_plain_text():
    from app.core.database import AsyncSessionLocal
    from app.services import keyword_corpus as kc

    sample = "Zażółć GĘŚLĄ jaźń / Kraków\\Łódź CI/CD-driven"
    async with AsyncSessionLocal() as db:
        folded = (
            await db.execute(text(f"SELECT {kc.FOLD_FUNCTION}(:t)"), {"t": sample})
        ).scalar_one()
    assert folded == kc.fold_text(sample)


@pytest.mark.asyncio
async def test_note_unwrap_json_only_touches_the_traffit_wrapper():
    from app.core.database import AsyncSessionLocal
    from app.services import keyword_corpus as kc

    cases = {
        json.dumps({"content": "<p>Toruń</p>", "state": {}}): "<p>Toruń</p>",
        "<p>zwykły HTML</p>": "<p>zwykły HTML</p>",
        '{"content": ': '{"content": ',
        json.dumps({"to": {"email": "a@b.pl"}, "subject": "x"}): json.dumps(
            {"to": {"email": "a@b.pl"}, "subject": "x"}
        ),
        json.dumps({"content": ""}): json.dumps({"content": ""}),
    }
    async with AsyncSessionLocal() as db:
        for raw, expected in cases.items():
            got = (
                await db.execute(
                    text(f"SELECT {kc.NOTE_UNWRAP_FUNCTION}(:c)"), {"c": raw}
                )
            ).scalar_one()
            assert got == expected, raw


@pytest.mark.asyncio
async def test_notes_backfill_unwraps_without_touching_updated_at():
    """Pętla uzupełniania: notatka bez indeksu dostaje go, a treść zapisana
    przez import jako JSON zostaje rozpakowana — ``updated_at`` bez zmian
    (od niego zależy odcisk nocnej analizy notatek przez AI)."""
    from app.core.database import AsyncSessionLocal
    from app.services import keyword_corpus as kc
    from app.tasks.keyword_corpus_backfill import _fill_keyset_batch

    ids = await _seed()
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET LOCAL session_replication_role = replica"))
        note_id, before = (
            await db.execute(
                text(
                    "UPDATE notes SET content_fold_fts = NULL "
                    "WHERE candidate_id = :id RETURNING id, updated_at"
                ),
                {"id": ids["noted"]},
            )
        ).one()
        await db.commit()

    await _fill_keyset_batch(
        kc.NOTES_BACKFILL_BATCH_SQL, note_id - 1, 1, kc.NOTE_TRIGGER_NAME
    )

    async with AsyncSessionLocal() as db:
        content, fts, after = (
            await db.execute(
                text(
                    "SELECT content, content_fold_fts::text, updated_at "
                    "FROM notes WHERE id = :id"
                ),
                {"id": note_id},
            )
        ).one()
    assert content.startswith("<div><p>Kandydat z Toruń")
    assert "'torun'" in fts
    assert after == before


def test_fold_text_keeps_length_and_splits_slash():
    from app.services import keyword_corpus as kc

    assert kc.fold_text("Agile/Scrum, Łódź") == "agile scrum, lodz"
    assert kc.fold_text("CI/CD-driven") == "ci cd driven"
    sample = "Zażółć gęślą jaźń"
    assert len(kc.fold_text(sample)) == len(sample)


@pytest.mark.asyncio
async def test_suggest_counts_special_tokens_in_folded_mode(folded):
    """Podpowiedź liczy „c#” z tego samego indeksu co lista (dawniej: brak)."""
    from app.core.database import AsyncSessionLocal
    from app.services import keyword_suggest

    await _seed()
    keyword_suggest.clear_count_cache()
    async with AsyncSessionLocal() as db:
        counts = await keyword_suggest.count_candidates(db, ["c#", "ci/cd"])
    assert counts["c#"] is not None and counts["c#"] >= 1
    assert counts["ci/cd"] is None, "słowo z ukośnikiem to fraza — bez liczby"


@pytest.mark.asyncio
async def test_version_phase_recomputes_only_on_a_new_version(monkeypatch):
    from app.services import keyword_corpus as kc
    from app.tasks import keyword_corpus_backfill as loop

    calls: list[str] = []

    async def fake_recompute(name, sql, limit, trigger):
        calls.append(name)
        return 0

    async def fake_store():
        calls.append("stored")

    async def db_version():
        return kc.FOLD_VERSION

    async def no_position():
        return {}

    async def fake_clear():
        calls.append("cleared")

    monkeypatch.setattr(loop, "_recompute", fake_recompute)
    monkeypatch.setattr(loop, "_store_fold_version", fake_store)
    monkeypatch.setattr(loop, "_db_fold_version", db_version)
    monkeypatch.setattr(loop, "_load_recompute_position", no_position)
    monkeypatch.setattr(loop, "_clear_recompute_position", fake_clear)
    monkeypatch.setattr(kc, "_fold_ready", False)
    monkeypatch.setattr(kc, "_notes_ready", False)

    async def current():
        return kc.FOLD_VERSION

    monkeypatch.setattr(loop, "_stored_fold_version", current)
    await loop._version_phase()
    assert calls == []
    assert kc.fold_ready() and kc.notes_ready()

    async def older():
        return kc.FOLD_VERSION - 1

    monkeypatch.setattr(loop, "_stored_fold_version", older)
    await loop._version_phase()
    assert calls == ["candidates", "notes", "stored", "cleared"]
    assert kc.fold_ready() and kc.notes_ready()


@pytest.mark.asyncio
async def test_stored_fold_version_reads_jsonb():
    from app.core.database import AsyncSessionLocal
    from app.services import keyword_corpus as kc
    from app.tasks import keyword_corpus_backfill as loop

    await loop._store_fold_version()
    assert await loop._stored_fold_version() == kc.FOLD_VERSION
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM app_settings WHERE key = :key"),
            {"key": kc.FOLD_VERSION_KEY},
        )
        await db.commit()
    assert await loop._stored_fold_version() is None


@pytest.mark.asyncio
async def test_recompute_resumes_after_a_container_restart(monkeypatch):
    """Pozycja przeliczania przeżywa restart procesu (deploy po każdym merge'u).

    Do 26.09.2026 żyła tylko w pamięci: każde wdrożenie zaczynało ~45-minutowe
    przeliczenie od zera i wersja 2 składania nie skończyła się ani razu.
    """
    from app.services import keyword_corpus as kc
    from app.tasks import keyword_corpus_backfill as loop

    await loop._clear_recompute_position()
    try:
        await loop._save_recompute_position("candidates", 1234)
        await loop._save_recompute_position("notes", 77)
        await loop._save_recompute_position("candidates", 2345)
        assert await loop._load_recompute_position() == {
            "candidates": 2345,
            "notes": 77,
        }

        starts: dict[str, int] = {}

        async def fake_batch(sql, after, limit, trigger):
            name = "notes" if limit == loop._NOTES_BATCH else "candidates"
            starts.setdefault(name, after)
            return 0

        async def older():
            return kc.FOLD_VERSION - 1

        async def fake_store():
            return None

        monkeypatch.setattr(loop, "_fill_keyset_batch", fake_batch)
        monkeypatch.setattr(loop, "_stored_fold_version", older)
        monkeypatch.setattr(loop, "_store_fold_version", fake_store)
        monkeypatch.setattr(kc, "_fold_ready", False)
        monkeypatch.setattr(kc, "_notes_ready", False)
        loop._recompute_after.clear()  # „nowy proces”

        await loop._version_phase()
        assert starts == {"candidates": 2345, "notes": 77}
        assert await loop._load_recompute_position() == {}, "koniec kasuje pozycję"
    finally:
        loop._recompute_after.clear()
        await loop._clear_recompute_position()


@pytest.mark.asyncio
async def test_recompute_position_of_another_version_is_ignored():
    from app.core.database import AsyncSessionLocal
    from app.services import keyword_corpus as kc
    from app.tasks import keyword_corpus_backfill as loop

    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO app_settings (key, value) VALUES (:key, CAST(:value AS jsonb)) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            ),
            {
                "key": loop._RECOMPUTE_POSITION_KEY,
                "value": json.dumps({"version": kc.FOLD_VERSION - 1, "candidates": 99}),
            },
        )
        await db.commit()
    try:
        assert await loop._load_recompute_position() == {}
        await loop._save_recompute_position("notes", 5)
        assert await loop._load_recompute_position() == {"notes": 5}
    finally:
        await loop._clear_recompute_position()
