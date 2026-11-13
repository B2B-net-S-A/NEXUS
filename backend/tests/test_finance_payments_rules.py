"""Przelewy faktur kosztowych (0696, E3) — reguły bez bazy.

Tryb przelewu i progi MPP, tytuł przed i po 1.01.2027 (data wstrzykiwana),
format MPP, biała lista (próg odhaczenia), rachunki (NRB, IBAN), dopasowanie
obciążenia z wyciągu (dokładne, częściowe, MPP, niejednoznaczne), plik Elixir
z klasyfikacją MPP i CSV bez formuł. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.finance_ledger import FinanceCostEntry
from app.models.finance_payments import FinancePaymentBatchItem
from app.services.client_settlements import contractor_details
from app.services.finance_ledger import payment_rules as rules
from app.services.finance_ledger import payments
from app.services.finance_payments_schema import ALL_DDL, DOWNGRADE_DDL
from app.services.hr.bank import elixir
from app.services.hr.bank.accounts import iban_check_digits
from app.services.hr.bank.parsed import StatementLine
from app.services.hr.ksef import fa
from app.services.hr_schema_bundle import COLUMN_DDL

BEFORE = date(2026, 12, 31)
AFTER = date(2027, 1, 1)
NIP = "1234563218"
KSEF = f"{NIP}-20261105-0A1B2C3D4E5F-AB"


def _nrb(seed: int) -> str:
    bban = f"10900000{seed:016d}"
    return iban_check_digits(bban) + bban


SUPPLIER = _nrb(4242)
OTHER = _nrb(5151)


# ── Tryb ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("flags", "gross", "currency", "expected"),
    [
        ([], "14999.99", "PLN", ("standard", False)),
        ([], "15000.00", "PLN", ("mpp", True)),
        (["no_mpp"], "90000.00", "PLN", ("standard", False)),
        (["mpp"], "100.00", "PLN", ("mpp", False)),
        (["tax_office_account", "mpp"], "100.00", "PLN", ("tax_office", False)),
        ([], "90000.00", "EUR", ("standard", False)),
    ],
)
def test_tryb_z_flag_i_progu(flags, gross, currency, expected) -> None:
    mode = rules.mode_for(flags, Decimal(gross), currency)
    assert (mode.mode, mode.suggested) == expected


def test_mpp_w_walucie_obcej_blokuje() -> None:
    with pytest.raises(rules.PaymentRuleError) as exc:
        rules.mode_for(["mpp"], Decimal("100"), "EUR")
    assert exc.value.code == "mpp_currency"


# ── Tytuł ────────────────────────────────────────────────────────────────────


def _title(**kwargs):
    base = {
        "mode": "standard",
        "invoice_number": "FV/7/11/2026",
        "ksef_number": KSEF,
        "from_ksef": True,
        "vat_amount": Decimal("2300.00"),
        "seller_nip": NIP,
        "today": BEFORE,
    }
    return rules.title_lines(**{**base, **kwargs})


def test_tytul_numer_faktury_i_ksef_w_osobnych_liniach() -> None:
    assert _title() == ["FV/7/11/2026", KSEF]
    assert all(len(line) <= 35 for line in _title())


def test_brak_numeru_ksef_przed_2027_przechodzi_po_2027_blokuje() -> None:
    assert _title(ksef_number=None) == ["FV/7/11/2026"]
    with pytest.raises(rules.PaymentRuleError) as exc:
        _title(ksef_number=None, today=AFTER)
    assert exc.value.code == "no_ksef_number"
    # Faktura spoza KSeF (PDF) po 1.01.2027 bez numeru KSeF — dalej przechodzi.
    assert _title(ksef_number=None, from_ksef=False, today=AFTER) == ["FV/7/11/2026"]
    assert _title(today=AFTER) == ["FV/7/11/2026", KSEF]


def test_tytul_mpp_w_formacie_komunikatu() -> None:
    lines = _title(mode="mpp")
    assert "".join(lines) == (f"/VAT/2300,00/IDC/{NIP}/INV/FV/7/11/2026/TXT/{KSEF}")
    assert len(lines) <= 4 and all(len(line) <= 35 for line in lines)
    no_ksef = "".join(_title(mode="mpp", ksef_number=None))
    assert no_ksef.endswith("/TXT/FV/7/11/2026")


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"seller_nip": None}, "mpp_no_nip"),
        ({"vat_amount": None}, "mpp_no_vat"),
        ({"invoice_number": None}, "no_invoice_number"),
    ],
)
def test_mpp_bez_danych_blokuje(kwargs, code) -> None:
    with pytest.raises(rules.PaymentRuleError) as exc:
        _title(mode="mpp", **kwargs)
    assert exc.value.code == code


def test_tytul_bez_znakow_psujacych_plik() -> None:
    assert _title(invoice_number='FV|7"\n2026', ksef_number=None) == ["FV 7 2026"]


# ── Biała lista i art. 105a ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("gross", "state", "mode", "currency", "expected"),
    [
        ("15000.01", "not_listed", "standard", "PLN", True),
        ("15000.01", "off", "standard", "PLN", True),
        ("15000.01", "unchecked", "mpp", "PLN", True),
        ("15000.00", "not_listed", "standard", "PLN", False),
        ("90000.00", "listed", "standard", "PLN", False),
        ("90000.00", "not_listed", "tax_office", "PLN", False),
        ("90000.00", "foreign", "standard", "EUR", False),
    ],
)
def test_odhaczenie_bialej_listy_powyzej_15000(
    gross, state, mode, currency, expected
) -> None:
    assert (
        rules.needs_white_list_ack(
            mode=mode, currency=currency, gross=Decimal(gross), white_list_state=state
        )
        is expected
    )


def test_art_105a_podpowiedz_tylko_ponizej_progu_i_bez_mpp() -> None:
    hint = rules.art_105a_hint
    big = Decimal("50000.01")
    assert hint(mode="standard", gross=Decimal("9000"), currency="PLN", month_net=big)
    assert not hint(
        mode="standard",
        gross=Decimal("9000"),
        currency="PLN",
        month_net=Decimal("50000"),
    )
    assert not hint(mode="mpp", gross=Decimal("9000"), currency="PLN", month_net=big)
    assert not hint(
        mode="standard", gross=Decimal("15000"), currency="PLN", month_net=big
    )


# ── Rachunek ─────────────────────────────────────────────────────────────────


def test_rachunek_krajowy_i_zagraniczny() -> None:
    spaced = "PL" + " ".join(SUPPLIER[i : i + 4] for i in range(0, 26, 4))
    assert rules.normalize_account(spaced) == SUPPLIER
    assert rules.is_domestic(SUPPLIER)
    assert rules.normalize_account("de89 3704 0044 0532 0130 00") == (
        "DE89370400440532013000"
    )
    assert not rules.is_domestic("DE89370400440532013000")
    for bad in ("PL" + SUPPLIER[:-1] + "0", "DE00370400440532013000", "abc"):
        with pytest.raises(rules.PaymentRuleError) as exc:
            rules.normalize_account(bad)
        assert exc.value.code == "bad_account"


# ── Obciążenie z wyciągu ─────────────────────────────────────────────────────


def _line(amount: str, title: str, account: str | None = None, currency="PLN"):
    return StatementLine(
        index=1,
        booked_on=date(2026, 11, 20),
        amount=Decimal(amount),
        direction="debit",
        currency=currency,
        title=title,
        counterparty_account=account,
        bank_ref="R1",
    )


def _cand(entry_id: int, gross: str, **kwargs) -> rules.CostCandidate:
    base = {
        "currency": "PLN",
        "gross": Decimal(gross),
        "paid": Decimal("0"),
        "invoice_number": f"FV/{entry_id}/11/2026",
        "ksef_number": None,
    }
    return rules.CostCandidate(entry_id=entry_id, **{**base, **kwargs})


def test_wyciag_numer_ksef_dokladnie_czesciowo_i_za_duzo() -> None:
    found = _cand(1, "1230.00", ksef_number=KSEF)
    exact = rules.decide_debit(_line("1230.00", f"Zaplata {KSEF}"), [found])
    assert (exact.entry_id, exact.reason, exact.amount) == (
        1,
        "ksef",
        Decimal("1230.00"),
    )
    part = rules.decide_debit(_line("230.00", KSEF), [found])
    assert (part.entry_id, part.partial) == (1, True)
    over = rules.decide_debit(_line("2000.00", KSEF), [found])
    assert (over.entry_id, over.reason, over.candidates) == (
        None,
        "amount_exceeds",
        (1,),
    )
    paid = rules.decide_debit(
        _line("1230.00", KSEF),
        [_cand(1, "1230.00", ksef_number=KSEF, paid=Decimal("1230"))],
    )
    assert paid.reason == "already_paid"


def test_wyciag_mpp_netto_plus_vat_z_tytulu() -> None:
    found = _cand(1, "1230.00", ksef_number=KSEF)
    line = _line("1000.00", f"/VAT/230,00/IDC/{NIP}/INV/FV/1/11/2026/TXT/{KSEF}")
    decision = rules.decide_debit(line, [found])
    assert (decision.entry_id, decision.amount) == (1, Decimal("1230.00"))


def test_ten_sam_numer_faktury_u_dwoch_dostawcow_rozstrzyga_rachunek() -> None:
    first = _cand(
        1, "500.00", invoice_number="1/11/2026", accounts=frozenset({SUPPLIER})
    )
    second = _cand(2, "500.00", invoice_number="1/11/2026", accounts=frozenset({OTHER}))
    blind = rules.decide_debit(_line("500.00", "Faktura 1/11/2026"), [first, second])
    assert (blind.entry_id, blind.reason, set(blind.candidates)) == (
        None,
        "ambiguous",
        {1, 2},
    )
    by_account = rules.decide_debit(
        _line("500.00", "Faktura 1/11/2026", OTHER), [first, second]
    )
    assert by_account.entry_id == 2
    # Częściowa zapłata po samym numerze faktury — tylko z potwierdzonym rachunkiem.
    partial = rules.decide_debit(_line("100.00", "Faktura 1/11/2026"), [first])
    assert (partial.entry_id, partial.reason) == (None, "amount_differs")
    confirmed = rules.decide_debit(
        _line("100.00", "Faktura 1/11/2026", SUPPLIER), [first]
    )
    assert (confirmed.entry_id, confirmed.partial) == (1, True)


def test_pozycja_paczki_po_rachunku_i_kwocie() -> None:
    batched = _cand(
        3,
        "800.00",
        invoice_number=None,
        batch_amount=Decimal("800.00"),
        batch_account=SUPPLIER,
    )
    hit = rules.decide_debit(_line("800.00", "przelew", SUPPLIER), [batched])
    assert (hit.entry_id, hit.reason) == (3, "batch")
    assert not rules.decide_debit(_line("800.00", "przelew", OTHER), [batched]).related
    assert not rules.decide_debit(
        _line("799.00", "przelew", SUPPLIER), [batched]
    ).related


def test_waluta_inna_niz_faktury() -> None:
    found = _cand(1, "100.00", ksef_number=KSEF, currency="EUR")
    decision = rules.decide_debit(_line("100.00", KSEF), [found])
    assert decision.reason == "currency_differs"


# ── Plik ─────────────────────────────────────────────────────────────────────


def test_elixir_klasyfikacja_mpp_53_zwykly_51() -> None:
    sender = elixir.Sender(name="Spółka Przykładowa", account=_nrb(1))
    base = {
        "recipient_name": "Dostawca",
        "recipient_account": SUPPLIER,
        "amount": Decimal("1230.00"),
        "title_lines": ("FV/7/11/2026",),
        "execution_date": date(2026, 11, 20),
    }
    plain = elixir.elixir_line(elixir.TransferRow(**base), sender)
    mpp = elixir.elixir_line(
        elixir.TransferRow(**base, classification=elixir.CLASSIFICATION_MPP), sender
    )
    assert plain.endswith('"51"') and mpp.endswith('"53"')


def test_csv_neutralizuje_formuly() -> None:
    item = FinancePaymentBatchItem(
        account=SUPPLIER,
        recipient_name='=HYPERLINK("http://example.com")',
        amount=Decimal("1230.00"),
        vat_amount=Decimal("230.00"),
        currency="PLN",
        mode="mpp",
        title_lines=["@SUM(1)"],
    )
    entry = FinanceCostEntry(seller_nip=NIP)
    content = payments.render_csv([(item, entry)], date(2026, 11, 20)).decode("utf-8")
    assert "'=HYPERLINK" in content
    assert "'@SUM(1)" in content
    assert "1230,00" in content and "230,00" in content


def test_ddl_w_lustrze_entrypointu_i_downgrade() -> None:
    for stmt in ALL_DDL:
        if stmt.startswith("CREATE TABLE"):
            assert stmt in COLUMN_DDL
    assert len(DOWNGRADE_DDL) == 7
    assert DOWNGRADE_DDL[0].startswith("DELETE FROM finance_cost_entry_events")


def test_rachunek_z_xml_faktury_kontraktora_trafia_do_details() -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Faktura xmlns="http://crd.gov.pl/wzor/2025/06/25/13775/">'
        "<Naglowek><KodFormularza>FA</KodFormularza>"
        "<WariantFormularza>3</WariantFormularza></Naglowek>"
        f"<Podmiot1><DaneIdentyfikacyjne><NIP>{NIP}</NIP>"
        "<Nazwa>Konsultant Przykładowy</Nazwa></DaneIdentyfikacyjne></Podmiot1>"
        "<Fa><KodWaluty>PLN</KodWaluty><P_1>2026-11-03</P_1><P_2>FV 1/11/2026</P_2>"
        "<P_13_1>100.00</P_13_1><P_14_1>23.00</P_14_1><P_15>123.00</P_15>"
        "<RodzajFaktury>VAT</RodzajFaktury>"
        f"<Platnosc><RachunekBankowy><NrRB>{SUPPLIER}</NrRB></RachunekBankowy>"
        f"<RachunekBankowy><NrRB>{SUPPLIER}</NrRB></RachunekBankowy></Platnosc>"
        "</Fa></Faktura>"
    ).encode()
    parsed = fa.parse_invoice(xml)
    assert parsed.accounts == (SUPPLIER,)
    assert contractor_details.details_from(parsed)["accounts"] == [SUPPLIER]


def test_rachunek_faktora_z_xml_obok_rachunku_sprzedawcy() -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Faktura xmlns="http://crd.gov.pl/wzor/2025/06/25/13775/">'
        "<Naglowek><KodFormularza>FA</KodFormularza>"
        "<WariantFormularza>3</WariantFormularza></Naglowek>"
        f"<Podmiot1><DaneIdentyfikacyjne><NIP>{NIP}</NIP>"
        "<Nazwa>Konsultant Przykładowy</Nazwa></DaneIdentyfikacyjne></Podmiot1>"
        "<Fa><KodWaluty>PLN</KodWaluty><P_1>2026-11-03</P_1><P_2>FV 2/11/2026</P_2>"
        "<P_13_1>100.00</P_13_1><P_14_1>23.00</P_14_1><P_15>123.00</P_15>"
        "<RodzajFaktury>VAT</RodzajFaktury>"
        f"<Platnosc><RachunekBankowy><NrRB>{SUPPLIER}</NrRB></RachunekBankowy>"
        f"<RachunekBankowyFaktora><NrRB>{OTHER}</NrRB></RachunekBankowyFaktora>"
        "</Platnosc></Fa></Faktura>"
    ).encode()
    parsed = fa.parse_invoice(xml)
    assert parsed.accounts == (SUPPLIER,)
    assert parsed.factor_accounts == (OTHER,)
    details = contractor_details.details_from(parsed)
    assert details["accounts"] == [SUPPLIER]
    assert details["factor_accounts"] == [OTHER]
