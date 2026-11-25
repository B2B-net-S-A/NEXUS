"""Ostrzeżenie „podwójna zapłata” (``finance_ledger.double_pay``) — bez bazy.

Fikcyjni dostawcy, numery i kwoty.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.finance_ledger.double_pay import CostDoc, findings, number_key

NIP = "1111111111"


def _doc(key: str, **kw) -> CostDoc:
    base = dict(
        key=key,
        seller_nip=NIP,
        invoice_number=f"FV/{key}/2026",
        kind="Vat",
        issue_date=date(2026, 3, 31),
        currency="PLN",
        net=Decimal("1000.00"),
    )
    base.update(kw)
    return CostDoc(**base)


def test_korekta_na_plus_rowna_calej_wczesniejszej_fakturze_ostrzega() -> None:
    march = _doc("m", issue_date=date(2026, 3, 31), net=Decimal("21000.00"))
    k3 = _doc("k3", kind="Kor", issue_date=date(2026, 5, 11), net=Decimal("21000.00"))
    [sentence] = findings(k3, [march, k3], contractors=True)
    assert "Korekta FV/k3/2026" in sentence and "FV/m/2026 z 31.03.2026" in sentence
    assert "21 000,00 PLN" in sentence


def test_korekta_o_roznice_albo_na_minus_nie_ostrzega() -> None:
    march = _doc("m", net=Decimal("21000.00"))
    small = _doc("k1", kind="Kor", issue_date=date(2026, 4, 2), net=Decimal("400.00"))
    minus = _doc(
        "k2", kind="Kor", issue_date=date(2026, 4, 2), net=Decimal("-21000.00")
    )
    assert findings(small, [march], contractors=True) == []
    assert findings(minus, [march], contractors=True) == []


def test_korekta_rowna_fakturze_pozniejszej_albo_w_innej_walucie_nie_ostrzega() -> None:
    later = _doc("p", issue_date=date(2026, 6, 30))
    eur = _doc("e", currency="EUR", issue_date=date(2026, 1, 31))
    kor = _doc("k", kind="Kor", issue_date=date(2026, 5, 11))
    assert findings(kor, [later, eur], contractors=True) == []


def test_druga_faktura_na_te_sama_kwote_w_tym_samym_miesiacu() -> None:
    a = _doc("a", issue_date=date(2026, 10, 30))
    b = _doc("b", issue_date=date(2026, 11, 2))
    [sentence] = findings(b, [a], contractors=True)
    assert "Druga faktura" in sentence and "FV/a/2026 z 30.10.2026" in sentence


def test_faktury_za_kolejne_miesiace_nie_ostrzegaja() -> None:
    # 1. dnia miesiąca za poprzedni, 30. za bieżący — 29 dni od siebie.
    a = _doc("a", issue_date=date(2026, 10, 1))
    b = _doc("b", issue_date=date(2026, 10, 30))
    assert findings(b, [a], contractors=True) == []


def test_miesiac_uslugi_z_kontraktu_wygrywa_z_data() -> None:
    a = _doc("a", issue_date=date(2026, 11, 2), service_month="2026-10")
    b = _doc("b", issue_date=date(2026, 11, 3), service_month="2026-11")
    c = _doc("c", issue_date=date(2026, 12, 1), service_month="2026-10")
    assert findings(b, [a], contractors=True) == []
    assert len(findings(c, [a], contractors=True)) == 1


def test_druga_faktura_tylko_w_dzienniku_kontraktorow() -> None:
    a = _doc("a", issue_date=date(2026, 10, 30))
    b = _doc("b", issue_date=date(2026, 10, 31))
    assert findings(b, [a], contractors=False) == []


def test_ten_sam_numer_dwa_razy() -> None:
    a = _doc("a", invoice_number="FV 7/10/2026", net=Decimal("10.00"))
    b = _doc("b", invoice_number="fv7/10/2026", net=Decimal("20.00"))
    [sentence] = findings(b, [a], contractors=False)
    assert "Ten sam numer" in sentence
    assert number_key(" FV 7/10/2026 ") == "fv7/10/2026"


def test_korekta_na_zero_z_numerem_faktury_nie_ostrzega() -> None:
    a = _doc("a", invoice_number="FV/1/2026")
    kor = _doc("k", kind="Kor", invoice_number="FV/1/2026", net=Decimal("0.00"))
    assert findings(kor, [a], contractors=True) == []
    assert findings(a, [kor], contractors=True) == []


def test_odrzucony_albo_duplikat_nie_jest_druga_faktura() -> None:
    a = _doc("a", issue_date=date(2026, 10, 30), settled=True)
    b = _doc("b", issue_date=date(2026, 10, 31), invoice_number="FV/a/2026")
    assert findings(b, [a], contractors=True) == []


def test_inny_dostawca_nie_jest_brany_pod_uwage() -> None:
    a = _doc("a", seller_nip="2222222222", issue_date=date(2026, 10, 30))
    b = _doc("b", issue_date=date(2026, 10, 31))
    assert findings(b, [a], contractors=True) == []
