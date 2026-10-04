"""0415: niedokończone formularze „Nowa rekrutacja” na koncie autora.

Testy z bazą (CI) + kontrakty bez bazy (lustro DDL, limity).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.job_intake_form import JobIntakeForm
from app.models.user import UserRole
from app.services import job_intake_form_schema, job_intake_forms
from tests._jarvis_helpers import make_user

URL = "/api/job-intake/forms"
_BACKEND = Path(__file__).resolve().parent.parent


# ── bez bazy ─────────────────────────────────────────────────────────────────


def test_entrypoint_mirrors_the_migration_sql():
    entrypoint = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    for stmt in (job_intake_form_schema.TABLE_DDL, job_intake_form_schema.INDEX_DDL):
        assert stmt in entrypoint, stmt


def test_migration_reads_the_single_source():
    migration = (
        _BACKEND / "alembic" / "versions" / "0415_job_intake_forms.py"
    ).read_text(encoding="utf-8")
    assert "job_intake_form_schema" in migration
    assert 'down_revision = "0414_job_required_decisions"' in migration


def test_form_size_counts_utf8_bytes():
    # Polskie znaki to dwa bajty — limit dotyczy tego, co zapisze Postgres.
    assert job_intake_forms.form_size_bytes({"a": "ą"}) == len('{"a":"ą"}'.encode())


def test_expiry_is_thirty_days_after_last_change():
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    assert job_intake_forms.expires_at(now) == now + timedelta(days=30)


def test_router_does_not_log_form_content():
    source = (_BACKEND / "app" / "api" / "job_intake_forms.py").read_text("utf-8")
    assert "logger" not in source


# ── z bazą ───────────────────────────────────────────────────────────────────


async def _client() -> tuple[int, str]:
    name = f"Formularze {uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        client = Client(name=name)
        db.add(client)
        await db.commit()
        return client.id, name


def _body(client_id: int | None = None, **over) -> dict:
    body = {
        "label": "Java Developer — fikcyjny klient",
        "client_id": client_id,
        "source": "text",
        "request_text": "Szukamy Java Developera, start od zaraz.",
        "form": {"title": "Java Developer", "must": ["Java"]},
    }
    body.update(over)
    return body


@pytest.mark.asyncio
async def test_author_saves_lists_reads_updates_and_deletes(app_client) -> None:
    _, headers = await make_user(UserRole.delivery_lead)
    client_id, client_name = await _client()

    created = await app_client.post(URL, json=_body(client_id), headers=headers)
    assert created.status_code == 201, created.text
    form_id = created.json()["id"]
    assert created.json()["updated_at"]

    listed = await app_client.get(URL, headers=headers)
    assert listed.status_code == 200, listed.text
    item = next(i for i in listed.json()["items"] if i["id"] == form_id)
    assert item["client_name"] == client_name
    assert item["source"] == "text"
    assert item["expires_at"] > item["updated_at"]
    assert "form" not in item and "request_text" not in item

    read = await app_client.get(f"{URL}/{form_id}", headers=headers)
    assert read.status_code == 200, read.text
    assert read.json()["form"] == {"title": "Java Developer", "must": ["Java"]}
    assert read.json()["request_text"].startswith("Szukamy")

    updated = await app_client.put(
        f"{URL}/{form_id}",
        json=_body(client_id, label="Inna nazwa", form={"title": "Senior"}),
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    read = await app_client.get(f"{URL}/{form_id}", headers=headers)
    assert read.json()["label"] == "Inna nazwa"
    assert read.json()["form"] == {"title": "Senior"}

    deleted = await app_client.delete(f"{URL}/{form_id}", headers=headers)
    assert deleted.status_code == 204
    assert (
        await app_client.get(f"{URL}/{form_id}", headers=headers)
    ).status_code == 404


@pytest.mark.asyncio
async def test_other_person_gets_404_for_every_operation(app_client) -> None:
    _, author = await make_user(UserRole.delivery_lead)
    _, other = await make_user(UserRole.delivery_lead)
    form_id = (await app_client.post(URL, json=_body(), headers=author)).json()["id"]

    assert (await app_client.get(f"{URL}/{form_id}", headers=other)).status_code == 404
    assert (
        await app_client.put(f"{URL}/{form_id}", json=_body(), headers=other)
    ).status_code == 404
    assert (
        await app_client.delete(f"{URL}/{form_id}", headers=other)
    ).status_code == 404
    listed = (await app_client.get(URL, headers=other)).json()["items"]
    assert form_id not in {i["id"] for i in listed}
    # Autor dalej ma swój formularz.
    assert (await app_client.get(f"{URL}/{form_id}", headers=author)).status_code == 200


@pytest.mark.asyncio
async def test_recruiter_without_recruitment_manage_is_refused(app_client) -> None:
    _, headers = await make_user(UserRole.recruiter)
    assert (await app_client.get(URL, headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_twenty_one_forms_hit_the_limit(app_client) -> None:
    user_id, headers = await make_user(UserRole.delivery_lead)
    async with AsyncSessionLocal() as db:
        db.add_all(
            JobIntakeForm(user_id=user_id, label=f"F{i}", form={})
            for i in range(job_intake_forms.MAX_FORMS_PER_USER)
        )
        await db.commit()

    resp = await app_client.post(URL, json=_body(), headers=headers)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "forms_limit"
    assert resp.json()["detail"]["message"]


@pytest.mark.asyncio
async def test_size_limits_give_422(app_client) -> None:
    _, headers = await make_user(UserRole.delivery_lead)
    too_big = {"blob": "x" * (job_intake_forms.MAX_FORM_BYTES + 10)}
    assert (
        await app_client.post(URL, json=_body(form=too_big), headers=headers)
    ).status_code == 422
    long_text = "a" * (job_intake_forms.MAX_REQUEST_TEXT_CHARS + 1)
    assert (
        await app_client.post(URL, json=_body(request_text=long_text), headers=headers)
    ).status_code == 422


@pytest.mark.asyncio
async def test_unknown_client_is_422(app_client) -> None:
    _, headers = await make_user(UserRole.delivery_lead)
    resp = await app_client.post(
        URL, json=_body(client_id=2_000_000_000), headers=headers
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_retention_deletes_only_forms_older_than_thirty_days() -> None:
    from app.tasks import queue_retention

    user_id, _ = await make_user(UserRole.delivery_lead)
    old = datetime.now(timezone.utc) - timedelta(days=31)
    async with AsyncSessionLocal() as db:
        stale = JobIntakeForm(user_id=user_id, label="stary", form={})
        fresh = JobIntakeForm(user_id=user_id, label="świeży", form={})
        db.add_all([stale, fresh])
        await db.flush()
        await db.execute(
            text("UPDATE job_intake_forms SET updated_at = :t WHERE id = :i"),
            {"t": old, "i": stale.id},
        )
        await db.commit()
        stale_id, fresh_id = stale.id, fresh.id

    await queue_retention.prune_once()

    async with AsyncSessionLocal() as db:
        left = set(
            (
                await db.scalars(
                    select(JobIntakeForm.id).where(
                        JobIntakeForm.id.in_([stale_id, fresh_id])
                    )
                )
            ).all()
        )
    assert left == {fresh_id}


@pytest.mark.asyncio
async def test_delete_own_form_helper_refuses_foreign_form() -> None:
    author_id, _ = await make_user(UserRole.delivery_lead)
    other_id, _ = await make_user(UserRole.delivery_lead)
    async with AsyncSessionLocal() as db:
        row = JobIntakeForm(user_id=author_id, label="x", form={})
        db.add(row)
        await db.flush()
        assert not await job_intake_forms.delete_own_form(
            db, user_id=other_id, form_id=row.id
        )
        assert await job_intake_forms.delete_own_form(
            db, user_id=author_id, form_id=row.id
        )
        await db.rollback()
