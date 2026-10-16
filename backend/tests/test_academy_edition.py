"""Edycja Akademii od strony recepcji (etap 5, makieta „I”).

Edycja = program i miesiąc startu (``cohort_month``). Check lista z wzoru
recepcji (9 sekcji) zakładana raz na edycję, hotel i bilet uczestnika, hurtowe
wydanie zestawów (osobny protokół na osobę, odmowa jednej nie cofa reszty) oraz
haki statusu zgłoszenia: podpis → zadanie zestawu, odejście → anulowanie hotelu
i biletu, zadanie zwrotu. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date

import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.academy import AcademyApplication
from app.models.academy_logistics import (
    AcademyEditionChecklistItem,
    AcademyParticipantLogistics,
)
from app.models.equipment import EquipmentItem, EquipmentTask
from app.services import academy_edition
from app.services.academy_documents import program_dates
from app.services.equipment import tasks as equipment_tasks
from tests.test_equipment_api import (
    _headers,
    _item,
    _model,
    _tag,
    _user,
    make_academy_participant,
    make_people,
    modules_state,
)

ACADEMY = "/api/academy"
ACTIONS = "/api/academy/applications"


@pytest_asyncio.fixture
async def modules_on():
    async with modules_state(True):
        yield


@pytest_asyncio.fixture
async def modules_off():
    async with modules_state(False):
        yield


@pytest_asyncio.fixture
async def people():
    return await make_people()


def _pesel_like() -> str:
    digits = "9001010000"
    weights = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    total = sum(int(d) * w for d, w in zip(digits, weights))
    return digits + str((10 - total % 10) % 10)


def _cohort_ahead(months: int = 3) -> date:
    today = business_today()
    month = today.month - 1 + months
    return date(today.year + month // 12, month % 12 + 1, 1)


# Edycja testów = ``_cohort_ahead()`` liczone przy wywołaniu, nie stała modułu:
# data z importu po północy w trakcie biegu CI wskazywałaby wczoraj
# (``test_no_import_time_dates.py``).


async def _signed(**kwargs) -> dict:
    """Uczestnik edycji za trzy miesiące (podpisana umowa), chyba że podano inaczej."""
    kwargs.setdefault("status", "signed")
    kwargs.setdefault("cohort_month", _cohort_ahead())
    return await make_academy_participant(**kwargs)


def _url(person: dict, cohort: date | None = None) -> str:
    cohort = cohort or _cohort_ahead()
    return f"{ACADEMY}/programs/{person['program_id']}/editions/{cohort:%Y-%m}"


async def _edition(app_client, people, url: str, who: str = "reception"):
    response = await app_client.get(url, headers=_headers(people[who]))
    assert response.status_code == 200, response.text
    return response.json()


def _row(body: dict, application_id: int) -> dict:
    return next(
        p for p in body["participants"] if p["application_id"] == application_id
    )


async def _task(source_key: str) -> EquipmentTask | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(EquipmentTask).where(EquipmentTask.source_key == source_key)
        )


async def _act(app_client, people, application_id: int, body: dict):
    response = await app_client.post(
        f"{ACTIONS}/{application_id}/actions",
        json=body,
        headers=_headers(people["recruiter"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


# ── Bramki i adresy ───────────────────────────────────────────────────────────


async def test_module_off_answers_404_except_admin(
    app_client, modules_off, people
) -> None:
    person = await _signed()
    for who in ("reception", "recruiter"):
        response = await app_client.get(_url(person), headers=_headers(people[who]))
        assert response.status_code == 404, who
        assert response.json()["detail"] == "Ten moduł nie jest jeszcze włączony."
    admin = await app_client.get(_url(person), headers=_headers(people["admin"]))
    assert admin.status_code == 200


async def test_reception_or_academy_access_reads_only_reception_issues(
    app_client, modules_on, people
) -> None:
    person = await _signed()
    reception = await _edition(app_client, people, _url(person))
    assert reception["can_issue"] is True
    assert reception["edition"]["key"] == f"{_cohort_ahead():%Y-%m}"
    assert (
        reception["edition"]["starts_on"]
        == program_dates(_cohort_ahead())[0].isoformat()
    )
    recruiter = await _edition(app_client, people, _url(person), "recruiter")
    assert recruiter["can_issue"] is False
    async with AsyncSessionLocal() as db:
        # Kadry bez roli rekrutera: ani „Sprzęt”, ani Akademia.
        hr_only = await _user(db, "employee", grants=("people_admin",))
        await db.commit()
    for who, user in (("worker", people["worker"]), ("hr_only", hr_only)):
        refused = await app_client.get(_url(person), headers=_headers(user))
        assert refused.status_code == 403, who
    logistics = await app_client.patch(
        f"{_url(person)}/participants/{person['application_id']}",
        json={"hotel": "zrobione"},
        headers=_headers(people["recruiter"]),
    )
    assert logistics.status_code == 200, logistics.text
    issue = await app_client.post(
        f"{_url(person)}/issue",
        json={
            "participants": [
                {"application_id": person["application_id"], "lines": [{"item_id": 1}]}
            ]
        },
        headers=_headers(people["recruiter"]),
    )
    assert issue.status_code == 403
    listing = await app_client.get(
        f"{ACADEMY}/editions",
        params={"program_id": person["program_id"]},
        headers=_headers(people["reception"]),
    )
    assert listing.status_code == 200
    assert [e["key"] for e in listing.json()["items"]] == [f"{_cohort_ahead():%Y-%m}"]
    assert listing.json()["items"][0]["participants"] == 1
    missing = await app_client.get(
        f"{ACADEMY}/programs/987654321/editions/{_cohort_ahead():%Y-%m}",
        headers=_headers(people["reception"]),
    )
    assert missing.status_code == 404
    bad_month = await app_client.get(
        f"{ACADEMY}/programs/{person['program_id']}/editions/2026-13",
        headers=_headers(people["reception"]),
    )
    assert bad_month.status_code == 422


async def test_people_before_signing_belong_to_the_next_edition(
    app_client, modules_on, people
) -> None:
    sent = await make_academy_participant(status="contract_sent")
    early = await make_academy_participant(
        status="scheduled", program_id=sent["program_id"]
    )
    upcoming = academy_edition.pending_cohort()
    listing = await app_client.get(
        f"{ACADEMY}/editions",
        params={"program_id": sent["program_id"]},
        headers=_headers(people["reception"]),
    )
    assert [e["key"] for e in listing.json()["items"]] == [f"{upcoming:%Y-%m}"]
    body = await _edition(app_client, people, _url(sent, upcoming))
    assert [p["application_id"] for p in body["participants"]] == [
        sent["application_id"]
    ]
    assert _row(body, sent["application_id"])["contract"]["state"] == "wyslana"
    assert early["application_id"] not in {
        p["application_id"] for p in body["participants"]
    }
    other_month = await _edition(app_client, people, _url(sent))
    assert other_month["participants"] == []


# ── Check lista ───────────────────────────────────────────────────────────────


async def test_checklist_is_created_once_and_keeps_ticks(
    app_client, modules_on, people
) -> None:
    person = await _signed()
    url = _url(person)
    body = await _edition(app_client, people, url)
    assert [s["label"] for s in body["checklist"]][0] == "Informacje od prowadzącej"
    assert len(body["checklist"]) == 9
    assert body["checklist_total"] == 70 == len(academy_edition.template_rows())
    item = body["checklist"][1]["items"][0]
    ticked = await app_client.patch(
        f"{url}/checklist/{item['id']}",
        json={"done": True, "note": "Rezerwacja w folderze edycji"},
        headers=_headers(people["reception"]),
    )
    assert ticked.status_code == 200, ticked.text
    assert ticked.json()["done"] is True
    assert ticked.json()["done_by"] == people["reception"].name

    # Nowy punkt wzoru (tu: brakujący wiersz) dopisuje się, odhaczenia zostają.
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AcademyEditionChecklistItem).where(
                AcademyEditionChecklistItem.program_id == person["program_id"],
                AcademyEditionChecklistItem.cohort_month == _cohort_ahead(),
                AcademyEditionChecklistItem.item_key == "after_close",
            )
        )
        await db.commit()
        program_id = person["program_id"]
        assert (
            await academy_edition.ensure_checklist(db, program_id, _cohort_ahead()) == 1
        )
        assert (
            await academy_edition.ensure_checklist(db, program_id, _cohort_ahead()) == 0
        )
        await db.commit()
    again = await _edition(app_client, people, url)
    assert again["checklist_total"] == 70
    kept = next(i for i in again["checklist"][1]["items"] if i["id"] == item["id"])
    assert kept["done"] is True and kept["note"] == "Rezerwacja w folderze edycji"
    assert again["checklist"][1]["done"] == 1

    unticked = await app_client.patch(
        f"{url}/checklist/{item['id']}",
        json={"done": False},
        headers=_headers(people["recruiter"]),
    )
    assert unticked.json()["done"] is False
    assert unticked.json()["note"] == "Rezerwacja w folderze edycji"

    secret = await app_client.patch(
        f"{url}/checklist/{item['id']}",
        json={"note": f"PESEL {_pesel_like()}"},
        headers=_headers(people["reception"]),
    )
    assert secret.status_code == 422
    other_month = await app_client.patch(
        f"{_url(person, _cohort_ahead(4))}/checklist/{item['id']}",
        json={"done": True},
        headers=_headers(people["reception"]),
    )
    assert other_month.status_code == 404


# ── Logistyka ─────────────────────────────────────────────────────────────────


async def test_logistics_validation_and_participant_scope(
    app_client, modules_on, people
) -> None:
    person = await _signed()
    url = f"{_url(person)}/participants"
    headers = _headers(people["reception"])
    saved = await app_client.patch(
        f"{url}/{person['application_id']}",
        json={"hotel": "zrobione", "ticket": "nie_dotyczy", "note": "Pokój dwuosobowy"},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "application_id": person["application_id"],
        "hotel": "zrobione",
        "ticket": "nie_dotyczy",
        "logistics_note": "Pokój dwuosobowy",
    }
    bad = await app_client.patch(
        f"{url}/{person['application_id']}", json={"hotel": "jutro"}, headers=headers
    )
    assert bad.status_code == 422
    secret = await app_client.patch(
        f"{url}/{person['application_id']}",
        json={"note": f"kontakt {_pesel_like()}"},
        headers=headers,
    )
    assert secret.status_code == 422
    other = await _signed()
    foreign = await app_client.patch(
        f"{url}/{other['application_id']}", json={"hotel": "zrobione"}, headers=headers
    )
    assert foreign.status_code == 404
    row = _row(
        await _edition(app_client, people, _url(person)), person["application_id"]
    )
    assert (row["hotel"], row["ticket"]) == ("zrobione", "nie_dotyczy")
    assert row["contract"]["state"] == "podpisana"


# ── Haki statusu zgłoszenia ───────────────────────────────────────────────────


async def test_signed_creates_kit_task_before_program_start(
    app_client, modules_on, people
) -> None:
    person = await make_academy_participant(status="contract_sent")
    await _act(
        app_client,
        people,
        person["application_id"],
        {"action": "signed", "cohort_month": _cohort_ahead().isoformat()},
    )
    task = await _task(f"academy:{person['application_id']}:kit")
    assert task is not None
    assert task.kind == "wydanie" and task.status == "otwarte"
    assert task.academy_application_id == person["application_id"]
    assert task.title == f"Przygotuj zestaw Akademii: {person['name']}"
    async with AsyncSessionLocal() as db:
        expected = max(
            await equipment_tasks.workdays_before(
                db, program_dates(_cohort_ahead())[0], academy_edition.KIT_LEAD_WORKDAYS
            ),
            business_today(),
        )
        application = await db.get(AcademyApplication, person["application_id"])
        # Drugi przebieg niczego nie dubluje.
        again = await academy_edition.kit_task(db, application)
        await db.commit()
    assert task.due_on == expected
    assert again is not None and again.id == task.id
    listed = await app_client.get(
        "/api/equipment/tasks", headers=_headers(people["reception"])
    )
    mine = next(t for t in listed.json()["items"] if t["id"] == task.id)
    assert mine["holder"] == {
        "kind": "academy",
        "id": person["application_id"],
        "name": person["name"],
    }
    body = await _edition(app_client, people, _url(person))
    assert _row(body, person["application_id"])["contract"]["state"] == "podpisana"


async def test_hooks_do_nothing_when_module_is_off(
    app_client, modules_off, people
) -> None:
    person = await make_academy_participant(status="task_passed")
    await _act(app_client, people, person["application_id"], {"action": "signed"})
    assert await _task(f"academy:{person['application_id']}:kit") is None
    async with AsyncSessionLocal() as db:
        db.add(
            AcademyParticipantLogistics(
                application_id=person["application_id"], hotel="zrobione"
            )
        )
        await db.commit()
    await _act(app_client, people, person["application_id"], {"action": "withdraw"})
    async with AsyncSessionLocal() as db:
        row = await db.get(AcademyParticipantLogistics, person["application_id"])
    assert row is not None and row.hotel == "zrobione"


async def test_equipment_failure_does_not_block_status_change(
    app_client, modules_on, people, monkeypatch
) -> None:
    async def boom(*_args, **_kwargs):
        raise RuntimeError("awaria modułu sprzętu (test)")

    monkeypatch.setattr(academy_edition, "kit_task", boom)
    person = await make_academy_participant(status="task_passed")
    body = await _act(
        app_client, people, person["application_id"], {"action": "signed"}
    )
    assert body["status"] == "signed"
    async with AsyncSessionLocal() as db:
        application = await db.get(AcademyApplication, person["application_id"])
    assert application.status == "signed" and application.signed_at is not None
    assert await _task(f"academy:{person['application_id']}:kit") is None


async def test_leaving_cancels_travel_and_kit_task_and_asks_for_return(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    first = await make_academy_participant(status="contract_sent")
    second = await _signed(program_id=first["program_id"])
    await _act(
        app_client,
        people,
        first["application_id"],
        {"action": "signed", "cohort_month": _cohort_ahead().isoformat()},
    )
    assert (await _task(f"academy:{first['application_id']}:kit")).status == "otwarte"
    await app_client.patch(
        f"{_url(first)}/participants/{first['application_id']}",
        json={"hotel": "zrobione", "ticket": "do_zrobienia"},
        headers=headers,
    )
    model = await _model(app_client, headers, "laptop", "2100.00")
    item = await _item(app_client, headers, model["id"])
    issued = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "academy",
            "holder_id": second["application_id"],
            "lines": [{"item_id": item["id"]}],
        },
        headers=headers,
    )
    assert issued.status_code == 201, issued.text

    await _act(
        app_client,
        people,
        first["application_id"],
        {"action": "withdraw", "reason": "Rezygnacja przed startem"},
    )
    await _act(app_client, people, second["application_id"], {"action": "withdraw"})

    kit = await _task(f"academy:{first['application_id']}:kit")
    assert kit.status == "anulowane"
    assert await _task(f"academy:{first['application_id']}:return") is None
    give_back = await _task(f"academy:{second['application_id']}:return")
    assert give_back is not None and give_back.status == "otwarte"
    assert give_back.kind == "zwrot" and give_back.due_on == business_today()

    body = await _edition(app_client, people, _url(first))
    gone = _row(body, first["application_id"])
    assert gone["left"] is True and gone["contract"]["state"] == "rezygnacja"
    assert (gone["hotel"], gone["ticket"]) == ("do_anulowania", "nie_dotyczy")
    holding = _row(body, second["application_id"])
    assert holding["kit"]["state"] == "do_zwrotu"
    assert holding["hotel"] == "nie_dotyczy"
    assert body["summary"]["kits_to_return"] == 1
    assert body["summary"]["participants"] == 0 and body["summary"]["left"] == 2


# ── Hurtowe wydanie ───────────────────────────────────────────────────────────


async def test_bulk_issue_reports_per_participant(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    a = await _signed()
    b = await _signed(program_id=a["program_id"])
    c = await _signed(
        status="withdrew", closed_stage="signed", program_id=a["program_id"]
    )
    outsider = await _signed()
    laptops = await _model(app_client, headers, "laptop", "2500.00")
    phones = await _model(app_client, headers, "telefon", "800.00")
    a_laptop = await _item(
        app_client, headers, laptops["id"], inventory_number=f"K-{_tag()}"
    )
    a_phone = await _item(app_client, headers, phones["id"])
    b_laptop = await _item(app_client, headers, laptops["id"])
    b_phone = await _item(app_client, headers, phones["id"])
    c_laptop = await _item(app_client, headers, laptops["id"])
    x_laptop = await _item(app_client, headers, laptops["id"])
    busy = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "user",
            "holder_id": people["worker"].id,
            "lines": [{"item_id": b_laptop["id"]}],
        },
        headers=headers,
    )
    assert busy.status_code == 201
    url = f"{_url(a)}/issue"

    duplicate = await app_client.post(
        url,
        json={
            "participants": [
                {
                    "application_id": a["application_id"],
                    "lines": [{"item_id": a_laptop["id"]}],
                },
                {
                    "application_id": b["application_id"],
                    "lines": [{"item_id": a_laptop["id"]}],
                },
            ]
        },
        headers=headers,
    )
    assert duplicate.status_code == 422

    response = await app_client.post(
        url,
        json={
            "send_link": True,
            "participants": [
                {
                    "application_id": a["application_id"],
                    "lines": [
                        {"item_id": a_laptop["id"], "accessories": "zasilacz, mysz"},
                        {"item_id": a_phone["id"]},
                    ],
                },
                {
                    "application_id": b["application_id"],
                    "lines": [{"item_id": b_phone["id"]}, {"item_id": b_laptop["id"]}],
                },
                {
                    "application_id": c["application_id"],
                    "lines": [{"item_id": c_laptop["id"]}],
                },
                {
                    "application_id": outsider["application_id"],
                    "lines": [{"item_id": x_laptop["id"]}],
                },
            ],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert (report["issued"], report["failed"]) == (1, 3)
    by_person = {r["application_id"]: r for r in report["results"]}
    ok = by_person[a["application_id"]]
    assert ok["ok"] is True and ok["link_url"]
    assert ok["protocol"]["holder"]["name"] == a["name"]
    assert ok["protocol"]["holder"]["kind"] == "academy"
    assert len(ok["protocol"]["lines"]) == 2
    assert by_person[b["application_id"]]["status"] == 409
    assert by_person[c["application_id"]]["status"] == 409
    assert by_person[outsider["application_id"]]["status"] == 404
    async with AsyncSessionLocal() as db:
        # Wszystko albo nic dla osoby: telefon B nie został wydany.
        assert (await db.get(EquipmentItem, b_phone["id"])).status == "na_stanie"
        assert (await db.get(EquipmentItem, c_laptop["id"])).status == "na_stanie"
        assert (await db.get(EquipmentItem, a_phone["id"])).status == "wydany"

    body = await _edition(app_client, people, _url(a))
    row_a = _row(body, a["application_id"])
    assert row_a["kit"]["state"] == "wydany" and len(row_a["kit"]["items"]) == 2
    assert row_a["protocol"]["number"] == ok["protocol"]["number"]
    assert row_a["protocol"]["status"] == "oczekuje"
    assert _row(body, b["application_id"])["kit"]["state"] == "brak"
    assert body["summary"]["kits_issued"] == 1
