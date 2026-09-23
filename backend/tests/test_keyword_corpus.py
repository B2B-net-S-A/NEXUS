"""Korpus słów kluczowych (migracja 0350) — przez prawdziwy endpoint i Postgresa.

Każdy przypadek to rozjazd z Traffitem zmierzony na produkcji 22.09.2026
(``app/services/keyword_corpus.py``):

* podsumowanie AI NIE jest przeszukiwane („bankowość” z AI ≠ bankowość w CV);
* poziom umiejętności NIE jest słowem („java NIE junior” nie wycina seniora
  z ``{"name": "Java", "level": "junior"}`` przy innej umiejętności);
* pola Traffita i „Kandydat o sobie” SĄ przeszukiwane, także w zakresach
  „Stanowisko” i „Umiejętności”;
* „.net” nie łapie „B2B.net S.A.” z klauzuli zgody;
* do końca backfillu wiersze bez korpusu znajduje stara kolumna.

Baza testowa jest wspólna: każde żądanie zawęża się frazą ``NONCE`` w ``q``.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text

NONCE = "zk" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])
_IDS: dict[str, int] = {}


async def _seed() -> dict[str, int]:
    if _IDS:
        return _IDS
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    def person(key: str, **kw: Any) -> Candidate:
        return Candidate(
            name=key.capitalize(),
            lastname=f"Korpusowy{key}",
            email=f"{key}-{uuid.uuid4().hex[:10]}@example.com",
            status=CandidateStatus.active,
            linkedin_current_company=NONCE,
            **kw,
        )

    async with AsyncSessionLocal() as db:
        rows = {
            "ai_only": person(
                "aionly",
                raw_cv_text="Programista Python.",
                ai_summary="Doświadczenie w sektorze: bankowość, ubezpieczenia.",
            ),
            "about": person(
                "about",
                raw_cv_text="Analityk.",
                profile_about="Od lat w bankowość detaliczna.",
            ),
            "senior": person(
                "senior",
                raw_cv_text="Senior developer.",
                skills=[
                    {"name": "Java", "level": "senior"},
                    {"name": "SQL", "level": "junior"},
                ],
            ),
            "traffit": person(
                "traffit",
                raw_cv_text="",
                cv_extracted_data={
                    "traffit_technologie": "Kafka, Spark",
                    "traffit_Position": "QA Engineer",
                    "traffit_experience": "5+",
                },
            ),
            "consent": person(
                "consent",
                raw_cv_text=(
                    "Tester. Wyrażam zgodę na przetwarzanie przez B2B.net S.A. "
                    "moich danych osobowych."
                ),
            ),
            "aspnet": person("aspnet", raw_cv_text="Backend: ASP.NET Core, C#."),
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


@pytest.fixture(params=[True, False], ids=["corpus-ready", "during-backfill"])
def corpus_state(request, monkeypatch):
    """Oba stany zapytania: po backfillu i w jego trakcie (gałąź zapasowa)."""
    from app.services import keyword_corpus

    monkeypatch.setattr(keyword_corpus, "_ready", request.param)
    return request.param


@pytest.mark.asyncio
async def test_trigger_fills_the_corpus_on_insert():
    from app.core.database import AsyncSessionLocal

    ids = await _seed()
    async with AsyncSessionLocal() as db:
        doc, fts = (
            await db.execute(
                text(
                    "SELECT keyword_doc, keyword_fts::text FROM candidates WHERE id = :id"
                ),
                {"id": ids["traffit"]},
            )
        ).one()
    assert "kafka" in doc and "qa engineer" in doc
    assert "5+" not in doc, "koszyk stażu to nie tekst"
    assert "'kafka'" in fts


@pytest.mark.asyncio
async def test_ai_summary_is_not_searched(app_client, app_auth_headers, corpus_state):
    found = await _keys(app_client, app_auth_headers, q_all="bankowość")
    assert "ai_only" not in found
    assert "about" in found, "„Kandydat o sobie” jest przeszukiwany"


@pytest.mark.asyncio
async def test_skill_level_is_not_a_word(app_client, app_auth_headers, corpus_state):
    found = await _keys(app_client, app_auth_headers, q_all="java", q_none="junior")
    assert "senior" in found


@pytest.mark.asyncio
async def test_traffit_fields_are_searched_and_scoped(
    app_client, app_auth_headers, corpus_state
):
    assert "traffit" in await _keys(app_client, app_auth_headers, q_all="kafka")
    assert "traffit" in await _keys(
        app_client, app_auth_headers, q_all="kafka", q_scope="skills"
    )
    assert "traffit" in await _keys(
        app_client, app_auth_headers, q_all="qa", q_scope="title"
    )
    assert "traffit" not in await _keys(
        app_client, app_auth_headers, q_all="kafka", q_scope="title"
    )


@pytest.mark.asyncio
async def test_dotnet_skips_the_consent_clause(
    app_client, app_auth_headers, corpus_state
):
    found = await _keys(app_client, app_auth_headers, q_all=".net")
    assert "aspnet" in found
    assert "consent" not in found


@pytest.mark.asyncio
async def test_row_without_corpus_is_found_until_backfill_ends(
    app_client, app_auth_headers, monkeypatch
):
    """Wiersz sprzed migracji (``keyword_doc IS NULL``): zapasowa gałąź po
    ``search_fts`` znajduje go, dopóki pętla nie policzy korpusu."""
    from app.core.database import AsyncSessionLocal
    from app.services import keyword_corpus
    from app.tasks.keyword_corpus_backfill import _fill_batch, _pending

    ids = await _seed()
    async with AsyncSessionLocal() as db:
        # Trigger wyłączony tylko w tej sesji — tak wygląda wiersz sprzed 0350.
        # LOCAL: sesja wraca do puli, a rola „replica” zostałaby na połączeniu
        # i wyłączyła trigger także backfillowi niżej.
        await db.execute(text("SET LOCAL session_replication_role = replica"))
        await db.execute(
            text(
                "UPDATE candidates SET keyword_doc = NULL, keyword_fts = NULL "
                "WHERE id = :id"
            ),
            {"id": ids["senior"]},
        )
        await db.commit()

    monkeypatch.setattr(keyword_corpus, "_ready", False)
    assert "senior" in await _keys(app_client, app_auth_headers, q_all="senior")
    assert await _pending()

    for _ in range(1000):
        if not await _pending():
            break
        await _fill_batch()
    assert not await _pending()
    monkeypatch.setattr(keyword_corpus, "_ready", True)
    assert "senior" in await _keys(app_client, app_auth_headers, q_all="senior")


def test_python_mirror_takes_values_not_keys_or_levels():
    from types import SimpleNamespace

    from app.services import keyword_corpus as kc

    cand = SimpleNamespace(
        skills=[{"name": "Java", "level": "junior"}, "Docker"],
        cv_extracted_data={"traffit_technologie": "Kafka"},
        experience=[{"role": "Dev", "start": "2020-01", "source": "cv"}],
    )
    assert kc.skills_text(cand) == "Java Docker · Kafka"
    assert kc.json_text(cand.experience, kc.EXPERIENCE_KEYS) == "Dev"
