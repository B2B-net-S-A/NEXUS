"""Słownik umiejętności, etap 2 (06.11.2026) na żywej bazie.

- Zapamiętany wynik dopasowania nie przeżywa zmiany słownika: po dodaniu
  aliasu rekrutacja, która wymaga tego hasła, liczy się od nowa.
- Rola nie przyjmuje aliasów (ani ręcznie, ani przez „Zmapuj”).
- Nowe hasło wymaga kategorii z listy; nazwę i kategorię hasła da się poprawić.

Dane fikcyjne z losowym znacznikiem; baza testowa jest wspólna.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.match_score import CandidateJobMatchScore
from app.models.skill import Skill, SkillAlias
from app.models.user import User, UserRole
from app.services import (
    job_lifecycle,
    match_score_cache,
    skill_curation,
    skill_taxonomy_loader,
)
from app.services.skill_taxonomy_loader import refresh_alias_map


def _hex() -> str:
    return uuid.uuid4().hex[:8]


async def _headers_for(app_client: AsyncClient, role: UserRole) -> dict[str, str]:
    suffix = _hex()
    email = f"skill-stage2-{role.value}-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Słownik {role.value}",
                role=role,
                roles=[role.value],
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _cached_row_stale(job_id: int, candidate_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        stale = await db.scalar(
            select(CandidateJobMatchScore.stale).where(
                CandidateJobMatchScore.job_id == job_id,
                CandidateJobMatchScore.candidate_id == candidate_id,
            )
        )
    assert stale is not None, "brak zapamiętanego wyniku"
    return stale


@pytest.mark.asyncio
async def test_dictionary_change_touches_published_and_reopen_recomputes() -> None:
    """Audyt 2, W4 i W5: słownik unieważnia tylko opublikowane, a wersja rośnie.
    Zamknięta wraca z unieważnionymi wynikami (`publish_core`, jedyna droga otwarcia)."""
    tag = _hex()
    skill_id = await _skill(f"Zarn{tag}", "tools")
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient W4 {tag}")
        db.add(client)
        await db.flush()
        jobs = [
            Job(
                title=f"Analityk {status.value} {tag}",
                status=status,
                client_id=client.id,
                must_skills=[{"name": f"Zarn{tag}"}],
            )
            for status in (JobStatus.published, JobStatus.closed)
        ]
        candidate = Candidate(
            name="Kandydat",
            lastname=f"Wersja{tag}",
            email=f"skill-w4-{tag}@example.com",
            skills=[{"name": f"Zarn{tag}"}],
        )
        db.add_all([*jobs, candidate])
        await db.commit()
        published_id, closed_id = (job.id for job in jobs)
        candidate_id = candidate.id
    await refresh_alias_map()

    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        for job_id in (published_id, closed_id):
            job = await db.get(Job, job_id)
            await match_score_cache.get_cached_or_compute(
                candidate, job, db, semantic_similarity=0.5
            )
        await db.commit()

    version_before = await skill_taxonomy_loader._stored_dictionary_version()
    async with AsyncSessionLocal() as db:
        await skill_curation.add_alias(db, skill_id, f"zarnish{tag}")
    version_after = await skill_taxonomy_loader._stored_dictionary_version()

    assert version_after != version_before
    assert skill_taxonomy_loader._loaded_version == version_after
    assert await _cached_row_stale(published_id, candidate_id) is True
    assert await _cached_row_stale(closed_id, candidate_id) is False

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, closed_id)
        actor = await db.scalar(select(User).where(User.is_active.is_(True)).limit(1))
        if actor is None:
            actor = User(
                email=f"skill-w4-actor-{tag}@example.com",
                password_hash=hash_password(f"T3st_{tag}!PassX"),
                name="Aktor",
                role=UserRole.admin,
                roles=[UserRole.admin.value],
                is_active=True,
                profile_completed=True,
            )
            db.add(actor)
            await db.flush()
        await job_lifecycle.publish_core(
            db, job, actor, job_lifecycle.PostCommit(), new_opening=False
        )
        await db.commit()
    assert await _cached_row_stale(closed_id, candidate_id) is True


async def _skill(name: str, category: str) -> int:
    async with AsyncSessionLocal() as db:
        skill = Skill(canonical_name=name, category=category)
        db.add(skill)
        await db.commit()
        return skill.id


@pytest.mark.asyncio
async def test_cached_score_is_recomputed_after_new_alias() -> None:
    tag = _hex()
    skill_id = await _skill(f"Zorb{tag}", "tools")
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient etapu 2 {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Analityk {tag}",
            status=JobStatus.published,
            client_id=client.id,
            must_skills=[{"name": f"Zorb{tag}"}],
        )
        candidate = Candidate(
            name="Kandydat",
            lastname=f"Etap{tag}",
            email=f"skill-stage2-{tag}@example.com",
            skills=[{"name": f"zorbish{tag}"}],
        )
        db.add_all([job, candidate])
        await db.commit()
        job_id, candidate_id = job.id, candidate.id
    await refresh_alias_map()

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        candidate = await db.get(Candidate, candidate_id)
        before = await match_score_cache.get_cached_or_compute(
            candidate, job, db, semantic_similarity=0.5
        )
        await db.commit()
    assert any(f"zorb{tag}" == g.lower() for g in before.gap_must), before.gap_must

    async with AsyncSessionLocal() as db:
        await skill_curation.add_alias(db, skill_id, f"zorbish{tag}")

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        candidate = await db.get(Candidate, candidate_id)
        after = await match_score_cache.get_cached_or_compute(
            candidate, job, db, semantic_similarity=0.5
        )
    assert any(f"zorb{tag}" == m.lower() for m in after.matching_must), (
        "zapamiętany wynik sprzed aliasu przeżył zmianę słownika",
        after.gap_must,
    )


@pytest.mark.asyncio
async def test_role_does_not_take_aliases() -> None:
    tag = _hex()
    role_id = await _skill(f"Rola {tag}", "role_management")
    async with AsyncSessionLocal() as db:
        with pytest.raises(skill_curation.CurationError, match="rola"):
            await skill_curation.add_alias(db, role_id, f"leadish{tag}")
    async with AsyncSessionLocal() as db:
        aliases = (
            await db.scalars(
                select(SkillAlias.alias).where(SkillAlias.skill_id == role_id)
            )
        ).all()
    assert aliases == []


@pytest.mark.asyncio
async def test_new_skill_needs_category_from_the_list(
    app_client: AsyncClient,
) -> None:
    hor = await _headers_for(app_client, UserRole.head_of_recruitment)
    tag = _hex()
    missing = await app_client.post(
        "/api/skills-admin/skills", json={"canonical_name": f"Qux{tag}"}, headers=hor
    )
    assert missing.status_code == 422
    role = await app_client.post(
        "/api/skills-admin/skills",
        json={"canonical_name": f"Qux{tag}", "category": "role_management"},
        headers=hor,
    )
    assert role.status_code == 422
    ok = await app_client.post(
        "/api/skills-admin/skills",
        json={"canonical_name": f"Qux{tag}", "category": "practice"},
        headers=hor,
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_rename_keeps_old_name_as_alias_and_changes_category(
    app_client: AsyncClient,
) -> None:
    hor = await _headers_for(app_client, UserRole.head_of_recruitment)
    tag = _hex()
    skill_id = await _skill(f"nosql{tag}", "database")
    resp = await app_client.patch(
        f"/api/skills-admin/skills/{skill_id}",
        json={"canonical_name": f"NoSQL {tag}", "category": "practice"},
        headers=hor,
    )
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        skill = await db.get(Skill, skill_id)
        aliases = set(
            (
                await db.scalars(
                    select(SkillAlias.alias).where(SkillAlias.skill_id == skill_id)
                )
            ).all()
        )
    assert (skill.canonical_name, skill.category) == (f"NoSQL {tag}", "practice")
    assert f"nosql{tag}" in aliases, "stary zapis dalej rozpoznaje hasło"

    case_only = await app_client.patch(
        f"/api/skills-admin/skills/{skill_id}",
        json={"canonical_name": f"NOSQL {tag}"},
        headers=hor,
    )
    assert case_only.status_code == 200
    bad = await app_client.patch(
        f"/api/skills-admin/skills/{skill_id}",
        json={"category": "role_dev"},
        headers=hor,
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_list_separates_roles_and_delivery_lead_cannot_edit(
    app_client: AsyncClient,
) -> None:
    tag = _hex()
    await _skill(f"Rola lista {tag}", "role_dev")
    await _skill(f"Umiejetnosc lista {tag}", "tools")
    hor = await _headers_for(app_client, UserRole.head_of_recruitment)
    roles = await app_client.get(
        "/api/skills-admin/skills", params={"q": tag, "kind": "roles"}, headers=hor
    )
    skills = await app_client.get(
        "/api/skills-admin/skills", params={"q": tag, "kind": "skills"}, headers=hor
    )
    assert [i["name"] for i in roles.json()["items"]] == [f"Rola lista {tag}"]
    assert [i["name"] for i in skills.json()["items"]] == [f"Umiejetnosc lista {tag}"]
    assert roles.json()["items"][0]["is_role"] is True
    assert "practice" in skills.json()["categories"]

    dl = await _headers_for(app_client, UserRole.delivery_lead)
    denied = await app_client.patch(
        "/api/skills-admin/skills/1", json={"category": "tools"}, headers=dl
    )
    assert denied.status_code == 403
