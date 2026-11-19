"""Różnica stawki z dokumentów kontraktu vs harmonogram (bez bazy).

Kwoty i daty zmyślone; układy przypadków z przeglądu plików 18.11.2026.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.contract_rate_documents import compare as c

TODAY = date(2026, 11, 18)


def contract(start=date(2026, 4, 1), baseline="100", schedule=(), currency="PLN"):
    return c.ContractRates(
        start_date=start,
        currency=currency,
        baseline_rate=Decimal(baseline) if baseline is not None else None,
        schedule=tuple(
            c.ScheduleStep(date.fromisoformat(f), Decimal(r)) for f, r in schedule
        ),
    )


def read(
    read_id, steps, kind="annex", effective=None, doc_date="2026-10-01", dismissed=False
):
    return c.ReadInput(
        read_id=read_id,
        dismissed=dismissed,
        result={
            "kind": kind,
            "changes_rate": True,
            "document_date": doc_date,
            "effective_from": effective,
            "rate_steps": [
                {
                    "rate": r,
                    "currency": cur,
                    "unit": unit,
                    "from": f,
                    "to": t,
                    "condition": cond,
                }
                for (r, f, t, unit, cur, cond) in (
                    (s + (None,) * (6 - len(s))) for s in steps
                )
            ],
        },
    )


def step(rate, frm=None, to=None, unit="hour", currency="PLN", condition=None):
    return (rate, frm, to, unit, currency, condition)


def test_annex_unknown_to_nexus_is_auto():
    out = c.compare(contract(), [read(1, [step(110, "2026-11-01")])], TODAY)
    f = out[1]
    assert f is not None and f.category == "auto"
    assert f.steps == [
        {
            "from": "2026-11-01",
            "to": None,
            "rate": 110.0,
            "nexus_rate": 100.0,
            "condition": None,
        }
    ]


def test_annex_effective_date_used_when_step_has_no_date():
    out = c.compare(contract(), [read(1, [step(110)], effective="2026-12-01")], TODAY)
    assert out[1].steps[0]["from"] == "2026-12-01"


def test_matching_document_gives_no_finding():
    out = c.compare(
        contract(), [read(1, [step(100, "2026-04-01")], kind="contract")], TODAY
    )
    assert out[1] is None


def test_progressive_contract_reports_only_unknown_step():
    out = c.compare(
        contract(schedule=[("2026-04-01", "100")]),
        [
            read(
                1,
                [step(100, "2026-04-01", "2026-10-31"), step(105, "2026-11-01")],
                kind="contract",
            )
        ],
        TODAY,
    )
    assert [s["from"] for s in out[1].steps] == ["2026-11-01"]
    assert out[1].category == "auto"


def test_past_step_of_same_annex_is_included():
    # 130 od 09 do 10, potem 140 od 11 — oba kroki, nie tylko „dziś”.
    out = c.compare(
        contract(baseline="120"),
        [read(1, [step(130, "2026-09-01", "2026-10-31"), step(140, "2026-11-01")])],
        TODAY,
    )
    assert [(s["from"], s["rate"]) for s in out[1].steps] == [
        ("2026-09-01", 130.0),
        ("2026-11-01", 140.0),
    ]


def test_future_step_is_reported():
    out = c.compare(
        contract(schedule=[("2026-04-01", "100")]),
        [
            read(
                1,
                [step(100, "2026-04-01", "2026-12-31"), step(104, "2027-01-01")],
                kind="contract",
            )
        ],
        TODAY,
    )
    assert out[1].steps[0]["from"] == "2027-01-01"


def test_old_history_superseded_by_newer_document_is_ignored():
    old = read(1, [step(80, "2019-01-01")], kind="contract", doc_date="2018-12-01")
    new = read(2, [step(100, "2026-04-01")], kind="contract", doc_date="2026-03-01")
    out = c.compare(contract(), [old, new], TODAY)
    assert out[1] is None and out[2] is None


def test_previous_agreement_window_before_contract_start_is_ignored():
    prev = read(1, [step(90, "2026-01-01", "2026-03-31")], kind="contract")
    out = c.compare(contract(), [prev], TODAY)
    assert out[1] is None


def test_two_documents_disagreeing_on_same_day_go_to_review():
    a = read(1, [step(110, "2026-11-01")])
    b = read(2, [step(115, "2026-11-01")])
    out = c.compare(contract(), [a, b], TODAY)
    assert out[1].category == "review" and c.REASON_CONFLICT in out[1].reasons
    assert out[2].category == "review"


def test_dismissed_read_does_not_compete():
    a = read(1, [step(110, "2026-11-01")])
    b = read(2, [step(115, "2026-11-01")], dismissed=True)
    out = c.compare(contract(), [a, b], TODAY)
    assert out[1].category == "auto" and out[2] is None


def test_nexus_newer_change_goes_to_review():
    out = c.compare(
        contract(schedule=[("2026-04-01", "100"), ("2026-10-01", "95")]),
        [read(1, [step(110, "2026-06-01")])],
        TODAY,
    )
    assert out[1].category == "review" and c.REASON_NEXUS_NEWER in out[1].reasons


def test_condition_step_goes_to_review():
    out = c.compare(
        contract(), [read(1, [step(110, condition="po okresie próbnym")])], TODAY
    )
    assert out[1].category == "review" and c.REASON_CONDITION in out[1].reasons


def test_other_currency_goes_to_review():
    out = c.compare(
        contract(), [read(1, [step(30, "2026-11-01", currency="EUR")])], TODAY
    )
    assert out[1].category == "review" and c.REASON_UNIT in out[1].reasons


def test_monthly_rate_on_hourly_contract_goes_to_review():
    out = c.compare(
        contract(), [read(1, [step(16000, "2026-11-01", unit="month")])], TODAY
    )
    assert c.REASON_UNIT in out[1].reasons


def test_day_rate_is_compared_per_hour():
    out = c.compare(contract(), [read(1, [step(800, "2026-11-01", unit="day")])], TODAY)
    assert out[1] is None


def test_change_over_threshold_goes_to_review():
    out = c.compare(contract(), [read(1, [step(150, "2026-11-01")])], TODAY)
    assert out[1].category == "review" and c.REASON_BIG in out[1].reasons


def test_document_without_rate_gives_no_finding():
    r = c.ReadInput(
        read_id=1, result={"kind": "other", "changes_rate": False, "rate_steps": []}
    )
    assert c.compare(contract(), [r], TODAY) == {1: None}


def test_rate_on_same_day_later_entry_wins():
    k = contract(schedule=[("2026-04-01", "100"), ("2026-04-01", "105")])
    assert c.rate_on(k, date(2026, 5, 1)) == Decimal("105")


def test_rate_on_only_future_steps_uses_earliest():
    k = contract(schedule=[("2027-01-01", "120"), ("2027-06-01", "130")])
    assert c.rate_on(k, date(2026, 11, 1)) == Decimal("120")


def test_rate_on_empty_schedule_uses_baseline():
    assert c.rate_on(contract(baseline="99"), TODAY) == Decimal("99")


def test_old_step_still_in_force_goes_to_review():
    out = c.compare(
        contract(start=date(2023, 4, 1), baseline="105"),
        [read(1, [step(100, "2023-10-01")], kind="contract", doc_date="2023-03-01")],
        TODAY,
    )
    assert out[1].category == "review" and c.REASON_OLD in out[1].reasons


def test_newer_annex_supersedes_older_contract_step():
    contract_doc = read(
        1, [step(130, "2026-08-03")], kind="contract", doc_date="2026-06-03"
    )
    annex = read(
        2,
        [step(120, "2026-07-27", "2026-12-31"), step(125, "2027-01-01")],
        doc_date="2026-06-11",
    )
    out = c.compare(
        contract(start=date(2026, 7, 27), baseline="120"), [contract_doc, annex], TODAY
    )
    assert out[1] is None
    assert out[2].category == "auto"
    assert [s["from"] for s in out[2].steps] == ["2027-01-01"]


def test_per_client_rates_in_one_annex_go_to_review():
    annex = read(
        1,
        [
            step(130, "2026-07-01", condition="klient A"),
            step(125, "2026-07-01", condition="klient B"),
        ],
    )
    out = c.compare(contract(baseline="130"), [annex], TODAY)
    assert out[1].category == "review"
    assert c.REASON_SAME_DOC in out[1].reasons and c.REASON_CONDITION in out[1].reasons
