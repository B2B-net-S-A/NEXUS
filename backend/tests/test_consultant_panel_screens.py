"""Ekrany panelu konsultanta i okno aktywacji. Dane fikcyjne — repo jest publiczne.

Odpowiedzi trafiają do osoby spoza firmy, więc testy pilnują też tego, czego w nich NIE ma:
stawki klienta, marży, cennika i uwag sprzętu, cudzych protokołów i materiałów.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.admin_case import AdminCase
from app.models.consultant_panel import ClientOnboardingMaterial, CpActivation
from app.models.contract import Contract
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentItem,
    EquipmentModel,
    EquipmentProtocol,
)
from app.models.user import User, UserRole
from app.services.consultant_portal.documents import month_row
from app.services.equipment import protocols
from app.services.equipment.holders import resolve_holder
from tests.care_announcements_seed import headers, make_user, tag
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    BASE,
    Person,
    clean_team,
    install_mailer,
    make_member,
    make_person,
    portal_all,
    portal_restored,
    session_headers,
    set_portal,
)

PANEL = "/api/consultant-panel"
PDF = b"%PDF-1.4 materialy"


async def _set_rates(person: Person) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == person.contract_id)
            .values(rate_candidate=Decimal("160"), rate_client=Decimal("210"))
        )
        await db.commit()


async def _protocol(person: Person, actor: User, *, status: str = "oczekuje") -> int:
    async with AsyncSessionLocal() as db:
        holder = await resolve_holder(db, "contract", person.contract_id)
        protocol = await protocols.create_protocol(
            db,
            kind="wydanie",
            holder=holder,
            lines=[
                {"name": "Laptop testowy", "category": "laptop", "identifier": "LT"}
            ],
            protocol_date=business_today(),
            actor=await db.get(User, actor.id),
        )
        protocol.status = status
        model = EquipmentModel(
            category="laptop", name=f"Laptop {tag()}", price_pln=Decimal("4100")
        )
        db.add(model)
        await db.flush()
        item = EquipmentItem(
            model_id=model.id,
            inventory_number=f"E-{tag()}",
            status="wydany",
            notes="uwaga recepcji",
        )
        db.add(item)
        await db.flush()
        db.add(
            EquipmentAssignment(
                item_id=item.id,
                contract_id=person.contract_id,
                issue_protocol_id=protocol.id,
                issued_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        return protocol.id


# ── Stawka i menu ────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("portal_all")
async def test_me_shows_own_rate_and_nothing_about_the_client(app_client) -> None:
    person = await make_person()
    await _set_rates(person)
    me = await app_client.get(
        f"{BASE}/me", headers=await session_headers(app_client, person)
    )
    assert me.status_code == 200
    body = me.json()
    assert body["rate"]["amount"] == "160.00"
    text = me.text
    assert "210" not in text
    assert "rate_client" not in text
    assert "margin" not in text


@pytest.mark.usefixtures("portal_all")
async def test_equipment_menu_is_hidden_without_a_protocol(app_client) -> None:
    person = await make_person()
    session = await session_headers(app_client, person)
    me = (await app_client.get(f"{BASE}/me", headers=session)).json()
    assert me["menu"]["equipment"] is False
    empty = (await app_client.get(f"{BASE}/equipment", headers=session)).json()
    assert empty == {"items": [], "protocols": []}


# ── Sprzęt ───────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("portal_all")
async def test_equipment_lists_protocol_items_without_internal_fields(
    app_client,
) -> None:
    person = await make_person()
    actor = await make_user(UserRole.admin)
    protocol_id = await _protocol(person, actor)
    session = await session_headers(app_client, person)
    screen = await app_client.get(f"{BASE}/equipment", headers=session)
    assert screen.status_code == 200
    body = screen.json()
    assert body["items"][0]["protocol_id"] == protocol_id
    assert body["protocols"][0]["can_confirm"] is True
    assert "uwaga recepcji" not in screen.text
    assert "4100" not in screen.text
    assert "price" not in screen.text
    todo = (await app_client.get(f"{BASE}/todo", headers=session)).json()
    assert any(row["key"] == f"protocol-{protocol_id}" for row in todo["items"])


@pytest.mark.usefixtures("portal_all")
async def test_issue_without_protocol_stays_out_of_the_panel(app_client) -> None:
    person = await make_person()
    async with AsyncSessionLocal() as db:
        model = EquipmentModel(category="laptop", name=f"Stary {tag()}")
        db.add(model)
        await db.flush()
        item = EquipmentItem(model_id=model.id, status="wydany")
        db.add(item)
        await db.flush()
        db.add(
            EquipmentAssignment(
                item_id=item.id,
                contract_id=person.contract_id,
                issued_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    session = await session_headers(app_client, person)
    body = (await app_client.get(f"{BASE}/equipment", headers=session)).json()
    assert body["items"] == []


@pytest.mark.usefixtures("portal_all")
async def test_foreign_protocol_is_404_for_pdf_and_confirm(app_client) -> None:
    owner = await make_person()
    stranger = await make_person()
    actor = await make_user(UserRole.admin)
    protocol_id = await _protocol(owner, actor)
    session = await session_headers(app_client, stranger)
    pdf = await app_client.get(
        f"{BASE}/equipment/protocols/{protocol_id}/document.pdf", headers=session
    )
    assert pdf.status_code == 404
    confirm = await app_client.post(
        f"{BASE}/equipment/protocols/{protocol_id}/confirm",
        headers=session,
        json={"signer_name": "Obca Osoba"},
    )
    assert confirm.status_code == 404
    async with AsyncSessionLocal() as db:
        assert (await db.get(EquipmentProtocol, protocol_id)).status == "oczekuje"


@pytest.mark.usefixtures("portal_all")
async def test_consultant_confirms_receipt_once(app_client) -> None:
    person = await make_person()
    actor = await make_user(UserRole.admin)
    protocol_id = await _protocol(person, actor)
    session = await session_headers(app_client, person)
    url = f"{BASE}/equipment/protocols/{protocol_id}/confirm"
    done = await app_client.post(
        url, headers=session, json={"signer_name": "Anna Przykładowa"}
    )
    assert done.status_code == 200, done.text
    assert done.json() == {"status": "podpisany"}
    async with AsyncSessionLocal() as db:
        protocol = await db.get(EquipmentProtocol, protocol_id)
    assert protocol.signer_name == "Anna Przykładowa"
    again = await app_client.post(
        url, headers=session, json={"signer_name": "Anna Przykładowa"}
    )
    assert again.status_code == 409


# ── Rozliczenie ──────────────────────────────────────────────────────────────


def test_client_report_template_has_no_report_step() -> None:
    row = month_row(2026, 10, [], mode="client_report")
    assert row["action"] == "send_invoice"
    assert row["report_label"] == "Raport: przysyła klient"
    assert month_row(2026, 10, [])["action"] == "send_report"


@pytest.mark.usefixtures("portal_all")
async def test_finance_sets_the_template_and_consultant_reads_it(app_client) -> None:
    person = await make_person()
    finance = await make_user(UserRole.finance)
    recruiter = await make_user(UserRole.recruiter)
    url = f"{PANEL}/clients/{person.client_id}/settlement"
    refused = await app_client.put(
        url, headers=headers(recruiter), json={"mode": "own_report"}
    )
    assert refused.status_code == 403
    saved = await app_client.put(
        url,
        headers=headers(finance),
        json={"mode": "client_report", "instructions": "Fakturę wystaw do 10."},
    )
    assert saved.status_code == 200, saved.text
    session = await session_headers(app_client, person)
    screen = (await app_client.get(f"{BASE}/settlement", headers=session)).json()
    assert screen["mode"] == "client_report"
    assert screen["instructions"] == "Fakturę wystaw do 10."
    months = (await app_client.get(f"{BASE}/finance/overview", headers=session)).json()
    assert months["months"][0]["action"] == "send_invoice"


# ── Zostań trenerem ──────────────────────────────────────────────────────────


TRAINER = {
    "topics": ["AWS", "Kubernetes"],
    "experience": "Prowadzę szkolenia od pięciu lat.",
    "proposal_title": "Kubernetes w praktyce",
    "proposal_hours": "3 h",
    "audience": "Konsultanci DevOps",
    "availability": "2 dni w miesiącu",
    "materials": "",
}


@pytest.mark.usefixtures("portal_all")
async def test_trainer_application_makes_one_case_and_can_be_corrected(
    app_client,
) -> None:
    person = await make_person()
    session = await session_headers(app_client, person)
    first = await app_client.put(f"{BASE}/trainer", headers=session, json=TRAINER)
    assert first.status_code == 200, first.text
    second = await app_client.put(
        f"{BASE}/trainer", headers=session, json={**TRAINER, "topics": ["Azure"]}
    )
    assert second.status_code == 200
    async with AsyncSessionLocal() as db:
        cases = (
            await db.scalars(
                select(AdminCase).where(
                    AdminCase.contract_id == person.contract_id,
                    AdminCase.source == "portal",
                )
            )
        ).all()
    assert len(cases) == 1
    assert "Azure" in cases[0].description
    read = (await app_client.get(f"{BASE}/trainer", headers=session)).json()
    assert read["application"]["topics"] == ["Azure"]
    listed = (await app_client.get(f"{BASE}/cases", headers=session)).json()
    assert [row["id"] for row in listed["items"]] == [cases[0].id]


@pytest.mark.usefixtures("portal_all")
async def test_trainer_status_names_the_assigned_owner(app_client) -> None:
    """13.11.2026: sprawa z opiekunem pokazywała „Czeka na przydzielenie osoby”."""

    person = await make_person()
    session = await session_headers(app_client, person)
    assert (
        await app_client.put(f"{BASE}/trainer", headers=session, json=TRAINER)
    ).status_code == 200
    owner = await make_user(UserRole.talent_community_manager, name="Nadia")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(AdminCase)
            .where(
                AdminCase.contract_id == person.contract_id,
                AdminCase.source == "portal",
            )
            .values(assignee_user_id=owner.id, status="in_progress")
        )
        await db.commit()
    read = (await app_client.get(f"{BASE}/trainer", headers=session)).json()
    assert read["application"]["waiting"]["who"] == "us"
    assert owner.name in read["application"]["waiting"]["label"]


@pytest.mark.usefixtures("portal_all")
async def test_trainer_application_follows_the_training_agreement(app_client) -> None:
    """Bez formy „u klienta” i stawki za dzień: szkolenia są zdalne, cena to wycena."""

    person = await make_person()
    session = await session_headers(app_client, person)
    sent = await app_client.put(
        f"{BASE}/trainer",
        headers=session,
        json={**TRAINER, "form": "onsite", "day_rate": "4 000 zł"},
    )
    assert sent.status_code == 200, sent.text
    body = sent.json()["application"]
    assert "day_rate" not in body and "form" not in body
    assert body["proposal_title"] == "Kubernetes w praktyce"
    async with AsyncSessionLocal() as db:
        case = await db.scalar(
            select(AdminCase).where(
                AdminCase.contract_id == person.contract_id,
                AdminCase.source == "portal",
            )
        )
    assert "Stawka za dzień" not in case.description
    assert "Kubernetes w praktyce" in case.description


@pytest.mark.usefixtures("portal_all")
async def test_trainer_sample_needs_an_application_and_a_real_file(app_client) -> None:
    person = await make_person()
    session = await session_headers(app_client, person)
    early = await app_client.post(
        f"{BASE}/trainer/sample",
        headers=session,
        files={"file": ("probka.pdf", PDF, "application/pdf")},
    )
    assert early.status_code == 409
    await app_client.put(f"{BASE}/trainer", headers=session, json=TRAINER)
    fake = await app_client.post(
        f"{BASE}/trainer/sample",
        headers=session,
        files={"file": ("probka.pdf", b"nie pdf", "application/pdf")},
    )
    assert fake.status_code == 422
    project = await app_client.post(
        f"{BASE}/trainer/sample",
        headers=session,
        files={"file": ("project.drp", b"PK\x03\x04x", "application/octet-stream")},
    )
    assert project.status_code == 422
    ok = await app_client.post(
        f"{BASE}/trainer/sample",
        headers=session,
        files={"file": ("probka.pdf", PDF, "application/pdf")},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["application"]["sample_name"] == "probka.pdf"


@pytest.mark.usefixtures("portal_all")
async def test_trainer_needs_topics_and_experience(app_client) -> None:
    person = await make_person()
    session = await session_headers(app_client, person)
    refused = await app_client.put(
        f"{BASE}/trainer", headers=session, json={**TRAINER, "topics": ["  "]}
    )
    assert refused.status_code == 422


# ── Aktywacja w NEXUSIE ──────────────────────────────────────────────────────


@pytest.mark.usefixtures("portal_restored", "clean_team")
async def test_only_care_and_admin_activate(app_client) -> None:
    person = await make_person(activated=False)
    outsider = await make_member("finance")
    care = await make_member("care", name="Maja")
    url = f"{PANEL}/contracts/{person.contract_id}/activation"
    refused = await app_client.post(
        url, headers=headers(outsider), json={"email": person.email}
    )
    assert refused.status_code == 403
    done = await app_client.post(
        url, headers=headers(care), json={"email": person.email}
    )
    assert done.status_code == 200, done.text
    assert done.json()["activation"]["active"] is True
    gone = await app_client.post(
        f"{PANEL}/contracts/{person.contract_id}/deactivation", headers=headers(care)
    )
    assert gone.status_code == 200
    assert gone.json()["activation"]["active"] is False


@pytest.mark.usefixtures("portal_restored")
async def test_only_admin_flips_panel_and_mail(app_client) -> None:
    recruiter = await make_user(UserRole.recruiter)
    admin = await make_user(UserRole.admin)
    refused = await app_client.put(
        f"{PANEL}/settings", headers=headers(recruiter), json={"state": "pilot"}
    )
    assert refused.status_code == 403
    done = await app_client.put(
        f"{PANEL}/settings", headers=headers(admin), json={"state": "pilot"}
    )
    assert done.json()["state"] == "pilot"


@pytest.mark.usefixtures("portal_restored")
async def test_refused_mail_keeps_the_activation_and_says_why(app_client) -> None:
    person = await make_person(activated=False)
    admin = await make_user(UserRole.admin)
    await set_portal("pilot")
    done = await app_client.post(
        f"{PANEL}/contracts/{person.contract_id}/activation",
        headers=headers(admin),
        json={
            "email": person.email,
            "send_mail": True,
            "subject": "Start",
            "body": "Dzień dobry",
        },
    )
    assert done.status_code == 200, done.text
    assert done.json()["activation"]["active"] is True
    assert done.json()["mail_error"]


# ── Materiały ────────────────────────────────────────────────────────────────


@pytest.fixture
def _storage(tmp_path, monkeypatch):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)


@pytest.mark.usefixtures("portal_all", "_storage")
async def test_consultant_sees_only_materials_chosen_at_activation(app_client) -> None:
    person = await make_person(activated=False)
    other = await make_person()
    admin = await make_user(UserRole.admin)
    add = await app_client.post(
        f"{PANEL}/materials",
        headers=headers(admin),
        data={"title": "Bezpieczeństwo", "client_id": str(person.client_id)},
        files={"file": ("zasady.pdf", PDF, "application/pdf")},
    )
    assert add.status_code == 201, add.text
    material_id = add.json()["id"]
    skipped = await app_client.post(
        f"{PANEL}/materials",
        headers=headers(admin),
        data={"title": "Tylko link", "url": "https://example.com/szkolenie"},
    )
    assert skipped.status_code == 201, skipped.text
    proposal = (
        await app_client.get(
            f"{PANEL}/contracts/{person.contract_id}", headers=headers(admin)
        )
    ).json()
    assert {material_id, skipped.json()["id"]} <= {
        row["id"] for row in proposal["materials"]
    }
    done = await app_client.post(
        f"{PANEL}/contracts/{person.contract_id}/activation",
        headers=headers(admin),
        json={"email": person.email, "material_ids": [material_id]},
    )
    assert done.status_code == 200, done.text
    session = await session_headers(app_client, person)
    start = (await app_client.get(f"{BASE}/start", headers=session)).json()
    assert [row["id"] for row in start["materials"]] == [material_id]
    file_response = await app_client.get(
        f"{BASE}/start/materials/{material_id}/file", headers=session
    )
    assert file_response.status_code == 200
    assert file_response.content == PDF
    stranger = await session_headers(app_client, other)
    assert (
        await app_client.get(
            f"{BASE}/start/materials/{material_id}/file", headers=stranger
        )
    ).status_code == 404
    gone = await app_client.delete(
        f"{PANEL}/materials/{material_id}", headers=headers(admin)
    )
    assert gone.status_code == 200
    assert (
        await app_client.get(
            f"{BASE}/start/materials/{material_id}/file", headers=session
        )
    ).status_code == 404


@pytest.mark.usefixtures("portal_restored")
async def test_material_of_another_client_cannot_be_chosen(app_client) -> None:
    person = await make_person(activated=False)
    other = await make_person()
    admin = await make_user(UserRole.admin)
    foreign = await app_client.post(
        f"{PANEL}/materials",
        headers=headers(admin),
        data={
            "title": "Cudzy",
            "url": "https://example.com/cudzy",
            "client_id": str(other.client_id),
        },
    )
    refused = await app_client.post(
        f"{PANEL}/contracts/{person.contract_id}/activation",
        headers=headers(admin),
        json={"email": person.email, "material_ids": [foreign.json()["id"]]},
    )
    assert refused.status_code == 422
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CpActivation).where(CpActivation.contract_id == person.contract_id)
        )
    assert row is None


@pytest.mark.usefixtures("portal_restored")
async def test_material_link_must_be_https(app_client) -> None:
    admin = await make_user(UserRole.admin)
    refused = await app_client.post(
        f"{PANEL}/materials",
        headers=headers(admin),
        data={"title": "Zły link", "url": "javascript:alert(1)"},
    )
    assert refused.status_code == 422
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(ClientOnboardingMaterial).where(
                ClientOnboardingMaterial.title == "Zły link"
            )
        )
        assert rows.first() is None


# ── Poprawki po przeglądzie ──────────────────────────────────────────────────


@pytest.mark.usefixtures("portal_restored")
async def test_mail_does_not_go_out_while_the_panel_is_off(app_client) -> None:
    person = await make_person(activated=False)
    admin = await make_user(UserRole.admin)
    await set_portal("off")
    done = await app_client.post(
        f"{PANEL}/contracts/{person.contract_id}/activation",
        headers=headers(admin),
        json={"email": person.email, "send_mail": True, "subject": "S", "body": "T"},
    )
    assert done.status_code == 200, done.text
    assert "zamknięty" in done.json()["mail_error"]
    later = await app_client.post(
        f"{PANEL}/contracts/{person.contract_id}/welcome-mail",
        headers=headers(admin),
        json={"subject": "S", "body": "T"},
    )
    assert later.status_code == 409


@pytest.mark.usefixtures("portal_all")
async def test_todo_skips_current_month_and_months_before_activation(
    app_client,
) -> None:
    person = await make_person()
    session = await session_headers(app_client, person)
    today = business_today()
    fresh = (await app_client.get(f"{BASE}/todo", headers=session)).json()["items"]
    assert not [row for row in fresh if row["key"].startswith(("report-", "invoice-"))]
    month = today.month - 1 or 12
    year = today.year if today.month > 1 else today.year - 1
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CpActivation)
            .where(CpActivation.contract_id == person.contract_id)
            .values(activated_at=datetime(year, month, 1, tzinfo=timezone.utc))
        )
        await db.execute(
            update(Contract)
            .where(Contract.id == person.contract_id)
            .values(start_date=date(year - 1, 1, 1))
        )
        await db.commit()
    later = (await app_client.get(f"{BASE}/todo", headers=session)).json()["items"]
    keys = [row["key"] for row in later if row["key"].startswith("report-")]
    assert keys == [f"report-{year}-{month}"]


@pytest.mark.usefixtures("portal_all")
async def test_client_merge_moves_material_and_rule() -> None:
    from app.api.clients import _move_client_materials_on_merge
    from app.models.consultant_panel import ClientSettlementRule

    source = await make_person()
    target = await make_person()
    async with AsyncSessionLocal() as db:
        db.add(ClientSettlementRule(client_id=source.client_id, mode="client_report"))
        material = ClientOnboardingMaterial(
            client_id=source.client_id,
            title="Materiał",
            kind="link",
            url="https://example.com/m",
        )
        db.add(material)
        await db.commit()
        material_id = material.id
    async with AsyncSessionLocal() as db:
        moved = await _move_client_materials_on_merge(
            db, source.client_id, target.client_id
        )
        await db.commit()
    assert moved["settlement_rule"] == 1
    assert moved["onboarding_materials"] == 1
    async with AsyncSessionLocal() as db:
        assert (
            await db.get(ClientOnboardingMaterial, material_id)
        ).client_id == target.client_id
        assert await db.get(ClientSettlementRule, target.client_id) is not None


@pytest.mark.usefixtures("portal_all")
async def test_erasing_a_person_clears_panel_copies() -> None:
    from app.models.consultant_panel import CpTrainerApplication
    from app.models.consultant_portal import CpSession
    from app.services.candidate_hard_delete import erase_panel_data

    person = await make_person()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(
            CpSession(
                contract_id=person.contract_id,
                email=person.email,
                token_hash=tag() * 4,
                expires_at=now + timedelta(hours=1),
                created_at=now,
            )
        )
        db.add(CpTrainerApplication(contract_id=person.contract_id, experience="Opis"))
        await db.commit()
    async with AsyncSessionLocal() as db:
        await erase_panel_data(db, person.candidate_id)
        await db.commit()
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CpActivation).where(CpActivation.contract_id == person.contract_id)
        )
        sessions = await db.scalars(
            select(CpSession).where(CpSession.contract_id == person.contract_id)
        )
        applications = await db.scalars(
            select(CpTrainerApplication).where(
                CpTrainerApplication.contract_id == person.contract_id
            )
        )
        assert row.email == ""
        assert row.deactivated_at is not None
        assert sessions.first() is None
        assert applications.first() is None


async def test_contract_merge_keeps_one_active_activation() -> None:
    from app.services.contract_merge import _resolve_child_duplicates

    survivor = await make_person()
    loser = await make_person()
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CpActivation)
            .where(CpActivation.contract_id == survivor.contract_id)
            .values(deactivated_at=datetime.now(timezone.utc))
        )
        await db.commit()
    catalog = [{"table_name": "cp_activations", "column_name": "contract_id"}]
    async with AsyncSessionLocal() as db:
        out = await _resolve_child_duplicates(
            db, catalog, [loser.contract_id], survivor.contract_id
        )
        await db.commit()
    assert out["cp_activations_duplicates_removed"] == 1
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(CpActivation).where(
                    CpActivation.contract_id.in_(
                        [survivor.contract_id, loser.contract_id]
                    )
                )
            )
        ).all()
    assert [row.contract_id for row in rows] == [loser.contract_id]
    assert rows[0].deactivated_at is None


def test_start_screen_stays_for_30_days_after_later_of_start_and_activation() -> None:
    from app.services.consultant_portal.panel import _start_visible

    today = date(2026, 11, 5)
    old = Contract(start_date=date(2022, 6, 8))
    fresh = CpActivation(activated_at=datetime(2026, 11, 1, 12, tzinfo=timezone.utc))
    stale = CpActivation(activated_at=datetime(2026, 9, 1, 12, tzinfo=timezone.utc))
    assert _start_visible(old, fresh, today) is True
    assert _start_visible(old, stale, today) is False
    assert _start_visible(Contract(start_date=date(2026, 11, 20)), None, today) is True


@pytest.mark.usefixtures("portal_all")
async def test_person_already_working_gets_invite_without_first_day(app_client) -> None:
    from app.services.hr import welcome_mail

    person = await make_person()
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == person.contract_id)
            .values(start_date=date(2022, 6, 8))
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        draft = await welcome_mail.draft_for(
            db, person.contract_id, assume_panel_open=True
        )
    assert draft.subject == "Twój panel konsultanta B2B.net"
    assert "zaczynasz" not in draft.body
    assert "2022" not in draft.body
    session = await session_headers(app_client, person)
    start = (await app_client.get(f"{BASE}/start", headers=session)).json()
    assert start["first_day"] is None
    assert start["start_date"] is None
