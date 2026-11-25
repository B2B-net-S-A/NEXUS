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
from app.models.interview_question import InterviewQuestion, InterviewQuestionSource
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


# ── Odpowiedź pod pytaniem (0777, F55, decyzja Artura 25.11.2026) ───────────


async def _set_answer(question_id: int, answer: str | None, source: str | None) -> None:
    async with AsyncSessionLocal() as db:
        question = await db.get(InterviewQuestion, question_id)
        question.ideal_answer = answer
        question.ideal_answer_source = source
        await db.commit()


async def test_answer_and_its_source_are_in_the_bank(app_client: AsyncClient):
    _, headers = await _admin()
    w = await _world()
    excel = await _bank_question(w["client"], "Czym jest MQ?")
    legacy = await _bank_question(w["client"], "Odpowiedź sprzed 0777")
    ai = await _bank_question(w["client"], "Playwright")
    heading = await _bank_question(w["client"], "Bazy danych i optymalizacja")
    pending = await _bank_question(w["client"], "Czy zna RLS")
    await _set_answer(excel, "Broker kolejek IBM.", "excel")
    await _set_answer(legacy, "Bez źródła w bazie.", None)
    await _set_answer(ai, "Narzędzie do testów E2E.", "ai")
    await _set_answer(heading, None, "none")

    items = {i["id"]: i for i in await _items_for(app_client, headers, w["client"])}
    got = {q: (items[q]["answer"], items[q]["answer_source"]) for q in items}
    assert got[excel] == ("Broker kolejek IBM.", "excel")
    assert got[legacy] == ("Bez źródła w bazie.", "excel")
    assert got[ai] == ("Narzędzie do testów E2E.", "ai")
    assert got[heading] == (None, "none")
    assert got[pending] == (None, None)


async def test_nightly_run_fills_unanswered_marks_headings_and_never_overwrites(
    app_client: AsyncClient, monkeypatch
):
    import json
    import re

    from app.services import interview_answer_proposals as iap

    w = await _world()
    answered = await _bank_question(w["client"], "Pytanie z odpowiedzią z Excela")
    question = await _bank_question(w["client"], "Klasa abstrakcyjna")
    heading = await _bank_question(w["client"], "Kolejki i komunikacja asynchroniczna")
    await _set_answer(answered, "Odpowiedź z arkusza.", "excel")
    await _pin(w["java"], question, user_id=None)
    mine = {question, heading}
    prompts: list[str] = []
    sent_ids: set[int] = set()

    def fake_model(prompt: str) -> str:
        prompts.append(prompt)
        payload = re.search(r"<pytania>\n(.*)\n</pytania>", prompt, re.S)
        items = json.loads(payload.group(1))
        sent_ids.update(i["id"] for i in items)
        # Tylko własne wiersze: wspólna baza testów ma pytania innych testów.
        return json.dumps(
            [
                {"id": i["id"], "answer": None if i["id"] == heading else "Propozycja."}
                for i in items
                if i["id"] in mine
            ]
        )

    monkeypatch.setattr(iap, "_call_model", fake_model)
    monkeypatch.setattr(iap, "api_key_configured", lambda _m: True)

    async with AsyncSessionLocal() as db:
        summary = await iap.run(db, limit=1_000_000)
    assert summary["status"] == "ok"
    sent = " ".join(prompts)
    assert mine <= sent_ids and answered not in sent_ids
    assert "Java Developer" in sent  # stanowisko z przypięcia importu
    assert "Asked-" not in sent  # bez nazwy klienta

    async with AsyncSessionLocal() as db:
        rows = {
            q.id: (q.ideal_answer, q.ideal_answer_source)
            for q in [
                await db.get(InterviewQuestion, i)
                for i in (answered, question, heading)
            ]
        }
        assert rows == {
            answered: ("Odpowiedź z arkusza.", "excel"),
            question: ("Propozycja.", "ai"),
            heading: (None, "none"),
        }
        # Zapis warunkowy: odpowiedź, która już stoi, zostaje.
        assert await iap.store(db, {answered: "Nadpisanie.", question: None}) == (0, 0)
    async with AsyncSessionLocal() as db:
        assert (
            await db.get(InterviewQuestion, answered)
        ).ideal_answer == "Odpowiedź z arkusza."
        assert (await db.get(InterviewQuestion, question)).ideal_answer == "Propozycja."

    # Druga noc nie wysyła ponownie ani odpowiedzi, ani nagłówka.
    sent_ids.clear()
    async with AsyncSessionLocal() as db:
        await iap.run(db, limit=1_000_000)
    assert not mine & sent_ids
