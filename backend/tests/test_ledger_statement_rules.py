"""Sprawozdania (K8a) — reguły bez bazy: słownik znaczników MF z JPK_KR_PD(1),
zapis pozycji konta, rozpoznanie znacznika i wyliczenie bilansu oraz RZiS
w wariancie porównawczym. Kwoty w groszach, konta z typowego planu."""

from __future__ import annotations

import pytest

from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import markers, statements


def _ytd(amounts):
    return {account: turnover for account, _, turnover in amounts}


def _find(nodes, label):
    for node in nodes:
        if node["label"] == label:
            return node
        found = _find(node["children"], label)
        if found is not None:
            return found
    return None


def _path(nodes, *labels):
    node = None
    for label in labels:
        node = next(item for item in nodes if item["label"] == label)
        nodes = node["children"]
    return node


def _line(result, letter):
    return next(line for line in result["income"]["lines"] if line["number"] == letter)


# ── Słownik MF ───────────────────────────────────────────────────────────────


def test_dictionary_comes_from_mf_schema_in_order():
    known = markers.dictionary()
    assert len(known) == 244
    codes = list(known)
    assert codes[0] == "BAAI1_W"
    assert codes[-1] == "INNE"
    assert known["RPBIII"].label == "Koszty działalności operacyjnej · Usługi obce"
    assert known["BPAV_ES_NPR"].group == markers.GROUP_LIABILITIES


def test_adjustment_codes_share_position_with_their_item():
    known = markers.dictionary()
    assert known["BAAII1c_U"].position == known["BAAII1c_W"].position
    assert known["BABII3a_D12_A"].position == known["BABII3a_D12"].position


def test_every_rule_points_at_existing_marker():
    known = markers.dictionary()
    for prefix, pair in markers.RULES.items():
        assert pair.debit in known, prefix
        assert pair.credit in known, prefix


def test_comparative_variant_skips_cost_by_function_codes():
    known = markers.dictionary()
    assert known["RPBIII"].comparative is True
    assert known["RPAI_RKAI_POZ"].comparative is True
    assert known["RKE"].comparative is False
    assert known["BPAVI"].comparative is False


# ── Zapis pozycji przy koncie ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        (None, None),
        ("", None),
        ("  RPBIII ", "RPBIII"),
        ("BABII3a_D12/BPBIII3d_D12", "BABII3a_D12/BPBIII3d_D12"),
        ("BABII3a_D12 / BPBIII3d_D12", "BABII3a_D12/BPBIII3d_D12"),
        ("BPAVI/BPAVI", "BPAVI"),
    ],
)
def test_report_line_accepts_mf_markers(raw, stored):
    assert markers.clean_report_line(raw) == stored


@pytest.mark.parametrize(
    "raw",
    [
        "Usługi obce",
        "RPBIII/RPBVII",
        "BABII3a_D12/",
        "BABII3a_D12/BPBIII3d_D12/BPAVI",
        "B.III",
    ],
)
def test_report_line_refuses_free_text_and_bad_pairs(raw):
    with pytest.raises(LedgerError) as error:
        markers.clean_report_line(raw)
    assert error.value.status == 422


def test_stored_garbage_reads_as_no_marker():
    assert markers.parse("stary opis pozycji") is None
    assert markers.parse("RPBIII").debit == "RPBIII"


# ── Znacznik konta ────────────────────────────────────────────────────────────


def test_own_marker_beats_parent_and_rule():
    own = {"402-203": "RPBVII", "402": "RPBII"}
    assert markers.resolve("402-203", own) == (markers._pair("RPBVII"), "own")
    assert markers.resolve("402-215", own) == (markers._pair("RPBII"), "parent")
    assert markers.resolve("402-215", {}) == (markers._pair("RPBIII"), "rule")


def test_dictionary_analytics_inherit_from_parent_account():
    own = {"201-2": "BABII3c_W/BPBIII3i"}
    pair, source = markers.resolve("201-2-1042", own)
    assert (pair.debit, pair.credit, source) == ("BABII3c_W", "BPBIII3i", "parent")


def test_ambiguous_cost_accounts_wait_for_accountant():
    # 400–405 mają w planach różne znaczenia (K6 księguje amortyzację na 401).
    for number in ("400", "401", "404-1", "010", "070"):
        assert markers.resolve(number, {}) == (None, "none")


def test_off_balance_and_cost_allocation_are_outside_comparative_statements():
    assert markers.resolve("901", {"901": "INNE"}) == (None, "excluded")
    assert markers.resolve("490", {}) == (None, "excluded")
    assert markers.resolve("501-12", {}) == (None, "excluded")


def test_longest_rule_prefix_wins():
    assert markers.rule_for("751-1").debit == "RPHIV_RKKIV_POZ"
    assert markers.rule_for("760").debit == "RPDIV_RKGIV_P"
    assert markers.rule_for("701-10-1").debit == "RPAI_RKAI_POZ"


# ── Bilans i RZiS ─────────────────────────────────────────────────────────────

MONTH = [
    # (konto, saldo na koniec miesiąca Wn−Ma, obroty miesiąca Wn−Ma)
    ("801", -5_000_00, 0),  # kapitał z BO
    ("131", 5_000_00 + 300_00, 300_00),  # BO + wpłata klienta
    ("200-1", 1_230_00 - 300_00, 1_230_00 - 300_00),
    ("222", -230_00, -230_00),
    ("701-4-1", -1_000_00, -1_000_00),
    ("402-203", 800_00, 800_00),
    ("201-7", -984_00, -984_00),
    ("221", 184_00, 184_00),
]


def test_balance_sheet_balances_with_net_result_from_result_accounts():
    result = statements.build(MONTH, {}, {}, ytd_result=_ytd(MONTH))
    balance = result["balance"]
    assert balance["balanced"] is True
    assert balance["assets_total"] == 5_300_00 + 930_00 + 184_00
    net = _find(balance["liabilities"], "Zysk (strata) netto")
    assert net["amount"] == 200_00
    assert (
        _find(balance["liabilities"], "Kapitał (fundusz) podstawowy")["amount"]
        == 5_000_00
    )
    assert result["issues"] == []
    assert result["complete"] is True


def test_income_statement_comparative_signs_and_totals():
    result = statements.build(MONTH, {}, {}, ytd_result=_ytd(MONTH))
    assert _line(result, "A")["amount"] == 1_000_00
    assert _line(result, "B")["amount"] == 800_00
    assert _line(result, "C")["amount"] == 200_00
    assert _line(result, "L")["amount"] == 200_00
    assert [line["number"] for line in result["income"]["lines"]] == list(
        "ABCDEFGHIJKL"
    )
    assert (
        _line(result, "C")["computed"] is True
        and _line(result, "B")["computed"] is False
    )
    services = _find(_line(result, "B")["children"], "Usługi obce")
    assert services["number"] == "III"
    assert services["accounts"] == [{"account": "402", "name": None, "amount": 800_00}]


def test_settlement_analytics_split_between_receivables_and_payables():
    amounts = [
        ("202-2-10", 500_00, 500_00),  # klient winien
        ("202-2-11", -120_00, -120_00),  # nadpłata innego klienta
        ("701-10-1", -380_00, -380_00),
    ]
    result = statements.build(amounts, {}, {}, ytd_result=_ytd(amounts))
    balance = result["balance"]
    receivables = _path(
        balance["assets"],
        "Aktywa obrotowe",
        "Należności krótkoterminowe",
        "Należności od pozostałych jednostek",
        "Z tytułu dostaw i usług",
        "o okresie spłaty do 12 miesięcy",
    )
    payables = _path(
        balance["liabilities"],
        "Zobowiązania i rezerwy na zobowiązania",
        "Zobowiązania krótkoterminowe",
        "Wobec pozostałych jednostek",
        "Z tytułu dostaw i usług",
        "O okresie wymagalności do 12 miesięcy",
    )
    assert receivables["amount"] == 500_00
    assert payables["amount"] == 120_00
    assert balance["balanced"] is True


def test_balance_sheet_numbering_follows_annex_1():
    result = statements.build(MONTH, {}, {}, ytd_result=_ytd(MONTH))
    assets = result["balance"]["assets"]
    assert [(node["number"], node["label"]) for node in assets[:2]] == [
        ("A", "Aktywa trwałe"),
        ("B", "Aktywa obrotowe"),
    ]
    current = assets[1]
    assert [child["number"] for child in current["children"]] == [
        "I",
        "II",
        "III",
        "IV",
    ]
    trade = _path(
        assets,
        "Aktywa obrotowe",
        "Należności krótkoterminowe",
        "Należności od pozostałych jednostek",
        "Z tytułu dostaw i usług",
    )
    assert trade["number"] == "a)"
    others = _path(assets, "Aktywa obrotowe", "Należności krótkoterminowe")["children"]
    assert [child["number"] for child in others] == ["1", "2", "3"]


def test_unmapped_account_blocks_and_unbalances():
    amounts = [*MONTH, ("404", 150_00, 150_00), ("231", -150_00, -150_00)]
    result = statements.build(amounts, {}, {}, ytd_result=_ytd(amounts))
    assert result["complete"] is False
    assert result["issues"] == [
        {
            "account": "404",
            "name": None,
            "problem": "Konto bez pozycji sprawozdania",
            "amount": 150_00,
        }
    ]
    assert result["balance"]["balanced"] is False


def test_cost_by_function_marker_and_other_marker_are_problems():
    amounts = [("409-1", 10_00, 10_00), ("905", 7_00, 7_00), ("249", -10_00, -10_00)]
    own = {"409-1": "RKE", "249": "INNE"}
    result = statements.build(
        amounts, own, {"409": "Pozostałe"}, ytd_result=_ytd(amounts)
    )
    problems = {(item["account"], item["problem"]) for item in result["issues"]}
    assert problems == {
        ("409", "Znacznik tylko wariantu kalkulacyjnego"),
        ("249", "Znacznik „INNE” — poza sprawozdaniem"),
    }


def test_cost_allocation_residual_is_warned_and_kept_in_balance():
    # Koszt zaksięgowany wprost na 5 (bez 4 i 490): porównawczy RZiS go nie widzi.
    amounts = [
        ("402-203", 800_00, 800_00),
        ("201-7", -900_00, -900_00),
        ("501-12", 100_00, 100_00),
        ("131", 100_00, 100_00),
        ("700", -100_00, -100_00),
    ]
    result = statements.build(amounts, {}, {}, ytd_result=_ytd(amounts))
    assert result["warnings"][0]["code"] == "allocation_residual"
    assert result["warnings"][0]["amount"] == 100_00
    # RZiS porównawczy nie widzi kont 5 i 490 …
    assert _line(result, "B")["amount"] == 800_00
    # … ale bilans tak — inaczej by się rozjechał.
    assert result["balance"]["balanced"] is True


def test_payroll_analytics_never_show_below_synthetic_account():
    amounts = [("231-12", -4_000_00, -4_000_00), ("404", 4_000_00, 4_000_00)]
    own = {"404": "RPBV"}
    result = statements.build(amounts, own, {}, ytd_result=_ytd(amounts))
    wages = _find(result["balance"]["liabilities"], "Z tytułu wynagrodzeń")
    assert wages["accounts"] == [{"account": "231", "name": None, "amount": 4_000_00}]


def test_range_turnover_feeds_income_and_ytd_feeds_net_result():
    # Marzec: obroty miesiąca w RZiS, wynik od stycznia w bilansie.
    amounts = [("701-4-1", -3_000_00, -1_000_00), ("200-1", 3_000_00, 1_000_00)]
    result = statements.build(
        amounts, {}, {}, ytd_result={"701-4-1": -3_000_00, "200-1": 3_000_00}
    )
    assert _line(result, "A")["amount"] == 1_000_00
    assert (
        _find(result["balance"]["liabilities"], "Zysk (strata) netto")["amount"]
        == 3_000_00
    )
    assert result["balance"]["balanced"] is True
