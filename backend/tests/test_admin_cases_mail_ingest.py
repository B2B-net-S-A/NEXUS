"""Czytnik skrzynki administracja@ i haki spraw (E6) — na fałszywej skrzynce.

* nowa wiadomość → nowa sprawa w jednym przebiegu,
* odpowiedź w wątku (``conversationId`` albo ``In-Reply-To``) → ta sama sprawa
  (Compass zakładał sprawę z każdej odpowiedzi — auto-import wyłączono w Fazie 44),
* drugi przebieg niczego nie dubluje, wyłączony czytnik nic nie robi,
* haki kontraktu i odejścia są idempotentne.

Każdy test używa własnego UPN skrzynki (``@example.com``): zmiana skrzynki
zeruje znacznik czytnika, więc testy nie widzą swoich znaczników nawzajem.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.admin_case import AdminCase, AdminCaseMessage, AdminMailIngestState
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.models.hr_ops import HrJobRun
from app.models.user import User, UserRole
from app.services.admin_cases import hooks, mail_ingest
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING


class FakeMailbox:
    """Skrzynka w pamięci o kształcie odpowiedzi Graph."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.attachments: dict[str, list[dict[str, Any]]] = {}
        self.broken: set[str] = set()
        self.calls = 0

    def add(
        self,
        *,
        subject: str,
        hours_ago: float,
        conversation: str | None = None,
        in_reply_to: str | None = None,
        sender: str = "klient@example.com",
        attachments: list[dict[str, Any]] | None = None,
        headers: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        marker = uuid.uuid4().hex
        received = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        msg = {
            "id": f"AAMk-{marker}",
            "internetMessageId": f"<{marker}@example.com>",
            "conversationId": conversation or f"conv-{marker}",
            "subject": subject,
            "from": {"emailAddress": {"address": sender, "name": "Anna Przykładowa"}},
            "receivedDateTime": received.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hasAttachments": bool(attachments),
            "body": {"contentType": "html", "content": f"<p>{subject}</p>"},
            "internetMessageHeaders": [
                *(headers or []),
                *(
                    [{"name": "In-Reply-To", "value": in_reply_to}]
                    if in_reply_to
                    else []
                ),
            ],
        }
        self.messages.append(msg)
        if attachments:
            self.attachments[msg["id"]] = attachments
        return msg

    async def list_messages(
        self, mailbox: str, since: datetime
    ) -> list[dict[str, Any]]:
        self.calls += 1
        return [
            m
            for m in self.messages
            if mail_ingest._parse_dt(m["receivedDateTime"]) >= since
        ]

    async def list_attachments(
        self, mailbox: str, message_id: str
    ) -> list[dict[str, Any]]:
        if message_id in self.broken:
            raise RuntimeError("Graph 500")
        return self.attachments.get(message_id, [])


async def _set_cases_module(enabled: bool) -> Optional[dict]:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        previous = dict(row.value) if row is not None else None
        value = {
            **(previous or {key: False for key in HR_MODULE_KEYS}),
            "cases": enabled,
        }
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()
    return previous


async def _restore_modules(previous: Optional[dict]) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        row.value = previous or {key: False for key in HR_MODULE_KEYS}
        await db.commit()


@pytest_asyncio.fixture
async def cases_on():
    previous = await _set_cases_module(True)
    yield
    await _restore_modules(previous)


@pytest_asyncio.fixture
async def cases_off():
    previous = await _set_cases_module(False)
    yield
    await _restore_modules(previous)


@pytest.fixture
def mailbox_on(monkeypatch, cases_on) -> str:
    upn = f"administracja-{uuid.uuid4().hex[:8]}@example.com"
    monkeypatch.setenv(mail_ingest.MAILBOX_ENV, upn)
    monkeypatch.setenv(mail_ingest.ENABLED_ENV, "true")
    return upn


async def _run(fake: FakeMailbox) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return await mail_ingest.run_once(db, graph=fake)


async def _cases_for(fake: FakeMailbox) -> dict[str, int]:
    """graph_message_id → case_id dla wiadomości tej fałszywej skrzynki."""
    ids = [m["id"] for m in fake.messages]
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(AdminCaseMessage.graph_message_id, AdminCaseMessage.case_id).where(
                AdminCaseMessage.graph_message_id.in_(ids)
            )
        )
        return {row.graph_message_id: row.case_id for row in rows}


@pytest.mark.asyncio
async def test_new_mail_becomes_a_case_and_replies_join_it(mailbox_on) -> None:
    fake = FakeMailbox()
    first = fake.add(
        subject="Polisa OC dla konsultanta",
        hours_ago=5,
        attachments=[
            {"name": "polisa.pdf", "contentType": "application/pdf", "size": 1024}
        ],
    )
    other = fake.add(subject="Post na LinkedIn: kariera", hours_ago=4)

    result = await _run(fake)
    assert result["status"] == "ok"
    assert result["created"] == 2

    reply_same_conversation = fake.add(
        subject="RE: Polisa OC dla konsultanta",
        hours_ago=1,
        conversation=first["conversationId"],
    )
    reply_by_header = fake.add(
        subject="Odp: Post na LinkedIn",
        hours_ago=0.5,
        in_reply_to=other["internetMessageId"],
    )
    second = await _run(fake)
    assert second["status"] == "ok"
    assert second.get("created", 0) == 0
    assert second["attached"] == 2
    assert second["duplicate"] == 2

    by_message = await _cases_for(fake)
    assert by_message[reply_same_conversation["id"]] == by_message[first["id"]]
    assert by_message[reply_by_header["id"]] == by_message[other["id"]]
    assert by_message[first["id"]] != by_message[other["id"]]

    async with AsyncSessionLocal() as db:
        case = await db.get(AdminCase, by_message[first["id"]])
        marketing = await db.get(AdminCase, by_message[other["id"]])
        stored = await db.scalar(
            select(AdminCaseMessage).where(
                AdminCaseMessage.graph_message_id == first["id"]
            )
        )
    assert case.source == "mail"
    assert case.priority == "P2"
    assert case.title == "Polisa OC dla konsultanta"
    assert case.due_on is not None
    assert marketing.area == "marketing"
    assert stored.body_text == "Polisa OC dla konsultanta"
    assert stored.attachments == [
        {
            "name": "polisa.pdf",
            "content_type": "application/pdf",
            "size": 1024,
            "inline": False,
        }
    ]


@pytest.mark.asyncio
async def test_second_run_duplicates_nothing(mailbox_on) -> None:
    fake = FakeMailbox()
    fake.add(subject="Faktura za szkolenie BHP", hours_ago=3)
    fake.add(subject="Badania okresowe", hours_ago=2)

    await _run(fake)
    again = await _run(fake)
    assert again.get("created", 0) == 0
    assert again["duplicate"] == 2

    by_message = await _cases_for(fake)
    assert len(by_message) == 2
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count(AdminCaseMessage.id)).where(
                AdminCaseMessage.graph_message_id.in_(list(by_message))
            )
        )
    assert count == 2


@pytest.mark.asyncio
async def test_disabled_reader_does_nothing(monkeypatch) -> None:
    fake = FakeMailbox()
    fake.add(subject="Nie powinno trafić do spraw", hours_ago=1)

    monkeypatch.delenv(mail_ingest.MAILBOX_ENV, raising=False)
    monkeypatch.setenv(mail_ingest.ENABLED_ENV, "true")
    assert await _run(fake) == {"status": "disabled"}

    monkeypatch.setenv(mail_ingest.MAILBOX_ENV, "administracja@example.com")
    monkeypatch.setenv(mail_ingest.ENABLED_ENV, "false")
    assert await _run(fake) == {"status": "disabled"}

    assert fake.calls == 0
    assert await _cases_for(fake) == {}


@pytest.mark.asyncio
async def test_reader_waits_for_the_cases_module(monkeypatch, cases_off) -> None:
    fake = FakeMailbox()
    fake.add(subject="Moduł jeszcze wyłączony", hours_ago=1)
    monkeypatch.setenv(mail_ingest.MAILBOX_ENV, "administracja@example.com")
    monkeypatch.setenv(mail_ingest.ENABLED_ENV, "true")

    assert await _run(fake) == {"status": "disabled"}
    assert fake.calls == 0


@pytest.mark.asyncio
async def test_reply_reopens_finished_case(mailbox_on) -> None:
    fake = FakeMailbox()
    first = fake.add(subject="Zaświadczenie o współpracy", hours_ago=6)
    await _run(fake)
    case_id = (await _cases_for(fake))[first["id"]]
    async with AsyncSessionLocal() as db:
        case = await db.get(AdminCase, case_id)
        case.status = "closed"
        case.closed_at = datetime.now(timezone.utc)
        await db.commit()

    fake.add(
        subject="RE: Zaświadczenie o współpracy",
        hours_ago=1,
        conversation=first["conversationId"],
    )
    result = await _run(fake)
    assert result["reopened"] == 1
    async with AsyncSessionLocal() as db:
        case = await db.get(AdminCase, case_id)
    assert case.status == "new"
    assert case.closed_at is None


@pytest.mark.asyncio
async def test_broken_message_does_not_stop_the_rest_and_is_retried(
    mailbox_on,
) -> None:
    fake = FakeMailbox()
    broken = fake.add(
        subject="Umowa z załącznikiem",
        hours_ago=3,
        attachments=[
            {"name": "umowa.pdf", "contentType": "application/pdf", "size": 1}
        ],
    )
    fine = fake.add(subject="Pytanie o urlop", hours_ago=2)
    fake.broken.add(broken["id"])

    result = await _run(fake)
    assert result["status"] == "partial"
    assert result["failed"] == 1
    assert result["created"] == 1
    assert set(await _cases_for(fake)) == {fine["id"]}

    async with AsyncSessionLocal() as db:
        state = await db.get(AdminMailIngestState, 1)
    assert state.last_status == "partial"
    assert state.last_received_at < mail_ingest._parse_dt(broken["receivedDateTime"])

    fake.broken.clear()
    retry = await _run(fake)
    assert retry["created"] == 1
    assert set(await _cases_for(fake)) == {broken["id"], fine["id"]}


@pytest.mark.asyncio
async def test_messages_sent_from_the_mailbox_itself_are_skipped(mailbox_on) -> None:
    fake = FakeMailbox()
    fake.add(
        subject="Kopia wysłanej odpowiedzi", hours_ago=1, sender=mailbox_on.upper()
    )
    result = await _run(fake)
    assert result["skipped"] == 1
    assert await _cases_for(fake) == {}


@pytest.mark.asyncio
async def test_reply_from_public_address_joins_case_without_reopening(
    monkeypatch, cases_on
) -> None:
    # Wariant B (18.10.2026): administracja@ na home.pl, NEXUS czyta kopię
    # w skrzynce M365. Odpowiedź ludzi z home.pl z administracja@ w kopii
    # przychodzi z adresu widocznego — to nie nowe zgłoszenie.
    public = f"administracja-{uuid.uuid4().hex[:8]}@example.com"
    copy = f"nexus-{uuid.uuid4().hex[:8]}@example.com"
    monkeypatch.setenv(mail_ingest.MAILBOX_ENV, public)
    monkeypatch.setenv(mail_ingest.M365_MAILBOX_ENV, copy)
    monkeypatch.setenv(mail_ingest.ENABLED_ENV, "true")
    fake = FakeMailbox()
    first = fake.add(subject="Zaświadczenie o zatrudnieniu", hours_ago=6)
    await _run(fake)
    case_id = (await _cases_for(fake))[first["id"]]
    async with AsyncSessionLocal() as db:
        case = await db.get(AdminCase, case_id)
        case.status = "done"
        case.closed_at = datetime.now(timezone.utc)
        await db.commit()

    reply = fake.add(
        subject="RE: Zaświadczenie o zatrudnieniu",
        hours_ago=1,
        conversation=first["conversationId"],
        sender=public.upper(),
    )
    outside = fake.add(
        subject="Przypomnienie o badaniach", hours_ago=0.5, sender=public
    )
    result = await _run(fake)
    assert result["attached"] == 1
    assert result["skipped"] == 1
    assert result.get("created", 0) == 0 and result.get("reopened", 0) == 0
    by_message = await _cases_for(fake)
    assert by_message[reply["id"]] == case_id
    assert outside["id"] not in by_message
    async with AsyncSessionLocal() as db:
        case = await db.get(AdminCase, case_id)
    assert case.status == "done"
    assert case.closed_at is not None


@pytest.mark.asyncio
async def test_auto_replies_do_not_open_cases(mailbox_on) -> None:
    """Fala „jestem na urlopie” po komunikacie albo mailu powitalnym nie
    zakłada spraw ani nie otwiera zamkniętej (audyt 19.10.2026)."""

    fake = FakeMailbox()
    first = fake.add(subject="Zaświadczenie o zatrudnieniu", hours_ago=6)
    await _run(fake)
    case_id = (await _cases_for(fake))[first["id"]]
    async with AsyncSessionLocal() as db:
        case = await db.get(AdminCase, case_id)
        case.status = "done"
        case.closed_at = datetime.now(timezone.utc)
        await db.commit()

    headered = fake.add(subject="Jestem na urlopie", hours_ago=2)
    headered["internetMessageHeaders"] = [
        {"name": "Auto-Submitted", "value": "auto-replied"}
    ]
    fake.add(subject="Automatic reply: Komunikat dla konsultantów", hours_ago=1.5)
    in_thread = fake.add(
        subject="Odpowiedź automatyczna: Zaświadczenie o zatrudnieniu",
        hours_ago=1,
        conversation=first["conversationId"],
    )
    result = await _run(fake)
    assert result.get("created", 0) == 0 and result.get("reopened", 0) == 0
    assert result["skipped"] == 2 and result["attached"] == 1
    by_message = await _cases_for(fake)
    assert by_message[in_thread["id"]] == case_id
    assert headered["id"] not in by_message
    async with AsyncSessionLocal() as db:
        assert (await db.get(AdminCase, case_id)).status == "done"


def test_auto_reply_detection_spares_real_mail_and_bounces() -> None:
    def msg(subject: str, *headers: tuple[str, str]) -> dict:
        return {
            "subject": subject,
            "internetMessageHeaders": [{"name": n, "value": v} for n, v in headers],
        }

    auto = mail_ingest._is_auto_reply
    assert auto(msg("x", ("Auto-Submitted", "auto-replied")), "a@example.com")
    assert auto(msg("x", ("X-Autoreply", "yes")), "a@example.com")
    assert auto(msg("x", ("Precedence", "auto_reply")), "a@example.com")
    assert auto(msg("Out of Office: urlop"), "a@example.com")
    assert not auto(msg("x", ("Auto-Submitted", "no")), "a@example.com")
    assert not auto(msg("Wniosek o nieobecność"), "a@example.com")
    # Zwrotki przypina do komunikatu link_mail_case — nie są autoodpowiedzią.
    bounce = msg("Undeliverable", ("Auto-Submitted", "auto-replied"))
    assert not auto(bounce, "postmaster@example.com")


@pytest.mark.asyncio
async def test_running_lease_skips_a_parallel_run(mailbox_on) -> None:
    fake = FakeMailbox()
    fake.add(subject="Równoległy przebieg", hours_ago=1)
    async with AsyncSessionLocal() as db:
        assert await mail_ingest._claim_lease(db, datetime.now(timezone.utc))
    try:
        assert await _run(fake) == {"status": "skipped", "reason": "already_running"}
        assert fake.calls == 0
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(HrJobRun)
                .where(
                    HrJobRun.kind == mail_ingest.JOB_KIND,
                    HrJobRun.period_key == mail_ingest.LEASE_KEY,
                )
                .values(status="done")
            )
            await db.commit()
    assert (await _run(fake))["created"] == 1


# ── Haki dla innych modułów ──────────────────────────────────────────────────


@pytest_asyncio.fixture
async def contract_id() -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Arkada Przykładowa {tag}")
        candidate = Candidate(
            name="Anna", lastname=f"Przykładowa{tag}", email=f"anna-{tag}@example.com"
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            start_date=business_today() + timedelta(days=20),
        )
        db.add(contract)
        await db.commit()
        return contract.id


@pytest.mark.asyncio
async def test_new_contract_hook_is_idempotent(contract_id: int, cases_on) -> None:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        first = await hooks.open_case_for_new_contract(db, contract)
        again = await hooks.open_case_for_new_contract(db, contract)
        await db.commit()
        count = await db.scalar(
            select(func.count(AdminCase.id)).where(AdminCase.contract_id == contract_id)
        )
    assert first.id == again.id
    assert count == 1
    assert first.title.startswith("Wejście konsultanta: Anna Przykładowa")
    assert "Arkada Przykładowa" in first.title
    assert first.area == "onboarding"
    assert first.source == "contract"
    assert first.source_key == f"contract:{contract_id}:start"
    assert first.due_on == contract.start_date


@pytest.mark.asyncio
async def test_hooks_do_nothing_while_the_module_is_off(
    contract_id: int, cases_off
) -> None:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert await hooks.open_case_for_new_contract(db, contract) is None
        assert await hooks.open_case_for_offboarding(db, 1, None) is None
        await db.commit()
        count = await db.scalar(
            select(func.count(AdminCase.id)).where(AdminCase.contract_id == contract_id)
        )
    assert count == 0


@pytest.mark.asyncio
async def test_offboarding_hook_is_idempotent(cases_on) -> None:
    async with AsyncSessionLocal() as db:
        leaver = User(
            email=f"leaver-{uuid.uuid4().hex[:8]}@example.com",
            name="Tomasz Przykładowy",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        db.add(leaver)
        await db.flush()
        lifecycle_case_id = 900_000 + leaver.id
        first = await hooks.open_case_for_offboarding(db, leaver.id, lifecycle_case_id)
        again = await hooks.open_case_for_offboarding(db, leaver.id, lifecycle_case_id)
        await db.commit()
    assert first.id == again.id
    assert first.title == "Odejście: Tomasz Przykładowy"
    assert first.area == "offboarding"
    assert first.subject_user_id == leaver.id
    assert first.lifecycle_case_id == lifecycle_case_id
    assert first.source_key == f"lifecycle:{lifecycle_case_id}:offboarding"
