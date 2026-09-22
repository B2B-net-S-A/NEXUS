"""GET /api/insights/delivery-leads/portfolio — portfel DL per klient.

Pod ochroną:

1. **Niezmiennik sum**: suma wierszy klientów = nagłówek DL = wiersz
   ``GET /api/insights/delivery-leads`` dla tego samego okna. Bez tego ekran
   z rankingiem i portfelem obok siebie pokazuje dwie różne liczby pod jedną
   etykietą.
2. Alert ``hit_ratio_drop`` (spadek ≥ 20 pp przy ≥ 3 zapytaniach w obu oknach).
3. Zerowy mianownik → ``None``, nigdy 0.0.
4. ``unattributed`` obok rankingu, nigdy w czyimś wierszu.
5. ``open_jobs`` = opublikowane teraz; seria miesięczna ma 6 punktów.

Rok 1994 jest w testach niezajęty (baza testowa nie jest czyszczona).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contact import Contact
from app.models.job import Job, JobStatus, RecruitmentType, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole

RANKING_URL = "/api/insights/delivery-leads"
PORTFOLIO_URL = "/api/insights/delivery-leads/portfolio"
PARAMS = {"period": "month", "anchor": "1994-06-15"}


def _utc(month: int, day: int) -> datetime:
    return datetime(1994, month, day, 12, tzinfo=timezone.utc)


async def _seed_user(role: UserRole, label: str) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"insdlp-{label}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!DlPort"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            name=f"DLP {label} {unique}",
            password_hash=hash_password(password),
            role=role,
            is_active=True,
            profile_completed=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_client(label: str, head_dl_id: int | None = None) -> int:
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"DlPort-{label}-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.flush()
        if head_dl_id is not None:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=head_dl_id, client_id=cli.id, is_head=True
                )
            )
        await db.commit()
        return cli.id


async def _seed_contact(client_id: int, name: str) -> int:
    async with AsyncSessionLocal() as db:
        contact = Contact(client_id=client_id, name=name, position="CTO")
        db.add(contact)
        await db.commit()
        await db.refresh(contact)
        return contact.id


async def _seed_job(
    *,
    client_id: int,
    dl_id: int | None,
    created_at: datetime,
    headcount: int = 1,
    job_status: JobStatus = JobStatus.closed,
    hm_id: int | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"DlPort {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=job_status,
            remote_policy=RemotePolicy.hybrid,
            recruitment_type=RecruitmentType.body_leasing,
            client_id=client_id,
            delivery_lead_id=dl_id,
            headcount=headcount,
            created_at=created_at,
            hiring_manager_contact_id=hm_id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_hired(job_id: int, moved_at: datetime) -> None:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=f"Dlp-{uuid.uuid4().hex[:4]}",
            lastname=f"Port-{uuid.uuid4().hex[:4]}",
            email=f"dlport-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(cand)
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job_id,
                stage=PipelineStage.hired,
                moved_at=moved_at,
            )
        )
        await db.commit()


async def _flush_cache() -> None:
    for prefix in ("insights:delivery-leads:", "insights:delivery-leads-portfolio:"):
        await cache_invalidate(prefix)


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


@pytest_asyncio.fixture
async def seeded() -> dict:
    """Dwóch DL, pięciu klientów, jedna oferta bez DL (``unattributed``)."""
    dl_a, _, _ = await _seed_user(UserRole.delivery_lead, "a")
    dl_b, _, _ = await _seed_user(UserRole.delivery_lead, "b")

    # DL A / klient X: maj 3/4 → czerwiec 1/4 = spadek o 50 pp → alert.
    client_x = await _seed_client("x")
    hm_main = await _seed_contact(client_x, "Anna Hiring")
    hm_other = await _seed_contact(client_x, "Beata Rzadka")
    may_jobs = [
        await _seed_job(client_id=client_x, dl_id=dl_a, created_at=_utc(5, 3 + i))
        for i in range(4)
    ]
    for job_id in may_jobs[:3]:
        await _seed_hired(job_id, _utc(5, 20))
    june_x = [
        await _seed_job(
            client_id=client_x,
            dl_id=dl_a,
            created_at=_utc(6, 2 + i),
            headcount=2 if i == 0 else 1,
            hm_id=hm_main if i < 3 else hm_other,
        )
        for i in range(4)
    ]
    await _seed_hired(june_x[0], _utc(6, 20))

    # DL A / klient Y: jedna oferta opublikowana, jeden placement, brak maja.
    client_y = await _seed_client("y")
    job_y = await _seed_job(
        client_id=client_y,
        dl_id=dl_a,
        created_at=_utc(6, 5),
        job_status=JobStatus.published,
    )
    await _seed_hired(job_y, _utc(6, 25))

    # DL B jako główny opiekun klienta Z (oferta bez własnego DL) — 1 zapytanie,
    # 0 placementów → hit ratio 0.0 (policzone, wyszło zero).
    client_z = await _seed_client("z", head_dl_id=dl_b)
    await _seed_job(client_id=client_z, dl_id=None, created_at=_utc(6, 7))

    # DL B / klient W: oferta z kwietnia, placement w czerwcu → 0 zapytań
    # w oknie, więc hit ratio = None (nie ma czego dzielić).
    client_w = await _seed_client("w")
    job_w = await _seed_job(client_id=client_w, dl_id=dl_b, created_at=_utc(4, 10))
    await _seed_hired(job_w, _utc(6, 12))

    # Oferta bez DL i bez głównego opiekuna → unattributed.
    client_u = await _seed_client("u")
    job_u = await _seed_job(client_id=client_u, dl_id=None, created_at=_utc(6, 9))
    await _seed_hired(job_u, _utc(6, 21))

    return {
        "dl_a": dl_a,
        "dl_b": dl_b,
        "client_x": client_x,
        "client_y": client_y,
        "client_z": client_z,
        "client_w": client_w,
        "hm_main": hm_main,
    }


async def _get(client: AsyncClient, url: str, headers: dict) -> dict:
    resp = await client.get(url, headers=headers, params=PARAMS)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _lead(body: dict, dl_id: int) -> dict:
    matches = [lead for lead in body["leads"] if lead["dl_id"] == dl_id]
    assert matches, f"DL {dl_id} nieobecny w portfelu"
    return matches[0]


def _client(lead: dict, client_id: int) -> dict:
    matches = [c for c in lead["clients"] if c["client_id"] == client_id]
    assert matches, f"klient {client_id} nieobecny u DL {lead['dl_id']}"
    return matches[0]


@pytest.mark.asyncio
async def test_rows_sum_to_header_and_header_matches_the_ranking(
    fx_client: AsyncClient, seeded: dict
):
    await _flush_cache()
    _, email, password = await _seed_user(UserRole.recruiter, "viewer")
    headers = await _login(fx_client, email, password)

    portfolio = await _get(fx_client, PORTFOLIO_URL, headers)
    ranking = await _get(fx_client, RANKING_URL, headers)
    assert portfolio["period"] == ranking["period"]
    assert portfolio["hit_ratio_target_pct"] == 30

    ranking_by_dl = {row["user_id"]: row for row in ranking["per_dl"]}
    # Niezmiennik dla KAŻDEGO DL w portfelu, nie tylko zasianych — inaczej
    # rozjazd u kogoś spoza fixture przeszedłby niezauważony.
    for lead in portfolio["leads"]:
        rows = lead["clients"]
        assert lead["requests"] == sum(r["requests"] for r in rows)
        assert lead["placements"] == sum(r["placements"] for r in rows)
        assert lead["vacancies"] == sum(r["vacancies"] for r in rows)

        rank = ranking_by_dl[lead["dl_id"]]
        assert lead["requests"] == rank["total_requests"]
        assert lead["vacancies"] == rank["total_vacancies"]
        assert lead["placements"] == rank["placements"]
        assert lead["hit_ratio"] == rank["hit_ratio"]
        assert lead["fill_rate"] == rank["fill_rate"]
        assert lead["open_requests"] == rank["open_requests"]
        assert lead["target_achieved"] == rank["target_achieved"]
    assert {lead["dl_id"] for lead in portfolio["leads"]} == set(ranking_by_dl)

    lead_a = _lead(portfolio, seeded["dl_a"])
    assert (lead_a["requests"], lead_a["placements"], lead_a["vacancies"]) == (5, 2, 6)
    assert lead_a["hit_ratio"] == 40.0

    assert portfolio["unattributed"] == {
        "requests": ranking["unattributed"]["requests"],
        "placements": ranking["unattributed"]["placements"],
    }
    assert portfolio["unattributed"]["requests"] >= 1
    assert portfolio["unattributed"]["placements"] >= 1


@pytest.mark.asyncio
async def test_hit_ratio_drop_alert_and_previous_window(
    fx_client: AsyncClient, seeded: dict
):
    await _flush_cache()
    _, email, password = await _seed_user(UserRole.sourcer, "alert")
    headers = await _login(fx_client, email, password)
    body = await _get(fx_client, PORTFOLIO_URL, headers)

    row_x = _client(_lead(body, seeded["dl_a"]), seeded["client_x"])
    assert row_x["requests"] == 4
    assert row_x["vacancies"] == 5
    assert row_x["placements"] == 1
    assert row_x["hit_ratio"] == 25.0
    assert row_x["fill_rate"] == 20.0
    assert row_x["prev_hit_ratio"] == 75.0
    assert row_x["delta_pp"] == -50.0
    assert row_x["alert"] == "hit_ratio_drop"

    # Brak poprzedniego okna → brak porównania, nie „spadek z zera".
    row_y = _client(_lead(body, seeded["dl_a"]), seeded["client_y"])
    assert row_y["hit_ratio"] == 100.0
    assert row_y["prev_hit_ratio"] is None
    assert row_y["delta_pp"] is None
    assert row_y["alert"] is None

    # Kolejność: placementy malejąco (X i Y po 1 → zapytania malejąco).
    lead_a = _lead(body, seeded["dl_a"])
    assert [c["client_id"] for c in lead_a["clients"]] == [
        seeded["client_x"],
        seeded["client_y"],
    ]


@pytest.mark.asyncio
async def test_zero_denominators_are_none_and_head_dl_attribution(
    fx_client: AsyncClient, seeded: dict
):
    await _flush_cache()
    _, email, password = await _seed_user(UserRole.admin, "zero")
    headers = await _login(fx_client, email, password)
    body = await _get(fx_client, PORTFOLIO_URL, headers)

    lead_b = _lead(body, seeded["dl_b"])
    row_z = _client(lead_b, seeded["client_z"])
    # Oferta bez własnego DL trafia do głównego opiekuna klienta.
    assert row_z["requests"] == 1
    assert row_z["placements"] == 0
    assert row_z["hit_ratio"] == 0.0

    row_w = _client(lead_b, seeded["client_w"])
    assert row_w["requests"] == 0
    assert row_w["placements"] == 1
    assert row_w["hit_ratio"] is None
    assert row_w["fill_rate"] is None

    assert lead_b["requests"] == 1
    assert lead_b["placements"] == 1
    assert lead_b["hit_ratio"] == 100.0


@pytest.mark.asyncio
async def test_open_jobs_monthly_series_and_top_hiring_manager(
    fx_client: AsyncClient, seeded: dict
):
    await _flush_cache()
    _, email, password = await _seed_user(UserRole.admin, "series")
    headers = await _login(fx_client, email, password)
    body = await _get(fx_client, PORTFOLIO_URL, headers)

    lead_a = _lead(body, seeded["dl_a"])
    row_x = _client(lead_a, seeded["client_x"])
    row_y = _client(lead_a, seeded["client_y"])

    # Oferty X są zamknięte, oferta Y opublikowana.
    assert row_x["open_jobs"] == 0
    assert row_y["open_jobs"] == 1
    assert lead_a["open_requests"] == 1

    series = row_x["monthly_placements"]
    assert [p["month"] for p in series] == [
        "1994-01",
        "1994-02",
        "1994-03",
        "1994-04",
        "1994-05",
        "1994-06",
    ]
    assert [p["placements"] for p in series] == [0, 0, 0, 0, 3, 1]
    assert len(row_y["monthly_placements"]) == 6

    hm = row_x["top_hiring_manager"]
    assert hm == {
        "contact_id": seeded["hm_main"],
        "name": "Anna Hiring",
        "title": "CTO",
        "jobs": 3,
    }
    assert row_y["top_hiring_manager"] is None


@pytest.mark.asyncio
async def test_portfolio_requires_authentication(fx_client: AsyncClient):
    resp = await fx_client.get(PORTFOLIO_URL, params=PARAMS)
    assert resp.status_code in (401, 403)
