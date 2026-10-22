"""Naprawa dokumentów z maila przepiętych przez ucięty klucz (20.10.2026).

Do 20.10.2026 klucz dokumentu m365 to było pierwsze 100 znaków id załącznika,
a id z Graph ma wspólny początek skrzynki — CV z nowego maila przejmowało
cudzy dokument razem z cudzym plikiem. `app.cli.m365_document_repair` oddaje
plik właścicielowi, daje każdej osobie dokument z jej własnego załącznika
i ustawia od nowa główne CV. Dane syntetyczne.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import undefer

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.cli import m365_document_repair as repair_cli
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.m365 import Email, EmailAttachment, EmailDirection
from app.models.user import User, UserRole
from app.services.m365 import attachment_handler
from tests.test_candidate_stage_cv_snapshot import _seed_job, _seed_stage

pytestmark = pytest.mark.asyncio


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def storage(monkeypatch, tmp_path):
    monkeypatch.setattr(attachment_handler, "STORAGE_ROOT", tmp_path)
    return tmp_path


async def _person(label: str) -> int:
    async with AsyncSessionLocal() as db:
        person = Candidate(name="Synth", lastname=f"{label}{uuid.uuid4().hex[:6]}")
        db.add(person)
        await db.commit()
        return person.id


async def _mailbox_user() -> int:
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"repair-mail-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("P@ss"),
            name="Mail",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _mail_cv(
    storage,
    *,
    user_id: int,
    candidate_id: int,
    content: bytes,
    days_ago: int,
    direction: EmailDirection = EmailDirection.received,
) -> tuple[int, str]:
    """Załącznik CV z plikiem na dysku; zwraca (id, ucięty klucz sprzed 20.10)."""
    suffix = uuid.uuid4().hex
    filename = f"cv-{suffix[:8]}.pdf"
    (storage / filename).write_bytes(content)
    # Wspólny początek skrzynki jak w Graph. Ucięty klucz sprzed 20.10 zawiera
    # tu jeszcze kawałek `suffix` — testy na wspólnej bazie nie mogą dzielić
    # klucza (UNIQUE external_source + external_id); przepięcie siejemy wprost.
    graph_id = "AAMkSyntheticMailbox" + "x" * 60 + suffix
    async with AsyncSessionLocal() as db:
        email = Email(
            user_id=user_id,
            candidate_id=candidate_id,
            m365_message_id=f"msg-{suffix}",
            m365_conversation_id="c",
            from_address="synthetic@example.com",
            received_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            direction=direction,
            has_attachments=True,
        )
        db.add(email)
        await db.flush()
        attachment = EmailAttachment(
            email_id=email.id,
            m365_attachment_id=graph_id,
            filename=filename,
            content_type="application/pdf",
            size_bytes=len(content),
            is_cv_candidate=True,
            storage_path=filename,
            sha256=_sha(content),
            parsed_candidate_id=candidate_id,
        )
        db.add(attachment)
        await db.commit()
        return attachment.id, graph_id[:100]


async def _document(
    candidate_id: int,
    *,
    content: bytes,
    claimed_sha: str,
    external_id: str | None,
    primary: bool = False,
    source: str = "m365",
    uploaded_days_ago: int = 1,
    removed: bool = False,
) -> int:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        doc = CandidateDocument(
            candidate_id=candidate_id,
            filename=f"doc-{uuid.uuid4().hex[:8]}.pdf",
            file_content=content,
            content_type="application/pdf",
            size_bytes=len(content),
            document_kind=CandidateDocumentKind.cv,
            is_primary=primary,
            uploaded_at=now - timedelta(days=uploaded_days_ago),
            external_source=source,
            external_id=external_id,
            content_sha256=claimed_sha,
            source_deleted_at=now if removed else None,
            removed_at=now if removed else None,
        )
        db.add(doc)
        await db.commit()
        return doc.id


async def _docs(candidate_id: int) -> list[CandidateDocument]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(CandidateDocument)
            .options(undefer(CandidateDocument.file_content))
            .where(CandidateDocument.candidate_id == candidate_id)
            .order_by(CandidateDocument.id)
        )
        return list(rows)


async def _run(ids: list[int], **kwargs) -> repair_cli.Plan:
    async with AsyncSessionLocal() as db:
        items = await repair_cli.plan(db, candidate_ids=ids, **kwargs)
        await repair_cli.repair(db, items)
        await db.commit()
    return items


async def test_foreign_file_returns_to_its_owner_and_holder_gets_own_cv(storage):
    user_id = await _mailbox_user()
    owner = await _person("Owner")
    holder = await _person("Holder")
    owner_cv, holder_cv = b"%PDF owner synthetic", b"%PDF holder synthetic"
    _, truncated = await _mail_cv(
        storage, user_id=user_id, candidate_id=owner, content=owner_cv, days_ago=5
    )
    await _mail_cv(
        storage, user_id=user_id, candidate_id=holder, content=holder_cv, days_ago=1
    )
    # Stan po błędzie: dokument właściciela u złego posiadacza, skrót jego CV.
    poisoned = await _document(
        holder,
        content=owner_cv,
        claimed_sha=_sha(holder_cv),
        external_id=truncated,
        primary=True,
    )
    job_id = await _seed_job()
    stage_id = await _seed_stage(holder, job_id)
    async with AsyncSessionLocal() as db:
        copy = CandidateStageCV(
            candidate_stage_id=stage_id,
            candidate_id=holder,
            job_id=job_id,
            original_cv_filename="cudze.pdf",
            original_cv_content=owner_cv,
            original_cv_sha256=_sha(owner_cv),
        )
        db.add(copy)
        await db.commit()
        copy_id = copy.id

    async with AsyncSessionLocal() as db:
        dry = await repair_cli.plan(db, candidate_ids=[owner, holder])
        exposure = await repair_cli.client_exposure(db, dry)
    assert [(d, h, o) for d, h, o, _ in dry.returns] == [(poisoned, holder, owner)]
    assert exposure[0]["candidate_id"] == holder
    assert exposure[0]["stage"] == "new"

    items = await _run([owner, holder])
    assert items.fingerprint() == dry.fingerprint()

    owner_docs = await _docs(owner)
    assert [d.id for d in owner_docs] == [poisoned]
    returned = owner_docs[0]
    assert returned.content_sha256 == _sha(returned.file_content) == _sha(owner_cv)
    assert returned.external_id.startswith("m365:")
    assert returned.is_primary is True

    holder_docs = await _docs(holder)
    assert len(holder_docs) == 1
    own = holder_docs[0]
    assert own.file_content == holder_cv
    assert own.content_sha256 == _sha(holder_cv)
    assert own.is_primary is True
    assert own.external_source == "m365"

    async with AsyncSessionLocal() as db:
        copy = await db.get(CandidateStageCV, copy_id)
        assert copy.original_cv_sha256 == _sha(holder_cv)
        assert copy.original_snapshot_source == "m365_document_repair"
        holder_row = await db.get(Candidate, holder)
        assert holder_row.cv_filename == own.filename
        trail = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == holder,
                Activity.action == "m365_documents_repaired",
            )
        )
        assert trail.details["removed_doc_ids"] == [poisoned]
        assert trail.details["primary_after"] == own.id

    # Drugi bieg nie ma już nic do zrobienia.
    async with AsyncSessionLocal() as db:
        again = await repair_cli.plan(db, candidate_ids=[owner, holder])
    assert not (again.returns or again.removals or again.creates or again.primaries)


async def test_file_only_from_outgoing_mail_is_soft_removed_at_wrong_holder(storage):
    user_id = await _mailbox_user()
    sender_side = await _person("Sent")
    holder = await _person("Holder")
    sent_cv, holder_cv = b"%PDF sent synthetic", b"%PDF holder own synthetic"
    _, truncated = await _mail_cv(
        storage,
        user_id=user_id,
        candidate_id=sender_side,
        content=sent_cv,
        days_ago=9,
        direction=EmailDirection.sent,
    )
    await _mail_cv(
        storage, user_id=user_id, candidate_id=holder, content=holder_cv, days_ago=2
    )
    poisoned = await _document(
        holder, content=sent_cv, claimed_sha=_sha(holder_cv), external_id=truncated
    )

    items = await _run([sender_side, holder])

    assert items.removals == [(poisoned, holder)]
    assert await _docs(sender_side) == []
    holder_docs = {d.id: d for d in await _docs(holder)}
    removed = holder_docs.pop(poisoned)
    assert removed.source_deleted_at is not None and removed.removed_at is not None
    assert removed.content_sha256 == _sha(sent_cv)
    [own] = holder_docs.values()
    assert own.file_content == holder_cv and own.is_primary is True


async def test_missing_mail_document_keeps_a_chosen_primary_and_a_removal(storage):
    user_id = await _mailbox_user()
    person = await _person("Kept")
    removed_person = await _person("Removed")
    mail_cv, manual_cv = b"%PDF mail synthetic", b"%PDF manual synthetic"
    await _mail_cv(
        storage, user_id=user_id, candidate_id=person, content=mail_cv, days_ago=1
    )
    manual = await _document(
        person,
        content=manual_cv,
        claimed_sha=_sha(manual_cv),
        external_id=None,
        source="manual",
        primary=True,
        uploaded_days_ago=30,
    )
    gone_cv = b"%PDF removed synthetic"
    await _mail_cv(
        storage,
        user_id=user_id,
        candidate_id=removed_person,
        content=gone_cv,
        days_ago=3,
    )
    await _document(
        removed_person,
        content=gone_cv,
        claimed_sha=_sha(gone_cv),
        external_id=None,
        removed=True,
    )

    items = await _run([person, removed_person])

    docs = {d.id: d for d in await _docs(person)}
    assert docs[manual].is_primary is True
    [added] = [d for d in docs.values() if d.id != manual]
    assert added.file_content == mail_cv and added.is_primary is False
    assert [r for _, _, r in items.skipped] == ["removed"]
    assert len(await _docs(removed_person)) == 1


async def test_excluded_and_mismatching_files_are_left_alone(storage):
    user_id = await _mailbox_user()
    excluded = await _person("Excluded")
    broken = await _person("Broken")
    await _mail_cv(
        storage,
        user_id=user_id,
        candidate_id=excluded,
        content=b"%PDF excluded synthetic",
        days_ago=1,
    )
    attachment_id, _ = await _mail_cv(
        storage,
        user_id=user_id,
        candidate_id=broken,
        content=b"%PDF original synthetic",
        days_ago=1,
    )
    async with AsyncSessionLocal() as db:
        attachment = await db.get(EmailAttachment, attachment_id)
        (storage / attachment.storage_path).write_bytes(b"%PDF changed on disk")

    items = await _run([excluded, broken], exclude={excluded})

    assert items.creates == []
    assert items.skipped == [(broken, attachment_id, "file_mismatch")]
    assert await _docs(excluded) == []
    assert await _docs(broken) == []


async def test_apply_refuses_a_plan_that_differs_from_the_dry_run(storage, capsys):
    user_id = await _mailbox_user()
    person = await _person("Guard")
    await _mail_cv(
        storage,
        user_id=user_id,
        candidate_id=person,
        content=b"%PDF guard synthetic",
        days_ago=1,
    )

    assert await repair_cli.main([], candidate_ids=[person]) == 0
    assert "--expected" in capsys.readouterr().out
    assert await _docs(person) == []

    code = await repair_cli.main(
        ["--apply", "--expected", "000000000000"], candidate_ids=[person]
    )
    assert code == 2
    assert "Plan różni się od próby" in capsys.readouterr().err
    assert await _docs(person) == []


async def test_owner_keeps_the_primary_cv_someone_chose(storage):
    """Pomiar 20.10: „najnowsze” u właściciela zdjęłoby główne CV z Traffita."""
    user_id = await _mailbox_user()
    owner = await _person("Owner")
    holder = await _person("Holder")
    owner_cv, holder_cv = b"%PDF owner mail synthetic", b"%PDF holder mail synthetic"
    _, truncated = await _mail_cv(
        storage, user_id=user_id, candidate_id=owner, content=owner_cv, days_ago=4
    )
    await _mail_cv(
        storage, user_id=user_id, candidate_id=holder, content=holder_cv, days_ago=1
    )
    chosen_cv = b"%PDF traffit synthetic"
    async with AsyncSessionLocal() as db:
        chosen = CandidateDocument(
            candidate_id=owner,
            # Plik do klienta jako główne CV: ktoś go wskazał, zostaje.
            filename="Synth_B2B.docx",
            file_content=chosen_cv,
            document_kind=CandidateDocumentKind.cv,
            is_primary=True,
            external_source="traffit",
            content_sha256=_sha(chosen_cv),
        )
        db.add(chosen)
        await db.commit()
        chosen_id = chosen.id
    poisoned = await _document(
        holder, content=owner_cv, claimed_sha=_sha(holder_cv), external_id=truncated
    )

    items = await _run([owner, holder])

    assert owner not in items.primaries
    docs = {d.id: d for d in await _docs(owner)}
    assert docs[chosen_id].is_primary is True
    assert docs[poisoned].is_primary is False
    assert docs[poisoned].content_sha256 == _sha(owner_cv)


async def test_apply_writes_receipt_and_rereads_only_the_listed_profile(
    storage, monkeypatch, capsys
):
    from sqlalchemy import text

    user_id = await _mailbox_user()
    person = await _person("Reread")
    other = await _person("Quiet")
    for candidate_id in (person, other):
        await _mail_cv(
            storage,
            user_id=user_id,
            candidate_id=candidate_id,
            content=f"%PDF reread {candidate_id}".encode(),
            days_ago=1,
        )
    calls: list[tuple[int, int, str]] = []

    async def _fake_enrich(candidate_id, document_id, trigger="cv_upload", **_):
        calls.append((candidate_id, document_id, trigger))

    monkeypatch.setattr(
        "app.api.candidates._enrich_candidate_from_document_task", _fake_enrich
    )
    async with AsyncSessionLocal() as db:
        fingerprint = (
            await repair_cli.plan(db, candidate_ids=[person, other])
        ).fingerprint()
    try:
        code = await repair_cli.main(
            ["--apply", "--expected", fingerprint, "--reread", str(person)],
            candidate_ids=[person, other],
        )
        assert code == 0
        [created] = await _docs(person)
        assert created.is_primary is True
        assert calls == [(person, created.id, "cv_repair")]
        async with AsyncSessionLocal() as db:
            receipt = await db.scalar(
                text("SELECT value FROM app_settings WHERE key = :k"),
                {"k": repair_cli.RECEIPT_KEY},
            )
        if isinstance(receipt, str):
            receipt = json.loads(receipt)
        assert receipt["created"] == 2 and receipt["fingerprint"] == fingerprint
        # Drugi zapis przy istniejącym paragonie jest odrzucany.
        assert (
            await repair_cli.main(
                ["--apply", "--expected", fingerprint], candidate_ids=[person, other]
            )
            == 2
        )
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("DELETE FROM app_settings WHERE key = :k"),
                {"k": repair_cli.RECEIPT_KEY},
            )
            await db.commit()


async def test_plan_returns_a_hidden_foreign_file_visible_and_lists_its_projection(
    storage, monkeypatch
):
    """Audyt 22.10.2026 (F113, F114), bez bazy: plik, który zły posiadacz
    usunął z profilu, wraca do właściciela widoczny (do 22.10 zostawał ukryty,
    a nową kopię blokował powód „removed”); próba wypisuje osobę, której
    profil czytano z cudzego dokumentu."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    now = datetime.now(timezone.utc)
    owner_cv, holder_cv = b"%PDF owner hidden synthetic", b"%PDF holder synthetic"
    (storage / "owner.pdf").write_bytes(owner_cv)
    (storage / "holder.pdf").write_bytes(holder_cv)

    def mail(candidate_id: int, attachment_id: int, content: bytes, name: str, days):
        return repair_cli.MailCv(
            candidate_id=candidate_id,
            sha256=_sha(content),
            attachment_id=attachment_id,
            m365_attachment_id=f"AAMkSynthetic-{attachment_id}",
            storage_path=name,
            filename=name,
            content_type="application/pdf",
            received_at=now - timedelta(days=days),
        )

    hidden = repair_cli.Doc(
        id=100,
        candidate_id=2,
        content_sha256=_sha(holder_cv),
        file_sha256=_sha(owner_cv),
        file_size=len(owner_cv),
        external_id="AAMkSynthetic-truncated",
        external_source="m365",
        document_kind="cv",
        is_primary=False,
        deleted=True,
        removed=True,
        outdated=False,
        uploaded_at=now - timedelta(days=1),
        filename="holder.pdf",
    )
    monkeypatch.setattr(
        repair_cli,
        "_mail_cvs",
        AsyncMock(
            return_value={
                (1, _sha(owner_cv)): mail(1, 11, owner_cv, "owner.pdf", 5),
                (2, _sha(holder_cv)): mail(2, 12, holder_cv, "holder.pdf", 1),
            }
        ),
    )
    monkeypatch.setattr(repair_cli, "_documents", AsyncMock(return_value=[hidden]))
    monkeypatch.setattr(repair_cli, "_quarantined_pairs", AsyncMock(return_value=set()))
    monkeypatch.setattr(
        repair_cli,
        "_projection_sources",
        AsyncMock(return_value={2: (100, "holder.pdf")}),
        raising=False,
    )

    items = await repair_cli.plan(SimpleNamespace(), candidate_ids=[1, 2])

    assert [(d, h, o) for d, h, o, _ in items.returns] == [(100, 2, 1)]
    # Do 22.10: właścicielowi nowa kopia „removed”, a zwrócony plik ukryty.
    assert [s for s in items.skipped if s[0] == 1] == []
    assert items.primaries[1] == (None, 100)
    assert items.restores == [100]
    assert items.creates == [(2, 12)]
    assert items.projections == [(2, 100, _sha(owner_cv))]
    report = repair_cli.summarize(items, [])
    assert report["returned"][0]["restored"] is True
    assert report["projection_from_foreign"] == [{"candidate": 2, "doc": 100}]


async def test_hidden_foreign_file_returns_visible_and_holder_loses_its_facts(
    storage, monkeypatch
):
    """Audyt 22.10.2026 (F113, F114): zapis zdejmuje ukrycie ze zwracanego
    dokumentu i czyści u złego posiadacza fakty odczytane z cudzego pliku."""
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.services.embedding_service.delete_candidate_embedding",
        AsyncMock(return_value=True),
    )
    user_id = await _mailbox_user()
    owner = await _person("Owner")
    holder = await _person("Holder")
    owner_cv, holder_cv = b"%PDF owner hidden db", b"%PDF holder own db"
    _, truncated = await _mail_cv(
        storage, user_id=user_id, candidate_id=owner, content=owner_cv, days_ago=5
    )
    await _mail_cv(
        storage, user_id=user_id, candidate_id=holder, content=holder_cv, days_ago=1
    )
    poisoned = await _document(
        holder,
        content=owner_cv,
        claimed_sha=_sha(holder_cv),
        external_id=truncated,
        removed=True,
    )
    async with AsyncSessionLocal() as db:
        row = await db.get(Candidate, holder)
        row.raw_cv_text = "Synthetic foreign CV text"
        row.ai_summary = "Synthetic foreign summary"
        row.skills = [{"name": "Foreign Skill"}]
        row.cv_extracted_data = {
            "skills": [{"name": "Foreign Skill"}],
            "cv_highlights": {"source_document_id": poisoned},
        }
        await db.commit()

    items = await _run([owner, holder])

    assert items.restores == [poisoned]
    assert items.projections == [(holder, poisoned, _sha(owner_cv))]
    [returned] = await _docs(owner)
    assert returned.id == poisoned
    assert returned.removed_at is None and returned.source_deleted_at is None
    assert returned.removed_by is None
    assert returned.is_primary is True
    async with AsyncSessionLocal() as db:
        row = await db.get(Candidate, holder)
        assert row.raw_cv_text is None
        assert row.ai_summary is None
        assert row.skills == []
        trail = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == holder,
                Activity.action == "m365_documents_repaired",
            )
        )
        assert trail.details["projection_cleared"] is True


async def test_hidden_foreign_file_stays_hidden_when_the_owner_removed_that_file(
    storage, monkeypatch
):
    """Przegląd audytu 22.10.2026 (F113 a 0435), bez bazy: plik, który
    właściciel sam usunął ze swojego profilu, wraca do niego, ale ukryty —
    zdjęcie ukrycia złego posiadacza nie cofa decyzji właściciela."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    now = datetime.now(timezone.utc)
    owner_cv, holder_cv = b"%PDF owner removed synthetic", b"%PDF holder synthetic"
    (storage / "owner.pdf").write_bytes(owner_cv)
    (storage / "holder.pdf").write_bytes(holder_cv)

    def doc(doc_id: int, candidate_id: int, claimed: bytes, **kwargs):
        return repair_cli.Doc(
            id=doc_id,
            candidate_id=candidate_id,
            content_sha256=_sha(claimed),
            file_sha256=_sha(owner_cv),
            file_size=len(owner_cv),
            document_kind="cv",
            is_primary=False,
            deleted=True,
            removed=True,
            outdated=False,
            uploaded_at=now - timedelta(days=1),
            filename="x.pdf",
            **kwargs,
        )

    hidden = doc(
        100,
        2,
        holder_cv,
        external_id="AAMkSynthetic-truncated",
        external_source="m365",
    )
    owner_removed = doc(101, 1, owner_cv, external_id=None, external_source="manual")
    monkeypatch.setattr(
        repair_cli,
        "_mail_cvs",
        AsyncMock(
            return_value={
                (1, _sha(owner_cv)): repair_cli.MailCv(
                    candidate_id=1,
                    sha256=_sha(owner_cv),
                    attachment_id=11,
                    m365_attachment_id="AAMkSynthetic-11",
                    storage_path="owner.pdf",
                    filename="owner.pdf",
                    content_type="application/pdf",
                    received_at=now - timedelta(days=5),
                ),
            }
        ),
    )
    monkeypatch.setattr(
        repair_cli, "_documents", AsyncMock(return_value=[hidden, owner_removed])
    )
    monkeypatch.setattr(repair_cli, "_quarantined_pairs", AsyncMock(return_value=set()))
    monkeypatch.setattr(
        repair_cli, "_projection_sources", AsyncMock(return_value={2: (None, None)})
    )

    items = await repair_cli.plan(SimpleNamespace(), candidate_ids=[1, 2])

    assert [(d, h, o) for d, h, o, _ in items.returns] == [(100, 2, 1)]
    assert items.restores == []
    assert (1, 11, "removed") in items.skipped
    assert repair_cli.summarize(items, [])["returned"][0]["restored"] is False
