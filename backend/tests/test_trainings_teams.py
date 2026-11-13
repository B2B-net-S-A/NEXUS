"""Szkolenia w Teams (0695): spotkanie z NEXUSA, zaproszenia, nagranie, oceny.

Graph jest udawany (``FakeGraph``) — sprawdzamy, co NEXUS zleca Microsoftowi i co
zapisuje, gdy Microsoft odpowie albo nie. Dane fikcyjne — repo jest publiczne.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.notification import Notification, NotificationType
from app.models.training import (
    Training,
    TrainingAttendance,
    TrainingFile,
    TrainingTranscript,
)
from app.models.user import UserRole
from app.services import prep_meetings
from app.services.m365 import teams_prep_graph, teams_training_graph
from app.services.m365.teams_prep_graph import CreatedPrepEvent, TranscriptRef
from app.services.m365.teams_training_graph import AttendeeTime, RecordingRef
from app.services.trainings import recordings
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

ORGANIZER = "szkolenia@example.com"
JOIN = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_nexus"
VTT = """WEBVTT

00:00:05.000 --> 00:00:09.000
<v Prowadzący>Dzień dobry, zaczynamy od zgody RODO.

00:31:52.000 --> 00:31:58.000
<v Prowadzący>Zgoda RODO musi być aktualna w dniu wysyłki.
"""


class FakeGraph:
    def __init__(self) -> None:
        self.created: list[tuple[str, dict]] = []
        self.updated: list[tuple[str, dict]] = []
        self.cancelled: list[str] = []
        self.presenters: list[list[str]] = []
        self.fail_create = False
        self.recordings: list[RecordingRef] = []
        self.attendance: Optional[list[AttendeeTime]] = None
        self.vtt = VTT

    async def create_event(self, upn: str, payload: dict) -> CreatedPrepEvent:
        if self.fail_create:
            raise RuntimeError("graph down")
        self.created.append((upn, payload))
        online = payload.get("isOnlineMeeting")
        return CreatedPrepEvent(
            graph_event_id=f"ev-{len(self.created)}",
            change_key="ck",
            join_url=JOIN if online else None,
        )

    async def update_event(self, upn: str, event_id: str, payload: dict) -> str:
        self.updated.append((event_id, payload))
        return "ck2"

    async def cancel_event(self, upn: str, event_id: str, comment: str) -> str:
        self.cancelled.append(event_id)
        return "cancelled"

    async def resolve_user_id(self, upn: str) -> str:
        return "organizer-oid"

    async def find_online_meeting(self, user_id: str, join_url: str) -> str:
        return "meeting-1"

    async def enable_auto_transcription(self, user_id: str, meeting_id: str) -> None:
        return None

    async def set_presenters(self, user_id: str, meeting_id: str, emails: list[str]) -> str:
        self.presenters.append(emails)
        return "presenter"

    async def list_recordings(self, user_id: str, meeting_id: str) -> list[RecordingRef]:
        return self.recordings

    async def stream_recording(self, user_id: str, meeting_id: str, recording_id: str):
        yield b"\x00\x00\x00\x18ftypmp42"
        yield b"0" * 64

    async def list_transcripts(self, user_id: str, meeting_id: str) -> list[TranscriptRef]:
        return [TranscriptRef(id="tr-1", created="2026-11-12T17:30:00Z")]

    async def transcript_vtt(self, user_id: str, meeting_id: str, transcript_id: str) -> str:
        return self.vtt

    async def attendance_report(self, user_id: str, meeting_id: str):
        return self.attendance


@pytest.fixture
def graph(monkeypatch) -> FakeGraph:
    fake = FakeGraph()
    monkeypatch.setattr(settings, "TRAININGS_TEAMS_ENABLED", True)
    monkeypatch.setattr(settings, "TRAININGS_TEAMS_MAILBOX", ORGANIZER)
    monkeypatch.setattr(prep_meetings, "app_only_ready", lambda: True)
    for name in (
        "create_event",
        "update_event",
        "cancel_event",
        "resolve_user_id",
        "find_online_meeting",
        "enable_auto_transcription",
        "list_transcripts",
        "transcript_vtt",
    ):
        monkeypatch.setattr(teams_prep_graph, name, getattr(fake, name))
    monkeypatch.setattr(teams_training_graph, "set_presenters", fake.set_presenters)
    monkeypatch.setattr(teams_training_graph, "list_recordings", fake.list_recordings)
    monkeypatch.setattr(teams_training_graph, "stream_recording", fake.stream_recording)
    monkeypatch.setattr(teams_training_graph, "attendance", fake.attendance_report)
    return fake


async def _employee_training(app_client, tcm, lecturer, **extra: Any) -> int:
    created = await app_client.post(
        STAFF,
        headers=headers(tcm),
        json={**_order(deliverables=[], **extra), "trainer_user_id": lecturer.id},
    )
    assert created.status_code == 201, created.text
    training_id = created.json()["training"]["id"]
    sent = await app_client.post(f"{STAFF}/{training_id}/send", headers=headers(tcm))
    assert sent.status_code == 200, sent.text
    return training_id


async def _notifications(user_id: int, ntype: NotificationType) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == user_id,
                        Notification.notification_type == ntype,
                    )
                )
            ).all()
        )


@pytest.mark.usefixtures("portal_all")
async def test_nexus_creates_the_meeting_and_each_sign_up_gets_its_own_invite(
    app_client, graph, monkeypatch
) -> None:
    install_mailer(monkeypatch)
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    listener = await make_user(UserRole.recruiter, name="Lucyna")
    person = await make_person()
    consultant = await session_headers(app_client, person)

    me = (await app_client.get(f"{STAFF}/me", headers=headers(tcm))).json()
    assert me["teams_ready"] is True
    training_id = await _employee_training(app_client, tcm, lecturer)

    # Spotkanie główne: kalendarz szkolenia@, Teams, tylko prowadzący, stały transactionId.
    upn, payload = graph.created[0]
    assert upn == ORGANIZER and payload["isOnlineMeeting"] is True
    assert [a["emailAddress"]["address"] for a in payload["attendees"]] == [lecturer.email]
    assert payload["transactionId"] == f"nexus-training-{training_id}"
    assert graph.presenters == [[lecturer.email]]
    view = (await app_client.get(f"{STAFF}/{training_id}", headers=headers(tcm))).json()
    assert view["training"]["join_url"] == JOIN
    assert view["training"]["teams"]["status"] == "created"
    assert view["training"]["teams"]["recording"] == "waiting"

    # Zapis = osobne zaproszenie bez własnego spotkania; wypis = jego odwołanie.
    joined = await app_client.post(
        f"{STAFF}/library/{training_id}/registration",
        headers=headers(listener),
        json={"join": True},
    )
    assert joined.status_code == 200
    _, invite = graph.created[1]
    assert "isOnlineMeeting" not in invite
    assert [a["emailAddress"]["address"] for a in invite["attendees"]] == [listener.email]
    assert "meetup-join" in invite["body"]["content"]
    from_panel = await app_client.post(
        f"{BASE}/trainings/{training_id}/registration",
        headers=consultant,
        json={"join": True},
    )
    assert from_panel.status_code == 200
    _, panel_invite = graph.created[2]
    assert [a["emailAddress"]["address"] for a in panel_invite["attendees"]] == [person.email]

    left = await app_client.post(
        f"{STAFF}/library/{training_id}/registration",
        headers=headers(listener),
        json={"join": False},
    )
    assert left.status_code == 200
    assert graph.cancelled == ["ev-2"]

    # Zmiana terminu przesuwa spotkanie i zaproszenie konsultanta (bez nowych spotkań).
    moved = await app_client.put(
        f"{STAFF}/{training_id}",
        headers=headers(tcm),
        json={**_order(deliverables=[], time_from="17:00", time_to="20:00")},
    )
    assert moved.status_code == 200, moved.text
    assert len(graph.created) == 3
    assert {event_id for event_id, _ in graph.updated} == {"ev-1", "ev-3"}
    assert graph.updated[0][1]["start"]["dateTime"].endswith("T17:00:00")


async def test_graph_failure_keeps_the_step_and_retry_creates_the_meeting(
    app_client, graph
) -> None:
    graph.fail_create = True
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    training_id = await _employee_training(app_client, tcm, lecturer)
    view = (await app_client.get(f"{STAFF}/{training_id}", headers=headers(tcm))).json()
    assert view["training"]["status"] == "signed"
    assert view["training"]["teams"]["status"] == "failed"
    assert "graph down" in view["training"]["teams"]["error"]

    graph.fail_create = False
    retried = await app_client.post(f"{STAFF}/{training_id}/teams", headers=headers(tcm))
    assert retried.status_code == 200, retried.text
    assert retried.json()["training"]["teams"]["status"] == "created"

    recruiter = await make_user(UserRole.recruiter, name="Roksana")
    refused = await app_client.post(
        f"{STAFF}/{training_id}/teams", headers=headers(recruiter)
    )
    assert refused.status_code == 403


async def test_cancel_cancels_the_meeting_and_invites(app_client, graph) -> None:
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    listener = await make_user(UserRole.recruiter, name="Lucyna")
    training_id = await _employee_training(app_client, tcm, lecturer)
    await app_client.post(
        f"{STAFF}/library/{training_id}/registration",
        headers=headers(listener),
        json={"join": True},
    )
    # Szkolenie pracownika po wysłaniu jest „signed” i nie da się go już anulować trasą,
    # więc sprawdzamy serwis: odwołanie obejmuje spotkanie i zaproszenie.
    from app.services.trainings import teams

    async with AsyncSessionLocal() as db:
        training = await db.get(Training, training_id)
        training.status = "cancelled"
        await teams.sync_meeting(db, training, now=datetime.now(timezone.utc))
        await db.commit()
    assert set(graph.cancelled) == {"ev-1", "ev-2"}


async def test_seat_limit_refuses_the_next_sign_up(app_client, graph) -> None:
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    first = await make_user(UserRole.recruiter, name="Lucyna")
    second = await make_user(UserRole.recruiter, name="Liwia")
    training_id = await _employee_training(app_client, tcm, lecturer, seat_limit=1)
    ok = await app_client.post(
        f"{STAFF}/library/{training_id}/registration",
        headers=headers(first),
        json={"join": True},
    )
    assert ok.status_code == 200
    full = await app_client.post(
        f"{STAFF}/library/{training_id}/registration",
        headers=headers(second),
        json={"join": True},
    )
    assert full.status_code == 409
    assert full.json()["detail"]["code"] == "no_seats"
    live = (await app_client.get(f"{STAFF}/library", headers=headers(second))).json()
    row = next(r for r in live["live"] if r["id"] == training_id)
    assert row["seat_limit"] == 1 and row["taken"] == 1


@pytest.mark.usefixtures("_storage")
async def test_recording_transcript_and_attendance_come_back_from_teams(
    app_client, graph
) -> None:
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    second = await make_user(UserRole.talent_community_manager, name="Teresa")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    listener = await make_user(UserRole.recruiter, name="Lucyna")
    outsider = await make_user(UserRole.recruiter, name="Oliwia")
    training_id = await _employee_training(app_client, tcm, lecturer)
    await app_client.post(
        f"{STAFF}/library/{training_id}/registration",
        headers=headers(listener),
        json={"join": True},
    )
    # Szkolenie się odbyło: przesuwamy termin w przeszłość.
    yesterday = business_today() - timedelta(days=1)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Training)
            .where(Training.id == training_id)
            .values(
                session_date=yesterday,
                recording_next_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        await db.commit()

    # Nagrania jeszcze nie ma: czekamy dalej.
    async with AsyncSessionLocal() as db:
        assert await recordings.fetch_due(db) == {"waiting": 1}

    graph.recordings = [RecordingRef(id="rec-1", created="2026-11-12T17:31Z", content_url=None)]
    graph.attendance = [
        AttendeeTime(name="Lucyna", email=listener.email, seconds=4260),
        AttendeeTime(name="Gość", email="gosc@example.com", seconds=600),
    ]
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Training)
            .where(Training.id == training_id)
            .values(recording_next_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await recordings.fetch_due(db) == {"imported": 1}

    async with AsyncSessionLocal() as db:
        files = (
            await db.scalars(
                select(TrainingFile).where(TrainingFile.training_id == training_id)
            )
        ).all()
        assert [(f.kind, f.status, f.uploaded_by_user_id) for f in files] == [
            ("recording", "accepted", None)
        ]
        assert (await db.get(TrainingTranscript, training_id)).vtt.startswith("WEBVTT")
        present = (
            await db.scalars(
                select(TrainingAttendance).where(
                    TrainingAttendance.training_id == training_id
                )
            )
        ).all()
        assert {(a.user_id, a.minutes) for a in present} == {
            (listener.id, 71),
            (None, 10),
        }
    assert await _notifications(tcm.id, NotificationType.training_recording)

    # Przed decyzją TCM nagrania nie widać nikomu.
    library = (await app_client.get(f"{STAFF}/library", headers=headers(listener))).json()
    assert training_id not in [r["id"] for r in library["recordings"]]

    # Udostępnienie zapisanym: zapisana widzi i odtwarza, niezapisana nie.
    shared = await app_client.post(
        f"{STAFF}/{training_id}/share", headers=headers(second), json={"share": True}
    )
    assert shared.status_code == 200, shared.text
    assert await _notifications(listener.id, NotificationType.training_recording)
    library = (await app_client.get(f"{STAFF}/library", headers=headers(listener))).json()
    item = next(r for r in library["recordings"] if r["id"] == training_id)
    assert item["scope"] == "registered"
    file_id = item["files"][0]["id"]
    ticket = await app_client.get(
        f"{STAFF}/library/files/{file_id}/ticket", headers=headers(listener)
    )
    assert ticket.status_code == 200 and "t=reg." in ticket.json()["url"]
    played = await app_client.get(ticket.json()["url"])
    assert played.status_code in (200, 206)
    other = (await app_client.get(f"{STAFF}/library", headers=headers(outsider))).json()
    assert training_id not in [r["id"] for r in other["recordings"]]
    refused = await app_client.get(
        f"{STAFF}/library/files/{file_id}/ticket", headers=headers(outsider)
    )
    assert refused.status_code == 404

    # Transkrypt: wyszukiwanie z sekundą, tylko dla widzących nagranie.
    found = await app_client.get(
        f"{STAFF}/library/{training_id}/transcript",
        params={"q": "rodo"},
        headers=headers(listener),
    )
    assert [h["second"] for h in found.json()["hits"]] == [5, 1912]
    assert (
        await app_client.get(
            f"{STAFF}/library/{training_id}/transcript", headers=headers(outsider)
        )
    ).status_code == 404

    # Cofnięcie udostępnienia zamyka wydany bilet od razu.
    await app_client.post(
        f"{STAFF}/{training_id}/share", headers=headers(second), json={"share": False}
    )
    assert (await app_client.get(ticket.json()["url"])).status_code == 403


async def test_recording_gives_up_after_the_limit(app_client, graph) -> None:
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    training_id = await _employee_training(app_client, tcm, lecturer)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Training)
            .where(Training.id == training_id)
            .values(
                session_date=business_today() - timedelta(days=5),
                recording_next_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await recordings.fetch_due(db) == {"none": 1}


async def test_only_registered_rate_after_the_date_and_trainer_sees_comments(
    app_client, graph
) -> None:
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    listener = await make_user(UserRole.recruiter, name="Lucyna")
    outsider = await make_user(UserRole.recruiter, name="Oliwia")
    training_id = await _employee_training(app_client, tcm, lecturer)
    await app_client.post(
        f"{STAFF}/library/{training_id}/registration",
        headers=headers(listener),
        json={"join": True},
    )
    early = await app_client.post(
        f"{STAFF}/library/{training_id}/feedback",
        headers=headers(listener),
        json={"rating": 5},
    )
    assert early.status_code == 409
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Training)
            .where(Training.id == training_id)
            .values(session_date=business_today() - timedelta(days=1))
        )
        await db.commit()
    stranger = await app_client.post(
        f"{STAFF}/library/{training_id}/feedback",
        headers=headers(outsider),
        json={"rating": 1},
    )
    assert stranger.status_code == 403
    for rating in (3, 5):
        rated = await app_client.post(
            f"{STAFF}/library/{training_id}/feedback",
            headers=headers(listener),
            json={"rating": rating, "comment": "Konkretnie i z przykładami"},
        )
        assert rated.status_code == 200
    view = (await app_client.get(f"{STAFF}/{training_id}", headers=headers(tcm))).json()
    assert view["training"]["feedback"] == {
        "count": 1,
        "average": 5.0,
        "comments": ["Konkretnie i z przykładami"],
    }


async def test_reminders_go_to_registered_staff_once(app_client, graph) -> None:
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    listener = await make_user(UserRole.recruiter, name="Lucyna")
    tomorrow = business_today() + timedelta(days=1)
    training_id = await _employee_training(
        app_client, tcm, lecturer, session_date=tomorrow.isoformat()
    )
    await app_client.post(
        f"{STAFF}/library/{training_id}/registration",
        headers=headers(listener),
        json={"join": True},
    )
    from zoneinfo import ZoneInfo

    ten = datetime.combine(
        business_today(), datetime.min.time(), tzinfo=ZoneInfo("Europe/Warsaw")
    ).replace(hour=10)
    async with AsyncSessionLocal() as db:
        first = await recordings.send_reminders(db, now=ten.astimezone(timezone.utc))
        second = await recordings.send_reminders(db, now=ten.astimezone(timezone.utc))
    assert first["day"] >= 1 and second["day"] == 0
    assert len(await _notifications(listener.id, NotificationType.training_reminder)) == 1


@pytest.mark.usefixtures("portal_all")
async def test_tcm_signer_and_finance_hear_about_their_step(app_client, monkeypatch) -> None:
    install_mailer(monkeypatch)
    person = await make_person()
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    trainer = await session_headers(app_client, person)
    from tests.test_trainings_flow import QUOTE

    created = await app_client.post(
        STAFF,
        headers=headers(tcm),
        json={**_order(), "trainer_contract_id": person.contract_id},
    )
    training_id = created.json()["training"]["id"]
    await app_client.post(f"{STAFF}/{training_id}/send", headers=headers(tcm))
    quoted = await app_client.put(
        f"{BASE}/trainings/{training_id}/quote", headers=trainer, json=QUOTE
    )
    assert quoted.status_code == 200, quoted.text
    rows = await _notifications(tcm.id, NotificationType.training_quote)
    assert len(rows) == 1 and "zł" not in rows[0].message
