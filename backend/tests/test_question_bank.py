"""Rekrutacje → „Pytania z rozmów” (prośba Delivery Leadki z 24.11.2026).

Dawny Excel z pytaniami, tylko że dopisuje się sam: pytanie, stanowisko, klient
i manager, bez duplikatów. Te testy pilnują, że:

* to samo pytanie z dwóch debriefów jest jednym wierszem z oboma stanowiskami
  i licznikiem 2, a manager przychodzi z rekrutacji (hiring manager);
* archiwum Excela jest w tej samej liście ze źródłem ``archive``, stanowisko
  dostaje tylko przez przypięcie importu, nie przez pin człowieka.
"""

from __future__ import annotations

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.contact import Contact
from app.models.interview_question import InterviewQuestionSource
from app.models.job import Job
from tests.test_client_questions_asked import (
    _admin,
    _bank_question,
    _debrief,
    _pin,
    _world,
)

URL = "/api/interview-cycle/question-bank"


async def _items_for(
    api: AsyncClient, headers: dict[str, str], client_id: int
) -> list[dict]:
    resp = await api.get(URL, headers=headers)
    assert resp.status_code == 200, resp.text
    return [i for i in resp.json()["items"] if i["client_id"] == client_id]


async def _set_manager(job_id: int, client_id: int, name: str) -> None:
    async with AsyncSessionLocal() as db:
        contact = Contact(client_id=client_id, name=name)
        db.add(contact)
        await db.flush()
        job = await db.get(Job, job_id)
        job.hiring_manager_contact_id = contact.id
        await db.commit()


async def test_same_question_from_two_debriefs_is_one_row_with_roles_and_manager(
    app_client: AsyncClient,
):
    _, headers = await _admin()
    w = await _world()
    await _set_manager(w["java"], w["client"], "Manager Javy")
    await _debrief(
        app_client, headers, w, w["java"], ["Transakcje w Spring", "Jak testujesz?"]
    )
    await _debrief(app_client, headers, w, w["pm"], ["jak  TESTUJESZ?"])

    items = await _items_for(app_client, headers, w["client"])
    by_text = {i["text"].lower(): i for i in items}
    assert set(by_text) == {"transakcje w spring", "jak testujesz?"}

    shared = by_text["jak testujesz?"]
    assert shared["source"] == "debrief"
    assert shared["asked_count"] == 2
    assert {r["job_id"] for r in shared["roles"]} == {w["java"], w["pm"]}
    assert shared["managers"] == ["Manager Javy"]

    spring = by_text["transakcje w spring"]
    assert spring["asked_count"] == 1
    assert [r["manager"] for r in spring["roles"]] == ["Manager Javy"]


async def test_excel_archive_is_listed_and_only_import_pin_gives_a_role(
    app_client: AsyncClient,
):
    user_id, headers = await _admin()
    w = await _world()
    pinned = await _bank_question(w["client"], "Pytanie z Excela o tę rolę")
    by_hand = await _bank_question(w["client"], "Pytanie przypięte ręcznie")
    loose = await _bank_question(w["client"], "Pytanie z arkusza bez rekrutacji")
    await _pin(w["java"], pinned, user_id=None)
    await _pin(w["pm"], by_hand, user_id=user_id)

    items = {i["id"]: i for i in await _items_for(app_client, headers, w["client"])}
    assert {items[q]["source"] for q in (pinned, by_hand, loose)} == {"archive"}
    assert [r["job_id"] for r in items[pinned]["roles"]] == [w["java"]]
    assert items[by_hand]["roles"] == []
    assert items[loose]["roles"] == []
    assert items[loose]["asked_count"] == 0


async def test_manual_bank_question_is_not_listed(app_client: AsyncClient):
    """Bank ma też pytania dodane ręcznie (`manual`) — to nie są pytania z rozmów."""
    _, headers = await _admin()
    w = await _world()
    manual = await _bank_question(
        w["client"],
        "Pytanie dopisane w Bazie pytań",
        source=InterviewQuestionSource.manual,
    )

    ids = {i["id"] for i in await _items_for(app_client, headers, w["client"])}
    assert manual not in ids
