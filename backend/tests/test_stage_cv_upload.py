"""Nowe CV z rekrutacji — `POST /api/candidates/stages/{id}/cv/original/upload`
i `…/cv/original/refresh` na etapie bez wiersza CV (13.10.2026).

Kafelek „Wgraj nowe CV” w panelu osoby i okno „Dodaj z CV” robią jedno: plik
staje się głównym CV profilu i od razu kopią CV etapu („Oryginał CV”). Do tej
daty nowe CV wgrane w profilu nie zmieniało kopii w rekrutacji, a ręczne
„Aktualizuj snapshot” dawało 404 na etapach z importu Traffita (bez wiersza
CV), czyli na większości kart w „Nowych” i „Screeningu”.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate_document import CandidateDocument
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import UserRole
from app.services.candidate_stage_cv_service import create_original_cv_snapshot
from tests.test_candidate_stage_cv_snapshot import (
    _seed_candidate_with_cv,
    _seed_job,
    _seed_stage,
)
from tests.test_job_proposals import _user

pytestmark = pytest.mark.asyncio

NEW_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
)


@pytest.fixture(autouse=True)
def _no_cv_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    # Odczyt AI biegnie w tle po odpowiedzi; pusty tekst kończy go od razu.
    monkeypatch.setattr(
        "app.services.cv_text_extractor.extract_text",
        lambda *_args, **_kwargs: "",
    )


async def _stage_with_snapshot(*, snapshot: bool = True) -> tuple[int, int]:
    cid = await _seed_candidate_with_cv(
        cv_bytes=b"%PDF-1.4 OLD", cv_filename="stare.pdf"
    )
    sid = await _seed_stage(cid, await _seed_job())
    if snapshot:
        async with AsyncSessionLocal() as db:
            stage = await db.scalar(
                select(CandidateStage).where(CandidateStage.id == sid)
            )
            await create_original_cv_snapshot(db, stage)
            await db.commit()
    return cid, sid


async def _upload(
    client: AsyncClient,
    headers: dict[str, str],
    stage_id: int,
    *,
    filename: str = "nowe-cv.pdf",
    content: bytes = NEW_PDF,
):
    return await client.post(
        f"/api/candidates/stages/{stage_id}/cv/original/upload",
        headers=headers,
        files={"file": (filename, content, "application/pdf")},
    )


async def _documents(candidate_id: int) -> list[CandidateDocument]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CandidateDocument)
                    .where(CandidateDocument.candidate_id == candidate_id)
                    .order_by(CandidateDocument.id)
                )
            ).all()
        )


async def test_refresh_creates_missing_stage_cv_row(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    cid, sid = await _stage_with_snapshot(snapshot=False)

    res = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/original/refresh", headers=app_auth_headers
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["has_snapshot"] is True
    assert body["original_snapshot_source"] == "manual_refresh"
    assert body["candidate_id"] == cid


async def test_upload_makes_primary_cv_and_replaces_stage_copy(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    cid, sid = await _stage_with_snapshot()

    res = await _upload(app_client, app_auth_headers, sid)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["original_cv_filename"] == "nowe-cv.pdf"
    assert body["original_snapshot_source"] == "manual_upload"
    assert body["has_snapshot"] is True

    docs = await _documents(cid)
    primary = [d for d in docs if d.is_primary]
    assert [d.filename for d in primary] == ["nowe-cv.pdf"]

    download = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/original/download", headers=app_auth_headers
    )
    assert download.status_code == 200, download.text
    assert download.content == NEW_PDF

    async with AsyncSessionLocal() as db:
        csv_id = await db.scalar(
            select(CandidateStageCV.id).where(
                CandidateStageCV.candidate_stage_id == sid
            )
        )
        details = await db.scalar(
            select(Activity.details)
            .where(
                Activity.entity_type == "candidate_stage_cv",
                Activity.entity_id == csv_id,
                Activity.action == "snapshot_refreshed",
            )
            .order_by(Activity.id.desc())
            .limit(1)
        )
    assert details["snapshot_source"] == "manual_upload"
    assert details["old_filename"] == "stare.pdf"
    assert details["new_filename"] == "nowe-cv.pdf"


async def test_upload_on_stage_without_cv_row_creates_it(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    _, sid = await _stage_with_snapshot(snapshot=False)

    res = await _upload(app_client, app_auth_headers, sid)

    assert res.status_code == 200, res.text
    assert res.json()["original_snapshot_source"] == "manual_upload"


async def test_upload_refuses_formats_the_stage_copy_cannot_use(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    cid, sid = await _stage_with_snapshot()

    res = await _upload(
        app_client, app_auth_headers, sid, filename="cv.odt", content=b"odt"
    )

    assert res.status_code == 415, res.text
    assert "PDF, DOC albo DOCX" in res.json()["detail"]
    assert await _documents(cid) == []
    original = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/original", headers=app_auth_headers
    )
    assert original.json()["original_cv_filename"] == "stare.pdf"


async def test_same_file_already_in_profile_becomes_primary(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    cid, sid = await _stage_with_snapshot()
    for filename, content, primary in (
        ("glowne.pdf", b"%PDF-1.4 glowne " + uuid.uuid4().hex.encode(), "true"),
        ("angielskie.pdf", NEW_PDF, "false"),
    ):
        res = await app_client.post(
            f"/api/candidates/{cid}/documents",
            headers=app_auth_headers,
            files={"file": (filename, content, "application/pdf")},
            data={"document_kind": "cv", "is_primary": primary},
        )
        assert res.status_code == 201, res.text

    res = await _upload(app_client, app_auth_headers, sid, filename="angielskie.pdf")

    assert res.status_code == 200, res.text
    docs = await _documents(cid)
    assert len(docs) == 2
    assert [d.filename for d in docs if d.is_primary] == ["angielskie.pdf"]


async def test_role_without_candidate_write_is_refused_before_any_write(
    app_client: AsyncClient,
) -> None:
    # Bramka zespołu rekrutacji jest otwarta dla każdej roli wewnętrznej
    # (decyzja z 23.09.2026), więc odmowa idzie z prawa zapisu kandydata.
    cid, sid = await _stage_with_snapshot()
    _, viewer_headers = await _user(UserRole.user)

    res = await _upload(app_client, viewer_headers, sid)

    assert res.status_code == 403, res.text
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(CandidateDocument)
            .where(CandidateDocument.candidate_id == cid)
        )
    assert count == 0


async def _stage_copy_of(
    content: bytes, *, candidate_cv: bytes | None
) -> tuple[int, int]:
    """Etap z kopią CV `content` u osoby, której bieżące CV to `candidate_cv`."""
    cid = await _seed_candidate_with_cv(cv_bytes=candidate_cv, cv_filename="wlasne.pdf")
    sid = await _seed_stage(cid, await _seed_job())
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStageCV(
                candidate_stage_id=sid,
                candidate_id=cid,
                job_id=(
                    await db.scalar(
                        select(CandidateStage.job_id).where(CandidateStage.id == sid)
                    )
                ),
                original_cv_filename="cudze.pdf",
                original_cv_content=content,
                original_cv_sha256=hashlib.sha256(content).hexdigest(),
                original_snapshot_source="manual_upload",
            )
        )
        await db.commit()
    return cid, sid


async def test_quarantine_puts_the_persons_own_cv_back_into_stage_copies() -> None:
    from app.models.candidate import Candidate
    from app.services.candidate_stage_cv_service import (
        restore_stage_copies_after_quarantine,
    )

    wrong = b"%PDF-1.4 CV innej osoby"
    cid, sid = await _stage_copy_of(wrong, candidate_cv=b"%PDF-1.4 wlasne CV")
    async with AsyncSessionLocal() as db:
        candidate = await db.scalar(select(Candidate).where(Candidate.id == cid))
        fixed = await restore_stage_copies_after_quarantine(
            db,
            candidate=candidate,
            quarantined_sha256=hashlib.sha256(wrong).hexdigest(),
        )
        await db.commit()
        row = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
    assert fixed == 1
    assert row.original_snapshot_source == "quarantine_restore"
    assert row.original_cv_sha256 == hashlib.sha256(b"%PDF-1.4 wlasne CV").hexdigest()
    assert row.original_cv_filename == "wlasne.pdf"


async def test_quarantine_without_own_cv_leaves_stage_copy_empty() -> None:
    from app.models.candidate import Candidate
    from app.services.candidate_stage_cv_service import (
        restore_stage_copies_after_quarantine,
        snapshot_exists,
    )

    wrong = b"%PDF-1.4 CV innej osoby " + uuid.uuid4().hex.encode()
    cid, sid = await _stage_copy_of(wrong, candidate_cv=None)
    async with AsyncSessionLocal() as db:
        candidate = await db.scalar(select(Candidate).where(Candidate.id == cid))
        await restore_stage_copies_after_quarantine(
            db,
            candidate=candidate,
            quarantined_sha256=hashlib.sha256(wrong).hexdigest(),
        )
        await db.commit()
        row = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
    assert not snapshot_exists(row)
    assert row.original_cv_sha256 is None


async def test_candidate_pipelines_say_which_board_column_the_card_is_in(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    # Okno „Dodaj z CV” decyduje o podmianie CV tą samą regułą co Tablica
    # i `proposals/bulk` (zatrudniony ≠ zamknięty).
    from app.models.recruitment_pipeline import PipelineStage

    cid = await _seed_candidate_with_cv()
    in_progress_job, hired_job = await _seed_job(), await _seed_job()
    await _seed_stage(cid, in_progress_job)
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=cid, job_id=hired_job, stage=PipelineStage.hired
            )
        )
        await db.commit()

    res = await app_client.get(
        f"/api/candidates/{cid}/pipelines", headers=app_auth_headers
    )

    assert res.status_code == 200, res.text
    columns = {row["job_id"]: row["board_column"] for row in res.json()["pipelines"]}
    assert columns == {in_progress_job: "new", hired_job: "hired"}
