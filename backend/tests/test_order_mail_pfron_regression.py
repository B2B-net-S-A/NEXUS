"""Per-document VAT and full client-roster regressions; synthetic documents."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.order_mail_resolver import load_roster, resolve_rows
from app.services.order_mail_planner import plan_document
from app.services.order_pdf_parser import (
    ConsultantOrderRow,
    OrderExtraction,
    apply_document_rate_kind,
    apply_pfron_order_policy,
    erste_extract_rows,
)


def extraction(name="Konrada Korcza", rate="100.08", **kwargs):
    return OrderExtraction(
        title="ZAP/2031/42",
        start_date="2031-04-01",
        end_date="2031-06-30",
        consultant_rows=[
            ConsultantOrderRow(
                consultant_name=name,
                rate_client=Decimal(rate),
                rate_unit="hour",
                uncertain=True,
                uncertain_reason="Stawka podana jako brutto, nie wprost jako netto",
            )
        ],
        **kwargs,
    )


def test_pfron_long_rate_label_clears_only_resolved_uncertainty():
    result = extraction(
        uncertain=True,
        uncertain_reasons=[
            "Stawka podana jako brutto, nie wprost jako netto",
            "Sprawdź datę początku",
        ],
    )
    text = "Stawka brutto za jedną Roboczogodzinę świadczenia usług w PLN: 100,08 zł/h"
    apply_document_rate_kind(result, text)
    row = result.consultant_rows[0]
    assert row.rate_client == Decimal("81.37")
    assert row.rate_client_gross == Decimal("100.08")
    assert row.uncertain is False
    assert row.uncertain_reason is None
    assert result.uncertain_reasons == ["Sprawdź datę początku"]
    assert result.uncertain is True
    apply_document_rate_kind(result, text)
    assert row.rate_client == Decimal("81.37")


def test_each_person_rate_is_checked_separately():
    result = extraction()
    result.consultant_rows.append(
        ConsultantOrderRow(
            consultant_name="Anna Nowak",
            rate_client=Decimal("200.00"),
            rate_unit="hour",
            uncertain=False,
        )
    )
    text = (
        "Konrada Korcza: stawka 100,08 zł brutto za godzinę świadczenia usług.\n"
        "Anna Nowak: stawka 200,00 zł netto za godzinę świadczenia usług."
    )
    apply_document_rate_kind(result, text)
    assert [row.rate_client for row in result.consultant_rows] == [
        Decimal("81.37"),
        Decimal("200.00"),
    ]
    assert result.consultant_rows[1].rate_client_gross is None


@pytest.mark.parametrize("label", ["netto", "", "netto brutto"])
def test_pfron_client_identity_never_causes_gross_conversion(label):
    result = OrderExtraction(rate_client=Decimal("100.08"), rate_unit="hour")
    apply_pfron_order_policy(result, f"Stawka 100,08 PLN {label}")
    assert result.rate_client == Decimal("100.08")
    assert result.rate_client_gross is None
    if label != "netto":
        assert result.uncertain is True


def test_unrelated_vat_uncertainty_is_preserved():
    result = extraction(
        uncertain=True, uncertain_reasons=["Nieczytelny numer VAT klienta"]
    )
    apply_document_rate_kind(result, "Stawka 100,08 PLN brutto")
    assert result.uncertain_reasons == ["Nieczytelny numer VAT klienta"]


@pytest.mark.parametrize(
    "kind,expected", [("BRUTTO", "81.37"), ("NETTO", "100.08"), ("", "100.08")]
)
def test_deterministic_rate_check_also_uses_document_marking(kind, expected):
    rows = erste_extract_rows(
        "Dane kontraktora Jan Testowy Zlecenie od 2031-04-01 Zlecenie do 2031-04-30\n"
        f"Wartość zlecenia 20 dni roboczych x 100,08 PLN {kind}"
    )
    assert rows[0].rate_client == Decimal(expected)
    assert rows[0].uncertain is (not kind)


@pytest.mark.asyncio
async def test_full_current_roster_and_net_rate_reach_plan():
    db = AsyncMock()
    db.execute.return_value = Mock(
        all=Mock(
            return_value=[
                (
                    7,
                    "Konrad",
                    "Korcz",
                    70,
                    "ended",
                    date(2020, 1, 1),
                    date(2020, 12, 31),
                ),
            ]
        )
    )
    roster = await load_roster(db, 99)
    query = db.execute.call_args.args[0]
    # No status/date window or page limit may remove an existing client person.
    where = str(query.whereclause)
    assert "client_id" in where
    assert "status" not in where and "end_date" not in where
    assert query._limit_clause is None
    result = extraction()
    apply_document_rate_kind(result, "Stawka brutto za jedną Roboczogodzinę: 100,08 zł")
    plan = plan_document(
        client_id=99,
        extraction=result,
        resolved=resolve_rows(result.consultant_rows, roster),
        existing_orders_by_contract={},
        is_group_client=False,
        today=date(2031, 3, 1),
    )
    assert plan.rows[0].action == "new"
    assert plan.rows[0].candidate_id == 7
    assert plan.rows[0].contract_id == 70
    assert plan.rows[0].rate_client == "81.37"
    assert plan.order_number == "ZAP/2031/42"
