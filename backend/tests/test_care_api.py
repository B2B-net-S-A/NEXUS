"""Opieka nad konsultantami i mapa technologii (``/api/care``) — testy na bazie.

Zakres: przełącznik modułu, zakres Delivery Leada (cudzy klient → 403),
zapis tylko dla DL, TCM i admina, plan kontaktów zamykany rozmową,
„Do przepięcia” bez duplikatów, karta technologiczna na słowniku ``skills``
z kolejką do przejrzenia, mapa klienta z czterech źródeł i endpoint ATLASA
na kluczu konta serwisowego.

Baza testowa jest wspólna — każdy test zakłada własnych klientów, osoby
i umiejętności. Wszystkie dane są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Optional

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.candidate_skill_usage import CandidateSkillUsage
from app.models.client import Client, ClientStatus
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.contract_care import (
    CareConversation,
    RedeployQueueItem,
    SkillReviewItem,
    TechCard,
)
from app.models.job import Job, JobStatus
from app.models.skill import Skill, SkillAlias
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.care.plan import LOOKBACK_DAYS
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

pytestmark = pytest.mark.asyncio

OUT_OF_SCOPE = "Ten klient jest poza Twoim portfelem."
MODULE_OFF = "Ten moduł nie jest jeszcze włączony."


# ── Pomocnicze ──────────────────────────────────────────────────────────────


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def make_user(role: UserRole, *extra: UserRole) -> User:
    tag = _tag()
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"care-{tag}@example.com",
            name=f"Opiekun {tag}",
            role=role,
            roles=[role.value, *(r.value for r in extra)],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        return user


async def make_client(*, dl: Optional[User] = None) -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Firma Przykładowa {_tag()}", status=ClientStatus.active)
        db.add(client)
        await db.flush()
        if dl is not None:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=dl.id, client_id=client.id, is_head=True
                )
            )
        await db.commit()
        return client.id


async def make_contract(
    client_id: int,
    *,
    started_days_ago: int = 10,
    end_in_days: Optional[int] = None,
    status: ContractStatus = ContractStatus.active,
) -> tuple[int, int]:
    tag = _tag()
    today = business_today()
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Anna", lastname=f"Przykładowa-{tag}", email=f"care-{tag}@example.com"
        )
        db.add(candidate)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client_id,
            status=status,
            start_date=today - timedelta(days=started_days_ago),
            end_date=today + timedelta(days=end_in_days) if end_in_days else None,
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("130.000"),
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.commit()
        return contract.id, candidate.id


async def make_skill(label: str) -> tuple[int, str]:
    name = f"{label}{_tag()}"
    async with AsyncSessionLocal() as db:
        skill = Skill(canonical_name=name, category="tools")
        db.add(skill)
        await db.commit()
        return skill.id, name


async def set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


async def _previous_modules():
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )


@pytest_asyncio.fixture
async def care_on():
    previous = await _previous_modules()
    await set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await set_modules(previous or {key: False for key in HR_MODULE_KEYS})


@pytest_asyncio.fixture
async def care_off():
    previous = await _previous_modules()
    await set_modules({key: False for key in HR_MODULE_KEYS})
    yield
    await set_modules(previous or {key: False for key in HR_MODULE_KEYS})


def _card(**overrides) -> dict:
    body = {
        "interview_on": business_today().isoformat(),
        "finalize": True,
        "status": "ok",
        "skill_ids": [],
        "skill_names": [],
    }
    body.update(overrides)
    return body


# ── Dostęp ──────────────────────────────────────────────────────────────────


async def test_switched_off_module_answers_404_except_admin(
    app_client, care_off
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    admin = await make_user(UserRole.admin)
    client_id = await make_client(dl=dl)
    contract_id, _ = await make_contract(client_id)

    denied = await app_client.get(
        f"/api/care/contracts/{contract_id}", headers=headers(dl)
    )
    assert denied.status_code == 404
    assert denied.json()["detail"] == MODULE_OFF
    allowed = await app_client.get(
        f"/api/care/contracts/{contract_id}", headers=headers(admin)
    )
    assert allowed.status_code == 200, allowed.text


async def test_delivery_lead_sees_only_own_clients(app_client, care_on) -> None:
    dl = await make_user(UserRole.delivery_lead)
    own_client = await make_client(dl=dl)
    foreign_client = await make_client()
    own_contract, _ = await make_contract(own_client)
    foreign_contract, _ = await make_contract(foreign_client)

    own = await app_client.get(
        f"/api/care/contracts/{own_contract}", headers=headers(dl)
    )
    assert own.status_code == 200, own.text
    assert own.json()["can_edit"] is True

    for method, url, body in (
        ("get", f"/api/care/contracts/{foreign_contract}", None),
        ("get", f"/api/care/clients/{foreign_client}/tech-map", None),
        (
            "post",
            f"/api/care/contracts/{foreign_contract}/conversations",
            {"occurred_on": business_today().isoformat(), "channel": "phone"},
        ),
        (
            "post",
            f"/api/care/clients/{foreign_client}/stack-notes",
            {"content": "Java"},
        ),
    ):
        response = await app_client.request(
            method.upper(), url, headers=headers(dl), json=body
        )
        assert response.status_code == 403, (url, response.text)
        assert response.json()["detail"] == OUT_OF_SCOPE

    missing = await app_client.get(
        "/api/care/contracts/2000000000", headers=headers(dl)
    )
    assert missing.status_code == 404

    mine = await app_client.get(
        "/api/care/my-consultants?scope=all", headers=headers(dl)
    )
    ids = {row["contract_id"] for row in mine.json()["items"]}
    assert own_contract in ids and foreign_contract not in ids


async def test_readers_without_care_role_cannot_write(app_client, care_on) -> None:
    finance = await make_user(UserRole.finance)
    recruiter = await make_user(UserRole.recruiter)
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id)

    read = await app_client.get(
        f"/api/care/contracts/{contract_id}", headers=headers(finance)
    )
    assert read.status_code == 200, read.text
    assert read.json()["can_edit"] is False
    write = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        headers=headers(finance),
        json={"occurred_on": business_today().isoformat(), "channel": "phone"},
    )
    assert write.status_code == 403
    assert "Delivery Lead" in write.json()["detail"]

    blocked = await app_client.get(
        f"/api/care/contracts/{contract_id}", headers=headers(recruiter)
    )
    assert blocked.status_code == 403


# ── Opiekun i plan ──────────────────────────────────────────────────────────


async def test_owner_falls_back_from_contract_to_client_to_delivery_lead(
    app_client, care_on
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    tcm = await make_user(UserRole.talent_community_manager)
    other_dl = await make_user(UserRole.delivery_lead)
    recruiter = await make_user(UserRole.recruiter)
    client_id = await make_client(dl=dl)
    contract_id, _ = await make_contract(client_id)
    url = f"/api/care/contracts/{contract_id}"

    body = (await app_client.get(url, headers=headers(tcm))).json()
    assert body["owner"]["user"]["id"] == dl.id
    assert body["owner"]["source"] == "delivery_lead"

    default = await app_client.put(
        f"/api/care/clients/{client_id}/default-owner",
        headers=headers(tcm),
        json={"user_id": tcm.id},
    )
    assert default.status_code == 200, default.text
    body = (await app_client.get(url, headers=headers(tcm))).json()
    assert (body["owner"]["user"]["id"], body["owner"]["source"]) == (tcm.id, "client")

    # DL spoza portfela klienta nie może być opiekunem (dzwonek wiódłby na 403).
    outsider = await app_client.put(
        f"{url}/owner", headers=headers(tcm), json={"user_id": other_dl.id}
    )
    assert outsider.status_code == 422
    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=other_dl.id, client_id=client_id, is_head=False
            )
        )
        await db.commit()
    explicit = await app_client.put(
        f"{url}/owner", headers=headers(tcm), json={"user_id": other_dl.id}
    )
    assert explicit.status_code == 200, explicit.text
    assert (
        explicit.json()["owner"]["user"]["id"],
        explicit.json()["owner"]["source"],
    ) == (
        other_dl.id,
        "contract",
    )

    invalid = await app_client.put(
        f"{url}/owner", headers=headers(tcm), json={"user_id": recruiter.id}
    )
    assert invalid.status_code == 422

    listing = await app_client.get(
        "/api/care/my-consultants", headers=headers(other_dl)
    )
    row = next(r for r in listing.json()["items"] if r["contract_id"] == contract_id)
    assert row["next_contact"]["label"] == "Dzień 7"
    assert row["overdue_count"] == 1


async def test_conversation_closes_plan_item_and_flags_redeploy_once(
    app_client, care_on
) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id, started_days_ago=10)
    today = business_today()

    overview = (
        await app_client.get(f"/api/care/contracts/{contract_id}", headers=headers(tcm))
    ).json()
    plan = {item["kind"]: item for item in overview["plan"]}
    assert plan["day_7"]["overdue"] is True
    assert plan["day_7"]["status"] == "open"
    # Rytm domyślny (etap 3): pierwsze 90 dni co 2 tygodnie od startu.
    rhythm = [item for item in overview["plan"] if item["kind"] == "cadence"]
    assert rhythm[0]["due_on"] == (today + timedelta(days=4)).isoformat()

    body = {
        "occurred_on": today.isoformat(),
        "channel": "meeting",
        "satisfaction": 2,
        "note": "Projekt się kończy, chce zmienić zespół.",
        "wants_change": True,
        "attrition_risk": True,
        "project_end_on": (today + timedelta(days=40)).isoformat(),
        "follow_up_on": (today + timedelta(days=14)).isoformat(),
    }
    first = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        headers=headers(tcm),
        json=body,
    )
    assert first.status_code == 201, first.text
    data = first.json()
    plan = {item["kind"]: item for item in data["plan"]}
    assert plan["day_7"]["status"] == "done"
    # Zaległość zamyka tylko zaległe punkty — rozmowy z rytmu czekają dalej.
    assert {i["status"] for i in data["plan"] if i["kind"] == "cadence"} == {"open"}
    active = sorted(r["reason"] for r in data["redeploy"] if r["status"] == "open")
    assert active == ["attrition_risk", "project_end", "wants_change"]
    assert data["last_satisfaction"]["value"] == 2

    again = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        headers=headers(tcm),
        json=body,
    )
    assert again.status_code == 201
    assert len([r for r in again.json()["redeploy"] if r["status"] == "open"]) == 3

    future = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        headers=headers(tcm),
        json={
            "occurred_on": (today + timedelta(days=1)).isoformat(),
            "channel": "phone",
        },
    )
    assert future.status_code == 422
    backwards = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        headers=headers(tcm),
        json={
            "occurred_on": today.isoformat(),
            "channel": "phone",
            "follow_up_on": (today - timedelta(days=1)).isoformat(),
        },
    )
    assert backwards.status_code == 422
    bad_channel = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        headers=headers(tcm),
        json={"occurred_on": today.isoformat(), "channel": "sms"},
    )
    assert bad_channel.status_code == 422


async def test_next_contact_skips_follow_up_older_than_lookback(
    app_client, care_on
) -> None:
    """Karta kontraktu i „Moi konsultanci” liczą następny kontakt jak „Ten
    tydzień” i dzwonek: umówiony termin sprzed ``LOOKBACK_DAYS`` (import) odpada."""

    tcm = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id, started_days_ago=400)
    today = business_today()
    async with AsyncSessionLocal() as db:
        db.add(
            CareConversation(
                contract_id=contract_id,
                occurred_on=today - timedelta(days=60),
                channel="phone",
                follow_up_on=today - timedelta(days=LOOKBACK_DAYS + 1),
            )
        )
        await db.commit()

    overview = await app_client.get(
        f"/api/care/contracts/{contract_id}", headers=headers(tcm)
    )
    assert overview.status_code == 200, overview.text
    upcoming = overview.json()["next_contact"]
    # Stary kontrakt rozmawia co miesiąc (etap 3) — punkt z rytmu, nie follow-up.
    assert upcoming["label"] == "Rozmowa według rytmu"
    assert upcoming["plan_item_id"] is not None
    assert upcoming["due_on"] >= (today - timedelta(days=LOOKBACK_DAYS)).isoformat()

    listing = await app_client.get(
        "/api/care/my-consultants?scope=all", headers=headers(tcm)
    )
    row = next(r for r in listing.json()["items"] if r["contract_id"] == contract_id)
    assert row["next_contact"]["due_on"] == upcoming["due_on"]
    assert row["next_contact"]["label"] == "Rozmowa według rytmu"


async def test_dismissed_project_end_does_not_come_back_for_the_same_date(
    app_client, care_on
) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id)
    skill_id, _name = await make_skill("narzedzie")
    today = business_today()
    end = today + timedelta(days=30)

    created = await app_client.post(
        f"/api/care/contracts/{contract_id}/tech-cards",
        headers=headers(tcm),
        json=_card(skill_ids=[skill_id], project_end_on=end.isoformat()),
    )
    assert created.status_code == 201, created.text
    item = next(r for r in created.json()["redeploy"] if r["reason"] == "project_end")
    assert item["due_on"] == end.isoformat()

    dismissed = await app_client.patch(
        f"/api/care/redeploy/{item['id']}",
        headers=headers(tcm),
        json={"status": "dismissed"},
    )
    assert dismissed.status_code == 200, dismissed.text

    card_id = created.json()["tech_cards"][0]["id"]
    resaved = await app_client.put(
        f"/api/care/tech-cards/{card_id}",
        headers=headers(tcm),
        json=_card(skill_ids=[skill_id], project_end_on=end.isoformat()),
    )
    assert resaved.status_code == 200, resaved.text
    assert not [
        r for r in resaved.json()["redeploy"] if r["status"] in {"open", "in_progress"}
    ]

    # Nowsza informacja z inną datą = nowy wpis.
    later = today + timedelta(days=50)
    moved = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        headers=headers(tcm),
        json={
            "occurred_on": today.isoformat(),
            "channel": "phone",
            "project_end_on": later.isoformat(),
        },
    )
    active = [r for r in moved.json()["redeploy"] if r["status"] == "open"]
    assert [(r["reason"], r["due_on"]) for r in active] == [
        ("project_end", later.isoformat())
    ]

    reopen = await app_client.patch(
        f"/api/care/redeploy/{item['id']}",
        headers=headers(tcm),
        json={"status": "open"},
    )
    assert reopen.status_code == 409


async def test_closed_decisions_newest_first_and_reopen(app_client, care_on) -> None:
    """Audyt 22.10, F107 (decyzja Artura): „Decyzje zamknięte” w Konsultantach
    pokazują najpierw ostatnio zamknięte, „Otwórz ponownie” wraca wpis na
    „W toku” i zdejmuje go z listy zamkniętych."""

    tcm = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    first_contract, _ = await make_contract(client_id)
    second_contract, _ = await make_contract(client_id)
    today = business_today()
    ids = []
    for contract_id, due_on in (
        (first_contract, (today - timedelta(days=400)).isoformat()),
        (second_contract, None),
    ):
        created = await app_client.post(
            f"/api/care/contracts/{contract_id}/redeploy",
            headers=headers(tcm),
            json={"reason": "wants_change", "due_on": due_on},
        )
        assert created.status_code == 201, created.text
        ids.append(created.json()["id"])
    for item_id in ids:
        closed = await app_client.patch(
            f"/api/care/redeploy/{item_id}",
            headers=headers(tcm),
            json={"status": "dismissed"},
        )
        assert closed.status_code == 200, closed.text

    listing = await app_client.get(
        "/api/care/redeploy?state=closed", headers=headers(tcm)
    )
    assert listing.status_code == 200, listing.text
    order = [row["id"] for row in listing.json()["items"] if row["id"] in ids]
    # Zamknięty później (bez terminu) przed zamkniętym wcześniej z dawnym terminem.
    assert order == [ids[1], ids[0]]

    reopened = await app_client.patch(
        f"/api/care/redeploy/{ids[0]}",
        headers=headers(tcm),
        json={"status": "in_progress"},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "in_progress"
    assert reopened.json()["resolved_at"] is None
    after = await app_client.get(
        "/api/care/redeploy?state=closed", headers=headers(tcm)
    )
    assert ids[0] not in [row["id"] for row in after.json()["items"]]


# ── Karta technologiczna i kolejka technologii ──────────────────────────────


async def test_card_validation_refuses_incomplete_or_foreign_data(
    app_client, care_on
) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    other_client = await make_client()
    contract_id, _ = await make_contract(client_id)
    url = f"/api/care/contracts/{contract_id}/tech-cards"

    no_status = await app_client.post(
        url, headers=headers(tcm), json=_card(status=None, skill_names=["Java"])
    )
    assert no_status.status_code == 422
    no_tech = await app_client.post(url, headers=headers(tcm), json=_card())
    assert no_tech.status_code == 422
    area = await app_client.post(
        f"/api/care/clients/{other_client}/areas",
        headers=headers(tcm),
        json={"name": "Płatności"},
    )
    foreign_area = await app_client.post(
        url,
        headers=headers(tcm),
        json=_card(skill_names=["Java"], client_area_id=area.json()["id"]),
    )
    assert foreign_area.status_code == 422
    source_without_hiring = await app_client.post(
        url,
        headers=headers(tcm),
        json=_card(skill_names=["Java"], hiring=False, hiring_source="plotka"),
    )
    assert source_without_hiring.status_code == 422
    draft = await app_client.post(
        url, headers=headers(tcm), json=_card(finalize=False, status=None)
    )
    assert draft.status_code == 201, draft.text
    assert draft.json()["tech_cards"][0]["is_draft"] is True


async def test_unknown_technology_waits_for_review_and_mapping_links_the_card(
    app_client, care_on
) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    dl = await make_user(UserRole.delivery_lead)
    admin = await make_user(UserRole.admin)
    client_id = await make_client(dl=dl)
    contract_id, _ = await make_contract(client_id)
    known_id, known_name = await make_skill("znana")
    target_id, _target = await make_skill("cel")
    unknown = f"Platforma Testowa {_tag()}"

    created = await app_client.post(
        f"/api/care/contracts/{contract_id}/tech-cards",
        headers=headers(tcm),
        json=_card(
            skill_names=[known_name.upper(), unknown],
            new_area_name="Płatności",
            new_vendor_names=["Dostawca A"],
        ),
    )
    assert created.status_code == 201, created.text
    card = created.json()["tech_cards"][0]
    assert [s["id"] for s in card["skills"]] == [known_id]
    assert card["unrecognized_skills"] == [unknown.lower()]
    assert card["area"]["name"] == "Płatności"
    assert [v["name"] for v in card["vendors"]] == ["Dostawca A"]

    resaved = await app_client.put(
        f"/api/care/tech-cards/{card['id']}",
        headers=headers(tcm),
        json=_card(skill_names=[known_name, unknown]),
    )
    assert resaved.status_code == 200
    async with AsyncSessionLocal() as db:
        review = await db.scalar(
            select(SkillReviewItem).where(SkillReviewItem.name_key == unknown.lower())
        )
        assert review.status == "open"
        assert review.occurrences == 1

    queue = await app_client.get("/api/care/skill-review", headers=headers(dl))
    assert queue.status_code == 200
    assert queue.json()["can_curate"] is False
    assert review.id in {item["id"] for item in queue.json()["items"]}

    refused = await app_client.post(
        f"/api/care/skill-review/{review.id}/map",
        headers=headers(dl),
        json={"skill_id": target_id},
    )
    assert refused.status_code == 403

    mapped = await app_client.post(
        f"/api/care/skill-review/{review.id}/map",
        headers=headers(admin),
        json={"skill_id": target_id},
    )
    assert mapped.status_code == 200, mapped.text
    overview = (
        await app_client.get(f"/api/care/contracts/{contract_id}", headers=headers(tcm))
    ).json()
    card = overview["tech_cards"][0]
    assert {s["id"] for s in card["skills"]} == {known_id, target_id}
    assert card["unrecognized_skills"] == []
    async with AsyncSessionLocal() as db:
        alias = await db.scalar(
            select(SkillAlias).where(SkillAlias.alias == unknown.lower())
        )
        assert alias is not None and alias.skill_id == target_id

    twice = await app_client.post(
        f"/api/care/skill-review/{review.id}/map",
        headers=headers(admin),
        json={"skill_id": target_id},
    )
    assert twice.status_code == 409

    # Ta sama nazwa na nowej karcie trafia od razu w słownik (alias).
    other_contract, _ = await make_contract(client_id)
    direct = await app_client.post(
        f"/api/care/contracts/{other_contract}/tech-cards",
        headers=headers(tcm),
        json=_card(skill_names=[unknown]),
    )
    assert [s["id"] for s in direct.json()["tech_cards"][0]["skills"]] == [target_id]


async def test_review_can_create_a_new_skill_or_dismiss(app_client, care_on) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id)
    first = f"Nowa Technologia {_tag()}"
    second = f"Szum {_tag()}"
    created = await app_client.post(
        f"/api/care/contracts/{contract_id}/tech-cards",
        headers=headers(tcm),
        json=_card(skill_names=[first, second]),
    )
    assert created.status_code == 201, created.text
    async with AsyncSessionLocal() as db:
        items = {
            row.name_key: row.id
            for row in (
                await db.scalars(
                    select(SkillReviewItem).where(
                        SkillReviewItem.name_key.in_([first.lower(), second.lower()])
                    )
                )
            ).all()
        }

    made = await app_client.post(
        f"/api/care/skill-review/{items[first.lower()]}/create",
        headers=headers(tcm),
        json={"canonical_name": first, "category": "tools"},
    )
    assert made.status_code == 200, made.text
    dropped = await app_client.post(
        f"/api/care/skill-review/{items[second.lower()]}/dismiss", headers=headers(tcm)
    )
    assert dropped.status_code == 200

    card = (
        await app_client.get(f"/api/care/contracts/{contract_id}", headers=headers(tcm))
    ).json()["tech_cards"][0]
    assert [s["id"] for s in card["skills"]] == [made.json()["skill_id"]]
    assert card["unrecognized_skills"] == [second.lower()]

    duplicate = await app_client.post(
        f"/api/care/skill-review/{items[second.lower()]}/create",
        headers=headers(tcm),
        json={"canonical_name": first},
    )
    assert duplicate.status_code == 409


# ── Mapa klienta ────────────────────────────────────────────────────────────


async def test_tech_map_combines_four_sources(app_client, care_on) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    contract_id, candidate_id = await make_contract(client_id)
    card_skill, card_name = await make_skill("kartowa")
    job_skill, job_name = await make_skill("rekrutacyjna")
    consultant_skill, consultant_name = await make_skill("konsultancka")
    note_skill, note_name = await make_skill("notatkowa")
    async with AsyncSessionLocal() as db:
        db.add(
            Job(
                title=f"Programista {_tag()}",
                status=JobStatus.published,
                client_id=client_id,
                must_skills=[{"name": job_name}, {"name": card_name}],
                nice_skills=["Nieznana Rzecz"],
            )
        )
        db.add(
            CandidateSkillUsage(
                candidate_id=candidate_id,
                skill_canonical=consultant_name,
                skill_raw=consultant_name,
                months=24,
                provenance="cv",
            )
        )
        await db.commit()

    created = await app_client.post(
        f"/api/care/contracts/{contract_id}/tech-cards",
        headers=headers(dl),
        json=_card(
            skill_ids=[card_skill],
            new_area_name="Data",
            hiring=True,
            hiring_source="widzial",
            hiring_roles=["Analityk"],
        ),
    )
    assert created.status_code == 201, created.text

    url = f"/api/care/clients/{client_id}/tech-map"
    first = await app_client.get(url, headers=headers(dl))
    assert first.status_code == 200, first.text
    by_id = {row["skill_id"]: row for row in first.json()["technologies"]}
    assert by_id[card_skill]["counts"] == {
        "cards": 1,
        "jobs": 1,
        "consultants": 0,
        "notes": 0,
    }
    assert by_id[card_skill]["areas"] == ["Data"]
    assert by_id[job_skill]["counts"]["jobs"] == 1
    assert by_id[job_skill]["must_jobs"] == 1
    assert by_id[consultant_skill]["counts"]["consultants"] == 1
    assert by_id[consultant_skill]["consultant_months"] == 24
    assert note_skill not in by_id
    assert first.json()["open_jobs_count"] == 1
    assert first.json()["consultants_count"] == 1
    assert first.json()["signals"][0]["roles"] == ["Analityk"]
    # Mapa cieplna: karta w dziale „Data”, otwarta rekrutacja bez działu.
    heat = {row["skill_id"]: row for row in first.json()["heatmap"]["rows"]}
    assert [d["area"]["name"] for d in first.json()["departments"]] == ["Data"]
    assert heat[card_skill]["cells"][0]["counts"]["cards"] == 1
    assert heat[card_skill]["cells"][0]["open_jobs"] == 0
    assert heat[card_skill]["unassigned"]["counts"]["jobs"] == 1
    assert heat[card_skill]["unassigned"]["open_jobs"] == 1
    assert first.json()["open_jobs"][0]["area"] is None

    note = await app_client.post(
        f"/api/care/clients/{client_id}/stack-notes",
        headers=headers(dl),
        json={"content": f"Zespół Data przechodzi na {note_name} i {card_name}."},
    )
    assert note.status_code == 201, note.text
    second = await app_client.get(url, headers=headers(dl))
    by_id = {row["skill_id"]: row for row in second.json()["technologies"]}
    assert by_id[note_skill]["counts"]["notes"] == 1
    assert by_id[card_skill]["source_count"] == 3
    assert second.json()["technologies"][0]["skill_id"] == card_skill


# ── ATLAS ───────────────────────────────────────────────────────────────────


ATLAS = "/api/care/atlas/sales-signals"


async def test_atlas_signals_need_the_sales_signals_scope(
    app_client: AsyncClient, app_auth_headers: dict, care_on
) -> None:
    from tests.test_service_accounts import _account_with_key

    tcm = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id)
    skill_id, _name = await make_skill("sygnal")
    hiring = await app_client.post(
        f"/api/care/contracts/{contract_id}/tech-cards",
        headers=headers(tcm),
        json=_card(
            skill_ids=[skill_id],
            hiring=True,
            hiring_source="slyszal",
            hiring_roles=["Tester"],
        ),
    )
    card_id = hiring.json()["tech_cards"][0]["id"]
    draft = await app_client.post(
        f"/api/care/contracts/{contract_id}/tech-cards",
        headers=headers(tcm),
        json=_card(finalize=False, status=None, hiring=True),
    )
    draft_id = next(c["id"] for c in draft.json()["tech_cards"] if c["is_draft"])

    anonymous = await app_client.get(ATLAS)
    assert anonymous.status_code == 401
    as_tcm = await app_client.get(ATLAS, headers=headers(tcm))
    assert as_tcm.status_code == 403

    # Dawny zestaw Compassa (klienci + kontrakty) nie otwiera sygnałów.
    _, narrow_key, _ = await _account_with_key(
        app_client, app_auth_headers, ["clients:read", "contracts:read"]
    )
    narrow = await app_client.get(ATLAS, headers={"X-API-Key": narrow_key})
    assert narrow.status_code == 403

    _, key, _ = await _account_with_key(
        app_client, app_auth_headers, ["sales_signals:read"]
    )
    ok = await app_client.get(ATLAS, headers={"X-API-Key": key})
    assert ok.status_code == 200, ok.text
    ids = {signal["id"] for signal in ok.json()["signals"]}
    assert card_id in ids and draft_id not in ids
    signal = next(s for s in ok.json()["signals"] if s["id"] == card_id)
    assert signal["hiring_roles"] == ["Tester"]
    assert "consultant_email" not in signal
    assert ok.json()["count"] == len(ok.json()["signals"])

    bad_since = await app_client.get(
        f"{ATLAS}?since=wczoraj", headers={"X-API-Key": key}
    )
    assert bad_since.status_code == 422

    await set_modules({key_: False for key_ in HR_MODULE_KEYS})
    switched_off = await app_client.get(ATLAS, headers={"X-API-Key": key})
    assert switched_off.status_code == 404
    admin_jwt = await app_client.get(ATLAS, headers=app_auth_headers)
    assert admin_jwt.status_code == 200


async def test_atlas_status_updates_card_and_ignores_stale_ones(
    app_client: AsyncClient, app_auth_headers: dict, care_on
) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id)
    skill_id, _name = await make_skill("status")
    created = await app_client.post(
        f"/api/care/contracts/{contract_id}/tech-cards",
        headers=headers(tcm),
        json=_card(skill_ids=[skill_id], hiring=True, hiring_source="plotka"),
    )
    card_id = created.json()["tech_cards"][0]["id"]
    url = f"{ATLAS}/status"
    payload = {
        "updates": [
            {
                "signal_id": str(card_id),
                "status": "converted",
                "handled_at": "2026-10-10T10:00:00Z",
                "deal_title": "Szansa A",
            },
            {
                "signal_id": "nie-istnieje",
                "status": "archived",
                "handled_at": "2026-10-10T10:00:00Z",
            },
        ]
    }
    denied = await app_client.post(url, headers=headers(tcm), json=payload)
    assert denied.status_code == 403
    from tests.test_service_accounts import _account_with_key

    _, read_key, _ = await _account_with_key(
        app_client, app_auth_headers, ["sales_signals:read"]
    )
    read_only = await app_client.post(
        url, headers={"X-API-Key": read_key}, json=payload
    )
    assert read_only.status_code == 403
    _, write_key, _ = await _account_with_key(
        app_client, app_auth_headers, ["sales_signals:write"]
    )
    by_key = await app_client.post(
        url,
        headers={"X-API-Key": write_key},
        json={"updates": []},
    )
    assert by_key.status_code == 200, by_key.text
    accepted = await app_client.post(url, headers=app_auth_headers, json=payload)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {
        "accepted": 1,
        "ignored_stale": 0,
        "unknown": ["nie-istnieje"],
    }
    stale = await app_client.post(
        url,
        headers=app_auth_headers,
        json={
            "updates": [
                {
                    "signal_id": str(card_id),
                    "status": "archived",
                    "handled_at": "2026-10-01T10:00:00Z",
                }
            ]
        },
    )
    assert stale.json()["ignored_stale"] == 1
    async with AsyncSessionLocal() as db:
        card = await db.get(TechCard, card_id)
        assert (card.sales_status, card.sales_deal_title) == ("converted", "Szansa A")
        assert (
            await db.scalar(
                select(RedeployQueueItem.id).where(
                    RedeployQueueItem.contract_id == contract_id
                )
            )
            is None
        )
