"""„Popraw dokument” — trasy na prawdziwej bazie (dane fikcyjne).

Baza testowa jest wspólna i nieczyszczona: każdy test zakłada własny
kontrakt. Model jest podmieniony; kto przechodzi bramki, pilnuje wzorzec
``tests/data/authz_golden/legal_redline.json``.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
import zipfile
from datetime import date

import docx
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.services import storage_service
from app.services.legal_redline import proposals as proposals_module
from app.services.legal_redline.model import ChangeSource, RedlineChange

URL = "/api/legal/redline"


def _docx(*paragraphs: str) -> bytes:
    d = docx.Document()
    for text in paragraphs:
        d.add_paragraph(text)
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


SAMPLE = _docx(
    "§ 1 Przedmiot umowy",
    "Partner świadczy usługi programistyczne przez 30 dni.",
    "Zmiany umowy wymagają formy pisemnej.",
)


async def _contract_with_file(monkeypatch, tmp_path, data: bytes = SAMPLE, filename: str = "Umowa 12-2026.docx"):
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    marker = uuid.uuid4().hex[:8]
    relative = f"contracts/redline-{marker}.docx"
    (tmp_path / "contracts").mkdir(parents=True, exist_ok=True)
    (tmp_path / relative).write_bytes(data)
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name="Redline", lastname=f"Testowy-{marker}")
        client = Client(name=f"Klient Redline {marker}")
        db.add_all([candidate, client])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=date(2026, 1, 1),
        )
        db.add(contract)
        await db.flush()
        doc = ContractDocument(
            contract_id=contract.id,
            filename=filename,
            file_path=relative,
            doc_type=ContractDocumentType.contract,
            size_bytes=len(data),
        )
        db.add(doc)
        await db.commit()
        return contract.id, doc.id


async def test_contract_document_diff_and_render(app_client: AsyncClient, app_auth_headers, monkeypatch, tmp_path):
    cid, doc_id = await _contract_with_file(monkeypatch, tmp_path)
    new_text = "\n".join(
        [
            "§ 1 Przedmiot umowy",
            "Partner świadczy usługi programistyczne przez 14 dni.",
            "Zmiany umowy wymagają formy pisemnej.",
        ]
    )
    resp = await app_client.post(
        URL,
        data={"contract_id": str(cid), "document_id": str(doc_id), "new_text": new_text},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ai"]["status"] == "diff"
    assert body["source"]["sha256"] == hashlib.sha256(SAMPLE).hexdigest()
    assert [p["text"] for p in body["paragraphs"]][1] == "Partner świadczy usługi programistyczne przez 30 dni."
    assert [(c["find"], c["new_text"]) for c in body["changes"]] == [("30", "14")]

    rendered = await app_client.post(
        f"{URL}/render",
        data={
            "contract_id": str(cid),
            "document_id": str(doc_id),
            "sha256": body["source"]["sha256"],
            "changes": json.dumps(body["changes"]),
        },
        headers=app_auth_headers,
    )
    assert rendered.status_code == 200, rendered.text
    assert "poprawki%20asystenta.docx" in rendered.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(rendered.content)) as z:
        xml = z.read("word/document.xml").decode()
    assert "Asystent NEXUS" in xml and "<w:delText" in xml
    docx.Document(io.BytesIO(rendered.content))


async def test_uploaded_file_needs_a_contract_or_registry_row(app_client: AsyncClient, app_auth_headers):
    resp = await app_client.post(
        URL,
        files={"file": ("umowa.docx", SAMPLE, "application/octet-stream")},
        data={"use_ai": "false"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422
    assert "kontrakt" in resp.json()["detail"]


async def test_uploaded_file_in_contract_context_manual_mode(app_client: AsyncClient, app_auth_headers, monkeypatch, tmp_path):
    cid, _ = await _contract_with_file(monkeypatch, tmp_path)
    resp = await app_client.post(
        URL,
        files={"file": ("Umowa klienta.docx", SAMPLE, "application/octet-stream")},
        data={"contract_id": str(cid), "use_ai": "false"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ai"]["status"] == "manual"
    assert resp.json()["changes"] == []


async def test_pdf_is_refused_with_polish_message(app_client: AsyncClient, app_auth_headers, monkeypatch, tmp_path):
    cid, doc_id = await _contract_with_file(monkeypatch, tmp_path, filename="Umowa 12-2026.pdf")
    resp = await app_client.post(
        URL, data={"contract_id": str(cid), "document_id": str(doc_id)}, headers=app_auth_headers
    )
    assert resp.status_code == 422
    assert "DOCX" in resp.json()["detail"]


async def test_model_proposals_are_passed_through_with_entities(app_client: AsyncClient, app_auth_headers, monkeypatch, tmp_path):
    cid, doc_id = await _contract_with_file(monkeypatch, tmp_path)
    seen = {}

    async def fake_propose(_db, *, paragraphs, instruction, entities, user_id, extra_passages=None):
        seen["entities"] = {e.tag: e.value for e in entities}
        seen["instruction"] = instruction
        return proposals_module.Proposal(
            status="ok",
            changes=[
                RedlineChange(
                    id="a1",
                    kind="replace",
                    paragraph=1,
                    find="30 dni",
                    start=paragraphs[1].text.index("30 dni"),
                    end=paragraphs[1].text.index("30 dni") + 6,
                    new_text="14 dni",
                    reason="Krótszy termin.",
                    sources=(ChangeSource(ref="kc", label="art. 1 KC", quote="brak", state="mismatch"),),
                )
            ],
            notes=["§ 2 bez zmian."],
            model="claude-sonnet-5-5",
        )

    monkeypatch.setattr(proposals_module, "propose", fake_propose)
    resp = await app_client.post(
        URL,
        data={"contract_id": str(cid), "document_id": str(doc_id), "instruction": "Skróć termin"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert seen["entities"]["PARTNER"].startswith("Redline Testowy-")
    assert seen["entities"]["KLIENT"].startswith("Klient Redline")
    assert body["changes"][0]["blocked"] is True
    assert body["notes"] == ["§ 2 bez zmian."]

    # Zablokowana zmiana nie przechodzi do pliku.
    rendered = await app_client.post(
        f"{URL}/render",
        data={"contract_id": str(cid), "document_id": str(doc_id), "changes": json.dumps(body["changes"])},
        headers=app_auth_headers,
    )
    assert rendered.status_code == 422
    assert "bez pokrycia" in rendered.json()["detail"]


async def test_forged_document_quote_is_rechecked(app_client: AsyncClient, app_auth_headers, monkeypatch, tmp_path):
    cid, doc_id = await _contract_with_file(monkeypatch, tmp_path)
    change = {
        "id": "x",
        "kind": "replace",
        "paragraph": 2,
        "find": "pisemnej",
        "new_text": "dokumentowej",
        "sources": [{"ref": "dokument", "label": "Dokument", "quote": "zdanie, którego nie ma", "state": "ok"}],
    }
    rendered = await app_client.post(
        f"{URL}/render",
        data={"contract_id": str(cid), "document_id": str(doc_id), "changes": json.dumps([change])},
        headers=app_auth_headers,
    )
    assert rendered.status_code == 422


async def test_changed_file_and_conflicting_anchor(app_client: AsyncClient, app_auth_headers, monkeypatch, tmp_path):
    cid, doc_id = await _contract_with_file(monkeypatch, tmp_path)
    stale = await app_client.post(
        f"{URL}/render",
        data={"contract_id": str(cid), "document_id": str(doc_id), "sha256": "0" * 64, "changes": "[]"},
        headers=app_auth_headers,
    )
    assert stale.status_code == 409
    conflict = await app_client.post(
        f"{URL}/render",
        data={
            "contract_id": str(cid),
            "document_id": str(doc_id),
            "changes": json.dumps([{"id": "c7", "kind": "replace", "paragraph": 1, "find": "nie ma", "new_text": "x"}]),
        },
        headers=app_auth_headers,
    )
    assert conflict.status_code == 422
    assert conflict.json()["detail"]["change_id"] == "c7"
