"""Płace K7a z bazą: bramki, dane osoby z PESEL-em, lista płac od przeliczenia
po zatwierdzenie drugą osobą, odmowy i anulowanie.

Ścieżki odmowy: moduł Płac Księgowości wyłączony (404 poza adminem), konto
bez Płac (403), osoba nie zmienia swoich danych (403), PESEL drugi raz (409),
lista z niezamkniętego miesiąca (409), liczący nie zatwierdza (403), problemy
blokujące (409), dane zmienione po przeliczeniu (409), otwarcie miesiąca
z zatwierdzoną listą (409), wersja parametrów użyta przez listę (409).
Osoby, kwoty i PESEL-e fikcyjne; rok losowy z odległej przyszłości, żeby nie
zderzyć się z innymi testami na wspólnej bazie.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.hr_ops import HrAuditEvent
from app.models.hr_payroll import PayrollLine, PayrollPeriod
from app.models.hr_payroll_lists import (
    PayrollGrossInput,
    PayrollList,
    PayrollListLine,
    PayrollParameterVersion,
    PayrollPersonData,
    PayrollYearOpening,
)
from app.services.hr import payroll_close
from app.services.hr.payroll_errors import PayrollConflict
from app.services.hr.payroll_lists import params
from app.services.ledger import settings as ledger_settings
from tests.hr_settlements_seed import add_line, headers, make_user

BASE = "/api/hr/payroll-lists"
WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


def _pesel(born: date, serial: int) -> str:
    month = born.month + (20 if born.year >= 2000 else 0)
    body = f"{born.year % 100:02d}{month:02d}{born.day:02d}{serial:04d}"
    total = sum(int(d) * w for d, w in zip(body, WEIGHTS))
    return body + str((10 - total % 10) % 10)


def _address() -> dict[str, str]:
    return {
        "voivodeship": "mazowieckie",
        "county": "Testowo",
        "commune": "Testowo",
        "city": "Testowo",
        "street": "Przykładowa",
        "house_number": "1",
        "postal_code": "00-001",
    }


def _full_data(born: date, serial: int, **extra) -> dict:
    return {
        "pesel": _pesel(born, serial),
        "first_name": "Osoba",
        "last_name": "Testowa",
        "address": _address(),
        "tax_office_code": "1471",
        "zus_title_code": "011000",
        **extra,
    }


async def _set_ledger(value) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, ledger_settings.SETTING_KEY)
        if value is None:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(AppSetting(key=ledger_settings.SETTING_KEY, value=value))
        else:
            row.value = value
        await db.commit()


async def _ledger_value():
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, ledger_settings.SETTING_KEY)
        return None if row is None else row.value


class World:
    pass


@pytest_asyncio.fixture
async def world():
    year = random.randint(2090, 2099)
    previous = await _ledger_value()
    await _set_ledger({"modules": {"payroll": True}})
    w = World()
    w.year = year
    w.admin = await make_user("admin", profile=False, name="Admin Testowy")
    w.payroll1 = await make_user("recruiter", grants=("payroll",), profile=False)
    w.payroll2 = await make_user("recruiter", grants=("payroll",), profile=False)
    w.hr = await make_user("recruiter", grants=("people_admin",), employment_type="uop")
    w.recruiter = await make_user("recruiter", profile=False)
    w.uop = await make_user("employee", employment_type="uop")
    w.mandate = await make_user("employee", employment_type="zlecenie")
    async with AsyncSessionLocal() as db:
        version = PayrollParameterVersion(
            effective_from=date(year, 1, 1),
            params=dict(params.SEED_2026),
            status="confirmed",
            source="manual",
            confirmed_at=datetime(year, 1, 1, tzinfo=timezone.utc),
        )
        client = Client(name=f"Klient płac {uuid.uuid4().hex[:8]}")
        candidate = Candidate(
            name="Zleceniobiorca", lastname=f"Testowy{uuid.uuid4().hex[:6]}"
        )
        db.add_all([version, client, candidate])
        await db.flush()
        contract = Contract(
            client_id=client.id,
            candidate_id=candidate.id,
            contract_type=ContractType.uzlecenie,
            status=ContractStatus.active,
            start_date=date(year, 1, 1),
            rate_candidate=Decimal("42"),
        )
        db.add(contract)
        period = PayrollPeriod(year=year, month=10, status="closed", close_count=1)
        db.add(period)
        await db.commit()
        w.version_id = version.id
        w.client_id = client.id
        w.candidate_id = candidate.id
        w.contract_id = contract.id
        w.period_id = period.id
    # 160 h × 48,75 zł = 7800 zł (UoP), 168 h × 42 zł = 7056 zł (zlecenie w zespole).
    await add_line(w.period_id, w.uop, employment_type="uop", hours="160", rate="48.75")
    await add_line(
        w.period_id, w.mandate, employment_type="zlecenie", hours="168", rate="42.00"
    )
    yield w
    async with AsyncSessionLocal() as db:
        list_ids = list(
            await db.scalars(select(PayrollList.id).where(PayrollList.year == year))
        )
        await db.execute(
            delete(PayrollListLine).where(PayrollListLine.list_id.in_(list_ids or [0]))
        )
        await db.execute(delete(PayrollList).where(PayrollList.id.in_(list_ids or [0])))
        await db.execute(
            delete(PayrollGrossInput).where(PayrollGrossInput.period_id == w.period_id)
        )
        await db.execute(
            delete(PayrollYearOpening).where(PayrollYearOpening.year == year)
        )
        await db.execute(
            delete(PayrollPersonData).where(
                PayrollPersonData.user_id.in_([w.uop.id, w.mandate.id, w.hr.id])
                | (PayrollPersonData.candidate_id == w.candidate_id)
            )
        )
        await db.execute(
            delete(PayrollLine).where(PayrollLine.period_id == w.period_id)
        )
        await db.execute(delete(PayrollPeriod).where(PayrollPeriod.year == year))
        await db.execute(
            delete(PayrollParameterVersion).where(
                PayrollParameterVersion.effective_from >= date(year, 1, 1),
                PayrollParameterVersion.effective_from <= date(year, 12, 1),
            )
        )
        await db.execute(delete(Contract).where(Contract.id == w.contract_id))
        await db.execute(delete(Candidate).where(Candidate.id == w.candidate_id))
        await db.execute(delete(Client).where(Client.id == w.client_id))
        await db.commit()
    await _set_ledger(previous)


async def _fill_people(client, w) -> None:
    for path, data in (
        (f"users/{w.uop.id}", _full_data(date(1990, 3, 3), 1240, pit2=12)),
        (f"users/{w.mandate.id}", _full_data(date(1988, 5, 6), 3451)),
        (
            f"candidates/{w.candidate_id}",
            _full_data(date(1985, 1, 9), 7771, bank_account=None),
        ),
    ):
        response = await client.put(
            f"{BASE}/people/{path}", json=data, headers=headers(w.hr)
        )
        assert response.status_code == 200, response.text


async def _compute(client, w, user=None) -> dict:
    response = await client.post(
        f"{BASE}/months/{w.year}/10/compute",
        json={"pay_date": f"{w.year}-11-10"},
        headers=headers(user or w.payroll1),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _zero_foreign_contracts(client, w, payload) -> dict:
    """Kontrakty zleceniowe innych testów na wspólnej bazie — poza tą listą."""

    foreign = {
        line["contract_id"]
        for line in payload["list"]["lines"]
        if line["contract_id"] and line["contract_id"] != w.contract_id
    }
    for contract_id in foreign:
        response = await client.put(
            f"{BASE}/months/{w.year}/10/inputs",
            json={
                "contract_id": contract_id,
                "kind": "zlecenie",
                "gross": "0",
                "note": "poza testem",
            },
            headers=headers(w.payroll1),
        )
        assert response.status_code == 200, response.text
    return await _compute(client, w) if foreign else payload


def _line(payload: dict, **match) -> dict:
    for line in payload["list"]["lines"]:
        if all(line.get(key) == value for key, value in match.items()):
            return line
    raise AssertionError(f"brak pozycji {match}")


# ── Bramki ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gates_module_switch_and_permission(client, world) -> None:
    w = world
    refused = await client.get(
        f"{BASE}/months/{w.year}/10", headers=headers(w.recruiter)
    )
    assert refused.status_code == 403
    hr_on_list = await client.get(f"{BASE}/months/{w.year}/10", headers=headers(w.hr))
    assert hr_on_list.status_code == 403
    hr_people = await client.get(f"{BASE}/people", headers=headers(w.hr))
    assert hr_people.status_code == 200
    await _set_ledger({"modules": {"payroll": False}})
    hidden = await client.get(f"{BASE}/months/{w.year}/10", headers=headers(w.payroll1))
    assert hidden.status_code == 404
    admin = await client.get(f"{BASE}/months/{w.year}/10", headers=headers(w.admin))
    assert admin.status_code == 200
    await _set_ledger({"modules": {"payroll": True}})


# ── Dane osoby ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pesel_is_encrypted_masked_and_unique(client, world) -> None:
    w = world
    number = _pesel(date(1990, 3, 3), 1240)
    saved = await client.put(
        f"{BASE}/people/users/{w.uop.id}",
        json={"pesel": number, "pit2": 12},
        headers=headers(w.hr),
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert number not in saved.text
    assert body["pesel_masked"].endswith(number[-4:])
    assert body["birth_date"] is None
    async with AsyncSessionLocal() as db:
        record = await db.scalar(
            select(PayrollPersonData).where(PayrollPersonData.user_id == w.uop.id)
        )
        assert record is not None and number not in record.data_encrypted
        events = list(
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.entity_type == "payroll_person_data",
                    HrAuditEvent.entity_id == str(record.id),
                )
            )
        )
    assert events and all(number not in repr(e.details) for e in events)
    assert events[-1].details["fields"] == ["pesel", "pit2"]
    duplicate = await client.put(
        f"{BASE}/people/users/{w.mandate.id}",
        json={"pesel": number},
        headers=headers(w.hr),
    )
    assert duplicate.status_code == 409
    assert number not in duplicate.text
    bad = await client.put(
        f"{BASE}/people/users/{w.mandate.id}",
        json={"pesel": number[:-1] + str((int(number[-1]) + 1) % 10)},
        headers=headers(w.hr),
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_own_data_refused_and_stale_version(client, world) -> None:
    w = world
    own = await client.put(
        f"{BASE}/people/users/{w.hr.id}", json={"pit2": 12}, headers=headers(w.hr)
    )
    assert own.status_code == 403
    first = await client.put(
        f"{BASE}/people/users/{w.uop.id}",
        json={"pit2": 12, "expected_version": 0},
        headers=headers(w.hr),
    )
    assert first.status_code == 200
    stale = await client.put(
        f"{BASE}/people/users/{w.uop.id}",
        json={"pit2": 24, "expected_version": 0},
        headers=headers(w.payroll1),
    )
    assert stale.status_code == 409


# ── Lista płac ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_month_is_refused(client, world) -> None:
    w = world
    async with AsyncSessionLocal() as db:
        period = await db.get(PayrollPeriod, w.period_id)
        period.status = "open"
        await db.commit()
    response = await client.post(
        f"{BASE}/months/{w.year}/10/compute", json={}, headers=headers(w.payroll1)
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "period_open"


@pytest.mark.asyncio
async def test_list_from_compute_to_second_person_approval(client, world) -> None:
    w = world
    payload = await _zero_foreign_contracts(client, w, await _compute(client, w))
    lst = payload["list"]
    assert lst["status"] == "draft" and lst["number"] == f"LP/{w.year}/10"
    contractor = _line(payload, contract_id=w.contract_id)
    assert contractor["gross"] is None
    assert {p["code"] for p in contractor["problems"]} >= {
        "gross_missing",
        "person_data_missing",
    }
    blocked = await client.post(
        f"{BASE}/lists/{lst['id']}/approve", headers=headers(w.payroll2)
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "list_blocked"

    await _fill_people(client, w)
    set_input = await client.put(
        f"{BASE}/months/{w.year}/10/inputs",
        json={
            "contract_id": w.contract_id,
            "kind": "zlecenie",
            "gross": "7056.00",
            "note": "Rachunek zleceniobiorcy",
        },
        headers=headers(w.payroll1),
    )
    assert set_input.status_code == 200, set_input.text
    payload = await _compute(client, w)
    lst = payload["list"]
    uop = _line(payload, user_id=w.uop.id)
    assert uop["gross"] == "7800.00" and uop["net"] == "5646.86"
    assert uop["pit"] == "478.00"
    contractor = _line(payload, contract_id=w.contract_id)
    assert contractor["source"] == "manual" and contractor["net"] == "5096.96"
    assert not [p for p in lst["problems"] if p["blocking"]]
    assert lst["totals"]["deadlines"]["declaration_month"] == f"{w.year}-11"

    self_approve = await client.post(
        f"{BASE}/lists/{lst['id']}/approve", headers=headers(w.payroll1)
    )
    assert self_approve.status_code == 403
    approved = await client.post(
        f"{BASE}/lists/{lst['id']}/approve", headers=headers(w.payroll2)
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["list"]["status"] == "approved"

    again = await client.post(
        f"{BASE}/months/{w.year}/10/compute", json={}, headers=headers(w.payroll1)
    )
    assert again.status_code == 409
    changed = await client.put(
        f"{BASE}/months/{w.year}/10/inputs",
        json={
            "contract_id": w.contract_id,
            "kind": "zlecenie",
            "gross": "1",
            "note": "zmiana",
        },
        headers=headers(w.payroll1),
    )
    assert changed.status_code == 409
    in_use = await client.post(
        f"{BASE}/parameters",
        json={"effective_from": f"{w.year}-01-01", "params": params.SEED_2026},
        headers=headers(w.payroll1),
    )
    assert in_use.status_code == 409

    async with AsyncSessionLocal() as db:
        with pytest.raises(PayrollConflict) as exc:
            await payroll_close.reopen_month(
                db, year=w.year, month=10, actor_id=w.admin.id, reason="test otwarcia"
            )
        assert exc.value.code == "payroll_list_approved"
        await db.rollback()

    no_reason = await client.post(
        f"{BASE}/lists/{lst['id']}/cancel",
        json={"reason": ""},
        headers=headers(w.payroll2),
    )
    assert no_reason.status_code == 422
    cancelled = await client.post(
        f"{BASE}/lists/{lst['id']}/cancel",
        json={"reason": "korekta kwoty"},
        headers=headers(w.payroll2),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["list"] is None
    assert cancelled.json()["cancelled"][0]["number"] == f"LP/{w.year}/10"
    recomputed = await _compute(client, w)
    assert recomputed["list"]["number"] == f"LP/{w.year}/10/2"


@pytest.mark.asyncio
async def test_change_after_compute_needs_recompute(client, world) -> None:
    w = world
    await _fill_people(client, w)
    await client.put(
        f"{BASE}/months/{w.year}/10/inputs",
        json={
            "contract_id": w.contract_id,
            "kind": "zlecenie",
            "gross": "7056",
            "note": "rachunek",
        },
        headers=headers(w.payroll1),
    )
    payload = await _zero_foreign_contracts(client, w, await _compute(client, w))
    change = await client.put(
        f"{BASE}/people/users/{w.uop.id}",
        json={"kup": "increased"},
        headers=headers(w.hr),
    )
    assert change.status_code == 200
    stale = await client.post(
        f"{BASE}/lists/{payload['list']['id']}/approve", headers=headers(w.payroll2)
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_list"


@pytest.mark.asyncio
async def test_payslips_pdf_for_draft(client, world) -> None:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        pytest.skip("WeasyPrint bez bibliotek systemowych (pango)")
    w = world
    payload = await _compute(client, w)
    response = await client.get(
        f"{BASE}/lists/{payload['list']['id']}/payslips.pdf",
        headers=headers(w.payroll1),
    )
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_parameters_history_and_confirmation(client, world) -> None:
    w = world
    saved = await client.post(
        f"{BASE}/parameters",
        json={
            "effective_from": f"{w.year}-04-01",
            "params": {**params.SEED_2026, "accident_employer_rate": "1.93"},
            "note": "zawiadomienie ZUS",
        },
        headers=headers(w.payroll1),
    )
    assert saved.status_code == 201, saved.text
    version = next(
        v for v in saved.json()["versions"] if v["effective_from"] == f"{w.year}-04-01"
    )
    assert version["status"] == "to_confirm"
    assert [c["key"] for c in version["changes"]] == ["accident_employer_rate"]
    bad_day = await client.post(
        f"{BASE}/parameters",
        json={"effective_from": f"{w.year}-04-02", "params": params.SEED_2026},
        headers=headers(w.payroll1),
    )
    assert bad_day.status_code == 422
    confirmed = await client.post(
        f"{BASE}/parameters/{version['id']}/confirm", headers=headers(w.payroll2)
    )
    assert confirmed.status_code == 200
    refused = await client.post(
        f"{BASE}/parameters/{version['id']}/confirm", headers=headers(w.hr)
    )
    assert refused.status_code == 403


@pytest.mark.asyncio
async def test_input_for_contract_outside_month_becomes_a_line(client, world) -> None:
    w = world
    async with AsyncSessionLocal() as db:
        ended = Contract(
            client_id=w.client_id,
            candidate_id=w.candidate_id,
            contract_type=ContractType.uzlecenie,
            status=ContractStatus.ended,
            start_date=date(w.year, 1, 1),
            end_date=date(w.year, 9, 30),
            rate_candidate=Decimal("40"),
        )
        db.add(ended)
        await db.commit()
        ended_id = ended.id
    try:
        saved = await client.put(
            f"{BASE}/months/{w.year}/10/inputs",
            json={
                "contract_id": ended_id,
                "kind": "zlecenie",
                "gross": "1200.00",
                "note": "rozliczenie po końcu umowy",
            },
            headers=headers(w.payroll1),
        )
        assert saved.status_code == 200, saved.text
        payload = await _compute(client, w)
        line = _line(payload, contract_id=ended_id)
        assert line["source"] == "manual" and line["gross"] == "1200.00"
        assert line["basis"]["outside_month"] is True
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(PayrollGrossInput).where(
                    PayrollGrossInput.contract_id == ended_id
                )
            )
            list_ids = list(
                await db.scalars(
                    select(PayrollList.id).where(PayrollList.year == w.year)
                )
            )
            await db.execute(
                delete(PayrollListLine).where(
                    PayrollListLine.list_id.in_(list_ids or [0])
                )
            )
            await db.execute(delete(Contract).where(Contract.id == ended_id))
            await db.commit()


@pytest.mark.asyncio
async def test_deleted_candidate_keeps_pseudonymised_payroll_data(
    client, world
) -> None:
    w = world
    saved = await client.put(
        f"{BASE}/people/candidates/{w.candidate_id}",
        json=_full_data(date(1985, 1, 9), 7771),
        headers=headers(w.hr),
    )
    assert saved.status_code == 200, saved.text
    async with AsyncSessionLocal() as db:
        record = await db.scalar(
            select(PayrollPersonData).where(
                PayrollPersonData.candidate_id == w.candidate_id
            )
        )
        assert record is not None and record.candidate_ref
        ref = record.candidate_ref
        await db.execute(
            delete(Contract).where(Contract.candidate_id == w.candidate_id)
        )
        await db.execute(delete(Candidate).where(Candidate.id == w.candidate_id))
        await db.commit()
    async with AsyncSessionLocal() as db:
        kept = await db.scalar(
            select(PayrollPersonData).where(PayrollPersonData.candidate_ref == ref)
        )
        assert kept is not None and kept.candidate_id is None
        await db.delete(kept)
        await db.commit()
