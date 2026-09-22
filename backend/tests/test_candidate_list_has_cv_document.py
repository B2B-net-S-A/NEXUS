"""Lista kandydatów: `has_cv_document` mówi, czy jest ZAPISANY plik CV.

Import z Traffita wpisuje `cv_filename` od razu, a sam plik dociąga osobna
faza synchronizacji — do tego czasu kolumna „CV" pokazywała przycisk
podglądu, który kończył się komunikatem „Kandydat nie ma zapisanego pliku CV"
(odbiór na produkcji 22.09.2026: 14 z 50 najnowszych kandydatów).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient


async def _seed(tag: str) -> dict[str, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind

    async with AsyncSessionLocal() as db:
        name_only = Candidate(
            name="Tylko", lastname=f"{tag}-nazwa", cv_filename="cv.pdf"
        )
        with_doc = Candidate(name="Plik", lastname=f"{tag}-plik", cv_filename="cv.pdf")
        withdrawn = Candidate(
            name="Wycofany", lastname=f"{tag}-wycofany", cv_filename="cv.pdf"
        )
        other_kind = Candidate(name="Inny", lastname=f"{tag}-inny")
        db.add_all([name_only, with_doc, withdrawn, other_kind])
        await db.flush()
        db.add_all(
            [
                CandidateDocument(
                    candidate_id=with_doc.id,
                    filename="cv.pdf",
                    document_kind=CandidateDocumentKind.cv,
                    is_primary=True,
                ),
                CandidateDocument(
                    candidate_id=withdrawn.id,
                    filename="cv.pdf",
                    document_kind=CandidateDocumentKind.cv,
                    source_deleted_at=datetime.now(timezone.utc),
                ),
                CandidateDocument(
                    candidate_id=other_kind.id,
                    filename="umowa.pdf",
                    document_kind=CandidateDocumentKind.other,
                ),
            ]
        )
        await db.commit()
        return {
            "name_only": name_only.id,
            "with_doc": with_doc.id,
            "withdrawn": withdrawn.id,
            "other_kind": other_kind.id,
        }


@pytest.mark.asyncio
async def test_list_flags_only_candidates_with_a_stored_cv_document(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    tag = f"HasCv{uuid.uuid4().hex[:8]}"
    ids = await _seed(tag)

    response = await app_client.get(
        "/api/candidates",
        params={"q": tag, "page_size": 50},
        headers=app_auth_headers,
    )
    assert response.status_code == 200, response.text
    flags = {item["id"]: item["has_cv_document"] for item in response.json()["items"]}

    assert flags[ids["with_doc"]] is True
    # Sama nazwa pliku (import Traffita przed pobraniem) to jeszcze nie CV.
    assert flags[ids["name_only"]] is False
    # Dokument wycofany u źródła i dokument innego rodzaju się nie liczą.
    assert flags[ids["withdrawn"]] is False
    assert flags[ids["other_kind"]] is False
