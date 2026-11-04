"""Ticket 10 — raport kontraktów bez podpiętego zamówienia (XLSX).

„Podpięte zamówienie" = to, co widać w zakładce „Dokumenty" kontraktu:
dokument typu „Zamówienie" albo zamówienie kontraktu z wgranym PDF-em.
Baza testowa jest wspólna, więc asercje dotyczą WYŁĄCZNIE własnych kontraktów.
"""

from __future__ import annotations

import io
import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook

pytestmark = pytest.mark.asyncio

URL = "/api/contracts/missing-orders-report"


async def _seed() -> dict[str, int]:
    """Po jednym kontrakcie na każdy przypadek reguły. Zwraca {nazwa: id}."""

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import ClientOrderGroup
    from app.models.contract import Contract, ContractStatus, ContractType
    from app.models.contract_document import ContractDocument, ContractDocumentType

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient Zamówień {unique}")
        db.add(client)
        await db.flush()

        async def contract(
            key: str, status: ContractStatus = ContractStatus.active
        ) -> Contract:
            candidate = Candidate(
                # Nazwisko zaczynające się od „=" — raport musi je zneutralizować.
                name="Jan" if key != "formula" else "=HYPERLINK(1)",
                lastname=f"Zam{key}{unique}",
            )
            db.add(candidate)
            await db.flush()
            row = Contract(
                candidate_id=candidate.id,
                client_id=client.id,
                contract_type=ContractType.b2b,
                status=status,
                start_date=date(2026, 1, 1),
            )
            db.add(row)
            await db.flush()
            return row

        def order(row: Contract, **kw) -> ClientOrder:
            item = ClientOrder(
                client_id=client.id,
                contract_id=row.id,
                title=kw.pop("title", f"ZAM-{row.id}"),
                status=kw.pop("status", ClientOrderStatus.active),
                **kw,
            )
            db.add(item)
            return item

        ids: dict[str, int] = {}

        with_doc = await contract("doc")
        db.add(
            ContractDocument(
                contract_id=with_doc.id,
                filename="zamowienie.pdf",
                file_path=f"contracts/{with_doc.id}/zamowienie.pdf",
                doc_type=ContractDocumentType.order,
            )
        )
        ids["with_order_document"] = with_doc.id

        with_pdf = await contract("pdf")
        order(with_pdf, file_path=f"orders/{with_pdf.id}.pdf", filename="po.pdf")
        ids["with_order_pdf"] = with_pdf.id

        without_pdf = await contract("nopdf")
        order(without_pdf, title=f"PO-{unique}")
        order(
            without_pdf,
            title=f"ANUL-{unique}",
            status=ClientOrderStatus.cancelled,
        )
        ids["order_without_pdf"] = without_pdf.id

        other_doc = await contract("other", status=ContractStatus.ending)
        db.add(
            ContractDocument(
                contract_id=other_doc.id,
                filename="umowa.pdf",
                file_path=f"contracts/{other_doc.id}/umowa.pdf",
                doc_type=ContractDocumentType.contract,
            )
        )
        ids["only_contract_document"] = other_doc.id

        voided = await contract("void", status=ContractStatus.void)
        ids["void"] = voided.id

        group_line = await contract("group")
        group = ClientOrderGroup(
            client_id=client.id,
            order_number=f"GRP-{unique}",
            start_date=date(2026, 1, 1),
            file_path=f"order-groups/{unique}.pdf",
        )
        db.add(group)
        await db.flush()
        order(group_line, order_group_id=group.id)
        ids["group_pdf_without_copy"] = group_line.id

        formula = await contract("formula")
        ids["formula"] = formula.id

        possible = await contract("possible")
        for filename in ("Zamówienie 4500123456.pdf", "dowod.pdf"):
            db.add(
                ContractDocument(
                    contract_id=possible.id,
                    filename=filename,
                    file_path=f"contracts/{possible.id}/{filename}",
                    doc_type=ContractDocumentType.other,
                )
            )
        ids["possible_order_file"] = possible.id

        await db.commit()
    return ids


def _rows(content: bytes) -> dict[int, tuple]:
    book = load_workbook(io.BytesIO(content))
    assert book.sheetnames == ["Bez zamówienia", "Podsumowanie"]
    return {
        row[0]: row
        for row in book["Bez zamówienia"].iter_rows(min_row=2, values_only=True)
    }


async def test_report_lists_contracts_without_an_order_in_the_documents_tab(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    ids = await _seed()

    response = await app_client.get(URL, headers=app_auth_headers)

    assert response.status_code == 200, response.text
    assert "kontrakty-bez-zamowienia_" in response.headers["content-disposition"]
    rows = _rows(response.content)

    assert ids["with_order_document"] not in rows, "dokument „Zamówienie” liczy się"
    assert ids["with_order_pdf"] not in rows, "PDF na zamówieniu liczy się"
    assert ids["void"] not in rows, "anulowanej umowy nikt nie uzupełnia"

    no_pdf = rows[ids["order_without_pdf"]]
    assert no_pdf[1].endswith(f"/contracts/{ids['order_without_pdf']}")
    assert no_pdf[7] == "Aktywny"
    assert no_pdf[10] == 1, "anulowane zamówienie się nie liczy"
    assert no_pdf[11].startswith("PO-")
    assert not no_pdf[12]
    assert not no_pdf[13], "bez uwagi"

    other = rows[ids["only_contract_document"]]
    assert other[7] == "Kończący się"
    assert other[10] == 0
    assert other[11] == "—"

    group = rows[ids["group_pdf_without_copy"]]
    assert group[11].startswith("GRP-"), "numer z zamówienia MD/kosztowego"
    assert not group[12]
    assert "nie ma kopii" in group[13]

    possible = rows[ids["possible_order_file"]]
    assert possible[12] == "Zamówienie 4500123456.pdf", "„dowod.pdf” nie pasuje"
    assert "zmień jego typ" in possible[13]

    formula = rows[ids["formula"]]
    assert not str(formula[2]).startswith("="), "formuła zneutralizowana"


async def test_summary_counts_contracts_with_and_without_orders(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    await _seed()

    response = await app_client.get(URL, headers=app_auth_headers)

    book = load_workbook(io.BytesIO(response.content))
    summary = {
        row[0]: row[1]
        for row in book["Podsumowanie"].iter_rows(min_row=2, values_only=True)
        if row and row[0]
    }
    missing = book["Bez zamówienia"].max_row - 1
    total = summary["Kontrakty (bez anulowanych)"]
    assert summary["Bez zamówienia (arkusz „Bez zamówienia”)"] == missing
    assert summary["Z podpiętym zamówieniem"] == total - missing


async def test_finance_can_download_and_recruiter_cannot(app_client: AsyncClient):
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.models.user import User, UserRole

    async def headers(role: str) -> dict[str, str]:
        marker = uuid.uuid4().hex[:10]
        async with AsyncSessionLocal() as db:
            user = User(
                email=f"missing-orders-{marker}@example.com",
                name=f"Raport {marker}",
                role=UserRole(role),
                roles=[role],
                is_active=True,
            )
            db.add(user)
            await db.commit()
            token = create_access_token(subject=user.id, role=role)
        return {"Authorization": f"Bearer {token}"}

    finance = await app_client.get(URL, headers=await headers("finance"))
    assert finance.status_code == 200, finance.text

    recruiter = await app_client.get(URL, headers=await headers("recruiter"))
    assert recruiter.status_code == 403
