"""Finanse → Zamówienia PDF: grupowanie po miesiącu startu, nazwy plików, dostęp.

Baza testowa jest wspólna i nie jest czyszczona — każdy test pracuje na
własnym kliencie i na losowym miesiącu z dalekich lat, a asercje filtrują
wyniki po swoim kliencie.
"""

from __future__ import annotations

import io
import random
import uuid
from datetime import date
from decimal import Decimal
from urllib.parse import unquote

import pytest
from httpx import AsyncClient

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.services.finance_order_pdfs import build_download_name, format_period

pytestmark = pytest.mark.asyncio

_PDF = b"%PDF-1.4\n% test\n"


# ── Nazwa pliku (bez bazy) ──────────────────────────────────────────────────


def test_download_name_appends_surname_and_period():
    assert (
        build_download_name(
            "zamowienie_alior.pdf", "Nowak", date(2026, 9, 15), date(2026, 12, 31)
        )
        == "zamowienie_alior_Nowak_15.09.2026-31.12.2026.pdf"
    )


def test_download_name_without_surname_gets_only_the_period():
    assert (
        build_download_name("PO 445.PDF", None, date(2026, 9, 1), date(2026, 9, 30))
        == "PO 445_01.09.2026-30.09.2026.PDF"
    )


def test_download_name_open_ended_and_unsafe_characters():
    assert format_period(date(2026, 9, 1), None) == "01.09.2026-bezterminowo"
    name = build_download_name('a:b/c"d.pdf', "Nowak Kowalska", date(2026, 9, 1), None)
    assert name == "c_d_Nowak_Kowalska_01.09.2026-bezterminowo.pdf"
    assert build_download_name(None, "Łęcka", date(2026, 1, 2), None) == (
        "zamowienie_Łęcka_02.01.2026-bezterminowo.pdf"
    )
    assert build_download_name("skan", None, date(2026, 1, 2), None).endswith(
        "_02.01.2026-bezterminowo.pdf"
    )


# ── Dane w bazie ────────────────────────────────────────────────────────────


def _far_month() -> date:
    return date(random.randint(2060, 2099), random.randint(1, 12), 1)


async def _person(db, client_id: int, lastname: str) -> Contract:
    from app.models.candidate import Candidate

    candidate = Candidate(
        name="Jan", lastname=lastname, email=f"fop-{uuid.uuid4().hex[:8]}@example.com"
    )
    db.add(candidate)
    await db.flush()
    contract = Contract(
        candidate_id=candidate.id,
        client_id=client_id,
        contract_type=ContractType.b2b,
        status=ContractStatus.active,
        start_date=date(1940, 1, 1),
        rate_candidate=Decimal("100.000"),
        rate_unit=RateUnit.hourly,
        currency="PLN",
        rate_candidate_currency="PLN",
    )
    db.add(contract)
    await db.flush()
    return contract


def _order(client_id: int, contract_id: int, **extra) -> ClientOrder:
    return ClientOrder(
        client_id=client_id,
        contract_id=contract_id,
        title=f"NB-{uuid.uuid4().hex[:6]}",
        status=extra.pop("status", ClientOrderStatus.active),
        rate_unit=RateUnit.hourly,
        rate_client=Decimal("150.000"),
        rate_candidate=Decimal("100.000"),
        rate_client_currency="PLN",
        rate_candidate_currency="PLN",
        currency="PLN",
        **extra,
    )


def _attach(order_or_group, saver, filename: str) -> None:
    rel, size = saver(order_or_group.id, filename, io.BytesIO(_PDF))
    order_or_group.file_path = rel
    order_or_group.filename = filename
    order_or_group.content_type = "application/pdf"
    order_or_group.size_bytes = size


async def _seed(month: date) -> dict:
    """Klient z: zamówieniem okresowym, jego przedłużeniem, anulowanym,
    grupą z jedną osobą, grupą z dwiema osobami, linią BNP z własnym PDF-em
    i aneksem przedłużającym z dokumentem."""

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.client_order_group import ClientOrderGroup
    from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
    from app.models.contract_document import ContractDocument
    from app.services import storage_service

    suffix = uuid.uuid4().hex[:6]
    last = date(month.year, month.month, 28)
    prev_month = date(month.year - 1, month.month, 1)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"FinPdf {suffix}")
        db.add(client)
        await db.flush()
        alpha = await _person(db, client.id, f"Alfa{suffix}")
        beta = await _person(db, client.id, f"Beta{suffix}")
        gamma = await _person(db, client.id, f"Gamma{suffix}")

        earlier = _order(
            client.id, alpha.id, start_date=prev_month, end_date=prev_month
        )
        periodic = _order(client.id, alpha.id, start_date=month, end_date=last)
        cancelled = _order(
            client.id, beta.id, start_date=month, status=ClientOrderStatus.cancelled
        )
        db.add_all([earlier, periodic, cancelled])
        await db.flush()
        _attach(periodic, storage_service.save_client_order_po, "zamowienie_alior.pdf")
        _attach(cancelled, storage_service.save_client_order_po, "anulowane.pdf")

        solo = ClientOrderGroup(
            client_id=client.id, order_number=f"S-{suffix}", start_date=month
        )
        multi = ClientOrderGroup(
            client_id=client.id,
            order_number=f"M-{suffix}",
            start_date=month,
            end_date=last,
        )
        db.add_all([solo, multi])
        await db.flush()
        _attach(solo, storage_service.save_client_order_group_po, "solo.pdf")
        _attach(multi, storage_service.save_client_order_group_po, "bnp_zbiorcze.pdf")
        db.add(_order(client.id, beta.id, order_group_id=solo.id))
        bnp_line = _order(client.id, gamma.id, order_group_id=multi.id)
        db.add_all([bnp_line, _order(client.id, beta.id, order_group_id=multi.id)])
        await db.flush()
        _attach(bnp_line, storage_service.save_client_order_po, "bnp_osoba.pdf")

        rel, size = storage_service.save_contract_document(
            gamma.id, "aneks.pdf", io.BytesIO(_PDF)
        )
        doc = ContractDocument(
            contract_id=gamma.id, filename="aneks.pdf", file_path=rel, size_bytes=size
        )
        copy = ContractDocument(
            contract_id=gamma.id,
            filename="kopia_grupy.pdf",
            file_path=rel,
            source_order_group_id=multi.id,
        )
        db.add_all([doc, copy])
        await db.flush()
        prev_end = date(month.year, month.month, 1).toordinal() - 1
        amendment = ContractAmendment(
            contract_id=gamma.id,
            amendment_type=ContractAmendmentType.extension,
            old_values={"end_date": date.fromordinal(prev_end).isoformat()},
            new_values={"end_date": last.isoformat()},
            effective_date=date(month.year - 1, 1, 1),
            document_id=doc.id,
        )
        db.add(amendment)
        await db.commit()
        return {
            "client_id": client.id,
            "suffix": suffix,
            "periodic": periodic.id,
            "cancelled": cancelled.id,
            "solo": solo.id,
            "multi": multi.id,
            "bnp_line": bnp_line.id,
            "amendment": amendment.id,
            "last": last,
        }


async def _month(app_client, headers, month: date) -> dict:
    resp = await app_client.get(
        "/api/finance/order-pdfs",
        params={"year": month.year, "month": month.month},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_month_lists_client_files_with_names_from_the_assignment(
    app_client: AsyncClient, app_auth_headers: dict
):
    month = _far_month()
    ids = await _seed(month)
    body = await _month(app_client, app_auth_headers, month)
    [client] = [c for c in body["clients"] if c["client_id"] == ids["client_id"]]
    files = {(f["kind"], f["id"]): f for f in client["files"]}
    period = format_period(month, ids["last"])
    sfx = ids["suffix"]

    periodic = files[("order", ids["periodic"])]
    assert periodic["download_name"] == f"zamowienie_alior_Alfa{sfx}_{period}.pdf"
    assert periodic["entry_type"] == "extension"
    assert periodic["original_name"] == "zamowienie_alior.pdf"

    # Linia BNP z własnym PDF-em: nazwisko z przypisania, okres z grupy.
    line = files[("order", ids["bnp_line"])]
    assert line["download_name"] == f"bnp_osoba_Gamma{sfx}_{period}.pdf"

    # Grupa z jedną osobą — nazwisko; z dwiema — tylko klient i okres.
    solo = files[("group", ids["solo"])]
    assert solo["download_name"] == (f"solo_Beta{sfx}_{format_period(month, None)}.pdf")
    multi = files[("group", ids["multi"])]
    assert multi["download_name"] == f"bnp_zbiorcze_{period}.pdf"
    assert multi["consultant_name"] is None

    amendment = files[("amendment", ids["amendment"])]
    assert amendment["entry_type"] == "amendment"
    assert amendment["download_name"] == f"aneks_Gamma{sfx}_{period}.pdf"

    # Anulowane i kopia PDF-u grupy w dokumentach kontraktu — poza widokiem.
    assert ("order", ids["cancelled"]) not in files
    assert all(f["original_name"] != "kopia_grupy.pdf" for f in client["files"])
    assert len(client["files"]) == 5


async def test_months_summary_counts_the_client(
    app_client: AsyncClient, app_auth_headers: dict
):
    month = _far_month()
    await _seed(month)
    resp = await app_client.get(
        "/api/finance/order-pdfs/months", headers=app_auth_headers
    )
    assert resp.status_code == 200
    key = month.strftime("%Y-%m")
    [item] = [i for i in resp.json()["items"] if i["month"] == key]
    assert item["files"] >= 5 and item["clients"] >= 1


async def test_download_uses_the_listed_name(
    app_client: AsyncClient, app_auth_headers: dict
):
    month = _far_month()
    ids = await _seed(month)
    resp = await app_client.get(
        f"/api/finance/order-pdfs/order/{ids['periodic']}/file",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")
    disposition = unquote(resp.headers["content-disposition"])
    assert f"zamowienie_alior_Alfa{ids['suffix']}_" in disposition

    gone = await app_client.get(
        f"/api/finance/order-pdfs/order/{ids['cancelled']}/file",
        headers=app_auth_headers,
    )
    assert gone.status_code == 404


async def _headers_for(app_client: AsyncClient, role: str) -> dict[str, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    email = f"fop-{role}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Fop {role}",
                role=UserRole(role),
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.parametrize("role", ["recruiter", "delivery_lead"])
async def test_only_finance_section_can_see_order_pdfs(
    app_client: AsyncClient, role: str
):
    headers = await _headers_for(app_client, role)
    for path in (
        "/api/finance/order-pdfs/months",
        "/api/finance/order-pdfs",
        "/api/finance/order-pdfs/order/1/file",
    ):
        resp = await app_client.get(path, headers=headers)
        assert resp.status_code == 403, (path, resp.status_code)


async def test_finance_role_can_list(app_client: AsyncClient):
    headers = await _headers_for(app_client, "finance")
    resp = await app_client.get("/api/finance/order-pdfs/months", headers=headers)
    assert resp.status_code == 200
