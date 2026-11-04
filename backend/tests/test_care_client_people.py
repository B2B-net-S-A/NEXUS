"""Struktura u klienta i opinie klienta (etap 2, D8–D11, 17.10.2026).

Zakres: zapis opinii i jej odczyt przy kontrakcie, odmowy walidacji (kontakt
i kontrakt innego klienta, data z przyszłości), D11 — Finanse dostają 403,
Head of Recruitment czyta; prośby o opinię (D9) jako czysta reguła i jedna
pozycja na menedżera; drzewo działów z konsultantami i „Bez wskazanego
menedżera”; „Podlega pod” bez pętli i tylko w obrębie klienta, 403 bez prawa
edycji kontaktów; scalenie kontaktów z podwładnymi i scalenie duplikatu
kontraktu z opiniami.

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import select, text, update

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.contract_care import (
    CONTACTS_ORG,
    ClientArea,
    ClientFeedbackScore,
    ClientFeedbackSession,
)
from app.models.job import Job, JobStatus
from app.models.user import UserRole
from app.services.care.client_people import request_decision
from app.services.contact_duplicate_merge import merge_org
from app.services.contract_merge import (
    ContractMergeManifest,
    apply_contract_merge_plan,
    approval_fingerprint,
    build_contract_merge_plan,
)
from app.services.hr_foundation_schema import HR_MODULE_KEYS
from tests.test_care_api import (
    _previous_modules,
    headers,
    make_client,
    make_user,
    set_modules,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def care_module():
    previous = await _previous_modules()
    await set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await set_modules(previous or {key: False for key in HR_MODULE_KEYS})


D11_DENIED = (
    "Strukturę u klienta i opinie klienta widzą opiekun kontraktu, Delivery Lead "
    "klienta, Head of Recruitment i administrator."
)


def _tag() -> str:
    return uuid.uuid4().hex[:8]


async def make_contact(
    client_id: int,
    name: str,
    *,
    position: Optional[str] = None,
    department: Optional[str] = None,
    reports_to: Optional[int] = None,
    area_id: Optional[int] = None,
) -> int:
    async with AsyncSessionLocal() as db:
        contact = Contact(
            client_id=client_id, name=name, position=position, department=department
        )
        db.add(contact)
        await db.flush()
        if reports_to is not None or area_id is not None:
            await db.execute(
                update(CONTACTS_ORG)
                .where(CONTACTS_ORG.c.id == contact.id)
                .values(reports_to_contact_id=reports_to, client_area_id=area_id)
            )
        await db.commit()
        return contact.id


async def make_area(client_id: int, name: str) -> int:
    async with AsyncSessionLocal() as db:
        area = ClientArea(client_id=client_id, name=name, name_key=name.lower())
        db.add(area)
        await db.commit()
        return area.id


async def make_consultant(
    client_id: int,
    *,
    manager_id: Optional[int] = None,
    started_days_ago: int = 30,
    order_end_in_days: Optional[int] = None,
    line_manager: Optional[str] = None,
    first_name: str = "Jan",
) -> int:
    tag = _tag()
    today = business_today()
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name=first_name,
            lastname=f"Konsultant-{tag}",
            email=f"people-{tag}@example.com",
        )
        db.add(candidate)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client_id,
            status=ContractStatus.active,
            start_date=today - timedelta(days=started_days_ago),
            client_order_end_date=(
                today + timedelta(days=order_end_in_days)
                if order_end_in_days is not None
                else None
            ),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("130.000"),
            rate_unit=RateUnit.hourly,
            client_pm_contact_id=manager_id,
            line_manager=line_manager,
        )
        db.add(contract)
        await db.commit()
        return contract.id


async def add_session(
    client_id: int, contact_id: int, held_on: date, scores: dict[int, int]
) -> int:
    async with AsyncSessionLocal() as db:
        session = ClientFeedbackSession(
            client_id=client_id, contact_id=contact_id, held_on=held_on, channel="phone"
        )
        db.add(session)
        await db.flush()
        for contract_id, value in scores.items():
            db.add(
                ClientFeedbackScore(
                    session_id=session.id,
                    contract_id=contract_id,
                    quality=value,
                    communication=value,
                    autonomy=value,
                )
            )
        await db.commit()
        return session.id


def _person(org: dict, contact_id: int) -> dict:
    for department in org["departments"]:
        for person in department["people"]:
            if person["id"] == contact_id:
                return person
    raise AssertionError(f"brak osoby {contact_id} w drzewie")


# ── D9: reguła prośby o opinię ──────────────────────────────────────────────


async def test_request_rule_end_within_30_days_and_feedback_in_window() -> None:
    today = date(2026, 10, 19)
    start = today - timedelta(days=40)
    end = today + timedelta(days=20)
    ask = request_decision(starts=[start], ends=[end], last_held_on=None, today=today)
    assert ask is not None and ask.reasons == ("pre_end",)
    assert ask.due_on == end - timedelta(days=30)
    # Rozmowa w oknie 30 dni przed końcem — prośby nie ma.
    covered = request_decision(
        starts=[start], ends=[end], last_held_on=end - timedelta(days=25), today=today
    )
    assert covered is None
    # Rozmowa sprzed okna nie zamyka prośby przed końcem.
    before_window = request_decision(
        starts=[start], ends=[end], last_held_on=end - timedelta(days=31), today=today
    )
    assert before_window is not None and before_window.reasons == ("pre_end",)
    # Koniec za 31 dni — jeszcze nie.
    later = request_decision(
        starts=[start],
        ends=[today + timedelta(days=31)],
        last_held_on=None,
        today=today,
    )
    assert later is None


async def test_request_rule_quarter_without_feedback() -> None:
    today = date(2026, 10, 19)
    last = today - timedelta(days=90)
    ask = request_decision(starts=[], ends=[None], last_held_on=last, today=today)
    assert ask is not None and ask.reasons == ("quarterly",) and ask.due_on == today
    fresh = request_decision(
        starts=[], ends=[None], last_held_on=today - timedelta(days=89), today=today
    )
    assert fresh is None
    # Bez żadnej rozmowy kwartał liczy się od startu pierwszego konsultanta.
    never = request_decision(
        starts=[today - timedelta(days=120), today - timedelta(days=10)],
        ends=[None, None],
        last_held_on=None,
        today=today,
    )
    assert never is not None and never.due_on == today - timedelta(days=30)
    newcomer = request_decision(
        starts=[today - timedelta(days=10)], ends=[None], last_held_on=None, today=today
    )
    assert newcomer is None


async def test_one_request_per_manager_with_all_consultants(
    app_client, care_module
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    manager = await make_contact(client_id, "Piotr Zieliński-Przykładowy")
    covered = await make_contact(client_id, "Katarzyna Spokojna")
    ending = await make_consultant(client_id, manager_id=manager, order_end_in_days=20)
    staying = await make_consultant(client_id, manager_id=manager, started_days_ago=10)
    other = await make_consultant(client_id, manager_id=covered, order_end_in_days=15)
    await add_session(
        client_id, covered, business_today() - timedelta(days=5), {other: 4}
    )

    response = await app_client.get("/api/care/feedback-requests", headers=headers(dl))
    assert response.status_code == 200, response.text
    mine = [i for i in response.json()["items"] if i["client_id"] == client_id]
    assert [item["contact_id"] for item in mine] == [manager]
    assert mine[0]["reasons"] == ["pre_end"]
    assert [c["contract_id"] for c in mine[0]["consultants"]] == [ending, staying]


# ── Opinie: zapis, odczyt, odmowy ───────────────────────────────────────────


async def test_feedback_saved_and_visible_at_contract(app_client, care_module) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    manager = await make_contact(client_id, "Zofia Opiniująca", position="Head of QA")
    first = await make_consultant(client_id, manager_id=manager)
    second = await make_consultant(client_id, manager_id=manager)
    skipped = await make_consultant(client_id, manager_id=manager)

    saved = await app_client.post(
        f"/api/care/clients/{client_id}/feedback",
        headers=headers(dl),
        json={
            "contact_id": manager,
            "held_on": business_today().isoformat(),
            "channel": "meeting",
            "extension_outlook": "likely",
            "note": "Zespół chce zostać w tym składzie.",
            "scores": [
                {"contract_id": first, "quality": 5, "communication": 4, "autonomy": 4},
                {"contract_id": second, "quality": 3},
                {"contract_id": skipped},
            ],
        },
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["contract_ids"] == sorted([first, second])

    history = await app_client.get(
        f"/api/care/contracts/{first}/feedback", headers=headers(dl)
    )
    assert history.status_code == 200, history.text
    [item] = history.json()["items"]
    assert item["average"] == 4.3
    assert item["extension_outlook"] == "likely"
    assert item["contact"]["name"] == "Zofia Opiniująca"
    assert item["note"] == "Zespół chce zostać w tym składzie."
    nothing = await app_client.get(
        f"/api/care/contracts/{skipped}/feedback", headers=headers(dl)
    )
    assert nothing.json()["items"] == []

    org = (
        await app_client.get(f"/api/care/clients/{client_id}/org", headers=headers(dl))
    ).json()
    person = _person(org, manager)
    assert person["last_feedback"]["held_on"] == business_today().isoformat()
    assert person["last_feedback"]["average"] == 4.0


async def test_feedback_rejects_foreign_contact_contract_and_future(
    app_client, care_module
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    other_client = await make_client(dl=dl)
    manager = await make_contact(client_id, "Adam Właściwy")
    stranger = await make_contact(other_client, "Adam Obcy")
    own = await make_consultant(client_id, manager_id=manager)
    foreign = await make_consultant(other_client)
    url = f"/api/care/clients/{client_id}/feedback"
    base = {"held_on": business_today().isoformat(), "channel": "phone"}

    wrong_contact = await app_client.post(
        url,
        headers=headers(dl),
        json={
            **base,
            "contact_id": stranger,
            "scores": [{"contract_id": own, "quality": 4}],
        },
    )
    assert wrong_contact.status_code == 422
    wrong_contract = await app_client.post(
        url,
        headers=headers(dl),
        json={
            **base,
            "contact_id": manager,
            "scores": [{"contract_id": foreign, "quality": 4}],
        },
    )
    assert wrong_contract.status_code == 422
    future = await app_client.post(
        url,
        headers=headers(dl),
        json={
            **base,
            "held_on": (business_today() + timedelta(days=1)).isoformat(),
            "contact_id": manager,
        },
    )
    assert future.status_code == 422
    twice = await app_client.post(
        url,
        headers=headers(dl),
        json={
            **base,
            "contact_id": manager,
            "scores": [
                {"contract_id": own, "quality": 4},
                {"contract_id": own, "autonomy": 2},
            ],
        },
    )
    assert twice.status_code == 422
    async with AsyncSessionLocal() as db:
        saved = await db.scalar(
            select(ClientFeedbackSession.id).where(
                ClientFeedbackSession.client_id == client_id
            )
        )
    assert saved is None


async def test_d11_finance_denied_head_of_recruitment_reads(
    app_client, care_module
) -> None:
    finance = await make_user(UserRole.finance)
    hor = await make_user(UserRole.head_of_recruitment)
    outsider_dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client()
    manager = await make_contact(client_id, "Ola Przykładowa")
    contract_id = await make_consultant(client_id, manager_id=manager)

    for url in (
        f"/api/care/clients/{client_id}/org",
        f"/api/care/contracts/{contract_id}/feedback",
        "/api/care/feedback-requests",
    ):
        denied = await app_client.get(url, headers=headers(finance))
        assert denied.status_code == 403, (url, denied.text)
        assert denied.json()["detail"] == D11_DENIED
    write = await app_client.post(
        f"/api/care/clients/{client_id}/feedback",
        headers=headers(finance),
        json={"contact_id": manager, "held_on": business_today().isoformat()},
    )
    assert write.status_code == 403

    hor_org = await app_client.get(
        f"/api/care/clients/{client_id}/org", headers=headers(hor)
    )
    assert hor_org.status_code == 200, hor_org.text
    assert hor_org.json()["can_write_feedback"] is False
    hor_write = await app_client.post(
        f"/api/care/clients/{client_id}/feedback",
        headers=headers(hor),
        json={"contact_id": manager, "held_on": business_today().isoformat()},
    )
    assert hor_write.status_code == 403
    # Delivery Lead spoza portfela klienta — 403 zakresu.
    foreign = await app_client.get(
        f"/api/care/clients/{client_id}/org", headers=headers(outsider_dl)
    )
    assert foreign.status_code == 403


# ── Drzewo ──────────────────────────────────────────────────────────────────


async def test_org_tree_departments_people_and_consultants(
    app_client, care_module
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    data = await make_area(client_id, "Data")
    await make_area(client_id, "Płatności")
    head = await make_contact(client_id, "Zenon Szef", position="CTO", area_id=data)
    lead = await make_contact(
        client_id, "Piotr Lider", position="Head of Data", area_id=data, reports_to=head
    )
    loose = await make_contact(client_id, "Ewa Bezdziałowa", department="płatności")
    lm_text = await make_contact(client_id, "Michał Rogalski")
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Data Engineer {_tag()}",
            description="Opis",
            status=JobStatus.published,
            client_id=client_id,
            hiring_manager_contact_id=head,
        )
        db.add(job)
        await db.commit()
    managed = await make_consultant(client_id, manager_id=lead, order_end_in_days=40)
    orphan = await make_consultant(client_id, line_manager="Michał Rogalski")

    response = await app_client.get(
        f"/api/care/clients/{client_id}/org", headers=headers(dl)
    )
    assert response.status_code == 200, response.text
    org = response.json()
    assert [d["area"]["name"] if d["area"] else None for d in org["departments"]] == [
        "Data",
        None,
    ]
    data_people = org["departments"][0]["people"]
    assert [(p["id"], p["depth"]) for p in data_people] == [(head, 0), (lead, 1)]
    assert data_people[0]["is_hiring_manager"] is True
    assert data_people[0]["subordinates"] == [{"id": lead, "name": "Piotr Lider"}]
    leader = data_people[1]
    assert leader["is_manager"] is True
    assert leader["reports_to"] == {"id": head, "name": "Zenon Szef"}
    assert [c["contract_id"] for c in leader["consultants"]] == [managed]
    assert leader["consultants"][0]["end_source"] == "order"
    no_dept = {p["id"]: p for p in org["departments"][1]["people"]}
    assert set(no_dept) == {loose, lm_text}
    assert no_dept[loose]["department_hint"]["name"] == "Płatności"
    assert no_dept[loose]["department_hint"]["area_id"] is not None
    assert [row["contract_id"] for row in org["without_manager"]] == [orphan]
    assert org["without_manager"][0]["hint"]["contact_id"] == lm_text
    assert org["can_edit_org"] is True


async def test_reports_to_rejects_loops_and_foreign_contacts(
    app_client, care_module
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    other_client = await make_client(dl=dl)
    top = await make_contact(client_id, "Anna Góra")
    middle = await make_contact(client_id, "Bartek Środek", reports_to=top)
    bottom = await make_contact(client_id, "Celina Dół", reports_to=middle)
    stranger = await make_contact(other_client, "Daria Obca")
    url = f"/api/care/clients/{client_id}/contacts"

    loop = await app_client.patch(
        f"{url}/{top}", headers=headers(dl), json={"reports_to_contact_id": bottom}
    )
    assert loop.status_code == 422, loop.text
    assert "pętlę" in loop.json()["detail"]
    itself = await app_client.patch(
        f"{url}/{top}", headers=headers(dl), json={"reports_to_contact_id": top}
    )
    assert itself.status_code == 422
    foreign = await app_client.patch(
        f"{url}/{top}", headers=headers(dl), json={"reports_to_contact_id": stranger}
    )
    assert foreign.status_code == 422
    not_here = await app_client.patch(
        f"{url}/{stranger}", headers=headers(dl), json={"reports_to_contact_id": top}
    )
    assert not_here.status_code == 404

    moved = await app_client.patch(
        f"{url}/{bottom}",
        headers=headers(dl),
        json={"reports_to_contact_id": top, "new_area_name": "Data"},
    )
    assert moved.status_code == 200, moved.text
    person = _person(moved.json(), bottom)
    assert person["reports_to"]["id"] == top
    assert [a["name"] for a in moved.json()["areas"]] == ["Data"]
    assert person["area_id"] == moved.json()["areas"][0]["id"]
    foreign_area = await make_area(other_client, "Obcy dział")
    wrong_area = await app_client.patch(
        f"{url}/{bottom}", headers=headers(dl), json={"client_area_id": foreign_area}
    )
    assert wrong_area.status_code == 422


async def test_org_write_needs_contact_edit_right(app_client, care_module) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    outsider_dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client()
    top = await make_contact(client_id, "Anna Góra")
    other = await make_contact(client_id, "Bartek Podwładny")
    url = f"/api/care/clients/{client_id}/contacts/{other}"

    read = await app_client.get(
        f"/api/care/clients/{client_id}/org", headers=headers(tcm)
    )
    assert read.status_code == 200
    assert read.json()["can_edit_org"] is False
    for user in (tcm, outsider_dl):
        denied = await app_client.patch(
            url, headers=headers(user), json={"reports_to_contact_id": top}
        )
        assert denied.status_code == 403, denied.text
    async with AsyncSessionLocal() as db:
        manager = await db.scalar(
            select(CONTACTS_ORG.c.reports_to_contact_id).where(
                CONTACTS_ORG.c.id == other
            )
        )
    assert manager is None


# ── Scalanie ────────────────────────────────────────────────────────────────


async def test_contact_merge_moves_subordinates_feedback_and_breaks_loop() -> None:
    client_id = await make_client()
    area = await make_area(client_id, "Data")
    survivor = await make_contact(client_id, "Jan Scalany")
    duplicate = await make_contact(client_id, "Jan Scalany", area_id=area)
    report = await make_contact(client_id, "Ola Podwładna", reports_to=duplicate)
    # Zachowany podlegał pod podwładnego duplikatu — po scaleniu byłaby pętla.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CONTACTS_ORG)
            .where(CONTACTS_ORG.c.id == survivor)
            .values(reports_to_contact_id=report)
        )
        await db.commit()
    contract_id = await make_consultant(client_id, manager_id=duplicate)
    session_id = await add_session(
        client_id, duplicate, business_today(), {contract_id: 4}
    )

    async with AsyncSessionLocal() as db:
        result = await merge_org(db, survivor_id=survivor, duplicate_id=duplicate)
        await db.commit()
    assert result == {
        "subordinates_repointed": 1,
        "reports_to_loop_broken": 1,
        "feedback_sessions_repointed": 1,
    }
    async with AsyncSessionLocal() as db:
        rows = {
            row.id: row
            for row in (
                await db.execute(
                    select(CONTACTS_ORG).where(
                        CONTACTS_ORG.c.id.in_([survivor, report])
                    )
                )
            ).all()
        }
        session_contact = await db.scalar(
            select(ClientFeedbackSession.contact_id).where(
                ClientFeedbackSession.id == session_id
            )
        )
    assert rows[report].reports_to_contact_id == survivor
    assert rows[survivor].reports_to_contact_id is None
    assert rows[survivor].client_area_id == area
    assert session_contact == survivor


async def test_contract_merge_keeps_feedback_and_merges_same_session_scores() -> None:
    today = business_today()
    tag = _tag()
    ids: dict = {}
    try:
        async with AsyncSessionLocal() as db:
            candidate = Candidate(
                name="Scalana",
                lastname=f"Opinia-{tag}",
                email=f"fb-merge-{tag}@example.com",
            )
            client = Client(name=f"Klient Opinii {tag}")
            db.add_all([candidate, client])
            await db.flush()
            survivor = Contract(
                candidate_id=candidate.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=today - timedelta(days=60),
                rate_candidate=Decimal("100.000"),
                rate_client=Decimal("150.000"),
                margin=Decimal("50.000"),
                rate_unit=RateUnit.hourly,
                billing_hours_per_month=160,
                currency="PLN",
            )
            loser = Contract(
                candidate_id=candidate.id,
                client_id=client.id,
                status=ContractStatus.draft,
                start_date=today - timedelta(days=60),
                rate_unit=RateUnit.hourly,
                billing_hours_per_month=160,
                currency="PLN",
            )
            contact = Contact(client_id=client.id, name="Mira Menedżerka")
            db.add_all([survivor, loser, contact])
            await db.flush()
            sid, lid = survivor.id, loser.id
            ids.update(contracts=[sid, lid], candidate=candidate.id, client=client.id)
            shared = ClientFeedbackSession(
                client_id=client.id,
                contact_id=contact.id,
                held_on=today,
                channel="phone",
            )
            older = ClientFeedbackSession(
                client_id=client.id,
                contact_id=contact.id,
                held_on=today - timedelta(days=40),
                channel="email",
            )
            db.add_all([shared, older])
            await db.flush()
            survivor_score = ClientFeedbackScore(
                session_id=shared.id, contract_id=sid, quality=5
            )
            loser_score = ClientFeedbackScore(
                session_id=shared.id, contract_id=lid, quality=2, autonomy=3
            )
            history = ClientFeedbackScore(
                session_id=older.id, contract_id=lid, communication=4
            )
            db.add_all([survivor_score, loser_score, history])
            await db.commit()
            history_id, survivor_score_id = history.id, survivor_score.id

            manifest = ContractMergeManifest(same_client_groups=((sid, lid),))
            audit = await build_contract_merge_plan(db, manifest, today=today)
            assert audit["global_blockers"] == []
            assert audit["groups"][0]["blockers"] == []
            await db.rollback()
            applied = await apply_contract_merge_plan(
                db,
                manifest,
                expected_fingerprint=audit["fingerprint"],
                expected_approval_fingerprint=approval_fingerprint(
                    audit["fingerprint"]
                ),
                today=today,
            )
            await db.commit()
            moved = applied["applied"][0]["reparented"]
            assert moved["client_feedback_scores_duplicates_merged"] == 1
            scores = {
                row.id: row
                for row in (
                    await db.scalars(
                        select(ClientFeedbackScore).where(
                            ClientFeedbackScore.contract_id.in_([sid, lid])
                        )
                    )
                ).all()
            }
            assert set(scores) == {survivor_score_id, history_id}
            kept = scores[survivor_score_id]
            assert (kept.contract_id, kept.quality, kept.autonomy) == (sid, 5, 3)
            assert scores[history_id].contract_id == sid
    finally:
        async with AsyncSessionLocal() as db:
            if ids.get("contracts"):
                await db.execute(
                    text(
                        "DELETE FROM activities WHERE entity_type = 'contract' "
                        "AND entity_id = ANY(:ids)"
                    ),
                    {"ids": ids["contracts"]},
                )
                await db.execute(
                    text("DELETE FROM contracts WHERE id = ANY(:ids)"),
                    {"ids": ids["contracts"]},
                )
            if ids.get("client"):
                await db.execute(
                    text("DELETE FROM client_feedback_sessions WHERE client_id = :c"),
                    {"c": ids["client"]},
                )
                await db.execute(
                    text("DELETE FROM contacts WHERE client_id = :c"),
                    {"c": ids["client"]},
                )
                await db.execute(
                    text("DELETE FROM clients WHERE id = :c"), {"c": ids["client"]}
                )
            if ids.get("candidate"):
                await db.execute(
                    text("DELETE FROM candidates WHERE id = :c"),
                    {"c": ids["candidate"]},
                )
            await db.commit()
