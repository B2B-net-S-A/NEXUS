"""Aplikacje z Pracuj.pl → rekrutacja ogłoszenia (decyzja Artura 23.11.2026, wariant A).

Kopia produkcji z 22.11: 8 292 zdarzeń źródła „Pracuj.pl” z 30 dni, żadne
z rekrutacją. Strefa pracodawcy zna tylko swój numer ogłoszenia, a trzy aktywne
ogłoszenia miały ten sam tytuł, więc ogłoszenie z rekrutacją łączy Delivery
Lead (``services/pracuj_ads``), a tytuł tylko podpowiada.
"""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.schemas.candidate_source_event import PortalApplicationCreate
from app.services import portal_application, pracuj_ad_schema, pracuj_ads
from tests.test_pipeline_membership_gate import (
    _seed_candidate,
    _seed_job,
    _seed_recruiter,
)

BACKEND = Path(__file__).resolve().parents[1]


def _strefa_id() -> str:
    """Baza testów jest wspólna: numer ogłoszenia musi być unikalny."""
    return str(random.randint(10**8, 10**10))


# ── bez bazy ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("title", "normalized"),
    [
        ("Tester Manualny (k/m/x)", "tester manualny"),
        ("Tester Manualny (ZOB-3241)", "tester manualny"),
        ("Nordea: IT Developer - Senior (42961)", "it developer - senior"),
        ("Programista Python​ (m/k)", "programista python"),
        ("Senior IT Project Manager (K/M/N)", "senior it project manager"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_title(title, normalized):
    assert pracuj_ads.normalize_title(title) == normalized


@pytest.mark.parametrize(
    ("ad", "job", "expected"),
    [
        ("Tester Manualny (k/m/x)", "Tester Manualny (ZOB-3241)", True),
        ("Tester Manualny (k/m/x)", "Tester Manualny x4", True),
        ("Młodszy Kierownik Projektu (k/m/x)", "Młodszy Kierownik Projektu", True),
        ("IT Developer - Senior (k/m/x)", "Nordea: IT Developer - Senior (42961)", True),
        # Krótszy tytuł nie podpowiada dłuższego, który znaczy co innego.
        ("Tester Automatyczny (k/m/x)", "Tester", False),
        ("Młodszy Kierownik Projektu (k/m/x)", "Starszy Kierownik Projektu", False),
        ("", "Tester", False),
    ],
)
def test_suggests_is_only_close_titles(ad, job, expected):
    assert pracuj_ads.suggests(ad, job) is expected


def test_strefa_id_is_digits_only():
    assert pracuj_ads.valid_strefa_id("8819139")
    for bad in ("", "12", "88191x9", "../1", "8819139 "):
        assert not pracuj_ads.valid_strefa_id(bad)


def test_portal_application_accepts_pracuj():
    payload = PortalApplicationCreate(portal="pracuj", ad_id="8819139", ad_title="X")
    assert payload.portal == portal_application.PRACUJ


def test_schema_is_idempotent_and_mirrored_in_entrypoint():
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "from app.services import pracuj_ad_schema" in entrypoint
    assert "*_PRACUJ_ADS_DDL," in entrypoint
    for statement in pracuj_ad_schema.ALL_DDL:
        assert "IF NOT EXISTS" in re.sub(r"\s+", " ", statement), statement
    migration = (BACKEND / "alembic" / "versions" / "0754_pracuj_ads.py").read_text(
        encoding="utf-8"
    )
    assert "schema.ALL_DDL" in migration


def test_oauth_scope_for_ad_list():
    from app.services.oauth_route_scopes import OAUTH_ROUTE_RESOURCES

    assert OAUTH_ROUTE_RESOURCES["/api/portal-ads/pracuj"] == {"PUT": ("candidate",)}


# ── z bazą (CI) ─────────────────────────────────────────────────────────


async def _sync(*ads: pracuj_ads.AdIn) -> None:
    async with AsyncSessionLocal() as db:
        await pracuj_ads.upsert_ads(db, ads)
        await db.commit()


async def _apply(candidate_id: int, strefa_id: str, *, days_ago: int = 0):
    async with AsyncSessionLocal() as db:
        result = await portal_application.place_application(
            db,
            candidate_id=candidate_id,
            portal="pracuj",
            ad_id=strefa_id,
            ad_title="Tester Manualny (k/m/x)",
            applied_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
        await db.commit()
        return result


async def _stage(candidate_id: int, job_id: int):
    from app.models.recruitment_pipeline import CandidateStage

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
        )


async def _dl_job(app_client):
    from app.models.job import Job

    headers, uid = await _seed_recruiter(app_client, role="delivery_lead")
    job_id, _ = await _seed_job()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.delivery_lead_id = uid
        job.title = "Tester Manualny (ZOB-3241)"
        await db.commit()
    return headers, uid, job_id


@pytest.mark.asyncio
async def test_application_before_pairing_waits_then_lands_in_new(app_client):
    from app.models.job import Job
    from app.models.user import User

    _, uid, job_id = await _dl_job(app_client)
    sid = _strefa_id()
    await _sync(pracuj_ads.AdIn(sid, "Tester Manualny (k/m/x)", 20))
    cand = await _seed_candidate()

    first = await _apply(cand, sid, days_ago=2)
    assert first.outcome == "no_job"
    assert await _stage(cand, job_id) is None

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        user = await db.get(User, uid)
        result = await pracuj_ads.pair(db, job=job, strefa_id=sid, user=user)
        await db.commit()
    assert (result.added, result.already, result.skipped) == (1, 0, 0)
    stage = await _stage(cand, job_id)
    assert stage is not None and stage.stage.value == "new"

    # Ponowne połączenie niczego nie dubluje.
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        user = await db.get(User, uid)
        again = await pracuj_ads.pair(db, job=job, strefa_id=sid, user=user)
        await db.commit()
    assert (again.added, again.already) == (0, 1)


@pytest.mark.asyncio
async def test_application_after_pairing_goes_straight_to_job(app_client):
    from app.models.candidate_source_event import CandidateSourceEvent
    from app.models.job import Job
    from app.models.user import User

    _, uid, job_id = await _dl_job(app_client)
    sid = _strefa_id()
    await _sync(pracuj_ads.AdIn(sid, "Tester Manualny (k/m/x)"))
    async with AsyncSessionLocal() as db:
        await pracuj_ads.pair(
            db, job=await db.get(Job, job_id), strefa_id=sid, user=await db.get(User, uid)
        )
        await db.commit()
    cand = await _seed_candidate()

    result = await _apply(cand, sid)

    assert (result.outcome, result.job_id) == ("added", job_id)
    async with AsyncSessionLocal() as db:
        event = await db.scalar(
            select(CandidateSourceEvent).where(
                CandidateSourceEvent.candidate_id == cand,
                CandidateSourceEvent.job_id == job_id,
            )
        )
    assert event is not None and event.utm_source == "pracuj"
    assert event.note.startswith("Aplikacja przez Pracuj.pl")


@pytest.mark.asyncio
async def test_ad_paired_elsewhere_is_refused(app_client):
    from app.models.job import Job
    from app.models.user import User

    _, uid, job_a = await _dl_job(app_client)
    job_b, _ = await _seed_job()
    sid = _strefa_id()
    await _sync(pracuj_ads.AdIn(sid, "Tester Manualny (k/m/x)"))
    async with AsyncSessionLocal() as db:
        user = await db.get(User, uid)
        await pracuj_ads.pair(db, job=await db.get(Job, job_a), strefa_id=sid, user=user)
        await db.commit()
    async with AsyncSessionLocal() as db:
        user = await db.get(User, uid)
        with pytest.raises(pracuj_ads.AdTaken) as taken:
            await pracuj_ads.pair(
                db, job=await db.get(Job, job_b), strefa_id=sid, user=user
            )
    assert taken.value.job_id == job_a


@pytest.mark.asyncio
async def test_internal_ad_has_no_job_and_leaves_queue(app_client):
    from app.models.user import User

    _, uid, _job = await _dl_job(app_client)
    sid = _strefa_id()
    await _sync(pracuj_ads.AdIn(sid, "IT Rekruter / IT Rekruterka", 36))
    async with AsyncSessionLocal() as db:
        queue = await pracuj_ads.unpaired_queue(db)
        assert sid in {i["strefa_id"] for i in queue["items"]}
        await pracuj_ads.mark_internal(
            db, strefa_id=sid, user=await db.get(User, uid), internal=True
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        queue = await pracuj_ads.unpaired_queue(db)
        assert sid not in {i["strefa_id"] for i in queue["items"]}
        assert await pracuj_ads.job_for_ad(db, sid) is None


@pytest.mark.asyncio
async def test_pair_route_for_dl_and_refusal_for_recruiter(app_client):
    headers, _uid, job_id = await _dl_job(app_client)
    sid = _strefa_id()
    await _sync(pracuj_ads.AdIn(sid, "Tester Manualny (k/m/x)", 20))
    cand = await _seed_candidate()
    await _apply(cand, sid, days_ago=1)

    panel = await app_client.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)
    assert panel.status_code == 200, panel.text
    options = panel.json()["pracuj_ads"]["options"]
    mine = next(o for o in options if o["strefa_id"] == sid)
    assert mine["suggested"] is True and mine["logged_applications"] == 1

    rec_headers, rec_uid = await _seed_recruiter(app_client)
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.recruiter_id = rec_uid
        await db.commit()
    refused = await app_client.put(
        f"/api/jobs/{job_id}/portal-ad/pracuj-ads/{sid}", headers=rec_headers
    )
    assert refused.status_code == 403

    paired = await app_client.put(
        f"/api/jobs/{job_id}/portal-ad/pracuj-ads/{sid}", headers=headers
    )
    assert paired.status_code == 200, paired.text
    assert paired.json()["added"] == 1
    assert await _stage(cand, job_id) is not None

    unpaired = await app_client.delete(
        f"/api/jobs/{job_id}/portal-ad/pracuj-ads/{sid}", headers=headers
    )
    assert unpaired.status_code == 204
    # Karta zostaje — to już decyzje ludzi.
    assert await _stage(cand, job_id) is not None


@pytest.mark.asyncio
async def test_ad_list_route_only_for_integration(app_client):
    headers, _ = await _seed_recruiter(app_client, role="admin")
    resp = await app_client.put(
        "/api/portal-ads/pracuj",
        json={"ads": [{"strefa_id": _strefa_id(), "title": "X"}]},
        headers=headers,
    )
    assert resp.status_code == 403
