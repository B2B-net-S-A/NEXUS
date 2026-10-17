"""Integrity containment testy pipeline'u (M4 audyt PR-02).

Kontrakty:

- **P0.5** — porównanie stawki z budżetem idzie w JEDNEJ jednostce
  (168h/21d → PLN/mc); waluta ≠ PLN i nieznana jednostka to BRAK porównania,
  nigdy „ponad budżet". Od 17.09.2026 nic tu nie blokuje ruchu — wynik zasila
  wyłącznie odznakę `budget_exceeded`.
- **P0.4** — bramka „Oczekuje" USUNIĘTA: wiersz historyczny `pending` nie
  blokuje kolejnego ruchu (dawniej 409).
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


# ── P0.5: porównanie stawki z budżetem w jednej jednostce ───────────────────


async def test_hourly_rate_within_budget_stays_active(
    app_client: AsyncClient, app_auth_headers
):
    """100 PLN/h ×168 = 16 800 < 25 000 → active."""
    cand, (job, _) = await _seed_candidate(), await _seed_job(salary_max=25000)
    await _seed_stage(cand, job, "new")  # R9-N11-4: najpierw w „Nowych”
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


async def test_hired_move_survives_contract_draft_conflict(
    app_client: AsyncClient, app_auth_headers
):
    """Dwa żywe kontrakty pary → serwis szkicu odmawia 409. Zatrudnienie zostaje,
    kontraktów nadal dwa, jest `Activity(contract_draft_skipped)`."""
    from sqlalchemy import func, select

    from app.models.activity import Activity
    from app.models.contract import Contract, ContractStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    cand, (job, client_id) = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "acceptance")
    async with AsyncSessionLocal() as db:
        for _ in range(2):
            db.add(
                Contract(
                    candidate_id=cand,
                    client_id=client_id,
                    job_id=job,
                    status=ContractStatus.draft,
                )
            )
        await db.commit()

    r = await app_client.post(
        MOVE,
        json={"candidate_id": cand, "job_id": job, "stage": "hired"},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    stage_id = r.json()["id"]

    async with AsyncSessionLocal() as db:
        latest = await db.scalar(
            select(CandidateStage)
            .where(CandidateStage.candidate_id == cand, CandidateStage.job_id == job)
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
        assert latest is not None and latest.stage == PipelineStage.hired
        contracts = await db.scalar(
            select(func.count())
            .select_from(Contract)
            .where(Contract.candidate_id == cand, Contract.client_id == client_id)
        )
        assert contracts == 2
        skipped = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "pipeline",
                Activity.entity_id == stage_id,
                Activity.action == "contract_draft_skipped",
            )
        )
        assert skipped is not None
        assert "więcej niż jeden" in skipped.details["reason"]


async def test_hourly_rate_over_monthly_budget_stays_active(
    app_client: AsyncClient, app_auth_headers
):
    """150 PLN/h ×168 = 25 200 > 25 000 — do 17.09.2026 `pending`, dziś `active`;
    snapshot budżetu zostaje dla audytu."""
    cand, (job, _) = await _seed_candidate(), await _seed_job(salary_max=25000)
    await _seed_stage(cand, job, "new")  # R9-N11-4: najpierw w „Nowych”
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
    assert r.json()["verification_status"] == "active"
    assert r.json()["budget_max_at_move"] == 25000


async def test_foreign_currency_rate_stays_active(
    app_client: AsyncClient, app_auth_headers
):
    """EUR nie jest porównywane z budżetem — ale też niczego nie blokuje."""
    cand, (job, _) = await _seed_candidate(), await _seed_job(salary_max=25000)
    await _seed_stage(cand, job, "new")  # R9-N11-4: najpierw w „Nowych”
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
    assert r.json()["verification_status"] == "active"


async def test_kanban_carries_sheet_badges_and_profile_rate(
    app_client: AsyncClient, app_auth_headers
):
    from app.models.candidate import Candidate
    from app.models.recruitment_pipeline import CandidateStage

    cand, (job, _) = await _seed_candidate(), await _seed_job()
    empty_sheet_cand = await _seed_candidate()
    stage_id = await _seed_stage(cand, job, "verified")
    empty_stage_id = await _seed_stage(empty_sheet_cand, job, "verified")
    async with AsyncSessionLocal() as db:
        c = await db.get(Candidate, cand)
        c.expected_rate_hourly = Decimal("120")
        filled = await db.get(CandidateStage, stage_id)
        filled.screening_answers = {
            "answers": [{"question_id": "q1", "response": "ok"}]
        }
        empty = await db.get(CandidateStage, empty_stage_id)
        # Domyślny kształt `ScreeningAnswers` — pusta lista to NIE wypełniony arkusz.
        empty.screening_answers = {
            "answers": [],
            "overall_fit": "uncertain",
            "notes": "",
        }
        await db.commit()

    r = await app_client.get(f"/api/pipeline/kanban/{job}", headers=app_auth_headers)
    assert r.status_code == 200, r.text
    items = {
        item["candidate_id"]: item
        for col in r.json()["columns"]
        for item in col["items"]
    }
    assert items[cand]["screening_done"] is True
    assert items[cand]["scorecard_done"] is False
    assert Decimal(str(items[cand]["candidate_expected_rate_hourly"])) == Decimal("120")
    assert items[empty_sheet_cand]["screening_done"] is False


async def test_kanban_in_a_job_without_questions_asks_for_the_assessment(
    app_client: AsyncClient, app_auth_headers
):
    """Zgłoszenie 13.10.2026: rekrutacja bez pytań screeningowych nie ma
    arkusza, a karta w „Screeningu” dalej prosiła o jego uzupełnienie. Karta
    niesie teraz wymaganie „Dlaczego ten kandydat” i wie, czy jest wpisane."""
    from app.models.job import Job
    from app.models.recommendation_card import RecommendationCard

    assessed, bare = await _seed_candidate(), await _seed_candidate()
    job, _ = await _seed_job()
    with_questions, _ = await _seed_job()
    asked = await _seed_candidate()
    for cand in (assessed, bare):
        await _seed_stage(cand, job, "screening")
    await _seed_stage(asked, with_questions, "screening")
    async with AsyncSessionLocal() as db:
        (await db.get(Job, with_questions)).champion_profile = {
            "screening_questions": [{"id": "q1", "question": "Ile lat z Javą?"}]
        }
        for cand, job_id in ((assessed, job), (asked, with_questions)):
            db.add(
                RecommendationCard(
                    candidate_id=cand,
                    job_id=job_id,
                    fields_manual={
                        "recommendation": {
                            "raw": "Zna raportowanie podatkowe.",
                            "at": datetime.now(timezone.utc).isoformat(),
                        }
                    },
                )
            )
        await db.commit()

    async def cards(job_id: int) -> dict[int, dict]:
        r = await app_client.get(
            f"/api/pipeline/kanban/{job_id}", headers=app_auth_headers
        )
        assert r.status_code == 200, r.text
        return {
            item["candidate_id"]: item
            for col in r.json()["columns"]
            for item in col["items"]
        }

    no_questions = await cards(job)
    assert no_questions[assessed]["screening_requirement"] == "why_candidate"
    assert no_questions[assessed]["screening_done"] is True
    assert no_questions[bare]["screening_requirement"] == "why_candidate"
    assert no_questions[bare]["screening_done"] is False
    # Rekrutacja z pytaniami: ocena nie zastępuje arkusza, pole zostaje puste.
    asked_card = (await cards(with_questions))[asked]
    assert asked_card["screening_requirement"] is None
    assert asked_card["screening_done"] is False


async def test_move_from_legacy_pending_row_is_allowed(
    app_client: AsyncClient, app_auth_headers
):
    cand, (job, _) = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "verified", verification_status="pending")
    r = await app_client.post(
        MOVE,
        json={"candidate_id": cand, "job_id": job, "stage": "interview"},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text


async def test_rejection_email_is_scheduled_only_on_explicit_opt_in(
    app_client: AsyncClient, app_auth_headers, monkeypatch
):
    """Bez `send_rejection_email=True` serwer nie planuje maila; z `True` — tak."""
    from unittest.mock import AsyncMock

    import app.services.rejection_email_scheduler as scheduler

    schedule = AsyncMock(return_value=None)
    monkeypatch.setattr(scheduler, "maybe_schedule", schedule)
    # Runda 9 (R9-N11-1): mail wychodzi ze skrzynki odrzucającego — tu udajemy,
    # że ją ma (test niżej sprawdza przypadek bez skrzynki).
    monkeypatch.setattr(scheduler, "sender_has_mailbox", AsyncMock(return_value=True))

    cand, (job, _) = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "cv_sent")
    r = await app_client.post(
        MOVE,
        json={
            "candidate_id": cand,
            "job_id": job,
            "stage": "rejected",
            "rejection_reason": "Klient wybrał innego kandydata",
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    schedule.assert_not_awaited()

    cand2, (job2, _) = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand2, job2, "cv_sent")
    r2 = await app_client.post(
        MOVE,
        json={
            "candidate_id": cand2,
            "job_id": job2,
            "stage": "rejected",
            "rejection_reason": "Klient wybrał innego kandydata",
            "send_rejection_email": True,
        },
        headers=app_auth_headers,
    )
    assert r2.status_code == 200, r2.text
    schedule.assert_awaited_once()
    # Mail planuje się na OSOBĘ, która odrzuca, nie na prowadzącego rekrutacji.
    me = await app_client.get("/api/auth/me", headers=app_auth_headers)
    assert schedule.await_args.kwargs["recruiter_id"] == me.json()["id"]
    # Atrapa nic nie zapisała → serwer mówi wprost, że maila nie ma.
    assert r2.json()["rejection_email_status"] == "not_client_visible"
    assert r.json()["rejection_email_status"] is None


async def test_rejection_email_without_mailbox_is_refused_out_loud(
    app_client: AsyncClient, app_auth_headers, monkeypatch
):
    """Runda 9 (R9-N11-1/N11-2): odrzucający bez skrzynki M365 nie dostaje
    maila zaplanowanego z cudzej skrzynki ani cichego `skipped` po 15 minutach
    — odpowiedź ruchu mówi `no_mailbox`, a wiersz harmonogramu nie powstaje."""
    from unittest.mock import AsyncMock

    from sqlalchemy import select

    import app.services.rejection_email_scheduler as scheduler
    from app.models.rejection_email import ScheduledRejectionEmail

    monkeypatch.setattr(scheduler, "sender_has_mailbox", AsyncMock(return_value=False))
    cand, (job, _) = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "cv_sent")
    r = await app_client.post(
        MOVE,
        json={
            "candidate_id": cand,
            "job_id": job,
            "stage": "rejected",
            "rejection_reason": "Klient wybrał innego kandydata",
            "send_rejection_email": True,
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["rejection_email_status"] == "no_mailbox"
    assert r.json()["scheduled_rejection_email_id"] is None
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(ScheduledRejectionEmail.id).where(
                    ScheduledRejectionEmail.candidate_id == cand
                )
            )
        ).all()
    assert rows == []


async def test_move_sends_the_text_edited_in_the_rejection_window(
    app_client: AsyncClient, app_auth_headers, monkeypatch
):
    """13.10.2026: temat i treść z podglądu w oknie odrzucenia idą do wiersza
    harmonogramu — treść jako zwykły tekst z escape."""
    from unittest.mock import AsyncMock

    from sqlalchemy import select

    import app.services.rejection_email_scheduler as scheduler
    from app.models.rejection_email import ScheduledRejectionEmail

    monkeypatch.setattr(scheduler, "sender_has_mailbox", AsyncMock(return_value=True))
    cand, (job, _) = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "cv_sent")
    r = await app_client.post(
        MOVE,
        json={
            "candidate_id": cand,
            "job_id": job,
            "stage": "rejected",
            "rejection_reason": "Klient wybrał innego kandydata",
            "send_rejection_email": True,
            "rejection_email_subject": "Twoja rekrutacja\nw B2B",
            "rejection_email_body": "Cześć,\n\n<script>x</script> dziękujemy.",
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["rejection_email_status"] == "scheduled"
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(ScheduledRejectionEmail).where(
                ScheduledRejectionEmail.candidate_id == cand
            )
        )
    assert row is not None
    assert row.subject == "Twoja rekrutacja w B2B"
    assert row.body_html == (
        "<p>Cześć,</p>\n<p>&lt;script&gt;x&lt;/script&gt; dziękujemy.</p>"
    )


async def test_move_refuses_a_blank_rejection_mail(
    app_client: AsyncClient, app_auth_headers
):
    cand, (job, _) = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "cv_sent")
    r = await app_client.post(
        MOVE,
        json={
            "candidate_id": cand,
            "job_id": job,
            "stage": "rejected",
            "rejection_reason": "Klient wybrał innego kandydata",
            "send_rejection_email": True,
            "rejection_email_body": "   \n ",
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text


async def test_rejection_mail_preview_route(
    app_client: AsyncClient, app_auth_headers, monkeypatch
):
    """Podgląd w oknie odrzucenia: kto dostanie mail i z jaką treścią."""
    from unittest.mock import AsyncMock

    import app.services.rejection_email_scheduler as scheduler

    monkeypatch.setattr(scheduler, "sender_has_mailbox", AsyncMock(return_value=True))
    job, _ = await _seed_job()
    at_client, early = await _seed_candidate(), await _seed_candidate()
    verified = await _seed_candidate()
    await _seed_stage(at_client, job, "client_interview")
    await _seed_stage(early, job, "screening")
    await _seed_stage(verified, job, "verified")

    r = await app_client.post(
        "/api/rejection-emails/preview",
        json={"job_id": job, "candidate_ids": [at_client, early, verified]},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [
        (p["candidate_id"], p["skip_reason"], p["text_kind"]) for p in body["people"]
    ] == [
        (at_client, None, "after_client"),
        (early, "not_client_visible", None),
        # 17.10.2026 (D1): po rozmowie z nami mail też wychodzi.
        (verified, None, "before_client"),
    ]
    assert body["people"][0]["to_email"].endswith("@example.com")
    assert body["people"][1]["to_email"] is None  # przed weryfikacją — bez adresu
    assert body["subject"].startswith("Informacja zwrotna — Int-Job-")
    assert body["body"].startswith("Cześć Int,")
    assert [s["text_kind"] for s in body["samples"]] == ["after_client", "before_client"]

    missing = await app_client.post(
        "/api/rejection-emails/preview",
        json={"job_id": 2_000_000_000, "candidate_ids": [at_client]},
        headers=app_auth_headers,
    )
    assert missing.status_code == 404, missing.text

    too_big = await app_client.post(
        "/api/rejection-emails/preview",
        json={"job_id": job, "candidate_ids": [3_000_000_000]},
        headers=app_auth_headers,
    )
    assert too_big.status_code == 422, too_big.text


async def test_failed_post_commit_side_effect_does_not_turn_the_move_into_500(
    app_client: AsyncClient, app_auth_headers, monkeypatch
):
    """Audyt 25.09.2026: efekt uboczny po commicie, który zawiódł (tu błąd SQL
    przy przeliczeniu ryzyka), robił `db.rollback()` na sesji żądania —
    `current_user` i `stage` wygasały, a odpowiedź czytała je → MissingGreenlet
    → 500 po zapisanym ruchu. Teraz ruch zwraca 200 z danymi etapu."""
    from sqlalchemy import select, text

    import app.services.candidate_risk as candidate_risk
    from app.models.recruitment_pipeline import CandidateStage

    async def boom(db, candidate_id):  # noqa: ARG001
        await db.execute(text("SELECT 1 / 0"))

    monkeypatch.setattr(candidate_risk, "on_candidate_stage_change", boom)

    cand, (job, _) = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "new")
    r = await app_client.post(
        MOVE,
        json={"candidate_id": cand, "job_id": job, "stage": "screening"},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["candidate_id"] == cand and body["stage"] == "screening"

    async with AsyncSessionLocal() as db:
        latest = await db.scalar(
            select(CandidateStage)
            .where(CandidateStage.candidate_id == cand, CandidateStage.job_id == job)
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
    assert latest is not None and latest.stage.value == "screening"
