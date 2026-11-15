"""Rejestry VAT (K5a) — reguły bez bazy: podział stawek, kwoty z dekretu, sumy
pól JPK_V7M i pozycja listy zamknięcia. Kwoty w groszach, konta fikcyjne."""

from __future__ import annotations

from datetime import date

from app.services.ledger import closing, vat


def test_one_rate_takes_the_whole_invoice():
    assert vat.split_sales([{"net": "1000.00", "vat_rate": "23"}], 100_000, 23_000) == (
        {"23": (100_000, 23_000)},
        None,
    )
    # Usługa dla podatnika z UE: K_11 i „w tym” K_12, bez VAT.
    assert vat.split_sales([{"net": "500", "vat_rate": "np II"}], 215_000, 0) == (
        {"np_ue": (215_000, 0)},
        None,
    )
    # Korekta: wiersz „przed” ze znakiem minus, ta sama stawka = całe kwoty.
    correction = [
        {"net": "1000.00", "vat_rate": "23", "before_correction": True},
        {"net": "900.00", "vat_rate": "23"},
    ]
    assert vat.split_sales(correction, -10_000, -2_300) == ({"23": (-10_000, -2_300)}, None)


def test_mixed_rates_split_net_by_items_and_vat_only_where_taxed():
    items = [
        {"net": "1000.00", "vat_rate": "23"},
        {"net": "500.00", "vat_rate": "zw"},
    ]
    amounts, problem = vat.split_sales(items, 150_000, 23_000)
    assert problem is None
    assert amounts == {"23": (100_000, 23_000), "zw": (50_000, 0)}
    # 23% i 8%: VAT w proporcji netto × stawka, grosze sumują się do faktury.
    mixed = [{"net": "100.00", "vat_rate": "23"}, {"net": "100.00", "vat_rate": "8"}]
    amounts, problem = vat.split_sales(mixed, 20_000, 3_100)
    assert problem is None
    assert amounts == {"23": (10_000, 2_300), "8": (10_000, 800)}
    assert sum(v for _, v in amounts.values()) == 3_100


def test_rates_that_cannot_be_split_go_to_the_list():
    assert vat.split_sales([{"net": "1", "vat_rate": "oo"}], 100, 0)[1] == (
        "stawka spoza słownika JPK: oo"
    )
    assert vat.split_sales([], 100, 23)[1] == "pozycje faktury bez stawki VAT"
    assert vat.split_sales([{"net": "1"}], 100, 23)[1] == (
        "stawka spoza słownika JPK: brak stawki"
    )
    changed = [
        {"net": "100", "vat_rate": "23", "before_correction": True},
        {"net": "100", "vat_rate": "8"},
    ]
    assert vat.split_sales(changed, 0, -1_500)[1] == "korekta zmienia stawki — rozdziel ręcznie"
    without_net = [{"vat_rate": "23"}, {"net": "10", "vat_rate": "zw"}]
    assert "rozdziel ręcznie" in vat.split_sales(without_net, 2_000, 230)[1]


def test_amounts_come_from_the_decree():
    sale = [
        ("debit", "200-17", 123_000, 7),
        ("credit", "701", 100_000, None),
        ("credit", "222", 23_000, None),
    ]
    assert vat.sales_amounts(sale, output_account="222") == (100_000, 23_000)
    # Korekta in minus: strony zamienione.
    minus = [("credit", "200-17", 12_300, 7), ("debit", "701", 10_000, None), ("debit", "222", 2_300, None)]
    assert vat.sales_amounts(minus, output_account="222") == (-10_000, -2_300)
    purchase = [
        ("debit", "402", 100_000, None),
        ("debit", "221-1", 23_000, None),
        ("credit", "201-5", 123_000, 9),
    ]
    assert vat.purchase_amounts(purchase, input_account="221", intake_account="080") == (
        "other",
        100_000,
        23_000,
    )
    asset = [("debit", "080", 500_000, None), ("debit", "221", 115_000, None), ("credit", "201-5", 615_000, 9)]
    assert vat.purchase_amounts(asset, input_account="221", intake_account="080") == (
        "assets",
        500_000,
        115_000,
    )
    # Bez VAT naliczonego w dekrecie (bez odliczenia) — poza rejestrem.
    no_deduction = [("debit", "402", 123_000, None), ("credit", "201-5", 123_000, 9)]
    assert vat.purchase_amounts(no_deduction, input_account="221", intake_account="080") is None
    # „2210” to inne konto niż analityka „221-…”.
    other = [("debit", "2210", 5, None), ("credit", "201-5", 5, 9)]
    assert vat.purchase_amounts(other, input_account="221", intake_account="080") is None


def _row(key: str, net: int, tax: int, **extra) -> vat.Row:
    return vat.Row(
        document_id=1,
        number="X",
        ksef_number=None,
        issue_date=None,
        day=date(2026, 3, 1),
        counterparty="K",
        tax_id=None,
        country=None,
        amounts={key: (net, tax)},
        **extra,
    )


def test_summary_maps_groups_to_jpk_fields():
    summary = vat.summarize(
        [_row("23", 90_000, 20_700), _row("np_ue", 215_000, 0)],
        [_row("other", 1_100_000, 253_000)],
    )
    assert [(g["key"], g["net_field"], g["vat_field"], g["also"], g["net"], g["vat"]) for g in summary["groups"]] == [
        ("23", "K_19", "K_20", None, 90_000, 20_700),
        ("np_ue", "K_11", None, "K_12", 215_000, 0),
        ("other", "K_42", "K_43", None, 1_100_000, 253_000),
    ]
    assert (summary["output_vat"], summary["input_vat"], summary["due"]) == (20_700, 253_000, -232_300)


def _data(**extra) -> dict:
    values = {
        "sales": [{}],
        "purchases": [{}, {}],
        "summary": {"due": 12_345},
        "issues": [],
        "payroll_hidden": False,
    }
    values.update(extra)
    return values


def test_closing_item_for_vat_registers():
    href = "/accounting/vat?year=2026&month=3"
    ok = closing.vat_check(_data(), href)
    assert (ok["state"], ok["detail"]) == (
        "ok",
        "sprzedaż: 1, zakup: 2; VAT do zapłaty 123,45 zł (bez nadwyżki z poprzedniego okresu)",
    )
    surplus = closing.vat_check(_data(summary={"due": -500}, payroll_hidden=True), href)
    assert surplus["detail"].endswith("nadwyżka naliczonego 5,00 zł (bez nadwyżki z poprzedniego okresu); bez części płacowej")
    missing = {"kind": "missing_sales", "label": "Faktury sprzedaży z KSeF bez dokumentu w księdze", "count": 2}
    drafts = {"kind": "drafts", "label": "FVS i FVZ w buforze — rejestr liczy tylko zatwierdzone", "count": 1}
    problem = closing.vat_check(_data(issues=[missing, drafts]), href)
    assert problem["state"] == "problem"
    assert problem["detail"] == (
        "faktury sprzedaży z ksef bez dokumentu w księdze: 2; fvs i fvz w buforze: 1"
    )
    assert closing.vat_check(_data(issues=[drafts]), href)["state"] == "todo"
