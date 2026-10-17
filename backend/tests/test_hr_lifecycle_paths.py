"""Ścieżki wejścia i odejścia (etap 3, O1, O4, O5, M4): odbiorcy, wersje,
warunki pozycji, kto zmienia którą ścieżkę i „Dociągnij do trwających”.

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.models.contract import Contract
from app.models.hr_lifecycle import LifecycleCase, LifecycleTask, LifecycleTemplate
from app.services import hr_lifecycle_schema as schema
from app.services.hr import contract_hooks
from app.services.hr.lifecycle_planning import CaseFacts, item_applies
from tests.test_equipment_api import modules_on  # noqa: F401
from tests.test_hr_consultant_entry import (  # noqa: F401
    _cleanup,
    _world,
    back_office_head,  # noqa: F811
    pack,  # noqa: F811
)
from tests.test_hr_lifecycle_api import _grant, _headers, _team, _user

BASE = "/api/hr/lifecycle"


def _payload(template: dict, **changes) -> dict:
    body = {
        key: template[key]
        for key in (
            "kind",
            "audience",
            "name",
            "is_active",
            "employment_type",
            "department",
            "items",
        )
    }
    body.update(changes)
    return body


async def _consultant_path(app_client, headers) -> dict:
    listing = await app_client.get(
        f"{BASE}/templates?kind=onboarding&audience=consultant", headers=headers
    )
    assert listing.status_code == 200, listing.text
    return next(row for row in listing.json()["items"] if row["is_active"])


# ── Warunki (czyste funkcje) ─────────────────────────────────────────────────


def test_conditions_pick_items_by_form_equipment_and_student() -> None:
    b2b_ours = CaseFacts(employment_type="b2b", equipment="ours")
    contractor = CaseFacts(employment_type="zlecenie", equipment=None, student=False)
    assert item_applies({}, b2b_ours)
    assert item_applies({"employment_types": ["b2b"]}, b2b_ours)
    assert not item_applies({"employment_types": ["b2b"]}, contractor)
    assert item_applies({"equipment": "ours"}, b2b_ours)
    # Klient bez ustawienia sprzętu: pozycji sprzętu nie zakładamy (jak hak Sprzętu).
    assert not item_applies({"equipment": "ours"}, contractor)
    assert not item_applies({"student": True}, contractor)
    assert item_applies({"student": True}, CaseFacts(employment_type="zlecenie"))


def test_seeded_consultant_path_has_the_welcome_mail_key() -> None:
    name, items = schema.DEFAULT_TEMPLATES[("onboarding", "consultant")]
    assert name == "Konsultant u klienta"
    keys = {item["key"] for item in items if item["key"]}
    assert keys == {"welcome_mail", "equipment_kit", "equipment_issue"}
    assert all(item["assignee_kind"] in schema.TASK_ASSIGNEES for item in items)


# ── Kto zmienia którą ścieżkę (O4) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_hr_edits_team_paths_and_back_office_head_the_consultant_path(
    app_client,
    modules_on,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    team = await _team()
    hr = _headers(team["hr"])
    head = _headers(back_office_head)
    consultant = await _consultant_path(app_client, hr)
    assert consultant["can_edit"] is False  # Kadry widzą, nie zmieniają
    refused = await app_client.put(
        f"{BASE}/templates/{consultant['id']}", json=_payload(consultant), headers=hr
    )
    assert refused.status_code == 403
    listing = await app_client.get(f"{BASE}/templates?kind=onboarding", headers=head)
    team_path = next(
        row for row in listing.json()["items"] if row["audience"] == "team"
    )
    assert team_path["can_edit"] is False
    refused = await app_client.put(
        f"{BASE}/templates/{team_path['id']}", json=_payload(team_path), headers=head
    )
    assert refused.status_code == 403
    # Osoba bez Kadr i bez pionu nie widzi ścieżek wcale.
    outsider = await app_client.get(f"{BASE}/templates", headers=_headers(team["boss"]))
    assert outsider.status_code == 403
    # Odbiorców ścieżki nie da się zmienić zapisem.
    flipped = await app_client.put(
        f"{BASE}/templates/{consultant['id']}",
        json=_payload(consultant, audience="team"),
        headers=_headers(team["admin"]),
    )
    assert flipped.status_code == 422


@pytest.mark.asyncio
async def test_saving_a_path_bumps_the_version_and_keeps_item_keys(
    app_client,
    modules_on,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    head = _headers(back_office_head)
    path = await _consultant_path(app_client, head)
    items = [
        {key: item[key] for key in item if key not in ("key", "added_in_version")}
        for item in path["items"]
    ]
    items.append(
        {
            "title": "Karta wejściowa do biura klienta",
            "category": "equipment",
            "assignee_kind": "care_owner",
            "due_offset_days": 0,
            "conditions": {"equipment": "client"},
            "required": False,
        }
    )
    try:
        saved = await app_client.put(
            f"{BASE}/templates/{path['id']}",
            json=_payload(path, items=items),
            headers=head,
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["version"] == path["version"] + 1
        by_title = {item["title"]: item for item in body["items"]}
        assert by_title["Mail powitalny do konsultanta"]["key"] == "welcome_mail"
        new = by_title["Karta wejściowa do biura klienta"]
        assert new["added_in_version"] == body["version"]
        assert new["conditions"] == {"equipment": "client"} and new["required"] is False
        without_mail = await app_client.put(
            f"{BASE}/templates/{path['id']}",
            json=_payload(
                path,
                items=[
                    {
                        key: item[key]
                        for key in item
                        if key not in ("key", "added_in_version")
                    }
                    for item in path["items"]
                    if item["key"] != "welcome_mail"
                ],
            ),
            headers=head,
        )
        assert without_mail.status_code == 422
        assert "Mail powitalny" in without_mail.json()["detail"]
        bad = await app_client.put(
            f"{BASE}/templates/{path['id']}",
            json=_payload(
                path,
                items=[{**items[0], "conditions": {"employment_types": ["etat"]}}],
            ),
            headers=head,
        )
        assert bad.status_code == 422
    finally:
        await _restore(path)


async def _restore(path: dict) -> None:
    """Ścieżka startowa wraca do stanu z zasiewu (inne testy na niej polegają)."""

    async with AsyncSessionLocal() as db:
        template = await db.get(LifecycleTemplate, path["id"])
        template.version = path["version"]
        await db.execute(
            text(
                "DELETE FROM lifecycle_template_items WHERE template_id = :t "
                "AND id <> ALL(:keep)"
            ),
            {"t": path["id"], "keep": [item["id"] for item in path["items"]]},
        )
        await db.commit()


@pytest.mark.asyncio
async def test_catch_up_adds_new_items_to_live_entries_on_an_older_version(
    app_client,
    modules_on,  # noqa: F811
    pack,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    world = await _world(provider="klienta")
    head = _headers(back_office_head)
    path = await _consultant_path(app_client, head)
    try:
        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, world["id"])
            await contract_hooks.contract_started(db, contract)
            await db.commit()
        items = [
            {key: item[key] for key in item if key not in ("key", "added_in_version")}
            for item in path["items"]
        ] + [
            {
                "title": "Karta wejściowa do biura klienta",
                "category": "equipment",
                "assignee_kind": "care_owner",
                "due_offset_days": 0,
                "conditions": {"equipment": "client"},
            },
            {
                "title": "Tylko przy sprzęcie od nas",
                "category": "equipment",
                "assignee_kind": "reception",
                "due_offset_days": 0,
                "conditions": {"equipment": "ours"},
            },
        ]
        saved = await app_client.put(
            f"{BASE}/templates/{path['id']}",
            json=_payload(path, items=items),
            headers=head,
        )
        assert saved.json()["live_cases_behind"] >= 1
        async with AsyncSessionLocal() as db:
            case = await db.scalar(
                select(LifecycleCase).where(LifecycleCase.contract_id == world["id"])
            )
            before = set(
                await db.scalars(
                    select(LifecycleTask.title).where(LifecycleTask.case_id == case.id)
                )
            )
        assert (
            "Karta wejściowa do biura klienta" not in before
        )  # nowa wersja nie rusza trwających
        hr = await app_client.post(
            f"{BASE}/templates/{path['id']}/catch-up", headers=_headers(world["owner"])
        )
        assert hr.status_code == 403
        caught = await app_client.post(
            f"{BASE}/templates/{path['id']}/catch-up", headers=head
        )
        assert caught.status_code == 200, caught.text
        assert caught.json()["cases"] >= 1
        assert caught.json()["template"]["live_cases_behind"] == 0
        async with AsyncSessionLocal() as db:
            after = set(
                await db.scalars(
                    select(LifecycleTask.title).where(LifecycleTask.case_id == case.id)
                )
            )
            version = await db.scalar(
                select(LifecycleCase.template_version).where(
                    LifecycleCase.id == case.id
                )
            )
        assert after - before == {"Karta wejściowa do biura klienta"}  # warunek sprzętu
        assert version == saved.json()["version"]
        again = await app_client.post(
            f"{BASE}/templates/{path['id']}/catch-up", headers=head
        )
        assert again.json()["tasks"] == 0
    finally:
        await _cleanup(world)
        await _restore(path)


@pytest.mark.asyncio
async def test_team_onboarding_never_picks_the_consultant_path(
    app_client,
    modules_on,  # noqa: F811
) -> None:
    team = await _team()
    async with AsyncSessionLocal() as db:
        consultant_id = await db.scalar(
            select(LifecycleTemplate.id).where(
                LifecycleTemplate.kind == "onboarding",
                LifecycleTemplate.audience == "consultant",
            )
        )
        newcomer = await _user(db, "recruiter")
        await db.commit()
    created = await app_client.post(
        f"{BASE}/cases/onboarding",
        json={"user_id": newcomer.id, "start_date": "2030-03-04"},
        headers=_headers(team["hr"]),
    )
    assert created.status_code == 201, created.text
    assert created.json()["audience"] == "team"
    assert created.json()["template_id"] != consultant_id
    refused = await app_client.post(
        f"{BASE}/cases/onboarding",
        json={
            "email": "nowa.osoba.sciezka@example.com",
            "name": "Nowa Przykładowa",
            "start_date": "2030-03-04",
            "template_id": consultant_id,
        },
        headers=_headers(team["hr"]),
    )
    assert refused.status_code == 422


# ── Schemat: druga wersja 0460 na istniejącej bazie ──────────────────────────


@pytest.mark.asyncio
async def test_stage_three_ddl_is_idempotent_and_widens_old_checks() -> None:
    async with AsyncSessionLocal() as db:
        # Stara definicja CHECK-u wykonawców (etap 1) — blok ją podmienia.
        await db.execute(
            text(
                "ALTER TABLE lifecycle_tasks DROP CONSTRAINT ck_lifecycle_tasks_assignee"
            )
        )
        await db.execute(
            text(
                "ALTER TABLE lifecycle_tasks ADD CONSTRAINT ck_lifecycle_tasks_assignee "
                "CHECK (assignee_kind IN ('manager', 'people_admin', 'reception', "
                "'person', 'it')) NOT VALID"
            )
        )
        for _ in range(2):
            for statement in schema.ALL_DDL:
                await db.execute(text(statement))
        definition = await db.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_lifecycle_tasks_assignee'"
            )
        )
        seeded = await db.scalar(
            text(
                "SELECT count(*) FROM lifecycle_templates WHERE audience = 'consultant'"
            )
        )
        await db.commit()
    assert "administration" in definition and "care_owner" in definition
    assert seeded == 2


@pytest.mark.asyncio
async def test_administration_pool_is_the_cases_permission() -> None:
    from app.services.hr.lifecycle_access import pool_member_ids

    async with AsyncSessionLocal() as db:
        office = await _user(db, "recruiter")
        await _grant(db, office, "cases")
        await db.commit()
        assert office.id in await pool_member_ids(db, "administration")
