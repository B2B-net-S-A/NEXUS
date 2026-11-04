"""GET /api/insights/recruitment/competence-matrix — kategorie × etapy (dziś).

Pod ochroną: macierz liczy etapy TĄ SAMĄ funkcją co pulpit procesów
(``recruitment_operations``), więc liczba w komórce macierzy i suma liczników
wierszy pulpitu dla tej kategorii muszą się zgadzać.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.competence_category import CompetenceCategory
from app.models.job import Job, JobStatus, RecruitmentType, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import recruitment_operations as ops
from app.services.insights_competence_matrix import STAGES

URL = "/api/insights/recruitment/competence-matrix"


async def _seed_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"inscm-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Matrix"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Matrix {unique}",
                password_hash=hash_password(password),
                role=role,
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def fx_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


async def _add_stages(
    db, job_id: int, stages: list[PipelineStage], base: datetime
) -> None:
    """Jeden kandydat przechodzący przez ``stages`` — liczy się ostatni etap."""
    cand = Candidate(
        name=f"Cm-{uuid.uuid4().hex[:4]}",
        lastname=f"Matrix-{uuid.uuid4().hex[:4]}",
        email=f"cm-{uuid.uuid4().hex[:8]}@example.com",
    )
    db.add(cand)
    await db.flush()
    for i, stage in enumerate(stages):
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job_id,
                stage=stage,
                moved_at=base + timedelta(minutes=i),
            )
        )


@pytest_asyncio.fixture
async def seeded() -> dict:
    unique = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    async with AsyncSessionLocal() as db:
        category = CompetenceCategory(
            slug=f"matrix-{unique}",
            name_pl=f"Macierz {unique}",
            name_en=f"Matrix {unique}",
            description="test",
        )
        client = Client(name=f"Matrix-{unique}")
        db.add_all([category, client])
        await db.flush()

        def job(status: JobStatus) -> Job:
            return Job(
                title=f"Matrix {uuid.uuid4().hex[:6]}",
                location="Warszawa",
                status=status,
                remote_policy=RemotePolicy.hybrid,
                recruitment_type=RecruitmentType.body_leasing,
                client_id=client.id,
                competence_category_id=category.id,
            )

        job_a, job_b, job_closed, job_finished = (
            job(JobStatus.published),
            job(JobStatus.published),
            job(JobStatus.closed),
            job(JobStatus.published),
        )
        # Runda 7 (R7-N9-5): „Zakończony” w NEXUSIE nie jest otwarty, choć
        # status z Traffita zostaje `published`.
        job_finished.work_state = "finished"
        db.add_all([job_a, job_b, job_closed, job_finished])
        await db.flush()

        await _add_stages(db, job_a.id, [PipelineStage.new], now)
        await _add_stages(
            db, job_a.id, [PipelineStage.new, PipelineStage.screening], now
        )
        await _add_stages(db, job_a.id, [PipelineStage.cv_sent], now)
        await _add_stages(
            db, job_a.id, [PipelineStage.cv_sent, PipelineStage.rejected], now
        )
        await _add_stages(db, job_b.id, [PipelineStage.client_interview], now)
        await _add_stages(db, job_b.id, [PipelineStage.acceptance], now)
        await _add_stages(db, job_b.id, [PipelineStage.hired], now)
        # Zamknięta oferta nie wchodzi do macierzy, choćby miała kandydatów.
        await _add_stages(db, job_closed.id, [PipelineStage.new], now)
        await _add_stages(db, job_finished.id, [PipelineStage.new], now)
        # Runda 7 (R7-N9-4): liczniki = kolumny Tablicy — `posting` to „Nowi”,
        # `prep_call` to „Screening”, `negotiation` to „Umowa”.
        await _add_stages(db, job_a.id, [PipelineStage.posting], now)
        await _add_stages(db, job_a.id, [PipelineStage.prep_call], now)
        await _add_stages(db, job_b.id, [PipelineStage.negotiation], now)
        await db.commit()
        return {
            "category_id": category.id,
            "category_name": category.name_pl,
            "job_ids": [job_a.id, job_b.id],
        }


def test_stage_keys_mirror_the_dashboard_counters():
    """Klucze macierzy = liczniki pulpitu, w tej samej kolejności."""
    assert [key for key, _ in STAGES] == list(ops._DASHBOARD_COLUMN_FIELDS.values())


@pytest.mark.asyncio
async def test_matrix_counts_current_stages_of_published_jobs(
    fx_client: AsyncClient, seeded: dict
):
    email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(fx_client, email, password)
    resp = await fx_client.get(URL, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert [s["key"] for s in body["stages"]] == [
        "new",
        "screening",
        "cv_sent",
        "client_interview",
        "acceptance",
    ]
    assert [s["label"] for s in body["stages"]] == [
        "Nowy",
        "Screening",
        "Wysłany do klienta",
        "Rozmowa u klienta",
        "Umowa",
    ]
    assert body["as_of"]

    row = next(
        c for c in body["categories"] if c["category_id"] == seeded["category_id"]
    )
    assert row["name"] == seeded["category_name"]
    assert row["open_jobs"] == 2
    assert row["stage_counts"] == {
        "new": 2,
        "screening": 2,
        "cv_sent": 1,
        "client_interview": 1,
        "acceptance": 2,
    }

    # Sumy = suma wierszy (także „Bez kategorii" — ostatni, jeśli jest).
    assert body["totals"]["open_jobs"] == sum(
        c["open_jobs"] for c in body["categories"]
    )
    for key in row["stage_counts"]:
        assert body["totals"]["stage_counts"][key] == sum(
            c["stage_counts"][key] for c in body["categories"]
        )
    nulls = [i for i, c in enumerate(body["categories"]) if c["category_id"] is None]
    if nulls:
        assert nulls == [len(body["categories"]) - 1]
        assert body["categories"][-1]["name"] == "Bez kategorii"


@pytest.mark.asyncio
async def test_grouped_counts_equal_the_dashboard_row_counts(seeded: dict):
    """Agregat SQL = liczniki wiersza pulpitu z ładowania kandydatów."""
    async with AsyncSessionLocal() as db:
        grouped = await ops.dashboard_stage_counts_by_job(
            db, select(Job.id).where(Job.id.in_(seeded["job_ids"]))
        )
        latest = await ops._load_latest_stages(db, seeded["job_ids"])
    for job_id in seeded["job_ids"]:
        per_row = ops._stage_counts([r for r in latest if r.job_id == job_id])
        assert grouped[job_id] == per_row


@pytest.mark.asyncio
async def test_matrix_requires_authentication(fx_client: AsyncClient):
    resp = await fx_client.get(URL)
    assert resp.status_code in (401, 403)
