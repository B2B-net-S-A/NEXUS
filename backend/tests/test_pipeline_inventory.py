"""Tests for GET /api/admin/pipeline-inventory (M4 plan PR-00).

Read-only anomaly report kontrakt:
- auth: X-Snapshot-Token albo JWT admina; zwykły user → 403, brak auth → 401;
- shape: query_version/totals/summary/checks z count+sample+severity;
- fixtures wybranych klas anomalii są wykrywane;
- endpoint NICZEGO nie mutuje (row count przed == po);
- sample nie zawiera PII (tylko identyfikatory numeryczne / zewnętrzne ID)
  i respektuje SAMPLE_LIMIT.

Uses in-process `app_client` / `app_auth_headers` fixtures (real postgres in CI).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

URL = "/api/admin/pipeline-inventory"


async def _seed_candidate() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Inv",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"inv-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job(status_value: str = "published") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"InvClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j = Job(
            title=f"Inv-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus(status_value),
            client_id=cli.id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _seed_stage(
    candidate_id: int,
    job_id: int,
    stage_value: str,
    *,
    moved_at: datetime | None = None,
    verification_status: str = "active",
) -> int:
    from app.core.database import AsyncSessionLocal
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


async def _stage_rows_count() -> int:
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return (
            await db.execute(text("SELECT COUNT(*) FROM candidate_stages"))
        ).scalar_one()


def _check(report: dict, key: str) -> dict:
    matches = [c for c in report["checks"] if c["key"] == key]
    assert matches, f"check {key!r} missing from report"
    return matches[0]


def _sample_pairs(check: dict) -> set[tuple[int, int]]:
    return {
        (row["candidate_id"], row["job_id"])
        for row in check["sample"]
        if "candidate_id" in row and "job_id" in row
    }


# ── Auth ─────────────────────────────────────────────────────────────────────


async def test_inventory_requires_auth(app_client: AsyncClient):
    r = await app_client.get(URL)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_inventory_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(settings, "SNAPSHOT_TOKEN", "inventory-good-token")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.get(URL, headers={"X-Snapshot-Token": "wrong"})
    assert r.status_code == 401


async def test_inventory_rejects_non_admin(app_client: AsyncClient):
    """Zwykły user (viewer) z ważnym JWT dostaje 403 — raport jest admin-only."""
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    email = f"inv-viewer-{uuid.uuid4().hex[:8]}@example.com"
    password = f"V13wer_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Inv Viewer",
                role=UserRole.user,
                is_active=True,
            )
        )
        await db.commit()

    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    r = await app_client.get(URL, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


# ── Shape + anomaly fixtures + read-only guarantee ───────────────────────────


async def test_inventory_shape_detects_anomalies_and_does_not_mutate(
    app_client: AsyncClient, app_auth_headers: dict
):
    now = datetime.now(timezone.utc)

    # 1) pending_not_current — pending na starszym wierszu, nowszy istnieje.
    cand_a, job_a = await _seed_candidate(), await _seed_job()
    await _seed_stage(
        cand_a,
        job_a,
        "verified",
        moved_at=now - timedelta(days=2),
        verification_status="pending",
    )
    await _seed_stage(cand_a, job_a, "interview", moved_at=now - timedelta(days=1))

    # 2) hired_no_contract + terminal_then_active — hired, potem aktywny etap,
    #    zero kontraktów dla kandydata.
    cand_b, job_b = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand_b, job_b, "hired", moved_at=now - timedelta(days=3))
    await _seed_stage(cand_b, job_b, "interview", moved_at=now - timedelta(days=1))

    # 3) duplicate_latest_ties — dwa wiersze z identycznym MAX(moved_at).
    cand_c, job_c = await _seed_candidate(), await _seed_job()
    tie = now - timedelta(days=1)
    await _seed_stage(cand_c, job_c, "new", moved_at=tie)
    await _seed_stage(cand_c, job_c, "screening", moved_at=tie)

    # 4) latest_time_vs_id_mismatch — backdated wiersz z wyższym id.
    cand_d, job_d = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand_d, job_d, "screening", moved_at=now - timedelta(days=1))
    await _seed_stage(cand_d, job_d, "new", moved_at=now - timedelta(days=10))

    # 5) stale_cards_over_90d — aktywna karta sprzed 120 dni na otwartym jobie.
    cand_e, job_e = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand_e, job_e, "screening", moved_at=now - timedelta(days=120))

    rows_before = await _stage_rows_count()
    r = await app_client.get(URL, headers=app_auth_headers)
    assert r.status_code == 200, r.text
    report = r.json()
    assert await _stage_rows_count() == rows_before, "endpoint zmutował dane!"

    # Shape
    assert report["query_version"].startswith("m4-pr00")
    assert report["auth_mode"] == "jwt"
    assert report["sample_limit"] == 20
    assert set(report["summary"]) == {
        "checks_total",
        "checks_failed",
        "anomalies_p0",
        "anomalies_p1",
        "anomalies_p2",
    }
    assert report["summary"]["checks_failed"] == 0, [
        c for c in report["checks"] if c.get("error")
    ]
    totals = report["totals"]
    assert totals["stage_rows"] >= 9
    assert totals["pairs"] >= 5
    for check in report["checks"]:
        assert check["severity"] in {"P0", "P1", "P2"}
        assert isinstance(check["count"], int)
        assert len(check["sample"]) <= report["sample_limit"]
        assert check["elapsed_ms"] >= 0
        # Anty-PII: sample nigdy nie zawiera pól tekstowych typu
        # name/email/subject/body — wyłącznie identyfikatory.
        for row in check["sample"]:
            for field in row:
                assert field in {
                    "candidate_id",
                    "job_id",
                    "stage_id",
                    "contract_id",
                    "scheduled_email_id",
                    "candidate_stage_cv_id",
                    "tied_rows",
                    "live_contracts",
                    "occurrences",
                    "external_source",
                    "external_id",
                }, f"nieoczekiwane pole {field!r} w sample {check['key']}"

    # Anomaly detection
    assert (cand_a, job_a) in _sample_pairs(_check(report, "pending_not_current"))
    assert (cand_b, job_b) in _sample_pairs(_check(report, "hired_no_contract"))
    assert (cand_b, job_b) in _sample_pairs(_check(report, "terminal_then_active"))
    assert (cand_c, job_c) in _sample_pairs(_check(report, "duplicate_latest_ties"))
    assert (cand_d, job_d) in _sample_pairs(
        _check(report, "latest_time_vs_id_mismatch")
    )
    assert (cand_e, job_e) in _sample_pairs(_check(report, "stale_cards_over_90d"))

    # Czysta para (tylko aktywne etapy, bez anomalii czasowych) nie jest
    # raportowana w klasach P0.
    assert (cand_e, job_e) not in _sample_pairs(_check(report, "pending_not_current"))
    assert (cand_a, job_a) not in _sample_pairs(_check(report, "hired_no_contract"))


async def test_inventory_is_repeatable(app_client: AsyncClient, app_auth_headers):
    """Dwa kolejne wywołania zwracają tę samą wersję zapytań i te same countery
    (brak mutacji + deterministyczne definicje)."""
    r1 = await app_client.get(URL, headers=app_auth_headers)
    r2 = await app_client.get(URL, headers=app_auth_headers)
    assert r1.status_code == 200 and r2.status_code == 200
    a, b = r1.json(), r2.json()
    assert a["query_version"] == b["query_version"]
    counts_a = {c["key"]: c["count"] for c in a["checks"]}
    counts_b = {c["key"]: c["count"] for c in b["checks"]}
    assert counts_a == counts_b
