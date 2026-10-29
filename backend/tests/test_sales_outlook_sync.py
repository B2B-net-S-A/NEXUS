"""Outlook handlowców w Sprzedaży (decyzja Artura 28.10.2026, „tak, jak w Atlasie”).

* Skrzynkę podłącza też osoba z „Sprzedaż: podgląd” bez dostępu do kandydatów,
  ale jej poczta nie trafia do kandydatów (dopasowanie, CV z załączników,
  spotkania) — tylko na oś firm w Sprzedaży.
* Dopasowanie do firmy: adres kontaktu sprzedaży (firma główna i powiązane),
  potem domena firmy; bez darmowych skrzynek i domen firmy.
* Deduplikacja po ``internetMessageId`` / ``iCalUId`` — z historią z Atlasa
  i między skrzynkami dwóch handlowców.

Baza testowa jest wspólna dla przebiegu: domeny, adresy i nazwy niosą losowy tag.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.calendar_event import CalendarEvent
from app.models.candidate import Candidate, CandidateStatus
from app.models.m365 import Email, EmailMatchMethod
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyContact,
    SalesContact,
)
from app.models.user import User, UserRole
from app.services.m365 import sync as sync_mod
from app.services.m365.access import (
    CANDIDATE_SCOPE,
    MailboxScope,
    eligible_m365_owner,
    mailbox_scope,
)
from app.services.sales import outlook_activities as outlook
from app.services.section_permissions import resolve_effective_section_access
from tests._permission_grants import grant_permissions

SALES_ONLY = MailboxScope(candidates=False, sales=True)
BOTH = MailboxScope(candidates=True, sales=True)


def _tag() -> str:
    return uuid.uuid4().hex[:8]


async def _user(role: str = "employee", *grants: str) -> User:
    marker = _tag()
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"outlook-{marker}@example.com",
            name=f"Osoba {marker}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    if grants:
        await grant_permissions(user.id, *grants)
    return user


def _conn(user: User) -> SimpleNamespace:
    return SimpleNamespace(id=user.id, user_id=user.id, mailbox_upn=user.email)


async def _company(name: str, domain: str | None = None) -> int:
    async with AsyncSessionLocal() as db:
        company = SalesCompany(name=name, normalized_name=name.lower(), domain=domain)
        db.add(company)
        await db.commit()
        return company.id


async def _contact(email: str, company_id: int, *also: int) -> int:
    async with AsyncSessionLocal() as db:
        contact = SalesContact(full_name="Kontakt", email=email, company_id=company_id)
        db.add(contact)
        await db.flush()
        db.add(
            SalesCompanyContact(
                company_id=company_id, contact_id=contact.id, is_primary=True
            )
        )
        for other in also:
            db.add(SalesCompanyContact(company_id=other, contact_id=contact.id))
        await db.commit()
        return contact.id


async def _candidate(email: str) -> int:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Ewa",
            lastname=f"Outlook{_tag()}",
            email=email,
            status=CandidateStatus.active,
        )
        db.add(candidate)
        await db.commit()
        return candidate.id


def _graph_msg(
    *, sender: str, to: str, imid: str | None = None, attachments: bool = False
) -> dict:
    graph_id = f"msg-{_tag()}"
    return {
        "id": graph_id,
        "conversationId": f"conv-{_tag()}",
        "internetMessageId": imid or f"<{_tag()}@example.com>",
        "subject": "Oferta współpracy",
        "from": {"emailAddress": {"address": sender}},
        "toRecipients": [{"emailAddress": {"address": to}}],
        "sentDateTime": "2026-10-28T09:00:00Z",
        "receivedDateTime": "2026-10-28T09:00:00Z",
        "bodyPreview": "Dzień dobry, w nawiązaniu do rozmowy…",
        "body": {"contentType": "text", "content": "Dzień dobry"},
        "hasAttachments": attachments,
        "isRead": True,
        "webLink": f"https://outlook.office365.com/owa/?ItemID={graph_id}",
    }


def _graph_event(*attendees: str, start: datetime, uid: str | None = None) -> dict:
    return {
        "id": f"ev-{_tag()}",
        "iCalUId": uid or f"ical-{_tag()}",
        "changeKey": "ck1",
        "subject": "Spotkanie handlowe",
        "bodyPreview": "Agenda",
        "body": {"content": "Agenda"},
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": (start + timedelta(minutes=45)).isoformat()},
        "attendees": [{"emailAddress": {"address": a}} for a in attendees],
        "sensitivity": "normal",
        "webLink": "https://outlook.office365.com/calendar/item/x",
    }


async def _activities(source: str, external_id: str) -> list[SalesActivity]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(SalesActivity)
                    .where(
                        SalesActivity.external_source == source,
                        SalesActivity.external_id == external_id,
                    )
                    .order_by(SalesActivity.company_id)
                )
            ).all()
        )


async def _upsert(user: User, msg: dict, scope: MailboxScope) -> Email:
    async with AsyncSessionLocal() as db:
        row = await sync_mod._upsert_message(
            db, None, _conn(user), msg, "Inbox", scope=scope
        )
        await db.commit()
        return row


# ── Kto podłącza skrzynkę ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sales_view_without_candidates_owns_a_sales_only_mailbox() -> None:
    rep = await _user("employee", "sales_view")
    plain = await _user("employee")
    recruiter = await _user("recruiter")
    async with AsyncSessionLocal() as db:
        for user, expected in (
            (rep, SALES_ONLY),
            (plain, MailboxScope(candidates=False, sales=False)),
            (recruiter, CANDIDATE_SCOPE),
        ):
            fresh = await db.get(User, user.id)
            await resolve_effective_section_access(db, fresh)
            assert mailbox_scope(fresh) == expected
        # Ścieżki kandydatów (wysyłka, rozmowy, CV) dalej odmawiają handlowcowi.
        assert await eligible_m365_owner(db, rep.id) is None
        assert await eligible_m365_owner(db, rep.id, sales_ok=True) is not None
        assert await eligible_m365_owner(db, plain.id, sales_ok=True) is None


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_rep_can_see_and_start_mailbox_connection(
    app_client, monkeypatch
) -> None:
    from app.services.m365 import oauth as m365_oauth

    monkeypatch.setattr(settings, "M365_INTEGRATION_ENABLED", True)
    monkeypatch.setattr(
        m365_oauth, "new_authorize_url", lambda user_id: "https://login.example/x"
    )
    rep = await _user("employee", "sales_view")
    plain = await _user("employee")

    status_resp = await app_client.get(
        "/api/microsoft365/connection", headers=_headers(rep)
    )
    assert status_resp.status_code == 200, status_resp.text
    body = status_resp.json()
    assert body["connected"] is False
    assert body["mail_to_sales"] is True
    assert body["mail_to_candidates"] is False

    auth = await app_client.get("/api/microsoft365/authorize", headers=_headers(rep))
    assert auth.status_code == 200, auth.text

    for path in ("/api/microsoft365/connection", "/api/microsoft365/authorize"):
        denied = await app_client.get(path, headers=_headers(plain))
        assert denied.status_code == 403
    # Sprawdzanie zajętości uczestników to narzędzie rekrutera — nie handlowca.
    busy = await app_client.post(
        "/api/microsoft365/free-busy",
        json={
            "start": "2026-11-02T09:00:00Z",
            "end": "2026-11-02T10:00:00Z",
            "attendees": ["kto@example.com"],
        },
        headers=_headers(rep),
    )
    assert busy.status_code == 403


# ── Odcięcie kandydatów dla skrzynki handlowca ───────────────────────────


@pytest.mark.asyncio
async def test_rep_mail_never_links_a_candidate_nor_downloads_attachments(
    monkeypatch,
) -> None:
    rep = await _user("employee", "sales_view")
    recruiter = await _user("recruiter")
    candidate_mail = f"kandydat-{_tag()}@example.org"
    candidate_id = await _candidate(candidate_mail)

    async def _no_download(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("załączniki skrzynki handlowca nie są pobierane")

    monkeypatch.setattr(sync_mod.attachment_handler, "download_for_email", _no_download)
    row = await _upsert(
        rep,
        _graph_msg(sender=candidate_mail, to=rep.email, attachments=True),
        SALES_ONLY,
    )
    assert row.candidate_id is None
    assert row.match_method == EmailMatchMethod.unmatched

    # Kontrola: ta sama wiadomość w skrzynce rekrutera trafia do kandydata.
    monkeypatch.undo()
    linked = await _upsert(
        recruiter, _graph_msg(sender=candidate_mail, to=recruiter.email), BOTH
    )
    assert linked.candidate_id == candidate_id


@pytest.mark.asyncio
async def test_rep_calendar_never_links_a_candidate() -> None:
    rep = await _user("employee", "sales_view")
    candidate_mail = f"kandydat-{_tag()}@example.org"
    await _candidate(candidate_mail)
    ev = _graph_event(candidate_mail, start=datetime.now(timezone.utc))
    async with AsyncSessionLocal() as db:
        assert await sync_mod._upsert_event(db, _conn(rep), ev, scope=SALES_ONLY)
        await db.commit()
        row = await db.scalar(
            select(CalendarEvent).where(CalendarEvent.external_id == ev["id"])
        )
    assert row.candidate_id is None
    assert row.m365_ical_uid == ev["iCalUId"]


# ── Dopasowanie do firm ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mail_lands_on_company_by_domain_with_outlook_link() -> None:
    rep = await _user("employee", "sales_view")
    domain = f"firma-{_tag()}.example"
    company_id = await _company(f"Firma {domain}", f"https://www.{domain}/kontakt")
    msg = _graph_msg(sender=f"anna@eu.{domain}", to=rep.email)

    row = await _upsert(rep, msg, SALES_ONLY)

    assert row.web_link == msg["webLink"]
    [activity] = await _activities(outlook.EMAIL_SOURCE, msg["internetMessageId"])
    assert activity.company_id == company_id
    assert activity.kind == "email"
    assert activity.direction == "in"
    assert activity.web_link == msg["webLink"]
    assert activity.created_by_user_id == rep.id
    assert activity.contact_id is None
    assert activity.opportunity_id is None


@pytest.mark.asyncio
async def test_mail_lands_on_every_company_of_a_known_contact() -> None:
    rep = await _user("employee", "sales_view")
    first = await _company(f"Spółka A {_tag()}")
    second = await _company(f"Spółka B {_tag()}")
    address = f"zarzad-{_tag()}@grupa.example"
    contact_id = await _contact(address, first, second)
    msg = _graph_msg(sender=rep.email, to=address.upper())

    async with AsyncSessionLocal() as db:
        await sync_mod._upsert_message(
            db, None, _conn(rep), msg, "SentItems", scope=SALES_ONLY
        )
        await db.commit()

    activities = await _activities(outlook.EMAIL_SOURCE, msg["internetMessageId"])
    assert [a.company_id for a in activities] == sorted([first, second])
    assert {a.contact_id for a in activities} == {contact_id}
    assert {a.direction for a in activities} == {"out"}


@pytest.mark.asyncio
async def test_free_mail_internal_and_unknown_addresses_do_not_match(
    monkeypatch,
) -> None:
    rep = await _user("employee", "sales_view")
    internal = f"wew-{_tag()}.example"
    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", internal)
    # Firma z domeną darmowej poczty i firma z domeną NEXUSA (błędny wpis).
    await _company(f"Zła domena {_tag()}", "gmail.com")
    await _company(f"Nasza domena {_tag()}", internal)
    for sender in (
        f"ktos-{_tag()}@gmail.com",
        f"kolega@{internal}",
        f"nieznany@{_tag()}.example",
    ):
        msg = _graph_msg(sender=sender, to=rep.email)
        await _upsert(rep, msg, SALES_ONLY)
        assert await _activities(outlook.EMAIL_SOURCE, msg["internetMessageId"]) == []


@pytest.mark.asyncio
async def test_domain_shared_by_too_many_companies_is_not_a_match() -> None:
    rep = await _user("employee", "sales_view")
    domain = f"wspolna-{_tag()}.example"
    for _ in range(outlook.MAX_DOMAIN_COMPANIES + 1):
        await _company(f"Spółka {_tag()}", domain)
    msg = _graph_msg(sender=f"biuro@{domain}", to=rep.email)
    await _upsert(rep, msg, SALES_ONLY)
    assert await _activities(outlook.EMAIL_SOURCE, msg["internetMessageId"]) == []


@pytest.mark.asyncio
async def test_recruiter_mailbox_does_not_feed_sales() -> None:
    recruiter = await _user("recruiter")
    domain = f"klient-{_tag()}.example"
    await _company(f"Klient {domain}", domain)
    msg = _graph_msg(sender=f"hr@{domain}", to=recruiter.email)
    await _upsert(recruiter, msg, CANDIDATE_SCOPE)
    assert await _activities(outlook.EMAIL_SOURCE, msg["internetMessageId"]) == []


# ── Deduplikacja ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_same_mail_in_two_rep_mailboxes_and_atlas_history_is_one_activity() -> (
    None
):
    rep = await _user("employee", "sales_view")
    other = await _user("employee", "sales_view")
    domain = f"dedup-{_tag()}.example"
    atlas_company = await _company(f"Z Atlasa {domain}", domain)
    imid = f"<{_tag()}@{domain}>"
    async with AsyncSessionLocal() as db:
        db.add(
            SalesActivity(
                company_id=atlas_company,
                kind="email",
                subject="Z Atlasa",
                external_source=outlook.EMAIL_SOURCE,
                external_id=imid,
                external_ref=f"atlas:company_activities:{_tag()}",
            )
        )
        await db.commit()

    for owner in (rep, other, rep):
        await _upsert(
            owner,
            _graph_msg(sender=f"szef@{domain}", to=owner.email, imid=imid),
            SALES_ONLY,
        )

    [activity] = await _activities(outlook.EMAIL_SOURCE, imid)
    assert activity.external_ref is not None
    # Historia z Atlasa zostaje, synchronizacja tylko uzupełnia luki.
    assert activity.subject == "Z Atlasa"
    assert activity.web_link is not None
    assert activity.direction == "in"

    # Bez historii z Atlasa: dwie skrzynki → nadal jedna aktywność na firmę.
    fresh_domain = f"nowa-{_tag()}.example"
    await _company(f"Nowa {fresh_domain}", fresh_domain)
    fresh_imid = f"<{_tag()}@{fresh_domain}>"
    for owner in (rep, other):
        await _upsert(
            owner,
            _graph_msg(sender=f"szef@{fresh_domain}", to=owner.email, imid=fresh_imid),
            SALES_ONLY,
        )
    assert len(await _activities(outlook.EMAIL_SOURCE, fresh_imid)) == 1


@pytest.mark.asyncio
async def test_private_mail_is_not_recorded(monkeypatch) -> None:
    rep = await _user("employee", "sales_view")
    domain = f"prywatna-{_tag()}.example"
    await _company(f"Firma {domain}", domain)
    msg = _graph_msg(sender=f"ktos@{domain}", to=rep.email)
    msg["categories"] = [settings.M365_IGNORE_CATEGORY]
    await _upsert(rep, msg, SALES_ONLY)
    assert await _activities(outlook.EMAIL_SOURCE, msg["internetMessageId"]) == []


# ── Spotkania ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_meeting_is_recorded_and_cancelled_upcoming_meeting_disappears() -> None:
    rep = await _user("employee", "sales_view")
    domain = f"spotkanie-{_tag()}.example"
    company_id = await _company(f"Firma {domain}", domain)
    start = datetime.now(timezone.utc) + timedelta(days=3)
    ev = _graph_event(f"klient@{domain}", start=start)

    async with AsyncSessionLocal() as db:
        await sync_mod._upsert_event(db, _conn(rep), ev, scope=SALES_ONLY)
        await db.commit()
    [meeting] = await _activities(outlook.EVENT_SOURCE, ev["iCalUId"])
    assert meeting.company_id == company_id
    assert meeting.kind == "meeting"
    assert meeting.duration_minutes == 45
    assert meeting.done_at is None

    # Organizator usuwa spotkanie: delta niesie samo id — klucz z wiersza.
    async with AsyncSessionLocal() as db:
        await sync_mod._upsert_event(
            db,
            _conn(rep),
            {"id": ev["id"], "@removed": {"reason": "deleted"}},
            scope=SALES_ONLY,
        )
        await db.commit()
    assert await _activities(outlook.EVENT_SOURCE, ev["iCalUId"]) == []


@pytest.mark.asyncio
async def test_past_meeting_stays_when_cancelled_and_attendee_removal_keeps_live_one() -> (
    None
):
    rep = await _user("employee", "sales_view")
    other = await _user("employee", "sales_view")
    domain = f"przeszle-{_tag()}.example"
    await _company(f"Firma {domain}", domain)

    past = _graph_event(
        f"klient@{domain}", start=datetime.now(timezone.utc) - timedelta(days=2)
    )
    upcoming_uid = f"ical-{_tag()}"
    later = datetime.now(timezone.utc) + timedelta(days=5)
    rep_copy = _graph_event(f"klient@{domain}", start=later, uid=upcoming_uid)
    other_copy = _graph_event(f"klient@{domain}", start=later, uid=upcoming_uid)
    async with AsyncSessionLocal() as db:
        await sync_mod._upsert_event(db, _conn(rep), past, scope=SALES_ONLY)
        await sync_mod._upsert_event(db, _conn(rep), rep_copy, scope=SALES_ONLY)
        await sync_mod._upsert_event(db, _conn(other), other_copy, scope=SALES_ONLY)
        await db.commit()

    async with AsyncSessionLocal() as db:
        await sync_mod._upsert_event(
            db, _conn(rep), {**past, "isCancelled": True}, scope=SALES_ONLY
        )
        # Drugi handlowiec usuwa spotkanie u siebie — u pierwszego dalej stoi.
        await sync_mod._upsert_event(
            db,
            _conn(other),
            {"id": other_copy["id"], "@removed": {"reason": "deleted"}},
            scope=SALES_ONLY,
        )
        await db.commit()

    [kept] = await _activities(outlook.EVENT_SOURCE, past["iCalUId"])
    assert kept.done_at is not None
    assert len(await _activities(outlook.EVENT_SOURCE, upcoming_uid)) == 1


# ── Zaległe maile po podłączeniu ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_catch_up_records_mail_already_synced_before_the_change() -> None:
    admin = await _user("admin")
    domain = f"zalegle-{_tag()}.example"
    company_id = await _company(f"Firma {domain}", domain)
    imid = f"<{_tag()}@{domain}>"
    async with AsyncSessionLocal() as db:
        db.add(
            Email(
                user_id=admin.id,
                m365_message_id=f"old-{_tag()}",
                m365_internet_message_id=imid,
                m365_conversation_id="conv",
                subject="Sprzed wdrożenia",
                from_address=f"zarzad@{domain}",
                to_addresses=[{"address": admin.email}],
                received_at=datetime.now(timezone.utc) - timedelta(days=2),
            )
        )
        await db.commit()

    conn = SimpleNamespace(
        id=10_000_000 + admin.id, user_id=admin.id, mailbox_upn=admin.email
    )
    async with AsyncSessionLocal() as db:
        await sync_mod._sales_catch_up(db, conn)
        # Drugi raz nic nie robi (znacznik w ``app_settings``).
        await sync_mod._sales_catch_up(db, conn)

    [activity] = await _activities(outlook.EMAIL_SOURCE, imid)
    assert activity.company_id == company_id


@pytest.mark.asyncio
async def test_admin_mail_and_meeting_with_a_candidate_stay_off_the_company() -> None:
    """Skrzynka z kandydatami i Sprzedażą (admin): kandydat z adresem w domenie
    firmy sprzedaży nie przenosi korespondencji z nim na oś firmy."""
    admin = await _user("admin")
    domain = f"pracodawca-{_tag()}.example"
    await _company(f"Firma {domain}", domain)
    candidate_mail = f"kandydat@{domain}"
    candidate_id = await _candidate(candidate_mail)

    msg = _graph_msg(sender=candidate_mail, to=admin.email)
    row = await _upsert(admin, msg, BOTH)
    assert row.candidate_id == candidate_id
    assert await _activities(outlook.EMAIL_SOURCE, msg["internetMessageId"]) == []

    ev = _graph_event(
        candidate_mail, start=datetime.now(timezone.utc) + timedelta(days=1)
    )
    async with AsyncSessionLocal() as db:
        await sync_mod._upsert_event(db, _conn(admin), ev, scope=BOTH)
        await db.commit()
    assert await _activities(outlook.EVENT_SOURCE, ev["iCalUId"]) == []

    # Mail z firmy bez kandydatów w tej samej skrzynce idzie na oś jak zwykle.
    # (Mail z domeny pracodawcy kandydata matcher przypina kandydatowi —
    # ``smart_domain`` — więc też zostaje poza Sprzedażą.)
    other_domain = f"bez-kandydata-{_tag()}.example"
    await _company(f"Firma {other_domain}", other_domain)
    other = _graph_msg(sender=f"zarzad@{other_domain}", to=admin.email)
    await _upsert(admin, other, BOTH)
    assert len(await _activities(outlook.EMAIL_SOURCE, other["internetMessageId"])) == 1
