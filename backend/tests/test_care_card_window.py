"""Karta konsultanta i okno rozmowy według makiet (22.10.2026) — trasy na bazie.

* „Co u klienta”: wiersze nieruszone przychodzą jako „same” — karta z rozmowy
  potwierdza stan datą rozmowy, a ślad ``care.client_state_confirmed`` mówi,
  które wiersze potwierdzono, a które zmieniono (makieta P3).
* Sprawa z „Coś do załatwienia?” dostaje w opisie notatkę z rozmowy (S5).
* Sprawy w karcie mają datę zamknięcia i postęp checklisty (S3), a oś —
  „Sprawa otwarta: …” i „Sprawa zamknięta: … 1/2”.

Baza testowa jest wspólna — każdy test zakłada własnych klientów i osoby.
Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.admin_case import AdminCase
from app.models.contract_care import TechCard
from app.models.hr_ops import HrAuditEvent
from app.models.user import UserRole
from tests.test_care_api import _card, headers, make_skill, make_user
from tests.test_care_board import _setup, care_on  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio


async def test_untouched_rows_confirm_state_and_note_goes_to_case(
    app_client,
    care_on,  # noqa: F811
) -> None:
    lead, _client_id, area_id, _manager_id, contract_id, _cand = await _setup()
    admin = await make_user(UserRole.admin)
    skill_id, _ = await make_skill("Scala")
    first = await app_client.post(
        f"/api/care/contracts/{contract_id}/tech-cards",
        json=_card(skill_ids=[skill_id], client_area_id=area_id, team_size="9"),
        headers=headers(lead),
    )
    assert first.status_code == 201, first.text

    resp = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        json={
            "occurred_on": business_today().isoformat(),
            "channel": "phone",
            "note": "Pyta, czy firma pokryje certyfikat chmurowy.",
            "client_state": {
                "confirmed": True,
                "changes": {"team_size": "10"},
                "rows": {
                    "area": "same",
                    "manager": "same",
                    "team": "change",
                    "technologies": "same",
                },
            },
            "cases": [
                {"title": "Dofinansowanie certyfikatu", "area": "administration"}
            ],
        },
        headers=headers(admin),
    )
    assert resp.status_code == 201, resp.text
    saved = resp.json()
    assert (
        saved["tech_card_id"]
        and saved["tech_card_id"] != first.json()["tech_cards"][0]["id"]
    )

    async with AsyncSessionLocal() as db:
        trace = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.entity_type == "contract",
                HrAuditEvent.entity_id == str(contract_id),
                HrAuditEvent.action == "care.client_state_confirmed",
            )
        )
        case = await db.get(AdminCase, saved["case_ids"][0])
    assert trace is not None
    assert trace.details["confirmed"] == ["area", "manager", "technologies"]
    assert trace.details["changed"] == ["team"]
    assert trace.details["tech_card_id"] == saved["tech_card_id"]
    assert case.description.endswith(
        "Notatka z rozmowy:\nPyta, czy firma pokryje certyfikat chmurowy."
    )
    assert f"/care?contract={contract_id}" in case.description

    card = await app_client.get(
        f"/api/care/contracts/{contract_id}/card", headers=headers(lead)
    )
    project = card.json()["known_project"]
    # Stan potwierdzony z datą rozmowy, zmieniony zespół, ta sama technologia.
    assert project["source"]["kind"] == "conversation"
    assert project["team_size"] == "10"
    assert [t["skill_id"] for t in project["technologies"]] == [skill_id]


async def test_rows_must_name_known_fields(app_client, care_on) -> None:  # noqa: F811
    lead, *_rest, contract_id, _cand = await _setup()
    resp = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        json={
            "occurred_on": business_today().isoformat(),
            "client_state": {"confirmed": True, "rows": {"rate": "same"}},
        },
        headers=headers(lead),
    )
    assert resp.status_code == 422, resp.text


async def test_card_cases_have_closing_day_and_checklist(
    app_client,
    care_on,  # noqa: F811
) -> None:
    lead, *_rest, contract_id, _cand = await _setup()
    admin = await make_user(UserRole.admin)
    created = await app_client.post(
        "/api/cases",
        json={
            "title": "Wejście konsultanta",
            "area": "onboarding",
            "contract_id": contract_id,
            "checklist": [
                {"text": "Laptop", "done": True},
                {"text": "Dostęp VPN", "done": False},
            ],
        },
        headers=headers(admin),
    )
    assert created.status_code in (200, 201), created.text
    case_id = created.json()["id"]
    closed_at = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(AdminCase)
            .where(AdminCase.id == case_id)
            .values(status="done", closed_at=closed_at)
        )
        await db.commit()

    card = await app_client.get(
        f"/api/care/contracts/{contract_id}/card", headers=headers(admin)
    )
    assert card.status_code == 200, card.text
    row = next(item for item in card.json()["cases"] if item["id"] == case_id)
    # Zamknięta dziś: data zamknięcia (dzień firmy) i 1/2 checklisty.
    assert row["closed_on"] == business_today().isoformat()
    assert row["checklist_done"] == 1 and row["checklist_total"] == 2

    timeline = await app_client.get(
        f"/api/care/contracts/{contract_id}/timeline", headers=headers(admin)
    )
    titles = [
        e["title"] for e in timeline.json()["events"] if e.get("case_id") == case_id
    ]
    assert "Sprawa otwarta: Wejście konsultanta" in titles
    assert "Sprawa zamknięta: Wejście konsultanta 1/2" in titles


async def test_client_hiring_is_an_event_of_one_conversation(
    app_client,
    care_on,  # noqa: F811
) -> None:
    """Audyt 22.10, F1: „klient zatrudnia” nie przechodzi na kartę z kolejnej
    rozmowy, w której nikt go nie zaznaczył (sygnał popytu by się nie starzał)."""

    _lead, _client_id, area_id, _manager_id, contract_id, _cand = await _setup()
    admin = await make_user(UserRole.admin)
    skill_id, _ = await make_skill("Rust")
    today = business_today()
    first = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        json={
            "occurred_on": (today - timedelta(days=30)).isoformat(),
            "channel": "phone",
            "client_hiring": True,
            "client_state": {
                "confirmed": True,
                "changes": {
                    "skill_ids": [skill_id],
                    "area_id": area_id,
                    "hiring_roles": ["Java Developer"],
                    "hiring_source": "widzial",
                },
            },
        },
        headers=headers(admin),
    )
    assert first.status_code == 201, first.text

    second = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        json={
            "occurred_on": today.isoformat(),
            "channel": "phone",
            "client_state": {
                "confirmed": True,
                "changes": {},
                "rows": {
                    "area": "same",
                    "manager": "same",
                    "team": "same",
                    "technologies": "same",
                },
            },
        },
        headers=headers(admin),
    )
    assert second.status_code == 201, second.text
    card_id = second.json()["tech_card_id"]
    assert card_id and card_id != first.json()["tech_card_id"]

    async with AsyncSessionLocal() as db:
        card = await db.get(TechCard, card_id)
    assert card.hiring is None
    assert not card.hiring_roles
    assert card.hiring_source is None
