"""Wypowiedzenie/porozumienie w Dokumentach a „umowa B2B nie jest rozwiązana”.

Kontrakt #605 (22.11.2026): wypowiedzenie zaimportowane z SharePointa leżało
w Dokumentach, a strona mówiła „nierozwiązana”, bo przypomnienie czyta tylko
``agreement_termination_*``. API wskazuje teraz dokument
(``termination_document``), ale pól rozwiązania z niego NIE wypełnia —
ostatni dzień umowy wpisuje człowiek. Każdy test seeduje własne wiersze.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.contract_document import ContractDocument, ContractDocumentType

PATH = "/api/contracts"


async def _seed(
    *,
    contract_type: ContractType = ContractType.b2b,
    recorded: bool = False,
    docs: tuple[tuple[ContractDocumentType, str, int], ...] = (),
) -> tuple[int, dict]:
    """Zakończony kontrakt + dokumenty ``(typ, nazwa, dni temu)``; ``ids`` ma też nazwisko."""
    today = business_today()
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Wypowiedzenie",
            lastname=f"WAktach-{uuid.uuid4().hex[:6]}",
            email=f"wakt-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"KlientAkta-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.ended,
            contract_type=contract_type,
            start_date=today - timedelta(days=300),
            end_date=today - timedelta(days=20),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
        )
        if recorded:
            contract.agreement_termination_mode = "notice"
            contract.agreement_termination_party = "consultant"
            contract.agreement_termination_signed_on = today - timedelta(days=60)
            contract.agreement_last_day = today - timedelta(days=20)
        db.add(contract)
        await db.flush()
        ids: dict = {"_lastname": cand.lastname}
        now = datetime.now(timezone.utc)
        for doc_type, name, days_ago in docs:
            doc = ContractDocument(
                contract_id=contract.id,
                filename=name,
                file_path=f"contracts/{contract.id}/{uuid.uuid4().hex}.pdf",
                content_type="application/pdf",
                doc_type=doc_type,
                source="sharepoint_import",
                created_at=now - timedelta(days=days_ago),
            )
            db.add(doc)
            await db.flush()
            ids[name] = doc.id
        await db.commit()
        return contract.id, ids


async def test_detail_points_to_newest_termination_document_without_recording(
    app_client, app_auth_headers
):
    cid, ids = await _seed(
        docs=(
            (ContractDocumentType.termination_notice, "wypowiedzenie-stare.pdf", 60),
            (ContractDocumentType.termination_notice, "wypowiedzenie.pdf", 30),
            (ContractDocumentType.other, "inne.pdf", 1),
        )
    )
    resp = await app_client.get(f"{PATH}/{cid}", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    doc = body["termination_document"]
    assert doc["id"] == ids["wypowiedzenie.pdf"]
    assert doc["doc_type"] == "termination_notice"
    assert doc["filename"] == "wypowiedzenie.pdf"
    assert doc["source"] == "sharepoint_import"
    # Dokument niczego nie zapisuje — rozwiązanie wpisuje człowiek.
    assert body["agreement_termination_mode"] is None
    assert body["agreement_last_day"] is None


async def test_detail_without_termination_document_is_null(
    app_client, app_auth_headers
):
    cid, _ = await _seed(docs=((ContractDocumentType.other, "inne.pdf", 1),))
    resp = await app_client.get(f"{PATH}/{cid}", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["termination_document"] is None


async def test_recorded_or_non_b2b_contract_gets_no_hint(app_client, app_auth_headers):
    docs = ((ContractDocumentType.termination_agreement, "porozumienie.pdf", 5),)
    recorded, _ = await _seed(recorded=True, docs=docs)
    zlecenie, _ = await _seed(contract_type=ContractType.uzlecenie, docs=docs)
    for cid in (recorded, zlecenie):
        resp = await app_client.get(f"{PATH}/{cid}", headers=app_auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["termination_document"] is None


async def test_not_terminated_list_carries_document_on_row_and_member(
    app_client, app_auth_headers
):
    cid, ids = await _seed(
        docs=((ContractDocumentType.termination_agreement, "porozumienie.pdf", 3),)
    )
    for grouped in ("false", "true"):
        resp = await app_client.get(
            PATH,
            params={
                "agreement_not_terminated": "true",
                "status": "ended",
                "group_by_candidate": grouped,
                "page_size": 100,
                "q": ids["_lastname"],
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        row = next(
            i
            for i in items
            if i["id"] == cid
            or any(m["id"] == cid for m in i.get("group_members") or [])
        )
        if grouped == "true":
            member = next(m for m in row["group_members"] if m["id"] == cid)
            assert member["termination_document"]["id"] == ids["porozumienie.pdf"]
        else:
            assert row["termination_document"]["doc_type"] == "termination_agreement"
