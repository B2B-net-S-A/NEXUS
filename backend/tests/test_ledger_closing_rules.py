"""Lista zamknięcia miesiąca (K3d) — reguły bez bazy: terminy i pozycje listy."""

from __future__ import annotations

from datetime import date

from app.services.ledger import closing


def _due(year: int, month: int) -> dict[str, tuple[date, date]]:
    return {item.key: (item.nominal, item.due) for item in closing.deadlines(year, month)}


def test_october_deadlines_move_from_sunday_to_monday():
    due = _due(2026, 10)
    # 15.11.2026 to niedziela — ZUS i PPK w poniedziałek.
    assert due["zus"] == (date(2026, 11, 15), date(2026, 11, 16))
    assert due["ppk"] == (date(2026, 11, 15), date(2026, 11, 16))
    assert due["pit"] == (date(2026, 11, 20), date(2026, 11, 20))
    assert due["vat"] == (date(2026, 11, 25), date(2026, 11, 25))


def test_holidays_and_weekends_push_the_deadline():
    # 15.08.2026: sobota i Wniebowzięcie → poniedziałek 17.08.
    assert _due(2026, 7)["zus"] == (date(2026, 8, 15), date(2026, 8, 17))
    # 25.12.2026: Boże Narodzenie (piątek), 26.12 sobota i święto, 27.12 niedziela.
    assert _due(2026, 11)["vat"] == (date(2026, 12, 25), date(2026, 12, 28))


def test_december_deadlines_fall_in_january_of_next_year():
    due = _due(2026, 12)
    assert due["zus"] == (date(2027, 1, 15), date(2027, 1, 15))
    assert due["pit"] == (date(2027, 1, 20), date(2027, 1, 20))
    assert due["vat"] == (date(2027, 1, 25), date(2027, 1, 25))
    assert [item.key for item in closing.deadlines(2026, 12)] == ["zus", "ppk", "pit", "vat"]


def test_business_day_stays_put():
    assert closing.next_business_day(date(2026, 11, 20)) == date(2026, 11, 20)


def _summary_item(**counts) -> dict:
    item = {
        "kind": "costs",
        "label": "Faktury kosztowe",
        "total": 3,
        "to_post": 0,
        "changed": 0,
        "problems_total": 0,
    }
    item.update(counts)
    return item


def test_source_check_states():
    href = "/accounting/sources?year=2026&month=10"
    problem = closing.source_check(_summary_item(to_post=2, problems_total=1), href)
    assert problem["state"] == "problem"
    assert problem["detail"] == "do zaksięgowania: 2, do wyjaśnienia: 1"
    todo = closing.source_check(_summary_item(to_post=1, changed=1), href)
    assert todo["state"] == "todo" and todo["detail"] == "do zaksięgowania: 2"
    done = closing.source_check(_summary_item(), href)
    assert done["state"] == "ok" and done["detail"] == "w księdze"
    empty = closing.source_check(_summary_item(total=0), href)
    assert empty["state"] == "ok" and empty["detail"] == "nic w tym miesiącu"
    assert done["key"] == "source:costs" and done["href"] == href


def test_symfonia_check_lists_what_is_missing():
    href = "/accounting/symfonia?year=2026&month=10"
    todo = closing.symfonia_check({"outside": 2, "waiting": ["K/2026-10/1"]}, href)
    assert todo["state"] == "todo"
    assert todo["detail"] == (
        "zatwierdzone poza paczką: 2; czeka na „Zaksięgowana w Symfonii”: K/2026-10/1"
    )
    done = closing.symfonia_check({"outside": 0, "waiting": []}, href)
    assert done["state"] == "ok" and done["detail"] == "wszystko w paczkach"
