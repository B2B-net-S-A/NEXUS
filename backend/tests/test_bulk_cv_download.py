"""Tests for POST /api/candidates/bulk-cv-download."""

from __future__ import annotations

import io
import os
import uuid
import zipfile

import pytest
from httpx import AsyncClient


async def _seed_candidate(
    *,
    first: str,
    last: str,
    cv_filename: str | None = None,
    cv_on_disk: bytes | None = None,
    cv_in_db: bytes | None = None,
) -> int:
    """Insert a candidate directly and optionally place a CV file on disk."""
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=first,
            lastname=last,
            email=f"bulk-{uuid.uuid4().hex[:8]}@example.com",
            cv_filename=cv_filename,
            cv_file_content=cv_in_db,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        cid = cand.id

    if cv_on_disk is not None and cv_filename:
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        # Mirror the production write invariant while retaining the hostile
        # value in the DB. The endpoint must sanitize again on read because
        # imported legacy rows may not have gone through the upload handler.
        disk_name = os.path.basename(cv_filename.replace("\\", "/"))
        with open(
            os.path.join(settings.UPLOAD_DIR, f"candidate_{cid}_{disk_name}"), "wb"
        ) as f:
            f.write(cv_on_disk)

    return cid


async def _delete_candidate(candidate_id: int, cv_filename: str | None) -> None:
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        cand = await db.get(Candidate, candidate_id)
        if cand is not None:
            await db.delete(cand)
            await db.commit()

    if cv_filename:
        disk_name = os.path.basename(cv_filename.replace("\\", "/"))
        path = os.path.join(
            settings.UPLOAD_DIR, f"candidate_{candidate_id}_{disk_name}"
        )
        if os.path.exists(path):
            os.remove(path)


async def test_bulk_cv_download_unauthorized(app_client: AsyncClient):
    r = await app_client.post(
        "/api/candidates/bulk-cv-download", json={"candidate_ids": [1, 2]}
    )
    assert r.status_code in (401, 403)


async def test_bulk_cv_download_empty_list_400(
    app_client: AsyncClient, app_auth_headers: dict
):
    r = await app_client.post(
        "/api/candidates/bulk-cv-download",
        headers=app_auth_headers,
        json={"candidate_ids": []},
    )
    assert r.status_code == 422  # Pydantic min_length=1 violation


async def test_bulk_cv_download_over_limit_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    r = await app_client.post(
        "/api/candidates/bulk-cv-download",
        headers=app_auth_headers,
        json={"candidate_ids": list(range(1, 202))},
    )
    assert r.status_code == 422  # max_length=200


async def test_bulk_cv_download_happy_path(
    app_client: AsyncClient, app_auth_headers: dict
):
    ids: list[tuple[int, str]] = []
    ids.append(
        (
            await _seed_candidate(
                first="Anna",
                last="Kowalska",
                cv_filename="cv.pdf",
                cv_on_disk=b"%PDF-1.4 fake-a",
            ),
            "cv.pdf",
        )
    )
    ids.append(
        (
            await _seed_candidate(
                first="Jan",
                last="Nowak",
                cv_filename="resume.pdf",
                cv_on_disk=b"%PDF-1.4 fake-b",
            ),
            "resume.pdf",
        )
    )
    try:
        r = await app_client.post(
            "/api/candidates/bulk-cv-download",
            headers=app_auth_headers,
            json={"candidate_ids": [c[0] for c in ids]},
        )
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"
        assert r.headers["x-included-count"] == "2"
        assert r.headers["x-skipped-count"] == "0"
        assert "nexus-cvs-" in r.headers["content-disposition"]

        with zipfile.ZipFile(io.BytesIO(r.content), "r") as zf:
            names = zf.namelist()
            assert "_manifest.txt" in names
            # 2 CVs + manifest
            assert len(names) == 3
            # Filenames follow Lastname_Firstname_ID.pdf
            assert any(n.startswith("Kowalska_Anna_") and n.endswith(".pdf") for n in names)
            assert any(n.startswith("Nowak_Jan_") and n.endswith(".pdf") for n in names)
            manifest = zf.read("_manifest.txt").decode("utf-8")
            assert manifest.count("\tincluded") == 2
    finally:
        for cid, fn in ids:
            await _delete_candidate(cid, fn)


async def test_bulk_cv_download_mixed_sources_and_missing(
    app_client: AsyncClient, app_auth_headers: dict
):
    disk_id = await _seed_candidate(
        first="Disk",
        last="Candidate",
        cv_filename="on-disk.pdf",
        cv_on_disk=b"%PDF-disk",
    )
    db_id = await _seed_candidate(
        first="DB",
        last="Candidate",
        cv_filename="in-db.pdf",
        cv_in_db=b"%PDF-db",
    )
    no_cv_id = await _seed_candidate(first="NoCv", last="Candidate")

    try:
        r = await app_client.post(
            "/api/candidates/bulk-cv-download",
            headers=app_auth_headers,
            json={"candidate_ids": [disk_id, db_id, no_cv_id, 99_999_999]},
        )
        assert r.status_code == 200
        assert r.headers["x-included-count"] == "2"
        assert r.headers["x-skipped-count"] == "2"

        with zipfile.ZipFile(io.BytesIO(r.content), "r") as zf:
            names = zf.namelist()
            assert len(names) == 3  # 2 CVs + manifest
            manifest = zf.read("_manifest.txt").decode("utf-8")
            assert "skipped_no_cv" in manifest
            assert "skipped_not_found" in manifest
            assert manifest.count("\tincluded") == 2
            # DB-only content made it in
            db_entry = next(
                n for n in names if n.startswith("Candidate_DB_")
            )
            assert zf.read(db_entry) == b"%PDF-db"
    finally:
        await _delete_candidate(disk_id, "on-disk.pdf")
        await _delete_candidate(db_id, None)
        await _delete_candidate(no_cv_id, None)


async def test_bulk_cv_download_sanitizes_filenames(
    app_client: AsyncClient, app_auth_headers: dict
):
    # Path-traversal attempt in cv_filename; entry name must be sanitized.
    hostile = "../../etc/passwd.pdf"
    cid = await _seed_candidate(
        first="Evil/../X",
        last="Hack\\er",
        cv_filename=hostile,
        cv_on_disk=b"%PDF-evil",
    )
    try:
        r = await app_client.post(
            "/api/candidates/bulk-cv-download",
            headers=app_auth_headers,
            json={"candidate_ids": [cid]},
        )
        assert r.status_code == 200
        with zipfile.ZipFile(io.BytesIO(r.content), "r") as zf:
            names = [n for n in zf.namelist() if n != "_manifest.txt"]
            assert len(names) == 1
            entry = names[0]
            assert ".." not in entry
            assert "/" not in entry
            assert "\\" not in entry
            assert entry.endswith(".pdf")
    finally:
        await _delete_candidate(cid, hostile)
