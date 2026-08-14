"""Wgrywanie i podmiana PDF zamówienia (`PUT /orders/{id}/file`).

Endpoint istniał od dawna, ale nie miał ŻADNEGO wywołania z frontu — draft
tworzony automatycznie przez hook „hired" nosił notatkę „wgraj PDF zamówienia",
której nie dało się wykonać. Te testy pilnują trzech własności, na których
opiera się wymaganie „plik pojawia się w Dokumentach kontraktu, a podmiana go
aktualizuje, a nie dubluje":

* jeden Order = JEDEN plik (podmiana nadpisuje wiersz, nie dokłada drugiego),
* most do Dokumentów kontraktu jest liczony w locie z tego samego wiersza,
  więc nie ma czego zdublować,
* upload jest sprawdzany zanim cokolwiek trafi na dysk.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_TODAY = date.today()
_PDF = b"%PDF-1.4\n% minimalny plik\n"


async def _seed_order() -> dict[str, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Upl",
            lastname=f"C-{uuid.uuid4().hex[:6]}",
            email=f"upl-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"UplClient-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(client)

        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=_TODAY - timedelta(days=5),
            end_date=_TODAY + timedelta(days=60),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
            margin=Decimal("50.000"),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)

        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title=f"PO-{uuid.uuid4().hex[:5]}",
            status=ClientOrderStatus.draft,
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)

        return {
            "client_id": client.id,
            "contract_id": contract.id,
            "order_id": order.id,
        }


async def test_upload_attaches_pdf_and_records_uploader(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    ids = await _seed_order()
    resp = await app_client.put(
        f"/api/clients/{ids['client_id']}/orders/{ids['order_id']}/file",
        headers=app_auth_headers,
        files={"file": ("zamowienie.pdf", _PDF, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_file"] is True
    assert body["filename"] == "zamowienie.pdf"

    # Atrybucja: sekcja „Dokumenty zamówień" pokazuje ją w kolumnie „Dodał".
    bridge = await app_client.get(
        f"/api/clients/order-documents/by-contract/{ids['contract_id']}",
        headers=app_auth_headers,
    )
    assert bridge.status_code == 200, bridge.text
    docs = bridge.json()["documents"]
    assert len(docs) == 1
    assert docs[0]["uploaded_by_email"]
    assert docs[0]["uploaded_at"]


async def test_replacing_pdf_updates_row_instead_of_duplicating(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Wymaganie z ticketu wprost: podmiana AKTUALIZUJE, nie dubluje.

    Most do Dokumentów kontraktu jest read-time i czyta jeden wiersz Ordera,
    więc drugi wpis nie ma jak powstać — ten test broni tej właściwości przed
    „ulepszeniem" polegającym na kopiowaniu pliku do `contract_documents`.
    """
    ids = await _seed_order()
    url = f"/api/clients/{ids['client_id']}/orders/{ids['order_id']}/file"

    first = await app_client.put(
        url,
        headers=app_auth_headers,
        files={"file": ("v1.pdf", _PDF, "application/pdf")},
    )
    assert first.status_code == 200, first.text

    second = await app_client.put(
        url,
        headers=app_auth_headers,
        files={"file": ("v2.pdf", _PDF + b"druga wersja", "application/pdf")},
    )
    assert second.status_code == 200, second.text
    assert second.json()["filename"] == "v2.pdf"

    bridge = await app_client.get(
        f"/api/clients/order-documents/by-contract/{ids['contract_id']}",
        headers=app_auth_headers,
    )
    docs = bridge.json()["documents"]
    assert len(docs) == 1, "podmiana pliku zdublowała pozycję w Dokumentach"
    assert docs[0]["filename"] == "v2.pdf"


async def test_upload_rejects_non_pdf_extension(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    ids = await _seed_order()
    resp = await app_client.put(
        f"/api/clients/{ids['client_id']}/orders/{ids['order_id']}/file",
        headers=app_auth_headers,
        files={"file": ("zamowienie.docx", _PDF, "application/msword")},
    )
    assert resp.status_code == 415, resp.text


async def test_upload_rejects_file_that_only_pretends_to_be_pdf(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Rozszerzenie deklaruje nadawca; nagłówek pliku nie.

    Bez kontroli magicznych bajtów dowolna treść przemianowana na „.pdf"
    trafiała na wolumen i była potem serwowana z `media_type=application/pdf`
    każdemu, kto otworzy dokument zamówienia.
    """
    ids = await _seed_order()
    resp = await app_client.put(
        f"/api/clients/{ids['client_id']}/orders/{ids['order_id']}/file",
        headers=app_auth_headers,
        files={"file": ("udaje.pdf", b"<html>nie pdf</html>", "application/pdf")},
    )
    assert resp.status_code == 415, resp.text


async def test_bridge_lists_nothing_before_upload(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    ids = await _seed_order()
    bridge = await app_client.get(
        f"/api/clients/order-documents/by-contract/{ids['contract_id']}",
        headers=app_auth_headers,
    )
    assert bridge.status_code == 200, bridge.text
    assert bridge.json()["documents"] == []
