"""Three-decimal precision survives persistence contracts and API output."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import TypeAdapter

from app.models.client_order import ClientOrder
from app.models.client_order_group import ClientOrderGroup
from app.models.finance import FinanceMonthlyResult
from app.models.md_consumption import (
    ClientOrderInvoiceConsumption,
    MdConsumptionImportRow,
)
from app.schemas.client_order import ClientOrderUpdate
from app.schemas.client_order_group import MoneyPLN as OrderMoneyValue
from app.schemas.client_order_group import OrderGroupUpdate
from app.schemas.finance import FinanceResultRow, FinanceRowUpdate
from app.schemas.md_consumption import ImportRowRead
from app.schemas.new_contractor_order import NewContractorOrderRequest
from app.services.cost_orders import quantize_money
from app.services.multi_consultant_orders import format_md


BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic/versions/0252_md_cost_result_precision3.py"


def test_models_keep_three_decimal_result_scales() -> None:
    assert ClientOrder.__table__.c.total_value.type.precision == 13
    assert ClientOrder.__table__.c.total_value.type.scale == 3
    assert FinanceMonthlyResult.__table__.c.md_count.type.scale == 3
    assert FinanceMonthlyResult.__table__.c.compensation.type.scale == 3
    assert FinanceMonthlyResult.__table__.c.invoice_amount.type.scale == 3
    assert FinanceMonthlyResult.__table__.c.margin_pln.type.scale == 3

    for column in (
        ClientOrderGroup.__table__.c.budget_amount,
        ClientOrderGroup.__table__.c.budget_remaining,
        ClientOrderGroup.__table__.c.budget_manual_adjustment,
        MdConsumptionImportRow.__table__.c.invoice_amount,
        ClientOrderInvoiceConsumption.__table__.c.invoice_amount,
        ClientOrderInvoiceConsumption.__table__.c.settled_amount,
        ClientOrderInvoiceConsumption.__table__.c.unsettled_amount,
    ):
        assert column.type.scale == 3, column.name


def test_api_serializers_do_not_round_results_back_to_two_places() -> None:
    finance = FinanceResultRow(
        id=1,
        row_number=2,
        consultant_name="Jan Kowalski",
        md_count=Decimal("22.375"),
        compensation=Decimal("20900.125"),
        invoice_amount=Decimal("26180.375"),
        margin_pln=Decimal("5280.250"),
    ).model_dump(mode="json")
    assert finance["md_count"] == 22.375
    assert finance["compensation"] == 20900.125
    assert finance["invoice_amount"] == 26180.375
    assert finance["margin_pln"] == 5280.25

    finance_patch = FinanceRowUpdate(
        md_count=Decimal("22.375"),
        compensation=Decimal("20900.125"),
        invoice_amount=Decimal("26180.375"),
        margin_pln=Decimal("5280.250"),
    )
    assert finance_patch.invoice_amount == Decimal("26180.375")
    assert finance_patch.margin_pln == Decimal("5280.250")

    imported = ImportRowRead(
        id=1,
        row_number=2,
        consultant_name="Jan Kowalski",
        md_reported=Decimal("15.375000"),
        status="applied",
        status_label="Zaktualizowano",
        invoice_amount=Decimal("1234.125"),
    ).model_dump(mode="json")
    assert imported["md_reported"] == 15.375
    assert imported["invoice_amount"] == 1234.125

    assert (
        TypeAdapter(OrderMoneyValue).dump_python(Decimal("35000.125"), mode="json")
        == 35000.125
    )

    standalone = ClientOrderUpdate(total_value=Decimal("50000.125"))
    new_contractor = NewContractorOrderRequest(
        candidate_id=1,
        title="SAP 4500030751",
        total_value=Decimal("50000.125"),
    )
    group = OrderGroupUpdate(
        budget_amount=Decimal("50000.125"),
        budget_manual_adjustment=Decimal("0.375"),
    )
    assert standalone.total_value == Decimal("50000.125")
    assert new_contractor.total_value == Decimal("50000.125")
    assert group.budget_amount == Decimal("50000.125")
    assert group.budget_manual_adjustment == Decimal("0.375")


def test_calculation_and_history_format_use_three_places() -> None:
    assert quantize_money("1234.1254") == Decimal("1234.125")
    assert format_md(Decimal("15.3754")) == "15.375"


def test_0252_is_schema_only_and_covers_every_result_column() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0252_md_cost_result_precision3"' in source
    assert 'down_revision = "0251_explicit_md_per_consultant"' in source

    upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    assert "UPDATE " not in upgrade.upper()
    assert "op.alter_column" in upgrade

    for table, column in (
        ("finance_monthly_results", "md_count"),
        ("finance_monthly_results", "compensation"),
        ("finance_monthly_results", "invoice_amount"),
        ("finance_monthly_results", "margin_pln"),
        ("client_orders", "total_value"),
        ("client_order_groups", "budget_amount"),
        ("client_order_groups", "budget_remaining"),
        ("client_order_groups", "budget_manual_adjustment"),
        ("md_consumption_import_rows", "invoice_amount"),
        ("client_order_invoice_consumptions", "invoice_amount"),
        ("client_order_invoice_consumptions", "settled_amount"),
        ("client_order_invoice_consumptions", "unsettled_amount"),
    ):
        assert f'("{table}", "{column}"' in source


def test_0252_downgrade_keeps_room_for_rounding_carry() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade = source.split("def downgrade()", 1)[1]
    assert "type_=sa.Numeric(new_precision, 2)" in downgrade
    assert "numeric({new_precision},2)" in downgrade
    assert "numeric({old_precision},2)" not in downgrade
