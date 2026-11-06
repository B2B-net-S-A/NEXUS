"""Propozycje do słownika na żywej bazie: nocny bieg, decyzje HoR+, podpowiedź DL.

Baza testowa jest wspólna i nie jest czyszczona, więc każdy test zakłada własne
nazwy z losowym znacznikiem i sprawdza tylko je. Model jest podmieniony —
test nie płaci za wywołanie. Reguły bez bazy: ``test_skill_proposals.py``.
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.job import Job, JobStatus
from app.models.skill import Skill, SkillAlias
from app.models.skill_proposal import SkillProposal
from app.models.user import User, UserRole
from app.services import skill_proposals as sp


def _hex() -> str:
    return uuid.uuid4().hex[:8]


async def _headers_for(app_client: AsyncClient, role: UserRole) -> dict[str, str]:
    suffix = _hex()
    email = f"skill-proposals-{role.value}-{suffix}@example.com"
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


@pytest.fixture
def world(monkeypatch):
    """Fikcyjne nazwy: nowe hasło w 2 zapisach, wariant roli, ogólnik, wariant regułą."""
    tag = _hex()
    state = {
        "tag": tag,
        "new": f"Zorblax{tag}",
        "new_ms": f"MS Zorblax{tag}",
        "role_word": f"leadish{tag}",
        "generic": f"bazy{tag}",
        "rule": f"quux-{tag}",
        "calls": 0,
    }

    def fake_model(body: str) -> str:
        state["calls"] += 1
        payload = json.loads(body)
        items = []
        for family in payload["rodziny"]:
            names = " ".join(family["nazwy"])
            item = {"id": family["id"], "decision": "noise", "confidence": "low"}
            if f"zorblax{tag}" in names:
                item = {
                    "id": family["id"],
                    "decision": "new",
                    "canonical": f"Zorblax {tag}",
                    "category": "practice",
                    "confidence": "high",
                }
            elif state["role_word"] in names:
                item = {
                    "id": family["id"],
                    "decision": "alias",
                    "canonical": state["role_skill"],
                    "confidence": "high",
                }
            elif state["generic"] in names:
                item = {
                    "id": family["id"],
                    "decision": "generic",
                    "replacements": [state["base_skill"], "Nieistniejące DB"],
                    "confidence": "high",
                }
            items.append(item)
        return json.dumps({"items": items})

    monkeypatch.setattr(sp, "_call_model", fake_model)
    monkeypatch.setattr(sp, "TOP_FAMILIES", 1_000_000)
    return state


async def _seed(state: dict) -> None:
    tag = state["tag"]
    async with AsyncSessionLocal() as db:
        role_skill = Skill(
            canonical_name=f"Rola Lead {tag}", category="role_management"
        )
        base_skill = Skill(canonical_name=f"Bazowa DB {tag}", category="database")
        rule_skill = Skill(canonical_name=f"Quux{tag}", category="practice")
        db.add_all([role_skill, base_skill, rule_skill])
        await db.flush()
        state["role_skill"] = role_skill.canonical_name
        state["base_skill"] = base_skill.canonical_name
        state["base_skill_id"] = base_skill.id
        state["rule_skill_id"] = rule_skill.id
        for i in range(3):
            db.add(
                Candidate(
                    name="Kandydat",
                    lastname=f"Słownikowy{tag}{i}",
                    email=f"skill-proposals-{tag}-{i}@example.com",
                    skills=[
                        {"name": state["new"]},
                        {"name": state["role_word"]},
                        {"name": base_skill.canonical_name},
                    ],
                )
            )
        db.add(
            Job(
                title=f"Analityk {tag}",
                status=JobStatus.published,
                must_skills=[
                    {"name": state["new_ms"]},
                    {"name": f"{state['generic']} lub {state['rule']}"},
                ],
            )
        )
        await db.commit()


async def _rows(tag: str) -> dict[str, SkillProposal]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(SkillProposal).where(SkillProposal.family_key.contains(tag))
            )
        ).all()
    return {row.family_key: row for row in rows}


async def _run() -> dict:
    async with AsyncSessionLocal() as db:
        return await sp.run(db)


@pytest.mark.asyncio
async def test_nightly_run_groups_guards_and_keeps_decided(world) -> None:
    await _seed(world)
    summary = await _run()
    assert summary["model_error"] is False
    rows = await _rows(world["tag"])
    new = rows[f"zorblax{world['tag']}"]
    assert {n["name"] for n in new.names} == {
        world["new"].lower(),
        world["new_ms"].lower(),
    }
    assert (new.cand_count, new.job_count, new.weight) == (3, 1, 3 + 20)
    assert (new.decision, new.confidence, new.category) == ("new", "high", "practice")
    role = rows[world["role_word"]]
    assert role.confidence == "low"
    assert role.review_note.startswith("Wskazuje rolę")
    generic = rows[f"bazy{world['tag']}"]
    assert generic.replacements == [world["base_skill"]]
    rule = rows[f"quux{world['tag']}"]
    assert (rule.decision, rule.target_skill_id, rule.model) == (
        "alias",
        world["rule_skill_id"],
        None,
    )

    calls = world["calls"]
    await _run()
    assert world["calls"] == calls, "sklasyfikowane rodziny nie idą drugi raz do modelu"


@pytest.mark.asyncio
async def test_hor_accepts_sure_and_dictionary_learns(app_client, world) -> None:
    await _seed(world)
    await _run()
    hor = await _headers_for(app_client, UserRole.head_of_recruitment)

    listing = await app_client.get(
        "/api/skills-admin/proposals", params={"q": world["tag"]}, headers=hor
    )
    assert listing.status_code == 200, listing.text
    by_key = {item["family_key"]: item for item in listing.json()["items"]}
    assert by_key[f"zorblax{world['tag']}"]["sure"] is True
    assert by_key[world["role_word"]]["sure"] is False

    resp = await app_client.post("/api/skills-admin/proposals/accept-sure", headers=hor)
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        skill = await db.scalar(
            select(Skill).where(Skill.canonical_name == f"Zorblax {world['tag']}")
        )
        assert skill is not None and skill.category == "practice"
        aliases = set(
            (
                await db.scalars(
                    select(SkillAlias.alias).where(SkillAlias.skill_id == skill.id)
                )
            ).all()
        )
        assert {world["new"].lower(), world["new_ms"].lower()} <= aliases
        rule_aliases = set(
            (
                await db.scalars(
                    select(SkillAlias.alias).where(
                        SkillAlias.skill_id == world["rule_skill_id"]
                    )
                )
            ).all()
        )
        assert world["rule"].lower() in rule_aliases
    rows = await _rows(world["tag"])
    assert rows[world["role_word"]].status == "open", "rola czeka na człowieka"

    accepted_id = rows["zorblax" + world["tag"]].id
    again = await app_client.post(
        f"/api/skills-admin/proposals/{accepted_id}/accept", headers=hor
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_generic_cannot_be_accepted_and_reject_is_final(
    app_client, world
) -> None:
    await _seed(world)
    await _run()
    hor = await _headers_for(app_client, UserRole.head_of_recruitment)
    generic = (await _rows(world["tag"]))[f"bazy{world['tag']}"]

    refused = await app_client.post(
        f"/api/skills-admin/proposals/{generic.id}/accept", headers=hor
    )
    assert refused.status_code == 422
    rejected = await app_client.post(
        f"/api/skills-admin/proposals/{generic.id}/reject", headers=hor
    )
    assert rejected.status_code == 200
    await _run()
    assert (await _rows(world["tag"]))[f"bazy{world['tag']}"].status == "rejected"


@pytest.mark.asyncio
async def test_hor_can_fix_role_alias_into_new_entry(app_client, world) -> None:
    await _seed(world)
    await _run()
    hor = await _headers_for(app_client, UserRole.head_of_recruitment)
    role = (await _rows(world["tag"]))[world["role_word"]]
    resp = await app_client.post(
        f"/api/skills-admin/proposals/{role.id}/accept",
        json={
            "decision": "new",
            "canonical": f"Leadish {world['tag']}",
            "category": "practice",
        },
        headers=hor,
    )
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count(Skill.id)).where(
                Skill.canonical_name == f"Leadish {world['tag']}"
            )
        )
    assert count == 1


@pytest.mark.asyncio
async def test_delivery_lead_gets_hints_but_cannot_curate(app_client, world) -> None:
    await _seed(world)
    await _run()
    dl = await _headers_for(app_client, UserRole.delivery_lead)

    denied = await app_client.get("/api/skills-admin/proposals", headers=dl)
    assert denied.status_code == 403
    resp = await app_client.post(
        "/api/job-intake/dictionary-hints",
        json={"words": [world["new_ms"], world["generic"], world["base_skill"]]},
        headers=dl,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["can_curate"] is False
    by_word = {h["word"]: h for h in body["hints"]}
    assert world["base_skill"] not in by_word, "znane hasło nie dostaje podpowiedzi"
    new = by_word[world["new_ms"]]
    assert new["kind"] == "new" and new["proposal_id"]
    assert [w["name"] for w in new["add_words"]] == [world["new"].lower()]
    generic = by_word[world["generic"]]
    assert generic["kind"] == "generic"
    assert [w["name"] for w in generic["add_words"]] == [world["base_skill"]]
    assert generic["add_words"][0]["count"] == 3


@pytest.mark.asyncio
async def test_hint_limits_words(app_client, app_auth_headers) -> None:
    resp = await app_client.post(
        "/api/job-intake/dictionary-hints",
        json={"words": [f"w{i}" for i in range(61)]},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422
