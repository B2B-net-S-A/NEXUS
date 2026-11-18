"""Import wyciągu w Księdze (K4a) — koszt nie rośnie z liczbą operacji.

18.11.2026 18:42 import wyciągu na produkcji trwał 66,6 s przy 1057
zapytaniach (``http_outcome``), a jeden proces web stał przez ten czas
(``loop_lag_ms_p99`` 1111 ms, ``cpu_pct`` 87% bez pełnej zbiórki GC):
``/api/health`` 12,8 s, pulpit Rady 9–14 s. Dwa źródła:

* zapytania na każdą operację — duplikat sprawdzany w E3, R9 i E8 osobno dla
  każdej linii, ``refresh`` stanu zapłaty i zamknięcie pozycji paczki po
  każdej dopasowanej fakturze kosztowej, kontrahent faktury sprzedaży szukany
  fakturą po fakturze;
* CPU — wzorzec numeru faktury kompilowany od nowa dla każdej pary (operacja ×
  faktura); przy tysiącach faktur pamięć podręczna ``re`` (512 wzorców) nic nie
  trzyma, a jedna kompilacja to ok. 0,2 ms.

Test liczy SQL wysłany do sterownika przy ``POST /bank/import`` dla wyciągu
z ``k`` dopasowanymi fakturami kosztowymi, ``k`` wpłatami klientów, ``k``
wypłatami dla zespołu, ``k`` obciążeniami spoza NEXUSA i ``k`` opłatami banku —
dla dwóch wartości ``k``. Zapytania do tabel E3, E8 i Księgi nie rosną
wcale; rośnie tylko zapłata rozliczeń zespołu (``mark_paid`` osobno na każde
opłacone rozliczenie, jak „Opłacono” na karcie). Rodzaj, konto i uwaga każdej linii są sprawdzane dokładnie — te same
przed zmianą i po niej. Kwoty, NIP-y i rachunki fikcyjne.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, event, select, update

from app.core.database import AsyncSessionLocal, engine
from app.models.app_setting import AppSetting
from app.models.client_sales_invoice import (
    ClientSalesInvoice,
    ClientSalesInvoicePayment,
)
from app.models.finance_ledger import FinanceCostEntry
from app.models.finance_payments import FinanceCostPaymentRecord
from app.models.hr_approval import ApprovalDocument
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_settlement import PayrollInvoice, PayrollPayment, PayrollSettlement
from app.models.notification import Notification
from app.services.client_invoicing import settings as invoicing_settings
from app.services.finance_ledger.payments import DUPLICATE_REASON
from app.services.ledger import sources
from tests.test_finance_ledger_db import _headers, _set, world  # noqa: F401
from tests.test_finance_posting_db import _expense
from tests.test_ledger_db import _set_ledger
from tests.test_ledger_sources_db import (  # noqa: F401  (fixture ``client``, ``books``)
    ACC,
    OTHER_ACCOUNT,
    STRANGER_ACCOUNT,
    _bank_settings,
    _sales_invoice,
    _statement,
    books,
    client,
)

pytestmark = pytest.mark.asyncio

TEAM_NOTE = "Konto przypisuje osoba z Płacami (wypłata B2B, zwrot albo bez rozliczenia)."
#: Tabele, o które import pytał dotąd osobno dla każdej operacji.
PER_LINE_TABLES = (
    "finance_cost_",
    "finance_payment_batch_items",
    "client_sales_invoice",
    "finance_counterparties",
    "ledger_bank_",
    "payroll_payments WHERE",
)
#: Opłacone rozliczenie zespołu kosztuje swoje zapytania (``mark_paid``: blokada,
#: status, ślad HR, powiadomienie osoby z kontrolą RBAC) — jak „Opłacono” na
#: karcie, raz na rozliczenie. Zmierzone 19.11.2026: 17.
PER_TEAM_PAYOUT = 17


@contextmanager
def capture_sql():
    seen: list[str] = []

    def _on(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _on)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on)


def _shape(statement: str) -> str:
    """Początek zapytania — do komunikatu, który rodzaj zapytań rośnie."""

    return " ".join(statement.split())[:90]


async def _cost_invoices(world, books, k: int, marker: str) -> list[tuple[str, str]]:
    """``k`` faktur kosztowych dostawcy z kartoteki: (numer KSeF, kwota brutto)."""

    out = []
    for index in range(k):
        gross = f"{100 + index}.{index % 100:02d}"
        entry_id = await _expense(
            world, number=f"FK {marker}/{index}", net=gross, vat="0.00", gross=gross
        )
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(FinanceCostEntry)
                .where(FinanceCostEntry.id == entry_id)
                .values(stage="ready", counterparty_id=books["supplier"].id)
            )
            entry = await db.get(FinanceCostEntry, entry_id)
            ksef = await db.scalar(
                select(ApprovalDocument.ksef_number).where(
                    ApprovalDocument.id == entry.source_id
                )
            )
            await db.commit()
            out.append((ksef, gross))
    return out


async def _sales(world, books, k: int, marker: str) -> list[tuple[int, str, str]]:
    """``k`` faktur do klienta z kartoteki: (id, numer KSeF, kwota brutto)."""

    year = books["year"]
    nip = world["nips"]["client"]
    invoices = [
        _sales_invoice(
            nip,
            number=f"FS {marker}/{index}",
            buyer_nip=nip,
            buyer_name="Klient Testowy",
            issue_date=date(year, 3, 2),
            sale_date=date(year, 3, 2),
            net_amount=Decimal(f"{200 + index}.00"),
            vat_amount=Decimal("0"),
            gross_amount=Decimal(f"{200 + index}.00"),
        )
        for index in range(k)
    ]
    async with AsyncSessionLocal() as db:
        db.add_all(invoices)
        await db.commit()
    return [(i.id, i.ksef_number, f"{i.gross_amount:.2f}") for i in invoices]


async def _team(world, books, months: range, marker: str) -> dict[str, list]:
    """Rozliczenia B2B osoby z zespołu (miesiące roku testu) z fakturą z KSeF."""

    year = books["year"]
    person = world["person"]
    nip = world["nips"]["person"]
    made: dict[str, list] = {"periods": [], "settlements": [], "invoices": [], "ops": []}
    async with AsyncSessionLocal() as db:
        for month in months:
            gross = Decimal(f"{3000 + month}.00")
            ksef = f"{nip}-{year}{month:02d}28-{uuid.uuid4().hex[:12].upper()}-AB"
            period = PayrollPeriod(
                year=year,
                month=month,
                status="closed",
                closed_at=datetime.now(timezone.utc),
                close_count=1,
            )
            db.add(period)
            await db.flush()
            settlement = PayrollSettlement(
                period_id=period.id,
                user_id=person.id,
                employment_type="b2b",
                currency="PLN",
                expected_amount=gross,
                amount_basis="net",
                status="approved",
            )
            db.add(settlement)
            await db.flush()
            invoice = PayrollInvoice(
                source="ksef",
                ksef_number=ksef,
                ksef_acquired_at=datetime(year, month, 28, 9, 0, tzinfo=timezone.utc),
                seller_nip=nip,
                user_id=person.id,
                invoice_number=f"FV/{marker}/{month}",
                invoice_kind="original",
                issue_date=date(year, month, 28),
                currency="PLN",
                net_amount=gross,
                vat_amount=Decimal("0"),
                gross_amount=gross,
                items=[],
                xml_sha256=hashlib.sha256(ksef.encode()).hexdigest(),
                settlement_id=settlement.id,
                match_status="matched",
            )
            db.add(invoice)
            await db.flush()
            made["periods"].append(period.id)
            made["settlements"].append(settlement.id)
            made["invoices"].append(invoice.id)
            made["ops"].append((f"{gross:.2f}", f"FV/{marker}/{month} {ksef}"))
        await db.commit()
    return made


async def _drop_team(made: dict[str, list]) -> None:
    async with AsyncSessionLocal() as db:
        ids = made["settlements"]
        await db.execute(delete(PayrollPayment).where(PayrollPayment.settlement_id.in_(ids)))
        await db.execute(delete(PayrollInvoice).where(PayrollInvoice.id.in_(made["invoices"])))
        await db.execute(delete(PayrollSettlement).where(PayrollSettlement.id.in_(ids)))
        await db.execute(delete(PayrollPeriod).where(PayrollPeriod.id.in_(made["periods"])))
        await db.commit()


def _operations(costs, sales, team, marker: str) -> list[tuple[str, str, str, str, str]]:
    ops: list[tuple[str, str, str, str, str]] = []
    for index, (ksef, gross) in enumerate(costs):
        ops.append(("D", gross.replace(".", ","), f"Zaplata {ksef}", OTHER_ACCOUNT, f"K{marker}{index}"))
    for index, (_id, ksef, gross) in enumerate(sales):
        ops.append(("C", gross.replace(".", ","), f"Wplata {ksef}", OTHER_ACCOUNT, f"S{marker}{index}"))
    for index, (gross, title) in enumerate(team["ops"]):
        ops.append(("D", gross.replace(".", ","), title, STRANGER_ACCOUNT, f"P{marker}{index}"))
    for index in range(len(costs)):
        ops.append(("D", f"{30 + index},00", f"Czynsz {marker} {index}", OTHER_ACCOUNT, f"U{marker}{index}"))
        ops.append(("D", f"{index + 1},50", "Opłata za przelew", "", f"F{marker}{index}"))
    return ops


def _expected(books, k: int, *, payroll: bool) -> list[tuple]:
    """(rodzaj, konto, płacowe, uwaga) linii w kolejności pliku i zasięgu osoby."""

    acc = books["acc"]
    sales_account = sources.receivable_account(books["buyer"], acc["receivable"])
    rows = [("cost_invoice", books["supplier"].cost_account, False, "")] * k
    rows += [("sales_invoice", sales_account, False, "")] * k
    if payroll:
        rows += [("team", None, True, TEAM_NOTE)] * k
    for _index in range(k):
        rows.append(("unmatched", None, False, ""))
        rows.append(("fee", acc["fees"], False, ""))
    return rows


def _seen(data) -> list[tuple]:
    return [
        (line["kind"], line["counter_account"], line["payroll"], line["note"])
        for line in data["lines"]
    ]


async def _post(client, world, user: str, content: bytes):
    with capture_sql() as seen:
        response = await client.post(
            f"{ACC}/bank/import",
            files={"file": ("wyciag.sta", content, "text/plain")},
            headers=_headers(world[user]),
        )
    assert response.status_code == 201, response.text
    return response.json(), seen


@pytest_asyncio.fixture
async def invoicing():
    """Moduł faktur do klientów włączony (E8 dopasowuje uznania), potem jak był."""

    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(
                AppSetting.key == invoicing_settings.SETTING_KEY
            )
        )
    await _set(invoicing_settings.SETTING_KEY, {"enabled": True})
    yield
    await _set(invoicing_settings.SETTING_KEY, previous)


@pytest.mark.parametrize("user", ["accountant", "module_only"])
async def test_bank_import_query_count_does_not_grow_with_lines(
    client, world, books, invoicing, user
):
    await _set_ledger(_bank_settings(world, books))
    payroll = user == "accountant"
    runs = []
    team_made = []
    sales_ids: list[int] = []
    try:
        for k, months in ((2, range(1, 3)), (8, range(3, 11))):
            marker = uuid.uuid4().hex[:5].upper()
            costs = await _cost_invoices(world, books, k, marker)
            sales = await _sales(world, books, k, marker)
            sales_ids += [item[0] for item in sales]
            team = await _team(world, books, months, marker)
            team_made.append(team)
            ops = _operations(costs, sales, team, marker)
            data, sql = await _post(client, world, user, _statement(books["year"], *ops))
            assert data["already_imported"] is False
            assert _seen(data) == _expected(books, k, payroll=payroll)
            assert data["payroll_hidden"] is (not payroll)
            assert data["unresolved"] == k * (2 if payroll else 1)
            runs.append((k, ops, data, sql))

        (_k1, _ops1, _d1, small_sql), (k2, ops2, large, large_sql) = runs
        growth = Counter(map(_shape, large_sql)) - Counter(map(_shape, small_sql))
        print(f"\n[{user}] k=2: {len(small_sql)} zapytań, k=8: {len(large_sql)}")
        for shape, count in growth.most_common(30):
            print(f"  +{count:4d}  {shape}")
        per_line = {
            shape: n
            for shape, n in growth.items()
            if any(table in shape for table in PER_LINE_TABLES)
        }
        assert not per_line, per_line
        extra_payouts = (k2 - 2) if payroll else 0
        assert len(large_sql) - len(small_sql) <= PER_TEAM_PAYOUT * extra_payouts, (
            growth.most_common(10)
        )

        # Ten sam ruch w drugim pliku (dzienny i miesięczny): duplikat w Księdze
        # i „ignored” w E3/E8/R9 — sprawdzane hurtem, tak samo jak linia po linii.
        fee = ("D", "7,77", "Opłata za wyciąg", "", f"G{uuid.uuid4().hex[:6]}")
        again, again_sql = await _post(
            client, world, user, _statement(books["year"], *ops2, fee)
        )
        kinds = Counter(line["kind"] for line in again["lines"])
        assert kinds == {"duplicate": len(again["lines"]) - 1, "fee": 1}, kinds
        sha = hashlib.sha256(_statement(books["year"], *ops2, fee)).hexdigest()
        async with AsyncSessionLocal() as db:
            for model, expected in (
                (FinanceCostPaymentRecord, k2),
                (ClientSalesInvoicePayment, k2),
                (PayrollPayment, k2 if payroll else 0),
            ):
                rows = list(
                    await db.scalars(select(model).where(model.statement_sha256 == sha))
                )
                assert len(rows) == expected, model.__tablename__
                assert {(row.match_status, row.reason) for row in rows} <= {
                    ("ignored", DUPLICATE_REASON)
                }
        assert len(again_sql) <= len(large_sql)
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ClientSalesInvoicePayment).where(
                    ClientSalesInvoicePayment.invoice_id.in_(sales_ids)
                )
            )
            await db.execute(delete(ClientSalesInvoice).where(ClientSalesInvoice.id.in_(sales_ids)))
            await db.commit()
        for made in team_made:
            await _drop_team(made)
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Notification).where(Notification.user_id == world["person"].id)
            )
            await db.commit()
