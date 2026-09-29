"""`POST /api/candidates/cv/preview` + `/from-cv` z polami formularza (29.09.2026).

Okno „Dodaj kandydata” czyta wgrane CV, wypełnia formularz, a zapis bierze
TEN SAM odczyt z pamięci procesu — model płaci raz. Pilnujemy:

- podgląd nie zakłada kandydata,
- podgląd + zapis tym samym plikiem = jedno wywołanie `parse_cv`,
- pola formularza wygrywają z odczytem CV, a pole wyczyszczone (`""`) NIE
  wraca z CV (ani do profilu, ani do skanu duplikatów),
- zły e-mail w formularzu = 422 przy polu `email`,
- e-mail innego kandydata = twarde 409 także przy `force` (jak ręczne dodanie),
- reszta formularza (`candidate`, JSON) walidowana jak `POST /api/candidates`
  PRZED odczytem i zapisem — zła wartość = 422 i brak kandydata,
- plik z `/from-cv` niesie autora wgrania,
- przy trafieniu w pamięć bez `force` darmowe sito i tak biegnie.
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate

pytestmark = pytest.mark.asyncio


def _parsed(unique: str) -> dict:
    return {
        "first_name": "Czytany",
        "last_name": f"ZCv{unique}",
        "email": f"cv-preview-{unique}@example.com",
        "phone": None,
        "city": "Kraków",
        "current_position": "Tester",
        "linkedin_url": None,
        "skills": [{"name": "Python", "level": "mid", "years": 3}],
        "_confidence": {"first_name": 0.9, "email": 0.95},
        "_source": "claude:test",
    }


def _patch_pipeline(monkeypatch, parsed: dict, sieve_rows=None) -> dict[str, int]:
    from app.api import candidates as candidates_api
    from app.services import cv_text_extractor

    calls = {"parse": 0, "sieve": 0}

    def _fake_extract(*_args, **_kwargs) -> str:
        return "Tester\nPython, pytest"

    async def _fake_parse(_text, **_kwargs):
        calls["parse"] += 1
        return dict(parsed)

    async def _fake_embed(*_args, **_kwargs):
        return None

    async def _fake_cc(_candidate, _db):
        return None

    async def _sieve(*_args, **_kwargs):
        calls["sieve"] += 1
        return list(sieve_rows or [])

    monkeypatch.setattr(cv_text_extractor, "extract_text", _fake_extract)
    monkeypatch.setattr("app.services.cv_parser.parse_cv", _fake_parse, raising=True)
    monkeypatch.setattr(
        "app.services.cv_upload_dedup.find_duplicates_without_llm",
        _sieve,
        raising=True,
    )
    monkeypatch.setattr(
        "app.services.embedding_service.embed_candidate", _fake_embed, raising=True
    )
    monkeypatch.setattr(
        candidates_api, "_auto_assign_primary_cc", _fake_cc, raising=True
    )
    return calls


def _file(content: bytes) -> dict:
    return {"file": ("cv.pdf", content, "application/pdf")}


async def _count(**where) -> int:
    async with AsyncSessionLocal() as db:
        stmt = select(func.count(Candidate.id))
        for column, value in where.items():
            stmt = stmt.where(getattr(Candidate, column) == value)
        return int(await db.scalar(stmt) or 0)


async def _cleanup(**where) -> None:
    async with AsyncSessionLocal() as db:
        stmt = select(Candidate)
        for column, value in where.items():
            stmt = stmt.where(getattr(Candidate, column) == value)
        for row in (await db.scalars(stmt)).all():
            await db.delete(row)
        await db.commit()


async def test_preview_fills_the_form_without_creating_a_candidate(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    unique = uuid.uuid4().hex[:8]
    parsed = _parsed(unique)
    _patch_pipeline(monkeypatch, parsed)

    resp = await app_client.post(
        "/api/candidates/cv/preview",
        headers=app_auth_headers,
        files=_file(f"%PDF-1.4 {unique}".encode()),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Czytany"
    assert body["lastname"] == parsed["last_name"]
    assert body["email"] == parsed["email"]
    assert body["city"] == "Kraków"
    assert body["current_position"] == "Tester"
    assert len(body["cv_sha256"]) == 64
    assert await _count(email=parsed["email"]) == 0


async def test_preview_then_save_reads_the_cv_once_and_form_wins(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    unique = uuid.uuid4().hex[:8]
    parsed = _parsed(unique)
    calls = _patch_pipeline(monkeypatch, parsed)
    content = f"%PDF-1.4 once {unique}".encode()
    typed_email = f"cv-preview-typed-{unique}@example.com"

    preview = await app_client.post(
        "/api/candidates/cv/preview", headers=app_auth_headers, files=_file(content)
    )
    assert preview.status_code == 200, preview.text

    try:
        saved = await app_client.post(
            "/api/candidates/from-cv",
            headers=app_auth_headers,
            files=_file(content),
            data={"name": "Poprawiony", "email": typed_email},
        )
        assert saved.status_code == 201, saved.text
        candidate = saved.json()["candidate"]
        assert candidate["name"] == "Poprawiony"
        assert candidate["lastname"] == parsed["last_name"]
        assert candidate["email"] == typed_email
        assert calls["parse"] == 1

        # Plik z `/from-cv` niesie autora wgrania.
        documents = await app_client.get(
            f"/api/candidates/{candidate['id']}/documents", headers=app_auth_headers
        )
        assert documents.status_code == 200, documents.text
        assert documents.json()[0]["uploaded_by_name"]
    finally:
        await _cleanup(email=typed_email)


async def test_cleared_field_is_not_refilled_from_the_cv_nor_used_for_dedup(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    """E-mail z CV należy do istniejącej osoby, rekruter pole wyczyścił.

    Bez honorowania listy `cleared` skan duplikatów znalazłby tamtą osobę
    (409), a przy zapisie adres wróciłby z CV.
    """
    unique = uuid.uuid4().hex[:8]
    parsed = _parsed(unique)
    _patch_pipeline(monkeypatch, parsed)
    other = await app_client.post(
        "/api/candidates",
        headers=app_auth_headers,
        json={"name": "Inna", "lastname": f"Osoba{unique}", "email": parsed["email"]},
    )
    assert other.status_code == 201, other.text

    form = {
        "name": "Nowy",
        "lastname": f"Bezmaila{unique}",
        # Pusty napis z multipart FastAPI traktuje jak brak pola — wyczyszczenie
        # idzie osobną listą (tak wysyła je okno „Dodaj kandydata”).
        "cleared": "email,city",
    }
    try:
        saved = await app_client.post(
            "/api/candidates/from-cv",
            headers=app_auth_headers,
            files=_file(f"%PDF-1.4 cleared {unique}".encode()),
            data=form,
        )
        assert saved.status_code == 201, saved.text
        candidate = saved.json()["candidate"]
        assert candidate["email"] is None
        assert not candidate.get("city")
    finally:
        await _cleanup(lastname=f"Bezmaila{unique}")
        await _cleanup(email=parsed["email"])


async def test_email_of_another_candidate_is_a_hard_409_even_with_force(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    unique = uuid.uuid4().hex[:8]
    taken = f"cv-taken-{unique}@example.com"
    _patch_pipeline(monkeypatch, _parsed(unique))
    other = await app_client.post(
        "/api/candidates",
        headers=app_auth_headers,
        json={"name": "Zajęty", "lastname": f"Adres{unique}", "email": taken},
    )
    assert other.status_code == 201, other.text

    try:
        resp = await app_client.post(
            "/api/candidates/from-cv?force=true",
            headers=app_auth_headers,
            files=_file(f"%PDF-1.4 taken {unique}".encode()),
            data={
                "name": "Druga",
                "lastname": f"Osoba{unique}",
                "email": taken.upper(),
            },
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == "Kandydat z tym adresem e-mail już istnieje."
        assert await _count(lastname=f"Osoba{unique}") == 0
    finally:
        await _cleanup(email=taken)


async def test_invalid_extra_field_is_422_before_the_read_and_creates_nothing(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    unique = uuid.uuid4().hex[:8]
    calls = _patch_pipeline(monkeypatch, _parsed(unique))

    resp = await app_client.post(
        "/api/candidates/from-cv",
        headers=app_auth_headers,
        files=_file(f"%PDF-1.4 extra {unique}".encode()),
        data={
            "name": "Zly",
            "lastname": f"Formularz{unique}",
            "candidate": json.dumps({"max_onsite_days_per_week": 9}),
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["loc"][:2] == ["body", "max_onsite_days_per_week"]
    assert calls["parse"] == 0
    assert await _count(lastname=f"Formularz{unique}") == 0

    unknown = await app_client.post(
        "/api/candidates/from-cv",
        headers=app_auth_headers,
        files=_file(f"%PDF-1.4 extra2 {unique}".encode()),
        data={"candidate": json.dumps({"raw_cv_text": "x"})},
    )
    assert unknown.status_code == 422, unknown.text
    assert calls["parse"] == 0


async def test_extra_fields_are_saved_in_the_same_request(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    unique = uuid.uuid4().hex[:8]
    parsed = _parsed(unique)
    _patch_pipeline(monkeypatch, parsed)

    try:
        saved = await app_client.post(
            "/api/candidates/from-cv",
            headers=app_auth_headers,
            files=_file(f"%PDF-1.4 extras {unique}".encode()),
            data={
                "candidate": json.dumps(
                    {
                        "tags": ["java"],
                        "years_it_experience": 7,
                        "max_onsite_days_per_week": 2,
                    }
                )
            },
        )
        assert saved.status_code == 201, saved.text
        candidate = saved.json()["candidate"]
        assert candidate["years_it_experience"] == 7
        assert candidate["max_onsite_days_per_week"] == 2
        assert "java" in candidate["tags"]
    finally:
        await _cleanup(email=parsed["email"])


async def test_cache_hit_without_force_still_runs_the_free_sieve(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    unique = uuid.uuid4().hex[:8]
    row = {
        "candidate_id": 1,
        "name": "Istniejący",
        "lastname": "Kandydat",
        "email": None,
        "match_score": 1.0,
        "match_reasons": ["cv_hash"],
    }
    calls = _patch_pipeline(monkeypatch, _parsed(unique), sieve_rows=[row])
    content = f"%PDF-1.4 sieve {unique}".encode()

    forced = await app_client.post(
        "/api/candidates/cv/preview?force=true",
        headers=app_auth_headers,
        files=_file(content),
    )
    assert forced.status_code == 200, forced.text
    assert calls["sieve"] == 0

    saved = await app_client.post(
        "/api/candidates/from-cv", headers=app_auth_headers, files=_file(content)
    )
    assert saved.status_code == 409, saved.text
    assert saved.json()["detail"]["matches"][0]["candidate_id"] == 1
    assert calls["sieve"] == 1
    assert calls["parse"] == 1


async def test_invalid_email_in_form_is_a_field_error(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    unique = uuid.uuid4().hex[:8]
    calls = _patch_pipeline(monkeypatch, _parsed(unique))

    resp = await app_client.post(
        "/api/candidates/from-cv",
        headers=app_auth_headers,
        files=_file(f"%PDF-1.4 bad {unique}".encode()),
        data={"email": "to-nie-jest-mail"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["loc"] == ["body", "email"]
    assert calls["parse"] == 0
