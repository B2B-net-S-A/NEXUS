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


# ── Awaria połączenia, zły wiersz, przerwany przebieg (poprawki 17.10) ──────


async def _rows(announcement_id: int) -> list[CareAnnouncementRecipient]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CareAnnouncementRecipient)
                    .where(CareAnnouncementRecipient.announcement_id == announcement_id)
                    .order_by(CareAnnouncementRecipient.id)
                )
            ).all()
        )


@pytest.mark.usefixtures("care_on", "sending_on", "quiet_queue")
async def test_missing_token_ends_the_pass_without_using_anyones_attempts(
    app_client, monkeypatch
) -> None:
    """Brak tokenu to awaria połączenia: przebieg kończy się od razu, nikt nie
    traci próby i nikt nie trafia do „błąd wysyłki”, choćby trwało to godzinę."""

    from app.services.care.announcement_mail import GraphMailer
    from app.services.hr.m365 import auth as m365_auth

    install_mailer(monkeypatch)
    author = await make_user(UserRole.talent_community_manager)
    announcement_id, _, _ = await _queued(app_client, author, 3)
    asked: list[bool] = []

    def no_token(*, force_refresh: bool = False):
        asked.append(force_refresh)
        return None

    monkeypatch.setattr(m365_auth, "acquire_hr_token", no_token)
    graph = GraphMailer("administracja@example.com")
    minute = _minute()
    for step in range(MAX_PASSES):
        async with AsyncSessionLocal() as db:
            result = await announcement_queue.run_once(
                db, mailer=graph, now=minute + timedelta(minutes=step)
            )
        assert result["status"] == "deferred", result
        assert result["reason"] == "transport"
    # Jedno pytanie o token na przebieg — nie trzy osoby po kolei.
    assert len(asked) == MAX_PASSES
    rows = await _rows(announcement_id)
    assert {row.status for row in rows} == {"pending"}
    assert {row.attempts for row in rows} == {0}
    assert {row.claimed_at for row in rows} == {None}

    fake = FakeMailer()
    async with AsyncSessionLocal() as db:
        await announcement_queue.run_once(
            db, mailer=fake, now=minute + timedelta(minutes=MAX_PASSES)
        )
    assert set(await _statuses(announcement_id)) == {"sent"}


MAX_PASSES = announcement_queue.MAX_ATTEMPTS + 2


@pytest.mark.usefixtures("care_on", "sending_on", "quiet_queue")
async def test_rate_limit_still_defers_one_person_with_attempts(
    app_client, monkeypatch
) -> None:
    install_mailer(monkeypatch)
    author = await make_user(UserRole.talent_community_manager)
    announcement_id, _, _ = await _queued(app_client, author, 2)
    fake = FakeMailer(outcome=MailOutcome("deferred", "http_429"))
    minute = _minute()
    for step in range(announcement_queue.MAX_ATTEMPTS):
        async with AsyncSessionLocal() as db:
            await announcement_queue.run_once(
                db, mailer=fake, now=minute + timedelta(minutes=step)
            )
    rows = await _rows(announcement_id)
    assert {row.status for row in rows} == {"failed"}
    assert {row.attempts for row in rows} == {announcement_queue.MAX_ATTEMPTS}


@pytest.mark.usefixtures("care_on", "sending_on", "quiet_queue")
async def test_one_broken_person_does_not_spoil_the_batch(
    app_client, monkeypatch
) -> None:
    """Błąd przygotowania maila jednej osoby zapisuje jej stan; reszta paczki
    wychodzi, a nikt nie zostaje „w wysyłce” ani „niepewny” bez wysłania."""

    from app.services.care import announcement_mail

    install_mailer(monkeypatch)
    author = await make_user(UserRole.talent_community_manager)
    announcement_id, _, _ = await _queued(app_client, author, 3)
    real_compose = announcement_mail.compose

    def compose(**kwargs):
        if kwargs.get("first_name") == "Osoba1":
            raise ValueError("zepsuty wiersz")
        return real_compose(**kwargs)

    monkeypatch.setattr(announcement_mail, "compose", compose)
    fake = FakeMailer()
    async with AsyncSessionLocal() as db:
        result = await announcement_queue.run_once(db, mailer=fake, now=_minute())
    assert result["status"] == "ok", result
    by_name = {row.first_name: row for row in await _rows(announcement_id)}
    assert by_name["Osoba0"].status == "sent"
    assert by_name["Osoba2"].status == "sent"
    broken = by_name["Osoba1"]
    assert broken.status == "pending" and broken.attempts == 1
    assert broken.error_code == "prepare"
    assert len(fake.sent) == 2


@pytest.mark.usefixtures("care_on", "sending_on", "quiet_queue")
async def test_person_removed_mid_batch_is_skipped(app_client, monkeypatch) -> None:
    """Wiersz osoby zniknął (usunięty kandydat) między rezerwacją a wysyłką."""

    from sqlalchemy import delete

    install_mailer(monkeypatch)
    author = await make_user(UserRole.talent_community_manager)
    announcement_id, _, _ = await _queued(app_client, author, 3)
    rows = await _rows(announcement_id)
    doomed = rows[1].id

    class Deleting(FakeMailer):
        async def send(self, *, to: str, subject: str, text: str) -> MailOutcome:
            if not self.sent:
                async with AsyncSessionLocal() as other:
                    await other.execute(
                        delete(CareAnnouncementRecipient).where(
                            CareAnnouncementRecipient.id == doomed
                        )
                    )
                    await other.commit()
            return await super().send(to=to, subject=subject, text=text)

    fake = Deleting()
    async with AsyncSessionLocal() as db:
        result = await announcement_queue.run_once(db, mailer=fake, now=_minute())
    assert result["status"] == "ok", result
    assert sorted(await _statuses(announcement_id)) == ["sent", "sent"]
    async with AsyncSessionLocal() as db:
        done = await db.get(CareAnnouncement, announcement_id)
    assert done.status == "sent"


@pytest.mark.usefixtures("care_on", "sending_on", "quiet_queue")
async def test_rows_claimed_but_never_started_go_back_to_the_queue(
    app_client, monkeypatch
) -> None:
    """Przerwany przebieg: osoba zarezerwowana, a nieobsłużona, wraca do kolejki
    (dostaje mail); osoba, do której wysyłka ruszyła — „niepewny”."""

    from sqlalchemy import update

    install_mailer(monkeypatch)
    author = await make_user(UserRole.talent_community_manager)
    announcement_id, _, _ = await _queued(app_client, author, 2)
    never_started, mid_send = (row.id for row in await _rows(announcement_id))
    old = datetime.now(timezone.utc) - timedelta(minutes=30)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CareAnnouncementRecipient)
            .where(CareAnnouncementRecipient.id == never_started)
            .values(status="sending", claimed_at=None, updated_at=old)
        )
        await db.execute(
            update(CareAnnouncementRecipient)
            .where(CareAnnouncementRecipient.id == mid_send)
            .values(status="sending", claimed_at=old, updated_at=old)
        )
        await db.commit()
    fake = FakeMailer()
    async with AsyncSessionLocal() as db:
        await announcement_queue.run_once(db, mailer=fake, now=_minute())
    by_id = {row.id: row for row in await _rows(announcement_id)}
    assert by_id[never_started].status == "sent"
    assert by_id[mid_send].status == "uncertain"
    assert len(fake.sent) == 1


@pytest.mark.usefixtures("care_on", "sending_on", "quiet_queue")
async def test_idle_queue_does_not_book_a_job_run(app_client, monkeypatch) -> None:
    from app.models.hr_ops import HrJobRun

    mailer = install_mailer(monkeypatch)
    minute = _minute()
    async with AsyncSessionLocal() as db:
        result = await announcement_queue.run_once(db, mailer=mailer, now=minute)
        booked = await db.scalar(
            select(HrJobRun.id).where(
                HrJobRun.kind == announcement_queue.JOB_KIND,
                HrJobRun.period_key == minute.strftime("%Y-%m-%dT%H:%M"),
            )
        )
    assert result["status"] == "idle"
    assert booked is None


@pytest.mark.usefixtures("care_on", "sending_on", "quiet_queue")
async def test_unstarted_row_of_a_cancelled_announcement_ends_cancelled(
    app_client, monkeypatch
) -> None:
    from sqlalchemy import update

    install_mailer(monkeypatch)
    author = await make_user(UserRole.talent_community_manager)
    announcement_id, _, _ = await _queued(app_client, author, 1)
    (row,) = await _rows(announcement_id)
    old = datetime.now(timezone.utc) - timedelta(minutes=30)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CareAnnouncementRecipient)
            .where(CareAnnouncementRecipient.id == row.id)
            .values(status="sending", claimed_at=None, updated_at=old)
        )
        await db.execute(
            update(CareAnnouncement)
            .where(CareAnnouncement.id == announcement_id)
            .values(status="cancelled")
        )
        await db.commit()
    fake = FakeMailer()
    async with AsyncSessionLocal() as db:
        await announcement_queue.run_once(db, mailer=fake, now=_minute())
    assert await _statuses(announcement_id) == ["cancelled"]
    assert fake.sent == []
