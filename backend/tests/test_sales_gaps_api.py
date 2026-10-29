"""Sprzedaż po audycie importu Atlasa (28.10.2026): luki API.

Maile firmy na osi szansy, telefony na liście zadań, „Sales Motion” z Atlasa,
podsumowanie lejka, opiekunowie z Atlasa, duplikaty i scalanie firm, osoba
w kilku firmach, surowe dane leada.

Baza testowa jest wspólna dla przebiegu: nazwy, NIP-y i etykiety niosą losowy
tag, a podsumowanie liczy własny lejek testu.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyContact,
    SalesContact,
    SalesFile,
    SalesLead,
    SalesOpportunity,
    SalesPipeline,
    SalesPipelineStage,
)
from app.models.user import User
from app.services.sales.atlas_import import ATLAS_REVIEW_TAG
from app.services.sales.summary import period_range
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_opportunities_api import _company

ACTIVITIES = "/api/sales/activities"
OPPS = "/api/sales/opportunities"
COMPANIES = "/api/sales/companies"
CONTACTS = "/api/sales/contacts"


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def _nip() -> str:
    return f"{uuid.uuid4().int % 10**10:010d}"


async def _opportunity(app_client, user, company_id: int, **fields) -> dict:
    resp = await app_client.post(
        OPPS,
        json={"company_id": company_id, "title": f"Szansa {_tag()}", **fields},
        headers=_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _add(*rows) -> list[int]:
    async with AsyncSessionLocal() as db:
        db.add_all(rows)
        await db.commit()
        return [row.id for row in rows]


# ── A. Aktywności ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_opportunity_timeline_can_include_company_mail(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _company(app_client, rep)
    opp = await _opportunity(app_client, rep, company_id)
    note = await app_client.post(
        ACTIVITIES,
        json={"kind": "note", "opportunity_id": opp["id"], "subject": "Notatka"},
        headers=_headers(rep),
    )
    assert note.status_code == 201, note.text
    now = datetime.now(timezone.utc)
    mail_id, _manual_id = await _add(
        SalesActivity(
            kind="email",
            company_id=company_id,
            subject="Mail z Outlooka",
            occurred_at=now - timedelta(days=1),
            done_at=now - timedelta(days=1),
            external_source="msgraph-mail",
            web_link="https://outlook.example.com/m/1",
            direction="in",
            duration_minutes=None,
        ),
        SalesActivity(
            kind="note",
            company_id=company_id,
            subject="Notatka firmy",
            occurred_at=now,
        ),
    )

    plain = (
        await app_client.get(
            ACTIVITIES, params={"opportunity_id": opp["id"]}, headers=_headers(rep)
        )
    ).json()
    assert [a["subject"] for a in plain] == ["Notatka"]
    assert plain[0]["from_company"] is False

    with_mail = (
        await app_client.get(
            ACTIVITIES,
            params={"opportunity_id": opp["id"], "with_company_mail": "true"},
            headers=_headers(rep),
        )
    ).json()
    assert [a["subject"] for a in with_mail] == ["Notatka", "Mail z Outlooka"]
    mail = with_mail[1]
    assert mail["id"] == mail_id
    assert (mail["from_company"], mail["direction"], mail["external_source"]) == (
        True,
        "in",
        "msgraph-mail",
    )
    assert mail["web_link"] == "https://outlook.example.com/m/1"

    paged = (
        await app_client.get(
            ACTIVITIES,
            params={
                "opportunity_id": opp["id"],
                "with_company_mail": "true",
                "limit": 1,
                "offset": 1,
            },
            headers=_headers(rep),
        )
    ).json()
    assert [a["id"] for a in paged] == [mail_id]


@pytest.mark.asyncio
async def test_tasks_include_calls_with_due_date_and_complete_in_bulk(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    viewer = await _user("sales_view")
    company_id = await _company(app_client, rep)
    opp = await _opportunity(app_client, rep, company_id)
    due = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    call = (
        await app_client.post(
            ACTIVITIES,
            json={
                "kind": "call",
                "opportunity_id": opp["id"],
                "subject": "Oddzwonić do CTO",
                "due_at": due,
            },
            headers=_headers(rep),
        )
    ).json()
    assert call["assignee"]["id"] == rep.id
    assert call["done_at"] is None
    logged = (
        await app_client.post(
            ACTIVITIES,
            json={"kind": "call", "company_id": company_id, "subject": "Rozmowa"},
            headers=_headers(rep),
        )
    ).json()
    assert logged["done_at"] is not None
    task = (
        await app_client.post(
            ACTIVITIES,
            json={
                "kind": "task",
                "company_id": company_id,
                "subject": "Oferta",
                "due_at": due,
            },
            headers=_headers(rep),
        )
    ).json()

    mine = (await app_client.get(f"{ACTIVITIES}/tasks", headers=_headers(rep))).json()
    assert mine["total"] == 2
    assert {t["id"] for t in mine["items"]} == {call["id"], task["id"]}
    calls = (
        await app_client.get(
            f"{ACTIVITIES}/tasks", params={"kind": "call"}, headers=_headers(rep)
        )
    ).json()
    assert [t["id"] for t in calls["items"]] == [call["id"]]
    first = (
        await app_client.get(
            f"{ACTIVITIES}/tasks",
            params={"limit": 1, "offset": 1},
            headers=_headers(rep),
        )
    ).json()
    assert first["total"] == 2 and len(first["items"]) == 1

    refused = await app_client.post(
        f"{ACTIVITIES}/tasks/complete",
        json={"ids": [call["id"]]},
        headers=_headers(viewer),
    )
    assert refused.status_code == 403
    done = await app_client.post(
        f"{ACTIVITIES}/tasks/complete",
        json={"ids": [call["id"], task["id"], logged["id"]]},
        headers=_headers(rep),
    )
    assert done.json() == {"updated": 2}
    again = await app_client.post(
        f"{ACTIVITIES}/tasks/complete",
        json={"ids": [call["id"]]},
        headers=_headers(rep),
    )
    assert again.json() == {"updated": 0}
    assert (await app_client.get(f"{ACTIVITIES}/tasks", headers=_headers(rep))).json()[
        "total"
    ] == 0
    touched = (
        await app_client.get(f"{OPPS}/{opp['id']}", headers=_headers(rep))
    ).json()
    assert touched["last_activity_at"] is not None


@pytest.mark.asyncio
async def test_activity_is_edited_by_its_author_or_admin(app_client) -> None:
    rep = await _user("sales_edit")
    other = await _user("sales_edit")
    admin = await _user(role="admin")
    company_id = await _company(app_client, rep)
    note = (
        await app_client.post(
            ACTIVITIES,
            json={"kind": "note", "company_id": company_id, "subject": "Notatka"},
            headers=_headers(rep),
        )
    ).json()
    refused = await app_client.patch(
        f"{ACTIVITIES}/{note['id']}", json={"subject": "X"}, headers=_headers(other)
    )
    assert refused.status_code == 403

    due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    edited = await app_client.patch(
        f"{ACTIVITIES}/{note['id']}",
        json={
            "kind": "call",
            "subject": "Telefon",
            "body": "Treść",
            "due_at": due,
            "occurred_at": None,
            "assignee_user_id": other.id,
        },
        headers=_headers(rep),
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert (body["kind"], body["subject"], body["body"]) == ("call", "Telefon", "Treść")
    assert body["assignee"]["id"] == other.id
    assert body["due_at"] is not None

    by_admin = await app_client.patch(
        f"{ACTIVITIES}/{note['id']}", json={"subject": "Admin"}, headers=_headers(admin)
    )
    assert by_admin.status_code == 200
    assert by_admin.json()["subject"] == "Admin"


# ── B. Szanse ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atlas_motion_resolves_decision_map_people(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _company(app_client, rep)
    opp = await _opportunity(app_client, rep, company_id)
    plain = (await app_client.get(f"{OPPS}/{opp['id']}", headers=_headers(rep))).json()
    assert plain["atlas_motion"] is None

    atlas_id = str(uuid.uuid4())
    tag = _tag()
    by_ref, by_email, by_name = await _add(
        SalesContact(
            full_name=f"Osoba Ref {tag}",
            company_id=None,
            external_ref=f"atlas:contacts:{atlas_id}",
        ),
        SalesContact(
            full_name=f"Osoba Mail {tag}",
            email=f"mail-{tag}@example.com",
            company_id=company_id,
        ),
        SalesContact(full_name=f"Osoba Nazwisko {tag}", company_id=company_id),
    )
    custom = {
        "atlas": {
            "imported_from": "pipedrive",
            "products": ["Body leasing", None],
            "subscription_items": [{"name": "Pakiet", "mrr": 100}, "zły wpis"],
            "it_factory": {
                "decision_map": [
                    {"name": "Ktoś Z Atlasa", "contact_id": atlas_id},
                    {"name": "Ktoś Mailem", "email": f"MAIL-{tag}@example.com"},
                    {"name": f"osoba nazwisko {tag}"},
                    {"name": "Nieznany"},
                    {"name": "   "},
                ],
                "purchasing_process": {
                    "milestones": {
                        "nda_signed_at": "2026-01-10",
                        "next_rfp_expected_at": "2026-12-01",
                        "next_evaluation_at": None,
                    }
                },
                "decision_map_completeness": 99,
            },
        }
    }
    async with AsyncSessionLocal() as db:
        row = await db.get(SalesOpportunity, opp["id"])
        row.custom_fields = custom
        await db.commit()

    motion = (
        await app_client.get(f"{OPPS}/{opp['id']}", headers=_headers(rep))
    ).json()["atlas_motion"]
    assert motion["products"] == ["Body leasing"]
    assert motion["subscription_items"] == [{"name": "Pakiet", "mrr": 100}]
    assert motion["meddic"] is None
    itf = motion["it_factory"]
    assert [e["nexus_contact_id"] for e in itf["decision_map"]] == [
        by_ref,
        by_email,
        by_name,
        None,
        None,
    ]
    assert (itf["decision_map_completeness"], itf["process_completeness"]) == (4, 2)


@pytest.mark.asyncio
async def test_opportunity_list_sorts(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _company(app_client, rep)
    today = business_today()
    small = await _opportunity(
        app_client,
        rep,
        company_id,
        value="100",
        expected_close_date=(today + timedelta(days=30)).isoformat(),
    )
    big = await _opportunity(
        app_client,
        rep,
        company_id,
        value="900",
        expected_close_date=(today + timedelta(days=5)).isoformat(),
    )
    none = await _opportunity(app_client, rep, company_id)

    async def order(sort: str) -> list[int]:
        resp = await app_client.get(
            OPPS, params={"company_id": company_id, "sort": sort}, headers=_headers(rep)
        )
        assert resp.status_code == 200, resp.text
        return [o["id"] for o in resp.json()["items"]]

    assert await order("value") == [big["id"], small["id"], none["id"]]
    assert await order("close") == [big["id"], small["id"], none["id"]]
    assert await order("created") == [none["id"], big["id"], small["id"]]
    bad = await app_client.get(OPPS, params={"sort": "x"}, headers=_headers(rep))
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_summary_counts_open_value_weighted_and_stale(app_client) -> None:
    rep = await _user("sales_edit")
    viewer = await _user("sales_view")
    tag = _tag()
    async with AsyncSessionLocal() as db:
        pipeline = SalesPipeline(key=f"t-{tag}", name=f"Lejek {tag}", position=99)
        db.add(pipeline)
        await db.flush()
        s1 = SalesPipelineStage(
            pipeline_id=pipeline.id,
            key="a",
            name="Pierwszy",
            position=1,
            probability=10,
        )
        s2 = SalesPipelineStage(
            pipeline_id=pipeline.id, key="b", name="Drugi", position=2, probability=50
        )
        won = SalesPipelineStage(
            pipeline_id=pipeline.id,
            key="won",
            name="Wygrana",
            position=3,
            probability=100,
            outcome="won",
        )
        company = SalesCompany(
            name=f"Lejek Firma {tag}", normalized_name=f"lejek {tag}"
        )
        db.add_all([s1, s2, won, company])
        await db.flush()
        pipeline_id, s1_id, s2_id = pipeline.id, s1.id, s2.id
        await db.commit()

    today = business_today()
    next_start, _ = period_range("next_quarter", today)

    def opp(stage_id: int, value: str, probability: int, **extra) -> SalesOpportunity:
        return SalesOpportunity(
            company_id=company.id,
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            title=f"Szansa {_tag()}",
            value=Decimal(value),
            probability=probability,
            **extra,
        )

    a, b, c, d, _won, _archived = await _add(
        opp(
            s1_id,
            "1000",
            10,
            owner_user_id=rep.id,
            mrr_value=Decimal("800"),
            expected_close_date=today,
        ),
        opp(s2_id, "2000", 50, owner_user_id=rep.id),
        opp(s2_id, "500", 50, expected_close_date=today),
        opp(s1_id, "300", 10, owner_user_id=rep.id, expected_close_date=next_start),
        opp(s2_id, "7000", 100, status="won", owner_user_id=rep.id),
        opp(
            s2_id,
            "7000",
            50,
            owner_user_id=rep.id,
            archived_at=datetime.now(timezone.utc),
        ),
    )
    now = datetime.now(timezone.utc)
    await _add(
        SalesActivity(
            kind="call",
            company_id=company.id,
            opportunity_id=c,
            subject="Świeży telefon",
            occurred_at=now - timedelta(days=2),
        )
    )
    async with AsyncSessionLocal() as db:
        # b i d bez ruchu od miesiąca; c stary, ale ma świeżą aktywność.
        await db.execute(
            text(
                "UPDATE sales_opportunities SET updated_at = now() - interval '30 days' "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": [b, c, d]},
        )
        await db.commit()

    url = "/api/sales/summary"
    assert (
        await app_client.get(url, headers=_headers(await _user()))
    ).status_code == 403

    full = (
        await app_client.get(
            url, params={"pipeline_id": pipeline_id}, headers=_headers(viewer)
        )
    ).json()
    assert full["pipeline"]["id"] == pipeline_id
    assert full["open_count"] == 4
    assert Decimal(full["value"]) == Decimal("3800")
    assert Decimal(full["weighted"]) == Decimal("1380")  # 100 + 1000 + 250 + 30
    assert Decimal(full["mrr"]) == Decimal("800")
    assert full["stale_count"] == 2
    owners = {(o["owner"] or {}).get("id"): o for o in full["by_owner"]}
    assert owners[rep.id]["open"] == 3 and owners[rep.id]["stale"] == 2
    assert owners[rep.id]["no_close"] == 1
    assert Decimal(owners[None]["weighted"]) == Decimal("250")
    stages = {s["stage"]["id"]: s for s in full["by_stage"]}
    assert set(stages) == {s1_id, s2_id}
    assert (stages[s1_id]["count"], Decimal(stages[s1_id]["value"])) == (2, 1300)

    quarter = (
        await app_client.get(
            url,
            params={"pipeline_id": pipeline_id, "period": "quarter"},
            headers=_headers(viewer),
        )
    ).json()
    assert (quarter["open_count"], Decimal(quarter["value"])) == (2, 1500)
    assert quarter["stale_count"] == 0
    quarter_owners = {(o["owner"] or {}).get("id"): o for o in quarter["by_owner"]}
    assert quarter_owners[rep.id]["open"] == 1
    assert quarter_owners[rep.id]["no_close"] == 1

    following = (
        await app_client.get(
            url,
            params={"pipeline_id": pipeline_id, "period": "next_quarter"},
            headers=_headers(viewer),
        )
    ).json()
    assert (following["open_count"], following["stale_count"]) == (1, 1)

    default = await app_client.get(url, headers=_headers(viewer))
    assert default.status_code == 200
    assert default.json()["pipeline"]["id"] != pipeline_id


# ── C. Firmy ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_labels_list_filter_and_admin_assign(app_client) -> None:
    rep = await _user("sales_edit")
    admin = await _user(role="admin")
    label = f"Opiekun {_tag()}"
    tag = _tag()
    first, second = await _add(
        SalesCompany(
            name=f"Etykieta A {tag}",
            normalized_name=f"etykieta a {tag}",
            owner_label=label,
            tags=[ATLAS_REVIEW_TAG],
        ),
        SalesCompany(
            name=f"Etykieta B {tag}",
            normalized_name=f"etykieta b {tag}",
            owner_label=label,
            tags=[f"tag-{tag}"],
        ),
    )
    async with AsyncSessionLocal() as db:
        pipeline = (
            await db.execute(select(SalesPipeline).where(SalesPipeline.key == "sales"))
        ).scalar_one()
        stage_id = (
            await db.execute(
                select(SalesPipelineStage.id)
                .where(SalesPipelineStage.pipeline_id == pipeline.id)
                .order_by(SalesPipelineStage.position)
                .limit(1)
            )
        ).scalar_one()
    free, owned = await _add(
        SalesOpportunity(
            company_id=first, pipeline_id=pipeline.id, stage_id=stage_id, title="Bez"
        ),
        SalesOpportunity(
            company_id=first,
            pipeline_id=pipeline.id,
            stage_id=stage_id,
            title="Z opiekunem",
            owner_user_id=admin.id,
        ),
    )

    listed = (
        await app_client.get(
            COMPANIES, params={"owner_label": label}, headers=_headers(rep)
        )
    ).json()
    assert {c["id"] for c in listed["items"]} == {first, second}
    by_id = {c["id"]: c for c in listed["items"]}
    assert (
        by_id[first]["needs_review"] is True and by_id[second]["needs_review"] is False
    )
    assert by_id[first]["owner_label"] == label
    review = (
        await app_client.get(
            COMPANIES,
            params={"owner_label": label, "review": "true"},
            headers=_headers(rep),
        )
    ).json()
    assert [c["id"] for c in review["items"]] == [first]
    tagged = (
        await app_client.get(
            COMPANIES, params={"tag": f"tag-{tag}"}, headers=_headers(rep)
        )
    ).json()
    assert [c["id"] for c in tagged["items"]] == [second]

    labels = (
        await app_client.get(f"{COMPANIES}/owner-labels", headers=_headers(rep))
    ).json()
    assert {"label": label, "companies": 2} in labels

    assign = f"{COMPANIES}/owner-labels/assign"
    refused = await app_client.post(
        assign, json={"label": label, "owner_user_id": rep.id}, headers=_headers(rep)
    )
    assert refused.status_code == 403
    async with AsyncSessionLocal() as db:
        inactive = User(
            email=f"sales-off-{_tag()}@example.com",
            name="Nieaktywny",
            role=rep.role,
            roles=[rep.role.value],
            is_active=False,
            profile_completed=True,
        )
        db.add(inactive)
        await db.commit()
        inactive_id = inactive.id
    bad = await app_client.post(
        assign,
        json={"label": label, "owner_user_id": inactive_id},
        headers=_headers(admin),
    )
    assert bad.status_code == 422
    done = await app_client.post(
        assign, json={"label": label, "owner_user_id": rep.id}, headers=_headers(admin)
    )
    assert done.json() == {"companies": 2, "opportunities": 1}

    async with AsyncSessionLocal() as db:
        companies = (
            (
                await db.execute(
                    select(SalesCompany).where(SalesCompany.id.in_([first, second]))
                )
            )
            .scalars()
            .all()
        )
        assert {(c.owner_user_id, c.owner_label) for c in companies} == {(rep.id, None)}
        assert (await db.get(SalesOpportunity, free)).owner_user_id == rep.id
        assert (await db.get(SalesOpportunity, owned)).owner_user_id == admin.id
    labels = (
        await app_client.get(f"{COMPANIES}/owner-labels", headers=_headers(rep))
    ).json()
    assert label not in {row["label"] for row in labels}


@pytest.mark.asyncio
async def test_setting_owner_clears_atlas_owner_label(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    (company_id,) = await _add(
        SalesCompany(
            name=f"Bez opiekuna {tag}",
            normalized_name=f"bez opiekuna {tag}",
            owner_label=f"Opiekun {tag}",
        )
    )
    resp = await app_client.patch(
        f"{COMPANIES}/{company_id}",
        json={"owner_user_id": rep.id},
        headers=_headers(rep),
    )
    assert resp.status_code == 200, resp.text
    assert (resp.json()["owner"]["id"], resp.json()["owner_label"]) == (rep.id, None)


@pytest.mark.asyncio
async def test_duplicate_groups_by_nip_and_name(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    nip = _nip()
    ids = []
    for name, company_nip in (
        (f"Dubel NIP {tag} A", nip),
        (f"Dubel NIP {tag} B", nip),
        (f"Dubel Nazwa {tag}", None),
        (f"Dubel Nazwa {tag} S.A.", None),
    ):
        resp = await app_client.post(
            COMPANIES,
            json={"name": name, "nip": company_nip, "allow_duplicate": True},
            headers=_headers(rep),
        )
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["id"])

    groups = (
        await app_client.get(f"{COMPANIES}/duplicates", headers=_headers(rep))
    ).json()
    by_ids = {frozenset(c["id"] for c in g["companies"]): g for g in groups}
    assert by_ids[frozenset(ids[:2])]["reason"] == "nip"
    assert by_ids[frozenset(ids[:2])]["key"] == nip
    assert by_ids[frozenset(ids[2:])]["reason"] == "name"
    assert by_ids[frozenset(ids[2:])]["companies"][0]["open_opportunities"] == 0

    hint = (
        await app_client.get(
            f"{COMPANIES}/duplicates",
            params={"name": f"Dubel Nazwa {tag}"},
            headers=_headers(rep),
        )
    ).json()
    assert {d["id"] for d in hint} == set(ids[2:])


@pytest.mark.asyncio
async def test_merge_moves_everything_and_archives_the_source(app_client) -> None:
    rep = await _user("sales_edit")
    other = await _user("sales_edit")
    tag = _tag()
    target = (
        await app_client.post(
            COMPANIES,
            json={"name": f"Cel {tag}", "tags": ["a"]},
            headers=_headers(rep),
        )
    ).json()
    source = (
        await app_client.post(
            COMPANIES,
            json={
                "name": f"Źródło {tag}",
                "tags": ["a", "b"],
                "nip": _nip(),
                "hq_city": "Gdańsk",
            },
            headers=_headers(rep),
        )
    ).json()
    child = (
        await app_client.post(
            COMPANIES,
            json={"name": f"Córka {tag}", "parent_company_id": source["id"]},
            headers=_headers(rep),
        )
    ).json()
    async with AsyncSessionLocal() as db:
        row = await db.get(SalesCompany, source["id"])
        row.custom_fields = {"atlas": {"x": 1}}
        target_row = await db.get(SalesCompany, target["id"])
        target_row.custom_fields = {"atlas": {"y": 2}}
        await db.commit()
    main_contact = (
        await app_client.post(
            CONTACTS,
            json={"company_id": source["id"], "full_name": f"Główna {tag}"},
            headers=_headers(rep),
        )
    ).json()
    both_contact = (
        await app_client.post(
            CONTACTS,
            json={"company_id": target["id"], "full_name": f"Obie {tag}"},
            headers=_headers(rep),
        )
    ).json()
    linked = await app_client.post(
        f"{CONTACTS}/{both_contact['id']}/companies",
        json={"company_id": source["id"], "role": "Doradca"},
        headers=_headers(rep),
    )
    assert linked.status_code == 200, linked.text
    opp = await _opportunity(app_client, rep, source["id"])
    note = (
        await app_client.post(
            ACTIVITIES,
            json={"kind": "note", "company_id": source["id"], "subject": "Notatka"},
            headers=_headers(rep),
        )
    ).json()
    file_id, lead_id = await _add(
        SalesFile(company_id=source["id"], filename="a.pdf", storage_key=f"k/{tag}"),
        SalesLead(
            source="manual",
            title="Lead",
            company_id=source["id"],
            fingerprint=f"merge-{tag}",
        ),
    )

    url = f"{COMPANIES}/{target['id']}/merge"
    assert (
        await app_client.post(
            url, json={"source_id": source["id"]}, headers=_headers(other)
        )
    ).status_code == 403
    assert (
        await app_client.post(
            url, json={"source_id": target["id"]}, headers=_headers(rep)
        )
    ).status_code == 422

    merged = await app_client.post(
        url, json={"source_id": source["id"]}, headers=_headers(rep)
    )
    assert merged.status_code == 200, merged.text
    body = merged.json()
    assert body["tags"] == ["a", "b"]
    assert (body["nip"], body["hq_city"]) == (source["nip"], "Gdańsk")
    assert body["open_opportunities"] == 1

    async with AsyncSessionLocal() as db:
        archived = await db.get(SalesCompany, source["id"])
        assert archived.archived_at is not None
        assert archived.custom_fields["merged_into"] == target["id"]
        kept = await db.get(SalesCompany, target["id"])
        assert kept.custom_fields["atlas"] == {"y": 2}
        assert (await db.get(SalesOpportunity, opp["id"])).company_id == target["id"]
        assert (await db.get(SalesActivity, note["id"])).company_id == target["id"]
        assert (await db.get(SalesFile, file_id)).company_id == target["id"]
        assert (await db.get(SalesLead, lead_id)).company_id == target["id"]
        assert (await db.get(SalesCompany, child["id"])).parent_company_id == target[
            "id"
        ]
        assert (await db.get(SalesContact, main_contact["id"])).company_id == target[
            "id"
        ]
        links = (
            (
                await db.execute(
                    select(SalesCompanyContact).where(
                        SalesCompanyContact.contact_id.in_(
                            [main_contact["id"], both_contact["id"]]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {
            (link.contact_id, link.company_id, link.is_primary) for link in links
        } == {
            (main_contact["id"], target["id"], True),
            (both_contact["id"], target["id"], True),
        }

    again = await app_client.post(
        url, json={"source_id": source["id"]}, headers=_headers(rep)
    )
    assert again.status_code == 409


# ── D. Kontakty ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_contact_in_several_companies(app_client) -> None:
    rep = await _user("sales_edit")
    viewer = await _user("sales_view")
    first = await _company(app_client, rep)
    second = await _company(app_client, rep)
    tag = _tag()
    phone_tail = f"{uuid.uuid4().int % 10**6:06d}"
    contact = (
        await app_client.post(
            CONTACTS,
            json={
                "company_id": first,
                "full_name": f"Wielofirmowa {tag}",
                "title": "CTO",
                "mobile_phone": f"+48 600-{phone_tail[:3]} {phone_tail[3:]}",
            },
            headers=_headers(rep),
        )
    ).json()
    assert contact["companies"] == [
        {
            "company_id": first,
            "company_name": contact["company_name"],
            "role": None,
            "title": "CTO",
            "is_primary": True,
            "is_current": True,
        }
    ]
    url = f"{CONTACTS}/{contact['id']}/companies"
    assert (
        await app_client.post(
            url, json={"company_id": second}, headers=_headers(viewer)
        )
    ).status_code == 403
    linked = (
        await app_client.post(
            url,
            json={"company_id": second, "role": "Doradca", "is_current": False},
            headers=_headers(rep),
        )
    ).json()
    assert [
        (c["company_id"], c["is_primary"], c["role"]) for c in linked["companies"]
    ] == [
        (first, True, None),
        (second, False, "Doradca"),
    ]

    in_second = (
        await app_client.get(
            CONTACTS, params={"company_id": second}, headers=_headers(rep)
        )
    ).json()
    assert [c["id"] for c in in_second["items"]] == [contact["id"]]
    by_phone = (
        await app_client.get(
            CONTACTS, params={"q": f"600{phone_tail}"}, headers=_headers(rep)
        )
    ).json()
    assert [c["id"] for c in by_phone["items"]] == [contact["id"]]

    primary = await app_client.delete(f"{url}/{first}", headers=_headers(rep))
    assert primary.status_code == 409
    moved = (
        await app_client.patch(
            f"{CONTACTS}/{contact['id']}",
            json={"company_id": second},
            headers=_headers(rep),
        )
    ).json()
    assert {c["company_id"]: c["is_primary"] for c in moved["companies"]} == {
        first: False,
        second: True,
    }
    unlinked = await app_client.delete(f"{url}/{first}", headers=_headers(rep))
    assert unlinked.status_code == 200
    assert [c["company_id"] for c in unlinked.json()["companies"]] == [second]

    await app_client.post(f"{CONTACTS}/{contact['id']}/archive", headers=_headers(rep))
    archived = (
        await app_client.get(
            CONTACTS, params={"archived": "true", "q": tag}, headers=_headers(rep)
        )
    ).json()
    assert [c["id"] for c in archived["items"]] == [contact["id"]]


# ── E. Leady ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_lead_out_carries_payload(app_client) -> None:
    rep = await _user("sales_view")
    tag = _tag()
    (lead_id,) = await _add(
        SalesLead(
            source="atlas",
            title=f"Lead {tag}",
            fingerprint=f"payload-{tag}",
            payload={"reason": "nowy dział IT"},
        )
    )
    lead = (
        await app_client.get(f"/api/sales/leads/{lead_id}", headers=_headers(rep))
    ).json()
    assert lead["payload"] == {"reason": "nowy dział IT"}
