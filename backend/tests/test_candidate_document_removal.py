"""„Usuń z profilu” przy pliku kandydata (0435, decyzja Artura 13.10.2026).

Kontrakt, który łatwo cicho złamać:

- usuwa wyłącznie admin i Head of Recruitment (rekruter i Delivery Lead: 403),
- plik znika z listy, pobierania, źródeł generatora i „bieżącego CV”, ale
  wiersz i klucz w magazynie zostają (CV nie kasujemy nigdy) razem z tym,
  kto i kiedy usunął,
- główne CV też wolno usunąć: następcy nie wybieramy sami, a wskaźnik CV na
  kandydacie przestaje pokazywać na usunięty plik — także wtedy, gdy trzyma
  własną kopię pod innym kluczem (import z Traffita wgrywał CV dwa razy),
- ten sam plik da się potem wgrać ponownie jako nowy wiersz.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


def _pdf(tag: str) -> bytes:
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
        + f"% {tag}\n".encode()
    )


async def _headers_for(client: AsyncClient, role: UserRole) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"doc-remove-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Rm"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Doc Remove {role.value}",
                role=role,
                roles=[role.value],
                is_active=True,
            )
        )
        await db.commit()
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _candidate(client: AsyncClient, headers: dict[str, str]) -> int:
    unique = uuid.uuid4().hex[:8]
    created = await client.post(
        "/api/candidates",
        headers=headers,
        json={
            "name": "Plik",
            "lastname": f"Usuwany-{unique}",
            "email": f"doc-remove-{unique}@example.com",
        },
    )
    assert created.status_code in (200, 201), created.text
    return created.json()["id"]


async def _upload_cv(
    client: AsyncClient,
    headers: dict[str, str],
    candidate_id: int,
    *,
    content: bytes | None = None,
) -> int:
    name = f"cv-{uuid.uuid4().hex[:8]}.pdf"
    resp = await client.post(
        f"/api/candidates/{candidate_id}/documents",
        headers=headers,
        files={
            "file": (name, content or _pdf(name), "application/pdf"),
        },
        data={"document_kind": "cv"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _listed_ids(
    client: AsyncClient, headers: dict[str, str], candidate_id: int
) -> list[int]:
    listing = await client.get(
        f"/api/candidates/{candidate_id}/documents", headers=headers
    )
    assert listing.status_code == 200, listing.text
    return [row["id"] for row in listing.json()]


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.head_of_recruitment])
async def test_admin_and_head_of_recruitment_remove_a_file(
    app_client: AsyncClient, app_auth_headers: dict[str, str], role: UserRole
) -> None:
    candidate_id = await _candidate(app_client, app_auth_headers)
    primary_id = await _upload_cv(app_client, app_auth_headers, candidate_id)
    other_id = await _upload_cv(app_client, app_auth_headers, candidate_id)
    headers = await _headers_for(app_client, role)

    removed = await app_client.delete(
        f"/api/candidates/{candidate_id}/documents/{other_id}", headers=headers
    )
    assert removed.status_code == 204, removed.text

    assert await _listed_ids(app_client, app_auth_headers, candidate_id) == [primary_id]
    content = await app_client.get(
        f"/api/candidates/{candidate_id}/documents/{other_id}/content",
        headers=app_auth_headers,
    )
    assert content.status_code == 404
    again = await app_client.delete(
        f"/api/candidates/{candidate_id}/documents/{other_id}", headers=headers
    )
    assert again.status_code == 404

    async with AsyncSessionLocal() as db:
        row = await db.get(CandidateDocument, other_id)
        # Nic nie jest kasowane: wiersz zostaje z informacją, kto i kiedy.
        assert row is not None
        assert row.source_deleted_at is not None
        assert row.removed_at is not None
        assert row.removed_by is not None
        assert row.is_primary is False
        audit = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == candidate_id,
                    Activity.action == "candidate_document_removed",
                )
            )
        ).all()
        assert len(audit) == 1
        # Dziennik bez nazwy pliku (nazwa CV to zwykle imię i nazwisko).
        assert audit[0].details == {
            "doc_id": other_id,
            "document_kind": "cv",
            "was_primary": False,
        }


@pytest.mark.parametrize(
    "role",
    [
        UserRole.recruiter,
        UserRole.delivery_lead,
        UserRole.talent_community_manager,
        UserRole.finance,
        UserRole.user,
    ],
)
async def test_other_roles_cannot_remove_a_file(
    app_client: AsyncClient, app_auth_headers: dict[str, str], role: UserRole
) -> None:
    candidate_id = await _candidate(app_client, app_auth_headers)
    await _upload_cv(app_client, app_auth_headers, candidate_id)
    other_id = await _upload_cv(app_client, app_auth_headers, candidate_id)
    headers = await _headers_for(app_client, role)

    denied = await app_client.delete(
        f"/api/candidates/{candidate_id}/documents/{other_id}", headers=headers
    )
    assert denied.status_code == 403, denied.text
    assert other_id in await _listed_ids(app_client, app_auth_headers, candidate_id)


async def test_primary_cv_can_be_removed_and_no_successor_is_picked(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _candidate(app_client, app_auth_headers)
    # Pierwsze wgrane CV zostaje głównym, drugie leży obok.
    primary_id = await _upload_cv(app_client, app_auth_headers, candidate_id)
    other_id = await _upload_cv(app_client, app_auth_headers, candidate_id)

    removed = await app_client.delete(
        f"/api/candidates/{candidate_id}/documents/{primary_id}",
        headers=app_auth_headers,
    )
    assert removed.status_code == 204, removed.text

    listing = await app_client.get(
        f"/api/candidates/{candidate_id}/documents", headers=app_auth_headers
    )
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert [row["id"] for row in rows] == [other_id]
    # Nowe główne CV odświeża profil odczytem AI — wybiera je człowiek.
    assert rows[0]["is_primary"] is False

    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        assert candidate is not None
        assert candidate.cv_filename is None

    # Drugie CV dalej da się ustawić jako główne.
    promoted = await app_client.patch(
        f"/api/candidates/{candidate_id}/documents/{other_id}",
        headers=app_auth_headers,
        json={"is_primary": True},
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["is_primary"] is True


async def test_removing_the_only_cv_detaches_the_candidate_cv_pointer(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.services.cv_source import get_current_cv

    candidate_id = await _candidate(app_client, app_auth_headers)
    content = _pdf(f"only-{uuid.uuid4().hex}")
    doc_id = await _upload_cv(
        app_client, app_auth_headers, candidate_id, content=content
    )
    # CV z formularza kariery leży też wprost na kandydacie — `get_current_cv`
    # wraca do tej kopii, gdy nie znajdzie dokumentu.
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        document = await db.get(CandidateDocument, doc_id)
        assert candidate is not None and document is not None
        assert document.content_sha256 == hashlib.sha256(content).hexdigest()
        candidate.cv_filename = document.filename
        candidate.cv_file_content = content
        await db.commit()

    removed = await app_client.delete(
        f"/api/candidates/{candidate_id}/documents/{doc_id}",
        headers=app_auth_headers,
    )
    assert removed.status_code == 204, removed.text

    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        assert candidate is not None
        assert candidate.cv_filename is None
        assert candidate.cv_file_content is None
        # Generator, QC i migawka CV etapu nie dostają już tego pliku.
        assert await get_current_cv(db, candidate) is None

    sources = await app_client.get(
        f"/api/cv-generator/candidates/{candidate_id}/cv-sources",
        headers=app_auth_headers,
    )
    assert sources.status_code == 200, sources.text
    assert sources.json() == []


async def _seed_stored_cv(
    candidate_id: int, *, filename: str, storage_key: str, is_primary: bool
) -> int:
    """Wiersz dokumentu jak po imporcie: plik w magazynie, bez bajtów w bazie."""
    async with AsyncSessionLocal() as db:
        document = CandidateDocument(
            candidate_id=candidate_id,
            filename=filename,
            storage_key=storage_key,
            content_type="application/pdf",
            document_kind=CandidateDocumentKind.cv,
            is_primary=is_primary,
            external_source="traffit",
        )
        db.add(document)
        await db.flush()
        document_id = document.id
        await db.commit()
        return document_id


async def _set_pointer(
    candidate_id: int, *, filename: str | None, storage_key: str
) -> None:
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        assert candidate is not None
        candidate.cv_filename = filename
        candidate.cv_storage_key = storage_key
        await db.commit()


async def _pointer(candidate_id: int) -> tuple[str | None, str | None]:
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        assert candidate is not None
        return candidate.cv_filename, candidate.cv_storage_key


async def _pointer_copies(candidate_id: int) -> list[CandidateDocument]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(CandidateDocument).where(
                    CandidateDocument.candidate_id == candidate_id,
                    CandidateDocument.external_source == "legacy_pointer",
                )
            )
        )


async def test_pointer_holding_its_own_copy_of_the_file_is_detached(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Import z Traffita: to samo CV pod dwoma kluczami (wskaźnik i dokument).

    Bez odpięcia `get_current_cv` wracałby do klucza wskaźnika (migawka CV
    etapu, paczka ZIP), a `entrypoint.sh` po wdrożeniu odtworzyłby dokument.
    """
    from app.services.cv_source import get_current_cv

    candidate_id = await _candidate(app_client, app_auth_headers)
    unique = uuid.uuid4().hex[:8]
    doc_key, pointer_key = f"cv/doc-{unique}.pdf", f"cv/pointer-{unique}.pdf"
    doc_id = await _seed_stored_cv(
        candidate_id, filename="CV_Import.pdf", storage_key=doc_key, is_primary=True
    )
    # Ta sama nazwa bez względu na wielkość liter — tak porównuje entrypoint.
    await _set_pointer(candidate_id, filename="cv_import.PDF", storage_key=pointer_key)

    removed = await app_client.delete(
        f"/api/candidates/{candidate_id}/documents/{doc_id}",
        headers=app_auth_headers,
    )
    assert removed.status_code == 204, removed.text

    assert await _pointer(candidate_id) == (None, None)
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        assert candidate is not None
        assert await get_current_cv(db, candidate) is None

    # Druga kopia zostaje w magazynie i ma wiersz — klucz nie traci wskaźnika.
    copies = await _pointer_copies(candidate_id)
    assert [copy.storage_key for copy in copies] == [pointer_key]
    assert copies[0].source_deleted_at is not None
    assert copies[0].removed_at is not None
    assert copies[0].is_primary is False
    assert await _listed_ids(app_client, app_auth_headers, candidate_id) == []


async def test_pointer_of_another_file_in_the_profile_is_left_alone(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _candidate(app_client, app_auth_headers)
    unique = uuid.uuid4().hex[:8]
    new_key, old_key = f"cv/new-{unique}.pdf", f"cv/old-{unique}.pdf"
    new_id = await _seed_stored_cv(
        candidate_id, filename="cv-nowe.pdf", storage_key=new_key, is_primary=True
    )
    old_id = await _seed_stored_cv(
        candidate_id, filename="cv-stare.pdf", storage_key=old_key, is_primary=False
    )
    # Wskaźnik został przy starszym CV, które dalej leży w profilu.
    await _set_pointer(candidate_id, filename="cv-stare.pdf", storage_key=old_key)

    removed = await app_client.delete(
        f"/api/candidates/{candidate_id}/documents/{new_id}",
        headers=app_auth_headers,
    )
    assert removed.status_code == 204, removed.text
    assert await _pointer(candidate_id) == ("cv-stare.pdf", old_key)
    assert await _pointer_copies(candidate_id) == []

    # Dopiero usunięcie pliku, na który pokazuje, odpina wskaźnik.
    removed = await app_client.delete(
        f"/api/candidates/{candidate_id}/documents/{old_id}",
        headers=app_auth_headers,
    )
    assert removed.status_code == 204, removed.text
    assert await _pointer(candidate_id) == (None, None)
    # Ten sam klucz co w usuniętym wierszu — drugiego wiersza nie trzeba.
    assert await _pointer_copies(candidate_id) == []


async def test_pointer_named_after_the_removed_file_follows_its_key(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Nowe główne CV zmienia we wskaźniku samą nazwę; klucz zostaje przy
    starszym pliku. Bez poprawy nazwy zasilanie w `entrypoint.sh` odtworzyłoby
    po wdrożeniu główne CV o nazwie usuniętego pliku."""
    candidate_id = await _candidate(app_client, app_auth_headers)
    unique = uuid.uuid4().hex[:8]
    old_key = f"cv/old-{unique}.pdf"
    await _seed_stored_cv(
        candidate_id, filename="cv-stare.pdf", storage_key=old_key, is_primary=False
    )
    new_id = await _seed_stored_cv(
        candidate_id,
        filename="cv-nowe.pdf",
        storage_key=f"cv/new-{unique}.pdf",
        is_primary=True,
    )
    await _set_pointer(candidate_id, filename="cv-nowe.pdf", storage_key=old_key)

    removed = await app_client.delete(
        f"/api/candidates/{candidate_id}/documents/{new_id}",
        headers=app_auth_headers,
    )
    assert removed.status_code == 204, removed.text
    assert await _pointer(candidate_id) == ("cv-stare.pdf", old_key)
    assert await _pointer_copies(candidate_id) == []


async def test_nameless_pointer_with_its_own_key_is_detached_with_the_cv(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Kwarantanna tożsamości czyści we wskaźniku samą nazwę — klucz drugiej
    kopii zostaje i bez odpięcia dalej zasilałby `get_current_cv`."""
    from app.services.cv_source import get_current_cv

    candidate_id = await _candidate(app_client, app_auth_headers)
    unique = uuid.uuid4().hex[:8]
    pointer_key = f"cv/pointer-{unique}.pdf"
    doc_id = await _seed_stored_cv(
        candidate_id,
        filename="CV_Import.pdf",
        storage_key=f"cv/doc-{unique}.pdf",
        is_primary=True,
    )
    await _set_pointer(candidate_id, filename=None, storage_key=pointer_key)

    removed = await app_client.delete(
        f"/api/candidates/{candidate_id}/documents/{doc_id}",
        headers=app_auth_headers,
    )
    assert removed.status_code == 204, removed.text
    assert await _pointer(candidate_id) == (None, None)
    copies = await _pointer_copies(candidate_id)
    assert [copy.storage_key for copy in copies] == [pointer_key]
    assert copies[0].filename == "CV_Import.pdf"
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        assert candidate is not None
        assert await get_current_cv(db, candidate) is None


async def test_pointer_moves_to_the_primary_cv_that_stays(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _candidate(app_client, app_auth_headers)
    unique = uuid.uuid4().hex[:8]
    primary_key = f"cv/primary-{unique}.pdf"
    await _seed_stored_cv(
        candidate_id, filename="cv-glowne.pdf", storage_key=primary_key, is_primary=True
    )
    old_id = await _seed_stored_cv(
        candidate_id,
        filename="cv-stare.pdf",
        storage_key=f"cv/old-{unique}.pdf",
        is_primary=False,
    )
    pointer_key = f"cv/pointer-{unique}.pdf"
    await _set_pointer(candidate_id, filename="cv-stare.pdf", storage_key=pointer_key)

    removed = await app_client.delete(
        f"/api/candidates/{candidate_id}/documents/{old_id}",
        headers=app_auth_headers,
    )
    assert removed.status_code == 204, removed.text
    assert await _pointer(candidate_id) == ("cv-glowne.pdf", primary_key)
    assert [copy.storage_key for copy in await _pointer_copies(candidate_id)] == [
        pointer_key
    ]


async def test_removed_file_can_be_uploaded_again(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _candidate(app_client, app_auth_headers)
    content = _pdf(f"again-{uuid.uuid4().hex}")
    doc_id = await _upload_cv(
        app_client, app_auth_headers, candidate_id, content=content
    )
    removed = await app_client.delete(
        f"/api/candidates/{candidate_id}/documents/{doc_id}",
        headers=app_auth_headers,
    )
    assert removed.status_code == 204, removed.text

    new_id = await _upload_cv(
        app_client, app_auth_headers, candidate_id, content=content
    )
    assert new_id != doc_id
    assert await _listed_ids(app_client, app_auth_headers, candidate_id) == [new_id]


async def test_file_of_another_candidate_is_not_found(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    owner_id = await _candidate(app_client, app_auth_headers)
    stranger_id = await _candidate(app_client, app_auth_headers)
    doc_id = await _upload_cv(app_client, app_auth_headers, owner_id)

    resp = await app_client.delete(
        f"/api/candidates/{stranger_id}/documents/{doc_id}",
        headers=app_auth_headers,
    )
    assert resp.status_code == 404, resp.text
    assert await _listed_ids(app_client, app_auth_headers, owner_id) == [doc_id]
