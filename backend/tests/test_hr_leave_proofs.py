"""Załącznik do wniosku urlopowego — potwierdzenie nieobecności w e-teczce.

Compass miał przy wniosku plik do 5 MB (akt ślubu, urodzenia, zgonu,
krwiodawstwo). Tu: osoba dołącza go przy składaniu albo później, Kadry
pobierają, przełożony widzi tylko liczbę (D6), plik jest dokumentem e-teczki
rodzaju „potwierdzenie nieobecności”. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.hr_document import HrDocument
from app.models.hr_leave import LeaveRequest
from app.models.hr_ops import HrAuditEvent
from app.models.hr_profile import EmployeeProfile
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services import storage_service
from app.services.hr import leave_proofs, leave_queries, leave_substitute
from tests.hr_documents_seed import (
    docx_bytes,
    documents_on,  # noqa: F401  (fixture)
    documents_store_root,  # noqa: F401  (fixture)
    pdf_bytes,
    png_bytes,
)

#: E-teczka i moduły „Ludzi” włączone, magazyn plików w katalogu testu.
WITH_DOCUMENTS = pytest.mark.usefixtures("documents_on", "documents_store_root")

BASE = "/api/hr/leave"
DAY = date(2091, 11, 13)  # wtorek


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: str, *, profile: bool = False, **profile_values) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"proof-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if profile:
        db.add(EmployeeProfile(user_id=user.id, **profile_values))
        await db.flush()
    return user


async def _team():
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "recruiter", profile=True)
        worker = await _user(
            db, "employee", profile=True, employment_type="uop", manager_user_id=boss.id
        )
        hr = await _user(db, "employee", profile=True)
        db.add(
            UserActionOverride(user_id=hr.id, action="people_admin", access="manage")
        )
        await db.commit()
    return boss, worker, hr


async def _submit(
    client, worker: User, leave_type: str = "occasional", day: date = DAY
) -> dict:
    created = await client.post(
        BASE + "/requests",
        json={
            "leave_type": leave_type,
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
        },
        headers=_headers(worker),
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _attach(client, worker: User, request_id: str, content: bytes, name: str):
    return await client.post(
        f"{BASE}/requests/{request_id}/proofs",
        files={"file": (name, content, "application/octet-stream")},
        headers=_headers(worker),
    )


def _row(payload: dict, request_id: str) -> dict:
    found = [item for item in payload["items"] if item["id"] == request_id]
    assert found, payload
    return found[0]


@pytest.mark.asyncio
@WITH_DOCUMENTS
async def test_proof_reaches_person_and_hr_but_supervisor_sees_only_the_count(
    app_client,
) -> None:
    boss, worker, hr = await _team()
    request = await _submit(app_client, worker)
    assert request["proof_count"] == 0
    assert request["proofs"] == []
    assert request["can_add_proof"] is True

    content = pdf_bytes()
    attached = await _attach(
        app_client, worker, request["id"], content, "akt ślubu.pdf"
    )
    assert attached.status_code == 201, attached.text
    row = attached.json()
    assert row["proof_count"] == 1
    assert row["proofs"][0]["file_name"] == "akt ślubu.pdf"
    assert row["proofs"][0]["can_remove"] is True
    document_id = row["proofs"][0]["id"]

    mine = await app_client.get(BASE + "/my-requests", headers=_headers(worker))
    assert _row(mine.json(), request["id"])["proof_count"] == 1
    own_file = await app_client.get(
        f"{BASE}/requests/{request['id']}/proofs/{document_id}/file",
        headers=_headers(worker),
    )
    assert own_file.status_code == 200
    assert own_file.content == content

    # Przełożony: „Załącznik ✓” bez listy i bez pobrania (D6).
    queue = await app_client.get(BASE + "/approvals/pending", headers=_headers(boss))
    boss_row = _row(queue.json(), request["id"])
    assert boss_row["proof_count"] == 1
    assert boss_row["proofs"] is None
    denied = await app_client.get(
        f"{BASE}/approvals/{request['id']}/proofs/{document_id}/file",
        headers=_headers(boss),
    )
    assert denied.status_code == 403
    folder = await app_client.get(
        f"/api/hr/documents/people/{worker.id}", headers=_headers(boss)
    )
    assert folder.status_code == 404

    # Kadry: lista i pobranie, w e-teczce dokument „potwierdzenie nieobecności”.
    hr_queue = await app_client.get(BASE + "/approvals/pending", headers=_headers(hr))
    hr_row = _row(hr_queue.json(), request["id"])
    assert [proof["id"] for proof in hr_row["proofs"]] == [document_id]
    assert hr_row["proofs"][0]["can_remove"] is False
    hr_file = await app_client.get(
        f"{BASE}/approvals/{request['id']}/proofs/{document_id}/file",
        headers=_headers(hr),
    )
    assert hr_file.status_code == 200
    assert hr_file.content == content
    assert "attachment" in hr_file.headers["content-disposition"]

    folder = await app_client.get(
        f"/api/hr/documents/people/{worker.id}", headers=_headers(hr)
    )
    assert folder.status_code == 200
    (document,) = folder.json()["documents"]
    assert document["kind"] == "absence_proof"
    assert document["leave_request_id"] == request["id"]
    assert document["audience"] == {
        "person": True,
        "payroll": False,
        "equipment": False,
    }

    # Po akceptacji można dołączyć dalej (zaświadczenie przychodzi później).
    approved = await app_client.post(
        f"{BASE}/approvals/{request['id']}/approve", headers=_headers(boss)
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["proof_count"] == 1
    later = await _attach(app_client, worker, request["id"], png_bytes(), "skan.png")
    assert later.status_code == 201, later.text
    assert later.json()["proof_count"] == 2


@pytest.mark.asyncio
@WITH_DOCUMENTS
async def test_proof_download_from_request_leaves_the_folder_trace(app_client) -> None:
    """Pobranie załącznika z wniosku zostawia ten sam ślad co e-teczka.

    Audyt 21.10.2026: `GET /api/hr/documents/{id}/file` zapisuje
    `document_downloaded` (`sensitivity='health'` przy potwierdzeniu
    nieobecności), a obie trasy wniosku pobierały ten sam plik bez śladu.
    """

    _boss, worker, hr = await _team()
    request = await _submit(app_client, worker)
    attached = await _attach(app_client, worker, request["id"], pdf_bytes(), "akt.pdf")
    assert attached.status_code == 201, attached.text
    document_id = attached.json()["proofs"][0]["id"]

    own = await app_client.get(
        f"{BASE}/requests/{request['id']}/proofs/{document_id}/file",
        headers=_headers(worker),
    )
    assert own.status_code == 200
    team = await app_client.get(
        f"{BASE}/approvals/{request['id']}/proofs/{document_id}/file",
        headers=_headers(hr),
    )
    assert team.status_code == 200

    async with AsyncSessionLocal() as db:
        events = (
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.entity_type == "hr_document",
                    HrAuditEvent.action == "document_downloaded",
                    HrAuditEvent.entity_id == str(document_id),
                )
            )
        ).all()
    assert sorted(
        (e.actor_user_id, e.subject_user_id, e.sensitivity, e.details["kind"])
        for e in events
    ) == sorted(
        [
            (worker.id, worker.id, "health", "absence_proof"),
            (hr.id, worker.id, "health", "absence_proof"),
        ]
    )


@pytest.mark.asyncio
@WITH_DOCUMENTS
async def test_proof_refusals(app_client) -> None:
    boss, worker, hr = await _team()
    request = await _submit(app_client, worker, "blood_donation")
    rid = request["id"]

    word = await _attach(app_client, worker, rid, docx_bytes(), "akt.docx")
    assert word.status_code == 422
    assert "PDF" in word.json()["detail"]
    too_big = b"%PDF-1.4\n" + b"0" * (leave_proofs.MAX_PROOF_BYTES + 1)
    big = await _attach(app_client, worker, rid, too_big, "duzy.pdf")
    assert big.status_code == 422
    assert "5 MB" in big.json()["detail"]
    empty = await _attach(app_client, worker, rid, b"", "pusty.pdf")
    assert empty.status_code == 422

    # Cudzy wniosek: 404 także dla przełożonego i Kadr (dołącza tylko osoba).
    for outsider in (boss, hr):
        foreign = await _attach(app_client, outsider, rid, pdf_bytes(), "x.pdf")
        assert foreign.status_code == 404, outsider.name

    content = pdf_bytes()
    assert (await _attach(app_client, worker, rid, content, "a.pdf")).status_code == 201
    again = await _attach(app_client, worker, rid, content, "a-kopia.pdf")
    assert again.status_code == 409
    for index in range(leave_proofs.MAX_PROOFS_PER_REQUEST - 1):
        ok = await _attach(app_client, worker, rid, pdf_bytes(), f"{index}.pdf")
        assert ok.status_code == 201, ok.text
    over = await _attach(app_client, worker, rid, pdf_bytes(), "nadmiar.pdf")
    assert over.status_code == 409

    other = await _submit(app_client, worker, "childcare", DAY + timedelta(days=1))
    cancelled = await app_client.post(
        f"{BASE}/requests/{other['id']}/cancel", headers=_headers(worker)
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["can_add_proof"] is False
    late = await _attach(app_client, worker, other["id"], pdf_bytes(), "po.pdf")
    assert late.status_code == 409


@pytest.mark.asyncio
@WITH_DOCUMENTS
async def test_person_removes_own_proof_and_the_trace_stays_for_hr(app_client) -> None:
    _, worker, hr = await _team()
    request = await _submit(app_client, worker)
    attached = await _attach(app_client, worker, request["id"], pdf_bytes(), "zly.pdf")
    document_id = attached.json()["proofs"][0]["id"]
    async with AsyncSessionLocal() as db:
        stored = (await db.get(HrDocument, document_id)).file_path
    assert (Path(storage_service.STORAGE_ROOT) / stored).is_file()

    removed = await app_client.post(
        f"{BASE}/requests/{request['id']}/proofs/{document_id}/remove",
        headers=_headers(worker),
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["proof_count"] == 0
    assert not (Path(storage_service.STORAGE_ROOT) / stored).exists()
    gone = await app_client.get(
        f"{BASE}/requests/{request['id']}/proofs/{document_id}/file",
        headers=_headers(worker),
    )
    assert gone.status_code == 404

    folder = await app_client.get(
        f"/api/hr/documents/people/{worker.id}", headers=_headers(hr)
    )
    (trace,) = folder.json()["documents"]
    assert trace["deleted"] is True
    assert trace["deletion_reason"] == "mistake"


@pytest.mark.asyncio
@WITH_DOCUMENTS
async def test_proof_added_by_hr_cannot_be_removed_by_the_person(app_client) -> None:
    _, worker, hr = await _team()
    request = await _submit(app_client, worker)
    attached = await _attach(app_client, worker, request["id"], pdf_bytes(), "a.pdf")
    document_id = attached.json()["proofs"][0]["id"]
    async with AsyncSessionLocal() as db:
        document = await db.get(HrDocument, document_id)
        document.added_by = hr.id
        await db.commit()

    refused = await app_client.post(
        f"{BASE}/requests/{request['id']}/proofs/{document_id}/remove",
        headers=_headers(worker),
    )
    assert refused.status_code == 403
    async with AsyncSessionLocal() as db:
        still = await db.scalar(
            select(HrDocument.deleted_at).where(HrDocument.id == document_id)
        )
    assert still is None


def test_substitute_never_gets_files_and_no_count_for_hidden_types() -> None:
    cover = leave_substitute.Cover(
        manager_user_id=1, manager_name="Przełożony", until=DAY
    )
    for leave_type, count in (("sick_leave", None), ("occasional", 2)):
        row = LeaveRequest(user_id=2, leave_type=leave_type)
        item = {"proof_count": 2, "proofs": [{"id": 1}], "note": "x"}
        leave_queries._mark_cover(item, row, cover)
        assert item["proofs"] is None
        assert item["proof_count"] == count


def test_suggested_types_and_mime_mirror_the_frontend() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "components"
        / "hr"
        / "leave"
        / "leave-proofs.ts"
    ).read_text(encoding="utf-8")
    for leave_type in leave_proofs.SUGGESTED_TYPES:
        assert f'"{leave_type}"' in source
    assert "5 * 1024 * 1024" in source
