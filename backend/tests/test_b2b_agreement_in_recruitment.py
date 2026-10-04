"""Rekruter generuje umowę w rekrutacji — PR 1 (backend), 04.10.2026.

Decyzje Artura: poprawia autor, rekruterzy i DL rekrutacji, TCM, admin (D3);
rekruter prosi o potwierdzenie podpisu (D1); „Zatrudniony” bez podpisu
i zamknięta karta przy żywej umowie trafiają do DL-a (D5). Podpowiedzi
formularza z rekrutacji, stan umowy na karcie, typ kontraktu przy ręcznym
zatrudnieniu.

In-process ``app_client``; baza wspólna i nieczyszczona — asercje tylko na
własnych wierszach (numery i nazwy z UUID).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from tests.test_b2b_generator_rate_visibility import _seed_user

PATH = "/api/b2b-generator/generated"


async def _admin_headers(app_client: AsyncClient) -> dict:
    resp = await app_client.post(
        "/api/auth/login",
        json={
            "email": app_client.headers["X-Test-Admin-Email"],
            "password": app_client.headers["X-Test-Admin-Password"],
        },
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_agreement(*, author_id: int, runner_id: int, dl_id: int) -> dict:
    """Klient, kandydat w rekrutacji („Nowi”), umowa „W trakcie” z rekrutacji."""

    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.models.team_structure import DeliveryLeadClientAssignment

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Umowa w rekrutacji {unique}")
        candidate = Candidate(
            name="Ewa", lastname=f"Umowa{unique}", email=f"umowa-{unique}@example.com"
        )
        db.add_all([client, candidate])
        await db.flush()
        job = Job(
            title=f"Java Developer {unique}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=runner_id,
            delivery_lead_id=dl_id,
        )
        db.add(job)
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=dl_id, client_id=client.id, is_head=True
            )
        )
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.new,
                moved_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
        seq = int(uuid.uuid4().int % 900_000) + 100_000
        row = B2BGeneratedContract(
            year=2099,
            seq=seq,
            contract_number=f"{seq}/2099",
            partner_name=f"Ewa Umowa{unique}",
            client_id=client.id,
            client_name=client.name,
            candidate_id=candidate.id,
            job_id=job.id,
            created_by=author_id,
            contract_status="in_progress",
            signature_status="unsigned",
            render_payload=None,
        )
        db.add(row)
        await db.commit()
        return {
            "client_id": client.id,
            "candidate_id": candidate.id,
            "job_id": job.id,
            "generated_id": row.id,
            "number": row.contract_number,
        }


@pytest.fixture
async def world(app_client: AsyncClient) -> dict:
    author_h, author_id = await _seed_user(app_client, "recruiter")
    runner_h, runner_id = await _seed_user(app_client, "recruiter")
    outsider_h, outsider_id = await _seed_user(app_client, "recruiter")
    tcm_h, _ = await _seed_user(app_client, "talent_community_manager")
    dl_h, dl_id = await _seed_user(app_client, "delivery_lead")
    docs = await _seed_agreement(author_id=author_id, runner_id=runner_id, dl_id=dl_id)
    return {
        **docs,
        "admin": await _admin_headers(app_client),
        "author": author_h,
        "runner": runner_h,
        "runner_id": runner_id,
        "outsider": outsider_h,
        "outsider_id": outsider_id,
        "tcm": tcm_h,
        "dl": dl_h,
        "dl_id": dl_id,
    }


async def _add_collaborator(job_id: int, user_id: int, source: str) -> None:
    from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource

    async with AsyncSessionLocal() as db:
        db.add(
            JobCollaborator(
                job_id=job_id, user_id=user_id, source=JobCollaboratorSource(source)
            )
        )
        await db.commit()


# ── D3: kto poprawia umowę pod tym samym numerem ─────────────────────────────


@pytest.mark.asyncio
async def test_job_team_corrects_the_agreement_outsiders_do_not(app_client, world):
    """Do 04.10 poprawiał tylko autor albo admin. Wiersz bez zapisanego
    formularza odpowiada 422 dopiero ZA bramką — 422 = bramka przepuściła."""
    url = f"{PATH}/{world['generated_id']}/form"
    for who in ("admin", "author", "runner", "dl"):
        resp = await app_client.get(url, headers=world[who])
        assert resp.status_code == 422, (who, resp.text)
    for who in ("outsider", "tcm"):
        # TCM może poprawiać, ale stawek cudzej umowy nie widzi (22.09.2026).
        resp = await app_client.get(url, headers=world[who])
        assert resp.status_code == 403, (who, resp.text)
        assert "stawki" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_self_added_collaborators_do_not_get_write_rights(app_client, world):
    """Uczestnik z kategorii (``auto_cc``) i ręczny współpracownik — każda rola
    wewnętrzna może dopisać się sama — nie poprawiają cudzej umowy i nie proszą
    o podpis. Prawo zapisu daje nadanie: aktywne przypisanie do requestu."""
    from app.models.job_work_assignment import WORK_ROLE, JobWorkAssignment

    await _add_collaborator(world["job_id"], world["outsider_id"], "auto_cc")
    form = f"{PATH}/{world['generated_id']}/form"
    request = f"{PATH}/{world['generated_id']}/signature-request"
    assert (await app_client.get(form, headers=world["outsider"])).status_code == 403

    manual_h, manual_id = await _seed_user(app_client, "recruiter")
    await _add_collaborator(world["job_id"], manual_id, "manual")
    assert (await app_client.get(form, headers=manual_h)).status_code == 403
    assert (await app_client.post(request, headers=manual_h)).status_code == 403

    assigned_h, assigned_id = await _seed_user(app_client, "recruiter")
    async with AsyncSessionLocal() as db:
        db.add(
            JobWorkAssignment(
                job_id=world["job_id"],
                user_id=assigned_id,
                role=WORK_ROLE,
                source="manual",
                state="active",
            )
        )
        await db.commit()
    assert (await app_client.get(form, headers=assigned_h)).status_code == 422


@pytest.mark.asyncio
async def test_register_row_tells_who_may_correct_and_where_the_person_is(
    app_client, world
):
    async def _item(who: str, **params) -> dict | None:
        resp = await app_client.get(
            PATH, headers=world[who], params={"job_id": world["job_id"], **params}
        )
        assert resp.status_code == 200, (who, resp.text)
        found = [i for i in resp.json() if i["id"] == world["generated_id"]]
        return found[0] if found else None

    runner_item = await _item("runner")
    assert runner_item["can_edit"] is True
    assert runner_item["can_delete"] is False  # usuwa nadal autor albo admin
    assert runner_item["created_by_role"] == "recruiter"
    assert runner_item["pair_column"] == "new"
    assert (await _item("outsider"))["can_edit"] is False
    assert await _item("admin", author="recruiter") is not None
    assert await _item("admin", candidate_id=world["candidate_id"]) is not None
    assert await _item("admin", candidate_id=world["candidate_id"] + 1) is None


# ── Podpowiedzi formularza z rekrutacji ──────────────────────────────────────


@pytest.mark.asyncio
async def test_prefill_reads_the_card_and_redacts_the_client_rate(app_client, world):
    from app.models.contract import RateUnit
    from app.models.recommendation_card import RecommendationCard
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        db.add(
            RecommendationCard(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                fields_notes={},
                fields_manual={
                    "rate": {
                        "raw": "140 zł/h",
                        "value": 140,
                        "currency": "PLN",
                        "period": "h",
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
                },
            )
        )
        db.add(
            CandidateStage(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                stage=PipelineStage.verified,
                moved_at=datetime.now(timezone.utc),
                client_rate_value=Decimal("180"),
                client_rate_unit=RateUnit.hourly,
                client_rate_currency="PLN",
            )
        )
        await db.commit()

    params = {"candidate_id": world["candidate_id"], "job_id": world["job_id"]}
    admin = await app_client.get(
        "/api/b2b-generator/prefill", headers=world["admin"], params=params
    )
    assert admin.status_code == 200, admin.text
    body = admin.json()
    assert body["rate"] == {"value": 140.0, "source": "card", "at": body["rate"]["at"]}
    assert body["client_rate"]["value"] == 180.0
    assert body["existing"]["id"] == world["generated_id"]

    runner = await app_client.get(
        "/api/b2b-generator/prefill", headers=world["runner"], params=params
    )
    assert runner.status_code == 200, runner.text
    assert runner.json()["client_rate"] is None
    assert runner.json()["client_rate_redacted"] is True
    assert runner.json()["rate"]["value"] == 140.0


# ── D1: prośba o potwierdzenie podpisu ───────────────────────────────────────


@pytest.mark.asyncio
async def test_recruiter_asks_the_dl_to_confirm_the_signature(app_client, world):
    from app.models.notification import Notification, NotificationType

    url = f"{PATH}/{world['generated_id']}/signature-request"
    assert (await app_client.post(url, headers=world["outsider"])).status_code == 403

    first = await app_client.post(url, headers=world["runner"])
    assert first.status_code == 200, first.text
    assert first.json()["sent"] is True
    assert len(first.json()["recipient_names"]) == 1

    again = await app_client.post(url, headers=world["runner"])
    assert again.status_code == 200, again.text
    assert again.json()["sent"] is False

    async with AsyncSessionLocal() as db:
        bells = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == world["dl_id"],
                    Notification.notification_type
                    == NotificationType.b2b_signature_requested,
                    Notification.related_entity_id == world["generated_id"],
                )
            )
        ).all()
    assert len(bells) == 1
    assert bells[0].link == f"/jobs/{world['job_id']}?candidate={world['candidate_id']}"

    dl_tasks = await app_client.get("/api/board-tasks", headers=world["dl"])
    assert dl_tasks.status_code == 200, dl_tasks.text
    to_confirm = [
        t
        for t in dl_tasks.json()["agreements"]["to_confirm"]
        if t["generated_id"] == world["generated_id"]
    ]
    assert [t["reason"] for t in to_confirm] == ["requested"]

    runner_tasks = await app_client.get("/api/board-tasks", headers=world["runner"])
    waiting = [
        t
        for t in runner_tasks.json()["agreements"]["waiting_on_others"]
        if t["generated_id"] == world["generated_id"]
    ]
    assert len(waiting) == 1


@pytest.mark.asyncio
async def test_hired_card_with_unsigned_agreement_lands_on_the_dl(app_client, world):
    """D5: „Zatrudniony” (np. z importu Traffita) przy umowie „W trakcie”."""
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                stage=PipelineStage.hired,
                moved_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    resp = await app_client.get("/api/board-tasks", headers=world["dl"])
    assert resp.status_code == 200, resp.text
    reasons = [
        t["reason"]
        for t in resp.json()["agreements"]["to_confirm"]
        if t["generated_id"] == world["generated_id"]
    ]
    assert reasons == ["hired_unsigned"]
    # Rekruter bez „Podpis B2B” nie dostaje cudzych spraw do potwierdzenia.
    outsider = await app_client.get("/api/board-tasks", headers=world["outsider"])
    assert all(
        t["generated_id"] != world["generated_id"]
        for t in outsider.json()["agreements"]["to_confirm"]
    )


# ── Stan umowy na karcie Tablicy ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_board_card_carries_the_agreement(app_client, world):
    resp = await app_client.get(
        f"/api/pipeline/kanban/{world['job_id']}", headers=world["admin"]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = [i for c in body["columns"] for i in c["items"]]
    if body.get("off_template"):
        items += body["off_template"]["items"]
    [card] = [i for i in items if i["candidate_id"] == world["candidate_id"]]
    assert card["agreement"]["number"] == world["number"]
    assert card["agreement"]["signature_status"] == "unsigned"


# ── D2: ręczne „Zatrudniony” z umową o pracę ─────────────────────────────────


@pytest.mark.asyncio
async def test_manual_hire_with_employment_contract_drafts_a_uop_contract(
    app_client, world, monkeypatch
):
    from app.core.config import settings
    from app.models.contract import Contract, ContractType

    monkeypatch.setattr(settings, "HIRED_SIGNED_VIA_REQUIRED", True)
    resp = await app_client.post(
        "/api/pipeline/move",
        headers=world["admin"],
        json={
            "candidate_id": world["candidate_id"],
            "job_id": world["job_id"],
            "stage": "hired",
            "hired_signed_via": "uop",
        },
    )
    assert resp.status_code < 300, resp.text
    async with AsyncSessionLocal() as db:
        contracts = (
            await db.scalars(
                select(Contract).where(
                    Contract.candidate_id == world["candidate_id"],
                    Contract.client_id == world["client_id"],
                )
            )
        ).all()
    assert [c.contract_type for c in contracts] == [ContractType.uop]
