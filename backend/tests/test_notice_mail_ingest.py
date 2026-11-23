"""Wypowiedzenia z poczty: czytnik spraw → propozycja → karta → decyzja (0755).

Dane fikcyjne (repo publiczne). Ścieżka jak na produkcji: mail na skrzynkę,
``mail_ingest.run_once``, propozycja przy sprawie, karta pod „Zakończenie”,
decyzja z kontrolą, że kontrakt naprawdę się zmienił.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.admin_case import AdminCase, AdminCaseMessage
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.notice_mail import KnownSenderEmail, NoticeMailProposal
from app.models.user import User, UserRole
from app.services.admin_cases import notice_mail, notice_view
from app.services.back_office import sources
from tests.test_admin_cases_mail_ingest import (  # noqa: F401 — fikstury
    FakeMailbox,
    _run,
    cases_on,
    mailbox_on,
)


def _body(msg: dict[str, Any], text: str) -> None:
    msg["body"] = {"contentType": "text", "content": text}


@pytest_asyncio.fixture
async def consultant() -> dict[str, Any]:
    # Same litery: z adresu ``imie.nazwisko@`` czytamy tylko słowa bez cyfr.
    tag = "".join(chr(97 + int(ch, 16)) for ch in uuid.uuid4().hex[:8])
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bank Wzorcowy {tag}")
        candidate = Candidate(
            name="Jan",
            lastname=f"Testowy{tag}",
            email=f"jan.prywatny-{tag}@example.com",
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            start_date=business_today() - timedelta(days=200),
            status=ContractStatus.active,
        )
        user = User(
            email=f"bo-{tag}@example.com",
            name="Obsługa Spraw",
            role=UserRole.admin,
            is_active=True,
        )
        db.add_all([contract, user])
        await db.commit()
        return {
            "tag": tag,
            "contract_id": contract.id,
            "candidate_id": candidate.id,
            "email": candidate.email,
            "company_email": f"jan.testowy{tag}@b2bnetwork.pl",
            "user_id": user.id,
        }


async def _proposals(case_id: int) -> list[NoticeMailProposal]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(NoticeMailProposal)
                    .where(NoticeMailProposal.case_id == case_id)
                    .order_by(NoticeMailProposal.id)
                )
            ).all()
        )


async def _case_of(graph_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(AdminCaseMessage.case_id).where(
                AdminCaseMessage.graph_message_id == graph_id
            )
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("mailbox_on")
async def test_notice_mail_becomes_a_proposal_on_the_ending_label(consultant) -> None:
    fake = FakeMailbox()
    msg = fake.add(
        subject="Wypowiedzenie umowy B2B",
        hours_ago=2,
        sender=consultant["email"],
        attachments=[
            {
                "name": "Wypowiedzenie umowy.pdf",
                "contentType": "application/pdf",
                "size": 9,
            }
        ],
    )
    _body(msg, "Cześć, w załączniku wypowiedzenie umowy. Proszę o potwierdzenie.")
    result = await _run(fake)
    assert result["status"] == "ok"

    case_id = await _case_of(msg["id"])
    [proposal] = await _proposals(case_id)
    assert proposal.kind == "consultant_notice"
    assert proposal.status == "pending"
    assert proposal.contract_id == consultant["contract_id"]
    assert proposal.match["reasons"] == ["sender"]
    assert proposal.proposed_last_day is not None
    assert proposal.proposed_last_day > proposal.delivered_on

    async with AsyncSessionLocal() as db:
        case = await db.get(AdminCase, case_id)
        # Automat nie łączy sprawy z kontraktem — robi to człowiek przy potwierdzeniu.
        assert case.contract_id is None
        assert case.area == "offboarding"
        cards = {c.case_id: c for c in await sources.case_cards(db, business_today())}
    card = cards[case_id]
    assert (card.team, card.lane) == ("contracts", "ending")
    assert card.meta["notice_kind"] == "consultant_notice"
    assert card.meta["notice_id"] == proposal.id
    assert card.contract_id == consultant["contract_id"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("mailbox_on")
async def test_reply_quoting_the_notice_does_not_duplicate_and_withdrawal_is_seen(
    consultant,
) -> None:
    fake = FakeMailbox()
    first = fake.add(
        subject="Wypowiedzenie",
        hours_ago=3,
        sender=consultant["email"],
        attachments=[
            {"name": "wypowiedzenie.pdf", "contentType": "application/pdf", "size": 9}
        ],
    )
    _body(first, "W załączniku wypowiedzenie.")
    await _run(fake)
    thanks = fake.add(
        subject="Re: Wypowiedzenie",
        hours_ago=2,
        conversation=first["conversationId"],
        sender=consultant["email"],
    )
    _body(thanks, "Dzięki za info.\n\nFrom: x\nW załączniku wypowiedzenie.")
    withdraw = fake.add(
        subject="Re: Wypowiedzenie",
        hours_ago=1,
        conversation=first["conversationId"],
        sender=consultant["email"],
    )
    _body(withdraw, "Po rozmowie wycofuję wypowiedzenie i zostaję w projekcie.")
    await _run(fake)

    case_id = await _case_of(first["id"])
    kinds = [p.kind for p in await _proposals(case_id)]
    assert kinds == ["consultant_notice", "withdrawal"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("mailbox_on")
async def test_company_address_matches_by_name_and_is_remembered_on_confirm(
    consultant,
) -> None:
    fake = FakeMailbox()
    msg = fake.add(
        subject="Wypowiedzenie umowy współpracy",
        hours_ago=2,
        sender=consultant["company_email"],
        headers=[
            {
                "name": "Authentication-Results",
                "value": "mx.microsoft.com 1; dkim=pass header.d=b2bnetwork.pl; "
                "dmarc=pass action=none header.from=b2bnetwork.pl",
            }
        ],
    )
    _body(msg, "Nawiązując do rozmowy, składam wypowiedzenie umowy.")
    await _run(fake)
    case_id = await _case_of(msg["id"])
    [proposal] = await _proposals(case_id)
    assert proposal.contract_id == consultant["contract_id"]
    assert proposal.match["reasons"] == ["name"]
    assert proposal.match["sender_authenticated"] is True

    async with AsyncSessionLocal() as db:
        actor = await db.get(User, consultant["user_id"])
        row = await db.get(NoticeMailProposal, proposal.id)
        with pytest.raises(notice_view.NoticeError) as refused:
            await notice_view.decide(
                db,
                row,
                actor=actor,
                decision="confirmed",
                contract_id=None,
                remember_sender=True,
                applied={},
                note=None,
            )
        assert refused.value.code == "not_terminated"
        await db.rollback()

    # Karta najpierw woła „Zakończ współpracę”; tu skrót: kontrakt kończący się.
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, consultant["contract_id"])
        contract.status = ContractStatus.ending
        contract.end_date = proposal.proposed_last_day
        contract.terminated_at = proposal.proposed_last_day
        await db.commit()

    async with AsyncSessionLocal() as db:
        actor = await db.get(User, consultant["user_id"])
        row = await db.get(NoticeMailProposal, proposal.id)
        await notice_view.decide(
            db,
            row,
            actor=actor,
            decision="confirmed",
            contract_id=None,
            remember_sender=True,
            applied={"last_day": proposal.proposed_last_day.isoformat()},
            note=None,
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        row = await db.get(NoticeMailProposal, proposal.id)
        case = await db.get(AdminCase, case_id)
        known = await db.get(KnownSenderEmail, consultant["company_email"])
        assert row.status == "confirmed"
        assert row.decided_by == consultant["user_id"]
        assert case.contract_id == consultant["contract_id"]
        assert case.status == "done"
        assert known is not None and known.candidate_id == consultant["candidate_id"]
        cards = {c.case_id for c in await sources.case_cards(db, business_today())}
        assert case_id not in cards


@pytest.mark.asyncio
@pytest.mark.usefixtures("mailbox_on")
async def test_rejected_proposal_returns_the_case_to_its_normal_label(
    consultant,
) -> None:
    fake = FakeMailbox()
    msg = fake.add(
        subject="Wypowiedzenie umowy", hours_ago=2, sender=consultant["email"]
    )
    _body(msg, "Składam wypowiedzenie umowy B2B.")
    await _run(fake)
    case_id = await _case_of(msg["id"])
    [proposal] = await _proposals(case_id)
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, consultant["user_id"])
        row = await db.get(NoticeMailProposal, proposal.id)
        await notice_view.decide(
            db,
            row,
            actor=actor,
            decision="rejected",
            contract_id=None,
            remember_sender=False,
            applied={},
            note="To pytanie o wzór.",
        )
        await db.commit()
        cards = {c.case_id: c for c in await sources.case_cards(db, business_today())}
        detail = await notice_view.proposal_detail(
            db, await db.get(NoticeMailProposal, proposal.id)
        )
    card = cards[case_id]
    assert (card.team, card.lane) == ("care", "exit")
    assert card.meta["notice_id"] is None
    assert detail["status"] == "rejected"


@pytest.mark.asyncio
async def test_remember_sender_never_takes_someone_elses_address(consultant) -> None:
    async with AsyncSessionLocal() as db:
        other = Candidate(name="Ewa", lastname=f"Inna{consultant['tag']}")
        db.add(other)
        await db.flush()
        db.add(
            KnownSenderEmail(
                email=f"wspolny-{consultant['tag']}@example.com",
                candidate_id=other.id,
                source="case_link",
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        taken = await notice_mail.remember_sender(
            db,
            email=f"WSPOLNY-{consultant['tag']}@example.com ",
            contract_id=consultant["contract_id"],
            actor_id=None,
        )
        own = await notice_mail.remember_sender(
            db,
            email=consultant["email"],
            contract_id=consultant["contract_id"],
            actor_id=None,
        )
        assert taken is False
        assert own is False  # adres z profilu: NEXUS już go zna


def test_notice_end_date_from_default_template() -> None:
    from app.services.b2b_documents.contract_versions import (
        default_refs,
        notice_end_date,
    )

    assert notice_end_date(date(2026, 10, 31), default_refs()) == date(2026, 11, 30)
    assert notice_end_date(date(2026, 11, 2), default_refs()) == date(2026, 12, 31)


@pytest.mark.asyncio
@pytest.mark.usefixtures("mailbox_on")
async def test_forged_sender_with_someones_contract_number_is_not_remembered(
    consultant,
) -> None:
    """Numer umowy z treści każdy przepisze: potwierdzenie nie uczy adresu obcego."""

    fake = FakeMailbox()
    msg = fake.add(
        subject="Wypowiedzenie umowy",
        hours_ago=2,
        sender=f"obcy-{consultant['tag']}@example.org",
    )
    _body(msg, "Składam wypowiedzenie umowy B2B.")
    await _run(fake)
    case_id = await _case_of(msg["id"])
    [proposal] = await _proposals(case_id)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, consultant["contract_id"])
        contract.status = ContractStatus.ending
        contract.terminated_at = business_today() + timedelta(days=30)
        row = await db.get(NoticeMailProposal, proposal.id)
        row.contract_id = consultant["contract_id"]
        row.match = {**row.match, "reasons": ["contract_number"]}
        await db.commit()
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, consultant["user_id"])
        row = await db.get(NoticeMailProposal, proposal.id)
        assert notice_mail.can_remember_sender(row) is False
        with pytest.raises(notice_view.NoticeError) as other:
            await notice_view.decide(
                db,
                row,
                actor=actor,
                decision="confirmed",
                contract_id=consultant["contract_id"] + 100_000,
                remember_sender=True,
                applied={},
                note=None,
            )
        assert other.value.code == "contract_not_proposed"
        await db.rollback()
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, consultant["user_id"])
        row = await db.get(NoticeMailProposal, proposal.id)
        await notice_view.decide(
            db,
            row,
            actor=actor,
            decision="confirmed",
            contract_id=None,
            remember_sender=True,
            applied={},
            note=None,
        )
        await db.commit()
        assert (
            await db.get(KnownSenderEmail, f"obcy-{consultant['tag']}@example.org")
            is None
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("mailbox_on")
async def test_contract_mails_hide_case_messages_from_people_who_cannot_read_the_case(
    consultant,
) -> None:
    from app.services.admin_cases.notice_mail_history import contract_mail_feed

    fake = FakeMailbox()
    msg = fake.add(subject="Sprawa kadrowa", hours_ago=1, sender=consultant["email"])
    _body(msg, "Poufna treść.")
    await _run(fake)
    case_id = await _case_of(msg["id"])
    async with AsyncSessionLocal() as db:
        case = await db.get(AdminCase, case_id)
        case.contract_id = consultant["contract_id"]
        outsider = User(
            email=f"dl-{consultant['tag']}@example.com",
            name="Delivery Lead",
            role=UserRole.delivery_lead,
            is_active=True,
        )
        db.add(outsider)
        await db.commit()
        admin = await db.get(User, consultant["user_id"])
        seen = await contract_mail_feed(
            db, consultant["contract_id"], user=admin, with_body=True, limit=20
        )
        hidden = await contract_mail_feed(
            db, consultant["contract_id"], user=outsider, with_body=True, limit=20
        )
    assert [m["case_id"] for m in seen] == [case_id]
    assert hidden == []


async def _decide(proposal_id: int, user_id: int, **kwargs: Any) -> None:
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, user_id)
        row = await db.get(NoticeMailProposal, proposal_id)
        await notice_view.decide(
            db,
            row,
            actor=actor,
            decision=kwargs.pop("decision", "confirmed"),
            contract_id=kwargs.pop("contract_id", None),
            remember_sender=kwargs.pop("remember_sender", False),
            applied={},
            note=None,
        )
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.usefixtures("mailbox_on")
async def test_pinned_contract_unlocks_an_unmatched_proposal(consultant) -> None:
    fake = FakeMailbox()
    msg = fake.add(
        subject="Wypowiedzenie umowy", hours_ago=2, sender="nieznany@example.org"
    )
    _body(msg, "Składam wypowiedzenie umowy B2B.")
    await _run(fake)
    case_id = await _case_of(msg["id"])
    [proposal] = await _proposals(case_id)
    assert proposal.contract_id is None
    async with AsyncSessionLocal() as db:
        case = await db.get(AdminCase, case_id)
        case.contract_id = consultant["contract_id"]
        contract = await db.get(Contract, consultant["contract_id"])
        contract.status = ContractStatus.ending
        contract.terminated_at = business_today() + timedelta(days=30)
        await db.commit()
        detail = await notice_view.proposal_detail(
            db, await db.get(NoticeMailProposal, proposal.id)
        )
    assert detail["contract"]["id"] == consultant["contract_id"]
    await _decide(proposal.id, consultant["user_id"])
    [after] = await _proposals(case_id)
    assert after.status == "confirmed"
    assert after.contract_id == consultant["contract_id"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("mailbox_on")
async def test_other_pending_proposal_keeps_the_case_on_the_board(consultant) -> None:
    fake = FakeMailbox()
    first = fake.add(
        subject="Wypowiedzenie",
        hours_ago=3,
        sender=consultant["email"],
        attachments=[
            {"name": "wypowiedzenie.pdf", "contentType": "application/pdf", "size": 9}
        ],
    )
    _body(first, "W załączniku wypowiedzenie.")
    await _run(fake)
    later = fake.add(
        subject="Re: Wypowiedzenie",
        hours_ago=1,
        conversation=first["conversationId"],
        sender=consultant["email"],
    )
    _body(later, "Jest prośba o zmianę daty na 15.01.2027.")
    await _run(fake)
    case_id = await _case_of(first["id"])
    notice, change = await _proposals(case_id)
    assert (notice.kind, change.kind) == ("consultant_notice", "date_change")
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, consultant["contract_id"])
        contract.status = ContractStatus.ending
        contract.terminated_at = notice.proposed_last_day
        await db.commit()
    await _decide(notice.id, consultant["user_id"])
    async with AsyncSessionLocal() as db:
        case = await db.get(AdminCase, case_id)
        assert case.status != "done"
        cards = {c.case_id: c for c in await sources.case_cards(db, business_today())}
    assert cards[case_id].meta["notice_kind"] == "date_change"


@pytest.mark.asyncio
@pytest.mark.usefixtures("mailbox_on")
async def test_rejecting_a_false_notice_restores_the_case_area(consultant) -> None:
    fake = FakeMailbox()
    msg = fake.add(
        subject="Pytanie o polisę",
        hours_ago=1,
        sender=consultant["email"],
        attachments=[
            {
                "name": "wypowiedzenie_wzor.pdf",
                "contentType": "application/pdf",
                "size": 9,
            }
        ],
    )
    _body(msg, "Czy ten wzór jest aktualny?")
    await _run(fake)
    case_id = await _case_of(msg["id"])
    [proposal] = await _proposals(case_id)
    async with AsyncSessionLocal() as db:
        assert (await db.get(AdminCase, case_id)).area == "offboarding"
    await _decide(proposal.id, consultant["user_id"], decision="rejected")
    async with AsyncSessionLocal() as db:
        assert (await db.get(AdminCase, case_id)).area == "administration"


@pytest.mark.asyncio
@pytest.mark.usefixtures("mailbox_on")
async def test_failing_proposal_keeps_the_case_and_message(
    consultant, monkeypatch
) -> None:
    from sqlalchemy.exc import IntegrityError

    from app.services.admin_cases import notice_mail as nm

    async def broken(db, *, case, message, sender_authenticated=False):
        case.area = "offboarding"
        await db.flush()
        raise IntegrityError("x", {}, Exception("boom"))

    monkeypatch.setattr(nm, "propose_for_message", broken)
    fake = FakeMailbox()
    msg = fake.add(
        subject="Wypowiedzenie umowy", hours_ago=1, sender=consultant["email"]
    )
    _body(msg, "Składam wypowiedzenie umowy B2B.")
    result = await _run(fake)
    assert result["status"] == "ok"
    case_id = await _case_of(msg["id"])
    assert case_id is not None
    assert await _proposals(case_id) == []
