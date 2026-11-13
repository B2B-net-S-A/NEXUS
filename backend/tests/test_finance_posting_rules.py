"""Dekret do Symfonii FK (E2, 0697) — reguły bez bazy.

Dopasowanie reguły (kontrahent przed kategorią, tylko aktywne), pozycje
Wn/Ma z kwot faktury, bilans, brak kontrahenta albo konta, waluta obca,
ręczna korekta (zły bilans = 422), wzór opisu i pliki eksportu (zawartość,
neutralizacja formuł). Kontrahenci, NIP-y i kwoty fikcyjne.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from app.services import finance_posting_schema as schema
from app.services.finance_ledger import posting
from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger.export_formats import (
    COLUMNS,
    FORMATS,
    ExportRow,
    NeutralCsv,
    NeutralXlsx,
)

NOW = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)
PLAN = {
    "402-203": posting.AccountView("402-203", "Usługi obce — kontraktorzy", "cost", True),
    "402-202": posting.AccountView("402-202", "Usługi obce", "cost", True),
    "409-906": posting.AccountView("409-906", "Pozostałe koszty", "cost", True),
    "409-998": posting.AccountView("409-998", "Pozostałe koszty", "cost", False),
    "221": posting.AccountView("221", "VAT naliczony", "vat", True),
}


def _rule(**overrides) -> posting.RuleView:
    values = {
        "id": 1,
        "category": "contractor",
        "counterparty_id": None,
        "cost_account": "402-203",
        "vat_account": "221",
        "deduction": "full",
        "register": "purchase",
        "doc_type": "FVZ",
        "service_label": "Usługi IT",
        "description_template": "{usługa} {MM}/{RRRR}",
        "active": True,
    }
    values.update(overrides)
    return posting.RuleView(**values)


def _input(**overrides) -> posting.DecreeInput:
    values = {
        "category": "contractor",
        "counterparty_id": 7,
        "counterparty_name": "Kontrahent Testowy",
        "counterparty_account": "201-2-901",
        "currency": "PLN",
        "net": Decimal("10000.00"),
        "vat": Decimal("2300.00"),
        "gross": Decimal("12300.00"),
        "invoice_number": "FV/1/10/2026",
        "period": date(2026, 10, 1),
    }
    values.update(overrides)
    return posting.DecreeInput(**values)


def _sides(decree) -> list[tuple[str, str, str, int]]:
    return [
        (item["kind"], item["account"], item["side"], item["amount"])
        for item in decree["positions"]
    ]


# ── Dopasowanie reguły ───────────────────────────────────────────────────────


def test_regula_kontrahenta_wygrywa_z_ogolna_kategorii() -> None:
    general = _rule(id=1)
    special = _rule(id=2, counterparty_id=7, cost_account="409-906")
    other_category = _rule(id=3, category="office", counterparty_id=7)
    rules = [general, special, other_category]
    assert posting.match_rule(rules, "contractor", 7) is special
    assert posting.match_rule(rules, "contractor", 8) is general
    assert posting.match_rule(rules, "contractor", None) is general
    assert posting.match_rule(rules, "office", 8) is None


def test_wylaczona_regula_nie_dziala() -> None:
    rules = [_rule(id=1), _rule(id=2, counterparty_id=7, active=False)]
    assert posting.match_rule(rules, "contractor", 7).id == 1
    assert posting.match_rule([_rule(active=False)], "contractor", None) is None


# ── Wyliczenie ───────────────────────────────────────────────────────────────


def test_domyslny_dekret_kontraktora_jak_w_ebi24() -> None:
    decree = posting.compute(_input(), [_rule()], PLAN, now=NOW)
    assert decree["problems"] == []
    assert (decree["register"], decree["doc_type"]) == ("purchase", "FVZ")
    assert decree["description"] == "Usługi IT 10/2026"
    assert _sides(decree) == [
        ("cost", "402-203", "debit", 1_000_000),
        ("vat", "221", "debit", 230_000),
        ("counterparty", "201-2-901", "credit", 1_230_000),
    ]
    assert decree["positions"][0]["vat_rate"] == "23"
    assert posting.check(decree, PLAN) == []


def test_bez_odliczenia_vat_brutto_w_koszt() -> None:
    decree = posting.compute(
        _input(), [_rule(deduction="none", vat_account=None)], PLAN, now=NOW
    )
    assert _sides(decree) == [
        ("cost", "402-203", "debit", 1_230_000),
        ("counterparty", "201-2-901", "credit", 1_230_000),
    ]
    assert decree["positions"][0]["deduction"] == "none"
    assert posting.check(decree, PLAN) == []


def test_korekta_odwraca_strony() -> None:
    decree = posting.compute(
        _input(
            net=Decimal("-100.00"), vat=Decimal("-23.00"), gross=Decimal("-123.00")
        ),
        [_rule()],
        PLAN,
        now=NOW,
    )
    assert _sides(decree) == [
        ("cost", "402-203", "credit", 10_000),
        ("vat", "221", "credit", 2_300),
        ("counterparty", "201-2-901", "debit", 12_300),
    ]
    assert posting.check(decree, PLAN) == []


def test_brak_vat_na_fakturze_wylicza_sie_z_brutto() -> None:
    decree = posting.compute(_input(vat=None), [_rule()], PLAN, now=NOW)
    assert _sides(decree)[1] == ("vat", "221", "debit", 230_000)
    zero = posting.compute(
        _input(vat=Decimal("0"), gross=Decimal("10000.00")), [_rule()], PLAN, now=NOW
    )
    assert [item["kind"] for item in zero["positions"]] == ["cost", "counterparty"]


def test_brak_konta_kontrahenta_blokuje() -> None:
    decree = posting.compute(_input(counterparty_account=None), [_rule()], PLAN, now=NOW)
    issues = posting.check(decree, PLAN)
    assert len(issues) == 1
    assert "nie ma konta rozrachunkowego" in issues[0]
    assert "Kontrahent Testowy" in issues[0]


def test_brak_kontrahenta_w_kartotece_blokuje() -> None:
    decree = posting.compute(
        _input(counterparty_id=None, counterparty_account=None), [_rule()], PLAN, now=NOW
    )
    assert posting.check(decree, PLAN) == [posting.NO_COUNTERPARTY]


def test_brak_reguly_blokuje() -> None:
    decree = posting.compute(_input(category="benefit"), [_rule()], PLAN, now=NOW)
    issues = posting.check(decree, PLAN)
    assert decree["positions"] == []
    assert issues and "Benefity" in issues[0]


def test_waluta_obca_wymaga_recznego_dekretu() -> None:
    decree = posting.compute(_input(currency="EUR"), [_rule()], PLAN, now=NOW)
    assert any("EUR" in issue for issue in posting.check(decree, PLAN))


def test_brak_kwot_netto_i_vat() -> None:
    decree = posting.compute(_input(net=None, vat=None), [_rule()], PLAN, now=NOW)
    assert posting.NO_AMOUNTS in posting.check(decree, PLAN)


def test_wylaczone_konto_z_reguly_blokuje() -> None:
    decree = posting.compute(_input(), [_rule(cost_account="409-998")], PLAN, now=NOW)
    assert any("409-998" in issue for issue in posting.check(decree, PLAN))


def test_niezbilansowany_dekret_to_blad_kontroli() -> None:
    decree = posting.compute(
        _input(gross=Decimal("12300.01")), [_rule()], PLAN, now=NOW
    )
    issues = posting.check(decree, PLAN)
    assert issues == ["Suma Wn (12 300,00 zł) różni się od sumy Ma (12 300,01 zł)."]


def test_brak_dekretu() -> None:
    assert posting.check(None, PLAN) == [posting.NOT_COMPUTED]


@pytest.mark.parametrize(
    ("net", "vat", "rate"),
    [
        ("100", "23", "23"),
        ("100", "8", "8"),
        ("100", "5", "5"),
        ("100", "0", "0"),
        ("100", "12", None),
        ("0", "0", None),
    ],
)
def test_stawka_vat_z_sum(net: str, vat: str, rate) -> None:
    assert posting.vat_rate(Decimal(net), Decimal(vat)) == rate


# ── Ręczna korekta ───────────────────────────────────────────────────────────


def _manual(positions, **overrides):
    body = {
        "register": "purchase",
        "doc_type": "fvz",
        "description": "  Usługi   IT 10/2026 ",
        "positions": positions,
    }
    body.update(overrides)
    return posting.manual_decree(body, PLAN, previous={"rule_id": 3}, now=NOW)


def test_reczny_dekret_zbilansowany() -> None:
    decree = _manual(
        [
            {"kind": "cost", "account": "402-202", "side": "debit", "amount": "600.00"},
            {"kind": "cost", "account": "409-906", "side": "debit", "amount": "400.00"},
            {"kind": "vat", "account": "221", "side": "debit", "amount": "230.00"},
            {
                "kind": "counterparty",
                "account": "201-2-901",
                "side": "credit",
                "amount": "1230.00",
            },
        ]
    )
    assert decree["manual"] is True and decree["rule_id"] == 3
    assert decree["doc_type"] == "FVZ"
    assert decree["description"] == "Usługi IT 10/2026"
    assert posting.check(decree, PLAN) == []


def test_reczny_dekret_bez_bilansu_to_422() -> None:
    with pytest.raises(LedgerError) as error:
        _manual(
            [
                {"kind": "cost", "account": "402-202", "side": "debit", "amount": "100"},
                {
                    "kind": "counterparty",
                    "account": "201-2-901",
                    "side": "credit",
                    "amount": "99.99",
                },
            ]
        )
    assert error.value.status == 422
    assert "Suma Wn (100,00 zł) różni się od sumy Ma (99,99 zł)" in error.value.message


@pytest.mark.parametrize(
    ("position", "fragment"),
    [
        ({"kind": "cost", "account": "999", "side": "debit", "amount": "1"}, "999"),
        ({"kind": "vat", "account": "402-202", "side": "debit", "amount": "1"}, "rodzaj"),
        ({"kind": "cost", "account": "=1+1", "side": "debit", "amount": "1"}, "niepoprawny"),
        ({"kind": "cost", "account": "402-202", "side": "debit", "amount": "0"}, "zera"),
        ({"kind": "cost", "account": "402-202", "side": "debit", "amount": "1.001"}, "dwa"),
    ],
)
def test_reczny_dekret_zle_pozycje(position, fragment: str) -> None:
    with pytest.raises(LedgerError) as error:
        _manual([position])
    assert error.value.status == 422
    assert fragment in error.value.message


# ── Opis ─────────────────────────────────────────────────────────────────────


def test_wzor_opisu() -> None:
    assert (
        posting.render_description(
            "{usługa} {MM}/{RRRR} — {numer}",
            service="Usługi IT",
            period=date(2026, 9, 1),
            number="FV/9",
            counterparty=None,
        )
        == "Usługi IT 09/2026 — FV/9"
    )
    assert posting.validate_template(" {usługa}  {MM}/{RRRR} ") == "{usługa} {MM}/{RRRR}"
    with pytest.raises(LedgerError) as error:
        posting.validate_template("{usluga} {MM}")
    assert error.value.status == 422 and "{usluga}" in error.value.message


# ── Schemat ──────────────────────────────────────────────────────────────────


def test_zasiew_tylko_kontami_wzorcowymi_i_regula_kontraktora() -> None:
    numbers = {number for number, _, _ in schema.SEED_ACCOUNTS}
    assert {"402-203", "221", "222", "202-2-10", "701-10-1"} <= numbers
    # Konta analityczne kontrahentów (201-2-NNN, 200-2-NNN) są w kartotece.
    assert not any(number.startswith(("201-", "200-", "203-")) for number in numbers)
    seed = " ".join(schema.DATA_DDL)
    assert "'contractor', '402-203', '221', 'full', 'purchase', 'FVZ'" in seed
    assert "WHERE NOT EXISTS" in seed


def test_nowe_akcje_historii_i_check_tylko_raz() -> None:
    assert {"decree", "export", "unexport", "book"} <= set(schema.EVENT_ACTIONS)
    assert "LIKE '%unexport%'" in schema.CONSTRAINT_DDL[0]


# ── Pliki eksportu ───────────────────────────────────────────────────────────


def _row(**overrides) -> ExportRow:
    values = {
        "register": "Zakup",
        "doc_type": "FVZ",
        "invoice_number": "=HYPERLINK(\"http://zly.example\")",
        "ksef_number": "1234567890-20261105-ABCDEF-AB",
        "issue_date": date(2026, 11, 4),
        "received_date": date(2026, 11, 5),
        "counterparty": "@Kontrahent Testowy",
        "nip": "1234567890",
        "symfonia_id": "+SYM-1",
        "account": "402-203",
        "debit": Decimal("10000.00"),
        "credit": None,
        "description": "-Usługi IT 10/2026",
        "vat_rate": "23",
        "deduction": "100%",
    }
    values.update(overrides)
    return ExportRow(**values)


def test_formaty_sa_w_rejestrze_po_kluczu() -> None:
    assert set(FORMATS) == {"neutral_xlsx", "neutral_csv"}
    for key, fmt in FORMATS.items():
        assert fmt.key == key and fmt.extension and fmt.media_type


def test_xlsx_kolumny_kwoty_i_neutralizacja_formul() -> None:
    content = NeutralXlsx().render([_row()])
    sheet = load_workbook(io.BytesIO(content)).active
    header = [cell.value for cell in sheet[1]]
    assert header == [label for _, label in COLUMNS]
    values = dict(zip(header, [cell.value for cell in sheet[2]]))
    assert values["Numer faktury"].startswith("'=")
    assert values["Kontrahent"] == "'@Kontrahent Testowy"
    assert values["ID Symfonii kontrahenta"] == "'+SYM-1"
    assert values["Opis"] == "'-Usługi IT 10/2026"
    assert values["Wn"] == 10000 and values["Ma"] is None
    assert values["Konto"] == "402-203"
    assert sheet.cell(row=2, column=1).data_type != "f"
    assert all(cell.data_type != "f" for cell in sheet[2])


def test_csv_srednik_bom_przecinek_i_neutralizacja() -> None:
    content = NeutralCsv().render([_row(), _row(debit=None, credit=Decimal("12300.5"))])
    assert content.startswith("﻿".encode())
    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig")), delimiter=";"))
    header = rows[0]
    first = dict(zip(header, rows[1]))
    second = dict(zip(header, rows[2]))
    assert first["Numer faktury"].startswith("'=")
    assert first["Wn"] == "10000,00" and first["Ma"] == ""
    assert second["Ma"] == "12300,50"
    assert first["Data wystawienia"] == "2026-11-04"
    assert first["Kontrahent"] == "'@Kontrahent Testowy"
