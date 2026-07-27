"""M5-P0.9 — restart-safe reconciliation of stuck signature dispatch.

Every signature sender persists a ``document_signatures`` row in
``status=draft`` and hands the actual send to a background task. A container
restart between the HTTP 202 and completion orphans the row at ``draft``/
``sending`` forever — the expiry sweepers only touch ``sent``/``in_progress``.
``app.tasks.signature_reconciler`` closes that hole: rows stuck past the grace
window are marked ``failed`` + the sender notified to resend.

DB-backed (real postgres in CI via the same session the app uses). We drive
``_reconcile_stuck`` directly so no wall-clock sleeps are needed — ``updated_at``
is stamped into the past on insert.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.notification import Notification
from app.tasks.signature_reconciler import (
    _reconcile_stuck,
    signature_reconciler_loop,
)

pytestmark = pytest.mark.asyncio

_OLD = datetime(2020, 1, 1, tzinfo=timezone.utc)


async def _seed_sender_and_contract() -> tuple[int, int]:
    """Create a sender user + a candidate/client/contract target. Returns ids."""
    from app.core.security import hash_password
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        u = User(
            email=f"recon-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("x"),
            name="Recon Sender",
            role=UserRole.admin,
            is_active=True,
        )
        cand = Candidate(
            name="Recon",
            lastname=f"Cand-{uuid.uuid4().hex[:6]}",
            email=f"recon-cand-{uuid.uuid4().hex[:8]}@example.com",
        )
        cli = Client(name=f"ReconClient-{uuid.uuid4().hex[:6]}")
        db.add_all([u, cand, cli])
        await db.commit()
        await db.refresh(u)
        await db.refresh(cand)
        await db.refresh(cli)

        contract = Contract(
            candidate_id=cand.id,
            client_id=cli.id,
            start_date=date(2026, 1, 1),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return u.id, contract.id


async def _seed_signature(
    *,
    sender_id: int,
    contract_id: int,
    status: SignatureStatus,
    provider: str,
    updated_at: datetime,
) -> int:
    """Insert a DocumentSignature with an explicit ``updated_at`` (bypass onupdate)."""
    async with AsyncSessionLocal() as db:
        sig = DocumentSignature(
            contract_id=contract_id,
            provider=provider,
            signature_type="QES",
            status=status,
            sender_user_id=sender_id,
            signer_email="signer@example.com",
            signer_first_name="Jan",
            signer_last_name="Podpisujący",
            created_at=updated_at,
            updated_at=updated_at,
        )
        db.add(sig)
        await db.commit()
        await db.refresh(sig)
        return sig.id


async def _status_of(sig_id: int) -> SignatureStatus:
    async with AsyncSessionLocal() as db:
        sig = await db.get(DocumentSignature, sig_id)
        assert sig is not None
        return sig.status


async def test_reconcile_marks_stuck_draft_failed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SIGNING_ENABLED", True)
    monkeypatch.setattr(settings, "AUTENTI_ENABLED", False)
    monkeypatch.setattr(settings, "SIGNATURE_RECONCILE_GRACE_SECONDS", 600)

    sender_id, contract_id = await _seed_sender_and_contract()
    sig_id = await _seed_signature(
        sender_id=sender_id,
        contract_id=contract_id,
        status=SignatureStatus.draft,
        provider="upload_validate",
        updated_at=_OLD,
    )

    touched = await _reconcile_stuck()
    assert touched >= 1

    async with AsyncSessionLocal() as db:
        sig = await db.get(DocumentSignature, sig_id)
        assert sig.status == SignatureStatus.failed
        assert sig.last_error and "restart" in sig.last_error.lower()
        assert sig.retry_count == 1

        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "document_signature",
                Activity.entity_id == sig_id,
                Activity.action == "signature_send_failed",
            )
        )
        assert activity is not None

        notif = await db.scalar(
            select(Notification).where(
                Notification.related_entity_type == "document_signature",
                Notification.related_entity_id == sig_id,
            )
        )
        assert notif is not None


async def test_reconcile_marks_stuck_sending_failed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTENTI_ENABLED", True)
    monkeypatch.setattr(settings, "SIGNING_ENABLED", False)
    monkeypatch.setattr(settings, "SIGNATURE_RECONCILE_GRACE_SECONDS", 600)

    sender_id, contract_id = await _seed_sender_and_contract()
    sig_id = await _seed_signature(
        sender_id=sender_id,
        contract_id=contract_id,
        status=SignatureStatus.sending,
        provider="autenti",
        updated_at=_OLD,
    )

    await _reconcile_stuck()
    assert await _status_of(sig_id) == SignatureStatus.failed


async def test_reconcile_skips_fresh_rows(monkeypatch) -> None:
    """A row inside the grace window is left alone (dispatch may still finish)."""
    monkeypatch.setattr(settings, "SIGNING_ENABLED", True)
    monkeypatch.setattr(settings, "AUTENTI_ENABLED", True)
    monkeypatch.setattr(settings, "SIGNATURE_RECONCILE_GRACE_SECONDS", 600)

    sender_id, contract_id = await _seed_sender_and_contract()
    fresh_id = await _seed_signature(
        sender_id=sender_id,
        contract_id=contract_id,
        status=SignatureStatus.draft,
        provider="upload_validate",
        updated_at=datetime.now(timezone.utc),
    )

    await _reconcile_stuck()
    assert await _status_of(fresh_id) == SignatureStatus.draft


async def test_reconcile_ignores_sent_and_in_progress(monkeypatch) -> None:
    """sent / in_progress are legitimate waiting states — never swept here."""
    monkeypatch.setattr(settings, "SIGNING_ENABLED", True)
    monkeypatch.setattr(settings, "AUTENTI_ENABLED", True)
    monkeypatch.setattr(settings, "SIGNATURE_RECONCILE_GRACE_SECONDS", 600)

    sender_id, contract_id = await _seed_sender_and_contract()
    sent_id = await _seed_signature(
        sender_id=sender_id,
        contract_id=contract_id,
        status=SignatureStatus.sent,
        provider="autenti",
        updated_at=_OLD,
    )
    inprog_id = await _seed_signature(
        sender_id=sender_id,
        contract_id=contract_id,
        status=SignatureStatus.in_progress,
        provider="upload_validate",
        updated_at=_OLD,
    )

    await _reconcile_stuck()
    assert await _status_of(sent_id) == SignatureStatus.sent
    assert await _status_of(inprog_id) == SignatureStatus.in_progress


async def test_reconcile_respects_provider_kill_switch(monkeypatch) -> None:
    """With only SIGNING on, an autenti row is untouched; in-house is healed."""
    monkeypatch.setattr(settings, "SIGNING_ENABLED", True)
    monkeypatch.setattr(settings, "AUTENTI_ENABLED", False)
    monkeypatch.setattr(settings, "SIGNATURE_RECONCILE_GRACE_SECONDS", 600)

    sender_id, contract_id = await _seed_sender_and_contract()
    autenti_id = await _seed_signature(
        sender_id=sender_id,
        contract_id=contract_id,
        status=SignatureStatus.sending,
        provider="autenti",
        updated_at=_OLD,
    )
    inhouse_id = await _seed_signature(
        sender_id=sender_id,
        contract_id=contract_id,
        status=SignatureStatus.draft,
        provider="upload_validate",
        updated_at=_OLD,
    )

    await _reconcile_stuck()
    assert await _status_of(autenti_id) == SignatureStatus.sending  # gated off
    assert await _status_of(inhouse_id) == SignatureStatus.failed


async def test_loop_noops_when_both_rails_disabled(monkeypatch) -> None:
    """The loop must return immediately (not spin) when both kill-switches off."""
    monkeypatch.setattr(settings, "AUTENTI_ENABLED", False)
    monkeypatch.setattr(settings, "SIGNING_ENABLED", False)

    # Returns without entering the while-loop; no timeout guard needed because a
    # regression (entering the loop) would hang the test, surfacing the bug.
    await signature_reconciler_loop()
