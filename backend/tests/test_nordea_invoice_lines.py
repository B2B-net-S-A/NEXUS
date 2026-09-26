"""Nordea: pozycja faktury cyklicznej w „Wejściach” (ticket 8, 25.09.2026).

Tekst dokumentu odwzorowuje układ, który pdfplumber oddaje dla Call Off
Agreement Nordei (sprawdzony 25.09 na 60 zamówieniach z produkcji): sekcja
„Invoice reference” jest PRAWĄ kolumną przeplecioną z adresem do faktury.
Osoby i numery są fikcyjne — repo jest publiczne.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services import nordea_invoice_lines as nil
from app.services.order_document_text import OrderDocumentText

ROOT = Path(__file__).resolve().parents[1]


def _document(
    *,
    niids: str = "NIIDS number: 2099-000123",
    contact: str = "Contact person: Jan Testowy",
    people: tuple[str, ...] = ("Anna Kowalska",),
) -> str:
    rows = "\n".join(
        f"{person} IT Developer Poland - 1 040 Hours 135,00 PLN 140 400,00 PLN"
        for person in people
    )
    return f"""Call Off Agreement
Nordea
Company name (hereinafter referred to as "Nordea") Company number
Nordea Bank Abp 2858394-9
Nordea contact e-mail address Nordea Request number (if Frame Agreement Call Off
applicable) number Agreement
consultant.procurement@example.com number
42452 CW2117535
299001
Nordea contact person Telephone number (including area code)
Maria Gorna-Testowa
Nordea invoicing address related to this Call Off Agreement Invoice reference
Nordea Bank Abp REF: ITSE
Satamaradankatu 5, FI-00020 NORDEA, Finland {contact}
C/O F206 E-mail: jan.testowy@example.com
SE - 971 90 Lulea {niids}
SE - Sweden Cost center: 2080008026
(VAT number: FI28583949)
Supplier
Company name (hereinafter referred to as the "Supplier") Company number
B2B.net S.A. 0000387063
Street or box Contact person
Aleje Jerozolimskie 180 Piotr Dostawca
Postal code and city Telephone number (including area code)
02-486 Warszawa
Initial Term
Start date End date
2099-09-14 2100-03-12
Consultant(s) (if applicable)
Person(s) at the Supplier who Competence Category Location Quantity (max Unit Rate Subtotal
it is intended to perform the (according to Nordea 160h/month)
service definitions)
{rows}
Total, excl. VAT 140 400,00 PLN
Contact persons
Contact persons under this Call Off Agreement:
For Nordea Maria Gorna-Testowa
"""


# ── Odczyt i formuła (bez bazy) ─────────────────────────────────────────────


def test_formula_is_built_from_invoice_reference_and_consultant_table():
    fields = nil.parse_invoice_fields(_document())
    assert fields.niids == "2099-000123"
    assert fields.contact == "Jan Testowy"
    assert fields.consultants == ("Anna Kowalska",)
    payload = nil.build_payload(fields, source="pdf")
    assert [line["text"] for line in payload["lines"]] == [
        "NIDS: 2099-000123, IT Retail Banking, Nordea Contact: Jan Testowy, "
        "Contractor: Anna Kowalska ID:"
    ]


def test_contact_is_never_taken_from_the_top_table_or_the_supplier():
    """„Nordea contact person” i „Contact person” Suppliera stoją bez dwukropka."""

    fields = nil.parse_invoice_fields(_document(contact="REF2: none"))
    assert fields.contact is None
    assert "Maria" not in nil.formula(fields.niids, fields.contact, "X")
    assert "Piotr Dostawca" not in nil.formula(fields.niids, fields.contact, "X")


def test_missing_fields_become_brak_placeholders():
    fields = nil.parse_invoice_fields(_document(niids="", contact="", people=()))
    payload = nil.build_payload(fields, source="pdf")
    assert [line["text"] for line in payload["lines"]] == [
        "NIDS: [brak], IT Retail Banking, Nordea Contact: [brak], "
        "Contractor: [brak] ID:"
    ]


def test_each_consultant_gets_own_line_and_the_card_shows_its_person():
    payload = nil.build_payload(
        nil.parse_invoice_fields(
            _document(people=("Anna Kowalska", "Tomasz Wiśniewski"))
        ),
        source="pdf",
    )
    texts = [line["text"] for line in payload["lines"]]
    assert len(texts) == 2
    assert texts[1].endswith("Contractor: Tomasz Wiśniewski ID:")

    mine = nil.lines_for_consultant(payload, "Wisniewski Tomasz")
    assert [(line["index"], line["consultant"]) for line in mine] == [
        (1, "Tomasz Wiśniewski")
    ]
    # Osoba spoza tabeli (inna pisownia) widzi wszystkie linie dokumentu.
    assert len(nil.lines_for_consultant(payload, "Ktoś Inny")) == 2


def test_template_without_pdf_keeps_the_order_consultant():
    payload = nil.template_payload("Anna Kowalska")
    assert payload["lines"][0]["text"] == (
        "NIDS: [brak], IT Retail Banking, Nordea Contact: [brak], "
        "Contractor: Anna Kowalska ID:"
    )


def test_deleting_the_pdf_keeps_a_manual_correction():
    class _Order:
        invoice_lines = nil.build_payload(
            nil.parse_invoice_fields(_document()), source="pdf"
        )

    order = _Order()
    order.invoice_lines["lines"][0]["edited_at"] = "2026-09-25T10:00:00+00:00"
    nil.clear_on_file_delete(order)
    assert order.invoice_lines is not None

    fresh = _Order()
    fresh.invoice_lines = nil.build_payload(
        nil.parse_invoice_fields(_document()), source="pdf"
    )
    nil.clear_on_file_delete(fresh)
    assert fresh.invoice_lines is None


def test_column_has_the_same_ddl_in_migration_and_entrypoint():
    source = (ROOT / "alembic/versions/0382_nordea_invoice_lines.py").read_text()
    statement = (
        "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS invoice_lines JSONB NULL"
    )
    assert statement in source
    assert f'"{statement}"' in (ROOT / "entrypoint.sh").read_text()


# ── Ścieżka w aplikacji (baza) ──────────────────────────────────────────────


async def _seed_nordea_order(monkeypatch, *, env: bool = True) -> dict[str, object]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus, ContractType, RateUnit

    suffix = uuid.uuid4().hex[:8]
    # Daleki miesiąc — baza testowa jest wspólna i nie jest czyszczona.
    # API przyjmuje lata 2000–2100 (``_validate_period``).
    first = date(2060 + int(suffix[:4], 16) % 40, 1 + int(suffix[4:6], 16) % 12, 1)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Nordea Test {suffix}")
        candidate = Candidate(
            name="Anna", lastname=f"Kowalska{suffix}", email=f"nil-{suffix}@example.com"
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=first + timedelta(days=3),
            rate_candidate=Decimal("110.000"),
            rate_unit=RateUnit.hourly,
            currency="PLN",
        )
        db.add(contract)
        await db.flush()
        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title=f"29{suffix[:4]}",
            status=ClientOrderStatus.active,
            start_date=first + timedelta(days=3),
            end_date=first + timedelta(days=150),
            rate_unit=RateUnit.hourly,
            rate_client=Decimal("135.000"),
            rate_candidate=Decimal("110.000"),
            currency="PLN",
        )
        db.add(order)
        await db.commit()
        ids = {
            "client_id": client.id,
            "order_id": order.id,
            "first": first,
            "person": f"Anna Kowalska{suffix}",
        }
    if env:
        monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(ids["client_id"]))
    return ids


def _fake_text(monkeypatch, text: str) -> None:
    import app.services.order_document_text as odt

    monkeypatch.setattr(
        odt,
        "extract_order_text",
        lambda path, filename: OrderDocumentText(
            text=text,
            page_count=3,
            ocr_used=False,
            ocr_capped=False,
            reextracted_with=None,
            letter_spacing_ratio=0.0,
        ),
    )


async def _entry(app_client: AsyncClient, headers: dict, ids: dict) -> dict:
    first: date = ids["first"]
    resp = await app_client.get(
        f"/api/finance/order-changes?year={first.year}&month={first.month}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return {e["order_id"]: e for e in resp.json()["entries"]}[ids["order_id"]]


@pytest.mark.asyncio
async def test_pdf_upload_saves_formula_edit_persists_and_survives_done(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    ids = await _seed_nordea_order(monkeypatch)
    _fake_text(monkeypatch, _document(people=(ids["person"],)))

    upload = await app_client.put(
        f"/api/clients/{ids['client_id']}/orders/{ids['order_id']}/file",
        headers=app_auth_headers,
        files={"file": ("286000_signed.pdf", b"%PDF-1.4\n%\n", "application/pdf")},
    )
    assert upload.status_code == 200, upload.text

    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    async with AsyncSessionLocal() as db:
        stored = (await db.get(ClientOrder, ids["order_id"])).invoice_lines
    assert stored["niids"] == "2099-000123"

    entry = await _entry(app_client, app_auth_headers, ids)
    expected = (
        "NIDS: 2099-000123, IT Retail Banking, Nordea Contact: Jan Testowy, "
        f"Contractor: {ids['person']} ID:"
    )
    assert [line["text"] for line in entry["invoice_lines"]] == [expected]

    edited = expected.replace("ID:", "ID: 42")
    save = await app_client.put(
        f"/api/finance/order-changes/invoice-lines/{ids['order_id']}",
        json={"index": 0, "text": edited},
        headers=app_auth_headers,
    )
    assert save.status_code == 200, save.text
    assert save.json()["lines"][0]["edited_by_name"]

    first: date = ids["first"]
    check = await app_client.post(
        "/api/finance/order-changes/checks",
        json={
            "year": first.year,
            "month": first.month,
            "item_key": entry["item_key"],
            "done": True,
        },
        headers=app_auth_headers,
    )
    assert check.status_code == 200, check.text
    after = await _entry(app_client, app_auth_headers, ids)
    assert after["done"] is not None
    assert [line["text"] for line in after["invoice_lines"]] == [edited]


@pytest.mark.asyncio
async def test_nordea_order_without_pdf_gets_template_and_other_clients_none(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    nordea = await _seed_nordea_order(monkeypatch)
    entry = await _entry(app_client, app_auth_headers, nordea)
    assert [line["text"] for line in entry["invoice_lines"]] == [
        "NIDS: [brak], IT Retail Banking, Nordea Contact: [brak], "
        f"Contractor: {nordea['person']} ID:"
    ]

    other = await _seed_nordea_order(monkeypatch, env=False)
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(nordea["client_id"]))
    assert (await _entry(app_client, app_auth_headers, other))["invoice_lines"] is None


@pytest.mark.asyncio
async def test_invoice_line_edit_is_refused_for_other_clients_and_empty_text(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    other = await _seed_nordea_order(monkeypatch, env=False)
    refused = await app_client.put(
        f"/api/finance/order-changes/invoice-lines/{other['order_id']}",
        json={"index": 0, "text": "NIDS: 1"},
        headers=app_auth_headers,
    )
    assert refused.status_code == 422

    nordea = await _seed_nordea_order(monkeypatch)
    blank = await app_client.put(
        f"/api/finance/order-changes/invoice-lines/{nordea['order_id']}",
        json={"index": 0, "text": "   "},
        headers=app_auth_headers,
    )
    assert blank.status_code == 422
    missing = await app_client.put(
        f"/api/finance/order-changes/invoice-lines/{nordea['order_id']}",
        json={"index": 3, "text": "NIDS: 1"},
        headers=app_auth_headers,
    )
    assert missing.status_code == 422


@pytest.mark.asyncio
async def test_loop_fills_formula_for_orders_uploaded_before_the_release(
    monkeypatch, tmp_path
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    ids = await _seed_nordea_order(monkeypatch)
    _fake_text(monkeypatch, _document(people=(ids["person"],)))
    pdf = tmp_path / "old.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(nil, "_abs_path", lambda order: pdf)
    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, ids["order_id"])
        order.file_path = "client_orders/old.pdf"
        await db.commit()

    async with AsyncSessionLocal() as db:
        assert await nil.fill_missing(db) >= 1
        await db.commit()
    async with AsyncSessionLocal() as db:
        stored = (await db.get(ClientOrder, ids["order_id"])).invoice_lines
    assert stored["contact"] == "Jan Testowy"


async def _order_with_old_pdf(monkeypatch, tmp_path) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    ids = await _seed_nordea_order(monkeypatch)
    _fake_text(monkeypatch, _document(people=(ids["person"],)))
    pdf = tmp_path / "old.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(nil, "_abs_path", lambda order: pdf)
    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, ids["order_id"])
        order.file_path = f"client_orders/old-{ids['order_id']}.pdf"
        await db.commit()
    return ids


@pytest.mark.asyncio
async def test_loop_ends_the_read_transaction_before_ocr_and_writes_conditionally(
    monkeypatch, tmp_path
):
    """R5-6 bez bazy: OCR po commicie odczytu, zapis tylko do pustej formuły."""
    import types

    from app.models.client_order import ClientOrder

    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "4242")
    pdf = tmp_path / "old.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(nil, "_abs_path", lambda order: pdf)
    order = ClientOrder(
        id=7, client_id=4242, contract_id=1, file_path="client_orders/a.pdf"
    )
    events: list[str] = []
    statements: list[str] = []

    class FakeSession:
        async def execute(self, stmt):
            sql = str(stmt.compile(compile_kwargs={"literal_binds": False}))
            statements.append(sql)
            events.append("select" if sql.lstrip().startswith("SELECT") else "update")
            return types.SimpleNamespace(
                scalars=lambda: types.SimpleNamespace(all=lambda: [order]),
                rowcount=1,
            )

        async def commit(self):
            events.append("commit")

    async def fake_to_thread(fn, *args, **kwargs):
        events.append("ocr")
        return {"source": "pdf", "lines": []}

    monkeypatch.setattr(nil, "asyncio", types.SimpleNamespace(to_thread=fake_to_thread))
    assert await nil.fill_missing(FakeSession()) == 1
    assert events == ["select", "commit", "ocr", "update", "commit"]
    update_sql = statements[-1]
    assert "invoice_lines IS NULL" in update_sql
    assert "client_orders.file_path =" in update_sql
    assert "file_uploaded_at IS NOT DISTINCT FROM" in update_sql


def _during_ocr(monkeypatch, order_id: int, change) -> None:
    """Zmiana wiersza w trakcie odczytu PDF-a (osobna sesja = inna osoba)."""
    import types

    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    async def fake_to_thread(fn, *args, **kwargs):
        result = fn(*args, **kwargs)
        async with AsyncSessionLocal() as other:
            row = await other.get(ClientOrder, order_id)
            change(row)
            await other.commit()
        return result

    monkeypatch.setattr(nil, "asyncio", types.SimpleNamespace(to_thread=fake_to_thread))


@pytest.mark.asyncio
async def test_loop_never_overwrites_a_manual_correction_made_during_ocr(
    monkeypatch, tmp_path
):
    """R5-6: ręczna formuła zapisana w trakcie OCR biegu wygrywa."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    ids = await _order_with_old_pdf(monkeypatch, tmp_path)
    manual = {"source": "template", "lines": [{"text": "NIDS: ręcznie"}]}

    def set_manual(row):
        row.invoice_lines = manual

    _during_ocr(monkeypatch, ids["order_id"], set_manual)
    async with AsyncSessionLocal() as db:
        await nil.fill_missing(db)
        await db.commit()
    async with AsyncSessionLocal() as db:
        stored = (await db.get(ClientOrder, ids["order_id"])).invoice_lines
    assert stored == manual


@pytest.mark.asyncio
async def test_loop_drops_the_result_when_the_pdf_was_replaced_during_ocr(
    monkeypatch, tmp_path
):
    """R5-6: podmieniony PDF — formuła starego pliku nie trafia do zamówienia."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    ids = await _order_with_old_pdf(monkeypatch, tmp_path)

    def replace_pdf(row):
        row.file_path = f"client_orders/new-{ids['order_id']}.pdf"

    _during_ocr(monkeypatch, ids["order_id"], replace_pdf)
    async with AsyncSessionLocal() as db:
        await nil.fill_missing(db)
        await db.commit()
    async with AsyncSessionLocal() as db:
        stored = (await db.get(ClientOrder, ids["order_id"])).invoice_lines
    assert stored is None


def test_none_is_stored_as_sql_null_so_the_loop_finds_it():
    """Runda 6 audytu: ``order.invoice_lines = None`` zapisywało JSON ``null``,
    którego ``fill_missing`` (``IS NULL``) nigdy nie wybierał."""
    from app.models.client_order import ClientOrder
    from app.services.nordea_invoice_lines import _formula_missing

    column_type = ClientOrder.__table__.c.invoice_lines.type
    assert column_type.none_as_null is True
    sql = str(_formula_missing().compile(compile_kwargs={"literal_binds": True}))
    assert "IS NULL" in sql and "jsonb_typeof" in sql
