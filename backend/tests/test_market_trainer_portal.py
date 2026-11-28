"""Wejście trenera z rynku do panelu (0807). Dane fikcyjne — repo jest publiczne.

Pilnuje reguł z treści handlerów, których macierz bramek nie widzi:

* własny włącznik: wyłączony = każda trasa 404 i żaden mail, wyłączenie kasuje sesje;
* panel otwiera TCM tylko trenerowi „w bazie trenerów”, z poprawnym NIP-em;
* link jednorazowy, sesja trenera nie otwiera tras konsultanta i odwrotnie;
* zamknięty panel, trener wycofany z bazy albo zmieniony adres = sesja pada;
* trener z rynku przechodzi obieg trenera B2B: zamówienie, wycena, dane do umowy
  z karty firmy, a cudze szkolenie i cudzy plik wyglądają jak brak.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.app_setting import AppSetting
from app.models.user import UserRole
from app.models.website_intake import MarketTrainerApplication, MtPortalSession
from app.services.market_trainer_portal import switch
from tests.care_announcements_seed import headers, make_user
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    BASE as CONSULTANT_BASE,
    install_mailer,
    make_person,
    portal_all,
    portal_restored,
    session_headers,
)

PORTAL = "/api/public/trainer-portal"
STAFF = "/api/trainings"
SESSION = "X-Portal-Session"
NIP = "1234563218"  # syntetyczny, z poprawną sumą kontrolną


@pytest_asyncio.fixture
async def market_switch():
    """Włącznik wejścia trenera: test ustawia, fixture przywraca stan sprzed testu."""
    async with AsyncSessionLocal() as db:
        before = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == switch.KEY)
        )

    async def _set(enabled: bool) -> None:
        async with AsyncSessionLocal() as db:
            await switch.save(db, enabled=enabled)
            await db.commit()

    yield _set
    async with AsyncSessionLocal() as db:
        await switch.save(db, enabled=switch.parse(before))
        await db.commit()


async def _trainer(*, status: str = "accepted", email: str | None = None) -> int:
    async with AsyncSessionLocal() as db:
        row = MarketTrainerApplication(
            full_name="Anna Przykładowa",
            email=email or f"rynek-{uuid.uuid4().hex[:8]}@example.com",
            topics=["Kubernetes"],
            first_training="Kafka od środka",
            experience="Warsztaty od 2019.",
            consents=[{"text": "zgoda", "sha256": "0" * 64}],
            status=status,
        )
        db.add(row)
        await db.commit()
        return row.id


def _company(email: str, **extra) -> dict:
    return {
        "company_name": "Przykładowa Szkoła Sp. z o.o.",
        "nip": NIP,
        "regon": "123456785",
        "company_address": "ul. Prosta 1, 00-001 Warszawa",
        "panel_email": email,
        **extra,
    }


def _order(**extra) -> dict:
    return {
        "title": "Kafka od środka",
        "topic": "Java",
        "session_date": (business_today() + timedelta(days=14)).isoformat(),
        "time_from": "16:00",
        "time_to": "19:00",
        "duration_minutes": 180,
        "expected_participants": 30,
        "deliverables": [{"key": "materials", "due_days": 2}],
        **extra,
    }


async def _open(app_client, tcm, trainer_id: int, email: str):
    return await app_client.post(
        f"{STAFF}/market-applications/{trainer_id}/panel",
        headers=tcm,
        json=_company(email),
    )


async def _login(app_client, mailer) -> dict[str, str]:
    token = mailer.sent[-1]["text"].split("#trener=")[1].split()[0]
    response = await app_client.post(f"{PORTAL}/session", json={"token": token})
    assert response.status_code == 200, response.text
    return {SESSION: response.json()["session_token"]}


async def test_switch_off_closes_everything(app_client, monkeypatch, market_switch):
    mailer = install_mailer(monkeypatch)
    await market_switch(False)
    tcm = headers(await make_user(UserRole.talent_community_manager))
    email = f"rynek-{uuid.uuid4().hex[:8]}@example.com"
    trainer_id = await _trainer(email=email)

    assert (await app_client.get(f"{PORTAL}/status")).status_code == 404
    opened = await _open(app_client, tcm, trainer_id, email)
    assert opened.status_code == 200, opened.text
    assert opened.json()["invite"] == "switch_off"
    assert mailer.sent == []
    link = await app_client.post(f"{PORTAL}/link", json={"email": email})
    assert link.status_code == 404


async def test_market_trainer_from_invite_to_quote(
    app_client, monkeypatch, market_switch
):
    mailer = install_mailer(monkeypatch)
    await market_switch(True)
    tcm = headers(await make_user(UserRole.talent_community_manager))
    email = f"rynek-{uuid.uuid4().hex[:8]}@example.com"
    trainer_id = await _trainer(email=email)

    bad_nip = await app_client.post(
        f"{STAFF}/market-applications/{trainer_id}/panel",
        headers=tcm,
        json=_company(email, nip="1234567890"),
    )
    assert bad_nip.status_code == 422
    opened = await _open(app_client, tcm, trainer_id, email)
    assert opened.status_code == 200, opened.text
    assert opened.json()["invite"] == "sent"
    panel = opened.json()["application"]["panel"]
    assert panel["panel_open"] is True and panel["nip"] == NIP
    assert mailer.sent[-1]["to"] == email
    assert "—" not in mailer.sent[-1]["text"]

    trainer = await _login(app_client, mailer)
    token = mailer.sent[-1]["text"].split("#trener=")[1].split()[0]
    reused = await app_client.post(f"{PORTAL}/session", json={"token": token})
    assert reused.status_code == 404

    me = (await app_client.get(f"{PORTAL}/me", headers=trainer)).json()
    assert me["kind"] == "trainer" and me["first_name"] == "Anna"
    company = (await app_client.get(f"{PORTAL}/trainer", headers=trainer)).json()
    assert company["company"]["company_name"] == "Przykładowa Szkoła Sp. z o.o."

    # Zamówienie dla trenera z rynku: obieg trenera B2B bez kontraktu.
    created = await app_client.post(
        STAFF, headers=tcm, json={**_order(), "trainer_market_id": trainer_id}
    )
    assert created.status_code == 201, created.text
    training = created.json()["training"]
    assert training["trainer_kind"] == "consultant"
    assert training["trainer_contract_id"] is None
    assert training["trainer_market_id"] == trainer_id
    assert training["trainer_name"] == "Anna Przykładowa"
    training_id = training["id"]
    draft = await app_client.get(f"{PORTAL}/trainings/{training_id}", headers=trainer)
    assert draft.status_code == 404

    sent = await app_client.post(f"{STAFF}/{training_id}/send", headers=tcm)
    assert sent.status_code == 200, sent.text
    assert any("do wyceny" in m["subject"] for m in mailer.sent if m["to"] == email)
    mine = (await app_client.get(f"{PORTAL}/trainings", headers=trainer)).json()
    assert [row["id"] for row in mine["mine"]] == [training_id]
    assert mine["library"] == {"recordings": [], "live": []}

    quote = await app_client.put(
        f"{PORTAL}/trainings/{training_id}/quote",
        headers=trainer,
        json={
            "agenda": [{"title": "Architektura", "minutes": 180}],
            "fee_prep": "1500",
            "fee_delivery": "1800",
            "fee_rights": "300",
        },
    )
    assert quote.status_code == 200, quote.text
    assert quote.json()["training"]["status"] == "quoted"

    partner = await app_client.get(f"{STAFF}/{training_id}/partner", headers=tcm)
    assert partner.status_code == 200, partner.text
    data = partner.json()["partner"]
    assert (data["company"], data["nip"], data["email"]) == (
        "Przykładowa Szkoła Sp. z o.o.",
        NIP,
        email,
    )
    assert (data["address"], data["postal_city"]) == ("ul. Prosta 1", "00-001 Warszawa")
    assert "NIP" not in partner.json()["missing"]


async def test_trainer_session_does_not_open_consultant_routes(
    app_client, monkeypatch, market_switch, portal_all
):
    mailer = install_mailer(monkeypatch)
    await market_switch(True)
    tcm = headers(await make_user(UserRole.talent_community_manager))
    email = f"rynek-{uuid.uuid4().hex[:8]}@example.com"
    await _open(app_client, tcm, await _trainer(email=email), email)
    trainer = await _login(app_client, mailer)
    consultant = await session_headers(app_client, await make_person())

    for path in ("/me", "/finance/overview", "/cases", "/trainings"):
        response = await app_client.get(f"{CONSULTANT_BASE}{path}", headers=trainer)
        assert response.status_code == 401, path
    assert (await app_client.get(f"{PORTAL}/me", headers=consultant)).status_code == 401


async def test_other_trainers_training_and_file_are_not_found(
    app_client, monkeypatch, market_switch
):
    mailer = install_mailer(monkeypatch)
    await market_switch(True)
    tcm = headers(await make_user(UserRole.talent_community_manager))
    first, second = (f"rynek-{uuid.uuid4().hex[:8]}@example.com" for _ in range(2))
    first_id = await _trainer(email=first)
    await _open(app_client, tcm, first_id, first)
    await _open(app_client, tcm, await _trainer(email=second), second)
    stranger = await _login(app_client, mailer)  # ostatni mail = drugi trener

    created = await app_client.post(
        STAFF, headers=tcm, json={**_order(), "trainer_market_id": first_id}
    )
    training_id = created.json()["training"]["id"]
    await app_client.post(f"{STAFF}/{training_id}/send", headers=tcm)

    assert (
        await app_client.get(f"{PORTAL}/trainings/{training_id}", headers=stranger)
    ).status_code == 404
    assert (
        await app_client.put(
            f"{PORTAL}/trainings/{training_id}/quote",
            headers=stranger,
            json={"agenda": [{"title": "X", "minutes": 60}]},
        )
    ).status_code == 404
    assert (
        await app_client.get(f"{PORTAL}/trainings/files/1", headers=stranger)
    ).status_code == 404


@pytest.mark.parametrize("change", ["close", "reject", "switch_off", "email"])
async def test_session_dies_with_the_panel(
    app_client, monkeypatch, market_switch, change
):
    mailer = install_mailer(monkeypatch)
    await market_switch(True)
    tcm = headers(await make_user(UserRole.talent_community_manager))
    email = f"rynek-{uuid.uuid4().hex[:8]}@example.com"
    trainer_id = await _trainer(email=email)
    await _open(app_client, tcm, trainer_id, email)
    trainer = await _login(app_client, mailer)
    assert (await app_client.get(f"{PORTAL}/me", headers=trainer)).status_code == 200

    if change == "close":
        closed = await app_client.post(
            f"{STAFF}/market-applications/{trainer_id}/panel/close", headers=tcm
        )
        assert closed.status_code == 200
        assert closed.json()["application"]["panel"]["panel_open"] is False
    elif change == "reject":
        rejected = await app_client.post(
            f"{STAFF}/market-applications/{trainer_id}/status",
            headers=tcm,
            json={"status": "rejected"},
        )
        assert rejected.status_code == 200
    elif change == "switch_off":
        await market_switch(False)
    else:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(MarketTrainerApplication)
                .where(MarketTrainerApplication.id == trainer_id)
                .values(panel_email=f"inny-{uuid.uuid4().hex[:8]}@example.com")
            )
            await db.commit()

    after = await app_client.get(f"{PORTAL}/me", headers=trainer)
    assert after.status_code == (404 if change == "switch_off" else 401)
    if change == "switch_off":
        async with AsyncSessionLocal() as db:
            left = await db.scalar(
                select(MtPortalSession.id).where(
                    MtPortalSession.application_id == trainer_id
                )
            )
        assert left is None


async def test_link_request_is_silent_and_limited(
    app_client, monkeypatch, market_switch
):
    mailer = install_mailer(monkeypatch)
    await market_switch(True)
    tcm = headers(await make_user(UserRole.talent_community_manager))
    email = f"rynek-{uuid.uuid4().hex[:8]}@example.com"
    await _open(app_client, tcm, await _trainer(email=email), email)
    invites = len(mailer.sent)

    unknown = await app_client.post(
        f"{PORTAL}/link", json={"email": f"nikt-{uuid.uuid4().hex[:6]}@example.com"}
    )
    assert unknown.status_code == 202
    responses = [
        await app_client.post(f"{PORTAL}/link", json={"email": email.upper()})
        for _ in range(4)
    ]
    assert {r.status_code for r in responses} == {202}
    assert len({r.json()["message"] for r in [unknown, *responses]}) == 1
    # Zaproszenie TCM to pierwszy link w tej godzinie: osoba dostaje jeszcze dwa.
    assert len(mailer.sent) - invites == 2


async def test_shared_address_opens_nothing(app_client, monkeypatch, market_switch):
    mailer = install_mailer(monkeypatch)
    await market_switch(True)
    tcm = headers(await make_user(UserRole.talent_community_manager))
    shared = f"wspolny-{uuid.uuid4().hex[:8]}@example.com"
    await _open(app_client, tcm, await _trainer(), shared)
    await _open(app_client, tcm, await _trainer(), shared)
    invites = len(mailer.sent)

    await app_client.post(f"{PORTAL}/link", json={"email": shared})

    assert len(mailer.sent) == invites


async def test_panel_only_for_trainer_in_base(app_client, monkeypatch, market_switch):
    install_mailer(monkeypatch)
    await market_switch(True)
    tcm = headers(await make_user(UserRole.talent_community_manager))
    email = f"rynek-{uuid.uuid4().hex[:8]}@example.com"
    trainer_id = await _trainer(status="interview", email=email)

    refused = await _open(app_client, tcm, trainer_id, email)
    assert refused.status_code == 409
    order = await app_client.post(
        STAFF, headers=tcm, json={**_order(), "trainer_market_id": trainer_id}
    )
    assert order.status_code == 422


@pytest.mark.parametrize("role", [UserRole.recruiter, UserRole.finance])
async def test_only_tcm_opens_panel_and_only_admin_switches(
    app_client, monkeypatch, market_switch, role
):
    install_mailer(monkeypatch)
    await market_switch(True)
    other = headers(await make_user(role))
    tcm = headers(await make_user(UserRole.talent_community_manager))
    email = f"rynek-{uuid.uuid4().hex[:8]}@example.com"
    trainer_id = await _trainer(email=email)

    assert (await _open(app_client, other, trainer_id, email)).status_code == 403
    switched = await app_client.put(
        f"{STAFF}/market-portal", headers=tcm, json={"enabled": False}
    )
    assert switched.status_code == 403
    assert (await app_client.get(f"{PORTAL}/status")).status_code == 200
