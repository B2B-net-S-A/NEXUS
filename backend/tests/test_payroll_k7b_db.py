"""Płace K7b z bazą: pensja UoP z L4 z modułu urlopów, oznaczenie Płac, składniki,
historia podstaw z Enovy, porównanie z listą z Enovy i odmowy.

Ścieżki odmowy: własna pensja (403), pensja osobie spoza UoP (422), pensja nie od
1. dnia (422), oznaczenie własnego L4 (403), oznaczenie nie-L4 (404), zmiana
składnika, pensji i oznaczenia przy zatwierdzonej liście (409), usunięcie pensji
użytej przez zatwierdzoną listę (409), import historii z nieznaną osobą (422).
Osoby i kwoty fikcyjne; rok losowy z odległej przyszłości (fixture ``world`` K7a).
"""

# ruff: noqa: F811  (fixture z innego pliku jako parametr testu)
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.hr_payroll_k7b import (
    PayrollAbsenceMark,
    PayrollBasisMonth,
    PayrollComponent,
    PayrollSalary,
)
from app.models.hr_payroll_lists import PayrollPersonData
from tests.hr_settlements_seed import add_line, headers, make_user
from tests.test_payroll_lists_db import (  # noqa: F401  (fixture ``client``, ``world``)
    BASE,
    _compute,
    _fill_people,
    _full_data,
    _line,
    _zero_foreign_contracts,
    client,
    world,
)


async def _leave(user_id: int, kind: str, start: date, end: date) -> LeaveRequest:
    async with AsyncSessionLocal() as db:
        request = LeaveRequest(
            user_id=user_id,
            leave_type=kind,
            status="approved",
            start_date=start,
            end_date=end,
            source="on_behalf",
        )
        db.add(request)
        await db.flush()
        day = start
        while day <= end:
            if day.weekday() < 5:
                db.add(
                    LeaveRequestDay(
                        leave_request_id=request.id,
                        user_id=user_id,
                        day=day,
                        fraction=Decimal("1.0"),
                        paid=False,
                        active=True,
                    )
                )
            day += timedelta(days=1)
        await db.commit()
        return request


@pytest_asyncio.fixture
async def k7b(world):
    w = world
    hired = date(2020, 1, 1)
    w.salaried = await make_user(
        "employee", employment_type="uop", hired_on=hired, work_start_date=hired
    )
    w.payroll_uop = await make_user(
        "recruiter", grants=("payroll",), employment_type="uop"
    )
    await add_line(
        w.period_id,
        w.salaried,
        employment_type="uop",
        hours="0",
        rate=None,
        bonus_total="500",
    )
    # Pon. 1.10 roku testu może wypaść w dowolny dzień tygodnia — L4 na 5 dni kalendarzowych.
    w.sick = await _leave(
        w.salaried.id, "sick_leave", date(w.year, 10, 6), date(w.year, 10, 10)
    )
    w.vacation = await _leave(
        w.salaried.id, "vacation", date(w.year, 10, 20), date(w.year, 10, 21)
    )
    yield w
    async with AsyncSessionLocal() as db:
        ids = [w.salaried.id, w.payroll_uop.id]
        await db.execute(
            delete(PayrollAbsenceMark).where(PayrollAbsenceMark.user_id.in_(ids))
        )
        await db.execute(
            delete(LeaveRequestDay).where(LeaveRequestDay.user_id.in_(ids))
        )
        await db.execute(delete(LeaveRequest).where(LeaveRequest.user_id.in_(ids)))
        await db.execute(
            delete(PayrollComponent).where(PayrollComponent.user_id.in_(ids))
        )
        await db.execute(delete(PayrollSalary).where(PayrollSalary.user_id.in_(ids)))
        await db.execute(
            delete(PayrollBasisMonth).where(PayrollBasisMonth.user_id.in_(ids))
        )
        await db.execute(
            delete(PayrollPersonData).where(PayrollPersonData.user_id.in_(ids))
        )
        await db.commit()


async def _salary(client, w, user, *, amount="8000", start=None, actor=None):
    return await client.put(
        f"{BASE}/salaries/users/{user.id}",
        json={"monthly_amount": amount, "effective_from": start or f"{w.year}-01-01"},
        headers=headers(actor or w.payroll1),
    )


async def _person(client, w) -> None:
    response = await client.put(
        f"{BASE}/people/users/{w.salaried.id}",
        json=_full_data(date(1990, 3, 3), 5321, sickness_insured_since="2020-01-01"),
        headers=headers(w.hr),
    )
    assert response.status_code == 200, response.text
    assert response.json()["sickness_insured_since"] == "2020-01-01"


@pytest.mark.asyncio
async def test_salary_refusals(client, k7b) -> None:
    w = k7b
    own = await _salary(client, w, w.payroll_uop, actor=w.payroll_uop)
    assert own.status_code == 403
    not_uop = await _salary(client, w, w.mandate)
    assert not_uop.status_code == 422
    mid_month = await _salary(client, w, w.salaried, start=f"{w.year}-01-15")
    assert mid_month.status_code == 422
    outsider = await client.get(f"{BASE}/salaries", headers=headers(w.recruiter))
    assert outsider.status_code == 403
    saved = await _salary(client, w, w.salaried)
    assert saved.status_code == 200, saved.text
    raise_ = await _salary(
        client, w, w.salaried, amount="8400", start=f"{w.year}-06-01"
    )
    assert raise_.status_code == 200, raise_.text
    rows = [row for row in raise_.json()["salaries"] if row["user_id"] == w.salaried.id]
    assert [row["effective_to"] for row in rows] == [None, f"{w.year}-05-31"]


@pytest.mark.asyncio
async def test_salary_with_sick_leave_marked_100_and_components(client, k7b) -> None:
    w = k7b
    await _person(client, w)
    assert (await _salary(client, w, w.salaried)).status_code == 200
    listed = await client.get(
        f"{BASE}/months/{w.year}/10/absences", headers=headers(w.payroll1)
    )
    assert listed.status_code == 200
    kinds = {item["leave_type"] for item in listed.json()["absences"]}
    assert {"sick_leave", "vacation"} <= kinds
    own = await client.put(
        f"{BASE}/absences/{w.sick.id}/mark",
        json={"sick_rate": "100"},
        headers=headers(w.salaried),
    )
    assert own.status_code in (403, 404)  # osoba bez Płac nie ma tu wstępu
    not_sick = await client.put(
        f"{BASE}/absences/{w.vacation.id}/mark",
        json={"sick_rate": "100"},
        headers=headers(w.payroll1),
    )
    assert not_sick.status_code == 404
    marked = await client.put(
        f"{BASE}/absences/{w.sick.id}/mark",
        json={"sick_rate": "100", "note": "wypadek w drodze do pracy"},
        headers=headers(w.payroll1),
    )
    assert marked.status_code == 200, marked.text

    payload = await _compute(client, w)
    line = _line(payload, user_id=w.salaried.id)
    assert line["source"] == "salary"
    k7b_data = line["basis"]["k7b"]
    (part,) = k7b_data["sick"]
    # Bez historii podstaw — podstawa z pensji (art. 37): 8000 − 13,71%.
    assert part["base"] == "6903.20" and part["rate"] == "100"
    assert part["paid_days"] == 5 and part["amount"] == "1150.55"
    assert k7b_data["salary_part"] == "6666.67"
    assert line["gross"] == "8317.22"  # pensja + chorobowe + premia 500
    assert line["result"]["insured_gross"] == "7166.67"  # bez chorobowego
    assert any(note["code"] == "sick_pay" for note in line["k7b_notes"])

    added = await client.put(
        f"{BASE}/months/{w.year}/10/components",
        json={
            "user_id": w.salaried.id,
            "kind": "variable",
            "amount": "300",
            "note": "nadgodziny",
        },
        headers=headers(w.payroll1),
    )
    assert added.status_code == 200, added.text
    assert added.json()["components"][0]["kind"] == "variable"
    payload = await _compute(client, w)
    assert _line(payload, user_id=w.salaried.id)["gross"] == "8617.22"


@pytest.mark.asyncio
async def test_approved_list_freezes_salary_components_and_marks(client, k7b) -> None:
    w = k7b
    await _person(client, w)
    await _fill_people(client, w)
    assert (await _salary(client, w, w.salaried)).status_code == 200
    contractor = await client.put(
        f"{BASE}/months/{w.year}/10/inputs",
        json={
            "contract_id": w.contract_id,
            "kind": "zlecenie",
            "gross": "7056.00",
            "note": "Rachunek",
        },
        headers=headers(w.payroll1),
    )
    assert contractor.status_code == 200, contractor.text
    payload = await _zero_foreign_contracts(client, w, await _compute(client, w))
    approve = await client.post(
        f"{BASE}/lists/{payload['list']['id']}/approve", headers=headers(w.payroll2)
    )
    assert approve.status_code == 200, approve.text
    component = await client.put(
        f"{BASE}/months/{w.year}/10/components",
        json={
            "user_id": w.salaried.id,
            "kind": "other",
            "amount": "100",
            "note": "nagroda",
        },
        headers=headers(w.payroll1),
    )
    assert component.status_code == 409
    salary = await _salary(
        client, w, w.salaried, amount="9000", start=f"{w.year}-10-01"
    )
    assert salary.status_code == 409
    mark = await client.put(
        f"{BASE}/absences/{w.sick.id}/mark",
        json={"sick_rate": "80"},
        headers=headers(w.payroll1),
    )
    assert mark.status_code == 409
    async with AsyncSessionLocal() as db:
        salary_id = await db.scalar(
            select(PayrollSalary.id).where(PayrollSalary.user_id == w.salaried.id)
        )
    removed = await client.delete(
        f"{BASE}/salaries/{salary_id}", headers=headers(w.payroll1)
    )
    assert removed.status_code == 409


def _history_csv(name: str, year: int) -> bytes:
    rows = [
        "Pracownik;Okres;Stałe wypłacone;Stałe za pełny miesiąc;Zmienne;"
        "Godziny nominalne;Godziny przepracowane"
    ]
    for month in range(1, 10):
        rows.append(f"{name};{year}-{month:02d};8000,00;8000,00;400,00;160;160")
    return "\r\n".join(rows).encode("utf-8")


@pytest.mark.asyncio
async def test_history_import_preview_save_and_unknown_person(client, k7b) -> None:
    w = k7b
    content = _history_csv(w.salaried.name, w.year)
    preview = await client.post(
        f"{BASE}/basis-history/import",
        files={"file": ("historia.csv", content, "text/csv")},
        headers=headers(w.payroll1),
    )
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["rows"]) == 9 and preview.json()["errors"] == []
    saved = await client.post(
        f"{BASE}/basis-history/import",
        params={"save": "true"},
        files={"file": ("historia.csv", content, "text/csv")},
        headers=headers(w.payroll1),
    )
    assert saved.status_code == 200 and saved.json()["saved"] is True
    async with AsyncSessionLocal() as db:
        count = len(
            list(
                await db.scalars(
                    select(PayrollBasisMonth).where(
                        PayrollBasisMonth.user_id == w.salaried.id
                    )
                )
            )
        )
    assert count == 9
    unknown = _history_csv("Nieznana Osoba Zupełnie", w.year)
    refused = await client.post(
        f"{BASE}/basis-history/import",
        params={"save": "true"},
        files={"file": ("historia.csv", unknown, "text/csv")},
        headers=headers(w.payroll1),
    )
    assert refused.status_code == 422
    # Z historią podstawa chorobowego to średnia z pełnych miesięcy (zmienne 400 zł).
    await _person(client, w)
    assert (await _salary(client, w, w.salaried)).status_code == 200
    payload = await _compute(client, w)
    part = _line(payload, user_id=w.salaried.id)["basis"]["k7b"]["sick"][0]
    assert part["base"] == "7248.36"  # 8400 − 13,71%


@pytest.mark.asyncio
async def test_compare_with_enova_person_by_person(client, k7b) -> None:
    w = k7b
    await _person(client, w)
    assert (await _salary(client, w, w.salaried)).status_code == 200
    payload = await _compute(client, w)
    line = _line(payload, user_id=w.salaried.id)
    r = line["result"]

    def money(value: str) -> str:
        return value.replace(".", ",")

    header = (
        "Pracownik;Razem brutto;Emerytalne prac.;Rentowe prac.;Chorobowe;Zdrowotne;"
        "Zaliczka podatku;PPK pracownika;Do wypłaty;Emerytalne pracodawca;"
        "Rentowe pracodawca;Wypadkowe;FP;FGŚP;PPK pracodawcy"
    )
    values = [
        r["gross"],
        r["pension_employee"],
        r["disability_employee"],
        r["sickness_employee"],
        r["health"],
        r["pit"],
        r["ppk_employee"],
        r["net"],
        r["pension_employer"],
        r["disability_employer"],
        r["accident_employer"],
        r["labour_fund"],
        r["fgsp"],
        r["ppk_employer"],
    ]
    surname_first = " ".join(reversed(w.salaried.name.split(" ", 1)))
    row = ";".join([surname_first, *(money(v) for v in values)])
    content = "\r\n".join([header, row]).encode("utf-8")
    compared = await client.post(
        f"{BASE}/lists/{payload['list']['id']}/compare-enova",
        files={"file": ("enova.csv", content, "text/csv")},
        headers=headers(w.payroll1),
    )
    assert compared.status_code == 200, compared.text
    body = compared.json()
    person = next(p for p in body["people"] if p["person"] == w.salaried.name)
    assert person["equal"] is True
    assert body["summary"]["only_enova"] == 0
    # Grosz różnicy w zaliczce i w wypłacie widać per osoba.
    values[5] = str(Decimal(values[5]) + 1)
    values[7] = str(Decimal(values[7]) - 1)
    row = ";".join([surname_first, *(money(v) for v in values)])
    content = "\r\n".join([header, row]).encode("utf-8")
    differs = await client.post(
        f"{BASE}/lists/{payload['list']['id']}/compare-enova",
        files={"file": ("enova.csv", content, "text/csv")},
        headers=headers(w.payroll1),
    )
    person = next(p for p in differs.json()["people"] if p["person"] == w.salaried.name)
    diffs = {item["key"]: item["diff"] for item in person["fields"] if item["diff"]}
    assert person["equal"] is False and diffs == {"pit": -100, "net": 100}
    refused = await client.post(
        f"{BASE}/lists/{payload['list']['id']}/compare-enova",
        files={"file": ("enova.csv", content, "text/csv")},
        headers=headers(w.recruiter),
    )
    assert refused.status_code == 403


@pytest.mark.asyncio
async def test_manual_amount_over_salary_keeps_sick_days_for_the_limit(
    client, k7b
) -> None:
    w = k7b
    await _person(client, w)
    assert (await _salary(client, w, w.salaried)).status_code == 200
    manual = await client.put(
        f"{BASE}/months/{w.year}/10/inputs",
        json={
            "user_id": w.salaried.id,
            "kind": "uop",
            "gross": "9000",
            "note": "z Enovy",
        },
        headers=headers(w.payroll1),
    )
    assert manual.status_code == 200, manual.text
    payload = await _compute(client, w)
    line = _line(payload, user_id=w.salaried.id)
    assert line["source"] == "manual" and line["gross"] == "9000.00"
    k7b_data = line["basis"]["k7b"]
    assert k7b_data["replaced"] is True and k7b_data["sick"][0]["paid_days"] == 5
    assert "salary_replaced" in {p["code"] for p in line["problems"]}
