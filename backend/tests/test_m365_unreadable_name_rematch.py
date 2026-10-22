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


@pytest.mark.asyncio
async def test_rematch_skips_private_mail_and_ineligible_mailbox() -> None:
    """Odpięty mail prywatny albo ze skrzynki bez dostępu zostaje niedopasowany.

    Ta sama reguła co zwykły rematch (`microsoft365_sync._rematch_pass`):
    `is_private_filtered` i `eligible_m365_owner`. Bez niej skrypt przypinał
    taki mail prawdziwej osobie z adresu nadawcy.
    """
    tag = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        recruiter = User(
            email=f"unreadable-r-{tag}@example.com",
            name="Synthetic recruiter",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value],
            is_active=True,
        )
        viewer = User(
            email=f"unreadable-v-{tag}@example.com",
            name="Synthetic viewer",
            role=UserRole.user,
            roles=[UserRole.user.value],
            is_active=True,
        )
        victim = Candidate(
            name="Іван", lastname="Петренко", email=f"victim-{tag}@example.org"
        )
        real = Candidate(
            name="Alex", lastname="Example", email=f"real-{tag}@example.org"
        )
        db.add_all([recruiter, viewer, victim, real])
        await db.flush()

        private = _email(
            recruiter.id,
            victim.id,
            EmailMatchMethod.smart_name,
            f"conv-p-{tag}",
            real.email,
            now - timedelta(days=3),
        )
        private.is_private_filtered = True
        foreign_box = _email(
            viewer.id,
            victim.id,
            EmailMatchMethod.smart_name,
            f"conv-v-{tag}",
            real.email,
            now - timedelta(days=2),
        )
        regular = _email(
            recruiter.id,
            victim.id,
            EmailMatchMethod.smart_name,
            f"conv-r-{tag}",
            real.email,
            now - timedelta(days=1),
        )
        db.add_all([private, foreign_box, regular])
        await db.flush()

        plan = await script.plan_and_stage(db, now=now)

        mine = {e: (new, method) for e, v, new, method in plan.emails if v == victim.id}
        assert mine == {
            private.id: (None, "unmatched"),
            foreign_box.id: (None, "unmatched"),
            regular.id: (real.id, "strict"),
        }
        rows = {
            r.id: (r.candidate_id, r.match_method)
            for r in (
                await db.execute(
                    select(Email.id, Email.candidate_id, Email.match_method).where(
                        Email.id.in_([private.id, foreign_box.id, regular.id])
                    )
                )
            ).all()
        }
        assert rows[private.id] == (None, EmailMatchMethod.unmatched)
        assert rows[foreign_box.id] == (None, EmailMatchMethod.unmatched)
        assert rows[regular.id] == (real.id, EmailMatchMethod.strict)
        # Bez commitu: zamknięcie sesji wycofuje dane syntetyczne.


def test_summary_lists_profiles_read_from_the_foreign_cv() -> None:
    """Audyt 22.10.2026 (F114): próba wypisuje, czyj profil czytano z cudzego
    CV — same id, a zmiana tej listy zmienia odcisk planu."""
    plan = script.Plan(victims=[7], removals=[(4, 7)], primaries={7: (4, None)})
    before = plan.fingerprint()
    plan.projections = [(7, 4, "a" * 64)]
    assert script.summarize(plan)["projection_from_foreign"] == [
        {"candidate": 7, "doc": 4}
    ]
    assert plan.fingerprint() != before


def test_profile_source_is_the_traced_document_or_the_primary_pointer() -> None:
    from types import SimpleNamespace

    foreign = SimpleNamespace(id=4, is_primary=True, filename="Foreign.pdf")
    other = SimpleNamespace(id=5, is_primary=False, filename="other.pdf")
    traced = SimpleNamespace(
        cv_extracted_data={"cv_highlights": {"source_document_id": 4}},
        cv_filename="own.pdf",
    )
    untraced = SimpleNamespace(cv_extracted_data={}, cv_filename="foreign.pdf")
    elsewhere = SimpleNamespace(
        cv_extracted_data={"cv_highlights": {"source_document_id": 99}},
        cv_filename="foreign.pdf",
    )
    assert script.projected_document(traced, [foreign, other]) is foreign
    assert script.projected_document(untraced, [foreign, other]) is foreign
    assert script.projected_document(elsewhere, [foreign, other]) is None


@pytest.mark.asyncio
async def test_apply_clears_facts_read_from_the_foreign_cv(monkeypatch) -> None:
    """Audyt 22.10.2026 (F114, decyzja Artura): po odpięciu cudzego CV profil
    poszkodowanego nie zostaje z tekstem, umiejętnościami i podsumowaniem
    z tego CV."""
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.services.embedding_service.delete_candidate_embedding",
        AsyncMock(return_value=True),
    )
    tag = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"unreadable-proj-{tag}@example.com",
            name="Synthetic recruiter",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value],
            is_active=True,
        )
        victim = Candidate(
            name="Олена",
            lastname="Петренко",
            raw_cv_text="Synthetic foreign CV text",
            ai_summary="Synthetic foreign summary",
            skills=[{"name": "Foreign Skill"}],
        )
        db.add_all([user, victim])
        await db.flush()
        mail = _email(
            user.id,
            victim.id,
            EmailMatchMethod.smart_name,
            f"conv-proj-{tag}",
            f"nobody@{tag}.test",
            now - timedelta(days=2),
        )
        db.add(mail)
        await db.flush()
        foreign_sha = uuid.uuid4().hex + uuid.uuid4().hex
        db.add(
            EmailAttachment(
                email_id=mail.id,
                m365_attachment_id=f"att-proj-{tag}",
                filename="foreign.pdf",
                content_type="application/pdf",
                size_bytes=7,
                is_inline=False,
                storage_path="synthetic/foreign.pdf",
                sha256=foreign_sha,
                is_cv_candidate=True,
                cv_parse_attempted_at=now,
                parsed_candidate_id=victim.id,
            )
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
            external_id=f"m365:proj-{tag}",
            content_sha256=foreign_sha,
            uploaded_at=now - timedelta(days=2),
        )
        db.add(foreign)
        await db.flush()
        victim.cv_extracted_data = {
            "skills": [{"name": "Foreign Skill"}],
            "cv_highlights": {"source_document_id": foreign.id},
        }
        await db.flush()

        plan = await script.plan_and_stage(db, now=now)
        assert (victim.id, foreign.id, foreign_sha) in plan.projections
        # Próba na sucho niczego nie czyści — to robi dopiero zapis.
        assert victim.raw_cv_text == "Synthetic foreign CV text"

        assert await script.clear_projections(db, plan) == len(plan.projections)
        await db.refresh(victim)
        assert victim.raw_cv_text is None
        assert victim.ai_summary is None
        assert victim.skills == []
        # Bez commitu: zamknięcie sesji wycofuje dane syntetyczne.
