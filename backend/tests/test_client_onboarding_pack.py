"""Pakiet klienta „Wejście u klienta” (etap 3, O2, makieta M5).

Kto czyta i zmienia pakiet, walidacja części, ``pack_tasks`` dla ścieżki
wejścia (bez zadań zestawu i wydania sprzętu — to pozycje ścieżki)
i ``first_day`` dla maila powitalnego. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.models.equipment import EquipmentProtocolTemplate
from app.models.user import UserRole
from app.services.hr import client_pack
from app.services.hr_lifecycle_schema import TASK_ASSIGNEES, TASK_CATEGORIES
from tests.client_onboarding_support import (
    PREFIX,
    deposit_template,
    ensure_router_mounted,
    headers,
    make_client,
    make_contact,
    make_contract,
    make_user,
    modules_state,
    tag,
)

pytestmark = pytest.mark.asyncio

MODULE_OFF = "Ten moduł nie jest jeszcze włączony."
OUT_OF_SCOPE = "Ten klient jest poza Twoim portfelem."


@pytest_asyncio.fixture
async def modules_on():
    ensure_router_mounted()
    async with modules_state(True):
        yield


@pytest_asyncio.fixture
async def modules_off():
    ensure_router_mounted()
    async with modules_state(False):
        yield


def _url(client_id: int) -> str:
    return f"{PREFIX}/clients/{client_id}/pack"


FULL_PACK = {
    "equipment": {
        "provider": "nasz",
        "ours": [{"name": "Laptop 14 cali (klasa konsultant)"}, {"name": "Słuchawki"}],
        "client": [
            {"name": "Karta wejściowa do biura", "note": "recepcja klienta"},
            {"name": "Token VPN"},
        ],
    },
    "first_day": {
        "place": "ul. Przykładowa 20, recepcja B",
        "time": "9:00",
        "bring": "dowód osobisty",
    },
    "documents": [
        {
            "name": "Zaświadczenie o niekaralności",
            "note": "nie starsze niż 3 miesiące",
            "offset_days": -5,
            "required": True,
            "requires_file": True,
        },
        {"name": "NDA klienta", "offset_days": 0, "required": True},
        {
            "name": "Szkolenie bezpieczeństwa klienta",
            "offset_days": 7,
            "required": False,
        },
    ],
    "accesses": [
        {
            "name": "Konto w domenie klienta, VPN",
            "note": "zakłada klient, prośbę wysyła DL",
            "assignee": "delivery_lead",
            "offset_days": -10,
            "required": True,
        },
        {
            "name": "Jira i komunikator klienta",
            "assignee": "care_owner",
            "offset_days": 1,
        },
    ],
}


def test_access_assignees_are_lifecycle_roles() -> None:
    assert set(client_pack.ACCESS_ASSIGNEES) <= set(TASK_ASSIGNEES)
    assert client_pack.DOCUMENT_ASSIGNEE in TASK_ASSIGNEES


# ── Dostęp ────────────────────────────────────────────────────────────────────


async def test_module_off_answers_404_except_admin(app_client, modules_off) -> None:
    dl = await make_user(UserRole.delivery_lead)
    admin = await make_user(UserRole.admin)
    client_id = await make_client(dl=dl)
    refused = await app_client.get(_url(client_id), headers=headers(dl))
    assert refused.status_code == 404 and refused.json()["detail"] == MODULE_OFF
    assert (
        await app_client.get(_url(client_id), headers=headers(admin))
    ).status_code == 200


async def test_who_reads_the_pack(app_client, modules_on) -> None:
    dl = await make_user(UserRole.delivery_lead)
    other_dl = await make_user(UserRole.delivery_lead)
    recruiter = await make_user(UserRole.recruiter)
    reception = await make_user(UserRole.recruiter, grants=("equipment",))
    client_id = await make_client(dl=dl)

    own = await app_client.get(_url(client_id), headers=headers(dl))
    assert own.status_code == 200
    body = own.json()
    assert body["exists"] is False and body["version"] == 0
    assert body["can_edit"] == {"equipment": True, "rest": True}
    assert {a["value"] for a in body["options"]["assignees"]} == set(
        client_pack.ACCESS_ASSIGNEES
    )

    foreign = await app_client.get(_url(client_id), headers=headers(other_dl))
    assert foreign.status_code == 403 and foreign.json()["detail"] == OUT_OF_SCOPE
    assert (
        await app_client.get(_url(client_id), headers=headers(recruiter))
    ).status_code == 403
    by_reception = await app_client.get(_url(client_id), headers=headers(reception))
    assert by_reception.status_code == 200
    assert by_reception.json()["can_edit"] == {"equipment": True, "rest": False}
    missing = await app_client.get(_url(10**9), headers=headers(dl))
    assert missing.status_code == 404


async def test_dl_saves_full_pack_and_version_guards_concurrent_edits(
    app_client, modules_on
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    contact_id = await make_contact(client_id)
    payload = {
        **FULL_PACK,
        "first_day": {**FULL_PACK["first_day"], "contact_id": contact_id},
    }
    saved = await app_client.put(_url(client_id), json=payload, headers=headers(dl))
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["exists"] is True and body["version"] == 1
    assert body["equipment"]["provider"] == "nasz"
    assert [i["name"] for i in body["equipment"]["client"]] == [
        "Karta wejściowa do biura",
        "Token VPN",
    ]
    assert body["first_day"] == {
        "contact_id": contact_id,
        "place": "ul. Przykładowa 20, recepcja B",
        "time": "09:00",
        "bring": "dowód osobisty",
    }
    assert body["documents"][0]["requires_file"] is True
    assert body["accesses"][0]["assignee"] == "delivery_lead"
    assert body["updated_by_name"] == dl.name
    async with AsyncSessionLocal() as db:
        provider = await db.scalar(
            text("SELECT equipment_provider FROM clients WHERE id = :id"),
            {"id": client_id},
        )
    assert provider == "nasz"

    # Część nieprzesłana zostaje; przesłana lista zastępuje listę.
    second = await app_client.put(
        _url(client_id),
        json={
            "expected_version": 1,
            "documents": [{"name": "NDA klienta", "offset_days": 0}],
        },
        headers=headers(dl),
    )
    assert second.status_code == 200
    assert second.json()["version"] == 2
    assert [d["name"] for d in second.json()["documents"]] == ["NDA klienta"]
    assert len(second.json()["accesses"]) == 2

    stale = await app_client.put(
        _url(client_id),
        json={"expected_version": 1, "accesses": []},
        headers=headers(dl),
    )
    assert stale.status_code == 409
    assert "odśwież" in stale.json()["detail"]


async def test_first_save_with_version_zero_does_not_overwrite_a_new_pack(
    app_client, modules_on
) -> None:
    """Dwie osoby zaczęły od pustego pakietu (wersja 0): druga dostaje 409."""

    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    first = await app_client.put(
        _url(client_id),
        json={"expected_version": 0, "documents": [{"name": "NDA", "offset_days": 0}]},
        headers=headers(dl),
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 1
    second = await app_client.put(
        _url(client_id),
        json={"expected_version": 0, "accesses": [{"name": "VPN", "offset_days": 0}]},
        headers=headers(dl),
    )
    assert second.status_code == 409
    assert "odśwież" in second.json()["detail"]
    kept = await app_client.get(_url(client_id), headers=headers(dl))
    assert [d["name"] for d in kept.json()["documents"]] == ["NDA"]
    assert kept.json()["accesses"] == []


async def test_pack_save_does_not_revert_equipment_flag_changed_elsewhere(
    app_client, modules_on
) -> None:
    """Flaga „sprzęt od nas” żyje na kliencie — pakiet nie cofa cudzej zmiany.

    Zapis bez ``provider`` zostawia flagę; zmiana flagi z oczekiwaną wartością,
    która już nie jest aktualna, to 409 jak przy wersji.
    """

    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl, provider="nieznany")
    first = await app_client.put(
        _url(client_id),
        json={"expected_version": 0, "equipment": {"ours": [{"name": "Laptop"}]}},
        headers=headers(dl),
    )
    assert first.status_code == 200, first.text
    assert first.json()["equipment"]["provider"] == "nieznany"
    # Ktoś zmienia flagę na profilu klienta (wersja pakietu bez zmian).
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE clients SET equipment_provider = 'nasz' WHERE id = :id"),
            {"id": client_id},
        )
        await db.commit()
    untouched = await app_client.put(
        _url(client_id),
        json={"expected_version": 1, "equipment": {"ours": [{"name": "Słuchawki"}]}},
        headers=headers(dl),
    )
    assert untouched.status_code == 200, untouched.text
    assert untouched.json()["equipment"]["provider"] == "nasz"
    stale = await app_client.put(
        _url(client_id),
        json={
            "expected_version": 2,
            "equipment": {
                "provider": "klienta",
                "expected_provider": "nieznany",
                "ours": [],
            },
        },
        headers=headers(dl),
    )
    assert stale.status_code == 409
    assert "sprzęt" in stale.json()["detail"]
    current = await app_client.put(
        _url(client_id),
        json={
            "expected_version": 2,
            "equipment": {"provider": "klienta", "expected_provider": "nasz"},
        },
        headers=headers(dl),
    )
    assert current.status_code == 200, current.text
    assert current.json()["equipment"]["provider"] == "klienta"


async def test_reception_changes_only_equipment_part(app_client, modules_on) -> None:
    reception = await make_user(UserRole.recruiter, grants=("equipment",))
    client_id = await make_client()
    equipment = await app_client.put(
        _url(client_id),
        json={
            "equipment": {"provider": "klienta", "client": [{"name": "Laptop klienta"}]}
        },
        headers=headers(reception),
    )
    assert equipment.status_code == 200, equipment.text
    refused = await app_client.put(
        _url(client_id),
        json={"documents": [{"name": "NDA", "offset_days": 0}]},
        headers=headers(reception),
    )
    assert refused.status_code == 403
    assert "część sprzętową" in refused.json()["detail"]
    recruiter = await make_user(UserRole.recruiter)
    assert (
        await app_client.put(
            _url(client_id), json={"equipment": {}}, headers=headers(recruiter)
        )
    ).status_code == 403


async def test_dl_cannot_save_foreign_client_pack(app_client, modules_on) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client()
    refused = await app_client.put(
        _url(client_id), json={"documents": []}, headers=headers(dl)
    )
    assert refused.status_code == 403 and refused.json()["detail"] == OUT_OF_SCOPE


@pytest.mark.parametrize(
    "payload, phrase",
    (
        ({"first_day": {"time": "25:00"}}, "Godzinę wpisz"),
        (
            {"accesses": [{"name": "VPN", "assignee": "person", "offset_days": 0}]},
            "Dostęp prowadzi",
        ),
        ({"accesses": [{"name": "VPN", "assignee": "care_owner"}]}, "termin"),
        ({"documents": [{"name": "   ", "offset_days": 0}]}, "potrzebuje nazwy"),
        ({"equipment": {"issue_template_id": 10**9}}, "Wybierz wzór protokołu wydania"),
    ),
)
async def test_invalid_parts_are_refused_with_reason(
    app_client, modules_on, payload, phrase
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    refused = await app_client.put(_url(client_id), json=payload, headers=headers(dl))
    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert phrase in (detail if isinstance(detail, str) else str(detail))


async def test_first_day_contact_must_belong_to_the_client(
    app_client, modules_on
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    foreign_contact = await make_contact(await make_client())
    refused = await app_client.put(
        _url(client_id),
        json={"first_day": {"contact_id": foreign_contact}},
        headers=headers(dl),
    )
    assert refused.status_code == 422
    assert "kontaktem tego klienta" in refused.json()["detail"]


async def test_template_of_other_kind_or_withdrawn_is_refused(
    app_client, modules_on
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    async with AsyncSessionLocal() as db:
        content = deposit_template()
        returned = EquipmentProtocolTemplate(
            kind="zwrot",
            name=f"Zwrot {tag()}",
            file_name="z.docx",
            content=content,
            file_sha256="0" * 64,
            file_size=len(content),
            fields=[],
        )
        withdrawn = EquipmentProtocolTemplate(
            kind="wydanie",
            name=f"Stary {tag()}",
            file_name="s.docx",
            content=content,
            file_sha256="0" * 64,
            file_size=len(content),
            fields=[],
            is_active=False,
        )
        db.add_all([returned, withdrawn])
        await db.commit()
    wrong_kind = await app_client.put(
        _url(client_id),
        json={"equipment": {"issue_template_id": returned.id}},
        headers=headers(dl),
    )
    assert wrong_kind.status_code == 422
    old = await app_client.put(
        _url(client_id),
        json={"equipment": {"issue_template_id": withdrawn.id}},
        headers=headers(dl),
    )
    assert old.status_code == 422 and "wycofany" in old.json()["detail"]
    ok = await app_client.put(
        _url(client_id),
        json={"equipment": {"return_template_id": returned.id}},
        headers=headers(dl),
    )
    assert ok.status_code == 200
    assert ok.json()["equipment"]["return_template_id"] == returned.id
    assert returned.id in [t["id"] for t in ok.json()["options"]["templates"]]


async def test_pack_preview_of_welcome_mail_uses_placeholders(
    app_client, modules_on
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    await app_client.put(_url(client_id), json=FULL_PACK, headers=headers(dl))
    preview = await app_client.get(
        f"{_url(client_id)}/welcome-preview", headers=headers(dl)
    )
    assert preview.status_code == 200
    body = preview.json()["body"]
    assert body.startswith("Cześć [imię],")
    assert "[dzień startu] o 9:00 zaczynasz" in body
    assert (
        "Przed startem prześlij: Zaświadczenie o niekaralności (nie starsze niż 3 miesiące)."
        in body
    )


# ── Kontrakt dla ścieżki wejścia i maila ──────────────────────────────────────


async def _save(client_id: int, payload: dict) -> None:
    actor = await make_user(UserRole.admin)
    async with AsyncSessionLocal() as db:
        await client_pack.save_pack(db, client_id, payload, actor=actor)
        await db.commit()


async def test_pack_tasks_cover_documents_accesses_and_client_items() -> None:
    client_id = await make_client()
    await _save(client_id, FULL_PACK)
    async with AsyncSessionLocal() as db:
        tasks = await client_pack.pack_tasks(db, client_id)
    titles = [task.title for task in tasks]
    assert titles == [
        "Zaświadczenie o niekaralności",
        "NDA klienta",
        "Szkolenie bezpieczeństwa klienta",
        "Konto w domenie klienta, VPN",
        "Jira i komunikator klienta",
        "Odbiór od klienta: Karta wejściowa do biura, Token VPN",
    ]
    # Zestaw i wydanie sprzętu „od nas” to pozycje ścieżki, nie pakietu.
    assert not any("zestaw" in t.lower() or "wydanie" in t.lower() for t in titles)
    by_title = {task.title: task for task in tasks}
    certificate = by_title["Zaświadczenie o niekaralności"]
    assert (certificate.assignee, certificate.offset_days, certificate.category) == (
        "care_owner",
        -5,
        "documents",
    )
    assert certificate.requires_file is True and certificate.required is True
    vpn = by_title["Konto w domenie klienta, VPN"]
    assert (vpn.assignee, vpn.offset_days, vpn.category) == (
        "delivery_lead",
        -10,
        "accounts",
    )
    pickup = tasks[-1]
    assert (pickup.assignee, pickup.category, pickup.required) == (
        "care_owner",
        "equipment",
        False,
    )
    for task in tasks:
        assert task.assignee in TASK_ASSIGNEES and task.category in TASK_CATEGORIES
        assert len(task.title) <= 200


async def test_empty_or_missing_pack_gives_no_tasks() -> None:
    client_id = await make_client()
    async with AsyncSessionLocal() as db:
        assert await client_pack.pack_tasks(db, client_id) == []
        assert await client_pack.pack_tasks(db, 10**9) == []
        pack = await client_pack.load_pack(db, client_id)
    assert pack.exists is False and pack.equipment_ours == ()


async def test_long_client_item_list_is_cut_to_task_title_limit() -> None:
    client_id = await make_client()
    await _save(
        client_id,
        {"equipment": {"client": [{"name": "Rzecz " + "x" * 190} for _ in range(3)]}},
    )
    async with AsyncSessionLocal() as db:
        (task,) = await client_pack.pack_tasks(db, client_id)
    assert len(task.title) == 200 and task.title.endswith("…")


async def test_first_day_prefers_contract_manager_then_pack_contact() -> None:
    client_id = await make_client()
    manager = await make_contact(client_id, "Menedżer Przykładowy")
    fallback = await make_contact(client_id, "Zapasowy Przykładowy")
    foreign = await make_contact(await make_client(), "Obcy Przykładowy")
    await _save(
        client_id,
        {
            "first_day": {
                "contact_id": fallback,
                "place": "Biuro klienta",
                "time": "08:30",
            }
        },
    )
    with_manager = await make_contract(client_id, manager_contact_id=manager)
    without_manager = await make_contract(client_id)
    foreign_manager = await make_contract(client_id, manager_contact_id=foreign)
    no_pack = await make_contract(await make_client())
    async with AsyncSessionLocal() as db:
        first = await client_pack.first_day(db, with_manager)
        second = await client_pack.first_day(db, without_manager)
        third = await client_pack.first_day(db, foreign_manager)
        assert await client_pack.first_day(db, no_pack) is None
        assert await client_pack.first_day(db, 10**9) is None
    assert first.contact_id == manager and first.contact_name.startswith("Menedżer")
    assert (first.place, first.time) == ("Biuro klienta", "08:30")
    assert second.contact_id == fallback
    assert third.contact_id == fallback


async def test_pack_save_leaves_audit_trail() -> None:
    client_id = await make_client()
    await _save(client_id, {"documents": [{"name": "NDA", "offset_days": 0}]})
    async with AsyncSessionLocal() as db:
        from app.models.activity import Activity

        actions = (
            await db.scalars(
                select(Activity.action).where(
                    Activity.entity_type == "client", Activity.entity_id == client_id
                )
            )
        ).all()
    assert "onboarding_pack_updated" in actions
