"""Shared identity normalization and independent PDF evidence regressions."""

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.order_mail_gate import evaluate
from app.services.order_mail_resolver import RosterContract, RosterPerson, resolve_rows
from app.services.order_pdf_parser import (
    OrderExtraction,
    pfron_extract_rows,
    apply_pfron_order_policy,
)
from app.services.order_policies.registry import policy_by_key
from tests.test_order_mail_gate_and_planner import _gate_input, _row

TEXT = """Imię i nazwisko: Krzysztof Pala – Specjalista DevOps
Stawka za jedną Roboczogodzinę (zgodna z Ofertą Wykonawcy): 147,60 zł brutto
Data rozpoczęcia wykonywania Prac przez Specjalistę: 01.09.2031
Okres realizacji Prac przez Specjalistę: 80 RBH / mies.
Termin wykonania Prac 30.09.2031r. z możliwością przedłużenia.
"""


def person(cid=1, name="Krzysztof", lastname="Pala"):
    return RosterPerson(
        cid, name, lastname, (RosterContract(cid * 10, "active", None, None),)
    )


@pytest.mark.parametrize(
    "name",
    [
        "Krzysztof Pala",
        " PALA\u00a0  krzysztof\n",
        "Krzysztof Pa\u200bla",
        "Krzysztof Pa\u00adla",
        "Krzysztof\tPala",
    ],
)
def test_reported_person_has_exact_unique_identity(name):
    resolved = resolve_rows([_row(name)], [person()])[0]
    assert resolved.match_kind == "exact" and resolved.candidate_id == 1


@pytest.mark.parametrize(
    "name", ["ZOLTANIECKI Marcin", "Marcin Żółtaniecki", "Marcin Żółtaniecki"]
)
def test_erste_uses_same_normalization(name):
    assert (
        resolve_rows([_row(name)], [person(name="Marcin", lastname="Żółtaniecki")])[
            0
        ].match_kind
        == "exact"
    )


def test_unicode_hyphen_is_equivalent_to_ascii_hyphen():
    assert (
        resolve_rows(
            [_row("Anna Nowak‑Testowa")], [person(name="Anna", lastname="NowakTestowa")]
        )[0].match_kind
        == "exact"
    )


def test_collisions_identify_records_and_remain_manual():
    resolved = resolve_rows([_row("PALA KRZYSZTOF")], [person(), person(2)])[0]
    assert resolved.match_kind == "ambiguous"
    assert resolved.candidate_id is None
    assert resolved.candidate_ids == (1, 2)
    assert "ID 1; kontrakty: 10" in resolved.reason
    assert "ID 2; kontrakty: 20" in resolved.reason
    assert not evaluate(_gate_input(resolved=(resolved,))).is_auto


@pytest.mark.parametrize(
    "name", ["Pala", "Krzysztof Pala 123", "Krzysztof Pala i Jan Nowak"]
)
def test_partial_names_or_unexplained_extra_identifiers_are_not_exact(name):
    assert resolve_rows([_row(name)], [person()])[0].match_kind != "exact"


def test_pfron_label_evidence_uses_person_and_own_rate():
    rows = policy_by_key("pfron").extract_rows(TEXT)
    assert rows[0].consultant_name == "Krzysztof Pala"
    assert rows[0].rate_client == Decimal("120.00")
    assert rows[0].rate_client_gross == Decimal("147.60")
    assert rows[0].rate_unit == "hour" and not rows[0].uncertain
    assert rows[0].end_date == "2031-09-30"
    assert len(pfron_extract_rows(TEXT + TEXT.replace("Pala", "Nowak"))) == 2


@pytest.mark.parametrize(
    "text",
    [
        TEXT.replace("Stawka za jedną", "Opłata za jedną"),
        TEXT + "Imię i nazwisko: Jan Nowak\nNieczytelna stawka",
        "Krzysztof Pala\n147,60 zł brutto",
    ],
)
def test_missing_or_incomplete_label_evidence_never_confirms_model(text):
    assert not pfron_extract_rows(text)


def test_pfron_md_quantity_warning_removed_without_hiding_other_uncertainty():
    ex = OrderExtraction(
        uncertain=True,
        uncertain_reasons=[
            "Wartość 80 RBH miesięcznie to godziny, nie roboczodni (MD) - niejednoznaczność jednostki dla pola md_total",
            "Nieczytelna stawka md_total",
            "Sprawdź datę początku",
        ],
    )
    apply_pfron_order_policy(ex, TEXT, filename="Zlecenie nr 31 Krzysztof Pala.pdf")
    assert ex.uncertain_reasons == [
        "Nieczytelna stawka md_total",
        "Sprawdź datę początku",
    ]


@pytest.mark.parametrize("change", ["name", "unit", "uncertain", "missing_rate"])
def test_equal_amount_alone_never_proves_person_row(change):
    row = _row("Jan Kowalski")
    row = replace(
        row,
        **{
            "name": {"consultant_name": "Jan Nowak"},
            "unit": {"rate_unit": "hour"},
            "uncertain": {"uncertain": True},
            "missing_rate": {"rate_client": None},
        }[change],
    )
    assert not evaluate(_gate_input(deterministic_rows=(row,))).is_auto


def test_reversed_names_still_pass_independent_evidence_gate():
    assert evaluate(
        _gate_input(deterministic_rows=(_row("KOWALSKI\u00a0jan"),))
    ).is_auto


def test_swapped_rates_or_duplicate_people_do_not_pass_gate():
    from app.services.order_mail_gate import _row_evidence_reasons

    rows = [_row("Jan Kowalski", "900"), _row("Anna Nowak", "950")]
    assert _row_evidence_reasons(
        rows, (_row("Jan Kowalski", "950"), _row("Anna Nowak", "900"))
    )
    assert _row_evidence_reasons([rows[0], rows[0]], tuple(rows))
    assert not _row_evidence_reasons(rows, tuple(reversed(rows)))


@pytest.mark.asyncio
async def test_pfron_plan_and_gate_pass_real_registered_extractor(monkeypatch):
    from app.services import order_mail_ingest as svc
    from app.services.order_document_text import OrderDocumentText
    from app.services.order_policies import active_policies

    rows = [_row("PALA Krzysztof", "120", "hour", "2031-09-01", "2031-09-30")]
    extraction = OrderExtraction(
        consultant_rows=rows,
        source="claude",
        uncertain=False,
        start_date="2031-09-01",
        end_date="2031-09-30",
    )
    apply_pfron_order_policy(
        extraction, TEXT, filename="Zlecenie nr 31 Krzysztof Pala.pdf"
    )
    db = AsyncMock()
    db.execute.return_value = Mock(
        scalars=Mock(return_value=Mock(all=Mock(return_value=[])))
    )
    monkeypatch.setattr(svc, "load_roster", AsyncMock(return_value=[person()]))
    row = SimpleNamespace()
    await svc._plan_and_gate(
        db,
        row,
        extraction,
        OrderDocumentText(TEXT, 1, False, False, None, 0.0),
        active_policies(122),
        122,
        "marker",
    )
    assert row.gate_verdict == "auto", row.gate_reasons
    assert row.gate_reasons == []
    assert row.proposal["resolved"][0]["match_kind"] == "exact"
    assert row.proposal["rows"][0]["candidate_id"] == 1


@pytest.mark.parametrize("marking", ["", "netto brutto", "brutto netto"])
def test_missing_or_conflicting_vat_marking_requires_review(marking):
    rows = pfron_extract_rows(TEXT.replace("brutto", marking))
    assert rows[0].uncertain
