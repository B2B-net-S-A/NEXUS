"""Komunikaty do konsultantów (O12): dostęp, grupy, wysyłka próbna, zatwierdzenie.

Przepływ: szkic → wysyłka próbna do autora (obowiązkowa po każdej zmianie
treści) → zatwierdzenie (powyżej 20 osób head back office albo admin, nigdy
autor) → kolejka. Przełącznik wysyłki w ``app_settings`` jest domyślnie
wyłączony: tworzenie, podgląd i próba działają, wysyłka do konsultantów = 409.
Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.models.care_announcement import CareAnnouncement, CareAnnouncementRecipient
from app.models.contract import ContractType
from app.models.notification import Notification, NotificationType
from app.models.user import UserRole
from tests.care_announcements_seed import (  # noqa: F401  (fixture'y)
    BASE,
    announcement_routes,
    care_off,
    care_on,
    draft_body,
    headers,
    divisions_restored,
    install_mailer,
    make_client,
    make_head,
    make_consultant,
    make_user,
    sending_default,
    sending_on,
    set_sending,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("announcement_routes")]


async def _create(app_client, author, **overrides) -> dict:
    response = await app_client.post(
        BASE, json=draft_body(**overrides), headers=headers(author)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _client_with(n: int, *, dl=None, **consultant) -> tuple[int, list[int]]:
    client_id = await make_client(dl=dl)
    candidates = []
    for _ in range(n):
        _contract, candidate = await make_consultant(client_id, **consultant)
        candidates.append(candidate)
    return client_id, candidates


# ── Dostęp ──────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("care_off")
async def test_module_off_answers_404(app_client) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    response = await app_client.get(BASE, headers=headers(tcm))
    assert response.status_code == 404


@pytest.mark.usefixtures("care_on")
async def test_recruiter_and_finance_cannot_write_announcements(app_client) -> None:
    recruiter = await make_user(UserRole.recruiter)
    finance = await make_user(UserRole.finance)
    for user in (recruiter, finance):
        listed = await app_client.get(BASE, headers=headers(user))
        assert listed.status_code == 403, listed.text
        created = await app_client.post(BASE, json=draft_body(), headers=headers(user))
        assert created.status_code == 403, created.text


@pytest.mark.usefixtures("care_on", "divisions_restored")
async def test_head_back_office_without_care_role_authors_and_approves(
    app_client,
) -> None:
    head = await make_head()
    listed = await app_client.get(BASE, headers=headers(head))
    assert listed.status_code == 200, listed.text
    me = listed.json()["me"]
    assert me["can_author"] is True and me["can_approve"] is True


@pytest.mark.usefixtures("care_on")
async def test_delivery_lead_targets_only_own_clients(app_client) -> None:
    dl = await make_user(UserRole.delivery_lead)
    other_dl = await make_user(UserRole.delivery_lead)
    own_client, _ = await _client_with(1, dl=dl)
    foreign_client, _ = await _client_with(1, dl=other_dl)

    refused = await app_client.post(
        f"{BASE}/preview",
        json={
            "kind": "mandatory",
            "audience": {"group": "client", "client_ids": [foreign_client]},
        },
        headers=headers(dl),
    )
    assert refused.status_code == 403, refused.text

    everyone = await app_client.post(
        f"{BASE}/preview",
        json={"kind": "mandatory", "audience": {"group": "all"}},
        headers=headers(dl),
    )
    assert everyone.status_code == 200, everyone.text
    clients = {row["client_id"] for row in everyone.json()["rows"]}
    assert own_client in clients and foreign_client not in clients


# ── Grupy i wykluczenia ────────────────────────────────────────────────────


@pytest.mark.usefixtures("care_on")
async def test_preview_counts_exclusions_and_dedupes_people(app_client) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    _, with_email = await make_consultant(client_id)
    _, without_email = await make_consultant(client_id, email=None)
    # Ta sama osoba z dwoma kontraktami u klienta dostaje jeden mail.
    _, twice = await make_consultant(client_id, first_name="Ewa")
    async with AsyncSessionLocal() as db:
        from app.models.candidate import Candidate
        from app.models.contract import Contract, ContractStatus

        candidate = await db.get(Candidate, twice)
        db.add(
            Contract(
                candidate_id=candidate.id,
                client_id=client_id,
                status=ContractStatus.active,
                contract_type=ContractType.b2b,
            )
        )
        await db.commit()

    response = await app_client.post(
        f"{BASE}/preview",
        json={
            "kind": "mandatory",
            "audience": {"group": "client", "client_ids": [client_id]},
        },
        headers=headers(tcm),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert body["will_receive"] == 2
    assert body["excluded_no_email"] == 1
    statuses = {row["candidate_id"]: row["status"] for row in body["rows"]}
    assert statuses[with_email] == "pending"
    assert statuses[without_email] == "excluded_no_email"
    assert statuses[twice] == "pending"


@pytest.mark.usefixtures("care_on")
async def test_contract_email_overrides_profile_email(app_client) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    _, candidate = await make_consultant(
        client_id, contract_email="z-umowy@example.com"
    )
    response = await app_client.post(
        f"{BASE}/preview",
        json={
            "kind": "mandatory",
            "audience": {"group": "client", "client_ids": [client_id]},
        },
        headers=headers(tcm),
    )
    rows = response.json()["rows"]
    assert [row["email"] for row in rows if row["candidate_id"] == candidate] == [
        "z-umowy@example.com"
    ]


@pytest.mark.usefixtures("care_on")
async def test_groups_form_ending_owner_and_selected(app_client) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    owner = await make_user(UserRole.talent_community_manager, name="Natalia")
    client_id = await make_client()
    _, b2b = await make_consultant(client_id, end_in_days=200)
    _, mandate = await make_consultant(
        client_id, contract_type=ContractType.uzlecenie, end_in_days=10
    )
    _, owned = await make_consultant(client_id, owner_id=owner.id, end_in_days=400)

    async def people(audience: dict) -> set[int]:
        response = await app_client.post(
            f"{BASE}/preview",
            json={"kind": "mandatory", "audience": audience},
            headers=headers(tcm),
        )
        assert response.status_code == 200, response.text
        return {row["candidate_id"] for row in response.json()["rows"]}

    mine = {b2b, mandate, owned}
    assert (await people({"group": "form", "forms": ["zlecenie"]})) & mine == {mandate}
    assert (await people({"group": "ending", "ending_days": 30})) & mine == {mandate}
    assert (await people({"group": "owner", "owner_user_ids": [owner.id]})) == {owned}
    assert (await people({"group": "selected", "candidate_ids": [b2b, owned]})) == {
        b2b,
        owned,
    }
    assert mine <= await people({"group": "all"})


@pytest.mark.usefixtures("care_on")
async def test_informational_skips_people_who_unsubscribed(app_client) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    _, stays = await make_consultant(client_id)
    _, left = await make_consultant(client_id)
    async with AsyncSessionLocal() as db:
        from app.models.care_announcement import CareAnnouncementOptOut

        db.add(CareAnnouncementOptOut(candidate_id=left))
        await db.commit()
    audience = {"group": "client", "client_ids": [client_id]}

    informational = await app_client.post(
        f"{BASE}/preview",
        json={"kind": "informational", "audience": audience},
        headers=headers(tcm),
    )
    body = informational.json()
    assert body["will_receive"] == 1 and body["excluded_opted_out"] == 1
    # Obowiązkowy idzie do wszystkich z grupy — wypis dotyczy informacyjnych.
    mandatory = await app_client.post(
        f"{BASE}/preview",
        json={"kind": "mandatory", "audience": audience},
        headers=headers(tcm),
    )
    assert mandatory.json()["will_receive"] == 2
    assert {stays, left} == {row["candidate_id"] for row in mandatory.json()["rows"]}


@pytest.mark.usefixtures("care_on")
async def test_unknown_placeholder_and_empty_subject_are_refused(app_client) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    unknown = await app_client.post(
        BASE, json=draft_body(body="Cześć {nazwisko}"), headers=headers(tcm)
    )
    assert unknown.status_code == 422
    assert "{nazwisko}" in unknown.json()["detail"]
    empty = await app_client.post(
        BASE, json=draft_body(subject="   "), headers=headers(tcm)
    )
    assert empty.status_code == 422


# ── Wysyłka próbna i zatwierdzenie ─────────────────────────────────────────


@pytest.mark.usefixtures("care_on", "sending_on")
async def test_submit_needs_test_send_of_current_content(
    app_client, monkeypatch
) -> None:
    mailer = install_mailer(monkeypatch)
    tcm = await make_user(UserRole.talent_community_manager)
    client_id, _ = await _client_with(2)
    created = await _create(
        app_client, tcm, audience={"group": "client", "client_ids": [client_id]}
    )
    url = f"{BASE}/{created['id']}"

    untested = await app_client.post(f"{url}/submit", headers=headers(tcm))
    assert untested.status_code == 409, untested.text

    tested = await app_client.post(f"{url}/test-send", headers=headers(tcm))
    assert tested.status_code == 200, tested.text
    assert tested.json()["test_current"] is True
    # Próba idzie do autora, z jego imieniem w miejscu {imię}, bez znacznika.
    assert [mail["to"] for mail in mailer.sent] == [tcm.email]
    assert mailer.sent[0]["subject"].startswith("[Próba]")
    assert "{imię}" not in mailer.sent[0]["text"]

    # Zmiana treści unieważnia próbę.
    edited = await app_client.patch(
        url, json={"body": "Cześć {imię}, nowa treść."}, headers=headers(tcm)
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["test_current"] is False
    again = await app_client.post(f"{url}/submit", headers=headers(tcm))
    assert again.status_code == 409

    await app_client.post(f"{url}/test-send", headers=headers(tcm))
    submitted = await app_client.post(f"{url}/submit", headers=headers(tcm))
    assert submitted.status_code == 200, submitted.text
    # Do 20 osób autor wysyła sam, bez zatwierdzenia.
    assert submitted.json()["status"] == "queued"
    assert submitted.json()["requires_approval"] is False
    assert submitted.json()["recipient_count"] == 2


@pytest.mark.usefixtures("care_on", "sending_default")
async def test_test_send_works_while_sending_is_switched_off(
    app_client, monkeypatch
) -> None:
    mailer = install_mailer(monkeypatch)
    tcm = await make_user(UserRole.talent_community_manager)
    client_id, _ = await _client_with(1)
    created = await _create(
        app_client, tcm, audience={"group": "client", "client_ids": [client_id]}
    )
    url = f"{BASE}/{created['id']}"

    listed = await app_client.get(BASE, headers=headers(tcm))
    assert listed.json()["settings"]["sending_enabled"] is False

    tested = await app_client.post(f"{url}/test-send", headers=headers(tcm))
    assert tested.status_code == 200, tested.text
    # Wysyłka do konsultantów przy wyłączonym przełączniku: 409, nic nie wychodzi.
    refused = await app_client.post(f"{url}/submit", headers=headers(tcm))
    assert refused.status_code == 409, refused.text
    assert "wyłączona" in refused.json()["detail"]
    assert [mail["to"] for mail in mailer.sent] == [tcm.email]
    async with AsyncSessionLocal() as db:
        row = await db.get(CareAnnouncement, created["id"])
        assert row.status == "draft"


@pytest.mark.usefixtures("care_on", "sending_on", "divisions_restored")
async def test_above_twenty_needs_head_and_author_cannot_approve(
    app_client, monkeypatch
) -> None:
    head = await make_head()
    mailer = install_mailer(monkeypatch)
    tcm = await make_user(UserRole.talent_community_manager)
    other_tcm = await make_user(UserRole.talent_community_manager)
    client_id, _ = await _client_with(21)
    created = await _create(
        app_client, tcm, audience={"group": "client", "client_ids": [client_id]}
    )
    url = f"{BASE}/{created['id']}"
    await app_client.post(f"{url}/test-send", headers=headers(tcm))
    submitted = await app_client.post(f"{url}/submit", headers=headers(tcm))
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["status"] == "pending" and body["requires_approval"] is True
    assert body["recipient_count"] == 21

    # Treść czekająca na zatwierdzenie jest zamrożona.
    frozen = await app_client.patch(url, json={"subject": "Inny"}, headers=headers(tcm))
    assert frozen.status_code == 409

    refused = await app_client.post(f"{url}/approve", headers=headers(tcm))
    assert refused.status_code == 403, refused.text
    # Inny opiekun cudzego komunikatu nie widzi wcale.
    hidden = await app_client.post(f"{url}/approve", headers=headers(other_tcm))
    assert hidden.status_code == 404, hidden.text

    async with AsyncSessionLocal() as db:
        notified = await db.scalar(
            select(Notification.id).where(
                Notification.user_id == head.id,
                Notification.notification_type == NotificationType.care_announcement,
                Notification.related_entity_id == created["id"],
            )
        )
        assert notified is not None

    approved = await app_client.post(f"{url}/approve", headers=headers(head))
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "queued"
    assert approved.json()["approver"]["id"] == head.id
    # Zatwierdzenie samo niczego nie wysyła — robi to kolejka.
    assert [mail["to"] for mail in mailer.sent] == [tcm.email]


@pytest.mark.usefixtures("care_on", "sending_on", "divisions_restored")
async def test_head_who_wrote_it_cannot_approve_it_admin_can(
    app_client, monkeypatch
) -> None:
    head = await make_head()
    install_mailer(monkeypatch)
    admin = await make_user(UserRole.admin)
    client_id, _ = await _client_with(21)
    created = await _create(
        app_client, head, audience={"group": "client", "client_ids": [client_id]}
    )
    url = f"{BASE}/{created['id']}"
    await app_client.post(f"{url}/test-send", headers=headers(head))
    await app_client.post(f"{url}/submit", headers=headers(head))
    own = await app_client.post(f"{url}/approve", headers=headers(head))
    assert own.status_code == 403
    assert "autor" in own.json()["detail"]
    approved = await app_client.post(f"{url}/approve", headers=headers(admin))
    assert approved.status_code == 200, approved.text


async def test_database_refuses_author_as_approver() -> None:
    author = await make_user(UserRole.admin)
    async with AsyncSessionLocal() as db:
        db.add(
            CareAnnouncement(
                code="AB12",
                subject="Temat",
                body="Treść",
                audience={"group": "all"},
                created_by=author.id,
                approved_by=author.id,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


@pytest.mark.usefixtures("care_on", "divisions_restored")
async def test_approve_with_sending_off_is_refused(app_client, monkeypatch) -> None:
    head = await make_head()
    install_mailer(monkeypatch)
    tcm = await make_user(UserRole.talent_community_manager)
    client_id, _ = await _client_with(21)
    await set_sending(True)
    try:
        created = await _create(
            app_client, tcm, audience={"group": "client", "client_ids": [client_id]}
        )
        url = f"{BASE}/{created['id']}"
        await app_client.post(f"{url}/test-send", headers=headers(tcm))
        submitted = await app_client.post(f"{url}/submit", headers=headers(tcm))
        assert submitted.json()["status"] == "pending"
        await set_sending(False)
        refused = await app_client.post(f"{url}/approve", headers=headers(head))
        assert refused.status_code == 409, refused.text
    finally:
        await set_sending(None)


@pytest.mark.usefixtures("care_on", "sending_on", "divisions_restored")
async def test_return_to_draft_notifies_author_and_drops_frozen_list(
    app_client, monkeypatch
) -> None:
    head = await make_head()
    install_mailer(monkeypatch)
    tcm = await make_user(UserRole.talent_community_manager)
    client_id, _ = await _client_with(21)
    created = await _create(
        app_client, tcm, audience={"group": "client", "client_ids": [client_id]}
    )
    url = f"{BASE}/{created['id']}"
    await app_client.post(f"{url}/test-send", headers=headers(tcm))
    await app_client.post(f"{url}/submit", headers=headers(tcm))
    returned = await app_client.post(
        f"{url}/return", json={"note": "Dopisz termin."}, headers=headers(head)
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["status"] == "draft"
    assert returned.json()["return_note"] == "Dopisz termin."
    async with AsyncSessionLocal() as db:
        left = await db.scalar(
            select(CareAnnouncementRecipient.id).where(
                CareAnnouncementRecipient.announcement_id == created["id"]
            )
        )
        assert left is None
        notified = await db.scalar(
            select(Notification.id).where(
                Notification.user_id == tcm.id,
                Notification.notification_type == NotificationType.care_announcement,
            )
        )
        assert notified is not None


@pytest.mark.usefixtures("care_on", "divisions_restored")
async def test_only_author_and_approvers_see_an_announcement(app_client) -> None:
    head = await make_head()
    tcm = await make_user(UserRole.talent_community_manager)
    other = await make_user(UserRole.talent_community_manager)
    created = await _create(app_client, tcm)
    url = f"{BASE}/{created['id']}"
    assert (await app_client.get(url, headers=headers(tcm))).status_code == 200
    assert (await app_client.get(url, headers=headers(head))).status_code == 200
    assert (await app_client.get(url, headers=headers(other))).status_code == 404
    listed = await app_client.get(BASE, headers=headers(other))
    assert created["id"] not in {row["id"] for row in listed.json()["items"]}


@pytest.mark.usefixtures("care_on", "divisions_restored")
async def test_only_admin_switches_sending(app_client) -> None:
    head = await make_head()
    admin = await make_user(UserRole.admin)
    refused = await app_client.put(
        f"{BASE}/settings", json={"sending_enabled": True}, headers=headers(head)
    )
    assert refused.status_code == 403
    try:
        switched = await app_client.put(
            f"{BASE}/settings", json={"sending_enabled": True}, headers=headers(admin)
        )
        assert switched.status_code == 200, switched.text
        assert switched.json()["sending_enabled"] is True
    finally:
        await set_sending(None)


@pytest.mark.usefixtures("care_on", "sending_on")
async def test_cancel_queued_stops_remaining_people(app_client, monkeypatch) -> None:
    install_mailer(monkeypatch)
    tcm = await make_user(UserRole.talent_community_manager)
    client_id, _ = await _client_with(2)
    created = await _create(
        app_client, tcm, audience={"group": "client", "client_ids": [client_id]}
    )
    url = f"{BASE}/{created['id']}"
    await app_client.post(f"{url}/test-send", headers=headers(tcm))
    await app_client.post(f"{url}/submit", headers=headers(tcm))
    cancelled = await app_client.post(f"{url}/cancel", headers=headers(tcm))
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    async with AsyncSessionLocal() as db:
        statuses = set(
            (
                await db.scalars(
                    select(CareAnnouncementRecipient.status).where(
                        CareAnnouncementRecipient.announcement_id == created["id"]
                    )
                )
            ).all()
        )
        assert statuses == {"cancelled"}


@pytest.mark.usefixtures("care_on", "sending_on")
async def test_admin_sending_a_delivery_lead_draft_keeps_the_lead_scope(
    app_client, monkeypatch
) -> None:
    """„Wszyscy” w szkicu Delivery Leada to jego klienci — także gdy wysyła admin."""

    install_mailer(monkeypatch)
    dl = await make_user(UserRole.delivery_lead)
    other_dl = await make_user(UserRole.delivery_lead)
    admin = await make_user(UserRole.admin)
    own_client, own = await _client_with(1, dl=dl)
    _foreign_client, foreign = await _client_with(1, dl=other_dl)
    created = await _create(app_client, dl)
    url = f"{BASE}/{created['id']}"
    await app_client.post(f"{url}/test-send", headers=headers(admin))
    submitted = await app_client.post(f"{url}/submit", headers=headers(admin))
    assert submitted.status_code == 200, submitted.text
    people = {row["candidate_id"] for row in submitted.json()["recipients"]}
    assert set(own) <= people
    assert not set(foreign) & people


@pytest.mark.usefixtures("care_on", "sending_on", "divisions_restored")
async def test_whoever_sent_it_for_approval_cannot_approve_it(
    app_client, monkeypatch
) -> None:
    """Admin, który wysłał cudzy szkic do zatwierdzenia, nie zatwierdza go sam."""

    install_mailer(monkeypatch)
    head = await make_head()
    tcm = await make_user(UserRole.talent_community_manager)
    admin = await make_user(UserRole.admin)
    client_id, _ = await _client_with(21)
    created = await _create(
        app_client, tcm, audience={"group": "client", "client_ids": [client_id]}
    )
    url = f"{BASE}/{created['id']}"
    await app_client.post(f"{url}/test-send", headers=headers(admin))
    submitted = await app_client.post(f"{url}/submit", headers=headers(admin))
    assert submitted.json()["status"] == "pending"
    own = await app_client.post(f"{url}/approve", headers=headers(admin))
    assert own.status_code == 403, own.text
    approved = await app_client.post(f"{url}/approve", headers=headers(head))
    assert approved.status_code == 200, approved.text
