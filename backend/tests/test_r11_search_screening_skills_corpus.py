"""Runda 11 (SEARCH): umiejętności potwierdzone w screeningu w korpusie słów kluczowych.

Profil pokazuje z ✓ umiejętności z ``verified_tech`` ORAZ potwierdzone
w screeningu (``screening_notes.verified_skills``, poziom „confirmed”). Runda
10 (F17) dołożyła do korpusu tylko ``verified_tech`` — umiejętność potwierdzona
w screeningu nie była słowem kluczowym. Poziom „none” (kandydat tego NIE umie)
i notatka rekrutera nie mogą trafić do korpusu.
"""

from __future__ import annotations

import importlib.util
import random
import string
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.services import keyword_corpus as kc

_BACKEND = Path(__file__).resolve().parents[1]
_MIGRATION = "0396_search_screening_skills_corpus.py"


def _migration():
    path = _BACKEND / "alembic" / "versions" / _MIGRATION
    spec = importlib.util.spec_from_file_location("m0396", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ── Bez bazy ────────────────────────────────────────────────────────────────


def test_trigger_kandydata_czyta_potwierdzone_umiejetnosci_ze_screeningu() -> None:
    ddl = kc.TRIGGER_FUNCTION_DDL
    assert "FROM screening_notes AS sn" in ddl
    assert "sn.candidate_id = NEW.id" in ddl
    # Tylko nazwa umiejętności i tylko poziom „confirmed”.
    assert "e ->> 'skill'" in ddl
    assert "e ->> 'level' = 'confirmed'" in ddl
    assert "'notes'" not in ddl
    # Surowy tekst JSON-a (z poziomami) nie wchodzi do korpusu.
    assert "verified_skills::text" not in ddl
    # Korpus nadal bierze profil i CV.
    assert kc.profile_text_sql("NEW.") in ddl
    assert "NEW.keyword_fold_fts" in ddl


def test_stara_funkcja_triggera_nie_czyta_screeningu() -> None:
    assert "screening_notes" not in kc.trigger_function_ddl(screening_skills=False)
    # 0350 jest zamrożona (łańcuch migracji na świeżej bazie).
    assert "screening_notes" not in kc.TRIGGER_FUNCTION_DDL_0350


def test_zapis_notatki_screeningu_przelicza_korpus_kandydata() -> None:
    fn = kc.SCREENING_TOUCH_FUNCTION_DDL
    assert "UPDATE candidates SET keyword_doc = NULL WHERE id = NEW.candidate_id" in fn
    # Scalanie przepina notatkę na innego kandydata — przeliczamy obu.
    assert "OLD.candidate_id IS DISTINCT FROM NEW.candidate_id" in fn
    assert "WHERE id = OLD.candidate_id" in fn
    trg = kc.SCREENING_TOUCH_TRIGGER_DDL
    assert "AFTER INSERT OR UPDATE OF verified_skills, candidate_id" in trg
    assert "ON screening_notes" in trg
    assert "DELETE" not in trg


def test_siatka_entrypointu_zaklada_trigger_screeningu() -> None:
    ddl = "\n".join(kc.schema_ddl())
    assert kc.SCREENING_TOUCH_FUNCTION in ddl
    assert f"CREATE OR REPLACE TRIGGER {kc.SCREENING_TOUCH_TRIGGER}" in ddl
    # Osłona: bez ``keyword_doc`` zapis notatki padałby na UPDATE-cie.
    guarded = [s for s in kc.schema_ddl() if kc.SCREENING_TOUCH_FUNCTION in s]
    assert guarded and all("column_name = 'keyword_doc'" in s for s in guarded)
    entrypoint = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "_KEYWORD_CORPUS_DDL = _kc.schema_ddl()" in entrypoint


def test_przeliczenie_zrodel_obejmuje_screening_i_verified_tech() -> None:
    assert kc.CORPUS_SOURCES_VERSION == 3
    assert kc.CORPUS_SOURCES_MARKER_COLUMN in kc.TRIGGER_FUNCTION_DDL
    assert kc.CORPUS_SOURCES_MARKER_COLUMN not in kc.trigger_function_ddl(
        screening_skills=False
    )
    sql = kc.SOURCES_RECOMPUTE_BATCH_SQL
    assert "verified_tech" in sql
    assert "FROM screening_notes AS sn WHERE sn.candidate_id = candidates.id" in sql


def test_migracja_0396_zaklada_i_zdejmuje_trigger(monkeypatch) -> None:
    module = _migration()
    executed: list[str] = []
    monkeypatch.setattr(module.op, "execute", executed.append, raising=False)
    module.upgrade()
    assert executed[0] == kc.TRIGGER_FUNCTION_DDL
    assert list(executed[1:]) == list(kc.SCREENING_TOUCH_DDLS)

    executed.clear()
    module.downgrade()
    assert list(executed[:2]) == list(kc.SCREENING_TOUCH_DROP_DDLS)
    assert "screening_notes" not in executed[2]
    assert kc.TRIGGER_FUNCTION in executed[2]


# ── Przez Postgresa i prawdziwe endpointy ───────────────────────────────────


def _word(prefix: str) -> str:
    return prefix + "".join(random.choices(string.ascii_lowercase, k=10))


NONCE = _word("zs")
CONFIRMED = _word("zc")
BASIC = _word("zb")
NONE_LEVEL = _word("zn")
NOTE_WORD = _word("zt")


async def _candidate(**kw: Any) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    async with AsyncSessionLocal() as db:
        row = Candidate(
            name="Screening",
            lastname=f"Korpus{uuid.uuid4().hex[:6]}",
            email=f"r11-screening-{uuid.uuid4().hex[:10]}@example.com",
            status=CandidateStatus.active,
            linkedin_current_company=NONCE,
            raw_cv_text="",
            **kw,
        )
        db.add(row)
        await db.commit()
        return row.id


async def _corpus(candidate_id: int) -> tuple[str, str, str]:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        doc, fts, fold = (
            await db.execute(
                text(
                    "SELECT keyword_doc, keyword_fts::text, keyword_fold_fts::text"
                    " FROM candidates WHERE id = :id"
                ),
                {"id": candidate_id},
            )
        ).one()
    return doc or "", fts or "", fold or ""


@pytest.mark.asyncio
async def test_zapis_screeningu_doklada_potwierdzone_umiejetnosci(
    app_client, app_auth_headers
):
    candidate_id = await _candidate()
    assert CONFIRMED not in (await _corpus(candidate_id))[2]

    resp = await app_client.post(
        "/api/screenings",
        json={
            "candidate_id": candidate_id,
            "verified_skills": [
                {
                    "skill": CONFIRMED.capitalize(),
                    "level": "confirmed",
                    "notes": NOTE_WORD,
                },
                {"skill": BASIC, "level": "basic"},
                {"skill": NONE_LEVEL, "level": "none"},
            ],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text

    doc, fts, fold = await _corpus(candidate_id)
    assert CONFIRMED in doc
    assert f"'{CONFIRMED}'" in fold
    assert CONFIRMED in fts.lower()
    for absent in (BASIC, NONE_LEVEL, NOTE_WORD, "confirmed"):
        assert absent not in fold, absent
        assert absent not in doc, absent


@pytest.fixture(params=[False, True], ids=["stara-sciezka", "korpus-zlozony"])
def mode(request, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "KEYWORD_SEARCH_FOLDED_FTS", request.param)
    monkeypatch.setattr(kc, "_ready", True)
    monkeypatch.setattr(kc, "_fold_ready", request.param)
    monkeypatch.setattr(kc, "_notes_ready", request.param)
    return request.param


@pytest.mark.asyncio
async def test_slowo_kluczowe_znajduje_umiejetnosc_ze_screeningu(
    app_client, app_auth_headers, mode
):
    skill = _word("zk")
    with_skill = await _candidate()
    without = await _candidate()
    resp = await app_client.post(
        "/api/screenings",
        json={
            "candidate_id": with_skill,
            "verified_skills": [{"skill": skill.capitalize(), "level": "confirmed"}],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text

    found = await app_client.get(
        "/api/candidates",
        params=[
            ("q", NONCE),
            ("text_mode", "literal"),
            ("page_size", 100),
            ("semantics_version", 2),
            ("q_any_group", skill),
        ],
        headers=app_auth_headers,
    )
    assert found.status_code == 200, found.text
    ids = {item["id"] for item in found.json()["items"]}
    assert with_skill in ids
    assert without not in ids


@pytest.mark.asyncio
async def test_przepiecie_notatki_przelicza_obu_kandydatow(app_client):
    from app.core.database import AsyncSessionLocal
    from app.models.screening_note import ScreeningNote
    from app.models.user import User

    skill = _word("zm")
    source = await _candidate()
    target = await _candidate()
    async with AsyncSessionLocal() as db:
        author_id = (
            await db.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": app_client.headers["X-Test-Admin-Email"]},
            )
        ).scalar_one()
        assert await db.get(User, author_id) is not None
        note = ScreeningNote(
            candidate_id=source,
            author_id=author_id,
            verified_skills=[{"skill": skill, "level": "confirmed"}],
        )
        db.add(note)
        await db.commit()
        note_id = note.id

    assert f"'{skill}'" in (await _corpus(source))[2]

    # Tak scalanie kandydatów przepina notatki (``candidate_merge``).
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE screening_notes SET candidate_id = :t WHERE id = :id"),
            {"t": target, "id": note_id},
        )
        await db.commit()

    assert f"'{skill}'" not in (await _corpus(source))[2]
    assert f"'{skill}'" in (await _corpus(target))[2]


@pytest.mark.asyncio
async def test_faza_zrodel_przelicza_kandydata_ze_screeningiem(
    app_client, app_auth_headers, monkeypatch
):
    """Wiersz z korpusem sprzed rundy 11 dostaje umiejętność ze screeningu."""
    from app.core.database import AsyncSessionLocal
    from app.tasks import keyword_corpus_backfill as loop

    skill = _word("zf")
    candidate_id = await _candidate()
    resp = await app_client.post(
        "/api/screenings",
        json={
            "candidate_id": candidate_id,
            "verified_skills": [{"skill": skill, "level": "confirmed"}],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    async with AsyncSessionLocal() as db:
        # Korpus „sprzed” rundy 11. Kolumny korpusu nie są na liście
        # ``UPDATE OF`` triggera, więc zapis przeżywa.
        await db.execute(
            text(
                "UPDATE candidates SET keyword_fts = to_tsvector('simple', 'stary'),"
                " keyword_fold_fts = to_tsvector('simple', 'stary') WHERE id = :id"
            ),
            {"id": candidate_id},
        )
        await db.commit()
    assert f"'{skill}'" not in (await _corpus(candidate_id))[2]

    async def never_done() -> None:
        return None

    monkeypatch.setattr(loop, "_stored_sources_version", never_done)
    await loop._sources_phase()

    _doc, fts, fold = await _corpus(candidate_id)
    assert f"'{skill}'" in fts and f"'{skill}'" in fold
