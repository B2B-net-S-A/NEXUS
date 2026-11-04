"""Rozliczenia — formaty plików płatności (R9): rachunek, tytuły, Elixir-O, CSV,
wyciągi MT940 i CAMT.053. Testy bez bazy.

Wszystkie rachunki, NIP-y i numery KSeF są fikcyjne (poprawne sumy kontrolne,
numery banków 9999xxxx, których nie ma w Polsce).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.hr.bank import accounts, camt053, elixir, mt940, titles
from app.services.hr.bank.parsed import StatementError

DATA = Path(__file__).parent / "data" / "bank"
COMPANY = "72999900010000000000001234"
OLA = "53999900020000000000004521"
KUBA = "87999900030000000000000937"
OFFICE = "70999900040000000000007777"
KSEF = "1234563218-20261104-5F2A9C0D71B3-4E"


# ── Rachunek ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        f"PL{OLA}",
        OLA,
        "PL53 9999 0002 0000 0000 0000 4521",
        "53-9999-0002-0000-0000-0000-4521",
    ],
)
def test_account_accepts_iban_and_nrb_spellings(raw):
    assert accounts.normalize_nrb(raw) == OLA


@pytest.mark.parametrize(
    "raw",
    [
        "PL53999900020000000000004522",  # zła suma kontrolna
        "5399990002000000000000452",  # 25 cyfr
        "DE89370400440532013000",  # rachunek zagraniczny
        "",
        None,
    ],
)
def test_account_refuses_wrong_numbers_without_echoing_them(raw):
    with pytest.raises(accounts.AccountError) as error:
        accounts.normalize_nrb(raw)
    assert "4522" not in str(error.value)


def test_account_parts_from_mt940_fields_get_check_digits():
    assert accounts.nrb_from_parts("99990002", "0000000000004521") == OLA
    assert accounts.nrb_from_parts("", OLA) == OLA
    assert accounts.nrb_from_parts("99990002", "123") is None


def test_account_helpers():
    assert accounts.last4(OLA) == "4521"
    assert accounts.bank_sort_code(OLA) == "99990002"
    assert accounts.masked(OLA) == "•• 4521"
    assert accounts.grouped_iban(OLA).startswith("PL53 9999 0002")


# ── Tytuły ────────────────────────────────────────────────────────────────────


def test_title_for_ksef_invoice_keeps_ksef_number_in_one_line():
    lines = titles.title_lines("b2b", 2026, 10, [titles.InvoiceRef("FV 10/2026", KSEF)])
    assert lines == ["FV 10/2026", KSEF]
    assert all(len(line) <= titles.LINE_LENGTH for line in lines)


def test_title_for_mandate_and_employment_contract():
    assert (
        titles.transfer_title("zlecenie", 2026, 10) == "Wynagrodzenie zlecenie 10/2026"
    )
    assert titles.transfer_title("uop", 2026, 3) == "Wynagrodzenie 03/2026"


def test_title_strips_characters_that_break_the_batch_file():
    lines = titles.title_lines(
        "b2b", 2026, 10, [titles.InvoiceRef('FV "1"|10/2026\n', None)]
    )
    assert lines == ["FV 1 10/2026"]


def test_ksef_numbers_found_in_bank_titles():
    text = f"Zapłata fv 10/2026 {KSEF.lower()} oraz {KSEF}"
    assert titles.ksef_numbers_in(text) == [KSEF]
    assert titles.ksef_numbers_in("FV 10/2026 bez numeru") == []


# ── Elixir-O i CSV ────────────────────────────────────────────────────────────


def _row(**changes):
    values = {
        "recipient_name": "Nowak Recruitment Ola Nowak",
        "recipient_account": OLA,
        "amount": Decimal("21106.80"),
        "title_lines": ("FV 10/2026", KSEF),
        "execution_date": date(2026, 11, 18),
    }
    values.update(changes)
    return elixir.TransferRow(**values)


SENDER = elixir.Sender(
    name="Spółka Przykładowa S.A. ul. Testowa 1 00-001 Warszawa", account=COMPANY
)


def test_elixir_line_has_pli_layout():
    line = elixir.elixir_line(_row(), SENDER)
    fields = line.split(",")
    assert fields[:5] == ["110", "20261118", "2110680", "99990001", "0"]
    assert fields[5] == f'"{COMPANY}"' and fields[6] == f'"{OLA}"'
    assert fields[9] == "0" and fields[10] == "99990002"
    assert f'"FV 10/2026|{KSEF}"' in line
    assert line.endswith('"",""' + ',"51"')
    # Nazwa nadawcy pocięta na linie po 35 znaków, bez przecinków w polach liczbowych.
    sender_field = line.split('"')[5]
    assert all(len(part) <= 35 for part in sender_field.split("|"))


def test_elixir_file_is_windows_1250_with_crlf():
    content = elixir.render_elixir([_row(), _row(amount=Decimal("1.05"))], SENDER)
    text = content.decode("windows-1250")
    assert text.count("\r\n") == 2
    assert "Spółka" in text
    assert ",105," in text


def test_elixir_amount_in_grosze_rounds_to_cents():
    assert elixir.grosze(Decimal("0.01")) == 1
    assert elixir.grosze(Decimal("17160.00")) == 1716000


def test_csv_batch_is_excel_friendly_and_safe():
    content = elixir.render_csv([_row(recipient_name="=HYPERLINK(1)")])
    text = content.decode("utf-8")
    assert text.startswith("﻿Rachunek odbiorcy;")
    assert "21106,80" in text
    assert "'=HYPERLINK(1)" in text
    assert "PL53 9999 0002" in text


# ── MT940 ─────────────────────────────────────────────────────────────────────


def test_mt940_reads_polish_bank_statement():
    parsed = mt940.parse((DATA / "mt940_listopad.sta").read_bytes())
    assert parsed.format == "mt940"
    assert parsed.account == COMPANY
    assert parsed.currency == "PLN"
    assert len(parsed.lines) == 5
    first, second, third, credit, storno = parsed.lines
    assert first.direction == "debit"
    assert first.amount == Decimal("21106.80")
    assert first.booked_on == date(2026, 11, 18)
    # Tytuł sklejony z kawałków ~20 i ~21 bez spacji — numer KSeF w całości.
    assert KSEF in first.title
    assert first.counterparty_account == OLA
    assert first.counterparty_name == "Nowak Recruitment Ola Nowak"
    assert first.bank_ref == "BR2611180001"
    assert first.line_ref == "1:BR2611180001"
    assert second.title == "Wynagrodzenie zlecenie 10/2026"
    assert second.counterparty_account == KUBA
    assert third.counterparty_name == "Biuro Przykładowe Sp. z o.o."
    assert third.counterparty_account == OFFICE
    # Opis bez podpól: rachunek z tekstu.
    assert credit.direction == "credit"
    assert credit.counterparty_account == OFFICE
    # Storno uznania (RC) obciąża rachunek.
    assert storno.direction == "debit"
    assert storno.booked_on == date(2026, 12, 31)


def test_mt940_refuses_other_files():
    with pytest.raises(StatementError):
        mt940.parse(b"Nazwa;Kwota\nJan;10\n")


def test_mt940_refuses_unreadable_operation():
    raw = b":20:X\r\n:25:/PL72999900010000000000001234\r\n:61:ZEPSUTE\r\n:86:x\r\n-"
    with pytest.raises(StatementError) as error:
        mt940.parse(raw)
    assert "operacji nr 1" in str(error.value)


def test_mt940_reads_utf8_too():
    raw = (
        (DATA / "mt940_listopad.sta")
        .read_bytes()
        .decode("windows-1250")
        .encode("utf-8")
    )
    parsed = mt940.parse(raw)
    assert parsed.lines[2].counterparty_name == "Biuro Przykładowe Sp. z o.o."


# ── CAMT.053 ──────────────────────────────────────────────────────────────────


def test_camt053_reads_entries_and_batch_details():
    raw = (DATA / "camt053_listopad.xml").read_bytes()
    assert camt053.looks_like(raw)
    parsed = camt053.parse(raw)
    assert parsed.format == "camt053"
    assert parsed.account == COMPANY
    assert len(parsed.lines) == 4
    invoice, mandate, rent, credit = parsed.lines
    assert invoice.amount == Decimal("21106.80") and invoice.direction == "debit"
    assert invoice.counterparty_account == OLA
    assert invoice.counterparty_name == "Nowak Recruitment Ola Nowak"
    assert KSEF in invoice.title
    # „NOTPROVIDED” nie jest referencją — zostaje referencja banku z pozycji.
    assert invoice.bank_ref == "BR2611180001"
    # Księgowanie zbiorcze: każda transakcja z własną kwotą.
    assert mandate.amount == Decimal("1612.00") and mandate.bank_ref == "E2E-ZLEC-10"
    assert rent.amount == Decimal("4000.00") and rent.counterparty_account == OFFICE
    assert credit.direction == "credit" and credit.title == "Zwrot kaucji"


def test_camt053_refuses_doctype_and_entities():
    evil = (
        b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b"<Document><BkToCstmrStmt><Stmt/></BkToCstmrStmt></Document>"
    )
    with pytest.raises(StatementError):
        camt053.parse(evil)


def test_camt053_refuses_broken_xml_and_other_documents():
    with pytest.raises(StatementError):
        camt053.parse(b"<Document><BkToCstmrStmt>")
    with pytest.raises(StatementError):
        camt053.parse(b"<Document><Other/></Document>")


def test_full_account_numbers_are_masked_in_titles():
    raw = (
        ":20:X\r\n:25:/PL72999900010000000000001234\r\n:60F:C261117PLN100,00\r\n"
        f":61:2611181118DN10,00NTRFNONREF//R1\r\n:86:Zwrot na PL{OLA} i {KUBA}\r\n-"
    ).encode()
    (line,) = mt940.parse(raw).lines
    assert OLA not in line.title and KUBA not in line.title
    assert "•• 4521" in line.title and "•• 0937" in line.title
    # Rachunek kontrahenta odczytany z tekstu przed maskowaniem.
    assert line.counterparty_account == OLA
    assert (
        accounts.mask_accounts(
            f"x PL{OLA[:2]} {OLA[2:6]} {OLA[6:10]} {OLA[10:14]} "
            f"{OLA[14:18]} {OLA[18:22]} {OLA[22:]} y"
        )
        == "x •• 4521 y"
    )
    # Numer KSeF (z myślnikami) zostaje w całości.
    assert accounts.mask_accounts(KSEF) == KSEF


def test_camt053_refuses_doctype_hidden_in_utf16():
    evil = (
        '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE d [<!ENTITY x "X">]>'
        "<Document><BkToCstmrStmt><Stmt><Ntry/></Stmt></BkToCstmrStmt></Document>"
    ).encode("utf-16")
    with pytest.raises(StatementError):
        camt053.parse(evil)


def test_bonus_sheet_header_from_settings_is_formula_safe():
    import io as _io
    from datetime import date as _date

    from openpyxl import load_workbook

    from app.services.hr import symfonia_files

    person = symfonia_files.SymfoniaPerson(
        user_id=1, surname="Przykładowa", given_name="Anna", symfonia_id="E-1"
    )
    content = symfonia_files.bonuses_xlsx(
        [
            symfonia_files.BonusRow(
                person=person, amounts={"=HYPERLINK(1)": Decimal("5")}
            )
        ],
        ["=HYPERLINK(1)"],
        first=_date(2026, 9, 1),
        last=_date(2026, 9, 30),
    )
    header = [cell.value for cell in load_workbook(_io.BytesIO(content)).active[1]]
    assert header[-1] == "'=HYPERLINK(1)"


# ── Po przeglądzie (17/18.10): podpola :86: sklejane liniowo ────────────────


def _best_time(body: str) -> float:
    import time

    runs = []
    for _ in range(3):
        start = time.perf_counter()
        fields = mt940._subfields(body)
        runs.append(time.perf_counter() - start)
    assert fields["20"] == "A" * body.count("~20")
    return min(runs)


def test_podpola_opisu_sklejaja_sie_liniowo_na_megabajcie():
    # ~1 MB opisu z tym samym podpolem powtórzonym 250 000 razy (wyciąg ma
    # limit 5 MB): czas ma rosnąć liniowo z rozmiarem, nie z kwadratem.
    small = _best_time("~20A" * 62_500)
    large = _best_time("~20A" * 250_000)
    assert large < 2.0
    assert large / max(small, 1e-4) < 8, (small, large)


# ── Audyt A2 (19.10.2026): kilka wyciągów w pliku, storno i status w CAMT ─────


def test_mt940_kilka_wyciagow_kazda_operacja_ma_walute_swojego_wyciagu():
    raw = (
        ":20:W1\r\n:25:/PL72999900010000000000001234\r\n:60F:C261117PLN100,00\r\n"
        ":61:2611181118DN123,45NTRFNONREF//R-PLN\r\n:86:Przelew PLN\r\n"
        ":62F:C261118PLN0,00\r\n-\r\n"
        ":20:W2\r\n:25:/PL72999900010000000000001234\r\n:60F:C261117EUR50,00\r\n"
        ":61:2611181118DN10,00NTRFNONREF//R-EUR\r\n:86:Przelew EUR\r\n-"
    ).encode()
    first, second = mt940.parse(raw).lines
    # Ostatnia operacja pierwszego wyciągu nie bierze waluty z :60F: następnego.
    assert first.currency == "PLN" and first.bank_ref == "R-PLN"
    assert second.currency == "EUR"


def _camt(*statements: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">'
        "<BkToCstmrStmt>" + "".join(statements) + "</BkToCstmrStmt></Document>"
    ).encode()


def _stmt(currency: str, *entries: str) -> str:
    return (
        f"<Stmt><Acct><Id><IBAN>PL{COMPANY}</IBAN></Id><Ccy>{currency}</Ccy></Acct>"
        + "".join(entries)
        + "</Stmt>"
    )


def _ntry(
    indicator: str,
    *,
    amount: str = "1230.00",
    ccy: str | None = "PLN",
    reversal: bool = False,
    status: str | None = None,
    ref: str = "BR-1",
) -> str:
    amt = f'<Amt Ccy="{ccy}">{amount}</Amt>' if ccy else f"<Amt>{amount}</Amt>"
    return (
        f"<Ntry>{amt}<CdtDbtInd>{indicator}</CdtDbtInd>"
        + ("<RvslInd>true</RvslInd>" if reversal else "")
        + (status or "")
        + "<BookgDt><Dt>2026-11-20</Dt></BookgDt>"
        + f"<AcctSvcrRef>{ref}</AcctSvcrRef>"
        + "<NtryDtls><TxDtls><RltdPties>"
        + f"<Dbtr><Nm>Spółka Przykładowa</Nm></Dbtr><DbtrAcct><Id><IBAN>PL{COMPANY}"
        + "</IBAN></Id></DbtrAcct>"
        + f"<Cdtr><Nm>Ola Nowak</Nm></Cdtr><CdtrAcct><Id><IBAN>PL{OLA}</IBAN></Id>"
        + "</CdtrAcct></RltdPties>"
        + "<RmtInf><Ustrd>FV 10/2026</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>"
    )


def test_camt053_storno_kierunek_z_cdtdbtind_a_kontrahent_z_pierwotnej_operacji():
    # Zwrot nieudanego przelewu do osoby: CRDT + RvslInd = wpływ na rachunek firmy.
    parsed = camt053.parse(_camt(_stmt("PLN", _ntry("CRDT", reversal=True))))
    (line,) = parsed.lines
    assert line.direction == "credit"
    # Kontrahent to odbiorca pierwotnego przelewu (Cdtr), nie my (Dbtr).
    assert line.counterparty_account == OLA
    assert line.counterparty_name == "Ola Nowak"
    # Zwykłe obciążenie bez storna — bez zmian.
    (plain,) = camt053.parse(_camt(_stmt("PLN", _ntry("DBIT")))).lines
    assert plain.direction == "debit" and plain.counterparty_account == OLA


@pytest.mark.parametrize(
    "status",
    [
        "<Sts>PDNG</Sts>",
        "<Sts>INFO</Sts>",
        "<Sts><Cd>PDNG</Cd></Sts>",
        "<Sts><Cd>INFO</Cd></Sts>",
    ],
)
def test_camt053_pomija_operacje_niezaksiegowane(status):
    raw = _camt(
        _stmt(
            "PLN",
            _ntry("DBIT", status=status, ref="BR-WAIT"),
            _ntry("DBIT", status="<Sts>BOOK</Sts>", ref="BR-BOOK-1"),
            _ntry("DBIT", status="<Sts><Cd>BOOK</Cd></Sts>", ref="BR-BOOK-2"),
            _ntry("DBIT", ref="BR-NO-STS"),
        )
    )
    refs = [line.bank_ref for line in camt053.parse(raw).lines]
    assert refs == ["BR-BOOK-1", "BR-BOOK-2", "BR-NO-STS"]


def test_camt053_waluta_z_wyciagu_ktory_niesie_operacje():
    raw = _camt(
        _stmt("PLN", _ntry("DBIT", ccy=None, ref="BR-PLN")),
        _stmt("EUR", _ntry("DBIT", ccy=None, ref="BR-EUR")),
        _stmt("EUR", _ntry("DBIT", ccy="USD", ref="BR-USD")),
    )
    pln, eur, usd = camt053.parse(raw).lines
    assert pln.currency == "PLN"
    # Bez Amt/@Ccy waluta z Acct/Ccy TEGO wyciągu, nie pierwszego w pliku.
    assert eur.currency == "EUR"
    # Waluta wpisu wygrywa z walutą rachunku.
    assert usd.currency == "USD"
