"""Mapa decyzyjna szansy: dodanie, poprawka, usunięcie osoby, historia, kontakt, import."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.sales import (
    SalesContact,
    SalesOpportunity,
    SalesOpportunityEvent,
    SalesPipeline,
    SalesPipelineStage,
)
from app.services.sales.decision_map import IT_FACTORIES_PIPELINE_KEY
from tests.test_sales_atlas_import_gaps import (
    LATER,
    FakeAtlas,
    _import,
    _one,
    _sales_pipeline,
)
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_opportunities_api import URL, _company, _stages


async def _factories_pipeline() -> tuple[int, int]:
    """Lejek Fabryki IT jak po imporcie z Atlasa (baza testowa jest wspólna)."""

    async with AsyncSessionLocal() as db:
        pipeline = await db.scalar(
            select(SalesPipeline).where(SalesPipeline.key == IT_FACTORIES_PIPELINE_KEY)
        )
        if pipeline is None:
            pipeline = SalesPipeline(key=IT_FACTORIES_PIPELINE_KEY, name="Fabryki IT")
            db.add(pipeline)
            await db.flush()
            db.add(
                SalesPipelineStage(
                    pipeline_id=pipeline.id,
                    key="itf-first",
                    name="Pierwszy kontakt",
                    position=1,
                    probability=10,
                    outcome="open",
                )
            )
            await db.commit()
        stage_id = await db.scalar(
            select(SalesPipelineStage.id).where(
                SalesPipelineStage.pipeline_id == pipeline.id
            )
        )
        return pipeline.id, stage_id


async def _opportunity(
    app_client, user, map_entries: Optional[list[dict[str, Any]]] = None
) -> tuple[int, int]:
    """Szansa w lejku Fabryki IT; ``map_entries`` jak z importu Atlasa."""

    company_id = await _company(app_client, user)
    pipeline_id, stage_id = await _factories_pipeline()
    custom = (
        {"atlas": {"it_factory": {"decision_map": map_entries, "next_step": "Telefon"}}}
        if map_entries is not None
        else {}
    )
    async with AsyncSessionLocal() as db:
        opp = SalesOpportunity(
            company_id=company_id,
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            title="Fabryka testowa",
            status="open",
            custom_fields=custom,
        )
        db.add(opp)
        await db.commit()
        return opp.id, company_id


def _map(detail: dict[str, Any]) -> list[dict[str, Any]]:
    return detail["atlas_motion"]["it_factory"]["decision_map"]


async def _events(opportunity_id: int) -> list[SalesOpportunityEvent]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(SalesOpportunityEvent)
                    .where(SalesOpportunityEvent.opportunity_id == opportunity_id)
                    .order_by(SalesOpportunityEvent.id)
                )
            ).scalars()
        )


@pytest.mark.asyncio
async def test_add_person_to_empty_map_records_history(app_client) -> None:
    rep = await _user("sales_edit")
    opportunity_id, _ = await _opportunity(app_client, rep)

    detail = (
        await app_client.get(f"{URL}/{opportunity_id}", headers=_headers(rep))
    ).json()
    assert detail["atlas_motion"] is None
    assert detail["decision_map_enabled"] is True

    resp = await app_client.post(
        f"{URL}/{opportunity_id}/decision-map",
        json={
            "name": "  Osoba Testowa  ",
            "role_in_company": "CIO",
            "decision_level": 1,
            "our_role": "champion",
            "last_contact_at": "2026-10-30",
            "email": "Osoba@Example.COM",
            "linkedin_url": "linkedin.com/in/osoba",
        },
        headers=_headers(rep),
    )
    assert resp.status_code == 201, resp.text
    [entry] = _map(resp.json())
    assert entry["name"] == "Osoba Testowa"
    assert entry["contact_status"] == "not_contacted"
    assert entry["last_contact_at"] == "2026-10-30"
    assert entry["email"] == "osoba@example.com"
    assert entry["linkedin_url"] == "https://linkedin.com/in/osoba"
    assert entry["key"]

    [event] = await _events(opportunity_id)
    assert (event.kind, event.field, event.user_id) == (
        "updated",
        "decision_map",
        rep.id,
    )
    assert event.old_value is None
    assert "Osoba Testowa" in event.new_value and "Champion" in event.new_value


@pytest.mark.asyncio
async def test_update_keeps_atlas_keys_and_records_only_changed_fields(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    opportunity_id, _ = await _opportunity(
        app_client,
        rep,
        [
            {
                "name": "Osoba Atlas",
                "contact_id": str(uuid.uuid4()),
                "linkedin_url": "ftp://stary-adres",
                "notes": None,
                "contact_status": "in_progress",
            }
        ],
    )
    detail = (
        await app_client.get(f"{URL}/{opportunity_id}", headers=_headers(rep))
    ).json()
    [before] = _map(detail)

    # Zły adres z Atlasa nie blokuje poprawki innego pola.
    resp = await app_client.patch(
        f"{URL}/{opportunity_id}/decision-map/{before['key']}",
        json={"notes": "Zna budżet", "contact_status": "in_progress"},
        headers=_headers(rep),
    )
    assert resp.status_code == 200, resp.text
    [after] = _map(resp.json())
    assert after["notes"] == "Zna budżet"
    assert after["key"] != before["key"]

    async with AsyncSessionLocal() as db:
        opp = await db.get(SalesOpportunity, opportunity_id)
        factory = opp.custom_fields["atlas"]["it_factory"]
    [stored] = factory["decision_map"]
    assert stored["contact_id"] == before["contact_id"]
    assert "key" not in stored and "from_contact" not in stored
    assert factory["next_step"] == "Telefon"
    assert factory["nexus_updated_by_user_id"] == rep.id

    [event] = await _events(opportunity_id)
    assert event.old_value == "Osoba Atlas — notatka: —"
    assert event.new_value == "Osoba Atlas — notatka: Zna budżet"


@pytest.mark.asyncio
async def test_update_without_change_writes_nothing(app_client) -> None:
    rep = await _user("sales_edit")
    opportunity_id, _ = await _opportunity(app_client, rep, [{"name": "Bez Zmian"}])
    detail = (
        await app_client.get(f"{URL}/{opportunity_id}", headers=_headers(rep))
    ).json()
    key = _map(detail)[0]["key"]
    resp = await app_client.patch(
        f"{URL}/{opportunity_id}/decision-map/{key}",
        json={"name": "Bez Zmian"},
        headers=_headers(rep),
    )
    assert resp.status_code == 200, resp.text
    assert _map(resp.json())[0]["key"] == key
    assert await _events(opportunity_id) == []


@pytest.mark.asyncio
async def test_stale_key_is_a_conflict_and_changes_nothing(app_client) -> None:
    rep = await _user("sales_edit")
    opportunity_id, _ = await _opportunity(app_client, rep, [{"name": "Osoba Raz"}])
    detail = (
        await app_client.get(f"{URL}/{opportunity_id}", headers=_headers(rep))
    ).json()
    stale = _map(detail)[0]["key"]
    first = await app_client.patch(
        f"{URL}/{opportunity_id}/decision-map/{stale}",
        json={"notes": "Pierwsza zmiana"},
        headers=_headers(rep),
    )
    assert first.status_code == 200, first.text

    for resp in (
        await app_client.patch(
            f"{URL}/{opportunity_id}/decision-map/{stale}",
            json={"notes": "Druga zmiana"},
            headers=_headers(rep),
        ),
        await app_client.delete(
            f"{URL}/{opportunity_id}/decision-map/{stale}", headers=_headers(rep)
        ),
    ):
        assert resp.status_code == 409, resp.text
        assert "Ktoś właśnie zmienił" in resp.json()["detail"]

    detail = (
        await app_client.get(f"{URL}/{opportunity_id}", headers=_headers(rep))
    ).json()
    assert [e["notes"] for e in _map(detail)] == ["Pierwsza zmiana"]


@pytest.mark.asyncio
async def test_identical_people_have_own_keys_and_delete_removes_one(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    twin = {"name": "Osoba Bliźniak"}
    opportunity_id, _ = await _opportunity(app_client, rep, [dict(twin), dict(twin)])
    detail = (
        await app_client.get(f"{URL}/{opportunity_id}", headers=_headers(rep))
    ).json()
    keys = [entry["key"] for entry in _map(detail)]
    assert len(set(keys)) == 2

    resp = await app_client.delete(
        f"{URL}/{opportunity_id}/decision-map/{keys[1]}", headers=_headers(rep)
    )
    assert resp.status_code == 200, resp.text
    assert [entry["name"] for entry in _map(resp.json())] == ["Osoba Bliźniak"]
    [event] = await _events(opportunity_id)
    assert (event.old_value, event.new_value) == ("Osoba Bliźniak", None)


@pytest.mark.parametrize(
    "body",
    [
        {"name": "   "},
        {"name": "x" * 256},
        {"name": "Ok", "decision_level": 5},
        {"name": "Ok", "decision_level": 0},
        {"name": "Ok", "our_role": "sponsor"},
        {"name": "Ok", "contact_status": "cold"},
        {"name": "Ok", "linkedin_url": "javascript:alert(1)"},
        {"name": "Ok", "email": "bez-malpy"},
        {"name": "Ok", "notes": "x" * 2001},
        {"name": "Ok", "nexus_contact_id": 1},
        {"name": "Ok", "contact_id": "atlas"},
    ],
)
@pytest.mark.asyncio
async def test_invalid_person_is_rejected(app_client, body: dict[str, Any]) -> None:
    rep = await _user("sales_edit")
    opportunity_id, _ = await _opportunity(app_client, rep)
    resp = await app_client.post(
        f"{URL}/{opportunity_id}/decision-map", json=body, headers=_headers(rep)
    )
    assert resp.status_code == 422, resp.text
    assert await _events(opportunity_id) == []


@pytest.mark.parametrize("body", [{"name": None}, {"contact_status": None}])
@pytest.mark.asyncio
async def test_update_cannot_clear_required_fields(
    app_client, body: dict[str, Any]
) -> None:
    rep = await _user("sales_edit")
    opportunity_id, _ = await _opportunity(app_client, rep, [{"name": "Osoba"}])
    detail = (
        await app_client.get(f"{URL}/{opportunity_id}", headers=_headers(rep))
    ).json()
    resp = await app_client.patch(
        f"{URL}/{opportunity_id}/decision-map/{_map(detail)[0]['key']}",
        json=body,
        headers=_headers(rep),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_view_only_user_cannot_write_the_map(app_client) -> None:
    rep = await _user("sales_edit")
    viewer = await _user("sales_view")
    opportunity_id, _ = await _opportunity(app_client, rep, [{"name": "Osoba"}])
    detail = (
        await app_client.get(f"{URL}/{opportunity_id}", headers=_headers(viewer))
    ).json()
    assert detail["decision_map_enabled"] is True
    key = _map(detail)[0]["key"]
    for resp in (
        await app_client.post(
            f"{URL}/{opportunity_id}/decision-map",
            json={"name": "Nowa"},
            headers=_headers(viewer),
        ),
        await app_client.patch(
            f"{URL}/{opportunity_id}/decision-map/{key}",
            json={"notes": "x"},
            headers=_headers(viewer),
        ),
        await app_client.delete(
            f"{URL}/{opportunity_id}/decision-map/{key}", headers=_headers(viewer)
        ),
    ):
        assert resp.status_code == 403, resp.text
    assert await _events(opportunity_id) == []


@pytest.mark.asyncio
async def test_other_pipeline_has_no_map(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _company(app_client, rep)
    stages = await _stages(app_client, rep)
    created = await app_client.post(
        URL,
        json={"company_id": company_id, "title": "Zwykła", "stage_id": stages["lead"]},
        headers=_headers(rep),
    )
    assert created.status_code == 201, created.text
    assert created.json()["decision_map_enabled"] is False
    resp = await app_client.post(
        f"{URL}/{created.json()['id']}/decision-map",
        json={"name": "Osoba"},
        headers=_headers(rep),
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_saving_fills_only_empty_contact_fields(app_client) -> None:
    rep = await _user("sales_edit")
    opportunity_id, company_id = await _opportunity(app_client, rep)
    async with AsyncSessionLocal() as db:
        contact = SalesContact(
            company_id=company_id,
            full_name="Osoba Kontakt",
            email="stary@example.com",
            mobile_phone="+48 600 000 000",
        )
        db.add(contact)
        await db.commit()
        contact_id = contact.id

    resp = await app_client.post(
        f"{URL}/{opportunity_id}/decision-map",
        json={
            "name": "Osoba Kontakt",
            "email": "nowy@example.com",
            "phone": "+48 500 000 000",
            "linkedin_url": "https://linkedin.com/in/kontakt",
            "notes": "Notatka z mapy",
            "role_in_company": "CTO",
        },
        headers=_headers(rep),
    )
    assert resp.status_code == 201, resp.text
    [entry] = _map(resp.json())
    assert entry["nexus_contact_id"] == contact_id
    assert entry["email"] == "nowy@example.com"
    assert entry["from_contact"] == []

    async with AsyncSessionLocal() as db:
        contact = await db.get(SalesContact, contact_id)
    assert contact.email == "stary@example.com"
    assert contact.phone is None and contact.mobile_phone == "+48 600 000 000"
    assert contact.linkedin_url == "https://linkedin.com/in/kontakt"
    assert contact.notes == "Notatka z mapy"
    assert contact.title is None

    events = await _events(opportunity_id)
    assert [event.field for event in events] == ["decision_map", "decision_map_contact"]
    assert events[1].new_value == "Osoba Kontakt: LinkedIn, notatka"


@pytest.mark.asyncio
async def test_too_long_email_stays_on_the_map_and_archived_contact_is_left_alone(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    opportunity_id, company_id = await _opportunity(app_client, rep)
    long_email = f"{'a' * 300}@example.com"
    async with AsyncSessionLocal() as db:
        fresh = SalesContact(company_id=company_id, full_name="Osoba Długa")
        archived = SalesContact(
            company_id=company_id,
            full_name="Osoba Archiwum",
            archived_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        db.add_all([fresh, archived])
        await db.commit()
        fresh_id, archived_id = fresh.id, archived.id

    for body in (
        {"name": "Osoba Długa", "email": long_email},
        {"name": "Osoba Archiwum", "phone": "+48 500 000 000"},
    ):
        resp = await app_client.post(
            f"{URL}/{opportunity_id}/decision-map", json=body, headers=_headers(rep)
        )
        assert resp.status_code == 201, resp.text

    async with AsyncSessionLocal() as db:
        assert (await db.get(SalesContact, fresh_id)).email is None
        assert (await db.get(SalesContact, archived_id)).phone is None


@pytest.mark.asyncio
async def test_values_from_contact_are_marked_and_not_stored_on_the_map(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    opportunity_id, company_id = await _opportunity(
        app_client, rep, [{"name": "Osoba Z Kontaktu", "notes": "Z mapy"}]
    )
    async with AsyncSessionLocal() as db:
        db.add(
            SalesContact(
                company_id=company_id,
                full_name="Osoba Z Kontaktu",
                email="kontakt@example.com",
                notes="Z kontaktu",
            )
        )
        await db.commit()
    detail = (
        await app_client.get(f"{URL}/{opportunity_id}", headers=_headers(rep))
    ).json()
    [entry] = _map(detail)
    assert entry["email"] == "kontakt@example.com"
    assert entry["notes"] == "Z mapy"
    assert entry["from_contact"] == ["email"]


@pytest.mark.asyncio
async def test_reimport_keeps_edited_map_and_refreshes_untouched_one(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    tag = uuid.uuid4().hex[:8]
    edited_ref, untouched_ref = f"atlas:deals:d1-{tag}", f"atlas:deals:d2-{tag}"

    def atlas(person: str) -> FakeAtlas:
        def deal(number: int) -> dict[str, Any]:
            return {
                "id": f"d{number}-{tag}",
                "title": f"Fabryka {number}",
                "company_id": f"c1-{tag}",
                "stage_id": "stage-lead",
                "status": "open",
                "custom_fields": {
                    "it_factory": {
                        "decision_map": [{"name": person, "contact_id": f"p1-{tag}"}]
                    }
                },
            }

        return FakeAtlas(
            {
                **_sales_pipeline(tag),
                "companies": [{"id": f"c1-{tag}", "name": f"Mapa Import {tag}"}],
                "contacts": [
                    {
                        "id": f"p1-{tag}",
                        "full_name": "Osoba Atlas",
                        "primary_company_id": f"c1-{tag}",
                    }
                ],
                "deals": [deal(1), deal(2)],
            }
        )

    await _import(atlas("Osoba Atlas"))
    opportunity_id = (await _one(SalesOpportunity, edited_ref)).id
    detail = (
        await app_client.get(f"{URL}/{opportunity_id}", headers=_headers(rep))
    ).json()
    resp = await app_client.patch(
        f"{URL}/{opportunity_id}/decision-map/{_map(detail)[0]['key']}",
        json={
            "notes": "Poprawione w NEXUSIE",
            "linkedin_url": "https://linkedin.com/in/osoba",
        },
        headers=_headers(rep),
    )
    assert resp.status_code == 200, resp.text
    contact_ref = f"atlas:contacts:p1-{tag}"
    assert (await _one(SalesContact, contact_ref)).linkedin_url is not None

    await _import(atlas("Osoba Atlas Nowa"), now=LATER)

    edited = (await _one(SalesOpportunity, edited_ref)).custom_fields
    [person] = edited["atlas"]["it_factory"]["decision_map"]
    assert (person["name"], person["notes"]) == ("Osoba Atlas", "Poprawione w NEXUSIE")
    # Kontakt uzupełniony z mapy też przeżywa bieg (Atlas nie ma tam LinkedIna).
    contact = await _one(SalesContact, contact_ref)
    assert contact.linkedin_url == "https://linkedin.com/in/osoba"
    assert contact.notes == "Poprawione w NEXUSIE"

    untouched = (await _one(SalesOpportunity, untouched_ref)).custom_fields
    assert (
        untouched["atlas"]["it_factory"]["decision_map"][0]["name"]
        == "Osoba Atlas Nowa"
    )
