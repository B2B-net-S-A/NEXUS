"""Profil „Kogo szukamy” i „Nie proponujemy” w porcji (decyzja Artura 16.11.2026).

Kontrakty: bez zapisu profil liczy się z tytułu i krytycznych Championa;
„Osoba to: X” przy „Inna rola” od 3 takich samych (casefold) w jednej
rekrutacji wchodzi na listę; wpis ręczny działa od razu; zdjęta etykieta
z odrzuceń przestaje działać; silnik „Nowych” nie dokłada osoby, której
obecne stanowisko zawiera etykietę całymi słowami. PUT: rekruter rekrutacji,
DL, HoR, admin — inny rekruter dostaje 403.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.autofill_feedback import AutofillFeedback
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.user import User, UserRole
from app.services import job_role_profile as profiles
from app.services import new_column_autofill as autofill
from tests.test_autofill_feedback import api_client  # noqa: F401 (fixture)


def _job(title, critical=None, job_id=1):
    champion = {"stack": {"critical": critical}} if critical is not None else None
    return SimpleNamespace(id=job_id, title=title, champion_profile=champion)


def test_default_profile_from_title_and_champion():
    assert profiles.default_profile(
        _job("Senior Java Developer", ["Java", "Spring"])
    ) == {
        "role": "programista",
        "specialty": None,
        "technology": "Java",
        "level": "dowolny",
    }
    lead = profiles.default_profile(_job("Test Automation Lead"))
    assert lead["role"] == "tester" and lead["level"] == "lider"
    unknown = profiles.default_profile(_job("Senior IT Analyst"))
    assert unknown["role"] is None and unknown["technology"] is None
    for title in ("Head of Data", "Kierownik projektu IT", "Solution Architect"):
        assert profiles.default_level(title) == "lider", title
    assert profiles.default_level("Leasing Specialist") == "dowolny"


def test_three_same_person_roles_make_an_exclusion():
    learned = profiles.learned_from_details(
        [
            {"role_kind": "profession", "person_role": "Data Engineer"},
            {"person_role": "data  engineer"},
            {"person_role": "DATA ENGINEER"},
            {"person_role": "Tester manualny"},
            {"role_wanted": "analityk"},
            None,
        ]
    )
    out = profiles.build_profile(_job("Senior IT Analyst"), None, learned)
    assert out["saved"] is False
    assert out["excluded"] == [
        {"label": "Data Engineer", "count": 3, "source": "rejections"}
    ]
    assert out["learning"] == [
        {"label": "Tester manualny", "count": 1, "dismissed": False}
    ]


def test_manual_entries_work_at_once_and_dismissed_stop():
    learned = profiles.learned_from_details([{"person_role": "DBA"}] * 4)
    row = SimpleNamespace(
        role="analityk biznesowy",
        specialty=None,
        technology=None,
        level="wykonawca",
        excluded=["Scrum Master", "scrum master"],
        dismissed=["dba"],
    )
    out = profiles.build_profile(_job("IT Analyst"), row, learned)
    assert out["role"] == "analityk biznesowy" and out["level"] == "wykonawca"
    assert out["excluded"] == [
        {"label": "Scrum Master", "count": 0, "source": "manual"}
    ]
    assert out["learning"] == [{"label": "DBA", "count": 4, "dismissed": True}]


def test_label_matches_whole_words_only():
    assert profiles.names_role("Senior Data Engineer", "data engineer")
    assert profiles.names_role("Tester / QA", "tester")
    assert not profiles.names_role("Big Data Engineering Lead", "data engineer")
    assert not profiles.names_role("Testerka", "tester")
    assert not profiles.names_role(None, "tester")
    assert profiles.names_role("C++ Developer", "c++")


def test_payload_is_cleaned_and_level_checked():
    data = profiles.clean_payload(
        {
            "role": "  analityk   biznesowy ",
            "level": "lider",
            "excluded": ["DBA", " dba ", "", "Tester"],
        }
    )
    assert data == {
        "role": "analityk biznesowy",
        "specialty": None,
        "technology": None,
        "level": "lider",
        "excluded": ["DBA", "Tester"],
    }
    with pytest.raises(HTTPException) as bad:
        profiles.clean_payload({"level": "manager"})
    assert bad.value.status_code == 422
    with pytest.raises(HTTPException):
        profiles.clean_payload({"excluded": [f"rola {i}" for i in range(21)]})


# ── Z bazą (CI) ──────────────────────────────────────────────────────────────


async def _with_position(cid: int, position: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == cid)
            .values(cv_extracted_data={"current_position": position})
        )
        await db.commit()


async def _role_rejection(job_id: int, cid: int, person_role: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            AutofillFeedback(
                job_id=job_id,
                candidate_id=cid,
                reason="other_level_or_role",
                learned_from="profile",
                bucket="search",
                detail={"role_kind": "profession", "person_role": person_role},
            )
        )
        await db.commit()


async def test_engine_skips_roles_on_the_list(monkeypatch):
    from tests.test_autofill_feedback import _client_with_jobs, _fill, _people, _pool

    monkeypatch.setattr(autofill, "TARGET", 5)
    _client, (job_id,) = await _client_with_jobs(1)
    rejected = await _people(3)
    data_engineer, scrum, analyst = await _people(3)
    tag = uuid.uuid4().hex[:6]
    for cid in rejected:
        await _role_rejection(job_id, cid, f"Data Engineer {tag}")
    await _with_position(data_engineer, f"Senior Data Engineer {tag}")
    await _with_position(scrum, "Scrum Master")
    await _with_position(analyst, "Business Analyst")
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        await profiles.save_profile(
            db,
            job,
            {"excluded": ["scrum master", f"Data Engineer {tag}"]},
            user_id=None,
        )
        await db.commit()
    await _pool(job_id, {data_engineer: 95, scrum: 90, analyst: 80})

    assert await _fill(job_id) == [analyst]

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        out = (await profiles.profiles_for_jobs(db, [job]))[job_id]
    # Etykieta z odrzuceń, która została na liście, dalej jest „z odrzuceń”.
    assert {(e["label"].casefold(), e["source"]) for e in out["excluded"]} == {
        ("scrum master", "manual"),
        (f"data engineer {tag}".casefold(), "rejections"),
    }


async def test_profile_put_is_for_the_job_team(api_client):  # noqa: F811
    from tests.test_autofill_feedback import _world

    world = await _world()
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        outsider = User(
            email=f"jrp-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Jrp"),
            name=f"JRP {tag}",
            role=UserRole.recruiter,
            is_active=True,
            profile_completed=True,
        )
        db.add(outsider)
        await db.commit()

    async def headers(email: str, password: str) -> dict:
        login = await api_client.post(
            "/api/auth/login", json={"email": email, "password": password}
        )
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    own = await headers(world["email"], world["password"])
    other = await headers(outsider.email, f"T3st_{tag}!Jrp")
    url = f"/api/review-batch/jobs/{world['job_id']}/profile"
    body = {"role": "analityk", "level": "wykonawca", "excluded": ["DBA"]}

    denied = await api_client.put(url, headers=other, json=body)
    assert denied.status_code == 403, denied.text

    saved = await api_client.put(url, headers=own, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["excluded"] == [
        {"label": "DBA", "count": 0, "source": "manual"}
    ]

    bad = await api_client.put(url, headers=own, json={**body, "level": "szef"})
    assert bad.status_code == 422

    read = await api_client.get(url, headers=own)
    assert read.status_code == 200
    assert read.json()["role"] == "analityk" and read.json()["can_edit"] is True
    assert (await api_client.get(url, headers=other)).json()["can_edit"] is False
