"""Jarvis — pętla agenta przez prawdziwą aplikację (in-process), model podmieniony.

Pilnujemy zasad, na których stoi bezpieczeństwo asystenta:
- odczyt idzie przez istniejące API tokenem pytającego (brak uprawnień =
  błąd narzędzia, zero danych);
- zapis jest PROPOZYCJĄ, dopóki człowiek nie kliknie, a zapis z „Cofnij”
  wykonuje się od razu i cofa go tylko jego właściciel, raz, przez 15 minut;
- zatwierdzenie wykonuje dokładnie zapisane argumenty i jest idempotentne;
- tryb „podgląd jako”, wyłączona flaga i trwająca tura kończą się przed modelem.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.jarvis import JarvisAction, JarvisConversation, JarvisConversationEntity
from app.models.job import Job, JobStatus
from app.models.my_people import MyPeopleOverride
from app.models.note import Note
from app.models.note_mention import NoteMention
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.talent_pool import TalentPool, TalentPoolMembership
from app.models.user import User, UserRole
from app.services.jarvis import actions as jarvis_actions
from tests._jarvis_helpers import (
    ScriptedModel,
    enable_jarvis,
    fake_message,
    make_candidate,
    make_user,
    parse_sse,
    text_block,
    tool_block,
)

pytestmark = pytest.mark.asyncio


async def _chat(client, headers, message, **extra):
    resp = await client.post(
        "/api/jarvis/chat", json={"message": message, **extra}, headers=headers
    )
    return resp


async def test_read_tool_round_trip_goes_through_the_real_api(app_client, monkeypatch):
    model = ScriptedModel(
        [
            fake_message(
                tool_block("search_help", {"query": "zamówienia"}, "toolu_help1")
            ),
            fake_message(text_block("Nie znalazłem procedury o tym tytule.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)

    resp = await _chat(app_client, headers, "Jak dodać zamówienie?")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(resp.text)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "conversation"
    assert kinds[-1] == "done"
    steps = [e for e in events if e["type"] == "step" and e["tool"] == "search_help"]
    assert [s["status"] for s in steps] == ["running", "done"]
    assert events[-2] == {
        "type": "message",
        "markdown": "Nie znalazłem procedury o tym tytule.",
        "final": True,
    }

    # Drugie wywołanie modelu dostało wynik narzędzia z prawdziwego /api/procedures.
    second = model.calls[1]["messages"]
    result = second[-1]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_help1"
    assert "is_error" not in result
    # Kontekst (data, rola, ekran) idzie w wiadomości użytkownika, NIE w systemie.
    first_user = model.calls[0]["messages"][0]["content"]
    assert first_user[0]["text"].startswith("[Kontekst")
    assert "Kontekst" not in model.calls[0]["system"]
    assert model.calls[0]["cache_system"] is True
    assert model.calls[0]["tools"][-1]["cache_control"] == {"type": "ephemeral"}

    conversation_id = events[0]["conversation_id"]
    detail = await app_client.get(
        f"/api/jarvis/conversations/{conversation_id}", headers=headers
    )
    assert detail.status_code == 200
    items = detail.json()["items"]
    assert items[0] == {
        "kind": "message",
        "role": "user",
        "markdown": "Jak dodać zamówienie?",
    }
    assert items[-1]["markdown"] == "Nie znalazłem procedury o tym tytule."

    status = await app_client.get("/api/jarvis/status", headers=headers)
    assert status.json()["available"] is True
    assert status.json()["used_today"] >= 1
    assert status.json()["busy"] is False


async def test_tools_outside_the_users_sections_are_not_offered(
    app_client, monkeypatch
):
    model = ScriptedModel(
        [
            fake_message(
                tool_block("finance_order_changes", {"year": 2026, "month": 9})
            ),
            fake_message(text_block("Nie mam do tego dostępu.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)

    resp = await _chat(app_client, headers, "Pokaż zmiany w zamówieniach za wrzesień")
    assert resp.status_code == 200
    offered = {tool["name"] for tool in model.calls[0]["tools"]}
    assert "finance_order_changes" not in offered
    assert "search_candidates" in offered

    result = model.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert "niedostępne" in result["content"]


async def test_api_denial_reaches_the_model_as_an_error_not_data(
    app_client, monkeypatch
):
    """Nawet gdy narzędzie JEST na liście, API egzekwuje uprawnienia samo."""
    from app.api import jarvis as jarvis_api
    from app.services.jarvis import tools as jarvis_tools

    model = ScriptedModel(
        [
            fake_message(
                tool_block("finance_order_changes", {"year": 2026, "month": 9})
            ),
            fake_message(text_block("Brak dostępu.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    # Symulujemy błąd filtra: podajemy modelowi wszystkie narzędzia.
    monkeypatch.setattr(
        jarvis_api,
        "tools_for_user",
        lambda _sections, **_hr: list(jarvis_tools.ALL_TOOLS),
    )
    _, headers = await make_user(UserRole.recruiter)

    resp = await _chat(app_client, headers, "Zmiany w zamówieniach")
    assert resp.status_code == 200
    result = model.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert result["content"].startswith("Brak uprawnień")


async def _make_pool(owner_id: int) -> int:
    async with AsyncSessionLocal() as db:
        pool = TalentPool(
            name=f"Pula Jarvisa {uuid.uuid4().hex[:6]}", created_by=owner_id
        )
        db.add(pool)
        await db.commit()
        return pool.id


async def _pool_members(pool_id: int) -> list[int]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(TalentPoolMembership.candidate_id).where(
                        TalentPoolMembership.talent_pool_id == pool_id
                    )
                )
            ).scalars()
        )


async def test_write_tool_only_proposes_and_confirm_executes_once(
    app_client, monkeypatch
):
    """Zapis BEZ „Cofnij” (tu: pula talentów) czeka na kliknięcie „Zrób to”."""
    candidate_id = await make_candidate("Propozycja")
    user_id, headers = await make_user(UserRole.admin)
    pool_id = await _make_pool(user_id)
    model = ScriptedModel(
        [
            fake_message(
                tool_block(
                    "add_to_talent_pool",
                    {
                        "pool_id": pool_id,
                        "candidate_id": candidate_id,
                        "_display": {"candidate_id": "Wstrzyknięta Nazwa"},
                    },
                )
            ),
            fake_message(
                text_block("Przygotowałem dodanie do puli — zatwierdź kartę.")
            ),
        ]
    )
    enable_jarvis(monkeypatch, model)

    resp = await _chat(app_client, headers, "Dodaj ją do puli")
    assert resp.status_code == 200
    events = parse_sse(resp.text)
    proposed = [e for e in events if e["type"] == "action_proposed"]
    assert len(proposed) == 1
    action = proposed[0]["action"]
    assert action["status"] == "proposed"
    # Nazwa na karcie przeczytana przez API, nie wstrzyknięta przez model.
    assert "Anna Propozycja" in action["preview"]["text"]
    assert "Wstrzyknięta" not in action["preview"]["text"]

    assert await _pool_members(pool_id) == [], "propozycja nie może niczego zapisać"
    async with AsyncSessionLocal() as db:
        linked = await db.scalar(
            select(JarvisConversationEntity).where(
                JarvisConversationEntity.entity_type == "candidate",
                JarvisConversationEntity.entity_id == candidate_id,
            )
        )
        assert linked is not None

    confirm = await app_client.post(
        f"/api/jarvis/actions/{action['id']}/confirm", headers=headers
    )
    assert confirm.status_code == 200, confirm.text
    body = confirm.json()
    assert body["message"] == "Kandydat dodany do puli."
    assert body["action"]["status"] == "executed"
    assert body["action"]["undo"] is None
    assert await _pool_members(pool_id) == [candidate_id]

    again = await app_client.post(
        f"/api/jarvis/actions/{action['id']}/confirm", headers=headers
    )
    assert again.status_code == 409


async def test_reversible_write_runs_at_once_and_undo_reverts_it(
    app_client, monkeypatch
):
    """Notatka (decyzja 27.10.2026): od razu, z „Cofnij” — jeden raz, tylko własna."""
    candidate_id = await make_candidate("Odrazu")
    model = ScriptedModel(
        [
            fake_message(
                tool_block(
                    "create_note",
                    {"candidate_id": candidate_id, "content": "Dostępna od listopada."},
                )
            ),
            fake_message(text_block("Zrobione.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.admin)
    _, stranger = await make_user(UserRole.admin)

    events = parse_sse((await _chat(app_client, headers, "dodaj notatkę")).text)
    card = next(e for e in events if e["type"] == "action_proposed")
    action = card["action"]
    assert action["status"] == "executed"
    assert action["undo"]["state"] == "available"
    assert "undo_calls" not in (action["result"] or {}), (
        "wywołania odwrotne zostają na serwerze"
    )
    assert ["candidate-notes"] in card["invalidates"]
    result = model.calls[1]["messages"][-1]["content"][0]
    assert result["content"].startswith("WYKONANO od razu")

    async def contents() -> list[str]:
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                select(Note.content).where(Note.candidate_id == candidate_id)
            )
            return list(rows.scalars())

    assert await contents() == ["Dostępna od listopada."]

    foreign = await app_client.post(
        f"/api/jarvis/actions/{action['id']}/undo", headers=stranger
    )
    assert foreign.status_code == 404
    undo = await app_client.post(
        f"/api/jarvis/actions/{action['id']}/undo", headers=headers
    )
    assert undo.status_code == 200, undo.text
    assert undo.json()["action"]["undo"]["state"] == "done"
    assert await contents() == []
    twice = await app_client.post(
        f"/api/jarvis/actions/{action['id']}/undo", headers=headers
    )
    assert twice.status_code == 409

    detail = await app_client.get(
        f"/api/jarvis/conversations/{events[0]['conversation_id']}", headers=headers
    )
    rebuilt = next(i for i in detail.json()["items"] if i["kind"] == "action")
    assert rebuilt["action"]["undo"]["state"] == "done"


async def test_note_with_a_mention_waits_for_a_click_and_has_no_undo(
    app_client, monkeypatch
):
    """Wzmianka to dzwonek i mail do innej osoby. „Cofnij” nie wyciągnie maila
    ze skrzynki, więc taka notatka nie wychodzi bez kliknięcia."""
    person = await make_candidate("Zewzmianka")
    colleague_id, _ = await make_user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        colleague_email = await db.scalar(
            select(User.email).where(User.id == colleague_id)
        )
    _, headers = await make_user(UserRole.admin)
    content = f"@{colleague_email} sprawdź tę osobę"

    card, model = await _run_now(
        app_client,
        monkeypatch,
        headers,
        "create_note",
        {"candidate_id": person, "content": content},
    )

    async def mentions() -> list[int]:
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                select(NoteMention.user_id)
                .join(Note, Note.id == NoteMention.note_id)
                .where(Note.candidate_id == person)
            )
            return list(rows.scalars())

    assert card["action"]["status"] == "proposed"
    assert await mentions() == [], "bez kliknięcia nikt nie dostaje wzmianki"
    told = model.calls[1]["messages"][-1]["content"][0]["content"]
    assert "CZEKA na zatwierdzenie" in told

    confirm = await app_client.post(
        f"/api/jarvis/actions/{card['action']['id']}/confirm", headers=headers
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["action"]["undo"] is None
    assert await mentions() == [colleague_id]


async def test_undo_window_closes_after_fifteen_minutes(app_client, monkeypatch):
    candidate_id = await make_candidate("Stara")
    model = ScriptedModel(
        [
            fake_message(
                tool_block(
                    "create_note", {"candidate_id": candidate_id, "content": "x"}
                )
            ),
            fake_message(text_block("Zrobione.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.admin)
    events = parse_sse((await _chat(app_client, headers, "notatka")).text)
    action_id = next(e for e in events if e["type"] == "action_proposed")["action"][
        "id"
    ]
    async with AsyncSessionLocal() as db:
        row = await db.get(JarvisAction, uuid.UUID(action_id))
        row.decided_at = datetime.now(timezone.utc) - timedelta(minutes=16)
        await db.commit()
    late = await app_client.post(
        f"/api/jarvis/actions/{action_id}/undo", headers=headers
    )
    assert late.status_code == 409


async def _make_job() -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Jarvis klient {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Jarvis rekrutacja {tag}",
            client_id=client.id,
            status=JobStatus.published,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _put_on_board(job_id: int, candidate_id: int, stage: PipelineStage) -> None:
    async with AsyncSessionLocal() as db:
        db.add(CandidateStage(candidate_id=candidate_id, job_id=job_id, stage=stage))
        await db.commit()


async def _board_people(job_id: int) -> set[int]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(CandidateStage.candidate_id).where(CandidateStage.job_id == job_id)
        )
        return set(rows.scalars())


async def _run_now(app_client, monkeypatch, headers, tool: str, args: dict):
    """Tura z jednym zapisem od razu: zwraca kartę i model (z wynikiem narzędzia)."""
    model = ScriptedModel(
        [fake_message(tool_block(tool, args)), fake_message(text_block("Zrobione."))]
    )
    enable_jarvis(monkeypatch, model)
    events = parse_sse((await _chat(app_client, headers, "zrób to")).text)
    return next(e for e in events if e["type"] == "action_proposed"), model


async def test_add_to_job_at_once_tells_model_who_was_skipped_and_undo_takes_only_added(
    app_client, monkeypatch
):
    job_id = await _make_job()
    newcomer = await make_candidate("Nowa")
    already = await make_candidate("Juzjest")
    await _put_on_board(job_id, already, PipelineStage.new)
    _, headers = await make_user(UserRole.admin)

    card, model = await _run_now(
        app_client,
        monkeypatch,
        headers,
        "add_candidates_to_job",
        {"job_id": job_id, "candidate_ids": [newcomer, already]},
    )
    action = card["action"]
    assert action["status"] == "executed"
    assert action["undo"]["state"] == "available"
    assert await _board_people(job_id) == {newcomer, already}
    told = model.calls[1]["messages"][-1]["content"][0]["content"]
    assert told.startswith("WYKONANO od razu")
    assert "skipped" in told and str(already) in told

    undo = await app_client.post(
        f"/api/jarvis/actions/{action['id']}/undo", headers=headers
    )
    assert undo.status_code == 200, undo.text
    assert undo.json()["action"]["undo"]["state"] == "done"
    assert await _board_people(job_id) == {already}, (
        "cofnięcie nie rusza osoby, która była tu wcześniej"
    )


async def test_add_to_job_where_everyone_is_skipped_is_not_done(
    app_client, monkeypatch
):
    job_id = await _make_job()
    already = await make_candidate("Wszyscyjuz")
    await _put_on_board(job_id, already, PipelineStage.new)
    _, headers = await make_user(UserRole.admin)

    card, model = await _run_now(
        app_client,
        monkeypatch,
        headers,
        "add_candidates_to_job",
        {"job_id": job_id, "candidate_ids": [already]},
    )
    assert card["action"]["status"] == "failed"
    assert card["action"]["undo"] is None
    assert card["action"]["result"]["error"].startswith("Nikogo nie dodano")
    result = model.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert result["content"].startswith("Nie udało się")


async def test_undo_of_add_after_a_move_fails_visibly_and_keeps_the_person(
    app_client, monkeypatch
):
    """Ruch karty po dodaniu: „Cofnij” nie kasuje przebiegu procesu."""
    job_id = await _make_job()
    person = await make_candidate("Poruchu")
    _, headers = await make_user(UserRole.admin)
    card, _ = await _run_now(
        app_client,
        monkeypatch,
        headers,
        "add_candidates_to_job",
        {"job_id": job_id, "candidate_ids": [person]},
    )
    await _put_on_board(job_id, person, PipelineStage.screening)

    undo = await app_client.post(
        f"/api/jarvis/actions/{card['action']['id']}/undo", headers=headers
    )
    assert undo.status_code == 200, undo.text
    assert undo.json()["action"]["undo"]["state"] == "failed"
    assert "Nie udało się cofnąć" in undo.json()["message"]
    assert await _board_people(job_id) == {person}


async def test_undo_says_it_when_the_note_from_adding_stays(app_client, monkeypatch):
    job_id = await _make_job()
    person = await make_candidate("Znotatka")
    _, headers = await make_user(UserRole.admin)
    card, _ = await _run_now(
        app_client,
        monkeypatch,
        headers,
        "add_candidates_to_job",
        {"job_id": job_id, "candidate_ids": [person], "note": "Polecona przez zespół."},
    )
    undo = await app_client.post(
        f"/api/jarvis/actions/{card['action']['id']}/undo", headers=headers
    )
    assert undo.status_code == 200, undo.text
    assert "zostaje w profilu" in undo.json()["message"]


async def test_undo_of_snooze_brings_back_the_earlier_pin(app_client, monkeypatch):
    person = await make_candidate("Moichludzi")
    user_id, headers = await make_user(UserRole.admin)

    async def override() -> str | None:
        async with AsyncSessionLocal() as db:
            return await db.scalar(
                select(MyPeopleOverride.kind).where(
                    MyPeopleOverride.user_id == user_id,
                    MyPeopleOverride.candidate_id == person,
                )
            )

    pin, _ = await _run_now(
        app_client, monkeypatch, headers, "pin_my_person", {"candidate_id": person}
    )
    assert pin["action"]["undo"]["state"] == "available"
    assert await override() == "pinned"
    snooze, _ = await _run_now(
        app_client,
        monkeypatch,
        headers,
        "snooze_my_person",
        {"candidate_id": person, "reason": "no_contact"},
    )
    assert await override() == "snoozed"

    undo = await app_client.post(
        f"/api/jarvis/actions/{snooze['action']['id']}/undo", headers=headers
    )
    assert undo.json()["action"]["undo"]["state"] == "done"
    assert await override() == "pinned"
    undo_pin = await app_client.post(
        f"/api/jarvis/actions/{pin['action']['id']}/undo", headers=headers
    )
    assert undo_pin.json()["action"]["undo"]["state"] == "done"
    assert await override() is None


async def test_crash_during_undo_closes_the_state_instead_of_spinning(
    app_client, monkeypatch
):
    person = await make_candidate("Awaria")
    _, headers = await make_user(UserRole.admin)
    card, _ = await _run_now(
        app_client,
        monkeypatch,
        headers,
        "create_note",
        {"candidate_id": person, "content": "x"},
    )

    async def boom(*_args, **_kwargs):
        raise RuntimeError("transport padł")

    monkeypatch.setattr(jarvis_actions.JarvisTransport, "call", boom)
    undo = await app_client.post(
        f"/api/jarvis/actions/{card['action']['id']}/undo", headers=headers
    )
    assert undo.status_code == 200, undo.text
    assert undo.json()["action"]["undo"]["state"] == "failed"


async def test_undo_stuck_running_after_a_restart_reads_as_failed() -> None:
    long_ago = datetime.now(timezone.utc) - timedelta(minutes=16)
    row = jarvis_actions.ActionRow(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        tool_use_id="t",
        tool_name="create_note",
        args={},
        preview={},
        status="executed",
        result={"undo_calls": [{"method": "DELETE"}], "undo_state": "running"},
        created_at=long_ago,
        decided_at=long_ago,
    )
    assert jarvis_actions.serialize_action(row)["undo"]["state"] == "failed"


async def test_reject_and_foreign_user_cannot_touch_the_action(app_client, monkeypatch):
    candidate_id = await make_candidate("Odrzucona")
    model = ScriptedModel(
        [
            fake_message(
                tool_block("refresh_activity_summary", {"candidate_id": candidate_id})
            ),
            fake_message(text_block("Gotowe do zatwierdzenia.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, owner = await make_user(UserRole.admin)
    _, stranger = await make_user(UserRole.admin)

    events = parse_sse((await _chat(app_client, owner, "notatka")).text)
    action_id = next(e for e in events if e["type"] == "action_proposed")["action"][
        "id"
    ]

    assert (
        await app_client.post(
            f"/api/jarvis/actions/{action_id}/confirm", headers=stranger
        )
    ).status_code == 404
    conversation_id = events[0]["conversation_id"]
    assert (
        await app_client.get(
            f"/api/jarvis/conversations/{conversation_id}", headers=stranger
        )
    ).status_code == 404

    rejected = await app_client.post(
        f"/api/jarvis/actions/{action_id}/reject", headers=owner
    )
    assert rejected.status_code == 200
    assert rejected.json()["action"]["status"] == "rejected"
    assert (
        await app_client.post(f"/api/jarvis/actions/{action_id}/confirm", headers=owner)
    ).status_code == 409


async def test_expired_proposal_cannot_be_confirmed(app_client, monkeypatch):
    candidate_id = await make_candidate("Wygasla")
    model = ScriptedModel(
        [
            fake_message(
                tool_block("refresh_activity_summary", {"candidate_id": candidate_id})
            ),
            fake_message(text_block("Czekam.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.admin)
    events = parse_sse((await _chat(app_client, headers, "notatka")).text)
    action_id = next(e for e in events if e["type"] == "action_proposed")["action"][
        "id"
    ]
    async with AsyncSessionLocal() as db:
        action = await db.get(JarvisAction, uuid.UUID(action_id))
        action.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        await db.commit()

    resp = await app_client.post(
        f"/api/jarvis/actions/{action_id}/confirm", headers=headers
    )
    assert resp.status_code == 409
    assert "wygasła" in resp.json()["detail"]


async def test_open_screen_emits_a_link_and_executes_nothing(app_client, monkeypatch):
    model = ScriptedModel(
        [
            fake_message(
                tool_block(
                    "open_screen",
                    {
                        "screen": "contract",
                        "id": 7,
                        "reason": "Kliknij „Zakończ współpracę”.",
                    },
                )
            ),
            fake_message(text_block("Tego nie zrobię za Ciebie — otwórz kontrakt.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)
    events = parse_sse(
        (await _chat(app_client, headers, "Zakończ współpracę z kontraktem 7")).text
    )
    links = [e for e in events if e["type"] == "deep_link"]
    assert links == [
        {
            "type": "deep_link",
            "href": "/contracts/7",
            "label": "Kontrakt",
            "reason": "Kliknij „Zakończ współpracę”.",
        }
    ]
    # Runda 10 (F14): wynik narzędzia mówi modelowi, że ekran NIE został
    # otwarty — inaczej odpowiadał „Otworzyłem zakładkę”.
    tool_results = [
        block
        for msg in model.calls[1]["messages"]
        if isinstance(msg.get("content"), list)
        for block in msg["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert tool_results
    assert "NIE został otwarty" in json.dumps(tool_results, ensure_ascii=False)


async def test_impersonation_disabled_flag_and_busy_turn_stop_before_the_model(
    app_client, monkeypatch, app_auth_headers
):
    model = ScriptedModel([])
    enable_jarvis(monkeypatch, model)
    target_id, headers = await make_user(UserRole.recruiter)

    impersonated = await _chat(
        app_client,
        {**app_auth_headers, "X-Impersonate-User-Id": str(target_id)},
        "cześć",
    )
    assert impersonated.status_code == 403

    async with AsyncSessionLocal() as db:
        conv = JarvisConversation(
            id=uuid.uuid4(),
            user_id=target_id,
            title="trwa",
            busy_until=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
        db.add(conv)
        await db.commit()
    busy = await _chat(app_client, headers, "druga wiadomość")
    assert busy.status_code == 409

    from app.core.config import settings

    monkeypatch.setattr(settings, "JARVIS_ENABLED", False)
    disabled = await _chat(app_client, headers, "cześć")
    assert disabled.status_code == 503
    assert model.calls == []


async def test_model_failure_is_a_friendly_error_and_releases_the_turn(
    app_client, monkeypatch
):
    from app.services import claude_client

    def boom(**_kwargs):
        raise claude_client.ClaudeOverloaded("przeciążony")

    enable_jarvis(monkeypatch, ScriptedModel([]))
    monkeypatch.setattr(claude_client, "call_claude", boom)
    _, headers = await make_user(UserRole.recruiter)
    events = parse_sse((await _chat(app_client, headers, "cześć")).text)
    errors = [e for e in events if e["type"] == "error"]
    assert errors and "Nie działam teraz" in errors[0]["message"]
    conversation_id = uuid.UUID(events[0]["conversation_id"])
    async with AsyncSessionLocal() as db:
        conv = await db.get(JarvisConversation, conversation_id)
        assert conv.busy_until is None


async def test_candidate_hard_delete_erases_linked_conversations(
    app_client, monkeypatch, app_auth_headers
):
    candidate_id = await make_candidate("Rodo")
    model = ScriptedModel(
        [
            fake_message(tool_block("get_candidate", {"candidate_id": candidate_id})),
            fake_message(text_block("Anna jest dostępna.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.admin)
    events = parse_sse(
        (await _chat(app_client, headers, "Kim jest ta kandydatka?")).text
    )
    conversation_id = uuid.UUID(events[0]["conversation_id"])

    deleted = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert deleted.status_code == 204, deleted.text
    async with AsyncSessionLocal() as db:
        assert await db.get(JarvisConversation, conversation_id) is None


async def test_conversation_list_and_delete_are_owner_scoped(app_client, monkeypatch):
    model = ScriptedModel([fake_message(text_block("Cześć!"))])
    enable_jarvis(monkeypatch, model)
    _, owner = await make_user(UserRole.recruiter)
    _, stranger = await make_user(UserRole.recruiter)
    events = parse_sse((await _chat(app_client, owner, "Cześć Jarvis")).text)
    conversation_id = events[0]["conversation_id"]

    listed = await app_client.get("/api/jarvis/conversations", headers=owner)
    assert [c["id"] for c in listed.json()][:1] == [conversation_id]
    assert listed.json()[0]["title"] == "Cześć Jarvis"
    assert conversation_id not in [
        c["id"]
        for c in (
            await app_client.get("/api/jarvis/conversations", headers=stranger)
        ).json()
    ]

    assert (
        await app_client.delete(
            f"/api/jarvis/conversations/{conversation_id}", headers=stranger
        )
    ).status_code == 404
    assert (
        await app_client.delete(
            f"/api/jarvis/conversations/{conversation_id}", headers=owner
        )
    ).status_code == 204


async def test_candidate_delete_erases_conversation_found_via_global_search(
    app_client, monkeypatch, app_auth_headers
):
    """Audyt 25.09.2026: `global_search` zwraca nazwisko i `/candidates/{id}`,
    ale nie jest narzędziem „kandydackim”, więc rozmowa nie była wiązana
    z osobą i przeżywała jej usunięcie (art. 17)."""
    lastname = f"Szukana-{uuid.uuid4().hex[:6]}"
    candidate_id = await make_candidate(lastname)
    model = ScriptedModel(
        [
            fake_message(tool_block("global_search", {"query": lastname})),
            fake_message(text_block("Znalazłem jedną osobę.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.admin)
    events = parse_sse((await _chat(app_client, headers, f"Kto to {lastname}?")).text)
    conversation_id = uuid.UUID(events[0]["conversation_id"])

    async with AsyncSessionLocal() as db:
        linked = (
            (
                await db.execute(
                    select(JarvisConversationEntity.entity_id).where(
                        JarvisConversationEntity.conversation_id == conversation_id,
                        JarvisConversationEntity.entity_type == "candidate",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert candidate_id in linked

    deleted = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert deleted.status_code == 204, deleted.text
    async with AsyncSessionLocal() as db:
        assert await db.get(JarvisConversation, conversation_id) is None
