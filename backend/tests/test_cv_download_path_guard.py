"""Odczyt CV z dysku nie może wyjść poza `UPLOAD_DIR`.

`/cv-download` i `/bulk-cv-download` składają ścieżkę jako
`UPLOAD_DIR/candidate_{id}_{cv_filename}`. Upload czyści nazwę
(`_sanitize_upload_filename`), ale importy (Traffit) i publiczny formularz
aplikacji zapisywały ją wprost. Dziś przed wyjściem chroni wyłącznie
przypadek: prefiks `candidate_{id}_` sprawia, że pierwszy segment ścieżki to
katalog, którego zwykle nie ma, więc jądro zwraca ENOENT. Te testy stawiają
warunek, w którym ta bariera nie działa (katalog o nazwie z prefiksem, symlink),
i sprawdzają, że bezpieczeństwo nie zależy od kształtu prefiksu.
"""

from __future__ import annotations

import io
import logging
import os
import uuid
import zipfile

import pytest
from httpx import AsyncClient

SECRET = b"%PDF-poza-katalogiem-uploadow"


async def _seed(cv_filename: str, *, cv_in_db: bytes | None = None) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Sciezka",
            lastname=f"Test-{uuid.uuid4().hex[:8]}",
            email=f"cv-guard-{uuid.uuid4().hex[:8]}@example.com",
            cv_filename=cv_filename,
            cv_file_content=cv_in_db,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _delete(*candidate_ids: int) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        for cid in candidate_ids:
            cand = await db.get(Candidate, cid)
            if cand is not None:
                await db.delete(cand)
        await db.commit()


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    """`UPLOAD_DIR` w katalogu tymczasowym + plik „sekretu” OBOK niego."""
    from app.core.config import settings

    root = tmp_path / "uploads"
    root.mkdir()
    (tmp_path / "secret.pdf").write_bytes(SECRET)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(root))
    return root


@pytest.mark.asyncio
async def test_single_download_does_not_follow_directory_components(
    app_client: AsyncClient, app_auth_headers: dict, upload_dir, caplog
):
    cid = await _seed("x/../../secret.pdf")
    # Warunek, w którym przypadkowa bariera prefiksu przestaje działać:
    # katalog `candidate_{id}_x` istnieje, więc `candidate_{id}_x/../../secret.pdf`
    # rozwiązuje się przez jądro do pliku OBOK `UPLOAD_DIR`.
    (upload_dir / f"candidate_{cid}_x").mkdir()
    try:
        with caplog.at_level(logging.WARNING):
            r = await app_client.get(
                f"/api/candidates/{cid}/cv-download", headers=app_auth_headers
            )
        assert r.status_code == 404, r.status_code
        assert SECRET not in r.content
        messages = [rec.getMessage() for rec in caplog.records]
        assert any(str(cid) in m and "UPLOAD_DIR" in m for m in messages), messages
        # Nazwa pliku bywa imieniem i nazwiskiem — nie trafia do logu.
        assert not any("secret.pdf" in m for m in messages), messages
    finally:
        await _delete(cid)


@pytest.mark.asyncio
async def test_single_download_does_not_follow_symlink_out_of_upload_dir(
    app_client: AsyncClient, app_auth_headers: dict, upload_dir
):
    cid = await _seed("cv.pdf")
    os.symlink(upload_dir.parent / "secret.pdf", upload_dir / f"candidate_{cid}_cv.pdf")
    try:
        r = await app_client.get(
            f"/api/candidates/{cid}/cv-download", headers=app_auth_headers
        )
        assert r.status_code == 404, r.status_code
        assert SECRET not in r.content
    finally:
        await _delete(cid)


@pytest.mark.asyncio
async def test_single_download_of_a_regular_file_still_works(
    app_client: AsyncClient, app_auth_headers: dict, upload_dir
):
    cid = await _seed("cv.pdf")
    (upload_dir / f"candidate_{cid}_cv.pdf").write_bytes(b"%PDF-zwykly")
    try:
        r = await app_client.get(
            f"/api/candidates/{cid}/cv-download", headers=app_auth_headers
        )
        assert r.status_code == 200, r.text
        assert r.content == b"%PDF-zwykly"
    finally:
        await _delete(cid)


@pytest.mark.asyncio
async def test_bulk_download_skips_escaping_path_and_keeps_db_fallback(
    app_client: AsyncClient, app_auth_headers: dict, upload_dir
):
    escaping = await _seed("x/../../secret.pdf")
    (upload_dir / f"candidate_{escaping}_x").mkdir()
    # Nazwa z komponentami katalogu, ale bajty w bazie: dysk jest pomijany,
    # a CV nadal wychodzi z BYTEA pod oczyszczoną nazwą wpisu.
    from_db = await _seed("../../etc/passwd.pdf", cv_in_db=b"%PDF-z-bazy")
    try:
        r = await app_client.post(
            "/api/candidates/bulk-cv-download",
            headers=app_auth_headers,
            json={"candidate_ids": [escaping, from_db]},
        )
        assert r.status_code == 200, r.text
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            manifest = zf.read("_manifest.txt").decode()
            entries = [n for n in zf.namelist() if n != "_manifest.txt"]
            payloads = [zf.read(n) for n in entries]
        assert SECRET not in payloads
        assert f"{escaping}\t" in manifest
        assert "skipped_file_missing" in manifest
        assert payloads == [b"%PDF-z-bazy"]
        entry = entries[0]
        assert ".." not in entry and "/" not in entry and "\\" not in entry
        assert entry.endswith(f"_{from_db}.pdf")
    finally:
        await _delete(escaping, from_db)


@pytest.mark.asyncio
async def test_public_apply_persist_cv_strips_directory_components(upload_dir):
    """Publiczny formularz zapisywał plik pod nazwą z przeglądarki wprost.

    Nazwa z `/` kończyła się `FileNotFoundError` (500 PO utworzeniu kandydata),
    a zapisana nazwa trafiała do `cv_filename`, które czytają ścieżki wyżej.
    """
    from starlette.datastructures import UploadFile

    from app.api.public_share import _persist_cv

    upload = UploadFile(file=io.BytesIO(b"%PDF-apply"), filename="sub/../cv.pdf")
    stored, _text = await _persist_cv(987654321, upload, b"%PDF-apply")
    assert stored == "cv.pdf"
    written = upload_dir / "candidate_987654321_cv.pdf"
    assert written.read_bytes() == b"%PDF-apply"
    assert list(upload_dir.parent.glob("*.pdf")) == [upload_dir.parent / "secret.pdf"]
