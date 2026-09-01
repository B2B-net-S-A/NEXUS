"""M5-P0.8 — a settled Autenti signature never regresses on a late event.

``handle_event`` applied any mapped status whenever it differed from the current
one, guarded only by a ``!=`` no-op check. Autenti webhooks are unordered, so a
delayed intermediate event (HANDED_OVER → in_progress) arriving after a terminal
COMPLETED would downgrade a finished signature back to in_progress.

Fix: a monotonic guard refuses any transition once ``sig.status`` is terminal
(completed / rejected / withdrawn / expired / failed). The event is still
recorded (audit) and side effects still run; only the status is frozen.

Behavioural against a real Postgres. A minimal signature (no contract) is enough
— HANDED_OVER triggers no side effects, and contract_id is nullable.
"""

from __future__ import annotations

import uuid

from datetime import date

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.user import User, UserRole
from app.services.autenti.webhook_handler import handle_event


async def _seed_signature(db, *, status: SignatureStatus) -> tuple[int, str]:
    u = uuid.uuid4().hex[:12]
    user = User(
        email=f"autenti-{u}@example.com",
        password_hash=hash_password("x"),
        name="Sender",
        role=UserRole.admin,
        is_active=True,
    )
    client = Client(name=f"Autenti {u}")
    cand = Candidate(name="Jan", lastname=f"Kowalski-{u}")
    db.add_all([user, client, cand])
    await db.flush()
    # A signature needs exactly one target (chk_signature_target_xor).
    contract = Contract(
        candidate_id=cand.id,
        client_id=client.id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        contract_type=ContractType.b2b,
        status=ContractStatus.active,
    )
    db.add(contract)
    await db.flush()
    ref = f"proc-{u}"
    sig = DocumentSignature(
        contract_id=contract.id,
        provider="autenti",
        provider_ref=ref,
        signature_type="SES",
        status=status,
        sender_user_id=user.id,
        signer_email=f"signer-{u}@example.com",
        signer_first_name="Jan",
        signer_last_name="Kowalski",
    )
    db.add(sig)
    await db.commit()
    return sig.id, ref


def _late_handed_over(ref: str) -> dict:
    return {"jti": uuid.uuid4().hex, "processId": ref, "eventType": "HANDED_OVER"}


async def test_late_event_does_not_regress_completed() -> None:
    async with AsyncSessionLocal() as db:
        sid, ref = await _seed_signature(db, status=SignatureStatus.completed)
        outcome = await handle_event(db, _late_handed_over(ref))
        assert outcome == "ok"
    async with AsyncSessionLocal() as db:
        sig = await db.get(DocumentSignature, sid)
        assert sig.status == SignatureStatus.completed, (
            "late HANDED_OVER downgraded a completed signature (M5-P0.8 regressed)"
        )


async def test_late_event_does_not_regress_rejected() -> None:
    async with AsyncSessionLocal() as db:
        sid, ref = await _seed_signature(db, status=SignatureStatus.rejected)
        await handle_event(db, _late_handed_over(ref))
    async with AsyncSessionLocal() as db:
        sig = await db.get(DocumentSignature, sid)
        assert sig.status == SignatureStatus.rejected


async def test_intermediate_event_still_advances_a_live_signature() -> None:
    """Positive control: the guard must NOT freeze a non-terminal signature."""
    async with AsyncSessionLocal() as db:
        sid, ref = await _seed_signature(db, status=SignatureStatus.sent)
        await handle_event(db, _late_handed_over(ref))
    async with AsyncSessionLocal() as db:
        sig = await db.get(DocumentSignature, sid)
        assert sig.status == SignatureStatus.in_progress, (
            "HANDED_OVER should advance a `sent` signature to in_progress"
        )
