"""Zajęcia wierzytelności kontraktora — reguły bez bazy (23.11.2026).

Należność na dzień przelewu (koszty, odsetki: brak / kwota / stopa od dnia /
nieustalone), wcześniejsze przelewy do organu (najpierw koszty, potem
odsetki), podział płatności przy kilku zajęciach, uchylenie, tytuł przelewu,
blokada białej listy kontraktora i dopasowanie przelewu do organu z wyciągu.
Kwoty, sygnatury i rachunki fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.finance_ledger import garnishment_rules as g
from app.services.finance_ledger import payment_rules as rules
from app.services.hr.bank.parsed import StatementLine
from app.services.hr.bank.titles import LINE_LENGTH, MAX_LINES

D = Decimal


def _terms(**kw) -> g.Terms:
    base = dict(
        id=1,
        case_number="KM 123/26",
        authority_name="Komornik Sądowy Testowy",
        served_on=date(2026, 11, 2),
        principal=D("1000.00"),
        costs=D("0.00"),
        interest_mode="none",
        account="1" * 26,
    )
    base.update(kw)
    return g.Terms(**base)


def test_bez_odsetek_i_kwota_z_pisma() -> None:
    assert g.balance_on(_terms(costs=D("50")), date(2026, 11, 20), []).due == D(
        "1050.00"
    )
    fixed = _terms(interest_mode="fixed", interest_amount=D("12.34"))
    assert g.balance_on(fixed, date(2027, 3, 1), []).due == D("1012.34")


def test_odsetki_ze_stopy_do_dnia_przelewu() -> None:
    # 1000 zł × 10% × 73 dni / 365 = 20,00 zł
    terms = _terms(
        interest_mode="rate", interest_rate=D("10"), interest_from=date(2026, 9, 1)
    )
    balance = g.balance_on(terms, date(2026, 11, 13), [])
    assert balance.interest == D("20.00")
    assert balance.due == D("1020.00")


def test_wplata_najpierw_na_koszty_i_odsetki_potem_naleznosc() -> None:
    terms = _terms(
        costs=D("30.00"),
        interest_mode="rate",
        interest_rate=D("10"),
        interest_from=date(2026, 9, 1),
    )
    # Do 13.11: odsetki 20,00; wpłata 550 → koszty 30, odsetki 20, należność 500.
    paid = [g.Transfer(on=date(2026, 11, 13), amount=D("550.00"))]
    # Od 13.11 do 25.01.2027 (73 dni) odsetki od 500 zł = 10,00.
    balance = g.balance_on(terms, date(2027, 1, 25), paid)
    assert balance.costs == D("0.00")
    assert balance.principal == D("500.00")
    assert balance.interest == D("10.00")
    assert balance.due == D("510.00")


def test_przelew_z_paczki_na_pozniejszy_dzien_odejmuje_sie_po_kwocie() -> None:
    paid = [g.Transfer(on=date(2026, 12, 20), amount=D("400.00"))]
    assert g.balance_on(_terms(), date(2026, 12, 1), paid).due == D("600.00")


def test_zajecie_splacone_nie_daje_ujemnej_naleznosci() -> None:
    paid = [g.Transfer(on=date(2026, 11, 3), amount=D("1500.00"))]
    assert g.balance_on(_terms(), date(2026, 11, 20), paid).due == D("0.00")


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"interest_mode": "unknown"}, "interest_unknown"),
        ({"interest_mode": "fixed"}, "interest_incomplete"),
        ({"interest_mode": "rate", "interest_rate": D("8")}, "interest_incomplete"),
        (
            {"interest_mode": "rate", "interest_from": date(2026, 9, 1)},
            "interest_incomplete",
        ),
    ],
)
def test_kwoty_nie_da_sie_policzyc(kw, code) -> None:
    with pytest.raises(g.GarnishmentError) as exc:
        g.balance_on(_terms(**kw), date(2026, 11, 20), [])
    assert exc.value.code == code


def test_zajecie_wieksze_niz_platnosc_bierze_calosc() -> None:
    terms = _terms(principal=D("5000.00"))
    balance = g.balance_on(terms, date(2026, 11, 20), [])
    shares, rest = g.split(D("1230.00"), [(terms, balance)])
    assert [s.amount for s in shares] == [D("1230.00")]
    assert rest == D("0.00")


def test_kilka_zajec_od_najwczesniej_doreczonego() -> None:
    later = _terms(id=2, served_on=date(2026, 11, 10), principal=D("500.00"))
    first = _terms(id=3, served_on=date(2026, 11, 1), principal=D("1000.00"))
    paid_off = _terms(id=4, served_on=date(2026, 10, 1), principal=D("10.00"))
    day = date(2026, 11, 20)
    pairs = [
        (later, g.balance_on(later, day, [])),
        (first, g.balance_on(first, day, [])),
        (
            paid_off,
            g.Balance(due=D("0.00"), principal=D("0"), interest=D("0"), costs=D("0")),
        ),
    ]
    shares, rest = g.split(D("1230.00"), pairs)
    assert [(s.terms.id, s.amount) for s in shares] == [
        (3, D("1000.00")),
        (2, D("230.00")),
    ]
    assert rest == D("0.00")
    shares, rest = g.split(D("2000.00"), pairs)
    assert [s.amount for s in shares] == [D("1000.00"), D("500.00")]
    assert rest == D("500.00")


def test_zajecie_dziala_od_doreczenia_do_dnia_uchylenia() -> None:
    terms = _terms(served_on=date(2026, 11, 5), lifted_on=date(2026, 11, 20))
    assert not terms.active_on(date(2026, 11, 4))
    assert terms.active_on(date(2026, 11, 5))
    assert terms.active_on(date(2026, 11, 19))
    # W dniu uchylenia już bez przelewu do organu.
    assert not terms.active_on(date(2026, 11, 20))


def test_tytul_przelewu_do_organu_miesci_sie_w_elixirze() -> None:
    lines = g.title_lines(
        case_number="GKM 1234/26",
        debtor_nip="1234567890",
        invoice_number="FV/7/11/2026",
    )
    assert lines[0] == "Sygn. GKM 1234/26"
    assert "Zajęcie wierzytelności" in lines
    assert "faktura FV/7/11/2026" in " ".join(lines)
    assert len(lines) <= MAX_LINES and all(len(line) <= LINE_LENGTH for line in lines)


def test_dluga_sygnatura_zostawia_numer_faktury_albo_blokuje() -> None:
    long_case = "Km " + "1234567890/" * 6  # 69 znaków: trzy linie sygnatury
    lines = g.title_lines(
        case_number=long_case, debtor_nip="1234567890", invoice_number="F/1"
    )
    assert lines[-1] == "faktura F/1" and len(lines) == MAX_LINES
    assert "Zajęcie wierzytelności" not in lines
    with pytest.raises(g.GarnishmentError) as exc:
        g.title_lines(case_number="X" * 140, debtor_nip=None, invoice_number="F/1")
    assert exc.value.code == "title_too_long"


@pytest.mark.parametrize(
    ("state", "code"),
    [
        ("not_listed", "white_list_not_listed"),
        ("unchecked", "white_list_unchecked"),
        ("listed", None),
        ("off", None),
        ("no_nip", None),
        ("foreign", None),
    ],
)
def test_biala_lista_kontraktora_blokuje_brak_i_blad_wykazu(state, code) -> None:
    assert rules.contractor_white_list_block(state) == code


def _line(amount: str, account: str, title: str) -> StatementLine:
    return StatementLine(
        index=1,
        booked_on=date(2026, 11, 21),
        amount=D(amount),
        currency="PLN",
        direction="debit",
        title=title,
        counterparty_name="Odbiorca",
        counterparty_account=account,
    )


def test_wyciag_dopasowuje_przelew_do_organu_z_pozycji_paczki() -> None:
    organ, contractor = "2" * 26, "3" * 26
    candidate = rules.CostCandidate(
        entry_id=7,
        currency="PLN",
        gross=D("1230.00"),
        paid=D("0.00"),
        invoice_number="K/1/11/2026",
        ksef_number=None,
        accounts=frozenset({organ, contractor}),
        batch_amount=D("180.00"),
        batch_account=contractor,
        batch_transfers=((organ, D("1050.00")),),
    )
    # Bez numeru faktury w tytule: rachunek i kwota przelewu z paczki.
    to_organ = rules.decide_debit(_line("1050.00", organ, "egzekucja"), [candidate])
    assert (to_organ.entry_id, to_organ.amount, to_organ.partial) == (
        7,
        D("1050.00"),
        True,
    )
    to_contractor = rules.decide_debit(_line("180.00", contractor, "x"), [candidate])
    assert to_contractor.entry_id == 7 and to_contractor.amount == D("180.00")
    # Z numerem faktury w tytule rachunek organu potwierdza fakturę.
    by_number = rules.decide_debit(
        _line("1050.00", organ, "Sygn. KM 1/26 faktura K/1/11/2026"), [candidate]
    )
    assert by_number.entry_id == 7 and by_number.partial
