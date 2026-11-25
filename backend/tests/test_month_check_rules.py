"""Kontrola miesiąca (0784): reguła bez bazy, dopasowanie pozycji i miesiąc faktury.

Osoby, klienci, numery faktur i kwoty zmyślone.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.contract_rate_history import collect as rh
from app.services.month_check import collect, rules

TODAY = date(2026, 11, 25)
MONTHS = ("2026-08", "2026-09", "2026-10")
RATE = Decimal("150")
CAND, CONTRACT, CLIENT = 1, 10, 100


def _ctx(**kw) -> rules.Context:
    base = dict(
        live=(CONTRACT,),
        contract_id=CONTRACT,
        client_id=CLIENT,
        rate=RATE,
        has_order=True,
    )
    base.update(kw)
    return rules.Context(**base)


def _sale(
    month: str,
    hours: str | None,
    *,
    net: str = "24000",
    cand: int = CAND,
    client: int = CLIENT,
) -> rules.SaleLine:
    return rules.SaleLine(
        candidate_id=cand,
        contract_id=CONTRACT,
        client_id=client,
        month=month,
        invoice_number=f"FS/{month}",
        hours=Decimal(hours) if hours is not None else None,
        net=Decimal(net),
    )


def _cost(
    issued: date, net: str, *, correction: bool = False, number: str | None = None
) -> rules.CostDoc:
    return rules.CostDoc(
        candidate_id=CAND,
        number=number or f"K/{issued.isoformat()}",
        issue_date=issued,
        net=Decimal(net),
        currency="PLN",
        correction=correction,
    )


def _inputs(
    sales=(),
    costs=(),
    *,
    context=None,
    today=TODAY,
    unnamed=None,
    unassigned=frozenset(),
) -> rules.Inputs:
    months = ("2026-07",) + MONTHS + ("2026-11",)
    ctx = context if context is not None else {(CAND, m): _ctx() for m in months}
    return rules.Inputs(
        months=MONTHS,
        today=today,
        sales=tuple(sales),
        costs=tuple(costs),
        context=ctx,
        unnamed_clients=unnamed or {},
        working_days={"2026-08": 20, "2026-09": 22, "2026-10": 22},
        unassigned_sales=unassigned,
    )


def _kinds(result: rules.Result) -> list[tuple[str, str]]:
    return sorted((f.kind, f.month) for f in result.findings)


# ── Miesiące ────────────────────────────────────────────────────────────────


def test_closed_months_and_deadline():
    assert rules.closed_months(date(2026, 11, 25)) == ["2026-08", "2026-09", "2026-10"]
    assert rules.closed_months(date(2026, 1, 3)) == ["2025-10", "2025-11", "2025-12"]
    assert rules.deadline("2026-12") == date(2027, 1, 15)


def test_working_days_skip_weekends_and_holidays():
    # Listopad 2026: 21 dni pon–pt, 11.11 (środa) to święto.
    assert collect.working_days("2026-11") == 20


# ── Godziny ─────────────────────────────────────────────────────────────────


def test_hours_within_half_a_day_match():
    # 160 h u klienta, konsultant 163 h × 150 zł — mieści się w 4 h.
    result = rules.evaluate(
        _inputs([_sale("2026-09", "160")], [_cost(date(2026, 9, 30), str(163 * 150))])
    )
    assert result.findings == []
    assert result.stats["2026-09"].matched == 1


def test_hours_mismatch_beyond_half_a_day():
    result = rules.evaluate(
        _inputs([_sale("2026-09", "160")], [_cost(date(2026, 9, 30), str(200 * 150))])
    )
    (finding,) = result.findings
    assert (finding.kind, finding.month) == (rules.HOURS_MISMATCH, "2026-09")
    assert finding.amount == Decimal("6000.00")
    assert finding.details["contractor_hours"] == "200.00"
    assert finding.details["client_hours"] == "160.00"


def test_md_units_count_as_eight_hours():
    line = _sale("2026-09", str(Decimal(20) * rules.HOURS_PER_DAY))
    result = rules.evaluate(_inputs([line], [_cost(date(2026, 9, 30), str(160 * 150))]))
    assert result.findings == []


def test_shift_by_a_month_is_not_a_case():
    # Faktura za IX przyszła z datą 05.11 (reguła daje X), a X ma swoją z 28.10:
    # razem IX + X zgadzają się z godzinami klienta.
    sales = [_sale("2026-09", "160"), _sale("2026-10", "160")]
    costs = [
        _cost(date(2026, 11, 5), str(160 * 150)),
        _cost(date(2026, 10, 28), str(160 * 150)),
    ]
    result = rules.evaluate(_inputs(sales, costs))
    assert _kinds(result) == []


def test_rate_unknown_is_counted_not_a_case():
    ctx = {(CAND, m): _ctx(rate=None) for m in ("2026-07",) + MONTHS + ("2026-11",)}
    result = rules.evaluate(
        _inputs(
            [_sale("2026-09", "160")], [_cost(date(2026, 9, 30), "99999")], context=ctx
        )
    )
    assert result.findings == []
    assert result.stats["2026-09"].skipped[rules.SKIP_NOT_COMPARABLE] == 1


# ── Brak faktury po jednej stronie ──────────────────────────────────────────


def test_cost_without_sale_after_the_15th():
    result = rules.evaluate(_inputs([], [_cost(date(2026, 10, 30), "24000")]))
    (finding,) = result.findings
    assert (finding.kind, finding.month, finding.amount) == (
        rules.COST_WITHOUT_SALE,
        "2026-10",
        Decimal("24000.00"),
    )


def test_cost_without_sale_waits_until_the_15th():
    result = rules.evaluate(
        _inputs([], [_cost(date(2026, 10, 30), "24000")], today=date(2026, 11, 14))
    )
    assert result.findings == []
    assert result.stats["2026-10"].skipped[rules.WAITING] == 1


def test_cost_without_sale_skipped_for_client_without_names():
    result = rules.evaluate(
        _inputs(
            [],
            [_cost(date(2026, 10, 30), "24000")],
            unnamed={"2026-10": frozenset({CLIENT})},
        )
    )
    assert result.findings == []
    assert result.stats["2026-10"].skipped[rules.SKIP_CLIENT] == 1


def test_cost_without_sale_skipped_while_sale_waits_for_buyer():
    result = rules.evaluate(
        _inputs(
            [],
            [_cost(date(2026, 10, 30), "24000")],
            unassigned=frozenset({(CAND, "2026-10")}),
        )
    )
    assert result.findings == []
    assert result.stats["2026-10"].skipped[rules.SKIP_UNASSIGNED] == 1


def test_cost_without_sale_marks_missing_contract_and_order():
    months = ("2026-07",) + MONTHS + ("2026-11",)
    no_contract = {
        (CAND, m): rules.Context(contract_id=CONTRACT, client_id=CLIENT, recent=True)
        for m in months
    }
    (finding,) = rules.evaluate(
        _inputs([], [_cost(date(2026, 10, 30), "24000")], context=no_contract)
    ).findings
    assert finding.data_issue == rules.NO_CONTRACT
    no_order = {(CAND, m): _ctx(has_order=False) for m in months}
    (finding,) = rules.evaluate(
        _inputs([], [_cost(date(2026, 10, 30), "24000")], context=no_order)
    ).findings
    assert finding.data_issue == rules.NO_ORDER


def test_cost_after_long_ended_contract_is_not_a_case():
    months = ("2026-07",) + MONTHS + ("2026-11",)
    result = rules.evaluate(
        _inputs(
            [],
            [_cost(date(2026, 10, 30), "24000")],
            context={(CAND, m): rules.Context() for m in months},
        )
    )
    assert result.findings == []
    assert result.stats["2026-10"].skipped[rules.SKIP_OUTSIDE] == 1


def test_sale_without_cost_needs_ksef_history():
    sales = [_sale("2026-10", "160")]
    assert (
        rules.evaluate(_inputs(sales, [])).stats["2026-10"].skipped[rules.SKIP_NO_KSEF]
        == 1
    )
    costs = [_cost(date(2026, 8, 31), str(160 * 150))]
    found = rules.evaluate(_inputs(sales + [_sale("2026-08", "160")], costs)).findings
    assert [(f.kind, f.month, f.amount) for f in found] == [
        (rules.SALE_WITHOUT_COST, "2026-10", Decimal("24000.00"))
    ]


def test_sale_without_cost_covered_by_double_invoice_next_month():
    # IX i X zafakturowane razem jedną fakturą z 30.10.
    sales = [_sale("2026-09", "160"), _sale("2026-10", "160")]
    result = rules.evaluate(_inputs(sales, [_cost(date(2026, 10, 30), str(320 * 150))]))
    assert result.findings == []


def test_correction_to_zero_leaves_month_without_cost():
    sales = [_sale("2026-09", "160"), _sale("2026-08", "160")]
    costs = [
        _cost(date(2026, 8, 31), str(160 * 150)),
        _cost(date(2026, 9, 30), str(160 * 150), number="FV/9"),
        _cost(date(2026, 10, 2), str(-160 * 150), correction=True, number="KOR/9"),
    ]
    found = rules.evaluate(_inputs(sales, costs)).findings
    assert [(f.kind, f.month) for f in found] == [(rules.SALE_WITHOUT_COST, "2026-09")]


# ── Pominięcia i dni robocze ────────────────────────────────────────────────


def test_parallel_contracts_are_skipped():
    months = ("2026-07",) + MONTHS + ("2026-11",)
    ctx = {
        (CAND, m): _ctx(live=(CONTRACT, CONTRACT + 1), contract_id=None) for m in months
    }
    result = rules.evaluate(
        _inputs([_sale("2026-09", "160")], [_cost(date(2026, 9, 30), "1")], context=ctx)
    )
    assert result.findings == []
    assert result.stats["2026-09"].skipped[rules.SKIP_PARALLEL] == 1


def test_over_working_days_only_when_contractor_does_not_confirm():
    # Październik: 22 dni robocze = 176 h; klient 200 h.
    sales = [_sale("2026-10", "200", net="30000")]
    confirmed = rules.evaluate(
        _inputs(sales, [_cost(date(2026, 10, 30), str(200 * 150))])
    )
    assert confirmed.findings == []
    assert confirmed.stats["2026-10"].overtime_confirmed == 1
    lower = rules.evaluate(_inputs(sales, [_cost(date(2026, 10, 30), str(176 * 150))]))
    kinds = _kinds(lower)
    assert (rules.OVER_WORKING_DAYS, "2026-10") in kinds
    over = next(f for f in lower.findings if f.kind == rules.OVER_WORKING_DAYS)
    assert over.details["excess_hours"] == "24.00"
    assert over.amount == Decimal("3600.00")


def test_finding_keys_are_stable():
    f = rules.Finding(
        rules.OVER_WORKING_DAYS, 5, "2026-10", None, 7, None, "PLN", None, {}
    )
    assert f.key == "over_working_days:5:2026-10:7"
    g = rules.Finding(
        rules.HOURS_MISMATCH, 5, "2026-10", None, 7, None, "PLN", None, {}
    )
    assert g.key == "hours_mismatch:5:2026-10"


# ── Miesiąc faktury konsultanta ─────────────────────────────────────────────


def test_assign_months_by_issue_day_and_best_fit():
    late = _cost(date(2026, 9, 26), "100")
    early = _cost(date(2026, 10, 8), "100")
    middle = _cost(date(2026, 10, 15), "200")
    out = rules.assign_months(
        [late, early, middle], {"2026-09": Decimal("100"), "2026-10": Decimal("200")}
    )
    assert sorted(d.number for d in out["2026-09"]) == sorted(
        [late.number, early.number]
    )
    assert [d.number for d in out["2026-10"]] == [middle.number]


def test_fixed_month_from_settlements_wins():
    doc = rules.CostDoc(
        CAND,
        "K/1",
        date(2026, 10, 3),
        Decimal("10"),
        "PLN",
        False,
        fixed_month="2026-10",
    )
    assert rules.assign_months([doc], {}) == {"2026-10": [doc]}


# ── Pozycje faktury ─────────────────────────────────────────────────────────


def _world() -> rh.World:
    rows = {
        CONTRACT: rh.ContractRow(CONTRACT, CAND, CLIENT, date(2025, 1, 1), None, True),
        CONTRACT + 1: rh.ContractRow(
            CONTRACT + 1, CAND + 1, CLIENT, date(2025, 1, 1), None, True
        ),
    }
    return rh.World(
        contracts=rows,
        person_tokens={
            CAND: frozenset({"jan", "przykladowy", "testowski"}),
            CAND + 1: frozenset({"anna", "zmyslona"}),
        },
        person_numbers={(CLIENT, "M000123"): {CONTRACT + 1}},
    )


def test_match_line_glued_person_number_and_short_double_surname():
    world = _world()
    names = {CAND: "Jan Przykładowy-Testowski", CAND + 1: "Anna Zmyślona"}
    glued = "NIDS: 1, Contact:Ktoś Inny, Contractor Ola NowakID: M000123"
    assert collect.match_line(world, names, CLIENT, "2026-10", glued) == CONTRACT + 1
    short = "IT, Contact: Ktoś Inny, Contractor Jan Przykładowy ID: X1"
    assert collect.match_line(world, names, CLIENT, "2026-10", short) == CONTRACT
    assert (
        collect.match_line(world, names, CLIENT, "2026-10", "Usługi IT bez nazwiska")
        is None
    )


class _Inv:
    def __init__(self, id_: int, items: list[dict], issue: date) -> None:
        self.id, self.items, self.issue_date = id_, items, issue


def test_chain_items_apply_corrections():
    root = _Inv(
        1,
        [
            {"name": "Usługi — Jan", "net": "100"},
            {"name": "Usługi — Anna", "net": "200"},
        ],
        date(2026, 10, 3),
    )
    cor = _Inv(
        2,
        [
            {"name": "Usługi — Anna", "net": "200", "before_correction": True},
            {"name": "Usługi — Anna", "net": "150"},
        ],
        date(2026, 10, 9),
    )
    items = collect.chain_items(root, [cor])
    assert [(i["name"], i["net"]) for i in items] == [
        ("Usługi — Jan", "100"),
        ("Usługi — Anna", "150"),
    ]
