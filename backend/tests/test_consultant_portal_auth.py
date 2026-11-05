"""Portal konsultanta: wyłącznik, link, sesja. Każda ścieżka odmowy ma test.

Główne ryzyko tego modułu to bezpieczeństwo, więc testy pilnują także tego, czego w
odpowiedzi NIE ma: ten sam tekst dla każdego adresu, brak tokenu w bazie, brak tokenu
pracownika w portalu i tokenu portalu w trasach pracownika.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.consultant_panel import CpActivation
from app.models.consultant_portal import CpLink, CpSession
from app.models.contract import Contract, ContractStatus
from app.models.user import UserRole
from app.services.consultant_portal import identity
from app.services.consultant_portal.auth import token_hash
from app.services.consultant_portal.portal_settings import PortalSettings, parse
from tests.care_announcements_seed import make_client, make_consultant, make_user, tag
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    BASE,
    SESSION,
    direct_link,
    install_mailer,
    make_person,
    portal_all,
    portal_restored,
    session_headers,
    set_portal,
)

pytestmark = pytest.mark.asyncio


# ── Wyłącznik ────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("portal_restored")
@pytest.mark.parametrize("state", [None, "off"])
async def test_switched_off_portal_answers_404_on_every_route(
    app_client, state
) -> None:
    await set_portal(state)
    person = await make_person()
    for method, path, body in (
        ("get", "/status", None),
        ("post", "/link", {"email": person.email}),
        ("post", "/session", {"token": "x" * 40}),
        ("get", "/me", None),
        ("get", "/faq", None),
        ("get", "/cases", None),
        ("get", "/meetings", None),
        ("get", "/finance/status", None),
        ("post", "/rating-form", {"token": "x" * 40}),
    ):
        response = await getattr(app_client, method)(
            f"{BASE}{path}", **({"json": body} if body else {})
        )
        assert response.status_code == 404, (path, response.text)
        assert response.json()["detail"] == "Not Found"


@pytest.mark.usefixtures("portal_restored")
async def test_turning_portal_off_kills_a_live_session(app_client) -> None:
    await set_portal("all")
    person = await make_person()
    headers = await session_headers(app_client, person)
    assert (await app_client.get(f"{BASE}/me", headers=headers)).status_code == 200
    await set_portal("off")
    assert (await app_client.get(f"{BASE}/me", headers=headers)).status_code == 404


@pytest.mark.usefixtures("portal_restored")
async def test_off_state_sends_no_mail_even_if_called_directly(
    app_client, monkeypatch
) -> None:
    mailer = install_mailer(monkeypatch)
    await set_portal("off")
    from app.services.consultant_portal import portal_mail

    async with AsyncSessionLocal() as db:
        outcome = await portal_mail.send(
            db, contract_id=1, to="a@example.com", subject="x", text="y"
        )
    assert outcome is None
    assert mailer.sent == []


def test_unreadable_setting_closes_the_portal() -> None:
    assert parse(None).state == "off"
    assert parse({"state": "everyone"}).state == "off"
    assert parse("all").state == "off"
    assert parse({"state": "pilot"}) == PortalSettings(state="pilot")


# ── Prośba o link ────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("portal_all")
async def test_same_answer_for_every_address(app_client, monkeypatch) -> None:
    mailer = install_mailer(monkeypatch)
    person = await make_person()
    known = await app_client.post(f"{BASE}/link", json={"email": person.email})
    unknown = await app_client.post(
        f"{BASE}/link", json={"email": "nikt-taki@example.com"}
    )
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert [mail["to"] for mail in mailer.sent] == [person.email]


@pytest.mark.usefixtures("portal_all")
async def test_link_goes_only_to_the_contract_address(app_client, monkeypatch) -> None:
    mailer = install_mailer(monkeypatch)
    # Adres z kartoteki kandydata nie wystarcza: liczy się adres z kontraktu.
    client_id = await make_client()
    address = f"kandydat-{tag()}@example.com"
    await make_consultant(client_id, email=address)
    await app_client.post(f"{BASE}/link", json={"email": address})
    assert mailer.sent == []


@pytest.mark.usefixtures("portal_all")
async def test_address_of_two_people_opens_nothing(app_client, monkeypatch) -> None:
    mailer = install_mailer(monkeypatch)
    first = await make_person()
    await make_person(email=first.email)
    response = await app_client.post(f"{BASE}/link", json={"email": first.email})
    assert response.status_code == 202
    assert mailer.sent == []


@pytest.mark.usefixtures("portal_all")
async def test_void_contract_gets_no_link(app_client, monkeypatch) -> None:
    mailer = install_mailer(monkeypatch)
    person = await make_person(status=ContractStatus.void)
    await app_client.post(f"{BASE}/link", json={"email": person.email})
    assert mailer.sent == []


@pytest.mark.usefixtures("portal_restored")
async def test_pilot_covers_only_activated_contracts(app_client, monkeypatch) -> None:
    mailer = install_mailer(monkeypatch)
    inside = await make_person()
    outside = await make_person(activated=False)
    await set_portal("pilot")
    await app_client.post(f"{BASE}/link", json={"email": outside.email})
    assert mailer.sent == []
    await app_client.post(f"{BASE}/link", json={"email": inside.email})
    assert [mail["to"] for mail in mailer.sent] == [inside.email]


@pytest.mark.usefixtures("portal_all")
async def test_link_limit_is_silent(app_client, monkeypatch) -> None:
    mailer = install_mailer(monkeypatch)
    person = await make_person()
    for _ in range(5):
        response = await app_client.post(f"{BASE}/link", json={"email": person.email})
        assert response.status_code == 202
    assert len(mailer.sent) == 3


@pytest.mark.usefixtures("portal_all")
async def test_only_the_hash_of_the_token_is_stored(app_client, monkeypatch) -> None:
    mailer = install_mailer(monkeypatch)
    person = await make_person()
    await app_client.post(f"{BASE}/link", json={"email": person.email})
    raw = mailer.last_token()
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(CpLink).where(CpLink.contract_id == person.contract_id)
            )
        ).all()
    assert [row.token_hash for row in rows] == [token_hash(raw)]
    assert raw not in {row.token_hash for row in rows}
    # Token idzie we fragmencie adresu: nie trafia do logów serwera ani do Referer.
    assert f"/konsultant/wejscie#{raw}" in mailer.sent[-1]["text"]


@pytest.mark.usefixtures("portal_all")
async def test_full_login_from_the_mail(app_client, monkeypatch) -> None:
    mailer = install_mailer(monkeypatch)
    person = await make_person()
    await app_client.post(f"{BASE}/link", json={"email": person.email})
    opened = await app_client.post(
        f"{BASE}/session", json={"token": mailer.last_token()}
    )
    assert opened.status_code == 200
    headers = {SESSION: opened.json()["session_token"]}
    me = await app_client.get(f"{BASE}/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["first_name"] == "Anna"
    # Nagłówek konsultanta nie niesie stawek.
    assert not {"rate_candidate", "rate_client"} & set(me.json())


# ── Zły link ─────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("portal_all")
async def test_link_works_once(app_client) -> None:
    person = await make_person()
    raw = await direct_link(person)
    assert (
        await app_client.post(f"{BASE}/session", json={"token": raw})
    ).status_code == 200
    second = await app_client.post(f"{BASE}/session", json={"token": raw})
    assert second.status_code == 404


@pytest.mark.usefixtures("portal_all")
async def test_bad_used_and_expired_links_look_the_same(app_client) -> None:
    person = await make_person()
    expired = await direct_link(person, ttl=timedelta(minutes=-1))
    used = await direct_link(person)
    await app_client.post(f"{BASE}/session", json={"token": used})
    answers = [
        await app_client.post(f"{BASE}/session", json={"token": token})
        for token in (expired, used, "z" * 43, "krótki", "")
    ]
    assert {answer.status_code for answer in answers} == {404}
    assert len({answer.text for answer in answers}) == 1


@pytest.mark.usefixtures("portal_all")
async def test_rating_link_does_not_open_a_session(app_client) -> None:
    from tests.consultant_portal_seed import make_meeting
    from app.services.consultant_portal import auth

    person = await make_person()
    meeting_id = await make_meeting(person, None)
    async with AsyncSessionLocal() as db:
        raw = await auth.rating_link(
            db,
            contract_id=person.contract_id,
            meeting_id=meeting_id,
            email=person.email,
            now=datetime.now(timezone.utc),
        )
        await db.commit()
    response = await app_client.post(f"{BASE}/session", json={"token": raw})
    assert response.status_code == 404


@pytest.mark.usefixtures("portal_all")
async def test_link_stops_when_contract_changes_address(app_client) -> None:
    person = await make_person()
    raw = await direct_link(person)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == person.contract_id)
            .values(candidate_email="nowy-adres@example.com")
        )
        await db.commit()
    response = await app_client.post(f"{BASE}/session", json={"token": raw})
    assert response.status_code == 404


# ── Sesja ────────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("portal_all")
async def test_no_or_bad_session_is_401(app_client) -> None:
    for headers in ({}, {SESSION: "nie-ma-takiej"}, {SESSION: "x" * 500}):
        response = await app_client.get(f"{BASE}/me", headers=headers)
        assert response.status_code == 401, headers
        assert response.json()["detail"] == "Sesja wygasła. Poproś o nowy link."


@pytest.mark.usefixtures("portal_all")
async def test_employee_token_does_not_open_the_portal(app_client) -> None:
    admin = await make_user(UserRole.admin)
    token = create_access_token(subject=admin.id, role=admin.role.value)
    for headers in (
        {SESSION: token},
        {"Authorization": f"Bearer {token}"},
        {SESSION: token, "Authorization": f"Bearer {token}"},
    ):
        response = await app_client.get(f"{BASE}/me", headers=headers)
        assert response.status_code == 401, headers


@pytest.mark.usefixtures("portal_all")
async def test_portal_token_does_not_work_for_employee_routes(app_client) -> None:
    person = await make_person()
    headers = await session_headers(app_client, person)
    raw = headers[SESSION]
    for path in (
        "/api/auth/me",
        "/api/back-office/board",
        "/api/back-office/portal/faq",
    ):
        for auth_headers in (headers, {"Authorization": f"Bearer {raw}"}):
            response = await app_client.get(path, headers=auth_headers)
            assert response.status_code == 401, (path, response.text)


@pytest.mark.usefixtures("portal_all")
async def test_expired_session_is_refused(app_client) -> None:
    person = await make_person()
    headers = await session_headers(app_client, person)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CpSession)
            .where(CpSession.token_hash == token_hash(headers[SESSION]))
            .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
        await db.commit()
    assert (await app_client.get(f"{BASE}/me", headers=headers)).status_code == 401


@pytest.mark.usefixtures("portal_all")
async def test_logout_ends_the_session(app_client) -> None:
    person = await make_person()
    headers = await session_headers(app_client, person)
    assert (await app_client.post(f"{BASE}/logout", headers=headers)).status_code == 200
    assert (await app_client.get(f"{BASE}/me", headers=headers)).status_code == 401


@pytest.mark.usefixtures("portal_all")
@pytest.mark.parametrize(
    "change",
    [
        {"status": ContractStatus.void},
        {"candidate_email": "inny@example.com"},
    ],
)
async def test_session_dies_with_the_contract(app_client, change) -> None:
    person = await make_person()
    headers = await session_headers(app_client, person)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract).where(Contract.id == person.contract_id).values(**change)
        )
        await db.commit()
    assert (await app_client.get(f"{BASE}/me", headers=headers)).status_code == 401


@pytest.mark.usefixtures("portal_restored")
async def test_session_dies_when_panel_is_deactivated(app_client) -> None:
    person = await make_person()
    await set_portal("pilot")
    headers = await session_headers(app_client, person)
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CpActivation).where(CpActivation.contract_id == person.contract_id)
        )
        await db.commit()
    assert (await app_client.get(f"{BASE}/me", headers=headers)).status_code == 401


def test_ended_contract_keeps_portal_only_for_the_grace_period() -> None:
    today = datetime(2026, 11, 2).date()
    recent = Contract(status=ContractStatus.ended, end_date=today - timedelta(days=10))
    old = Contract(
        status=ContractStatus.ended,
        end_date=today - timedelta(days=identity.ENDED_GRACE_DAYS + 1),
    )
    assert identity.eligible(recent, today)
    assert not identity.eligible(old, today)
    assert not identity.eligible(Contract(status=ContractStatus.draft), today)


# ── Kontrakt modułu ──────────────────────────────────────────────────────────


def test_public_module_has_no_future_annotations() -> None:
    """Moduł z ``@limiter.limit`` z tym importem dawałby 422 na każdym ciele żądania."""

    source = (
        Path(__file__).resolve().parents[1] / "app/api/consultant_portal.py"
    ).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            pytest.fail("from __future__ import annotations w module z limiterem")


def test_every_public_route_has_a_rate_limit() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app/api/consultant_portal.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    routes = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        names = [ast.unparse(d) for d in node.decorator_list]
        if any(name.startswith("router.") for name in names):
            routes += 1
            assert any(name.startswith("limiter.limit") for name in names), node.name
            assert any(name.startswith("limiter.shared_limit") for name in names), (
                node.name
            )
    assert routes >= 18


@pytest.mark.usefixtures("portal_all")
async def test_real_rate_limit_bites_on_the_link_route(app_client, monkeypatch) -> None:
    from app.core.rate_limit import limiter

    install_mailer(monkeypatch)
    limiter.enabled = True
    try:
        limiter.reset()
        answers = [
            (
                await app_client.post(
                    f"{BASE}/link", json={"email": "nikt@example.com"}
                )
            ).status_code
            for _ in range(7)
        ]
    finally:
        limiter.enabled = False
        limiter.reset()
    assert answers[:5] == [202] * 5
    assert 429 in answers[5:]
