"""Notatki: przypięcie, odpowiedzi, notatki systemowe (0399, decyzje 29.09.2026).

* przypięcie wspólne dla zespołu — bramka jak przy dodaniu notatki
  (viewer `user` dostaje 403), przypięte pierwsze na liście,
* odpowiedź na notatkę: jeden poziom (odpowiedź na odpowiedź = 422),
  dziedziczy kandydata i rekrutację notatki głównej, autor notatki głównej
  dostaje powiadomienie `note_reply`, lista nie liczy odpowiedzi jako notatek,
* oś czasu nie dubluje promowanych aktywności Traffita,
* wpis automatu (`external_source='system'`) ma `is_system`,
* lustro SQL migracji w `entrypoint.sh`.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.note import SYSTEM_NOTE_SOURCE, Note
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import note_threads_schema
from app.services.process_entry_meta import auto_match_badge, auto_match_entry_meta

_BACKEND = Path(__file__).resolve().parents[1]


# ── bez bazy ─────────────────────────────────────────────────────────────────


def test_entrypoint_mirrors_the_migration_sql():
    entrypoint = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    for stmt in (
        *note_threads_schema.ENUM_DDL,
        *note_threads_schema.COLUMN_DDL,
        note_threads_schema.SYSTEM_NOTES_BACKFILL,
    ):
        assert stmt in entrypoint, stmt


def test_system_backfill_matches_both_automat_patterns_and_is_one_off():
    sql = note_threads_schema.SYSTEM_NOTES_BACKFILL
    assert "'%Auto-match score:%'" in sql  # scraper JJIT/RocketJobs
    assert "'Auto-match %'" in sql and "kandydat dodany automatycznie" in sql
    assert "external_source IS NULL" in sql  # nie nadpisuje traffit/trainee_call
    assert note_threads_schema.SYSTEM_NOTES_MARKER in sql
    assert "DELETE" not in sql.upper()


def test_auto_match_badge_reads_only_known_fields():
    meta = auto_match_entry_meta(
        score=66.6, source="jjit", must_hit=["Java"] * 20, must_total=3
    )
    assert meta["score"] == 67
    assert len(meta["must_hit"]) == 8
    assert auto_match_badge(meta) == {
        "score": 67,
        "source": "jjit",
        "must_hit": ["Java"] * 8,
        "must_total": 3,
    }
    assert auto_match_badge(None) is None
    assert auto_match_badge({"kind": "other", "score": 5}) is None
    assert auto_match_badge({"kind": "auto_match", "score": "x"}) is None


@pytest.mark.asyncio
async def test_jjit_client_sends_structured_match_instead_of_a_note():
    from app.services.integrations.jjit.nexus_client import NexusLoopbackClient

    sent: dict = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"added": [7], "skipped": []}

    client = NexusLoopbackClient.__new__(NexusLoopbackClient)

    async def fake_request(method, path, **kwargs):
        sent.update(kwargs.get("json") or {})
        return _Resp()

    client._request = fake_request  # type: ignore[method-assign]
    added, _ = await client.add_to_job(
        3,
        7,
        {"score": 67.4, "matching_must": ["Java", "Spring"], "gap_must": ["K8s"]},
    )
    assert added is True
    assert "note" not in sent
    assert sent["auto_match"] == {
        "score": 67.4,
        "source": "jjit",
        "must_hit": ["Java", "Spring"],
        "must_total": 3,
    }


# ── z bazą ───────────────────────────────────────────────────────────────────


async def _seed_user(role: UserRole) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"pin-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Pin"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Pin {role.value} {unique}",
            role=role,
            roles=[role.value],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id, email, password


async def _seed_candidate() -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        c = Candidate(name=f"Cand{unique}", lastname="Pin", email=f"{unique}@x.com")
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job() -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"PinClient-{unique}")
        db.add(cli)
        await db.flush()
        job = Job(title=f"Rola {unique}", status=JobStatus.published, client_id=cli.id)
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _note(client, headers, **body) -> dict:
    resp = await client.post("/api/notes", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_pin_puts_note_first_and_viewer_cannot_pin(app_client: AsyncClient):
    cand_id = await _seed_candidate()
    _, r_email, r_pass = await _seed_user(UserRole.recruiter)
    recruiter = await _login(app_client, r_email, r_pass)
    older = await _note(app_client, recruiter, content="starsza", candidate_id=cand_id)
    await _note(app_client, recruiter, content="nowsza", candidate_id=cand_id)

    _, v_email, v_pass = await _seed_user(UserRole.user)
    viewer = await _login(app_client, v_email, v_pass)
    denied = await app_client.post(f"/api/notes/{older['id']}/pin", headers=viewer)
    assert denied.status_code == 403

    pinned = await app_client.post(f"/api/notes/{older['id']}/pin", headers=recruiter)
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["pinned_at"] is not None
    # Idempotentne.
    again = await app_client.post(f"/api/notes/{older['id']}/pin", headers=recruiter)
    assert again.status_code == 200

    listed = await app_client.get(
        "/api/notes", params={"candidate_id": cand_id}, headers=recruiter
    )
    items = listed.json()["items"]
    assert [i["content"] for i in items] == ["starsza", "nowsza"]
    assert items[0]["pinned_by_name"].startswith("Pin recruiter")

    only_pinned = await app_client.get(
        "/api/notes",
        params={"candidate_id": cand_id, "pinned_only": "true"},
        headers=recruiter,
    )
    assert [i["id"] for i in only_pinned.json()["items"]] == [older["id"]]

    # Przypięcie wspólne — odpina ktoś inny z prawem zapisu.
    _, o_email, o_pass = await _seed_user(UserRole.recruiter)
    other = await _login(app_client, o_email, o_pass)
    unpinned = await app_client.delete(f"/api/notes/{older['id']}/pin", headers=other)
    assert unpinned.status_code == 200
    assert unpinned.json()["pinned_at"] is None

    async with AsyncSessionLocal() as db:
        from app.models.activity import Activity

        actions = (
            await db.scalars(
                select(Activity.action).where(
                    Activity.entity_type == "note",
                    Activity.entity_id == older["id"],
                )
            )
        ).all()
    assert sorted(actions) == ["note_pinned", "note_unpinned"]


@pytest.mark.asyncio
async def test_reply_inherits_thread_notifies_author_and_is_one_level(
    app_client: AsyncClient,
):
    cand_id = await _seed_candidate()
    job_id = await _seed_job()
    other_cand = await _seed_candidate()
    author_id, a_email, a_pass = await _seed_user(UserRole.recruiter)
    author = await _login(app_client, a_email, a_pass)
    _, r_email, r_pass = await _seed_user(UserRole.recruiter)
    replier = await _login(app_client, r_email, r_pass)

    parent = await _note(
        app_client,
        author,
        content="Kandydat pyta o zdalną",
        candidate_id=cand_id,
        job_id=job_id,
    )
    reply = await _note(
        app_client,
        replier,
        content="Klient zgadza się na 2 dni w biurze",
        parent_note_id=parent["id"],
        # Klient nie przepnie odpowiedzi do innego kandydata ani rekrutacji.
        candidate_id=other_cand,
    )
    assert reply["parent_note_id"] == parent["id"]
    assert reply["candidate_id"] == cand_id
    assert reply["job_id"] == job_id

    nested = await app_client.post(
        "/api/notes",
        headers=author,
        json={"content": "odpowiedź na odpowiedź", "parent_note_id": reply["id"]},
    )
    assert nested.status_code == 422
    assert "odpowiedź" in nested.json()["detail"]

    pin_reply = await app_client.post(f"/api/notes/{reply['id']}/pin", headers=author)
    assert pin_reply.status_code == 422

    listed = await app_client.get(
        "/api/notes", params={"candidate_id": cand_id}, headers=author
    )
    body = listed.json()
    assert body["total"] == 1
    assert [i["id"] for i in body["items"]] == [parent["id"]]
    assert [r["id"] for r in body["items"][0]["replies"]] == [reply["id"]]
    assert body["items"][0]["replies"][0]["replies"] == []

    async with AsyncSessionLocal() as db:
        notes = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == author_id,
                    Notification.notification_type == NotificationType.note_reply,
                )
            )
        ).all()
        candidate = await db.get(Candidate, cand_id)
    assert len(notes) == 1
    assert f"note={parent['id']}" in (notes[0].link or "")
    # Odpowiedź nie jest osobną notatką w liczniku kandydata.
    assert candidate.notes_count == 1

    # Usunięcie notatki głównej zabiera odpowiedzi (CASCADE).
    deleted = await app_client.delete(f"/api/notes/{parent['id']}", headers=author)
    assert deleted.status_code == 204
    async with AsyncSessionLocal() as db:
        assert await db.get(Note, reply["id"]) is None


@pytest.mark.asyncio
async def test_reply_author_edits_own_reply_only(app_client: AsyncClient):
    cand_id = await _seed_candidate()
    _, a_email, a_pass = await _seed_user(UserRole.recruiter)
    author = await _login(app_client, a_email, a_pass)
    _, r_email, r_pass = await _seed_user(UserRole.recruiter)
    replier = await _login(app_client, r_email, r_pass)
    parent = await _note(app_client, author, content="główna", candidate_id=cand_id)
    reply = await _note(app_client, replier, content="odp", parent_note_id=parent["id"])
    forbidden = await app_client.patch(
        f"/api/notes/{reply['id']}", headers=author, json={"content": "zmiana"}
    )
    assert forbidden.status_code == 403
    ok = await app_client.patch(
        f"/api/notes/{reply['id']}", headers=replier, json={"content": "zmiana"}
    )
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_system_note_is_flagged_and_timeline_hides_traffit_duplicates(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.models.activity import Activity

    cand_id = await _seed_candidate()
    async with AsyncSessionLocal() as db:
        system = Note(
            content="Auto-match 70/100 — kandydat dodany automatycznie po odczycie CV.",
            candidate_id=cand_id,
            external_source=SYSTEM_NOTE_SOURCE,
        )
        human = Note(content="Rozmowa: szuka B2B", candidate_id=cand_id)
        db.add_all([system, human])
        for action in (
            "traffit:Email",
            "traffit:Reply",
            "traffit:Rozmowa telefoniczna",
            "traffit:Spotkanie",
            "traffit:Tag-dodany",
        ):
            db.add(
                Activity(
                    entity_type="candidate",
                    entity_id=cand_id,
                    action=action,
                    details={"content": action},
                )
            )
        await db.commit()
        await db.refresh(system)
        await db.refresh(human)

    listed = await app_client.get(
        "/api/notes", params={"candidate_id": cand_id}, headers=app_auth_headers
    )
    flags = {i["id"]: i["is_system"] for i in listed.json()["items"]}
    assert flags == {system.id: True, human.id: False}

    reply = await _note(
        app_client, app_auth_headers, content="dopisek", parent_note_id=human.id
    )
    timeline = await app_client.get(
        f"/api/candidates/{cand_id}/timeline", headers=app_auth_headers
    )
    assert timeline.status_code == 200, timeline.text
    items = timeline.json()["timeline"]
    actions = {i.get("action") for i in items if i.get("type") == "activity"}
    assert not actions & {
        "traffit:Email",
        "traffit:Reply",
        "traffit:Rozmowa telefoniczna",
        "traffit:Spotkanie",
    }
    assert "traffit:Tag-dodany" in actions
    note_ids = [i["id"] for i in items if i.get("type") == "note"]
    assert reply["id"] not in note_ids
    human_item = next(
        i for i in items if i.get("type") == "note" and i["id"] == human.id
    )
    assert [r["id"] for r in human_item["replies"]] == [reply["id"]]


# ── Przegląd PR #1911: odpowiedź nie wchodzi do kontraktu, dzwonek sprzątany ──


async def _seed_contract_note() -> dict:
    from datetime import timedelta

    from app.core.scheduling import business_today
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, ContractType

    token = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(name="Kontrakt", lastname=f"Notatka-{token}")
        client = Client(name=f"PinContract {token}")
        db.add_all([cand, client])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            contract_type=ContractType("b2b"),
            start_date=business_today() - timedelta(days=30),
            rate_client=100,
            rate_candidate=80,
            currency="PLN",
        )
        db.add(contract)
        await db.flush()
        note = Note(
            content="Notatka Delivery o przedłużeniu",
            candidate_id=cand.id,
            contract_id=contract.id,
        )
        db.add(note)
        await db.commit()
        return {
            "contract_id": contract.id,
            "candidate_id": cand.id,
            "note_id": note.id,
        }


@pytest.mark.asyncio
async def test_reply_to_contract_note_never_lands_in_the_contract_timeline(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Notatka kontraktu (DL + zakres klienta) ma kandydata, więc jest
    w „Historia → Notatki” z „Odpowiedz”. Odpowiedź rekrutera (sam zapis
    kandydata) nie może trafić na oś kontraktu — to omijałoby bramkę F03."""
    seeded = await _seed_contract_note()
    _, r_email, r_pass = await _seed_user(UserRole.recruiter)
    recruiter = await _login(app_client, r_email, r_pass)

    reply = await _note(
        app_client,
        recruiter,
        content="Dopisek rekrutera",
        parent_note_id=seeded["note_id"],
    )
    assert reply["candidate_id"] == seeded["candidate_id"]
    async with AsyncSessionLocal() as db:
        stored = await db.get(Note, reply["id"])
        assert stored.contract_id is None

    timeline = await app_client.get(
        f"/api/contracts/{seeded['contract_id']}/notes", headers=app_auth_headers
    )
    assert timeline.status_code == 200, timeline.text
    ids = [i["id"] for i in timeline.json() if i["kind"] == "note"]
    assert ids == [seeded["note_id"]]

    # Obrona w głąb: odpowiedź z kontraktem zapisana wprost też nie trafia
    # na oś kontraktu.
    async with AsyncSessionLocal() as db:
        db.add(
            Note(
                content="stara odpowiedź",
                candidate_id=seeded["candidate_id"],
                contract_id=seeded["contract_id"],
                parent_note_id=seeded["note_id"],
            )
        )
        await db.commit()
    again = await app_client.get(
        f"/api/contracts/{seeded['contract_id']}/notes", headers=app_auth_headers
    )
    assert [i["id"] for i in again.json() if i["kind"] == "note"] == [seeded["note_id"]]


@pytest.mark.asyncio
async def test_deleting_a_reply_retracts_its_bell_entry(app_client: AsyncClient):
    from app.services.mention_dispatch import NOTE_DELETED_PLACEHOLDER

    cand_id = await _seed_candidate()
    author_id, a_email, a_pass = await _seed_user(UserRole.recruiter)
    author = await _login(app_client, a_email, a_pass)
    _, r_email, r_pass = await _seed_user(UserRole.recruiter)
    replier = await _login(app_client, r_email, r_pass)
    parent = await _note(app_client, author, content="główna", candidate_id=cand_id)
    first = await _note(
        app_client, replier, content="pierwsza odpowiedź", parent_note_id=parent["id"]
    )
    second = await _note(
        app_client, replier, content="druga odpowiedź", parent_note_id=parent["id"]
    )

    async def bell(note_id: int) -> Notification:
        async with AsyncSessionLocal() as db:
            return await db.scalar(
                select(Notification).where(
                    Notification.user_id == author_id,
                    Notification.notification_type == NotificationType.note_reply,
                    Notification.related_entity_id == note_id,
                )
            )

    assert (await bell(first["id"])).message == "pierwsza odpowiedź"
    deleted = await app_client.delete(f"/api/notes/{first['id']}", headers=replier)
    assert deleted.status_code == 204
    gone = await bell(first["id"])
    assert gone.message == NOTE_DELETED_PLACEHOLDER
    assert gone.is_read is True

    # Usunięcie notatki głównej zabiera odpowiedzi (CASCADE) — ich dzwonki też.
    removed = await app_client.delete(f"/api/notes/{parent['id']}", headers=author)
    assert removed.status_code == 204
    assert (await bell(second["id"])).message == NOTE_DELETED_PLACEHOLDER
