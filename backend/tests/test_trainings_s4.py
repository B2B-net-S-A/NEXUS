"""Szkolenia S4 (0698): rozdziały i podsumowanie z AI, próba techniczna, obowiązkowe
dla roli, „Szukamy trenerów”.

Graph i model są udawane — sprawdzamy, co NEXUS zleca i co zapisuje, gdy odpowiedź
przyjdzie albo nie. Dane fikcyjne — repo jest publiczne.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, is_business_day
from app.models.training import Training, TrainingRegistration, TrainingTranscript
from app.models.user import UserRole
from app.services.m365 import teams_training_graph
from app.services.m365.teams_training_graph import RecordingRef
from app.services.trainings import ai_summary, core, recordings, teams
from tests.care_announcements_seed import headers, make_user
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    BASE,
    install_mailer,
    make_person,
    portal_all,
    portal_restored,
    session_headers,
)
from tests.test_trainings_flow import STAFF, _order, _storage  # noqa: F401
from tests.test_trainings_teams import FakeGraph, _employee_training, graph  # noqa: F401

# ── Rozdziały i podsumowanie z transkryptu ───────────────────────────────────

LONG_VTT = """WEBVTT

00:00:05.000 --> 00:00:09.000
<v Prowadzący>Dzień dobry, zaczynamy od zgody RODO.

00:12:40.000 --> 00:12:48.000
<v Prowadzący>Teraz ataki z użyciem AI: phishing i deepfake.

00:31:52.000 --> 00:31:58.000
<v Prowadzący>Zgoda RODO musi być aktualna w dniu wysyłki.

01:02:10.000 --> 01:02:15.000
<v Prowadzący>Na koniec pytania od was.
"""

ANSWER = {
    "summary": "Szkolenie o RODO i atakach z użyciem AI.",
    "chapters": [
        {"start": "00:00:05", "title": "Zgoda RODO"},
        {"start": "00:12:40", "title": "Ataki z użyciem AI"},
        {"start": "00:20:00", "title": "Rozdział z wymyśloną sekundą"},
        {"start": "01:02:10", "title": "Pytania"},
    ],
}


def test_chapters_keep_only_seconds_from_the_transcript() -> None:
    lines = ai_summary.transcript_lines(LONG_VTT)
    assert [s for s, _ in lines] == [5, 760, 1912, 3730]
    # Model nie widzi nazw mówców.
    assert "Prowadzący" not in ai_summary.render_transcript(lines)
    assert ai_summary.render_transcript(lines).startswith("[00:00:05] Dzień dobry")

    summary, chapters = ai_summary.parse_answer(
        json.dumps(ANSWER), {s for s, _ in lines}
    )
    assert summary == ANSWER["summary"]
    assert [(c["start_second"], c["title"]) for c in chapters] == [
        (5, "Zgoda RODO"),
        (760, "Ataki z użyciem AI"),
        (3730, "Pytania"),
    ]


def test_too_few_chapters_and_garbage_fall_back() -> None:
    one = {"summary": "S", "chapters": [{"start": "00:00:05", "title": "Jedyny"}]}
    assert ai_summary.parse_answer(json.dumps(one), {5}) == ("S", [])
    assert ai_summary.parse_answer("to nie JSON", {5}) == (None, [])
    assert ai_summary.parse_answer('["lista"]', {5}) == (None, [])
    fenced = "```json\n" + json.dumps(ANSWER) + "\n```"
    assert ai_summary.parse_answer(fenced, set())[0] == ANSWER["summary"]


def test_ai_chapters_replace_agenda_only_when_present() -> None:
    training = Training(
        title="T",
        agenda=[
            {"title": "Moduł 1", "minutes": 30},
            {"title": "Moduł 2", "minutes": 20},
        ],
    )
    assert [(c["start_second"], c["source"]) for c in core.chapters(training)] == [
        (0, "agenda"),
        (1800, "agenda"),
    ]
    assert core.chapters(training, []) == core.chapters(training)
    ai = [{"title": "Wstęp", "start_second": 5}, {"title": "AI", "start_second": 760}]
    assert core.chapters(training, ai) == [
        {
            "title": "Wstęp",
            "start_minute": 0,
            "start_second": 5,
            "source": "transcript",
        },
        {
            "title": "AI",
            "start_minute": 12,
            "start_second": 760,
            "source": "transcript",
        },
    ]


async def _imported_training(app_client, graph, monkeypatch, *, answer) -> tuple:  # noqa: F811
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    training_id = await _employee_training(app_client, tcm, lecturer)
    graph.vtt = LONG_VTT
    graph.recordings = [
        RecordingRef(id="rec-1", created="2026-11-12T17:31Z", content_url=None)
    ]
    calls: list[str] = []

    def model(chain, system, prompt):
        calls.append(prompt)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(ai_summary, "_call_model", model)
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda model: True
    )
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Training)
            .where(Training.id == training_id)
            .values(
                session_date=business_today() - timedelta(days=1),
                recording_next_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await recordings.fetch_due(db) == {"imported": 1}
    return tcm, training_id, calls


@pytest.mark.usefixtures("_storage")
async def test_import_adds_ai_chapters_and_summary(
    app_client,
    graph,  # noqa: F811
    monkeypatch,
) -> None:
    tcm, training_id, calls = await _imported_training(
        app_client, graph, monkeypatch, answer=json.dumps(ANSWER)
    )
    assert len(calls) == 1 and "[00:12:40] Teraz ataki" in calls[0]
    view = (await app_client.get(f"{STAFF}/{training_id}", headers=headers(tcm))).json()
    training = view["training"]
    assert training["summary"] == ANSWER["summary"]
    assert training["summary_status"] == "done"
    assert [c["start_second"] for c in training["chapters"]] == [5, 760, 3730]
    assert {c["source"] for c in training["chapters"]} == {"transcript"}

    # W bibliotece po publikacji: te same rozdziały i podsumowanie.
    second = await make_user(UserRole.talent_community_manager, name="Teresa")
    published = await app_client.post(
        f"{STAFF}/{training_id}/publish",
        headers=headers(second),
        json={"publish": True},
    )
    assert published.status_code == 200, published.text
    library = (await app_client.get(f"{STAFF}/library", headers=headers(tcm))).json()
    item = next(r for r in library["recordings"] if r["id"] == training_id)
    assert item["summary"] == ANSWER["summary"]
    assert [c["start_second"] for c in item["chapters"]] == [5, 760, 3730]


@pytest.mark.usefixtures("_storage")
async def test_model_failure_keeps_the_recording_and_agenda_chapters(
    app_client,
    graph,  # noqa: F811
    monkeypatch,
) -> None:
    tcm, training_id, calls = await _imported_training(
        app_client, graph, monkeypatch, answer=RuntimeError("model down")
    )
    assert len(calls) == 1
    view = (await app_client.get(f"{STAFF}/{training_id}", headers=headers(tcm))).json()
    training = view["training"]
    assert training["teams"]["recording"] == "imported"
    assert training["summary"] is None
    assert training["summary_status"] == "failed"
    assert all(c["source"] == "agenda" for c in training["chapters"])


@pytest.mark.usefixtures("_storage")
async def test_no_provider_key_skips_the_model(
    app_client,
    graph,  # noqa: F811
    monkeypatch,
) -> None:
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    training_id = await _employee_training(app_client, tcm, lecturer)
    async with AsyncSessionLocal() as db:
        db.add(TrainingTranscript(training_id=training_id, vtt=LONG_VTT))
        await db.commit()
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda model: False
    )

    def never(*_args):
        raise AssertionError("model nie powinien być wołany bez klucza")

    monkeypatch.setattr(ai_summary, "_call_model", never)
    async with AsyncSessionLocal() as db:
        assert await ai_summary.summarize(db, training_id) == "skipped"
        row = await db.get(TrainingTranscript, training_id)
        assert row.summary_status == "skipped" and row.ai_chapters == []


# ── Próba techniczna ─────────────────────────────────────────────────────────


def _two_business_days_before(day):
    remaining = 2
    while remaining:
        day -= timedelta(days=1)
        if is_business_day(
            datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
        ):
            remaining -= 1
    return day


@pytest.fixture
def settings_calls(graph, monkeypatch) -> list[str]:  # noqa: F811
    calls: list[str] = []

    async def rehearsal_settings(user_id: str, meeting_id: str) -> None:
        calls.append(meeting_id)

    monkeypatch.setattr(teams_training_graph, "rehearsal_settings", rehearsal_settings)
    return calls


async def test_rehearsal_is_a_second_short_meeting_with_the_lecturer(
    app_client,
    graph,  # noqa: F811
    settings_calls,
) -> None:
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    training_id = await _employee_training(app_client, tcm, lecturer, rehearsal=True)

    assert len(graph.created) == 2
    _, main = graph.created[0]
    upn, rehearsal = graph.created[1]
    assert upn == "szkolenia@example.com"
    assert rehearsal["isOnlineMeeting"] is True
    assert rehearsal["subject"].startswith("Próba techniczna:")
    assert [a["emailAddress"]["address"] for a in rehearsal["attendees"]] == [
        lecturer.email
    ]
    session = business_today() + timedelta(days=14)
    expected_day = _two_business_days_before(session)
    assert rehearsal["start"]["dateTime"] == f"{expected_day.isoformat()}T16:00:00"
    assert rehearsal["end"]["dateTime"] == f"{expected_day.isoformat()}T16:15:00"
    # Bez nagrywania: osobne ustawienia spotkania próby, nie te z nagrywaniem.
    assert settings_calls == ["meeting-1"]
    assert graph.presenters == [[lecturer.email]]

    view = (await app_client.get(f"{STAFF}/{training_id}", headers=headers(tcm))).json()
    assert view["training"]["order"]["rehearsal"] is True
    assert view["training"]["rehearsal"]["status"] == "created"
    assert view["training"]["rehearsal"]["join_url"]
    assert view["training"]["rehearsal"]["minutes"] == 15

    # Prowadzący-pracownik widzi próbę w kalendarzu, słuchacz nie.
    live = (await app_client.get(f"{STAFF}/library", headers=headers(lecturer))).json()
    row = next(r for r in live["live"] if r["id"] == training_id)
    assert row["leading"] is True and row["rehearsal"]["join_url"]
    listener = await make_user(UserRole.recruiter, name="Lucyna")
    other = (await app_client.get(f"{STAFF}/library", headers=headers(listener))).json()
    assert next(r for r in other["live"] if r["id"] == training_id)["rehearsal"] is None

    # Panel trenera dostaje ten sam blok (widok trenera po podpisie).
    async with AsyncSessionLocal() as db:
        training = await db.get(Training, training_id)
        trainer = await core.trainer_view(db, training)
    assert trainer["rehearsal"]["join_url"] == view["training"]["rehearsal"]["join_url"]

    # Nowy termin przesuwa próbę, bez nowego spotkania.
    later = session + timedelta(days=7)
    moved = await app_client.put(
        f"{STAFF}/{training_id}",
        headers=headers(tcm),
        json=_order(deliverables=[], session_date=later.isoformat(), rehearsal=True),
    )
    assert moved.status_code == 200, moved.text
    assert len(graph.created) == 2
    updated = [p for event_id, p in graph.updated if event_id == "ev-2"]
    assert updated[-1]["start"]["dateTime"].startswith(
        _two_business_days_before(later).isoformat()
    )

    # Odznaczenie odwołuje próbę.
    off = await app_client.put(
        f"{STAFF}/{training_id}",
        headers=headers(tcm),
        json=_order(deliverables=[], session_date=later.isoformat(), rehearsal=False),
    )
    assert off.status_code == 200
    assert graph.cancelled == ["ev-2"]
    assert off.json()["training"]["rehearsal"] is None


async def test_rehearsal_in_the_past_is_skipped_not_created(
    app_client,
    graph,  # noqa: F811
    settings_calls,
) -> None:
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    tomorrow = business_today() + timedelta(days=1)
    training_id = await _employee_training(
        app_client, tcm, lecturer, rehearsal=True, session_date=tomorrow.isoformat()
    )
    assert len(graph.created) == 1
    view = (await app_client.get(f"{STAFF}/{training_id}", headers=headers(tcm))).json()
    assert view["training"]["teams"]["status"] == "created"
    assert view["training"]["rehearsal"]["status"] == "skipped"
    assert view["training"]["rehearsal"]["join_url"] is None


async def test_rehearsal_failure_does_not_touch_the_main_meeting(
    app_client,
    graph,  # noqa: F811
    settings_calls,
    monkeypatch,
) -> None:
    original = graph.create_event

    async def fail_second(upn, payload):
        if payload["subject"].startswith("Próba techniczna"):
            raise RuntimeError("graph down")
        return await original(upn, payload)

    from app.services.m365 import teams_prep_graph

    monkeypatch.setattr(teams_prep_graph, "create_event", fail_second)
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    training_id = await _employee_training(app_client, tcm, lecturer, rehearsal=True)
    view = (await app_client.get(f"{STAFF}/{training_id}", headers=headers(tcm))).json()
    assert view["training"]["teams"]["status"] == "created"
    assert view["training"]["rehearsal"]["status"] == "failed"

    monkeypatch.setattr(teams_prep_graph, "create_event", original)
    retried = await app_client.post(
        f"{STAFF}/{training_id}/teams", headers=headers(tcm)
    )
    assert retried.json()["training"]["rehearsal"]["status"] == "created"


async def test_cancel_cancels_the_rehearsal_too(
    app_client,
    graph,  # noqa: F811
    settings_calls,
) -> None:
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    training_id = await _employee_training(app_client, tcm, lecturer, rehearsal=True)
    async with AsyncSessionLocal() as db:
        training = await db.get(Training, training_id)
        training.status = "cancelled"
        await teams.sync_meeting(db, training, now=datetime.now(timezone.utc))
        await db.commit()
    assert set(graph.cancelled) == {"ev-1", "ev-2"}


# ── Obowiązkowe dla roli ─────────────────────────────────────────────────────


async def test_mandatory_roles_register_and_invite_everyone_in_the_role(
    app_client,
    graph,  # noqa: F811
) -> None:
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.finance, name="Lena")
    accountant = await make_user(UserRole.finance, name="Fabiola")
    gone = await make_user(UserRole.finance, name="Felicja")
    recruiter = await make_user(UserRole.recruiter, name="Roksana")
    async with AsyncSessionLocal() as db:
        from app.models.user import User

        await db.execute(update(User).where(User.id == gone.id).values(is_active=False))
        await db.commit()

    refused = await app_client.post(
        STAFF,
        headers=headers(tcm),
        json={
            **_order(deliverables=[], mandatory_roles=["nie_ma_takiej"]),
            "trainer_user_id": lecturer.id,
        },
    )
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "bad_mandatory_roles"

    me = (await app_client.get(f"{STAFF}/me", headers=headers(tcm))).json()
    assert "finance" in me["mandatory_roles"] and "user" not in me["mandatory_roles"]

    training_id = await _employee_training(
        app_client, tcm, lecturer, mandatory_roles=["finance"], seat_limit=1
    )
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(TrainingRegistration).where(
                    TrainingRegistration.training_id == training_id
                )
            )
        ).all()
    by_user = {row.user_id: row for row in rows}
    # Aktywni w roli, bez prowadzącego i bez nieaktywnych; limit miejsc ich nie dotyczy.
    assert accountant.id in by_user and by_user[accountant.id].mandatory
    assert lecturer.id not in by_user and gone.id not in by_user
    assert recruiter.id not in by_user
    assert by_user[accountant.id].invite_status == "sent"
    invited = [
        a["emailAddress"]["address"]
        for _, payload in graph.created[1:]
        for a in payload["attendees"]
    ]
    assert accountant.email in invited

    live = (
        await app_client.get(f"{STAFF}/library", headers=headers(accountant))
    ).json()
    row = next(r for r in live["live"] if r["id"] == training_id)
    assert row["registered"] is True and row["mandatory"] is True
    # Obowiązkowi nie zajmują miejsc z limitu: wolne miejsce zostaje dla chętnych.
    assert row["taken"] == 0
    volunteer = await app_client.post(
        f"{STAFF}/library/{training_id}/registration",
        headers=headers(recruiter),
        json={"join": True},
    )
    assert volunteer.status_code == 200, volunteer.text
    other = await make_user(UserRole.recruiter, name="Rita")
    full = await app_client.post(
        f"{STAFF}/library/{training_id}/registration",
        headers=headers(other),
        json={"join": True},
    )
    assert full.status_code == 409 and full.json()["detail"]["code"] == "no_seats"
    view = (await app_client.get(f"{STAFF}/{training_id}", headers=headers(tcm))).json()
    assert view["training"]["order"]["mandatory_roles"] == ["finance"]
    assert view["training"]["mandatory_registrations"] >= 1

    # Obowiązkowego zapisu nie da się zdjąć samemu.
    left = await app_client.post(
        f"{STAFF}/library/{training_id}/registration",
        headers=headers(accountant),
        json={"join": False},
    )
    assert left.status_code == 409
    assert left.json()["detail"]["code"] == "mandatory"

    # Rola zdjęta z listy: zapis zostaje, ale już nieobowiązkowy.
    changed = await app_client.put(
        f"{STAFF}/{training_id}",
        headers=headers(tcm),
        json=_order(deliverables=[], mandatory_roles=[]),
    )
    assert changed.status_code == 200, changed.text
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(TrainingRegistration).where(
                TrainingRegistration.training_id == training_id,
                TrainingRegistration.user_id == accountant.id,
            )
        )
        assert row is not None and row.mandatory is False
    left = await app_client.post(
        f"{STAFF}/library/{training_id}/registration",
        headers=headers(accountant),
        json={"join": False},
    )
    assert left.status_code == 200


async def test_mandatory_roles_work_without_teams(app_client) -> None:
    """Bez Teams zapis obowiązkowy i tak powstaje: przypomnienia idą dzwonkiem."""
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    dl = await make_user(UserRole.delivery_lead, name="Dorota")
    training_id = await _employee_training(
        app_client, tcm, lecturer, mandatory_roles=["delivery_lead"]
    )
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(TrainingRegistration).where(
                TrainingRegistration.training_id == training_id,
                TrainingRegistration.user_id == dl.id,
            )
        )
        assert row is not None and row.mandatory and row.invite_status == ""


# ── Szukamy trenerów ─────────────────────────────────────────────────────────


@pytest.mark.usefixtures("portal_all")
async def test_tcm_publishes_topics_and_consultant_applies(
    app_client, monkeypatch
) -> None:
    install_mailer(monkeypatch)
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    recruiter = await make_user(UserRole.recruiter, name="Roksana")
    person = await make_person()
    consultant = await session_headers(app_client, person)

    created = await app_client.post(
        f"{STAFF}/topics",
        headers=headers(tcm),
        json={
            "title": "Terraform i IaC dla zespołów bankowych",
            "description": "2 h na żywo, ćwiczenia",
            "audience": "rekruterzy IT",
        },
    )
    assert created.status_code == 201, created.text
    topic = next(
        t
        for t in created.json()["topics"]
        if t["title"] == "Terraform i IaC dla zespołów bankowych"
    )
    assert topic["status"] == "open" and topic["applicants"] == 0
    other = await app_client.post(
        f"{STAFF}/topics", headers=headers(tcm), json={"title": "Pact w mikroserwisach"}
    )
    closed_id = next(
        t["id"] for t in other.json()["topics"] if t["title"] == "Pact w mikroserwisach"
    )
    await app_client.put(
        f"{STAFF}/topics/{closed_id}",
        headers=headers(tcm),
        json={"title": "Pact w mikroserwisach", "open": False},
    )
    assert (
        await app_client.post(
            f"{STAFF}/topics", headers=headers(recruiter), json={"title": "X"}
        )
    ).status_code == 403

    panel = (await app_client.get(f"{BASE}/trainings", headers=consultant)).json()
    wanted = {t["id"]: t for t in panel["wanted_topics"]}
    assert topic["id"] in wanted and closed_id not in wanted
    assert wanted[topic["id"]]["applied"] is False

    # Bez zgłoszenia trenera samo kliknięcie nie wystarcza.
    early = await app_client.post(
        f"{BASE}/trainer/topics/{topic['id']}", headers=consultant, json={"join": True}
    )
    assert early.status_code == 409

    # Formularz „Zostań trenerem” otwarty z tematu dopisuje temat do zgłoszenia.
    saved = await app_client.put(
        f"{BASE}/trainer",
        headers=consultant,
        json={
            "topics": ["Terraform"],
            "experience": "Prowadzę warsztaty IaC od trzech lat.",
            "topic_request_id": topic["id"],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["application"]["topic_request_ids"] == [topic["id"]]
    panel = (await app_client.get(f"{BASE}/trainings", headers=consultant)).json()
    assert next(t for t in panel["wanted_topics"] if t["id"] == topic["id"])["applied"]

    # Zamknięty temat nie przyjmie zgłoszenia.
    closed = await app_client.post(
        f"{BASE}/trainer/topics/{closed_id}", headers=consultant, json={"join": True}
    )
    assert closed.status_code == 409

    staff = (await app_client.get(f"{STAFF}/topics", headers=headers(tcm))).json()
    assert next(t for t in staff["topics"] if t["id"] == topic["id"])["applicants"] == 1
    applications = (
        await app_client.get(f"{STAFF}/applications", headers=headers(tcm))
    ).json()["applications"]
    mine = next(a for a in applications if a["contract_id"] == person.contract_id)
    assert mine["wanted_topics"] == ["Terraform i IaC dla zespołów bankowych"]

    # Wycofanie zgłoszenia na temat.
    withdrawn = await app_client.post(
        f"{BASE}/trainer/topics/{topic['id']}", headers=consultant, json={"join": False}
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["application"]["topic_request_ids"] == []


async def test_large_role_invites_go_in_batches_and_the_loop_sends_the_rest(
    app_client,
    graph,  # noqa: F811
    monkeypatch,
) -> None:
    """Cała rola to dziesiątki zaproszeń: żądanie wysyła porcję, resztę pętla."""
    monkeypatch.setattr(teams, "INVITES_PER_REQUEST", 2)
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    people = [await make_user(UserRole.back_office, name=f"Bogna{i}") for i in range(3)]
    training_id = await _employee_training(
        app_client, tcm, lecturer, mandatory_roles=["back_office"]
    )

    async def statuses() -> dict[int, str]:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.scalars(
                    select(TrainingRegistration).where(
                        TrainingRegistration.training_id == training_id
                    )
                )
            ).all()
            return {row.user_id: row.invite_status for row in rows}

    mine = {person.id for person in people}
    before = await statuses()
    assert mine <= set(before)
    # Wszyscy w roli (także z innych testów) czekają poza porcją z żądania.
    assert sum(1 for status in before.values() if status == "sent") == 2
    async with AsyncSessionLocal() as db:
        await recordings.send_pending_invites(db)
    after = await statuses()
    assert {after[person_id] for person_id in mine} == {"sent"}
