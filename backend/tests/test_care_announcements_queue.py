"""Kolejka komunikatów (O12): 30 maili na minutę, osobny mail do każdego, wypis.

Kolejka bierze najwyżej 30 osób na minutę (rezerwacja minuty w
``hr_job_runs`` — drugi proces w tej samej minucie nic nie wyśle), każdy
dostaje osobny mail z własnym imieniem i opiekunem, a informacyjny — własny
link wypisu (w bazie tylko SHA-256 tokenu). Wyłączony przełącznik zatrzymuje
kolejkę w miejscu. Fałszywy nadawca — nic nie wychodzi. Dane fikcyjne.
"""

from __future__ import annotations

import hashlib
import random
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.care_announcement import CareAnnouncement, CareAnnouncementRecipient
from app.models.user import UserRole
from app.services.care import announcement_queue
from app.services.care.announcement_mail import MailOutcome
from tests.care_announcements_seed import (  # noqa: F401  (fixture'y)
    BASE,
    FakeMailer,
    announcement_routes,
    care_on,
    draft_body,
    headers,
    install_mailer,
    make_client,
    make_consultant,
    make_user,
    quiet_queue,
    sending_on,
    set_sending,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("announcement_routes")]

TOKEN_RE = re.compile(r"/wypis/([A-Za-z0-9_-]{20,})")


def _minute() -> datetime:
    """Własna minuta testu — rezerwacje w ``hr_job_runs`` zostają między testami."""

    base = datetime(2031, 1, 1, tzinfo=timezone.utc)
    return base + timedelta(minutes=random.randint(0, 5_000_000))


async def _queued(app_client, author, n: int, *, kind: str = "mandatory", **extra):
    owner = await make_user(UserRole.talent_community_manager, name="Natalia")
    client_id = await make_client()
    candidates = []
    for index in range(n):
        _contract, candidate = await make_consultant(
            client_id, first_name=f"Osoba{index}", owner_id=owner.id, **extra
        )
        candidates.append(candidate)
    created = await app_client.post(
        BASE,
        json=draft_body(
            kind=kind, audience={"group": "client", "client_ids": [client_id]}
        ),
        headers=headers(author),
    )
    assert created.status_code == 201, created.text
    url = f"{BASE}/{created.json()['id']}"
    await app_client.post(f"{url}/test-send", headers=headers(author))
    submitted = await app_client.post(f"{url}/submit", headers=headers(author))
    assert submitted.status_code == 200, submitted.text
    return created.json()["id"], candidates, owner


async def _statuses(announcement_id: int) -> list[str]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CareAnnouncementRecipient.status).where(
                        CareAnnouncementRecipient.announcement_id == announcement_id
                    )
                )
            ).all()
        )


@pytest.mark.usefixtures("care_on", "sending_on", "quiet_queue")
async def test_queue_sends_thirty_a_minute_one_mail_per_person(
    app_client, monkeypatch
) -> None:
    mailer = install_mailer(monkeypatch)
    author = await make_user(UserRole.talent_community_manager)
    announcement_id, candidates, owner = await _queued(app_client, author, 20)
    second_id, more, _ = await _queued(app_client, author, 15)
    mailer.sent.clear()

    minute = _minute()
    async with AsyncSessionLocal() as db:
        first = await announcement_queue.run_once(db, mailer=mailer, now=minute)
    assert first["sent"] == 30
    assert len(mailer.sent) == 30
    # Ta sama minuta (drugi proces, restart) — nic więcej.
    async with AsyncSessionLocal() as db:
        same = await announcement_queue.run_once(db, mailer=mailer, now=minute)
    assert same["status"] == "skipped"
    assert len(mailer.sent) == 30

    async with AsyncSessionLocal() as db:
        await announcement_queue.run_once(
            db, mailer=mailer, now=minute + timedelta(minutes=1)
        )
    assert len(mailer.sent) == 35
    # Osobny mail do każdego: jeden adresat w polu „Do”, bez powtórzeń.
    addresses = [mail["to"] for mail in mailer.sent]
    assert len(set(addresses)) == 35
    assert all("," not in address and ";" not in address for address in addresses)
    # Pola uzupełnione per osoba, znacznik komunikatu w temacie.
    sample = next(mail for mail in mailer.sent if "Osoba3" in mail["text"])
    assert "{imię}" not in sample["text"] and "{opiekun}" not in sample["text"]
    assert owner.name in sample["text"]
    assert re.search(
        rf"\[Komunikat {announcement_id}/[A-Z0-9]{{4,8}}\]", sample["subject"]
    )

    assert set(await _statuses(announcement_id)) == {"sent"}
    assert set(await _statuses(second_id)) == {"sent"}
    async with AsyncSessionLocal() as db:
        done = await db.get(CareAnnouncement, announcement_id)
        assert done.status == "sent" and done.send_finished_at is not None


@pytest.mark.usefixtures("care_on", "sending_on", "quiet_queue")
async def test_switched_off_sending_stops_the_queue(app_client, monkeypatch) -> None:
    mailer = install_mailer(monkeypatch)
    author = await make_user(UserRole.talent_community_manager)
    announcement_id, _, _ = await _queued(app_client, author, 3)
    mailer.sent.clear()
    await set_sending(False)
    try:
        async with AsyncSessionLocal() as db:
            result = await announcement_queue.run_once(db, mailer=mailer, now=_minute())
    finally:
        await set_sending(True)
    assert result["status"] == "disabled"
    assert mailer.sent == []
    assert set(await _statuses(announcement_id)) == {"pending"}


@pytest.mark.usefixtures("care_on")
async def test_default_settings_send_nothing(app_client, monkeypatch) -> None:
    """Brak wiersza przełącznika (stan po wdrożeniu) = kolejka nic nie wysyła."""

    mailer = install_mailer(monkeypatch)
    await set_sending(None)
    async with AsyncSessionLocal() as db:
        result = await announcement_queue.run_once(db, mailer=mailer, now=_minute())
    assert result["status"] == "disabled"
    assert mailer.sent == []


@pytest.mark.usefixtures("care_on", "sending_on", "quiet_queue")
async def test_informational_carries_own_unsubscribe_link_hashed_in_db(
    app_client, monkeypatch
) -> None:
    mailer = install_mailer(monkeypatch)
    author = await make_user(UserRole.talent_community_manager)
    announcement_id, _, _ = await _queued(app_client, author, 2, kind="informational")
    mandatory_id, _, _ = await _queued(app_client, author, 1)
    mailer.sent.clear()
    async with AsyncSessionLocal() as db:
        await announcement_queue.run_once(db, mailer=mailer, now=_minute())

    informational = [
        m for m in mailer.sent if f"Komunikat {announcement_id}/" in m["subject"]
    ]
    tokens = [TOKEN_RE.search(mail["text"]).group(1) for mail in informational]
    assert len(set(tokens)) == 2
    async with AsyncSessionLocal() as db:
        stored = set(
            (
                await db.scalars(
                    select(CareAnnouncementRecipient.unsubscribe_token_sha256).where(
                        CareAnnouncementRecipient.announcement_id == announcement_id
                    )
                )
            ).all()
        )
    assert stored == {hashlib.sha256(token.encode()).hexdigest() for token in tokens}
    assert not set(tokens) & stored  # surowego tokenu w bazie nie ma

    mandatory = [m for m in mailer.sent if f"Komunikat {mandatory_id}/" in m["subject"]]
    assert mandatory and not TOKEN_RE.search(mandatory[0]["text"])


@pytest.mark.usefixtures("care_on", "sending_on", "quiet_queue")
async def test_opt_out_after_freezing_is_respected_at_send_time(
    app_client, monkeypatch
) -> None:
    mailer = install_mailer(monkeypatch)
    author = await make_user(UserRole.talent_community_manager)
    announcement_id, candidates, _ = await _queued(
        app_client, author, 2, kind="informational"
    )
    async with AsyncSessionLocal() as db:
        from app.models.care_announcement import CareAnnouncementOptOut

        db.add(CareAnnouncementOptOut(candidate_id=candidates[0]))
        await db.commit()
    mailer.sent.clear()
    async with AsyncSessionLocal() as db:
        await announcement_queue.run_once(db, mailer=mailer, now=_minute())
    assert len(mailer.sent) == 1
    assert sorted(await _statuses(announcement_id)) == ["excluded_opted_out", "sent"]


@pytest.mark.usefixtures("care_on", "sending_on", "quiet_queue")
async def test_uncertain_is_not_retried_and_deferred_is(
    app_client, monkeypatch
) -> None:
    install_mailer(monkeypatch)
    author = await make_user(UserRole.talent_community_manager)
    announcement_id, _, _ = await _queued(app_client, author, 2)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(CareAnnouncementRecipient).where(
                    CareAnnouncementRecipient.announcement_id == announcement_id
                )
            )
        ).all()
        uncertain_to, deferred_to = rows[0].email, rows[1].email
    fake = FakeMailer(
        per_address={
            uncertain_to: MailOutcome("uncertain", "http_504"),
            deferred_to: MailOutcome("deferred", "http_429"),
        }
    )
    minute = _minute()
    async with AsyncSessionLocal() as db:
        await announcement_queue.run_once(db, mailer=fake, now=minute)
    assert sorted(await _statuses(announcement_id)) == ["pending", "uncertain"]

    fake.per_address.pop(deferred_to)
    async with AsyncSessionLocal() as db:
        await announcement_queue.run_once(
            db, mailer=fake, now=minute + timedelta(minutes=1)
        )
    # Niepewny nie dostaje drugiego maila; odłożony wychodzi przy następnej minucie.
    assert [mail["to"] for mail in fake.sent].count(uncertain_to) == 1
    assert [mail["to"] for mail in fake.sent].count(deferred_to) == 2
    assert sorted(await _statuses(announcement_id)) == ["sent", "uncertain"]


@pytest.mark.usefixtures("care_on", "sending_on", "quiet_queue")
async def test_report_counts_sent_failed_and_exclusions(
    app_client, monkeypatch
) -> None:
    mailer = install_mailer(monkeypatch)
    author = await make_user(UserRole.talent_community_manager)
    announcement_id, _, _ = await _queued(app_client, author, 2)
    async with AsyncSessionLocal() as db:
        failing = await db.scalar(
            select(CareAnnouncementRecipient.email)
            .where(CareAnnouncementRecipient.announcement_id == announcement_id)
            .limit(1)
        )
    mailer.per_address[failing] = MailOutcome("failed", "http_400")
    async with AsyncSessionLocal() as db:
        await announcement_queue.run_once(db, mailer=mailer, now=_minute())
    detail = await app_client.get(f"{BASE}/{announcement_id}", headers=headers(author))
    counts = detail.json()["counts"]
    assert counts["sent"] == 1 and counts["failed"] == 1
    assert detail.json()["status"] == "sent"
