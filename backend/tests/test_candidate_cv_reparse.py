"""`POST /api/candidates/{id}/cv/reparse` — ponowny odczyt głównego CV (UAT B12).

Odczyt CV po wgraniu idzie w tle i kończy się po cichu przy pustym tekście,
błędzie parsera albo imporcie bez parsowania. Profil pokazywał wtedy „dane z CV
nie są jeszcze w profilu” bez następnego kroku. Endpoint kolejkuje TĘ SAMĄ
ścieżkę co wgranie pliku — z bramką tożsamości i kwotą AI.

Uses the in-process ``app_client`` / ``app_auth_headers`` fixtures (real
postgres in CI).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


async def _seed(with_primary_cv: bool) -> tuple[int, int | None]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind

    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Cv",
            lastname=f"Reparse-{uuid.uuid4().hex[:6]}",
            email=f"cv-reparse-{uuid.uuid4().hex[:8]}@example.com",
            cv_filename="cv.pdf" if with_primary_cv else None,
        )
        db.add(candidate)
        await db.flush()
        document_id = None
        if with_primary_cv:
            document = CandidateDocument(
                candidate_id=candidate.id,
                filename="cv.pdf",
                document_kind=CandidateDocumentKind.cv,
                is_primary=True,
                content_sha256="a" * 64,
            )
            db.add(document)
            await db.flush()
            document_id = document.id
        await db.commit()
        return candidate.id, document_id


async def test_reparse_queues_the_upload_enrichment_for_the_primary_cv(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id, document_id = await _seed(with_primary_cv=True)
    task = AsyncMock()
    with patch("app.api.candidates._enrich_candidate_from_document_task", task):
        response = await app_client.post(
            f"/api/candidates/{candidate_id}/cv/reparse", headers=app_auth_headers
        )

    assert response.status_code == 202, response.text
    assert response.json() == {"status": "queued", "document_id": document_id}
    task.assert_awaited_once()
    assert task.await_args.args == (candidate_id, document_id, "a" * 64)
    # AI-07: odczyt CV liczy się na osobę, która go zleciła, nie na „system”.
    assert task.await_args.kwargs["actor_user_id"] is not None


async def test_reparse_without_primary_cv_says_so(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id, _ = await _seed(with_primary_cv=False)
    response = await app_client.post(
        f"/api/candidates/{candidate_id}/cv/reparse", headers=app_auth_headers
    )
    assert response.status_code == 404
    assert "głównego pliku CV" in response.json()["detail"]
