"""Wynik zamkniętej rekrutacji na liście (prośba DL 26.11.2026, decyzja Artura).

„Wygrana” w „Zamkniętych projektach” klienta to ta sama reguła co hit ratio
(`hit_ratio_closures.closure_group`): powód „nie liczy się” wygrywa, potem
zatrudnienie od nas w bieżącym otwarciu, potem brak powodu → „bez wyniku”,
reszta → przegrana. Zielony wiersz musi zgadzać się z Ligą DL.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.dialects import postgresql

from app.models.job import JobCloseReason
from app.services.hit_ratio_closures import closure_group
from app.services.job_outcome import JOB_OUTCOMES, job_outcome_expr
from app.services.metric_definitions import HIT_RATIO_NEUTRAL_CLOSE_REASONS

# ── Bez bazy ─────────────────────────────────────────────────────────────────


def _sql() -> str:
    return str(
        job_outcome_expr().compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_outcome_values_match_hit_ratio_groups() -> None:
    assert JOB_OUTCOMES == ("won", "lost", "neutral", "unreviewed")
    groups = {
        closure_group(reason, hired)
        for reason in [*JobCloseReason, None]
        for hired in (True, False)
    }
    assert groups == set(JOB_OUTCOMES)


def test_expression_checks_neutral_before_hire_and_skips_open_jobs() -> None:
    sql = _sql()
    # Niezamknięta rekrutacja nie ma wyniku.
    assert sql.index("jobs.status != 'closed'") < sql.index("'neutral'")
    # Neutralny powód wygrywa z zatrudnieniem — jak `closure_group`.
    assert sql.index("'neutral'") < sql.index("'won'") < sql.index("'unreviewed'")
    for value in HIT_RATIO_NEUTRAL_CLOSE_REASONS:
        assert f"'{value}'" in sql
    # Zatrudnienie tylko w bieżącym otwarciu i bez wykluczonego placementu.
    assert "jobs.cycle_started_at IS NULL" in sql
    assert "placement_exclusions" in sql
    assert "'hired'" in sql
    # Bez powodu i „Inny” → bez wyniku, nie przegrana.
    assert "jobs.close_reason IS NULL" in sql
    assert "'other'" not in sql
    assert sql.rstrip().endswith("ELSE 'lost' END")


# ── Na bazie (CI) ────────────────────────────────────────────────────────────


async def _seed(token: str) -> tuple[int, dict[str, int], list[int]]:
    """Klient z rekrutacjami na każdy przypadek reguły."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.placement_exclusion import PlacementExclusion
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Outcome-{token}")
        db.add(client)
        await db.flush()
        cases = {
            "hired_no_reason": (JobStatus.closed, None, now - timedelta(days=60)),
            "filled_without_hire": (
                JobStatus.closed,
                JobCloseReason.filled_by_us,
                None,
            ),
            "paused_with_hire": (JobStatus.closed, JobCloseReason.paused, None),
            "competitor": (JobStatus.closed, JobCloseReason.competitor, None),
            "no_reason": (JobStatus.closed, None, None),
            "other": (JobStatus.closed, JobCloseReason.other, None),
            "hire_before_reopen": (JobStatus.closed, None, None),
            "excluded_hire": (JobStatus.closed, None, None),
            "open_with_hire": (JobStatus.published, None, None),
        }
        jobs: dict[str, int] = {}
        for key, (status, reason, _) in cases.items():
            job = Job(
                title=f"{token}-{key}",
                client_id=client.id,
                status=status,
                close_reason=reason,
                closed_at=now if status == JobStatus.closed else None,
                cycle_started_at=now if key == "hire_before_reopen" else None,
            )
            db.add(job)
            await db.flush()
            jobs[key] = job.id

        candidate_ids: list[int] = []
        for key in (
            "hired_no_reason",
            "paused_with_hire",
            "hire_before_reopen",
            "excluded_hire",
            "open_with_hire",
        ):
            candidate = Candidate(name="Zatrudniony", lastname=f"{key} {token}")
            db.add(candidate)
            await db.flush()
            candidate_ids.append(candidate.id)
            db.add(
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=jobs[key],
                    stage=PipelineStage.hired,
                    moved_at=now - timedelta(days=30),
                )
            )
            if key == "excluded_hire":
                db.add(
                    PlacementExclusion(
                        candidate_id=candidate.id, job_id=jobs[key], reason="manual"
                    )
                )
        await db.commit()
        return client.id, jobs, candidate_ids


async def _cleanup(client_id: int, candidate_ids: list[int]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job
    from app.models.placement_exclusion import PlacementExclusion
    from app.models.recruitment_pipeline import CandidateStage

    async with AsyncSessionLocal() as db:
        # Etapy i wykluczenia przed rekrutacjami: klucz z `candidate_stages`
        # nie ma kaskady.
        await db.execute(
            delete(CandidateStage).where(CandidateStage.candidate_id.in_(candidate_ids))
        )
        await db.execute(
            delete(PlacementExclusion).where(
                PlacementExclusion.candidate_id.in_(candidate_ids)
            )
        )
        await db.execute(delete(Job).where(Job.client_id == client_id))
        await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        await db.execute(delete(Client).where(Client.id == client_id))
        await db.commit()


@pytest.mark.asyncio
async def test_rows_filter_and_counts_follow_hit_ratio_rule(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    token = uuid.uuid4().hex[:8]
    client_id, jobs, candidate_ids = await _seed(token)
    try:
        response = await app_client.get(
            f"/api/jobs?client_id={client_id}&page_size=100&outcome_counts=true",
            headers=app_auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        rows = {row["id"]: row for row in body["items"]}
        outcome = {key: rows[job_id]["outcome"] for key, job_id in jobs.items()}
        assert outcome == {
            "hired_no_reason": "won",
            "filled_without_hire": "lost",
            "paused_with_hire": "neutral",
            "competitor": "lost",
            "no_reason": "unreviewed",
            "other": "unreviewed",
            "hire_before_reopen": "unreviewed",
            "excluded_hire": "unreviewed",
            "open_with_hire": None,
        }
        won_row = rows[jobs["hired_no_reason"]]
        assert won_row["hired_names"] == [f"Zatrudniony hired_no_reason {token}"]
        # Imiona tylko przy wygranej.
        assert rows[jobs["paused_with_hire"]]["hired_names"] == []
        assert body["outcome_counts"] == {
            "won": 1,
            "lost": 2,
            "neutral": 1,
            "unreviewed": 4,
        }

        async def ids(query: str) -> set[int]:
            r = await app_client.get(
                f"/api/jobs?client_id={client_id}&page_size=100&{query}",
                headers=app_auth_headers,
            )
            assert r.status_code == 200, r.text
            return {row["id"] for row in r.json()["items"]}

        assert await ids("outcome=won") == {jobs["hired_no_reason"]}
        assert await ids("outcome=won&outcome=neutral") == {
            jobs["hired_no_reason"],
            jobs["paused_with_hire"],
        }
        # Liczniki chipów nie zależą od wybranego chipa.
        r = await app_client.get(
            f"/api/jobs?client_id={client_id}&outcome=won&outcome_counts=true",
            headers=app_auth_headers,
        )
        assert r.json()["outcome_counts"]["unreviewed"] == 4
        assert r.json()["total"] == 1
        # Bez prośby o liczniki odpowiedź ich nie ma.
        assert (
            "outcome_counts"
            not in (
                await app_client.get(
                    f"/api/jobs?client_id={client_id}", headers=app_auth_headers
                )
            ).json()
        )

        unknown = await app_client.get(
            "/api/jobs?outcome=wygrana", headers=app_auth_headers
        )
        assert unknown.status_code == 422, unknown.text
        assert "wygrana" in unknown.text
    finally:
        await _cleanup(client_id, candidate_ids)
