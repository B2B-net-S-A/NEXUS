"""DL rekrutacji wpisany automatycznie (0376, audyt 24.09.2026).

- lustro migracji w ``entrypoint.sh`` (prod alembic bywa osierocony);
- DL wpisany przez automat idzie za zmianą głównego DL-a klienta, DL wpisany
  ręcznie zostaje; ręczna zmiana w rekrutacji zeruje znacznik;
- nieaktywny DL rekrutacji = jak brak DL-a: przegląd DL wraca do portfela
  klienta, a alert DL-owy eskaluje do HoR (zamiast przepadać).
"""

from __future__ import annotations

import importlib.util
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0376_job_delivery_lead_auto_filled.py"
needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _migration():
    spec = importlib.util.spec_from_file_location("m0376", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_chains_after_md_import_overflow_and_is_mirrored() -> None:
    module = _migration()
    assert module.revision == "0376_job_delivery_lead_auto_filled"
    assert module.down_revision == "0375_md_import_row_overflow"
    raw = (BACKEND / "entrypoint.sh").read_text()
    entrypoint = _collapse(re.sub(r'"\s*\n\s*"', "", raw))
    assert _collapse(module.ADD_COLUMN) in entrypoint
    assert _collapse(module.BACKFILL) in entrypoint
    assert "IF NOT EXISTS" in module.ADD_COLUMN


@pytest.mark.asyncio
async def test_inactive_delivery_lead_escalates_alert_to_head_of_recruitment() -> None:
    from app.services import notification_triggers as nt

    class _Db:
        def __init__(self, active: bool):
            self.active = active

        async def scalar(self, _stmt):
            return self.active

        async def execute(self, _stmt):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [91]))

    job = SimpleNamespace(delivery_lead_id=7)
    assert await nt._delivery_lead_targets(_Db(True), job) == [7]
    assert await nt._delivery_lead_targets(_Db(False), job) == [91]


async def _dl(active: bool = True, role: str = "delivery_lead") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        marker = uuid.uuid4().hex[:10]
        user = User(
            email=f"dlaf-{marker}@example.com",
            name=f"DL {marker}",
            role=UserRole(role),
            roles=[role],
            is_active=active,
        )
        db.add(user)
        await db.commit()
        return user.id


@needs_db
@pytest.mark.asyncio
async def test_auto_filled_dl_follows_head_change_manual_dl_stays() -> None:
    from sqlalchemy import update

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.services.job_delivery_lead_fill import fill_missing_job_delivery_leads

    old_head, new_head, manual = await _dl(), await _dl(), await _dl()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"dlaf-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        head_row = DeliveryLeadClientAssignment(
            delivery_lead_user_id=old_head, client_id=client.id, is_head=True
        )
        db.add(head_row)
        empty = Job(title="Pusta", client_id=client.id, status=JobStatus.published)
        chosen = Job(
            title="Wybrana",
            client_id=client.id,
            status=JobStatus.published,
            delivery_lead_id=manual,
        )
        db.add_all([empty, chosen])
        await db.commit()
        client_id, head_id = client.id, head_row.id
        empty_id, chosen_id = empty.id, chosen.id

    async with AsyncSessionLocal() as db:
        assert await fill_missing_job_delivery_leads(db, [client_id]) == 1
        await db.commit()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, empty_id)
        assert (job.delivery_lead_id, job.delivery_lead_auto_filled) == (
            old_head,
            True,
        )

    # Główny DL klienta się zmienia — DL wpisany automatycznie idzie za nim,
    # wybrany ręcznie zostaje.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(DeliveryLeadClientAssignment)
            .where(DeliveryLeadClientAssignment.id == head_id)
            .values(is_head=False)
        )
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=new_head, client_id=client_id, is_head=True
            )
        )
        await db.flush()
        assert await fill_missing_job_delivery_leads(db, [client_id]) == 1
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, empty_id)).delivery_lead_id == new_head
        chosen_job = await db.get(Job, chosen_id)
        assert chosen_job.delivery_lead_id == manual
        assert chosen_job.delivery_lead_auto_filled is False


@needs_db
@pytest.mark.asyncio
async def test_manual_patch_of_dl_clears_the_auto_flag(
    app_client, app_auth_headers
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    auto_dl, picked = await _dl(), await _dl()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"dlaf-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        job = Job(
            title="Auto DL",
            client_id=client.id,
            status=JobStatus.published,
            delivery_lead_id=auto_dl,
            delivery_lead_auto_filled=True,
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    # Ten sam DL odesłany przez formularz nie jest ręczną zmianą.
    same = await app_client.patch(
        f"/api/jobs/{job_id}",
        json={"delivery_lead_id": auto_dl},
        headers=app_auth_headers,
    )
    assert same.status_code == 200, same.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).delivery_lead_auto_filled is True

    changed = await app_client.patch(
        f"/api/jobs/{job_id}",
        json={"delivery_lead_id": picked},
        headers=app_auth_headers,
    )
    assert changed.status_code == 200, changed.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert (job.delivery_lead_id, job.delivery_lead_auto_filled) == (
            picked,
            False,
        )


@needs_db
@pytest.mark.asyncio
async def test_board_task_of_inactive_dl_falls_back_to_the_portfolio(
    monkeypatch,
) -> None:
    from sqlalchemy import update

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage
    from app.models.user import User
    from app.services import board_tasks as svc
    from tests.test_board_tasks import _cleanup, _seed_world

    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    world = await _seed_world()
    gone = await _dl()
    try:
        async with AsyncSessionLocal() as db:
            (await db.get(Job, world["job_id"])).delivery_lead_id = gone
            db.add(
                CandidateStage(
                    candidate_id=world["candidate_id"],
                    job_id=world["job_id"],
                    stage="interview",
                    stage_def_id=world["defs"]["qc"],
                    moved_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        async def task_dl() -> object:
            async with AsyncSessionLocal() as db:
                snapshot = await svc.load_snapshot(db)
            tasks = [
                t
                for t in snapshot.tasks
                if t.kind == svc.KIND_DL_REVIEW
                and t.candidate_id == world["candidate_id"]
            ]
            assert len(tasks) == 1
            return tasks[0].delivery_lead_id

        assert await task_dl() == gone
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(User).where(User.id == gone).values(is_active=False)
            )
            await db.commit()
        assert await task_dl() is None
    finally:
        await _cleanup(world, [gone])


async def _client_with_head(head_id: int) -> tuple[int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.team_structure import DeliveryLeadClientAssignment

    async with AsyncSessionLocal() as db:
        client = Client(name=f"dlaf-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        row = DeliveryLeadClientAssignment(
            delivery_lead_user_id=head_id, client_id=client.id, is_head=True
        )
        db.add(row)
        await db.commit()
        return client.id, row.id


async def _open_job(client_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        job = Job(title="Bez DL", client_id=client_id, status=JobStatus.published)
        db.add(job)
        await db.commit()
        return job.id


@needs_db
@pytest.mark.asyncio
async def test_head_without_delivery_lead_role_is_not_filled_in() -> None:
    """Runda 7 (N7-1): wpis w tabeli przypisań nie jest grantem roli.

    Główny DL, który dostał rolę rekrutera, zostawał DL-em rekrutacji klienta,
    a przeglądu DL nie widział wtedy nikt (`_sees_dl_review` wymaga roli).
    """
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.job_delivery_lead_fill import fill_missing_job_delivery_leads

    former_dl = await _dl(role="recruiter")
    client_id, _ = await _client_with_head(former_dl)
    job_id = await _open_job(client_id)

    async with AsyncSessionLocal() as db:
        assert await fill_missing_job_delivery_leads(db, [client_id]) == 0
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).delivery_lead_id is None


@needs_db
@pytest.mark.asyncio
async def test_auto_filled_dl_leaves_when_the_head_is_removed() -> None:
    """Runda 7 (N7-2): klient bez głównego DL-a — automatyczny DL schodzi."""
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.services.job_delivery_lead_fill import fill_missing_job_delivery_leads

    head = await _dl()
    client_id, head_row = await _client_with_head(head)
    job_id = await _open_job(client_id)
    async with AsyncSessionLocal() as db:
        await fill_missing_job_delivery_leads(db, [client_id])
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).delivery_lead_id == head

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(DeliveryLeadClientAssignment).where(
                DeliveryLeadClientAssignment.id == head_row
            )
        )
        await db.flush()
        await fill_missing_job_delivery_leads(db, [client_id])
        await db.commit()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert (job.delivery_lead_id, job.delivery_lead_auto_filled) == (None, False)


@needs_db
@pytest.mark.asyncio
async def test_client_change_moves_the_auto_filled_dl_to_the_new_client(
    app_client, app_auth_headers
) -> None:
    """Runda 7 (N7-2): po zmianie klienta nie zostaje DL poprzedniego klienta."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job
    from app.services.job_delivery_lead_fill import fill_missing_job_delivery_leads

    old_head, new_head = await _dl(), await _dl()
    old_client, _ = await _client_with_head(old_head)
    new_client, _ = await _client_with_head(new_head)
    async with AsyncSessionLocal() as db:
        headless = Client(name=f"dlaf-{uuid.uuid4().hex[:8]}")
        db.add(headless)
        await db.commit()
        headless_id = headless.id
    job_id = await _open_job(old_client)
    async with AsyncSessionLocal() as db:
        await fill_missing_job_delivery_leads(db, [old_client])
        await db.commit()

    moved = await app_client.patch(
        f"/api/jobs/{job_id}", json={"client_id": new_client}, headers=app_auth_headers
    )
    assert moved.status_code == 200, moved.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert (job.delivery_lead_id, job.delivery_lead_auto_filled) == (
            new_head,
            True,
        )

    moved = await app_client.patch(
        f"/api/jobs/{job_id}", json={"client_id": headless_id}, headers=app_auth_headers
    )
    assert moved.status_code == 200, moved.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).delivery_lead_id is None


# ── Jednorazowa korekta: rekrutacja założona przez DL-a wraca do niego ──────


async def _job_created_by(
    client_id: int,
    *,
    creator_id: int,
    dl_id: int,
    auto_filled: bool = True,
    status: str = "published",
    external_source: str = "manual",
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        job = Job(
            title="Korekta DL",
            client_id=client_id,
            status=JobStatus(status),
            created_by=creator_id,
            delivery_lead_id=dl_id,
            delivery_lead_auto_filled=auto_filled,
            external_source=external_source,
        )
        db.add(job)
        await db.commit()
        return job.id


@needs_db
@pytest.mark.asyncio
async def test_repair_returns_the_job_to_the_delivery_lead_who_created_it() -> None:
    """Zgłoszenie 08.10.2026: DL założył rekrutację, a automat wpisał głównego
    DL-a klienta. Korekta rusza tylko taki przypadek."""
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.job_creator_delivery_lead_repair import reassign_to_creators

    head, creator, recruiter = await _dl(), await _dl(), await _dl(role="recruiter")
    former_dl = await _dl(active=False)
    client_id, _ = await _client_with_head(head)
    by_dl = await _job_created_by(client_id, creator_id=creator, dl_id=head)
    untouched = {
        "ręcznie wpisany DL": await _job_created_by(
            client_id, creator_id=creator, dl_id=head, auto_filled=False
        ),
        "twórca bez roli DL": await _job_created_by(
            client_id, creator_id=recruiter, dl_id=head
        ),
        "twórca z nieaktywnym kontem": await _job_created_by(
            client_id, creator_id=former_dl, dl_id=head
        ),
        "zamknięta": await _job_created_by(
            client_id, creator_id=creator, dl_id=head, status="closed"
        ),
        "z Traffita": await _job_created_by(
            client_id, creator_id=creator, dl_id=head, external_source="traffit"
        ),
    }

    async with AsyncSessionLocal() as db:
        changes = {c["job_id"]: c for c in await reassign_to_creators(db)}
        await db.commit()

    assert changes[by_dl] == {
        "job_id": by_dl,
        "previous_dl_id": head,
        "dl_id": creator,
    }
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, by_dl)
        assert job.delivery_lead_id == creator
        assert job.delivery_lead_auto_filled is False
        for reason, job_id in untouched.items():
            assert job_id not in changes, reason
            assert (await db.get(Job, job_id)).delivery_lead_id == head, reason


@needs_db
@pytest.mark.asyncio
async def test_repair_runs_once_and_keeps_a_receipt_with_ids_only() -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting
    from app.services.job_creator_delivery_lead_repair import (
        REPAIR_MARKER,
        run_job_creator_delivery_lead_repair,
    )

    head, creator = await _dl(), await _dl()
    client_id, _ = await _client_with_head(head)
    job_id = await _job_created_by(client_id, creator_id=creator, dl_id=head)

    async with AsyncSessionLocal() as db:
        await db.execute(delete(AppSetting).where(AppSetting.key == REPAIR_MARKER))
        summary = await run_job_creator_delivery_lead_repair(db)
        await db.commit()
    assert summary is not None
    assert {"job_id": job_id, "previous_dl_id": head, "dl_id": creator} in summary[
        "changes"
    ]
    assert summary["total"] == len(summary["changes"])

    async with AsyncSessionLocal() as db:
        assert await run_job_creator_delivery_lead_repair(db) is None
