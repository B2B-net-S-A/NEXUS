"""Regresje ticketu PFRON: pola źródłowe, aktywny klient i przeliczenie kolejki."""

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import order_mail_ingest as svc
from app.services.order_client_identity import ClientIdentification
from app.services.order_document_text import OrderDocumentText
from app.services.order_mail_gate import evaluate
from app.services.order_pdf_parser import (
    ConsultantOrderRow,
    OrderExtraction,
    apply_document_rate_kind,
    apply_pfron_order_policy,
    pfron_end_date,
    pfron_order_number,
)
from app.services.order_policies import PolicyContext, active_policies, apply_policies
from tests.test_order_mail_gate_and_planner import _gate_input

FILENAME = "Zlecenie nr 34 Michał Chwedorczuk pk-sig.pdf"
TEXT = """ZLECENIE NA USŁUGI OUTSOURCING SPECJALISTÓW IT
na podstawie Umowy nr 2026/000008/PZP z dnia 22.04.2026
w związku z Zapotrzebowaniem Nr 1
Imię i nazwisko: Michał Chwedorczuk
Stawka za jedną Roboczogodzinę (zgodna z Ofertą Wykonawcy): 98,40 zł brutto
Data rozpoczęcia wykonywania Prac przez Specjalistę: 01.09.2026
Termin wykonania Prac 30.09.2026r. z możliwością przedłużenia do 31.12.2026.
"""


def old_extraction():
    return OrderExtraction(
        title="Zapotrzebowanie Nr 1 (Umowa nr 2026/000008/PZP)",
        start_date="2026-09-01",
        end_date="2026-12-31",
        consultant_rows=[
            ConsultantOrderRow(
                consultant_name="Michał Chwedorczuk",
                end_date="2026-12-31",
                rate_client=Decimal("98.40"),
                rate_unit="hour",
            )
        ],
        uncertain=True,
        uncertain_reasons=[
            "Brak jawnego numeru zamówienia/zlecenia - użyto numeru umowy i zapotrzebowania jako tytułu",
            "Niepewny odczyt: tytuł/numer zamówienia",
            "Nie znaleziono jednej konkretnej daty zakończenia okresu usług PFRON — wpisz datę ręcznie",
        ],
        source="claude",
    )


@pytest.mark.parametrize(
    "filename,expected",
    [
        (FILENAME, "34"),
        ("ZLECENIE NR 0034.pdf", "0034"),
        ("Zlecenie nr. 34.pdf", "34"),
        ("Zlecenie_nr_34_Test.pdf", None),
        ("Umowa 2026-000008-PZP Zapotrzebowanie nr 1.pdf", None),
        ("Zlecenie nr 34 i Zlecenie nr 35.pdf", None),
        ("Zlecenie nr 34/2026.pdf", None),
        (None, None),
    ],
)
def test_order_number_only_from_unambiguous_filename(filename, expected):
    assert pfron_order_number(filename) == expected


@pytest.mark.parametrize(
    "field",
    [
        "Termin wykonania Prac 30.09.2026r.",
        "Termin wykonania Prac:\n30.09.2026 r. z możliwością przedłużenia do 31.12.2026",
        "Termin wykonania Prac: od 01.09.2026 do 30.09.2026",
        "Termin wykonania\nPrac: 2026-09-01 – 2026-09-30",
    ],
)
def test_end_date_ignores_all_other_fields_and_extension(field):
    text = f"Okres od 01.01.2026 do 31.12.2026\n{field}\nData zakończenia usług: 31.03.2027"
    assert pfron_end_date(text) == "2026-09-30"


@pytest.mark.parametrize(
    "text",
    [
        "Termin realizacji usług: od 01.09.2026 do 30.09.2026",
        "Data zakończenia realizacji usług: 30.09.2026",
        "Termin wykonania Prac: 31.09.2026",
        "Termin wykonania Prac: 30.09.2026 lub 31.12.2026",
        "Termin wykonania Prac: 30.09.2026\nTermin wykonania Prac: 31.12.2026",
        "Termin wykonania Prac: według umowy\nData podpisu: 30.09.2026",
    ],
)
def test_absent_invalid_or_ambiguous_term_clears_model_row_dates(text):
    result = apply_pfron_order_policy(old_extraction(), text, filename=FILENAME)
    assert result.end_date is None
    assert result.consultant_rows[0].end_date is None
    assert result.uncertain


def test_pfron_corrects_document_and_row_and_preserves_unrelated_warning():
    result = old_extraction()
    result.uncertain_reasons.append("Nieczytelny numer VAT klienta")
    for _ in range(2):
        apply_pfron_order_policy(result, TEXT, filename=FILENAME)
        apply_document_rate_kind(result, TEXT)
        assert result.title == "34"
        assert result.end_date == result.consultant_rows[0].end_date == "2026-09-30"
        assert result.confidence == {"title": 1.0, "end_date": 1.0}
        assert result.consultant_rows[0].rate_client == Decimal("80.00")
        assert result.uncertain_reasons == ["Nieczytelny numer VAT klienta"]


def test_filename_is_passed_only_to_pfron_policy(monkeypatch):
    result, applied = apply_policies(
        old_extraction(),
        PolicyContext(document_text=TEXT, filename=FILENAME),
        active_policies(122),
    )
    assert applied == ["PFRON"] and result.title == "34"
    other = old_extraction()
    apply_policies(other, PolicyContext(document_text=TEXT, filename=FILENAME), [])
    assert other.title.startswith("Zapotrzebowanie")
    assert other.end_date == "2026-12-31"


@pytest.mark.parametrize("method", ["marker", "sender_domain"])
def test_only_verified_pfron_identity_waives_registry_reason(method):
    inp = _gate_input(identification_method=method, policies_applied=("PFRON",))
    assert any("numeru rejestrowego" in r for r in evaluate(inp).reasons)
    confirmed = replace(inp, trusted_policy_identity="pfron")
    assert not any("numeru rejestrowego" in r for r in evaluate(confirmed).reasons)
    other = replace(confirmed, policies_applied=("Nordea",))
    assert any("numeru rejestrowego" in r for r in evaluate(other).reasons)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "active_ids,expected", [([122], 122), ([], None), ([122, 58469], None)]
)
async def test_client_resolution_is_unambiguous_and_bounded(
    monkeypatch, active_ids, expected
):
    monkeypatch.setenv("PFRON_ORDER_EXTRACTION_CLIENT_IDS", "58469")
    db = AsyncMock()
    db.execute.return_value = Mock(
        scalars=Mock(return_value=Mock(all=Mock(return_value=active_ids)))
    )
    ident = ClientIdentification(client_key="pfron", method="marker")
    assert await svc.resolve_order_client_id(db, ident) == (expected, "pfron")
    query = db.execute.call_args.args[0]
    assert {122, 58469} in [
        set(v) for v in query.compile().params.values() if isinstance(v, (list, set))
    ]
    assert "coalesce" in str(query) and "category_override" in str(query)
    assert "merged_into_client_id IS NULL" in str(query)


@pytest.mark.asyncio
async def test_refresh_pfron_reidentifies_and_reapplies_fields_without_model_or_writer(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("PFRON_ORDER_EXTRACTION_CLIENT_IDS", "58469")
    row = SimpleNamespace(
        client_id=58469,
        client_key="pfron",
        identification_method="marker",
        sender_email="orders@example.test",
        storage_path="stored.pdf",
        attachment_name=FILENAME,
        extraction=svc.extraction_to_json(old_extraction()),
    )
    doc = OrderDocumentText(TEXT, 1, False, False, None, 0.0)
    monkeypatch.setattr(
        svc.storage_service, "get_order_mail_attachment_path", lambda p: tmp_path / p
    )
    monkeypatch.setattr(svc, "extract_order_text", lambda *args: doc)
    from app.services.order_policies.known_clients import (
        build_registry_from_known_clients,
    )

    monkeypatch.setattr(
        svc,
        "build_registry_from_db",
        AsyncMock(return_value=build_registry_from_known_clients()),
    )
    db = AsyncMock()
    db.execute.return_value = Mock(
        scalars=Mock(return_value=Mock(all=Mock(return_value=[122])))
    )
    parser, planner, writer = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(svc, "parse_order_document", parser)
    monkeypatch.setattr(svc, "_plan_and_gate", planner)
    monkeypatch.setattr("app.services.order_mail_apply.apply_document", writer)
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_AUTOAPPLY_ENABLED", True)
    await svc.refresh_review_plan(db, row)
    assert row.client_id == 122
    assert row.extraction["title"] == "34"
    assert row.extraction["end_date"] == "2026-09-30"
    assert row.extraction["consultant_rows"][0]["end_date"] == "2026-09-30"
    assert not row.extraction["uncertain_reasons"]
    assert planner.call_args.args[-2:] == (122, "marker")
    parser.assert_not_called()
    writer.assert_not_called()
