"""Wzory własne Generatora Umów B2B — API z bazą: zapis, bramki, zatwierdzanie,
dokument ze wzoru (bez skutków w kontraktach) i wersje.

Model jest wyłączony (``draft.model_available`` → ``False``): ścieżka „wgraj
Word / wzór bazowy → pola → zapis” musi działać bez niego. Baza wspólna
i nieczyszczona — asercje wyłącznie na własnych wierszach.
"""

from __future__ import annotations

import io
import uuid

import docx
import pytest

from app.core.database import AsyncSessionLocal
from tests.test_b2b_generator_rate_visibility import _seed_user

BASE = "/api/b2b-generator"
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture(autouse=True)
def _no_model(monkeypatch):
    from app.services.custom_templates import draft

    monkeypatch.setattr(draft, "model_available", lambda: False)


def _word(*lines: str) -> bytes:
    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _text(data: bytes) -> str:
    return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)


WORD = _word(
    "UMOWA O POPROWADZENIE SZKOLENIA",
    "zawarta w dniu ____________ pomiędzy B2B.net S.A., a Panem/ią ______________ "
    "prowadzącym/cą działalność gospodarczą pod firmą: ________, NIP: __________.",
    "Wynagrodzenie wynosi kwotę ______ zł netto (słownie: ____________).",
    "Klauzula informacyjna RODO: administratorem danych osobowych jest spółka.",
)


async def _upload(app_client, headers, data: bytes = WORD, name: str = "") -> dict:
    resp = await app_client.post(
        f"{BASE}/custom-templates",
        headers=headers,
        data={
            "origin": "upload",
            "name": name or f"Wzór testowy {uuid.uuid4().hex[:6]}",
        },
        files={"file": ("wzor.docx", data, DOCX_MEDIA)},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _values(detail: dict) -> dict:
    fields = (
        detail["working"]["fields"]
        if detail.get("working")
        else detail["active"]["fields"]
    )
    keys = {f["key"]: f for f in fields}
    out = {}
    for key, f in keys.items():
        if f["kind"] == "money":
            out[key] = "4200"
        elif f["kind"] == "date":
            out[key] = "2026-12-01"
        elif f["kind"] == "gender":
            out[key] = "k"
        else:
            out[key] = f"Wartość {f['label']}"
    out["partner.name_instrumental"] = "Anną Testową"
    return out


async def _approved(app_client, author, admin) -> dict:
    detail = await _upload(app_client, author)
    tid = detail["id"]
    resp = await app_client.post(
        f"{BASE}/custom-templates/{tid}/submit", headers=author
    )
    assert resp.status_code == 200, resp.text
    resp = await app_client.post(
        f"{BASE}/custom-templates/{tid}/approve", headers=admin, json={}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_upload_detects_fields_and_draft_is_private(app_client, app_auth_headers):
    author, _ = await _seed_user(app_client, "recruiter")
    other, _ = await _seed_user(app_client, "recruiter")
    detail = await _upload(app_client, author)
    keys = {f["key"] for f in detail["working"]["fields"]}
    assert {
        "partner.nip",
        "partner.legal_name",
        "document_date",
        "partner.gender",
    } <= keys
    assert detail["working"]["status"] == "draft"
    assert detail["working"]["problems"] == []
    assert detail["can_edit"] is True

    # Cudzy szkic: nie widać go ani na liście, ani w szczegółach.
    resp = await app_client.get(
        f"{BASE}/custom-templates/{detail['id']}", headers=other
    )
    assert resp.status_code == 404
    listed = (await app_client.get(f"{BASE}/custom-templates", headers=other)).json()
    assert detail["id"] not in {t["id"] for t in listed["templates"]}
    resp = await app_client.post(
        f"{BASE}/custom-templates/{detail['id']}/submit", headers=other
    )
    assert resp.status_code in (403, 404)
    # Administrator widzi szkic.
    resp = await app_client.get(
        f"{BASE}/custom-templates/{detail['id']}", headers=app_auth_headers
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_template_escaping_fields_cannot_be_submitted(app_client):
    author, _ = await _seed_user(app_client, "recruiter")
    detail = await _upload(
        app_client, author, _word("Strona {{ partner.nip }} i {{ ''.__class__ }}.")
    )
    assert detail["working"]["problems"]
    resp = await app_client.post(
        f"{BASE}/custom-templates/{detail['id']}/submit", headers=author
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "template_not_ready"


@pytest.mark.asyncio
async def test_only_admin_approves_and_returns(app_client, app_auth_headers):
    author, _ = await _seed_user(app_client, "recruiter")
    hor, _ = await _seed_user(app_client, "head_of_recruitment")
    detail = await _upload(app_client, author)
    tid = detail["id"]
    resp = await app_client.post(
        f"{BASE}/custom-templates/{tid}/submit", headers=author
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["working"]["status"] == "pending"
    # Zgłoszonego wzoru autor już nie zmienia.
    resp = await app_client.patch(
        f"{BASE}/custom-templates/{tid}", headers=author, json={"name": "X"}
    )
    assert resp.status_code == 409
    for who in (author, hor):
        resp = await app_client.post(
            f"{BASE}/custom-templates/{tid}/approve", headers=who, json={}
        )
        assert resp.status_code == 403
    resp = await app_client.post(
        f"{BASE}/custom-templates/{tid}/return",
        headers=app_auth_headers,
        json={"reason": "Dodaj limit kosztów dojazdu."},
    )
    assert resp.status_code == 200, resp.text
    working = resp.json()["working"]
    assert working["status"] == "draft"
    assert working["review_note"] == "Dodaj limit kosztów dojazdu."


@pytest.mark.asyncio
async def test_copyright_transfer_requires_written_signature(app_client):
    author, _ = await _seed_user(app_client, "recruiter")
    detail = await _upload(
        app_client,
        author,
        _word("Partner {{ partner.nip }} przenosi autorskie prawa majątkowe. RODO."),
    )
    tid = detail["id"]
    resp = await app_client.post(
        f"{BASE}/custom-templates/{tid}/submit", headers=author
    )
    assert resp.status_code == 422
    resp = await app_client.patch(
        f"{BASE}/custom-templates/{tid}",
        headers=author,
        json={"signature_form": "written"},
    )
    assert resp.status_code == 200
    resp = await app_client.post(
        f"{BASE}/custom-templates/{tid}/submit", headers=author
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_issued_document_lands_in_register_without_contract_effects(
    app_client, app_auth_headers
):
    from app.models.b2b_contract_document import B2BContractDocument
    from app.models.contract import Contract

    author, _ = await _seed_user(app_client, "recruiter")
    approved = await _approved(app_client, author, app_auth_headers)
    tid = approved["id"]
    assert approved["active"]["status"] == "approved"

    types = (await app_client.get(f"{BASE}/document-types", headers=author)).json()
    offered = {t["key"]: t for t in types["custom_types"]}
    assert f"custom:{tid}" in offered

    values = _values(approved)
    resp = await app_client.post(
        f"{BASE}/custom-templates/{tid}/documents", headers=author, json={"values": {}}
    )
    assert resp.status_code == 422  # wymagane pola
    resp = await app_client.post(
        f"{BASE}/custom-templates/{tid}/documents",
        headers=author,
        json={"values": values},
    )
    assert resp.status_code == 200, resp.text
    text = _text(resp.content)
    assert "Panią Anną Testową prowadzącą" in text
    assert "4 200,00 zł netto (słownie: cztery tysiące dwieście złotych 00/100)" in text
    doc_id = int(resp.headers["X-Document-Id"])

    listed = (
        await app_client.get(
            f"{BASE}/documents", headers=author, params={"family": ["custom"]}
        )
    ).json()
    row = next(r for r in listed if r["id"] == doc_id)
    assert row["family"] == "custom"
    assert row["type_label"] == approved["active"]["name"]
    assert row["can_edit"] is False

    async with AsyncSessionLocal() as db:
        contracts_before = await db.scalar(
            __import__("sqlalchemy").select(
                __import__("sqlalchemy").func.count(Contract.id)
            )
        )
    resp = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers, json={}
    )
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        doc = await db.get(B2BContractDocument, doc_id)
        assert doc.status == "signed"
        assert doc.effect_summary["no_contract_effects"] is True
        assert doc.contract_id is None
        contracts_after = await db.scalar(
            __import__("sqlalchemy").select(
                __import__("sqlalchemy").func.count(Contract.id)
            )
        )
    assert contracts_after == contracts_before


@pytest.mark.asyncio
async def test_issued_document_stays_on_its_version(app_client, app_auth_headers):
    author, _ = await _seed_user(app_client, "recruiter")
    approved = await _approved(app_client, author, app_auth_headers)
    tid = approved["id"]
    values = _values(approved)
    resp = await app_client.post(
        f"{BASE}/custom-templates/{tid}/documents",
        headers=author,
        json={"values": values},
    )
    assert resp.status_code == 200, resp.text
    doc_id = int(resp.headers["X-Document-Id"])

    resp = await app_client.post(
        f"{BASE}/custom-templates/{tid}/new-version", headers=author
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["working"]["version_no"] == 2
    resp = await app_client.post(
        f"{BASE}/custom-templates/{tid}/upload",
        headers=author,
        files={
            "file": (
                "v2.docx",
                _word(
                    "UMOWA V2 — SZKOLENIE STACJONARNE",
                    "zawarta w dniu ____________, NIP: __________. RODO.",
                ),
                DOCX_MEDIA,
            )
        },
    )
    assert resp.status_code == 200, resp.text
    await app_client.post(f"{BASE}/custom-templates/{tid}/submit", headers=author)
    resp = await app_client.post(
        f"{BASE}/custom-templates/{tid}/approve", headers=app_auth_headers, json={}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["active"]["version_no"] == 2

    resp = await app_client.post(
        f"{BASE}/documents/{doc_id}/docx", headers=author, json={"values": {}}
    )
    assert resp.status_code == 200, resp.text
    text = _text(resp.content)
    assert "UMOWA O POPROWADZENIE SZKOLENIA" in text
    assert "V2" not in text


@pytest.mark.asyncio
async def test_withdrawn_template_is_not_offered_and_selected_clients_are_enforced(
    app_client, app_auth_headers
):
    from app.models.client import Client

    author, _ = await _seed_user(app_client, "recruiter")
    async with AsyncSessionLocal() as db:
        allowed = Client(name=f"Klient-wzor-{uuid.uuid4().hex[:6]}")
        other = Client(name=f"Klient-inny-{uuid.uuid4().hex[:6]}")
        db.add_all([allowed, other])
        await db.commit()
        allowed_id, other_id = allowed.id, other.id
    detail = await _upload(app_client, author)
    tid = detail["id"]
    resp = await app_client.patch(
        f"{BASE}/custom-templates/{tid}",
        headers=author,
        json={"client_scope": "selected", "client_ids": [allowed_id]},
    )
    assert resp.status_code == 200, resp.text
    await app_client.post(f"{BASE}/custom-templates/{tid}/submit", headers=author)
    approved = (
        await app_client.post(
            f"{BASE}/custom-templates/{tid}/approve", headers=app_auth_headers, json={}
        )
    ).json()
    values = _values(approved)
    for client_id, status in ((None, 422), (other_id, 422), (allowed_id, 200)):
        resp = await app_client.post(
            f"{BASE}/custom-templates/{tid}/documents",
            headers=author,
            json={"values": values, "client_id": client_id},
        )
        assert resp.status_code == status, (client_id, resp.text)

    resp = await app_client.post(
        f"{BASE}/custom-templates/{tid}/withdraw",
        headers=author,
        json={"reason": "stary"},
    )
    assert resp.status_code == 403
    resp = await app_client.post(
        f"{BASE}/custom-templates/{tid}/withdraw",
        headers=app_auth_headers,
        json={"reason": "nieaktualny wzór"},
    )
    assert resp.status_code == 200, resp.text
    types = (await app_client.get(f"{BASE}/document-types", headers=author)).json()
    assert f"custom:{tid}" not in {t["key"] for t in types["custom_types"]}
    resp = await app_client.post(
        f"{BASE}/custom-templates/{tid}/documents",
        headers=author,
        json={"values": values, "client_id": allowed_id},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_sample_and_base_template_without_model(app_client):
    author, _ = await _seed_user(app_client, "recruiter")
    resp = await app_client.post(
        f"{BASE}/custom-templates",
        headers=author,
        data={
            "origin": "base",
            "base_key": "training_agreement",
            "instruction": "Szkolenie stacjonarne u klienta.",
        },
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail["message"]  # bez modelu szkic zostaje bez zmian
    keys = {f["key"] for f in detail["working"]["fields"]}
    assert {"partner.nip", "fees.total", "agenda"} <= keys
    resp = await app_client.post(
        f"{BASE}/custom-templates/{detail['id']}/sample", headers=author
    )
    assert resp.status_code == 200, resp.text
    assert "{{" not in _text(resp.content)
    resp = await app_client.post(
        f"{BASE}/custom-templates",
        headers=author,
        data={"origin": "brief", "instruction": "Umowa o szkolenie."},
    )
    assert resp.status_code == 503
