"""Crash windows: a side effect must never be recorded before it happened.

Three background paths committed (or emitted) their bookkeeping out of order
with the effect it describes. One replica is enough to hit all three — prod
restarts on every deploy, and Coolify's rolling overlap runs the old and new
container together for a moment.

1. ``tasks/chat_email_fallback`` stamped ``email_sent_at`` and committed BEFORE
   handing anything to SMTP. A crash in that window left the row permanently
   marked as sent with no email ever delivered — silent, unrecoverable loss.
2. ``tasks/autenti_expiry_sweeper`` wrote the signed PDF to storage under a
   random key and only committed the referencing row at the END of the batch.
   A crash left orphaned files, and every retry wrote another copy.
3. ``services/marketplace_service`` created match notifications BEFORE the
   alert-log claim and used the claim result only for a counter — so a pair
   another pass had already logged got notified a second time.

Each test drives the failure, not just the happy path: the send raises, the DB
write is rejected, the claim is lost to a competitor. Real Postgres.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pytest
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.tasks import chat_email_fallback as fallback_mod


class _SimulatedCrash(BaseException):
    """Stands in for the process dying mid-send.

    Deliberately a ``BaseException``: the loop catches ``Exception`` and runs
    its own cleanup, which is exactly the path we must NOT take here. A hard
    crash gets no cleanup — that is what makes the window dangerous.
    """


# ───────────────────────────────────────────────────────────────────────────
# 1. chat email fallback — the mail must not be marked sent before it is sent
# ───────────────────────────────────────────────────────────────────────────


async def _seed_offline_chat_notification() -> tuple[int, int]:
    """Offline user + an old, unread, unsent chat notification. Returns ids."""
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    async with AsyncSessionLocal() as db:
        u = User(
            email=f"crashwin-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("T3st_pass_xxxxxxx!"),
            name="Crash Window",
            role=UserRole.user,
            is_active=True,
            last_seen_at=None,  # never online → qualifies
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)

        n = Notification(
            user_id=u.id,
            title="Nowa wiadomość",
            message="Ktoś napisał na czacie rekrutacji",
            notification_type=NotificationType.job_chat_message,
            is_read=False,
            created_at=old,
        )
        db.add(n)
        await db.commit()
        await db.refresh(n)
        return u.id, n.id


async def _cleanup_notification(user_id: int, notif_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.id == notif_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()


async def _age_the_claim(notif_id: int, minutes: int) -> None:
    """Backdate the reservation so it reads as abandoned by a dead process."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Notification)
            .where(Notification.id == notif_id)
            .values(
                email_send_started_at=datetime.now(timezone.utc)
                - timedelta(minutes=minutes)
            )
        )
        await db.commit()


async def _crash_one_pass(monkeypatch, notif_id: int) -> None:
    """Run a pass whose SMTP send dies without unwinding."""

    def dying_send(**_kwargs):
        raise _SimulatedCrash("process died mid-send")

    monkeypatch.setattr(fallback_mod, "send_chat_fallback_email", dying_send)
    with pytest.raises(_SimulatedCrash):
        async with AsyncSessionLocal() as db:
            await fallback_mod._process_one_pass(db)


async def test_crash_mid_send_does_not_mark_the_mail_as_sent(monkeypatch) -> None:
    """The regression itself: a crash between claim and send must not lie.

    Under the old code ``email_sent_at`` was already committed at this point and
    the mail was gone for good.
    """
    user_id, notif_id = await _seed_offline_chat_notification()
    try:
        await _crash_one_pass(monkeypatch, notif_id)

        async with AsyncSessionLocal() as db:
            row = await db.get(Notification, notif_id)
            assert row is not None
            assert row.email_sent_at is None, (
                "row claims the email was sent, but SMTP never confirmed it"
            )
            assert row.email_send_started_at is not None, (
                "the reservation should survive the crash so it can go stale"
            )
    finally:
        await _cleanup_notification(user_id, notif_id)


async def test_mail_is_still_delivered_after_the_stale_claim_expires(
    monkeypatch,
) -> None:
    """Work is not lost: once the abandoned claim ages out, the mail goes out."""
    user_id, notif_id = await _seed_offline_chat_notification()
    try:
        await _crash_one_pass(monkeypatch, notif_id)
        await _age_the_claim(notif_id, fallback_mod.CLAIM_STALE_MIN + 5)

        calls: list[dict] = []

        def working_send(**kwargs):
            calls.append(kwargs)
            return True

        monkeypatch.setattr(fallback_mod, "send_chat_fallback_email", working_send)
        async with AsyncSessionLocal() as db:
            fired = await fallback_mod._process_one_pass(db)

        assert fired == 1, "the recovery pass should pick the abandoned row back up"
        assert len(calls) == 1

        async with AsyncSessionLocal() as db:
            row = await db.get(Notification, notif_id)
            assert row is not None
            assert row.email_sent_at is not None  # stamped only now, after SMTP
    finally:
        await _cleanup_notification(user_id, notif_id)


async def test_a_live_claim_still_blocks_a_second_pass(monkeypatch) -> None:
    """Recovery must not become a double send while the first pass may be alive."""
    user_id, notif_id = await _seed_offline_chat_notification()
    try:
        await _crash_one_pass(monkeypatch, notif_id)  # claim taken, still fresh

        calls: list[dict] = []

        def working_send(**kwargs):
            calls.append(kwargs)
            return True

        monkeypatch.setattr(fallback_mod, "send_chat_fallback_email", working_send)
        async with AsyncSessionLocal() as db:
            fired = await fallback_mod._process_one_pass(db)

        assert fired == 0
        assert calls == [], "fresh reservation must not be stolen — that is a re-send"
    finally:
        await _cleanup_notification(user_id, notif_id)


# ───────────────────────────────────────────────────────────────────────────
# 2. autenti sweeper — no orphaned PDFs, no duplicate copies
# ───────────────────────────────────────────────────────────────────────────


def _isolate_storage(monkeypatch, tmp_path) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "CONTRACTS_DIR", tmp_path / "contracts")


def test_stable_key_overwrites_instead_of_leaving_an_orphan(
    monkeypatch, tmp_path
) -> None:
    """A retry of a machine-generated document reuses the same object."""
    from io import BytesIO

    from app.services import storage_service

    _isolate_storage(monkeypatch, tmp_path)

    first, _ = storage_service.save_contract_document(
        contract_id=7,
        upload_filename="umowa_7_signed_42.pdf",
        source=BytesIO(b"%PDF-crashed-halfway"),
        stored_name="autenti-signed-42.pdf",
    )
    second, size = storage_service.save_contract_document(
        contract_id=7,
        upload_filename="umowa_7_signed_42.pdf",
        source=BytesIO(b"%PDF-full-retry"),
        stored_name="autenti-signed-42.pdf",
    )

    assert first == second
    files = list((tmp_path / "contracts" / "7").iterdir())
    assert len(files) == 1, f"retry left a duplicate behind: {files}"
    assert files[0].read_bytes() == b"%PDF-full-retry"
    assert size == len(b"%PDF-full-retry")


def test_human_uploads_keep_their_random_key(monkeypatch, tmp_path) -> None:
    """Two uploads of the same filename are two documents — unchanged behaviour."""
    from io import BytesIO

    from app.services import storage_service

    _isolate_storage(monkeypatch, tmp_path)

    a, _ = storage_service.save_contract_document(
        contract_id=9, upload_filename="umowa.pdf", source=BytesIO(b"one")
    )
    b, _ = storage_service.save_contract_document(
        contract_id=9, upload_filename="umowa.pdf", source=BytesIO(b"two")
    )

    assert a != b
    assert len(list((tmp_path / "contracts" / "9").iterdir())) == 2


async def _seed_contract_and_signature(
    *, status_completed: bool = True
) -> tuple[int, int, int]:
    """Sender + candidate + client + contract + signature. Returns ids."""
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract
    from app.models.document_signature import DocumentSignature, SignatureStatus

    async with AsyncSessionLocal() as db:
        u = User(
            email=f"sweep-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("x"),
            name="Sweeper Sender",
            role=UserRole.admin,
            is_active=True,
        )
        cand = Candidate(
            name="Sweep",
            lastname=f"Cand-{uuid.uuid4().hex[:6]}",
            email=f"sweep-cand-{uuid.uuid4().hex[:8]}@example.com",
        )
        cli = Client(name=f"SweepClient-{uuid.uuid4().hex[:6]}")
        db.add_all([u, cand, cli])
        await db.commit()
        await db.refresh(u)
        await db.refresh(cand)
        await db.refresh(cli)

        contract = Contract(
            candidate_id=cand.id, client_id=cli.id, start_date=date(2026, 1, 1)
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)

        sig = DocumentSignature(
            contract_id=contract.id,
            provider="autenti",
            signature_type="QES",
            status=(
                SignatureStatus.completed
                if status_completed
                else SignatureStatus.in_progress
            ),
            sender_user_id=u.id,
            signer_email="signer@example.com",
            signer_first_name="Jan",
            signer_last_name="Podpisujący",
            provider_ref=f"ref-{uuid.uuid4().hex[:8]}",
            autenti_process_id=f"proc-{uuid.uuid4().hex[:8]}",
            retry_count=0,
        )
        db.add(sig)
        await db.commit()
        await db.refresh(sig)
        return u.id, contract.id, sig.id


async def _cleanup_contract(user_id: int, contract_id: int) -> None:
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract
    from app.models.contract_document import ContractDocument
    from app.models.document_signature import DocumentSignature

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        cand_id = contract.candidate_id if contract else None
        cli_id = contract.client_id if contract else None
        await db.execute(
            delete(DocumentSignature).where(
                DocumentSignature.contract_id == contract_id
            )
        )
        await db.execute(
            delete(ContractDocument).where(ContractDocument.contract_id == contract_id)
        )
        await db.execute(delete(Contract).where(Contract.id == contract_id))
        if cand_id:
            await db.execute(delete(Candidate).where(Candidate.id == cand_id))
        if cli_id:
            await db.execute(delete(Client).where(Client.id == cli_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()


async def _process_ids(*sig_ids: int) -> list[str]:
    """Autenti process ids for the given signatures, in the order asked for."""
    from app.models.document_signature import DocumentSignature

    async with AsyncSessionLocal() as db:
        out = []
        for sid in sig_ids:
            sig = await db.get(DocumentSignature, sid)
            assert sig is not None
            out.append(sig.autenti_process_id)
        return out


def _install_autenti_stub(monkeypatch, download) -> None:
    """Point the sweeper at an offline client driven by ``download``."""
    from app.tasks import autenti_expiry_sweeper as sweeper_mod

    class _Config:
        @staticmethod
        def from_settings():
            return object()

    class _Client:
        def __init__(self, _config):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def download_signed_file(self, process_id):
            return download(process_id)

    monkeypatch.setattr(sweeper_mod, "AutentiConfig", _Config)
    monkeypatch.setattr(sweeper_mod, "AutentiClient", _Client)


async def test_rejected_db_write_leaves_no_orphaned_pdf(monkeypatch, tmp_path) -> None:
    """If the row cannot be stored, the file written for it is removed."""
    from app.models.contract_document import ContractDocument
    from app.models.document_signature import DocumentSignature
    from app.tasks import autenti_expiry_sweeper as sweeper_mod

    from app.services.autenti.client import AutentiError

    _isolate_storage(monkeypatch, tmp_path)

    user_id, contract_id, sig_id = await _seed_contract_and_signature()
    try:
        (mine,) = await _process_ids(sig_id)

        def download(process_id):
            # The sweeper scans the whole table and CI shares one database, so
            # anything that is not our own row is waved off down the handled
            # error path instead of being dragged into this scenario.
            if process_id != mine:
                raise AutentiError(503, "not part of this test")
            return b"%PDF-signed"

        _install_autenti_stub(monkeypatch, download)

        def rejected_doc(**kwargs):
            # Dangling FK → the flush is refused by Postgres.
            kwargs["contract_id"] = 2_000_000_000
            return ContractDocument(**kwargs)

        monkeypatch.setattr(sweeper_mod, "ContractDocument", rejected_doc)
        touched = await sweeper_mod._retry_signed_downloads()

        assert touched == 0
        contract_dir = tmp_path / "contracts" / str(contract_id)
        leftovers = list(contract_dir.iterdir()) if contract_dir.exists() else []
        assert leftovers == [], f"orphaned file left in storage: {leftovers}"

        async with AsyncSessionLocal() as db:
            sig = await db.get(DocumentSignature, sig_id)
            assert sig is not None
            assert sig.signed_document_id is None  # unchanged, retried next pass
    finally:
        await _cleanup_contract(user_id, contract_id)


async def test_crash_mid_batch_keeps_the_signature_already_attached(
    monkeypatch, tmp_path
) -> None:
    """Per-signature commit: a later crash cannot undo earlier finished work.

    The old code committed once at the very end, so dying on the second
    signature threw away the first one's attachment even though its PDF was
    already sitting in storage.
    """
    from app.models.contract_document import ContractDocument
    from app.models.document_signature import DocumentSignature
    from app.services.autenti.client import AutentiError
    from app.tasks import autenti_expiry_sweeper as sweeper_mod

    _isolate_storage(monkeypatch, tmp_path)

    user_a, contract_a, sig_a = await _seed_contract_and_signature()
    user_b, contract_b, sig_b = await _seed_contract_and_signature()
    try:
        ours = set(await _process_ids(sig_a, sig_b))
        served: set[str] = set()

        def download(process_id):
            # Row order is not guaranteed and CI shares one database with every
            # other test file, so key the behaviour off *our* two rows: the
            # first of ours to arrive succeeds, the second kills the process.
            # Anything else is waved off down the handled error path.
            if process_id not in ours:
                raise AutentiError(503, "not part of this test")
            if not served:
                served.add(process_id)
                return b"%PDF-first"
            raise _SimulatedCrash("container killed mid-batch")

        _install_autenti_stub(monkeypatch, download)

        with pytest.raises(_SimulatedCrash):
            await sweeper_mod._retry_signed_downloads()

        # Exactly one of ours got served; whichever it was must be durable.
        async with AsyncSessionLocal() as db:
            rows = (
                (
                    await db.execute(
                        select(DocumentSignature).where(
                            DocumentSignature.id.in_([sig_a, sig_b])
                        )
                    )
                )
                .scalars()
                .all()
            )
            attached = [r for r in rows if r.signed_document_id is not None]
            assert len(attached) == 1, (
                "the signature finished before the crash must stay attached"
            )
            doc = await db.get(ContractDocument, attached[0].signed_document_id)
            assert doc is not None
            assert doc.file_path  # the row survived the crash, committed on its own
    finally:
        await _cleanup_contract(user_a, contract_a)
        await _cleanup_contract(user_b, contract_b)


# ───────────────────────────────────────────────────────────────────────────
# 3. marketplace — notify only what we actually claimed
# ───────────────────────────────────────────────────────────────────────────


class _Breakdown:
    """Minimal stand-in for a scoring breakdown."""

    def __init__(self, total: float) -> None:
        self.total = total


async def _seed_marketplace_pair() -> tuple[int, int, int]:
    """Owner user + pooled candidate + scannable job. Returns ids."""
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.talent_pool import TalentPoolMembership
    from app.services.marketplace_service import ensure_marketplace_pool

    async with AsyncSessionLocal() as db:
        owner = User(
            email=f"mkt-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("x"),
            name="Marketplace Owner",
            role=UserRole.admin,
            is_active=True,
        )
        cli = Client(name=f"MktClient-{uuid.uuid4().hex[:6]}")
        db.add_all([owner, cli])
        await db.commit()
        await db.refresh(owner)
        await db.refresh(cli)

        cand = Candidate(
            name="Marketplace",
            lastname=f"Cand-{uuid.uuid4().hex[:6]}",
            email=f"mkt-cand-{uuid.uuid4().hex[:8]}@example.com",
            created_by=owner.id,
        )
        job = Job(
            title=f"Backend Engineer {uuid.uuid4().hex[:6]}",
            client_id=cli.id,
            status=JobStatus.published,
            must_skills=["python"],
            embedding_id=uuid.uuid4().hex,
            recruiter_id=owner.id,
        )
        db.add_all([cand, job])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(job)

        pool = await ensure_marketplace_pool(db)
        db.add(TalentPoolMembership(talent_pool_id=pool.id, candidate_id=cand.id))
        await db.commit()
        return owner.id, cand.id, job.id


async def _cleanup_marketplace(owner_id: int, cand_id: int, job_id: int) -> None:
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.models.marketplace_alert_log import MarketplaceAlertLog
    from app.models.talent_pool import TalentPoolMembership

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        cli_id = job.client_id if job else None
        await db.execute(
            delete(MarketplaceAlertLog).where(MarketplaceAlertLog.job_id == job_id)
        )
        await db.execute(
            delete(TalentPoolMembership).where(
                TalentPoolMembership.candidate_id == cand_id
            )
        )
        await db.execute(delete(Notification).where(Notification.user_id == owner_id))
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.execute(delete(Candidate).where(Candidate.id == cand_id))
        await db.execute(delete(User).where(User.id == owner_id))
        if cli_id:
            from app.models.client import Client

            await db.execute(delete(Client).where(Client.id == cli_id))
        await db.commit()


def _stub_scan_dependencies(monkeypatch, *, pre_check_says_new: bool) -> None:
    """Force a high-scoring match without Qdrant or the real scorer.

    ``pre_check_says_new`` False-positives the cheap ``_was_already_alerted``
    guard, which is precisely the race: the pre-check ran before a competing
    pass inserted the log row, so the claim is the only thing left to catch it.
    """
    from app.services import embedding_service, marketplace_service, scoring_service

    async def fake_semantic(**_kwargs):
        return []

    async def fake_score(*_args, **_kwargs):
        return _Breakdown(95.0)

    async def fake_pre_check(*_args, **_kwargs):
        return not pre_check_says_new

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", fake_semantic)
    monkeypatch.setattr(scoring_service, "score_candidate_job", fake_score)
    monkeypatch.setattr(marketplace_service, "_was_already_alerted", fake_pre_check)


async def _marketplace_notifications(owner_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Notification).where(
                Notification.user_id == owner_id,
                Notification.notification_type == NotificationType.marketplace_match,
            )
        )
        return list(rows.scalars().all())


async def test_no_notification_when_another_pass_already_claimed_the_pair(
    monkeypatch,
) -> None:
    """Lost the claim → send nothing. Previously it notified anyway."""
    from app.models.marketplace_alert_log import MarketplaceAlertLog
    from app.services.marketplace_service import scan_job_for_marketplace_matches

    owner_id, cand_id, job_id = await _seed_marketplace_pair()
    try:
        # A competing pass logged this pair between the pre-check and our insert.
        async with AsyncSessionLocal() as db:
            db.add(MarketplaceAlertLog(candidate_id=cand_id, job_id=job_id, score=91.0))
            await db.commit()

        _stub_scan_dependencies(monkeypatch, pre_check_says_new=True)

        async with AsyncSessionLocal() as db:
            result = await scan_job_for_marketplace_matches(job_id, db)
            await db.commit()

        assert result.new_alerts == 0
        assert await _marketplace_notifications(owner_id) == [], (
            "notified a human about a pair that was already alerted"
        )
    finally:
        await _cleanup_marketplace(owner_id, cand_id, job_id)


async def test_winning_the_claim_still_notifies(monkeypatch) -> None:
    """Positive control — the fix must not simply mute notifications."""
    from app.services.marketplace_service import scan_job_for_marketplace_matches

    owner_id, cand_id, job_id = await _seed_marketplace_pair()
    try:
        _stub_scan_dependencies(monkeypatch, pre_check_says_new=True)

        async with AsyncSessionLocal() as db:
            result = await scan_job_for_marketplace_matches(job_id, db)
            await db.commit()

        assert result.new_alerts == 1
        notifs = await _marketplace_notifications(owner_id)
        assert len(notifs) == 1
    finally:
        await _cleanup_marketplace(owner_id, cand_id, job_id)


async def test_alert_log_records_who_was_notified(monkeypatch) -> None:
    """Claiming before emitting must not lose the recipient bookkeeping."""
    from app.models.marketplace_alert_log import MarketplaceAlertLog
    from app.services.marketplace_service import scan_job_for_marketplace_matches

    owner_id, cand_id, job_id = await _seed_marketplace_pair()
    try:
        _stub_scan_dependencies(monkeypatch, pre_check_says_new=True)

        async with AsyncSessionLocal() as db:
            await scan_job_for_marketplace_matches(job_id, db)
            await db.commit()

        async with AsyncSessionLocal() as db:
            row: Optional[MarketplaceAlertLog] = (
                await db.execute(
                    select(MarketplaceAlertLog).where(
                        MarketplaceAlertLog.job_id == job_id
                    )
                )
            ).scalar_one_or_none()
            assert row is not None
            assert row.notified_candidate_owner_id == owner_id
            assert row.notified_job_owner_id == owner_id
    finally:
        await _cleanup_marketplace(owner_id, cand_id, job_id)
