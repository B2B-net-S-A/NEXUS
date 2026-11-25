"""Historia stawek z faktur KSeF — reguła i kolektor bez bazy (dane fikcyjne)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from app.services.contract_rate_history import collect, infer

TODAY = date(2026, 11, 25)


def obs(
    rates: dict[str, str], hours: str = "160"
) -> tuple[infer.MonthObservation, ...]:
    return tuple(
        infer.MonthObservation(
            month=m, rate=D(r), hours=D(hours), evidence=(f"FV/{m}",)
        )
        for m, r in rates.items()
    )


def contract(**kw) -> infer.ContractInput:
    base = dict(
        contract_id=1,
        start_date=date(2025, 1, 1),
        hourly_pln=True,
        client_schedule=(),
        cost_schedule=(),
        client_scalar=D("200"),
        cost_scalar=D("150"),
    )
    base.update(kw)
    return infer.ContractInput(**base)


SPRING = {"2026-04": "250", "2026-05": "250", "2026-06": "250"}
SUMMER = {"2026-07": "200", "2026-08": "200", "2026-09": "200", "2026-10": "200"}
COST_SPRING = {"2026-04": "190", "2026-05": "190", "2026-06": "190"}
COST_SUMMER = {"2026-07": "150", "2026-08": "150", "2026-09": "150", "2026-10": "150"}


def real(result: infer.ContractResult) -> list[infer.ProposedStep]:
    return [s for s in result.steps if not s.baseline]


# ── okresy ──────────────────────────────────────────────────────────────────


def test_period_needs_two_months_within_one_percent():
    found = infer.periods(obs({"2026-04": "100", "2026-05": "100.9", "2026-06": "130"}))
    assert [(p.months, p.rate) for p in found] == [
        (("2026-04", "2026-05"), D("100.45"))
    ]


def test_single_outlier_between_same_rate_does_not_break_period():
    found = infer.periods(
        obs({"2026-04": "150", "2026-05": "171.4", "2026-06": "150", "2026-07": "150"})
    )
    assert len(found) == 1
    assert found[0].months == ("2026-04", "2026-06", "2026-07")
    assert found[0].rate == D("150")


def test_median_snaps_to_whole_zloty():
    found = infer.periods(obs({"2026-04": "168.04", "2026-05": "168.1"}))
    assert found[0].rate == D("168")
    found = infer.periods(obs({"2026-04": "168.51", "2026-05": "168.51"}))
    assert found[0].rate == D("168.51")


# ── resolver = lustro Contract._resolve_scheduled_rate ──────────────────────


def test_rate_on_before_first_step_reads_earliest_step_not_column():
    schedule = (
        infer.Step(date(2026, 7, 1), D("120")),
        infer.Step(date(2026, 7, 1), D("130")),
    )
    assert infer.rate_on(schedule, D("999"), date(2026, 3, 1)) == D("130")
    assert infer.rate_on((), D("999"), date(2026, 3, 1)) == D("999")


# ── kategorie i kroki ───────────────────────────────────────────────────────


def test_no_history_both_legs_changed_together_is_automatic():
    result = infer.infer(
        contract(
            client_obs=obs({**SPRING, **SUMMER}),
            cost_obs=obs({**COST_SPRING, **COST_SUMMER}),
        ),
        TODAY,
    )
    assert result.category == infer.NO_HISTORY
    assert result.automatic
    steps = [(s.leg, s.effective_from, s.rate, s.baseline) for s in result.steps]
    assert steps == [
        ("client", date(2025, 1, 1), D("200"), True),
        ("client", date(2026, 4, 1), D("250"), False),
        ("client", date(2026, 7, 1), D("200"), False),
        ("cost", date(2025, 1, 1), D("150"), True),
        ("cost", date(2026, 4, 1), D("190"), False),
        ("cost", date(2026, 7, 1), D("150"), False),
    ]
    # Skutek: (250 − 200) × 160 h × 3 miesiące.
    assert real(result)[0].impact == D("24000.00")
    assert real(result)[0].evidence == ("FV/2026-04", "FV/2026-05", "FV/2026-06")


def test_return_step_uses_exact_nexus_value_when_close():
    result = infer.infer(
        contract(
            cost_scalar=D("169"),
            cost_obs=obs(
                {
                    "2026-04": "245",
                    "2026-05": "245",
                    "2026-06": "169.96",
                    "2026-07": "169",
                }
            ),
        ),
        TODAY,
    )
    assert [s.rate for s in real(result)] == [D("245"), D("169")]


def test_current_gap_changes_today_and_is_never_automatic():
    result = infer.infer(contract(client_obs=obs(SUMMER, hours="168")), TODAY)
    assert result.category == infer.OK
    result = infer.infer(
        contract(client_obs=obs({"2026-09": "210", "2026-10": "210"})), TODAY
    )
    assert result.category == infer.CURRENT_GAP
    assert not result.automatic
    assert infer.REASON_TODAY in real(result)[0].reasons


def test_past_one_leg_without_baseline_when_older_step_exists():
    schedule = (infer.Step(date(2024, 1, 1), D("150")),)
    result = infer.infer(
        contract(
            cost_schedule=schedule,
            cost_obs=obs({**COST_SPRING, **COST_SUMMER}),
        ),
        TODAY,
    )
    assert result.category == infer.PAST_ONE_LEG
    assert result.automatic
    assert not any(s.baseline for s in result.steps)


def test_human_step_inside_period_needs_review():
    schedule = (
        infer.Step(date(2025, 1, 1), D("150")),
        infer.Step(date(2026, 5, 1), D("190")),
        infer.Step(date(2026, 8, 1), D("150")),
    )
    result = infer.infer(
        contract(cost_schedule=schedule, cost_obs=obs({**COST_SPRING, **COST_SUMMER})),
        TODAY,
    )
    assert not result.automatic
    assert all(infer.REASON_HUMAN_STEP in s.reasons for s in real(result))


def test_gap_between_periods_makes_date_uncertain():
    result = infer.infer(
        contract(
            cost_obs=obs(
                {"2026-04": "190", "2026-05": "190", "2026-09": "150", "2026-10": "150"}
            )
        ),
        TODAY,
    )
    assert not result.automatic
    assert infer.REASON_GAP in real(result)[-1].reasons


def test_later_unexplained_month_blocks_open_ended_step():
    result = infer.infer(
        contract(cost_obs=obs({**COST_SPRING, "2026-07": "150", "2026-08": "173"})),
        TODAY,
    )
    # 150 jest tylko jednym miesiącem — krok 190 sięgałby do dziś.
    assert not result.automatic


def test_big_change_unit_before_start_and_open_settlement_need_review():
    big = infer.infer(
        contract(client_scalar=D("7.27"), client_obs=obs({**SPRING, **SUMMER})), TODAY
    )
    assert infer.REASON_BIG in real(big)[0].reasons
    unit = infer.infer(
        contract(hourly_pln=False, client_obs=obs({**SPRING, **SUMMER})), TODAY
    )
    assert infer.REASON_UNIT in real(unit)[0].reasons
    early = infer.infer(
        contract(start_date=date(2026, 5, 10), client_obs=obs({**SPRING, **SUMMER})),
        TODAY,
    )
    assert infer.REASON_BEFORE_START in real(early)[0].reasons
    open_month = infer.infer(
        contract(
            client_obs=obs({**SPRING, **SUMMER}),
            open_settlement_months=frozenset({"2026-10"}),
        ),
        TODAY,
    )
    assert not open_month.automatic
    assert infer.REASON_OPEN_SETTLEMENT in real(open_month)[0].reasons


def test_no_start_date_with_empty_schedule_needs_review():
    result = infer.infer(
        contract(start_date=None, client_obs=obs({**SPRING, **SUMMER})), TODAY
    )
    assert not result.automatic
    assert infer.REASON_NO_START in real(result)[0].reasons


def test_single_month_is_not_proof():
    result = infer.infer(contract(client_obs=obs({"2026-04": "250"})), TODAY)
    assert result.category == infer.OK
    assert not result.steps


# ── kolektor ────────────────────────────────────────────────────────────────


def world() -> collect.World:
    contracts = {
        10: collect.ContractRow(10, 100, 7, date(2025, 1, 1), None, True),
        11: collect.ContractRow(11, 101, 7, date(2025, 1, 1), None, True),
        12: collect.ContractRow(12, 102, 8, date(2025, 1, 1), None, True),
        # Imiennik u innego klienta.
        13: collect.ContractRow(13, 103, 8, date(2025, 1, 1), None, True),
    }
    return collect.World(
        contracts=contracts,
        person_tokens={
            100: frozenset({"jan", "testowy"}),
            101: frozenset({"anna", "przykladowa"}),
            102: frozenset({"ewa", "fikcyjna"}),
            103: frozenset({"ewa", "fikcyjna"}),
        },
        person_numbers={(7, "M000001"): {10}},
    )


def test_unit_hours():
    assert collect.unit_hours("godz.") == D(1)
    assert collect.unit_hours("MD") == D(8)
    assert collect.unit_hours("szt.") is None


def test_match_item_by_person_number_then_full_name():
    w = world()
    assert (
        collect.match_item(
            w, 7, "2026-05", "NIDS:1, Contact: Anna Przykladowa, ID: M000001"
        )
        == 10
    )
    assert collect.match_item(w, 7, "2026-05", "Contractor:Anna Przykładowa") == 11
    assert collect.match_item(w, 7, "2026-05", "Usługi IT Jan") is None
    # Dwie osoby o tym samym imieniu i nazwisku u klienta = bez kontraktu.
    assert collect.match_item(w, 8, "2026-05", "Ewa Fikcyjna") is None


def test_cost_month_rule_25th_day_and_window():
    rows = [
        collect.CostRow(
            "K1", "Jan Testowy IT", date(2026, 5, 28), "PLN", D("1"), False
        ),
        collect.CostRow(
            "K2", "Jan Testowy IT", date(2026, 6, 10), "PLN", D("1"), False
        ),
        collect.CostRow("K3", "Jan Testowy IT", date(2026, 7, 5), "PLN", D("1"), False),
    ]
    months = collect.cost_months(rows, hours_months={"2026-05", "2026-06"})
    assert [r.invoice_number for r in months["2026-05"]] == ["K1"]
    # 10.06: maj ma już fakturę z końca miesiąca, a czerwiec ma godziny → czerwiec.
    # 05.07: czerwiec nie ma faktury z końca miesiąca → czerwiec (dwie faktury
    # w miesiącu dają stawkę ×2, którą odrzuca warunek stałej stawki).
    assert [r.invoice_number for r in months["2026-06"]] == ["K2", "K3"]
    assert "2026-07" not in months


def test_build_inputs_client_price_and_cost_rate():
    w = world()
    sales = [
        collect.SalesRow(
            f"FS/{m}",
            7,
            m,
            date(2026, int(m[5:]) + 1, 3),
            "PLN",
            False,
            (
                {
                    "name": "Contractor Jan Testowy",
                    "unit": "godz.",
                    "quantity": "160",
                    "unit_price": "200",
                    "net": "31200",
                },
                {
                    "name": "Jan Testowy nadgodziny",
                    "unit": "godz.",
                    "quantity": "8",
                    "unit_price": "300",
                    "net": "2400",
                },
                {
                    "name": "Jan Testowy hotel",
                    "unit": "szt.",
                    "quantity": "1",
                    "unit_price": "500",
                    "net": "500",
                },
            ),
        )
        for m in ("2026-04", "2026-05")
    ]
    costs = [
        collect.CostRow(
            "K/04", "JT Jan Testowy", date(2026, 4, 28), "PLN", D("24000"), False
        ),
        collect.CostRow(
            "K/05", "JT Jan Testowy", date(2026, 5, 29), "PLN", D("24000"), False
        ),
    ]
    inputs = collect.build_inputs(w, sales, costs, {"2026-04", "2026-05"})
    assert [i.contract_id for i in inputs] == [10]
    item = inputs[0]
    assert [(o.month, o.rate, o.hours) for o in item.client_obs] == [
        ("2026-04", D("200"), D("160")),
        ("2026-05", D("200"), D("160")),
    ]
    assert [o.rate for o in item.cost_obs] == [D("150"), D("150")]


def test_build_inputs_link_names_person_and_correction_drops_cost():
    w = world()
    sales = [
        collect.SalesRow(
            "FS/1",
            7,
            "2026-04",
            date(2026, 5, 3),
            "PLN",
            False,
            (
                {
                    "name": "Praca kontraktora: 414097",
                    "unit": "MD",
                    "quantity": "20",
                    "unit_price": "1600",
                },
            ),
            linked_contracts=frozenset({11}),
        ),
        collect.SalesRow(
            "KOR/1",
            7,
            "2026-04",
            date(2026, 5, 20),
            "PLN",
            True,
            (
                {
                    "name": "Praca kontraktora: 414097",
                    "unit": "MD",
                    "quantity": "19",
                    "unit_price": "1600",
                },
            ),
            linked_contracts=frozenset({11}),
        ),
    ]
    costs = [
        collect.CostRow(
            "K/1", "Anna Przykładowa", date(2026, 4, 30), "PLN", D("20000"), False
        )
    ]
    inputs = collect.build_inputs(w, sales, costs, {"2026-04"})
    assert inputs[0].contract_id == 11
    assert inputs[0].client_obs[0].rate == D("200")
    # Korekta z osobą w miesiącu = godziny niepewne → bez obserwacji kosztu.
    assert inputs[0].cost_obs == ()


def test_nexus_rate_on_card_is_the_contract_rate_before_proposals():
    result = infer.infer(contract(client_obs=obs({**SPRING, **SUMMER})), TODAY)
    # Drugi krok (powrót do 200) pokazuje w „W kontrakcie” 200, nie 250 z propozycji.
    assert [(s.rate, s.nexus_rate) for s in real(result)] == [
        (D("250"), D("200")),
        (D("200"), D("200")),
    ]
