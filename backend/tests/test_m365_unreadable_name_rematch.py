"""Naprawa maili z „cyrylicy w smart_name” (20.10.2026).

Imię i nazwisko cyrylicą składały się w `smart_name` do pustego napisu, więc
jeden kandydat dostawał każdy niedopasowany mail, a `smart_thread` doklejał
odpowiedzi. Skrypt odpina takie maile, dopasowuje je obecnym matcherem,
zwalnia załączniki i zdejmuje z profilu cudze CV. Dane syntetyczne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.cli import m365_unreadable_name_rematch as script
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.m365 import Email, EmailAttachment, EmailDirection, EmailMatchMethod
from app.models.user import User, UserRole


def test_fingerprint_ignores_order() -> None:
    a = script.Plan(
        victims=[1],
        emails=[(2, 1, None, "unmatched"), (1, 1, 5, "strict")],
        removals=[(9, 1)],
        primaries={1: (9, 8)},
    )
    b = script.Plan(
        victims=[1],
        emails=[(1, 1, 5, "strict"), (2, 1, None, "unmatched")],
        removals=[(9, 1)],
        primaries={1: (9, 8)},
    )
    assert a.fingerprint() == b.fingerprint()
    b.primaries = {1: (9, None)}
    assert a.fingerprint() != b.fingerprint()


def test_summary_carries_only_ids_and_counts() -> None:
    plan = script.Plan(
        victims=[7],
        emails=[(1, 7, 5, "strict"), (2, 7, None, "unmatched")],
        attachments=[(3, 7, True)],
        removals=[(4, 7)],
        primaries={7: (4, 6)},
    )
    report = script.summarize(plan)
    assert report["emails_by_victim_and_new_method"] == {
        "7:strict": 1,
        "7:unmatched": 1,
    }
    assert report["relinked_candidates"] == 1
    assert report["attachments_released_incoming"] == 1
    assert report["primaries"] == {"7": [4, 6]}


def _email(user_id: int, candidate_id: int, method, conv: str, sender: str, at):
    tag = uuid.uuid4().hex
    return Email(
        user_id=user_id,
        candidate_id=candidate_id,
        m365_message_id=f"unreadable-{tag}",
        m365_conversation_id=conv,
        subject="Oferta",
        from_address=sender,
        to_addresses=[],
        cc_addresses=[],
        received_at=at,
        direction=EmailDirection.received,
        has_attachments=False,
        is_read=True,
        is_archived=False,
        is_private_filtered=False,
        match_method=method,
        match_confidence=0.5,
    )


@pytest.mark.asyncio
async def test_rematch_releases_foreign_mail_and_cv() -> None:
    tag = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"unreadable-{tag}@example.com",
            name="Synthetic recruiter",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value],
            is_active=True,
        )
        victim = Candidate(
            name="Іван",
            lastname="Петренко",
            email=f"victim-{tag}@example.org",
            cv_filename="own.pdf",
        )
        real = Candidate(
            name="Alex", lastname="Example", email=f"real-{tag}@example.org"
        )
        db.add_all([user, victim, real])
        await db.flush()

        conv_a, conv_b = f"conv-a-{tag}", f"conv-b-{tag}"
        smart_name, smart_thread = (
            EmailMatchMethod.smart_name,
            EmailMatchMethod.smart_thread,
        )
        # Mail prawdziwej osoby i odpowiedź w jej wątku.
        e1 = _email(
            user.id, victim.id, smart_name, conv_a, real.email, now - timedelta(days=5)
        )
        e2 = _email(
            user.id,
            victim.id,
            smart_thread,
            conv_a,
            f"x@{tag}.test",
            now - timedelta(days=4),
        )
        # Mail bez żadnego śladu osoby.
        e3 = _email(
            user.id,
            victim.id,
            smart_name,
            f"conv-c-{tag}",
            f"y@{tag}.test",
            now - timedelta(days=3),
        )
        # Wątek, który naprawdę jest poszkodowanego (mail od niego, strict).
        e5 = _email(
            user.id,
            victim.id,
            EmailMatchMethod.strict,
            conv_b,
            victim.email,
            now - timedelta(days=2),
        )
        e4 = _email(
            user.id,
            victim.id,
            smart_thread,
            conv_b,
            f"z@{tag}.test",
            now - timedelta(days=1),
        )
        db.add_all([e1, e2, e3, e4, e5])
        await db.flush()

        foreign_sha = uuid.uuid4().hex + uuid.uuid4().hex
        attachment = EmailAttachment(
            email_id=e1.id,
            m365_attachment_id=f"att-{tag}",
            filename="foreign.pdf",
            content_type="application/pdf",
            size_bytes=10,
            is_inline=False,
            storage_path="synthetic/foreign.pdf",
            sha256=foreign_sha,
            is_cv_candidate=True,
            cv_parse_attempted_at=now,
            parsed_candidate_id=victim.id,
        )
        own = CandidateDocument(
            candidate_id=victim.id,
            filename="own.pdf",
            file_content=b"own",
            content_type="application/pdf",
            size_bytes=3,
            document_kind=CandidateDocumentKind.cv,
            is_primary=False,
            external_source="traffit",
            uploaded_at=now - timedelta(days=30),
        )
        foreign = CandidateDocument(
            candidate_id=victim.id,
            filename="foreign.pdf",
            file_content=b"foreign",
            content_type="application/pdf",
            size_bytes=7,
            document_kind=CandidateDocumentKind.cv,
            is_primary=True,
            external_source="m365",
            external_id=f"m365:{tag}",
            content_sha256=foreign_sha,
            uploaded_at=now - timedelta(days=5),
        )
        db.add_all([attachment, own, foreign])
        await db.flush()

        plan = await script.plan_and_stage(db, now=now)

        assert victim.id in plan.victims and real.id not in plan.victims
        mine = {e: (new, method) for e, v, new, method in plan.emails if v == victim.id}
        assert mine == {
            e1.id: (real.id, "strict"),
            e2.id: (real.id, "smart_thread"),
            e3.id: (None, "unmatched"),
        }
        assert e4.id in plan.kept_thread_email_ids
        assert (attachment.id, victim.id, True) in plan.attachments
        assert (foreign.id, victim.id) in plan.removals
        assert plan.primaries[victim.id] == (foreign.id, own.id)
        assert plan.stage_copies == 0

        rows = {
            r.id: (r.candidate_id, r.match_method)
            for r in (
                await db.execute(
                    select(Email.id, Email.candidate_id, Email.match_method).where(
                        Email.id.in_([e1.id, e2.id, e3.id, e4.id, e5.id])
                    )
                )
            ).all()
        }
        assert rows[e1.id] == (real.id, EmailMatchMethod.strict)
        assert rows[e2.id] == (real.id, EmailMatchMethod.smart_thread)
        assert rows[e3.id] == (None, EmailMatchMethod.unmatched)
        assert rows[e4.id] == (victim.id, EmailMatchMethod.smart_thread)
        assert rows[e5.id] == (victim.id, EmailMatchMethod.strict)

        await db.refresh(attachment)
        await db.refresh(own)
        await db.refresh(foreign)
        assert attachment.parsed_candidate_id is None
        assert attachment.cv_parse_attempted_at is None
        assert foreign.removed_at is not None and foreign.is_primary is False
        assert own.is_primary is True
        assert victim.cv_filename == "own.pdf"
        # Bez commitu: zamknięcie sesji wycofuje dane syntetyczne.
