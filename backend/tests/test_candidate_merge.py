"""Scalanie duplikatów kandydatów (PR2) — testy na żywej bazie.

Pokrywa:

- konflikt unikalności rozstrzygany PER WIERSZ (``my_people_overrides``:
  para, która się zderza, zostawia nowszy wpis; wpis bez kolizji jest
  przepinany — nigdy „usuń wszystkie wiersze duplikatu”);
- FK o innej nazwie kolumny (``application_submissions.matched_candidate_id``);
- referencje polimorficzne (``activities``, ``notifications`` z linkiem);
- wybór pól przy konflikcie + kontakt duplikatu zachowany w ``custom_fields``;
- tożsamość z Traffita przechodzi na ocalałego; oba z Traffita = 409;
- odcisk: rozjazd = 409; ten sam kandydat = 422; rekruter = 403;
- Historia zdarzeń bez imion i nazwisk.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.application_submission import ApplicationSubmission
from app.models.candidate import Candidate
from app.models.critical_event import CriticalEvent
from app.models.my_people import MyPeopleOverride
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


async def _user(app_client: AsyncClient, role: UserRole) -> tuple[int, dict]:
    unique = uuid.uuid4().hex[:8]
    email = f"merge-{role.value}-{unique}@example.com"
    password = f"P4ss_{unique}!X"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Merge {role.value}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        user_id = user.id
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return user_id, {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _candidate(**fields) -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=fields.pop("name", "Jan"),
            lastname=fields.pop("lastname", f"Scalany{suffix}"),
            email=fields.pop("email", f"merge-{suffix}@example.com"),
            **fields,
        )
        db.add(cand)
        await db.commit()
        return cand.id


async def _preview(api, headers, survivor: int, other: int):
    return await api.get(
        f"/api/candidates/{survivor}/merge-preview",
        params={"other": other},
        headers=headers,
    )


async def _merge(api, headers, survivor: int, other: int, fp: str, choices=None):
    return await api.post(
        f"/api/candidates/{survivor}/merge",
        json={"other": other, "fingerprint": fp, "choices": choices},
        headers=headers,
    )


async def test_merge_moves_rows_resolving_unique_conflicts_per_row(
    app_client: AsyncClient,
):
    admin_id, headers = await _user(app_client, UserRole.admin)
    other_id, _ = await _user(app_client, UserRole.recruiter)
    survivor = await _candidate(phone="+48 600 100 200")
    duplicate = await _candidate(phone="+48 600 999 999", tags=["kafka"])
    older = datetime.now(timezone.utc) - timedelta(days=5)
    async with AsyncSessionLocal() as db:
        # Kolizja: ten sam użytkownik przypiął OBU — zostaje nowszy wpis
        # (duplikatu), starszy (ocalałego) znika.
        db.add(
            MyPeopleOverride(
                user_id=admin_id, candidate_id=survivor, kind="pinned", created_at=older
            )
        )
        db.add(
            MyPeopleOverride(user_id=admin_id, candidate_id=duplicate, kind="pinned")
        )
        # Bez kolizji: przypięcie innej osoby po prostu przechodzi.
        db.add(
            MyPeopleOverride(user_id=other_id, candidate_id=duplicate, kind="pinned")
        )
        submission = ApplicationSubmission(
            submitted_first_name="Jan",
            submitted_last_name="Scalany",
            submitted_email="jan@example.com",
            matched_candidate_id=duplicate,
            status="linked",
        )
        db.add(submission)
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=duplicate,
                action="note_added",
                user_id=admin_id,
                details={},
            )
        )
        db.add(
            Notification(
                user_id=admin_id,
                title="Nowe zgłoszenie",
                message="x",
                notification_type=NotificationType.new_application,
                related_entity_type="candidate",
                related_entity_id=duplicate,
                link=f"/candidates/{duplicate}",
            )
        )
        await db.commit()
        submission_id = submission.id

    preview = await _preview(app_client, headers, survivor, duplicate)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["can_apply"] is True
    refs = {(r["table"], r["column"]): r for r in plan["references"]}
    assert refs[("my_people_overrides", "candidate_id")]["rows"] == 2
    assert refs[("my_people_overrides", "candidate_id")]["conflicts"] == 1
    assert refs[("application_submissions", "matched_candidate_id")]["rows"] == 1
    phone = next(f for f in plan["fields"] if f["field"] == "phone")
    assert phone["conflict"] is True

    merged = await _merge(
        app_client,
        headers,
        survivor,
        duplicate,
        plan["fingerprint"],
        choices={"phone": "duplicate"},
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["replaced_rows"] == 1

    async with AsyncSessionLocal() as db:
        assert await db.get(Candidate, duplicate) is None
        kept = await db.get(Candidate, survivor)
        assert kept.phone == "+48 600 999 999"
        assert "kafka" in kept.tags
        merged_contacts = kept.custom_fields["merged_duplicates"]
        assert merged_contacts[-1]["candidate_id"] == duplicate
        pins = (
            await db.scalars(
                select(MyPeopleOverride).where(
                    MyPeopleOverride.candidate_id == survivor
                )
            )
        ).all()
        assert sorted(p.user_id for p in pins) == sorted([admin_id, other_id])
        admin_pin = next(p for p in pins if p.user_id == admin_id)
        assert admin_pin.created_at > older  # nowszy (z duplikatu) wygrał
        sub = await db.get(ApplicationSubmission, submission_id)
        assert sub.matched_candidate_id == survivor
        moved_activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == survivor,
                Activity.action == "note_added",
            )
        )
        assert moved_activity is not None
        note = await db.scalar(
            select(Notification).where(
                Notification.related_entity_type == "candidate",
                Notification.related_entity_id == survivor,
                Notification.user_id == admin_id,
            )
        )
        assert note is not None and note.link == f"/candidates/{survivor}"
        event = await db.scalar(
            select(CriticalEvent).where(
                CriticalEvent.event_type == "candidate.merge",
                CriticalEvent.entity_id == survivor,
            )
        )
        assert event is not None and event.outcome == "executed"
        assert "Scalany" not in (event.reason or "") + (event.entity_label or "")


async def test_traffit_identity_moves_to_survivor(app_client: AsyncClient):
    _, headers = await _user(app_client, UserRole.head_of_recruitment)
    ext = f"tt-{uuid.uuid4().hex[:8]}"
    survivor = await _candidate()
    duplicate = await _candidate(external_source="traffit", external_id=ext)

    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    resp = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        kept = await db.get(Candidate, survivor)
        assert (kept.external_source, kept.external_id) == ("traffit", ext)


async def test_both_from_traffit_is_blocked(app_client: AsyncClient):
    _, headers = await _user(app_client, UserRole.admin)
    survivor = await _candidate(
        external_source="traffit", external_id=f"tt-{uuid.uuid4().hex[:8]}"
    )
    duplicate = await _candidate(
        external_source="traffit", external_id=f"tt-{uuid.uuid4().hex[:8]}"
    )
    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    assert plan["can_apply"] is False
    assert [b["code"] for b in plan["blockers"]] == ["both_external"]

    resp = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "merge_blocked"
    async with AsyncSessionLocal() as db:
        assert await db.get(Candidate, duplicate) is not None


async def test_stale_fingerprint_is_409_and_keeps_both(app_client: AsyncClient):
    _, headers = await _user(app_client, UserRole.admin)
    survivor = await _candidate()
    duplicate = await _candidate()
    plan = (await _preview(app_client, headers, survivor, duplicate)).json()
    async with AsyncSessionLocal() as db:
        dup = await db.get(Candidate, duplicate)
        dup.city = "Gdańsk"
        await db.commit()

    resp = await _merge(app_client, headers, survivor, duplicate, plan["fingerprint"])
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "fingerprint_mismatch"
    async with AsyncSessionLocal() as db:
        assert await db.get(Candidate, duplicate) is not None


async def test_refusals(app_client: AsyncClient):
    _, admin = await _user(app_client, UserRole.admin)
    _, recruiter = await _user(app_client, UserRole.recruiter)
    survivor = await _candidate()
    duplicate = await _candidate()

    same = await _preview(app_client, admin, survivor, survivor)
    assert same.status_code == 422
    missing = await _preview(app_client, admin, survivor, 999_999_999)
    assert missing.status_code == 404
    forbidden = await _preview(app_client, recruiter, survivor, duplicate)
    assert forbidden.status_code == 403
    forbidden = await _merge(app_client, recruiter, survivor, duplicate, "0" * 64)
    assert forbidden.status_code == 403
