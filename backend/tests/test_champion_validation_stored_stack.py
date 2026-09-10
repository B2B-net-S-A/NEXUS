"""Validation checks the Champion stack as stored, never a resurrected one.

Profiles saved under #1477 carry MUST/NICE entries the old normaliser set
aside in `intake.unresolved`. `validation()` re-normalises the profile, and
since the retention fix that normalisation pulled those entries back into
the stack it validated — a stack that differed from the stored one and from
`jobs.must_skills` synced from it. Every such profile read as a
`skill_column_conflict` draft nobody could see in the editor (and, with
CHAMPION_INTAKE_GATE_ENABLED, it blocked search, handoff and CV). The set-aside
entries rejoin the stack only when the user saves an edit of that field.
"""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.services.champion_intake import enforce_operation, user_edit, validation
from tests.test_champion_intake_v4 import filled

# Thirteen words: set aside by the #1477 normaliser (> 12), kept by the current one.
SET_ASIDE = (
    "Minimum pięć lat komercyjnego doświadczenia w projektowaniu systemów "
    "rozproszonych opartych na Apache Kafka"
)


def stored_profile() -> dict:
    cp = filled()
    cp["stack"]["must"] = [{"name": "Java 17"}]
    cp["intake"]["unresolved"]["stack.must"] = SET_ASIDE
    return cp


def job(cp: dict, **columns) -> SimpleNamespace:
    values = {
        "champion_profile": cp,
        "title": "Java Developer",
        "client_id": 1,
        "rate_budget_hourly": None,
        "onsite_days_per_week": None,
        "location": None,
        "office_location": None,
        "remote_policy": None,
        "matching_requirements": None,
        "requirements_reviewed": False,
        "must_skills": [{"name": "Java 17", "level": None}],
        "nice_skills": None,
    }
    values.update(columns)
    return SimpleNamespace(**values)


def names(profile: dict, key: str = "must") -> list[str]:
    return [item["name"] for item in profile["stack"][key]]


@pytest.mark.parametrize("gate", ["false", "true"])
def test_a_set_aside_entry_does_not_turn_a_matching_profile_into_a_draft(
    monkeypatch, gate
) -> None:
    monkeypatch.setenv("CHAMPION_INTAKE_GATE_ENABLED", gate)
    cp = stored_profile()
    draft = job(cp)

    result = validation(cp, draft)

    assert result["status"] == "ready", result["issues"]
    assert result["issues"] == []
    assert result["blocked_operations"] == []
    for operation in ("search", "handoff", "cv"):
        enforce_operation(draft, operation)
    # Validation reads; it never rewrites the stored profile.
    assert names(cp) == ["Java 17"]
    assert cp["intake"]["unresolved"]["stack.must"] == SET_ASIDE


def test_columns_are_compared_with_the_stack_as_stored() -> None:
    """An unstamped profile from the August ingest, validated for the Radar.

    The ingest wrote the parsed MUST list to both the profile and
    `jobs.must_skills`, placeholder included. The re-normalised copy drops the
    placeholder; comparing THAT with the columns reported a conflict between
    two lists that are identical in the database.
    """
    cp = filled()
    cp.pop("intake")
    cp["stack"]["must"] = [{"name": "Java 17"}, {"name": "do ustalenia"}]
    columns = [{"name": "Java 17", "level": None}, {"name": "do ustalenia", "level": None}]

    result = validation(cp, job(cp, must_skills=columns), enforce=True)

    assert "skill_column_conflict" not in {i["code"] for i in result["issues"]}


def test_a_real_must_conflict_is_still_an_error(monkeypatch) -> None:
    monkeypatch.setenv("CHAMPION_INTAKE_GATE_ENABLED", "true")
    cp = stored_profile()

    result = validation(cp, job(cp, must_skills=[{"name": "Python", "level": None}]))

    conflict = next(i for i in result["issues"] if i["code"] == "skill_column_conflict")
    assert conflict["path"] == "stack.must"
    assert conflict["severity"] == "error"
    assert "search" in result["blocked_operations"]


def test_a_nice_conflict_is_a_warning_at_most(monkeypatch) -> None:
    monkeypatch.setenv("CHAMPION_INTAKE_GATE_ENABLED", "true")
    cp = stored_profile()
    cp["stack"]["nice"] = [{"name": "Terraform"}]

    result = validation(cp, job(cp, nice_skills=[{"name": "Ansible", "level": None}]))

    conflict = next(i for i in result["issues"] if i["code"] == "skill_column_conflict")
    assert conflict["path"] == "stack.nice"
    assert conflict["severity"] == "warning"
    assert conflict["blocked_operations"] == []
    assert result["status"] == "ready"


def test_a_nice_entry_set_aside_does_not_resurrect_either() -> None:
    cp = stored_profile()
    cp["stack"]["nice"] = [{"name": "Terraform"}]
    cp["intake"]["unresolved"]["stack.nice"] = SET_ASIDE

    result = validation(cp, job(cp, nice_skills=[{"name": "Terraform", "level": None}]))

    assert result["issues"] == []


def test_editing_the_must_stack_brings_the_set_aside_entry_back() -> None:
    edited = user_edit(
        stored_profile(),
        {"stack": {"must": [{"name": "Java 17"}, {"name": "Docker"}]}},
        7,
    )

    assert names(edited) == ["Java 17", "Docker", SET_ASIDE]
    assert "stack.must" not in edited["intake"]["unresolved"]
    assert edited["intake"]["advisory"]["stack.must"] == SET_ASIDE


def test_an_unrelated_edit_leaves_the_set_aside_entry_where_it_is() -> None:
    edited = user_edit(stored_profile(), {"project": {"about": "Nowy opis."}}, 7)

    assert names(edited) == ["Java 17"]
    assert edited["intake"]["unresolved"]["stack.must"] == SET_ASIDE


# ── API ──────────────────────────────────────────────────────────────────────


async def _seed() -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Synthetic Champion stack {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        row = Job(
            title="Synthetic Java role",
            status=JobStatus.draft,
            client_id=client.id,
            champion_profile=stored_profile(),
            must_skills=[{"name": "Java 17", "level": None}],
        )
        db.add(row)
        await db.commit()
        return row.id


async def test_stored_profile_is_ready_and_a_stack_edit_restores_and_syncs(
    app_client, app_auth_headers, monkeypatch
):
    async def no_refresh(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.services.job_matching_refresh.refresh_job_matching", no_refresh
    )
    monkeypatch.setenv("CHAMPION_INTAKE_GATE_ENABLED", "true")
    job_id = await _seed()
    route = f"/api/jobs/{job_id}/champion-profile"

    before = await app_client.get(route, headers=app_auth_headers)
    assert before.status_code == 200, before.text
    assert before.json()["validation"]["status"] == "ready", before.json()["validation"]
    assert before.json()["validation"]["issues"] == []

    edited = await app_client.put(
        route,
        json={"stack": {"must": [{"name": "Java 17"}, {"name": "Docker"}]}},
        headers=app_auth_headers,
    )
    assert edited.status_code == 200, edited.text
    async with AsyncSessionLocal() as db:
        saved = await db.scalar(select(Job).where(Job.id == job_id))
    expected = ["Java 17", "Docker", SET_ASIDE]
    assert names(saved.champion_profile) == expected
    assert [item["name"] for item in saved.must_skills] == expected
    issue_codes = {i["code"] for i in edited.json()["validation"]["issues"]}
    assert "skill_column_conflict" not in issue_codes
    assert edited.json()["validation"]["blocked_operations"] == []
