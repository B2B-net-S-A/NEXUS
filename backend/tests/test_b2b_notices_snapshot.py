"""Adres doręczeń w wydanej umowie, jej podglądzie i odtworzonym DOCX."""

from io import BytesIO
from uuid import uuid4

import pytest
from docx import Document

from app.services.b2b_contract_generator.notices import NOTICES_SNAPSHOT_FIELD
from app.core.database import AsyncSessionLocal
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.services.b2b_contract_generator.seeder import ensure_b2b_seed_data


def _text(response):
    assert response.status_code == 200, response.text[:300]
    return "\n".join(p.text for p in Document(BytesIO(response.content)).paragraphs)


@pytest.mark.parametrize("lang", ["pl", "en"])
@pytest.mark.parametrize("legacy", [False, True])
async def test_issue_preview_correct_and_redownload_keep_notices(
    app_client, app_auth_headers, lang, legacy
):
    async with AsyncSessionLocal() as db:
        await ensure_b2b_seed_data(db)

    render = "/api/b2b-generator/render"
    current = "wsparcie@b2bnetwork.pl"
    old = "administracja@b2bnetwork.pl"
    data = {
        "contract_number": f"{300000 + uuid4().int % 500000}/2026",
        "partner_name": "Partner Testowy",
        "partner_email": current,
        "client_name": "Klient Testowy",
        "language": lang,
        "signing_date": "2026-05-15",
        # Wartości przysłane przez formularz nie ustalają adresu spółki.
        "b2b_notices_email": "spoof@example.org",
        NOTICES_SNAPSHOT_FIELD: "spoof@example.org",
    }
    issued = await app_client.post(render, headers=app_auth_headers, json=data)
    assert f"B2BNET: {current}" in _text(issued)
    row_id = int(issued.headers["X-Generated-Contract-Id"])
    item = f"/api/b2b-generator/generated/{row_id}"

    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, row_id)
        saved = dict(row.render_payload)
        assert saved[NOTICES_SNAPSHOT_FIELD] == current
        if legacy:
            del saved[NOTICES_SNAPSHOT_FIELD]
            row.render_payload = saved
            await db.commit()

    expected = old if legacy else current
    download = await app_client.get(f"{item}/docx", headers=app_auth_headers)
    assert f"B2BNET: {expected}" in _text(download)
    preview = await app_client.post(
        render,
        params={"format": "html", "preview_generated_id": row_id},
        headers=app_auth_headers,
        json=data,
    )
    assert preview.status_code == 200, preview.text
    assert f"B2BNET: {expected}" in preview.json()["html"]
    other = await app_client.post(
        render,
        params={"format": "html", "preview_generated_id": row_id},
        headers=app_auth_headers,
        json={**data, "contract_number": "1/2000"},
    )
    assert other.status_code == 422
    corrected = await app_client.post(
        f"{item}/rerender", headers=app_auth_headers, json=data
    )
    content = _text(corrected)
    assert f"B2BNET: {expected}" in content
    partner_label = "Dla Partnera" if lang == "pl" else "For the Partner"
    assert f"{partner_label}: {current}" in content
    assert "rozliczenia@b2bnetwork.pl" in content
    assert "spoof@example.org" not in content
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, row_id)
        assert row.render_payload[NOTICES_SNAPSHOT_FIELD] == expected


@pytest.mark.parametrize("evidence", ["new_issue", "old_issue", "no_issue_record"])
async def test_contract_download_and_draft_use_first_issue_contact(
    app_client, app_auth_headers, evidence
):
    from sqlalchemy import select

    from app.models.activity import Activity
    from app.models.contract_template import ContractTemplate
    from tests.test_b2b_generated_contract_status import _admin_user_id
    from tests.test_b2b_generator_rate_visibility import _seed_documents

    admin = await _admin_user_id(app_client)
    docs = await _seed_documents(author_id=admin, job_recruiter_id=admin)
    contract_id = docs["contract_id"]
    current = "wsparcie@b2bnetwork.pl"
    expected = current if evidence == "new_issue" else "administracja@b2bnetwork.pl"
    async with AsyncSessionLocal() as db:
        await ensure_b2b_seed_data(db)
        first_issue = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "contract",
                Activity.entity_id == contract_id,
                Activity.action == "b2b_generated",
            )
        )
        if evidence == "new_issue":
            first_issue.details = {NOTICES_SNAPSHOT_FIELD: current}
        elif evidence == "no_issue_record":
            await db.delete(first_issue)
        template_id = await db.scalar(
            select(ContractTemplate.id).where(
                ContractTemplate.contract_type == "b2b",
                ContractTemplate.language == "pl",
            )
        )
        await db.commit()

    docx = await app_client.get(
        f"/api/b2b-generator/contracts/{contract_id}/docx", headers=app_auth_headers
    )
    assert f"B2BNET: {expected}" in _text(docx)
    path = f"/api/contracts/{contract_id}/draft"
    draft = await app_client.patch(
        path, headers=app_auth_headers, json={"template_id": template_id}
    )
    assert draft.status_code == 200, draft.text
    assert f"B2BNET: {expected}" in draft.json()["content_html"]

    manual_html = "<p>Kopia dla wsparcie@b2bnetwork.pl</p>"
    edited = await app_client.patch(
        path, headers=app_auth_headers, json={"content_html": manual_html}
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["content_html"] == manual_html
