"""INT-09/10 (audyt 22.09.2026): klucz aktywności per zdarzenie, sweeper per podpis."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_framework_contract import ClientFrameworkContract
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.document_signature_event import DocumentSignatureEvent
from app.models.user import User
from app.services.autenti import webhook_handler
from app.services.autenti.activity_log import (
    add_autenti_activity,
    autenti_event_key,
    autenti_remind_key,
)
from app.tasks import autenti_expiry_sweeper as sweeper


async def _user_id(db) -> int:
    uid = await db.scalar(select(User.id).order_by(User.id).limit(1))
    if uid is None:
        u = User(
            email=f"autenti-int+{time.time_ns()}@example.com",
            name="Autenti Test",
            is_active=True,
        )
        db.add(u)
        await db.flush()
        uid = u.id
    return uid


async def _contract_signature(**sig_kw) -> tuple[int, int, str]:
    async with AsyncSessionLocal() as db:
        uid = await _user_id(db)
        client = Client(name=f"Autenti INT {time.time_ns()}")
        cand = Candidate(name="Ala", lastname=f"Int-{time.time_ns()}")
        db.add_all([client, cand])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            start_date=date(2026, 1, 1),
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
        )
        db.add(contract)
        await db.flush()
        pid = f"proc-int-{time.time_ns()}"
        sig = DocumentSignature(
            contract_id=contract.id,
            autenti_process_id=pid,
            autenti_signature_type="SES",
            status=SignatureStatus.sent,
            sender_user_id=uid,
            signer_email="ala@example.com",
            signer_first_name="Ala",
            signer_last_name="Int",
            **sig_kw,
        )
        db.add(sig)
        await db.commit()
        return sig.id, contract.id, pid


def test_event_key_shape():
    assert autenti_event_key("p1", "signature_sent") == "p1:signature_sent"
    assert autenti_event_key(None, "x") is None
    assert autenti_remind_key(
        "p1", datetime(2026, 9, 22, 10, 0, 1, tzinfo=timezone.utc)
    ) == ("p1:signature_remind_sent:20260922T100001")


async def test_sent_remind_completed_sequence_and_idempotent_replay(monkeypatch):
    sig_id, contract_id, pid = await _contract_signature()

    async def _no_download(db, sig):
        return None

    monkeypatch.setattr(
        webhook_handler, "_download_and_attach_signed_file", _no_download
    )
    try:
        async with AsyncSessionLocal() as db:
            uid = await _user_id(db)
            for _ in range(2):  # replay of "sent" stays idempotent
                await add_autenti_activity(
                    db,
                    process_id=pid,
                    action="signature_sent",
                    entity_type="contract",
                    entity_id=contract_id,
                    user_id=uid,
                )
                await db.flush()
            for minutes in (0, 90):  # two reminders, one hour apart
                await add_autenti_activity(
                    db,
                    process_id=pid,
                    action="signature_remind_sent",
                    entity_type="contract",
                    entity_id=contract_id,
                    user_id=uid,
                    external_id=autenti_remind_key(
                        pid, datetime.now(timezone.utc) + timedelta(minutes=minutes)
                    ),
                )
            await db.commit()

        claims = {
            "jti": f"ev-{time.time_ns()}",
            "processId": pid,
            "eventType": "SIGNING_PROCESS_COMPLETED",
        }
        async with AsyncSessionLocal() as db:
            assert await webhook_handler.handle_event(db, claims) == "ok"
            await db.commit()
        # A redelivery with a NEW event id of the same completion.
        async with AsyncSessionLocal() as db:
            again = {**claims, "jti": f"ev-{time.time_ns()}-2"}
            await webhook_handler.handle_event(db, again)
            await db.commit()

        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(Activity.action, Activity.external_id).where(
                        Activity.external_source == "autenti",
                        Activity.external_id.like(f"{pid}:%"),
                    )
                )
            ).all()
            sig = await db.get(DocumentSignature, sig_id)
        actions = sorted(a for a, _ in rows)
        assert actions == [
            "signature_completed",
            "signature_remind_sent",
            "signature_remind_sent",
            "signature_sent",
        ]
        assert len({e for _, e in rows}) == len(rows)
        assert sig.status == SignatureStatus.completed
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Activity).where(Activity.external_id.like(f"{pid}:%"))
            )
            await db.execute(
                delete(DocumentSignatureEvent).where(
                    DocumentSignatureEvent.signature_id == sig_id
                )
            )
            await db.commit()


class _ExpiredClient:
    def __init__(self, _cfg):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_process(self, _pid):
        return {"status": "DOCUMENT_PROCESS_EXPIRED"}


async def test_sweeper_expires_contract_and_framework_signatures_independently(
    monkeypatch,
):
    past = datetime.now(timezone.utc) - timedelta(days=1)
    sig_id, contract_id, pid = await _contract_signature(expires_at=past)
    async with AsyncSessionLocal() as db:
        uid = await _user_id(db)
        client = Client(name=f"Autenti FC {time.time_ns()}")
        db.add(client)
        await db.flush()
        fc = ClientFrameworkContract(client_id=client.id, name="Umowa ramowa INT")
        db.add(fc)
        await db.flush()
        fc_pid = f"proc-fc-{time.time_ns()}"
        fc_sig = DocumentSignature(
            client_framework_contract_id=fc.id,
            autenti_process_id=fc_pid,
            autenti_signature_type="SES",
            status=SignatureStatus.sent,
            sender_user_id=uid,
            signer_email="fc@example.com",
            signer_first_name="F",
            signer_last_name="C",
            expires_at=past,
        )
        db.add(fc_sig)
        await db.commit()
        fc_sig_id = fc_sig.id

    monkeypatch.setattr(
        sweeper.AutentiConfig, "from_settings", staticmethod(lambda: object())
    )
    monkeypatch.setattr(sweeper, "AutentiClient", _ExpiredClient)

    touched = await sweeper._sweep_expired()
    assert touched >= 2
    async with AsyncSessionLocal() as db:
        a = await db.get(DocumentSignature, sig_id)
        b = await db.get(DocumentSignature, fc_sig_id)
        acts = (
            await db.scalars(
                select(Activity.external_id).where(
                    Activity.external_source == "autenti",
                    Activity.action == "signature_expired",
                    Activity.external_id.in_(
                        [f"{pid}:signature_expired", f"{fc_pid}:signature_expired"]
                    ),
                )
            )
        ).all()
    assert a.status == SignatureStatus.expired
    assert b.status == SignatureStatus.expired
    assert acts == [f"{pid}:signature_expired"], "no contract → no contract activity"


@pytest.mark.parametrize("pid", [None, ""])
def test_no_process_no_key(pid):
    assert autenti_event_key(pid, "x") is None
