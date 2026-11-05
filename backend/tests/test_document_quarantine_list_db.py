"""Lista plików profilu wie, co jest w kwarantannie i co jest kopią (Postgres).

Do 05.11.2026 zwolnić plik dało się tylko z API, a lista plików nie mówiła, który
plik jest w kwarantannie. Dane fikcyjne.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.candidate_source_identity_review import (
    CandidateSourceIdentityReview,
)
from app.models.user import User, UserRole
from app.services import cv_source

pytestmark = pytest.mark.asyncio

FOREIGN_FILE = b"%PDF-1.4 fikcyjne CV z kwarantanny"
OWN_FILE = b"%PDF-1.4 fikcyjne CV osoby"
NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)
REASON = {"reason": "W nagłówku stanowisko, w pliku ta osoba"}


async def _profile(extracted: dict | None = None) -> int:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Anna",
            lastname=f"Fikcyjna{uuid.uuid4().hex[:8]}",
            cv_extracted_data=extracted or {},
        )
        db.add(candidate)
        await db.commit()
        return candidate.id


async def _document(
    candidate_id: int,
    content: bytes,
    *,
    filename: str = "cv.pdf",
    stored_hash: bool = False,
    removed: bool = False,
) -> int:
    async with AsyncSessionLocal() as db:
        document = CandidateDocument(
            candidate_id=candidate_id,
            filename=filename,
            file_content=content,
            content_sha256=hashlib.sha256(content).hexdigest() if stored_hash else None,
            document_kind=CandidateDocumentKind.cv,
            is_primary=False,
            uploaded_at=NOW - timedelta(days=1),
            source_deleted_at=NOW if removed else None,
        )
        db.add(document)
        await db.commit()
        return document.id


async def _quarantine(
    candidate_id: int, document_id: int, provenance: str = "cv_parser:document"
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateSourceIdentityReview(
                candidate_id=candidate_id,
                source_kind="document",
                source_id=document_id,
                decision="confirmed_mismatch",
                provenance=provenance,
                detector_version="test",
                evidence={},
                reviewed_at=NOW,
            )
        )
        await db.commit()


async def _headers_for(client: AsyncClient, role: UserRole) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Q"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Fikcyjne konto",
                role=role,
                roles=[role.value],
                is_active=True,
            )
        )
        await db.commit()
    response = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _states(
    client: AsyncClient, headers: dict[str, str], candidate_id: int
) -> dict[int, dict]:
    response = await client.get(
        f"/api/candidates/{candidate_id}/identity-quarantine", headers=headers
    )
    assert response.status_code == 200, response.text
    return {item["document_id"]: item for item in response.json()}


async def _release(
    client: AsyncClient, headers: dict[str, str], candidate_id: int, document_id: int
):
    return await client.post(
        f"/api/candidates/{candidate_id}/identity-quarantine/document/{document_id}/override",
        headers=headers,
        json=REASON,
    )


async def test_quarantined_file_and_its_copy_point_at_the_file_to_release(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _profile()
    source_id = await _document(
        candidate_id, FOREIGN_FILE, filename="zrodlo.pdf", stored_hash=True
    )
    await _quarantine(candidate_id, source_id)
    copy_id = await _document(candidate_id, FOREIGN_FILE, filename="kopia.pdf")
    own_id = await _document(candidate_id, OWN_FILE, filename="wlasne.pdf")

    states = await _states(app_client, app_auth_headers, candidate_id)

    assert set(states) == {source_id, copy_id}
    assert own_id not in states
    assert states[source_id]["state"] == "quarantined"
    assert states[copy_id]["state"] == "copy"
    for item in states.values():
        assert item["source_document_id"] == source_id
        assert item["source_filename"] == "zrodlo.pdf"
        assert item["source_removed"] is False
        assert item["manual"] is False


async def test_human_decision_is_told_apart_from_the_parser(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _profile()
    source_id = await _document(candidate_id, FOREIGN_FILE)
    await _quarantine(candidate_id, source_id, provenance="manual:manual_review")

    states = await _states(app_client, app_auth_headers, candidate_id)

    assert states[source_id]["manual"] is True


async def test_profile_without_quarantine_has_an_empty_list(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _profile()
    await _document(candidate_id, OWN_FILE)

    assert await _states(app_client, app_auth_headers, candidate_id) == {}


async def test_missing_candidate_is_404(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    response = await app_client.get(
        "/api/candidates/2147483000/identity-quarantine", headers=app_auth_headers
    )
    assert response.status_code == 404


async def test_release_clears_the_file_and_its_copies_from_the_list(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _profile()
    source_id = await _document(candidate_id, FOREIGN_FILE, stored_hash=True)
    await _quarantine(candidate_id, source_id)
    await _document(candidate_id, FOREIGN_FILE, filename="kopia.pdf")

    response = await _release(app_client, app_auth_headers, candidate_id, source_id)

    assert response.status_code == 200, response.text
    assert await _states(app_client, app_auth_headers, candidate_id) == {}


async def test_copy_of_a_removed_file_can_still_be_released(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Usunięty oryginał nie ma wiersza na liście, a nadal trzyma kopię."""
    candidate_id = await _profile()
    source_id = await _document(
        candidate_id,
        FOREIGN_FILE,
        filename="usuniety.pdf",
        stored_hash=True,
        removed=True,
    )
    await _quarantine(candidate_id, source_id)
    copy_id = await _document(candidate_id, FOREIGN_FILE, filename="kopia.pdf")

    states = await _states(app_client, app_auth_headers, candidate_id)

    assert set(states) == {copy_id}
    assert states[copy_id]["source_document_id"] == source_id
    assert states[copy_id]["source_removed"] is True

    response = await _release(app_client, app_auth_headers, candidate_id, source_id)

    assert response.status_code == 200, response.text
    assert await _states(app_client, app_auth_headers, candidate_id) == {}


async def test_recruiter_sees_the_state_but_the_server_refuses_the_release(
    app_client: AsyncClient,
) -> None:
    candidate_id = await _profile()
    source_id = await _document(candidate_id, FOREIGN_FILE)
    await _quarantine(candidate_id, source_id)
    recruiter = await _headers_for(app_client, UserRole.recruiter)

    response = await _release(app_client, recruiter, candidate_id, source_id)

    assert response.status_code == 403
    states = await _states(app_client, recruiter, candidate_id)
    assert states[source_id]["state"] == "quarantined"


async def test_head_of_recruitment_releases(app_client: AsyncClient) -> None:
    candidate_id = await _profile()
    source_id = await _document(candidate_id, FOREIGN_FILE)
    await _quarantine(candidate_id, source_id)

    response = await _release(
        app_client,
        await _headers_for(app_client, UserRole.head_of_recruitment),
        candidate_id,
        source_id,
    )

    assert response.status_code == 200, response.text
    assert response.json()["override_active"] is True


async def test_release_removes_the_profile_notice_only_for_that_file(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _profile()
    source_id = await _document(candidate_id, FOREIGN_FILE)
    other_id = await _document(candidate_id, OWN_FILE, filename="drugi.pdf")
    await _quarantine(candidate_id, source_id)
    await _quarantine(candidate_id, other_id)
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        candidate.cv_extracted_data = {
            "_identity_quarantine_source": {"kind": "document", "id": source_id},
            "_manual_override_skills": True,
        }
        await db.commit()

    async def extracted() -> dict:
        async with AsyncSessionLocal() as db:
            return await db.scalar(
                select(Candidate.cv_extracted_data).where(Candidate.id == candidate_id)
            )

    await _release(app_client, app_auth_headers, candidate_id, other_id)
    assert (await extracted())["_identity_quarantine_source"]["id"] == source_id

    await _release(app_client, app_auth_headers, candidate_id, source_id)
    assert await extracted() == {"_manual_override_skills": True}


async def test_copy_sources_prefer_the_file_still_on_the_list() -> None:
    candidate_id = await _profile()
    removed_id = await _document(
        candidate_id, FOREIGN_FILE, stored_hash=True, removed=True
    )
    await _quarantine(candidate_id, removed_id)
    live_id = await _document(candidate_id, FOREIGN_FILE, filename="zywy.pdf")
    await _quarantine(candidate_id, live_id)
    copy_id = await _document(candidate_id, FOREIGN_FILE, filename="kopia.pdf")

    async with AsyncSessionLocal() as db:
        sources = await cv_source.quarantined_copy_sources(db, candidate_id)
        ids = await cv_source.quarantined_copy_document_ids(db, candidate_id)

    assert sources == {copy_id: live_id}
    assert ids == frozenset({copy_id})
