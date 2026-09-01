"""Integrity containment testy pipeline'u (M4 audyt PR-02).

Kontrakty:

- **P0.5** — gate budżetowy porównuje stawki w JEDNEJ jednostce
  (168h/21d → PLN/mc); waluta ≠ PLN i nieznana jednostka failują do manual
  review (pending), nigdy do auto-approve.
- **P0.4** — para z current row w statusie pending blokuje kolejny move
  (409); approve/reject działa wyłącznie na CURRENT row pary (409 na
  historycznym pending).
- **P1.1** — target stage musi istnieć i należeć do template'u joba;
  sprzeczne `stage`+`stage_def_id` → 422; rejection reason musi należeć do
  template'u i właściwej kategorii; withdrawn wymaga reason ze słownika;
  free-text reason przy rejected jest utrwalany w notes.
- **P1.7** — ruch na etap nieterminalny anuluje niewysłane maile odrzucenia
  pary (w tej samej transakcji).
- **P0.7** — bulk: dedupe, limit 100, walidacja joba i kandydatów.
- **P0.8** — hard delete rekrutacji z hired/kontraktem → 409 dla
  nie-admina; admin może (świadomy override).
- **P2.5** — template editor: PATCH nie omija ochron DELETE, spójność
  terminalności, pełna permutacja reorderu, sla_max_days ≥ 1.

Uses in-process fixtures (real postgres in CI).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.services.rate_normalization import normalize_rate_to_monthly

MOVE = "/api/pipeline/move"


# ── Unit: normalizacja stawek ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,unit,currency,expected",
    [
        (Decimal("150"), "hourly", "PLN", Decimal("25200.00")),
        (Decimal("1000"), "daily", "PLN", Decimal("21000.00")),
        (Decimal("20000"), "monthly", "PLN", Decimal("20000.00")),
        (Decimal("150"), "hourly", None, Decimal("25200.00")),  # brak = PLN
    ],
)
def test_normalize_known_units(value, unit, currency, expected):
    normalized, note = normalize_rate_to_monthly(value, unit, currency)
    assert normalized == expected, note


@pytest.mark.parametrize(
    "value,unit,currency",
    [
        (Decimal("150"), "hourly", "EUR"),  # waluta ≠ PLN
        (Decimal("150"), "weekly", "PLN"),  # nieznana jednostka
        (Decimal("150"), None, "PLN"),  # brak jednostki
    ],
)
def test_normalize_fails_closed(value, unit, currency):
    normalized, note = normalize_rate_to_monthly(value, unit, currency)
    assert normalized is None
    assert note  # nota wyjaśnia czemu manual review


# ── Fixtures ─────────────────────────────────────────────────────────────────


async def _seed_candidate() -> int:
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Int",
            lastname=f"Egr-{uuid.uuid4().hex[:6]}",
            email=f"integ-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job(
    salary_max: int | None = None, recruiter_id: int | None = None
) -> tuple[int, int]:
    """Returns (job_id, client_id)."""
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"IntClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j = Job(
            title=f"Int-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
            salary_max=salary_max,
            recruiter_id=recruiter_id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id, cli.id


async def _seed_stage(
    candidate_id: int,
    job_id: int,
    stage_value: str,
    *,
    moved_at: datetime | None = None,
    verification_status: str = "active",
) -> int:
    from app.models.recruitment_pipeline import (
        CandidateStage,
        PipelineStage,
        VerificationStatus,
    )

    async with AsyncSessionLocal() as db:
        stage = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage(stage_value),
            moved_at=moved_at or datetime.now(timezone.utc),
            verification_status=VerificationStatus(verification_status),
        )
        db.add(stage)
        await db.commit()
        await db.refresh(stage)
        return stage.id


async def _seed_template(
    *, is_default: bool = False, with_reason_category: str | None = None
) -> tuple[int, int | None, int | None]:
    """Returns (template_id, stage_def_id[screening-like], reason_id)."""
    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        RejectionReason,
        StageCategoryEnum,
        TerminalType,
    )

    async with AsyncSessionLocal() as db:
        tpl = PipelineTemplate(
            name=f"Int-Tpl-{uuid.uuid4().hex[:6]}", is_default=is_default
        )
        db.add(tpl)
        await db.flush()
        sd = PipelineStageDef(
            template_id=tpl.id,
            name="Int Custom Stage",
            order=1,
            category=StageCategoryEnum.internal,
        )
        db.add(sd)
        await db.flush()
        reason_id = None
        if with_reason_category:
            reason = RejectionReason(
                template_id=tpl.id,
                name=f"Int-Reason-{uuid.uuid4().hex[:4]}",
                category=TerminalType(with_reason_category),
            )
            db.add(reason)
            await db.flush()
            reason_id = reason.id
        await db.commit()
        return tpl.id, sd.id, reason_id


# ── P0.5: gate budżetowy w jednej jednostce ──────────────────────────────────


async def test_hourly_rate_over_monthly_budget_goes_pending(
    app_client: AsyncClient, app_auth_headers
):
    """150 PLN/h vs budżet 25 000 PLN/mc: stary kod → active (150<25000);
    po normalizacji 150×168=25 200 > 25 000 → pending."""
    cand, (job, _) = await _seed_candidate(), await _seed_job(salary_max=25000)
    r = await app_client.post(
        MOVE,
        json={
            "candidate_id": cand,
            "job_id": job,
            "stage": "verified",
            "expected_rate_value": 150,
            "expected_rate_unit": "hourly",
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["verification_status"] == "pending"


async def test_hourly_rate_within_budget_stays_active(
    app_client: AsyncClient, app_auth_headers
):
    """100 PLN/h ×168 = 16 800 < 25 000 → active."""
    cand, (job, _) = await _seed_candidate(), await _seed_job(salary_max=25000)
    r = await app_client.post(
        MOVE,
        json={
            "candidate_id": cand,
            "job_id": job,
            "stage": "verified",
            "expected_rate_value": 100,
            "expected_rate_unit": "hourly",
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["verification_status"] == "active"


async def test_foreign_currency_goes_manual_review(
    app_client: AsyncClient, app_auth_headers
):
    """EUR nie jest auto-przeliczane — fail-closed do pending."""
    cand, (job, _) = await _seed_candidate(), await _seed_job(salary_max=25000)
    r = await app_client.post(
        MOVE,
        json={
            "candidate_id": cand,
            "job_id": job,
            "stage": "verified",
            "expected_rate_value": 10,
            "expected_rate_unit": "hourly",
            "expected_rate_currency": "EUR",
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["verification_status"] == "pending"


async def test_pending_list_exposes_normalized_value(
    app_client: AsyncClient, app_auth_headers
):
    cand, (job, _) = await _seed_candidate(), await _seed_job(salary_max=20000)
    r = await app_client.post(
        MOVE,
        json={
            "candidate_id": cand,
            "job_id": job,
            "stage": "verified",
            "expected_rate_value": 200,
            "expected_rate_unit": "hourly",
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200 and r.json()["verification_status"] == "pending"
    lst = await app_client.get(
        f"/api/pipeline/pending-verifications?job_id={job}",
        headers=app_auth_headers,
    )
    assert lst.status_code == 200, lst.text
    rows = [x for x in lst.json() if x["candidate_id"] == cand]
    assert rows and Decimal(str(rows[0]["normalized_monthly_value"])) == Decimal(
        "33600.00"
    )


# ── P0.4: pending blokuje ruch; decyzja tylko na current ─────────────────────


async def test_move_blocked_while_pending(app_client: AsyncClient, app_auth_headers):
    cand, (job, _) = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "verified", verification_status="pending")
    r = await app_client.post(
        MOVE,
        json={"candidate_id": cand, "job_id": job, "stage": "interview"},
        headers=app_auth_headers,
    )
    assert r.status_code == 409, r.text


async def test_accept_verification_requires_current_row(
    app_client: AsyncClient, app_auth_headers
):
    now = datetime.now(timezone.utc)
    cand, (job, _) = await _seed_candidate(), await _seed_job()
    stale_pending = await _seed_stage(
        cand,
        job,
        "verified",
        moved_at=now - timedelta(days=2),
        verification_status="pending",
    )
    await _seed_stage(cand, job, "interview", moved_at=now - timedelta(days=1))
    r = await app_client.post(
        f"/api/pipeline/{stale_pending}/accept-verification",
        headers=app_auth_headers,
    )
    assert r.status_code == 409, r.text
    assert "aktualnym stanem" in r.json()["detail"]


# ── P1.1: target/reason integrity ────────────────────────────────────────────


async def test_move_rejects_nonexistent_stage_def(
    app_client: AsyncClient, app_auth_headers
):
    cand, (job, _) = await _seed_candidate(), await _seed_job()
    r = await app_client.post(
        MOVE,
        json={"candidate_id": cand, "job_id": job, "stage_def_id": 99999999},
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text


async def test_move_rejects_stage_from_foreign_template(
    app_client: AsyncClient, app_auth_headers
):
    """Target stage_def z innego template'u niż template joba → 422."""
    from app.models.job import Job

    _, foreign_stage_def, _ = await _seed_template()
    own_template_id, _, _ = await _seed_template()
    cand, (job, _) = await _seed_candidate(), await _seed_job()
    async with AsyncSessionLocal() as db:
        j = await db.get(Job, job)
        j.pipeline_template_id = own_template_id
        await db.commit()

    r = await app_client.post(
        MOVE,
        json={"candidate_id": cand, "job_id": job, "stage_def_id": foreign_stage_def},
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text
    assert "template" in r.json()["detail"].lower()


async def test_withdrawn_requires_dictionary_reason(
    app_client: AsyncClient, app_auth_headers
):
    """Free-text nie wystarcza dla withdrawn (DB CHECK) — czyste 422, nie 500."""
    cand, (job, _) = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "screening")
    r = await app_client.post(
        MOVE,
        json={
            "candidate_id": cand,
            "job_id": job,
            "stage": "withdrawn",
            "rejection_reason": "sam się wycofał",
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text
    assert "słownika" in r.json()["detail"]


async def test_rejected_free_text_is_persisted_in_notes(
    app_client: AsyncClient, app_auth_headers
):
    """Legacy rejected + free-text: dotąd tekst znikał — teraz ląduje w notes."""
    from app.models.recruitment_pipeline import CandidateStage

    cand, (job, _) = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "screening")
    r = await app_client.post(
        MOVE,
        json={
            "candidate_id": cand,
            "job_id": job,
            "stage": "rejected",
            "rejection_reason": "brak dopasowania technicznego",
            "send_rejection_email": False,
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    async with AsyncSessionLocal() as db:
        row = await db.get(CandidateStage, r.json()["id"])
        assert row is not None
        assert "brak dopasowania technicznego" in (row.notes or "")


async def test_reason_from_foreign_template_rejected(
    app_client: AsyncClient, app_auth_headers
):
    from app.models.job import Job

    _, _, foreign_reason = await _seed_template(with_reason_category="rejected")
    own_template_id, _, _ = await _seed_template(with_reason_category="rejected")
    cand, (job, _) = await _seed_candidate(), await _seed_job()
    async with AsyncSessionLocal() as db:
        j = await db.get(Job, job)
        j.pipeline_template_id = own_template_id
        await db.commit()
    await _seed_stage(cand, job, "screening")
    r = await app_client.post(
        MOVE,
        json={
            "candidate_id": cand,
            "job_id": job,
            "stage": "rejected",
            "rejection_reason_id": foreign_reason,
            "send_rejection_email": False,
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text


async def test_reason_wrong_category_rejected(
    app_client: AsyncClient, app_auth_headers
):
    """Powód kategorii 'withdrawn' przy ruchu 'rejected' → 422."""
    from app.models.job import Job

    tpl_id, _, withdrawn_reason = await _seed_template(with_reason_category="withdrawn")
    cand, (job, _) = await _seed_candidate(), await _seed_job()
    async with AsyncSessionLocal() as db:
        j = await db.get(Job, job)
        j.pipeline_template_id = tpl_id
        await db.commit()
    await _seed_stage(cand, job, "screening")
    r = await app_client.post(
        MOVE,
        json={
            "candidate_id": cand,
            "job_id": job,
            "stage": "rejected",
            "rejection_reason_id": withdrawn_reason,
            "send_rejection_email": False,
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text
    assert "kategori" in r.json()["detail"].lower()


# ── P1.7: restore anuluje niewysłane maile odrzucenia ────────────────────────


async def test_restore_cancels_pending_rejection_email(
    app_client: AsyncClient, app_auth_headers
):
    from sqlalchemy import select

    from app.models.rejection_email import (
        RejectionEmailStatus,
        ScheduledRejectionEmail,
    )
    from app.models.user import User

    cand, (job, _) = await _seed_candidate(), await _seed_job()
    stage_id = await _seed_stage(cand, job, "rejected")
    async with AsyncSessionLocal() as db:
        any_user = await db.scalar(select(User).limit(1))
        mail = ScheduledRejectionEmail(
            candidate_stage_id=stage_id,
            candidate_id=cand,
            job_id=job,
            recruiter_id=any_user.id,
            to_email="restore-me@example.com",
            subject="x",
            body_html="<p>x</p>",
            status=RejectionEmailStatus.pending,
            scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.add(mail)
        await db.commit()
        await db.refresh(mail)
        mail_id = mail.id

    r = await app_client.post(
        MOVE,
        json={"candidate_id": cand, "job_id": job, "stage": "screening"},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as db:
        row = await db.get(ScheduledRejectionEmail, mail_id)
        assert row.status == RejectionEmailStatus.cancelled
        assert row.cancelled_at is not None


# ── P0.7: bulk hygiene ───────────────────────────────────────────────────────


async def test_bulk_dedupes_and_validates(app_client: AsyncClient, app_auth_headers):
    cand, (job, _) = await _seed_candidate(), await _seed_job()
    r = await app_client.post(
        "/api/pipeline/bulk-move",
        json={"candidate_ids": [cand, cand, cand], "job_id": job, "stage": "screening"},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["moved"] == 1  # dedupe

    r = await app_client.post(
        "/api/pipeline/bulk-move",
        json={"candidate_ids": [cand, 99999999], "job_id": job, "stage": "screening"},
        headers=app_auth_headers,
    )
    assert r.status_code == 422 and "99999999" in r.text

    r = await app_client.post(
        "/api/pipeline/bulk-move",
        json={"candidate_ids": [cand], "job_id": 99999999, "stage": "screening"},
        headers=app_auth_headers,
    )
    assert r.status_code == 404

    r = await app_client.post(
        "/api/pipeline/bulk-move",
        json={
            "candidate_ids": list(range(1, 103)),
            "job_id": job,
            "stage": "screening",
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 422 and "100" in r.json()["detail"]


# ── P0.8: hard delete guard ──────────────────────────────────────────────────


async def _login_as(
    app_client: AsyncClient, role_value: str
) -> tuple[dict[str, str], int]:
    """Zwraca (nagłówki, user_id).

    ``user_id`` jest potrzebny, bo trasy pipeline'u sprawdzają teraz nie samą
    rolę, ale przynależność do KONKRETNEJ rekrutacji — test musi więc umieć
    przypisać zalogowanego rekrutera do oferty, na której działa.
    """
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"int-{role_value}-{unique}@example.com"
    password = f"T3st_{unique}!In"
    async with AsyncSessionLocal() as db:
        actor = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Int {role_value}",
            role=UserRole(role_value),
            is_active=True,
        )
        db.add(actor)
        await db.commit()
        await db.refresh(actor)
        actor_id = actor.id
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, actor_id


async def test_hard_delete_blocked_for_hired_history(app_client: AsyncClient):
    headers, actor_id = await _login_as(app_client, "recruiter")
    cand, (job, _) = await _seed_candidate(), await _seed_job(recruiter_id=actor_id)
    await _seed_stage(cand, job, "hired")
    r = await app_client.delete(
        f"/api/candidates/{cand}/recruitments/{job}", headers=headers
    )
    assert r.status_code == 409, r.text


async def test_hard_delete_blocked_for_contract_pair(app_client: AsyncClient):
    from app.models.contract import Contract

    headers, actor_id = await _login_as(app_client, "recruiter")
    cand, (job, client_id) = (
        await _seed_candidate(),
        await _seed_job(recruiter_id=actor_id),
    )
    await _seed_stage(cand, job, "screening")
    async with AsyncSessionLocal() as db:
        db.add(Contract(candidate_id=cand, client_id=client_id, job_id=job))
        await db.commit()
    r = await app_client.delete(
        f"/api/candidates/{cand}/recruitments/{job}", headers=headers
    )
    assert r.status_code == 409, r.text


async def test_hard_delete_admin_override_and_plain_pair(
    app_client: AsyncClient, app_auth_headers
):
    # Admin może usunąć parę z hired (świadomy override)…
    cand, (job, _) = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "hired")
    r = await app_client.delete(
        f"/api/candidates/{cand}/recruitments/{job}", headers=app_auth_headers
    )
    assert r.status_code == 200, r.text
    # …a recruiter zwykłą parę bez hired/kontraktu.
    headers, actor_id = await _login_as(app_client, "recruiter")
    cand2, (job2, _) = await _seed_candidate(), await _seed_job(recruiter_id=actor_id)
    await _seed_stage(cand2, job2, "screening")
    r = await app_client.delete(
        f"/api/candidates/{cand2}/recruitments/{job2}", headers=headers
    )
    assert r.status_code == 200, r.text


# ── P2.5: template editor guards ─────────────────────────────────────────────


async def test_template_patch_cannot_bypass_archive_guards(
    app_client: AsyncClient, app_auth_headers
):
    from app.models.job import Job

    tpl_id, _, _ = await _seed_template()
    _, (job, _) = await _seed_candidate(), await _seed_job()
    async with AsyncSessionLocal() as db:
        j = await db.get(Job, job)
        j.pipeline_template_id = tpl_id
        await db.commit()
    r = await app_client.patch(
        f"/api/pipeline-templates/{tpl_id}",
        json={"archived": True},
        headers=app_auth_headers,
    )
    assert r.status_code == 409, r.text


async def test_template_patch_cannot_unset_only_default(
    app_client: AsyncClient, app_auth_headers
):
    from sqlalchemy import update as sa_update

    from app.models.pipeline_template import PipelineTemplate

    tpl_id, _, _ = await _seed_template()
    async with AsyncSessionLocal() as db:
        await db.execute(
            sa_update(PipelineTemplate)
            .where(PipelineTemplate.id == tpl_id)
            .values(is_default=True)
        )
        await db.commit()
    r = await app_client.patch(
        f"/api/pipeline-templates/{tpl_id}",
        json={"is_default": False},
        headers=app_auth_headers,
    )
    assert r.status_code == 409, r.text


async def test_stage_patch_terminal_coherence(
    app_client: AsyncClient, app_auth_headers
):
    tpl_id, stage_def_id, _ = await _seed_template()
    r = await app_client.patch(
        f"/api/pipeline-templates/{tpl_id}/stages/{stage_def_id}",
        json={"is_terminal": True},
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text
    r = await app_client.patch(
        f"/api/pipeline-templates/{tpl_id}/stages/{stage_def_id}",
        json={"terminal_type": "rejected"},
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text
    r = await app_client.patch(
        f"/api/pipeline-templates/{tpl_id}/stages/{stage_def_id}",
        json={"sla_max_days": 0},
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text


async def test_reorder_requires_full_unique_permutation(
    app_client: AsyncClient, app_auth_headers
):
    from app.models.pipeline_template import PipelineStageDef, StageCategoryEnum

    tpl_id, stage_a, _ = await _seed_template()
    async with AsyncSessionLocal() as db:
        sd = PipelineStageDef(
            template_id=tpl_id,
            name="Int Second",
            order=2,
            category=StageCategoryEnum.internal,
        )
        db.add(sd)
        await db.commit()
        await db.refresh(sd)
        stage_b = sd.id

    # Częściowa lista → 422
    r = await app_client.patch(
        f"/api/pipeline-templates/{tpl_id}/stages/reorder",
        json=[{"stage_id": stage_a, "order": 5}],
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text
    # Zduplikowane ordery → 422
    r = await app_client.patch(
        f"/api/pipeline-templates/{tpl_id}/stages/reorder",
        json=[
            {"stage_id": stage_a, "order": 1},
            {"stage_id": stage_b, "order": 1},
        ],
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text
    # Pełna poprawna permutacja → 204
    r = await app_client.patch(
        f"/api/pipeline-templates/{tpl_id}/stages/reorder",
        json=[
            {"stage_id": stage_a, "order": 2},
            {"stage_id": stage_b, "order": 1},
        ],
        headers=app_auth_headers,
    )
    assert r.status_code == 204, r.text
