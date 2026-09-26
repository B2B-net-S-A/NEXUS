"""Runda 6 audytu — to, co przeżywało twarde usunięcie kandydata (art. 17 RODO).

Każdy test najpierw zakłada ślad osoby w miejscu, do którego kaskada FK nie
sięga, potem woła ``DELETE /api/candidates/{id}`` i sprawdza, że ślad zniknął:

* RODO-01 — nocny sync Traffita zakładał usuniętą osobę od nowa (także przez
  adopcję po mailu cudzego wiersza);
* RODO-02 — wygenerowane CV (``SET NULL``) zostawało czytelne i do pobrania,
  razem ze zrzutem zgody RODO w magazynie;
* RODO-03 — powiadomienia z imieniem i nazwiskiem zostawały (także typu
  ``candidate_stage`` i z linkiem ``?candidate=``); scalanie przepinało link
  tylko przy typie ``candidate``;
* RODO-06 — nazwisko w dzienniku integracji;
* RODO-07 — worker M365 zakładał osobę od nowa z niesparsowanego CV z maila.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

import app.services.traffit.importer as importer_mod
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


def _payload(consent_key: str | None = None) -> dict:
    payload = {
        "name": "Ewa Usunieta",
        "first_name": "Ewa",
        "position": "Data Engineer",
        "why_points": [],
        "education": [],
        "skills": [],
        "certifications": [],
        "languages": [],
        "experience": [],
        "language": "pl",
        "blind_cv": False,
        "content_mode": "polished",
        "highlight_keywords": [],
    }
    if consent_key:
        payload["consent_screenshot"] = {"storage_key": consent_key}
    return payload


async def _candidate(**fields) -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Ewa",
            lastname=f"Usunieta{suffix}",
            email=fields.pop("email", f"leftover-{suffix}@example.com"),
            **fields,
        )
        db.add(cand)
        await db.commit()
        return cand.id


async def _delete(app_client: AsyncClient, headers: dict, candidate_id: int) -> None:
    resp = await app_client.delete(f"/api/candidates/{candidate_id}", headers=headers)
    assert resp.status_code == 204, resp.text


async def _admin_id(app_client: AsyncClient, headers: dict) -> int:
    me = await app_client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return int(me.json()["id"])


# ── RODO-01: nagrobek dla syncu Traffita ─────────────────────────────────────


class _OneEmployee:
    def __init__(self, ext: str):
        self.ext = ext

    async def total_count(self, path):
        return 1

    async def get_paginated(self, path, *, page_size=100, **kw):
        return
        yield  # pragma: no cover

    async def get_pages(self, path, *, page_size=100, start_page=1, **kw):
        yield 1, [{"id": self.ext}]


async def _sync_employee(ext: str, email: str):
    async with AsyncSessionLocal() as db:
        imp = importer_mod.TraffitImporter(
            _OneEmployee(ext), db, dry_run=False, batch_size=10
        )
        imp.build_user_id_map = AsyncMock(return_value={})
        imp._record_new_candidate_index_intent = AsyncMock(return_value=None)
        original = importer_mod.traffit_employee_to_candidate
        importer_mod.traffit_employee_to_candidate = lambda raw, m: {
            "external_id": str(raw["id"]),
            "external_source": "traffit",
            "name": "Ewa",
            "lastname": "Wraca",
            "traffit_raw_name": "Ewa",
            "traffit_raw_lastname": "Wraca",
            "traffit_source_updated_at": None,
            "email": email,
            "phone": None,
            "linkedin": None,
            "city": None,
            "country": None,
            "location": None,
            "status": "active",
            "profile_about": None,
            "languages": [],
            "cv_filename": None,
            "cv_extracted_data": {},
            "source": "traffit",
            "created_by": None,
        }
        try:
            progress = await imp.import_candidates(since=None)
            await db.commit()
            return progress
        finally:
            importer_mod.traffit_employee_to_candidate = original


async def test_deleted_traffit_candidate_is_not_recreated_by_the_nightly_sync(
    app_client: AsyncClient, app_auth_headers: dict
):
    ext = str(900_000_000 + uuid.uuid4().int % 90_000_000)
    email = f"tomb-{uuid.uuid4().hex[:8]}@example.com"
    candidate_id = await _candidate(
        external_source="traffit", external_id=ext, email=email
    )
    await _delete(app_client, app_auth_headers, candidate_id)

    async with AsyncSessionLocal() as db:
        hashes = (
            (
                await db.execute(
                    text(
                        "SELECT external_id_hash FROM purged_candidates "
                        "WHERE external_source = 'traffit'"
                    )
                )
            )
            .scalars()
            .all()
        )
    from app.services.candidate_audit import candidate_source_tombstone

    assert candidate_source_tombstone("traffit", ext) in hashes
    assert not any(ext in h for h in hashes), "nagrobek nie trzyma surowego id"

    progress = await _sync_employee(ext, email)
    assert progress.skipped == 1
    assert progress.inserted == 0
    async with AsyncSessionLocal() as db:
        recreated = await db.scalar(
            select(Candidate.id).where(
                Candidate.external_source == "traffit",
                Candidate.external_id == ext,
            )
        )
    assert recreated is None, "sync odtworzył usuniętą osobę"


async def test_tombstone_blocks_the_adopt_path_onto_another_row(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Nowy profil z tym samym mailem nie dostaje historii usuniętej osoby."""
    ext = str(910_000_000 + uuid.uuid4().int % 80_000_000)
    email = f"tomb-adopt-{uuid.uuid4().hex[:8]}@example.com"
    deleted_id = await _candidate(
        external_source="traffit", external_id=ext, email=email
    )
    await _delete(app_client, app_auth_headers, deleted_id)
    fresh_id = await _candidate(email=email)

    progress = await _sync_employee(ext, email)
    assert progress.skipped == 1
    async with AsyncSessionLocal() as db:
        fresh = await db.get(Candidate, fresh_id)
    assert fresh.external_id is None
    assert fresh.lastname != "Wraca"


# ── CV zostają (decyzja Artura 26.09.2026: „nie usuwać nigdy żadnych CV”) ──


async def test_generated_cvs_and_consent_screenshot_survive_candidate_deletion(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.models.cv_source_cleanup import CvSourceCleanup

    candidate_id = await _candidate()
    key = f"consent/{uuid.uuid4().hex}.png"
    async with AsyncSessionLocal() as db:
        doc = CvGeneratedDocument(
            candidate_id=candidate_id,
            candidate_name="Ewa Usunieta",
            language="pl",
            blind=False,
            mode="new",
            filename="CV_pl.docx",
            status="ready",
            render_payload=_payload(key),
        )
        db.add(doc)
        await db.commit()
        doc_id = doc.id

    await _delete(app_client, app_auth_headers, candidate_id)

    async with AsyncSessionLocal() as db:
        kept = await db.get(CvGeneratedDocument, doc_id)
        assert kept is not None, "wygenerowane CV nie może zniknąć"
        assert kept.candidate_id is None
        scheduled = (
            await db.scalars(
                select(CvSourceCleanup.storage_key).where(
                    CvSourceCleanup.storage_key == key
                )
            )
        ).all()
    assert scheduled == [], "zrzut zgody przy CV nie trafia do kasowania"


# ── RODO-03: powiadomienia ──────────────────────────────────────────────────


def _unique_entity_id() -> int:
    """Indeks ``ix_notif_dedup_daily`` (użytkownik, typ, id encji, dzień) jest
    wspólny dla całej bazy testowej — stałe id zderzałyby się między testami."""
    return 1_000_000_000 + uuid.uuid4().int % 1_000_000_000


async def test_notifications_about_the_person_are_erased(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.models.client import Client
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage

    admin_id = await _admin_id(app_client, app_auth_headers)
    candidate_id = await _candidate()
    other_id = await _candidate()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"RODO {uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(title="RODO job", client_id=client.id)
        db.add(job)
        await db.flush()
        stage = CandidateStage(candidate_id=candidate_id, job_id=job.id)
        db.add(stage)
        await db.flush()

        def note(**kw) -> Notification:
            return Notification(
                user_id=admin_id,
                title="Kandydat Ewa Usunieta",
                message="Ewa Usunieta",
                notification_type=NotificationType.stage_rule,
                **kw,
            )

        gone = [
            note(related_entity_type="candidate", related_entity_id=candidate_id),
            note(related_entity_type="candidate_stage", related_entity_id=stage.id),
            note(
                related_entity_type="job",
                related_entity_id=_unique_entity_id(),
                link=f"/jobs/{job.id}?candidate={candidate_id}",
            ),
            note(
                related_entity_type="calendar_event",
                related_entity_id=_unique_entity_id(),
                link=f"/candidates/{candidate_id}?tab=activity",
            ),
        ]
        kept = [
            note(related_entity_type="candidate", related_entity_id=other_id),
            note(
                related_entity_type="job",
                related_entity_id=_unique_entity_id(),
                link=f"/candidates/{candidate_id}0",
            ),
        ]
        db.add_all([*gone, *kept])
        await db.commit()
        gone_ids = [n.id for n in gone]
        kept_ids = [n.id for n in kept]

    await _delete(app_client, app_auth_headers, candidate_id)

    async with AsyncSessionLocal() as db:
        for nid in gone_ids:
            assert await db.get(Notification, nid) is None, nid
        for nid in kept_ids:
            assert await db.get(Notification, nid) is not None, nid


async def test_merge_repoints_links_of_non_candidate_notifications(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.services.candidate_merge import _repoint_notification_links

    admin_id = await _admin_id(app_client, app_auth_headers)
    survivor = await _candidate()
    duplicate = await _candidate()
    async with AsyncSessionLocal() as db:
        rows = [
            Notification(
                user_id=admin_id,
                title="x",
                message="x",
                notification_type=NotificationType.stage_rule,
                related_entity_type="candidate_stage",
                related_entity_id=_unique_entity_id(),
                link=link,
            )
            for link in (
                f"/candidates/{duplicate}",
                f"/jobs/1?candidate={duplicate}&panel=cv",
            )
        ]
        db.add_all(rows)
        await db.commit()
        ids = [r.id for r in rows]
    async with AsyncSessionLocal() as db:
        touched = await _repoint_notification_links(
            db, survivor_id=survivor, duplicate_id=duplicate
        )
        await db.commit()
    assert touched == 2
    async with AsyncSessionLocal() as db:
        links = [(await db.get(Notification, nid)).link for nid in ids]
    assert links == [
        f"/candidates/{survivor}",
        f"/jobs/1?candidate={survivor}&panel=cv",
    ]


# ── RODO-06 i RODO-07 ───────────────────────────────────────────────────────


async def test_integration_log_and_email_cv_attachments_are_closed(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.models.integration_run import IntegrationRun, IntegrationRunEvent
    from app.models.m365 import Email, EmailAttachment, EmailDirection

    candidate_id = await _candidate()
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"leftover-mail-{suffix}@example.com",
            password_hash=hash_password("P@ss"),
            name="Mail",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        run = IntegrationRun(source="jjit")
        db.add(run)
        await db.flush()
        event = IntegrationRunEvent(
            run_id=run.id,
            source="jjit",
            external_id=f"app-{suffix}",
            candidate_id=candidate_id,
            traffit_id=4242,
            action="created",
            candidate_name="Ewa Usunieta",
        )
        email = Email(
            user_id=user.id,
            candidate_id=candidate_id,
            m365_message_id=f"msg-{suffix}",
            m365_conversation_id="c",
            from_address="ewa@example.com",
            received_at=datetime.now(timezone.utc),
            direction=EmailDirection.received,
            has_attachments=True,
        )
        db.add_all([event, email])
        await db.flush()
        attachment = EmailAttachment(
            email_id=email.id,
            m365_attachment_id=f"att-{suffix}",
            filename="Ewa_CV.pdf",
            content_type="application/pdf",
            size_bytes=3,
            is_cv_candidate=True,
        )
        db.add(attachment)
        await db.commit()
        event_id, attachment_id = event.id, attachment.id

    await _delete(app_client, app_auth_headers, candidate_id)

    async with AsyncSessionLocal() as db:
        event = await db.get(IntegrationRunEvent, event_id)
        attachment = await db.get(EmailAttachment, attachment_id)
    assert event.candidate_name is None
    assert event.traffit_id is None
    assert event.external_id == f"app-{suffix}"  # licznik biegu zostaje
    assert attachment.cv_parse_attempted_at is not None
