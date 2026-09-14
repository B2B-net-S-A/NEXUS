"""`POST /api/candidates/from-cv` — plik roboczy per żądanie, limit rozmiaru, sprzątanie.

Do 09.2026 trasa pisała upload pod `UPLOAD_DIR/from_cv_tmp_<nazwa z przeglądarki>`:
dwóch rekruterów wgrywających `CV.pdf` w tej samej sekundzie dzieliło JEDNĄ ścieżkę,
więc drugi zapis nadpisywał pierwszy w trakcie ekstrakcji, a `os.remove` pierwszego
żądania kasował plik drugiego. Ta trasa jako jedyna z trzech ścieżek uploadu CV nie
wołała też `_validate_upload_size`, a każdy wyjątek po ekstrakcji zostawiał plik.

Testy używają fixtur in-process (`app_client` + `app_auth_headers`), unikalnych
e-maili i sprzątają po sobie — baza CI jest współdzielona między plikami.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate

# Nowy prefiks i dawny (`from_cv_tmp_<nazwa>`), żeby test wykrywał też stary śmieć.
_TMP_PREFIXES = ("nexus_from_cv_", "from_cv_tmp_")


def _parsed_for(tag: str, *, email_local: str) -> dict:
    return {
        "first_name": f"Tmp{tag}",
        "last_name": "Kolizja",
        "email": f"{email_local}@example.com",
        "phone": None,
        "city": "Warszawa",
        "years_it_experience": 3,
        "skills": [],
        "education": [],
        "languages": [],
        "companies": [],
        "career_summary": "",
        "linkedin_url": None,
        "_confidence": {"first_name": 0.9, "last_name": 0.9, "email": 0.95},
        "_source": "test:from_cv_tempfile",
    }


def _stub_pipeline(monkeypatch, *, extract, parse):
    """Ekstraktor i parser podmienione; embedding i CC nie potrzebują Qdranta."""
    from app.api import candidates as candidates_api
    from app.services import cv_text_extractor

    async def _fake_embed(*_args, **_kwargs):
        return None

    async def _fake_cc(_candidate, _db):
        return None

    monkeypatch.setattr(cv_text_extractor, "extract_text", extract)
    monkeypatch.setattr("app.services.cv_parser.parse_cv", parse, raising=True)
    monkeypatch.setattr(
        "app.services.embedding_service.embed_candidate", _fake_embed, raising=True
    )
    monkeypatch.setattr(
        candidates_api, "_auto_assign_primary_cc", _fake_cc, raising=True
    )


async def _cleanup(emails: list[str]) -> None:
    async with AsyncSessionLocal() as db:
        rows = (
            (await db.execute(select(Candidate).where(Candidate.email.in_(emails))))
            .scalars()
            .all()
        )
        for row in rows:
            await db.delete(row)
        await db.commit()


def _leftover_scratch_files() -> set[str]:
    if not os.path.isdir(settings.UPLOAD_DIR):
        return set()
    return {
        name
        for name in os.listdir(settings.UPLOAD_DIR)
        if name.startswith(_TMP_PREFIXES)
    }


@pytest.mark.asyncio
async def test_two_uploads_with_the_same_filename_keep_their_own_content(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Dwa równoległe `CV.pdf` o różnej treści → każdy kandydat dostaje SWÓJ tekst.

    Ekstraktor czyta plik z dysku (jak prawdziwy) i oddaje jego zawartość — więc
    kolizja ścieżki objawiłaby się cudzym `raw_cv_text` albo `FileNotFoundError`.
    """
    tag = uuid.uuid4().hex[:8]
    email_a = f"tmp-a-{tag}"
    email_b = f"tmp-b-{tag}"
    body_a = f"TRESC-A-{tag}".encode()
    body_b = f"TRESC-B-{tag}".encode()

    def _extract(path: str, _filename: str) -> str:
        # Ekstrakcja idzie w wątku; pauza otwiera okno, w którym drugie żądanie
        # zdąży zapisać swój plik — przy wspólnej ścieżce pierwsze czytało
        # wtedy cudzą treść (dokładnie dawna kolizja).
        time.sleep(0.3)
        with open(path, "rb") as fh:
            data = fh.read()
        return data.decode()

    async def _parse(text: str, **_kwargs):
        local = email_a if text.endswith(f"A-{tag}") else email_b
        return _parsed_for(text[-10:], email_local=local)

    _stub_pipeline(monkeypatch, extract=_extract, parse=_parse)
    before = _leftover_scratch_files()
    try:
        resp_a, resp_b = await asyncio.gather(
            app_client.post(
                "/api/candidates/from-cv",
                headers=app_auth_headers,
                files={"file": ("CV.pdf", body_a, "application/pdf")},
            ),
            app_client.post(
                "/api/candidates/from-cv",
                headers=app_auth_headers,
                files={"file": ("CV.pdf", body_b, "application/pdf")},
            ),
        )
        assert resp_a.status_code == 201, resp_a.text
        assert resp_b.status_code == 201, resp_b.text
        by_email = {
            r.json()["candidate"]["email"]: r.json()["candidate"]["id"]
            for r in (resp_a, resp_b)
        }
        assert set(by_email) == {f"{email_a}@example.com", f"{email_b}@example.com"}

        async with AsyncSessionLocal() as db:
            texts = {
                row.email: row.raw_cv_text
                for row in (
                    await db.execute(
                        select(Candidate).where(
                            Candidate.id.in_(list(by_email.values()))
                        )
                    )
                )
                .scalars()
                .all()
            }
        assert texts[f"{email_a}@example.com"] == body_a.decode()
        assert texts[f"{email_b}@example.com"] == body_b.decode()
        # Plik roboczy nie przeżywa żądania.
        assert _leftover_scratch_files() == before
    finally:
        await _cleanup([f"{email_a}@example.com", f"{email_b}@example.com"])


@pytest.mark.asyncio
async def test_oversized_upload_is_refused_before_extraction(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    calls: list[str] = []

    def _extract(path: str, _filename: str) -> str:
        calls.append(path)
        return "nigdy"

    async def _parse(_text: str, **_kwargs):
        raise AssertionError("parser nie może zostać wywołany dla za dużego pliku")

    _stub_pipeline(monkeypatch, extract=_extract, parse=_parse)
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    too_big = b"x" * (1024 * 1024 + 1)
    resp = await app_client.post(
        "/api/candidates/from-cv",
        headers=app_auth_headers,
        files={"file": ("duzy.pdf", too_big, "application/pdf")},
    )
    assert resp.status_code == 413, resp.text
    assert calls == []


@pytest.mark.asyncio
async def test_failure_after_extraction_leaves_no_scratch_file(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    def _extract(path: str, _filename: str) -> str:
        assert os.path.exists(path)
        return "jakis tekst"

    async def _parse(_text: str, **_kwargs):
        raise RuntimeError("parser padl")

    _stub_pipeline(monkeypatch, extract=_extract, parse=_parse)
    before = _leftover_scratch_files()
    # `UnhandledErrorMiddleware` zamienia wyjątek na JSON-owe 500 (z CORS).
    resp = await app_client.post(
        "/api/candidates/from-cv",
        headers=app_auth_headers,
        files={"file": ("../../CV.pdf", b"tresc", "application/pdf")},
    )
    assert resp.status_code == 500, resp.text
    assert _leftover_scratch_files() == before


@pytest.mark.asyncio
async def test_oversized_upload_is_never_read_whole_into_memory(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Reaudyt 14.09.2026 (R04): odczyt jest ograniczony do limitu + 1 bajt.

    Samo 413 po `await file.read()` chroniło ekstrakcję i zapis, ale cały plik
    był już w pamięci procesu. Sprawdzamy argument faktycznego odczytu.
    """
    from starlette.datastructures import UploadFile

    read_sizes: list[int] = []
    original_read = UploadFile.read

    async def _spy_read(self, size: int = -1):
        read_sizes.append(size)
        return await original_read(self, size)

    def _extract(_path: str, _filename: str) -> str:
        raise AssertionError("ekstraktor nie może ruszyć za dużego pliku")

    async def _parse(_text: str, **_kwargs):
        raise AssertionError("parser nie może ruszyć za dużego pliku")

    _stub_pipeline(monkeypatch, extract=_extract, parse=_parse)
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setattr(UploadFile, "read", _spy_read)
    limit = 1024 * 1024
    resp = await app_client.post(
        "/api/candidates/from-cv",
        headers=app_auth_headers,
        files={"file": ("ogromny.pdf", b"x" * (limit * 3), "application/pdf")},
    )
    assert resp.status_code == 413, resp.text
    assert read_sizes == [limit + 1]
