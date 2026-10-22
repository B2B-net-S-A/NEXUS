"""Integration tests for POST /api/candidates/from-cv (v4 auto-fill).

Covers:
  * Happy path: CV → new candidate with contact fields populated
  * Dedup: 409 when the parsed email matches an existing candidate
  * Force: ?force=true still refuses a taken e-mail (no second profile)
  * 12.10.2026 — ta sama osoba = ten sam e-mail: imiennik, ten sam telefon
    i ten sam LinkedIn z INNYM adresem zakładają nowy profil
  * 22.10.2026 — ten sam telefon ORAZ to samo imię i nazwisko (inny e-mail)
    → 409 z `existing_candidate_id`; `?force=true` zakłada profil
"""

from __future__ import annotations

import uuid
from io import BytesIO

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate


FAKE_PARSED = {
    # Use emails/phones unlikely to collide with existing test fixtures.
    "first_name": "AnnaTest",
    "last_name": "TestowaUnique",
    "email": "anna.testowa.cv-v4@example.com",
    # 9-digit phone that isn't used by any other fixture.
    "phone": "+48 512 777 888",
    "city": "Warszawa",
    "years_it_experience": 6,
    "current_position": "Senior Python Developer",
    "skills": [
        {"name": "Python", "level": "senior", "years": 6},
        {"name": "FastAPI", "level": "senior", "years": 4},
    ],
    "education": [{"degree": "MSc", "field": "CS", "school": "PW", "year": 2017}],
    "languages": [{"name": "English", "level": "C1"}],
    "companies": ["Acme Corp", "Globex"],
    "career_summary": "6 lat Pythona w fintechu.",
    "linkedin_url": "https://linkedin.com/in/anna-testowa",
    "_confidence": {
        "first_name": 0.95,
        "last_name": 0.95,
        "email": 0.98,
        "phone": 0.9,
        "city": 0.7,
    },
    "_source": "claude:cv_enrichment:v4",
}


def _fake_pdf_bytes() -> bytes:
    """A tiny PDF-like payload. The extractor is monkeypatched so the
    actual bytes don't matter — just needs to be a non-empty file."""
    return b"%PDF-1.4 fake content for tests"


def _patch_parser_and_extractor(monkeypatch, parsed: dict):
    """Short-circuit CV pipeline: extractor returns canned text, parser the canned dict.

    Also stubs embedding + CC classification so tests don't need Qdrant.
    """
    from app.services import cv_text_extractor
    from app.api import candidates as candidates_api

    def _fake_extract(*_args, **_kwargs) -> str:
        return "Jan Testowy\nSenior Python Developer\nexperience: Python, FastAPI"

    async def _fake_parse(_text, **_kwargs):
        return parsed

    async def _fake_embed(*_args, **_kwargs):
        return None

    async def _fake_cc(_candidate, _db):
        return None

    monkeypatch.setattr(cv_text_extractor, "extract_text", _fake_extract)
    # Patch parse_cv at the call-site (it's imported inside the endpoint fn).
    monkeypatch.setattr("app.services.cv_parser.parse_cv", _fake_parse, raising=True)
    monkeypatch.setattr(
        "app.services.embedding_service.embed_candidate",
        _fake_embed,
        raising=True,
    )
    monkeypatch.setattr(
        candidates_api, "_auto_assign_primary_cc", _fake_cc, raising=True
    )


async def _cleanup_candidate(email: str) -> None:
    """Delete a candidate by email so re-runs stay green."""
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(Candidate).where(Candidate.email == email))
        if row:
            await db.delete(row)
            await db.commit()


@pytest.mark.asyncio
async def test_from_cv_happy_path_creates_candidate(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Upload → new candidate with fields populated from parsed output."""
    _patch_parser_and_extractor(monkeypatch, FAKE_PARSED)
    await _cleanup_candidate(FAKE_PARSED["email"])

    files = {"file": ("anna.pdf", _fake_pdf_bytes(), "application/pdf")}
    resp = await app_client.post(
        "/api/candidates/from-cv", headers=app_auth_headers, files=files
    )

    try:
        assert resp.status_code == 201, resp.text
        body = resp.json()
        candidate = body["candidate"]

        assert candidate["name"] == FAKE_PARSED["first_name"]
        assert candidate["lastname"] == FAKE_PARSED["last_name"]
        assert candidate["email"] == FAKE_PARSED["email"]
        assert candidate["phone"] == FAKE_PARSED["phone"]
        assert candidate["years_it_experience"] == 6

        assert body["confidence"]["email"] == pytest.approx(0.98)
        assert body["source"] == "claude:cv_enrichment:v4"
        assert body["duplicates"] == []
    finally:
        await _cleanup_candidate(FAKE_PARSED["email"])


@pytest.mark.asyncio
async def test_from_cv_returns_409_on_duplicate_email(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Second upload with the same parsed email must raise 409."""
    _patch_parser_and_extractor(monkeypatch, FAKE_PARSED)
    await _cleanup_candidate(FAKE_PARSED["email"])

    files = {"file": ("anna.pdf", _fake_pdf_bytes(), "application/pdf")}

    try:
        # First upload — green insert
        first = await app_client.post(
            "/api/candidates/from-cv",
            headers=app_auth_headers,
            files=files,
        )
        assert first.status_code == 201, first.text

        # Second upload — dedup scan must find the first candidate
        second = await app_client.post(
            "/api/candidates/from-cv",
            headers=app_auth_headers,
            files={"file": ("anna2.pdf", _fake_pdf_bytes(), "application/pdf")},
        )
        assert second.status_code == 409, second.text
        detail = second.json()["detail"]
        # FastAPI nests our dict under `detail`; both nested and flat shapes OK.
        if isinstance(detail, dict):
            assert "existing_candidate_id" in detail
            assert detail["existing_candidate_id"] == first.json()["candidate"]["id"]
            assert len(detail["matches"]) >= 1
        else:  # str detail — at minimum the 409 is correct
            assert "duplikat" in detail.lower()
    finally:
        await _cleanup_candidate(FAKE_PARSED["email"])


def _unique_pdf_bytes() -> bytes:
    """Inna treść przy każdym wywołaniu — sito identycznego pliku nie może
    przesłonić reguły e-maila."""
    return f"%PDF-1.4 {uuid.uuid4().hex}".encode()


def _person(unique: str, **fields) -> dict:
    base = {
        "first_name": "Regula",
        "last_name": f"Email{unique}",
        "email": f"regula-{unique}@example.com",
        "phone": None,
        "linkedin_url": None,
        "_confidence": {},
        "_source": "claude:test",
    }
    return {**base, **fields}


async def _post_cv(client: AsyncClient, headers: dict, *, force: bool = False):
    return await client.post(
        f"/api/candidates/from-cv{'?force=true' if force else ''}",
        headers=headers,
        files={"file": ("cv.pdf", _unique_pdf_bytes(), "application/pdf")},
    )


@pytest.mark.asyncio
async def test_from_cv_force_does_not_create_a_second_profile_with_the_same_email(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """`?force=true` omija sito, ale zajęty e-mail odmawia mimo to."""
    unique = uuid.uuid4().hex[:8]
    person = _person(unique)
    _patch_parser_and_extractor(monkeypatch, person)
    try:
        first = await _post_cv(app_client, app_auth_headers)
        assert first.status_code == 201, first.text

        second = await _post_cv(app_client, app_auth_headers, force=True)
        assert second.status_code == 409, second.text
        assert second.json()["detail"] == "Kandydat z tym adresem e-mail już istnieje."
    finally:
        await _cleanup_candidate(person["email"])


@pytest.mark.asyncio
async def test_from_cv_namesake_with_other_email_is_created(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """To samo imię i nazwisko, inny e-mail = inna osoba, bez odmowy."""
    unique = uuid.uuid4().hex[:8]
    first_person = _person(unique)
    namesake = _person(unique, email=f"imiennik-{unique}@example.com")
    try:
        _patch_parser_and_extractor(monkeypatch, first_person)
        first = await _post_cv(app_client, app_auth_headers)
        assert first.status_code == 201, first.text

        _patch_parser_and_extractor(monkeypatch, namesake)
        second = await _post_cv(app_client, app_auth_headers)
        assert second.status_code == 201, second.text
        assert second.json()["candidate"]["id"] != first.json()["candidate"]["id"]
        assert second.json()["duplicates"] == []
    finally:
        await _cleanup_candidate(first_person["email"])
        await _cleanup_candidate(namesake["email"])


@pytest.mark.asyncio
async def test_from_cv_same_phone_and_linkedin_other_email_is_created(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Wspólny telefon i ten sam LinkedIn nie robią z dwóch adresów jednej osoby."""
    unique = uuid.uuid4().hex[:8]
    shared = {
        "phone": "+48 512 9" + f"{uuid.uuid4().int % 100000:05d}",
        "linkedin_url": f"https://linkedin.com/in/regula-{unique}",
    }
    first_person = _person(unique, **shared)
    other_person = _person(
        unique,
        first_name="Inna",
        last_name=f"Osoba{unique}",
        email=f"inna-{unique}@example.com",
        **shared,
    )
    try:
        _patch_parser_and_extractor(monkeypatch, first_person)
        first = await _post_cv(app_client, app_auth_headers)
        assert first.status_code == 201, first.text

        _patch_parser_and_extractor(monkeypatch, other_person)
        second = await _post_cv(app_client, app_auth_headers)
        assert second.status_code == 201, second.text
    finally:
        await _cleanup_candidate(first_person["email"])
        await _cleanup_candidate(other_person["email"])


async def _insert_existing(**fields) -> int:
    """Profil sprzed scrapera (import z Traffita): telefon w innym zapisie."""
    async with AsyncSessionLocal() as db:
        candidate = Candidate(source="traffit", **fields)
        db.add(candidate)
        await db.commit()
        return candidate.id


async def _cleanup_candidate_id(candidate_id: int) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(Candidate, candidate_id)
        if row:
            await db.delete(row)
            await db.commit()


def _random_phone_digits() -> str:
    return "79" + f"{uuid.uuid4().int % 10_000_000:07d}"


@pytest.mark.asyncio
async def test_from_cv_same_phone_and_full_name_other_email_is_409_with_existing_id(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Scraper JustJoin 20–22.10.2026: panel nie podaje telefonu, CV go ma,
    e-mail inny niż w starym profilu → powstawał drugi profil tej samej osoby.
    Telefon z CV + to samo imię i nazwisko wskazują stary profil."""
    unique = uuid.uuid4().hex[:8]
    digits = _random_phone_digits()
    existing_id = await _insert_existing(
        name="Regula",
        lastname=f"Telefon{unique}",
        email=f"stary-{unique}@example.com",
        phone=f"{digits[:3]}-{digits[3:6]}-{digits[6:]}",
    )
    person = _person(
        unique,
        first_name="REGULA",
        last_name=f" telefon{unique} ",
        email=f"nowy-{unique}@example.com",
        phone=f"+48 {digits[:3]} {digits[3:6]} {digits[6:]}",
    )
    try:
        _patch_parser_and_extractor(monkeypatch, person)
        resp = await _post_cv(app_client, app_auth_headers)
        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert detail["existing_candidate_id"] == existing_id
        assert detail["matches"][0]["match_reasons"] == ["phone_exact", "name_exact"]
    finally:
        await _cleanup_candidate(person["email"])
        await _cleanup_candidate_id(existing_id)


@pytest.mark.asyncio
async def test_from_cv_same_phone_and_full_name_with_force_is_created(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Telefon z imieniem to dopasowanie, nie dowód jak e-mail — rekruter
    może założyć osobny profil („Załóż osobny profil” = `?force=true`)."""
    unique = uuid.uuid4().hex[:8]
    digits = _random_phone_digits()
    existing_id = await _insert_existing(
        name="Regula",
        lastname=f"Telefon{unique}",
        email=f"stary-{unique}@example.com",
        phone=digits,
    )
    person = _person(
        unique,
        last_name=f"Telefon{unique}",
        email=f"nowy-{unique}@example.com",
        phone=f"+48{digits}",
    )
    try:
        _patch_parser_and_extractor(monkeypatch, person)
        resp = await _post_cv(app_client, app_auth_headers, force=True)
        assert resp.status_code == 201, resp.text
        assert resp.json()["candidate"]["id"] != existing_id
    finally:
        await _cleanup_candidate(person["email"])
        await _cleanup_candidate_id(existing_id)


@pytest.mark.asyncio
async def test_from_cv_same_email_in_other_case_is_409_with_existing_id(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Odmowa bez `force` wskazuje profil — okna i klient JustJoin dodają
    wtedy CV do niego, więc `detail` musi zostać słownikiem."""
    unique = uuid.uuid4().hex[:8]
    person = _person(unique)
    try:
        _patch_parser_and_extractor(monkeypatch, person)
        first = await _post_cv(app_client, app_auth_headers)
        assert first.status_code == 201, first.text

        _patch_parser_and_extractor(
            monkeypatch, _person(unique, email=person["email"].upper())
        )
        second = await _post_cv(app_client, app_auth_headers)
        assert second.status_code == 409, second.text
        detail = second.json()["detail"]
        assert detail["existing_candidate_id"] == first.json()["candidate"]["id"]
        assert detail["matches"][0]["match_reasons"] == ["email_exact"]
    finally:
        await _cleanup_candidate(person["email"])


@pytest.mark.asyncio
async def test_from_cv_rejects_empty_text(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """CV that extracts to empty text must fail with 400 (no silent insert)."""
    from app.services import cv_text_extractor

    monkeypatch.setattr(cv_text_extractor, "extract_text", lambda *a, **k: "")
    files = {"file": ("blank.pdf", b"%PDF blank", "application/pdf")}
    resp = await app_client.post(
        "/api/candidates/from-cv",
        headers=app_auth_headers,
        files=files,
    )
    assert resp.status_code == 400
