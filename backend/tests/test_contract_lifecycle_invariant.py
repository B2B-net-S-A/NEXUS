"""Contract lifecycle invariant — P1-CONTRACT-01.

Locks the single guarded state machine (``app.services.contract_lifecycle``):

* guarded lifecycle routes still require verified completion when a signature
  is required (a completed ``DocumentSignature``);
* the client contract register can write its four operational statuses, while
  ``ready_for_signature``/``void`` stay exclusive to guarded lifecycle routes;
* finalizing an unsigned HTML draft ends at ``ready_for_signature`` (never
  ``active``), and emits no ``contract_signed`` side effect;
* a QES lane with ``DSS_VALIDATION_URL`` unset — or a timed-out / INDETERMINATE
  DSS verdict — does NOT complete the document or advance the pipeline;
* DELETE of an executed contract returns 409 and offers ``/void`` (soft-delete
  preserving documents + signature evidence);
* the legitimate revert flow works via the audited ``/reopen`` transition.

Unit tests exercise the lifecycle service directly; HTTP tests drive the real
endpoints through the in-process ``app_client``.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractType,
    ContractWorkMode,
)
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.services import contract_lifecycle as lifecycle
from app.services.signing import sender as signing_sender
from app.services.signing.provider import ValidationReport
from fastapi import HTTPException
from sqlalchemy import select


# ── Seed helpers ─────────────────────────────────────────────────────────────


async def _seed_user() -> int:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        u = User(
            email=f"lifecycle-{unique}@example.com",
            password_hash=hash_password("x"),
            name="Lifecycle Sender",
            role=UserRole.admin,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _seed_candidate_and_client() -> tuple[int, int]:
    from app.models.candidate import Candidate
    from app.models.client import Client

    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Life",
            lastname=f"Cycle{unique}",
            email=f"life-{unique}@example.com",
        )
        cli = Client(name=f"Klient LC {unique}")
        db.add_all([cand, cli])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(cli)
        return cand.id, cli.id


async def _seed_contract(
    *,
    status: ContractStatus = ContractStatus.draft,
    complete: bool = True,
    draft_html: str | None = None,
) -> int:
    cand_id, cli_id = await _seed_candidate_and_client()
    async with AsyncSessionLocal() as db:
        kwargs: dict = {
            "candidate_id": cand_id,
            "client_id": cli_id,
            "contract_type": ContractType.b2b,
            "status": status,
        }
        if complete:
            kwargs.update(
                start_date=date.today(),
                end_date=date.today() + timedelta(days=90),
                rate_candidate=15000,
                rate_client=20000,
                work_mode=ContractWorkMode.remote,
            )
        if draft_html is not None:
            kwargs["draft_content_html"] = draft_html
        contract = Contract(**kwargs)
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


async def _seed_signature(
    contract_id: int, sender_id: int, status: SignatureStatus
) -> int:
    async with AsyncSessionLocal() as db:
        sig = DocumentSignature(
            contract_id=contract_id,
            provider="upload_validate",
            signature_type="QES",
            status=status,
            sender_user_id=sender_id,
            signer_email="signer@example.com",
            signer_first_name="Jan",
            signer_last_name="Podpisujacy",
        )
        db.add(sig)
        await db.commit()
        await db.refresh(sig)
        return sig.id


# ── State machine ────────────────────────────────────────────────────────────


def test_state_machine_allows_and_forbids() -> None:
    # Legal edges
    lifecycle.assert_transition(ContractStatus.draft, ContractStatus.active)
    lifecycle.assert_transition(
        ContractStatus.draft, ContractStatus.ready_for_signature
    )
    lifecycle.assert_transition(
        ContractStatus.ready_for_signature, ContractStatus.active
    )
    lifecycle.assert_transition(ContractStatus.active, ContractStatus.void)
    lifecycle.assert_transition(ContractStatus.ended, ContractStatus.draft)
    # Illegal: void is terminal
    with pytest.raises(HTTPException) as exc:
        lifecycle.assert_transition(ContractStatus.void, ContractStatus.active)
    assert exc.value.status_code == 409


# ── Activation invariant (service) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_requires_completed_signature_once_started(
    monkeypatch,
) -> None:
    """A contract with an in-flight signature cannot activate until it completes."""
    uid = await _seed_user()
    cid = await _seed_contract(status=ContractStatus.draft, complete=True)
    await _seed_signature(cid, uid, SignatureStatus.sent)

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        with pytest.raises(HTTPException) as exc:
            await lifecycle.activate_contract(db, contract, actor_id=uid)
        assert exc.value.status_code == 409
        assert exc.value.detail["reason"] == "signature_required"
        # State unchanged — no route created `active` without completion.
        assert contract.status == ContractStatus.draft

    # Complete the signature → activation now allowed.
    async with AsyncSessionLocal() as db:
        sig = await db.scalar(
            select(DocumentSignature).where(DocumentSignature.contract_id == cid)
        )
        sig.status = SignatureStatus.completed
        await db.commit()

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        await lifecycle.activate_contract(db, contract, actor_id=uid)
        await db.commit()
        assert contract.status == ContractStatus.active


@pytest.mark.asyncio
async def test_activate_manual_path_when_signing_disabled(monkeypatch) -> None:
    """No signing rail + no signatures → activation proceeds on fields alone."""
    monkeypatch.setattr(settings, "SIGNING_ENABLED", False)
    uid = await _seed_user()
    cid = await _seed_contract(status=ContractStatus.draft, complete=True)

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        await lifecycle.activate_contract(db, contract, actor_id=uid)
        await db.commit()
        assert contract.status == ContractStatus.active


@pytest.mark.asyncio
async def test_activate_incomplete_draft_409() -> None:
    uid = await _seed_user()
    cid = await _seed_contract(status=ContractStatus.draft, complete=False)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        with pytest.raises(HTTPException) as exc:
            await lifecycle.activate_contract(db, contract, actor_id=uid)
        assert exc.value.status_code == 409
        assert "missing" in exc.value.detail


# ── Finalize unsigned HTML → ready_for_signature (HTTP) ───────────────────────


@pytest.mark.asyncio
async def test_finalize_unsigned_html_ends_ready_for_signature(
    app_client, app_auth_headers
) -> None:
    cid = await _seed_contract(
        status=ContractStatus.draft,
        complete=True,
        draft_html="<p>Umowa treść</p>",
    )
    resp = await app_client.post(
        f"/api/contracts/{cid}/draft/finalize", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # At most `ready_for_signature` — never `active` for an unsigned document.
    assert body["status"] == "ready_for_signature"
    assert body["document_id"] is not None

    # No `contract_signed` was emitted: the only activity is the finalize/ready
    # transition, not an activation.
    async with AsyncSessionLocal() as db:
        actions = (
            await db.scalars(
                select(Activity.action).where(
                    Activity.entity_type == "contract", Activity.entity_id == cid
                )
            )
        ).all()
    assert "contract_ready_for_signature" in actions
    assert "contract_activated" not in actions


@pytest.mark.asyncio
async def test_activate_finalized_blocked_without_signature_when_signing_on(
    app_client, app_auth_headers, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SIGNING_ENABLED", True)
    cid = await _seed_contract(status=ContractStatus.ready_for_signature, complete=True)
    resp = await app_client.post(
        f"/api/contracts/{cid}/activate", json={}, headers=app_auth_headers
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["reason"] == "signature_required"


# ── Contract register status writes (HTTP) ───────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("selected_status", ["draft", "active", "ending", "ended"])
async def test_create_contract_honours_register_status_body(
    app_client, app_auth_headers, selected_status
) -> None:
    cand_id, cli_id = await _seed_candidate_and_client()
    resp = await app_client.post(
        "/api/contracts",
        json={
            "candidate_id": cand_id,
            "client_id": cli_id,
            "start_date": date.today().isoformat(),
            "end_date": (date.today() + timedelta(days=90)).isoformat(),
            "rate_candidate": 15000,
            "rate_client": 20000,
            "contract_type": "b2b",
            "work_mode": "remote",
            "status": selected_status,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == selected_status


@pytest.mark.asyncio
async def test_patch_contract_honours_register_status_body(
    app_client, app_auth_headers
) -> None:
    cid = await _seed_contract(status=ContractStatus.draft, complete=True)
    resp = await app_client.patch(
        f"/api/contracts/{cid}",
        json={"status": "active", "team_name": "X"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"
    assert resp.json()["team_name"] == "X"

    for selected_status in ("ending", "ended", "draft"):
        changed = await app_client.patch(
            f"/api/contracts/{cid}",
            json={"status": selected_status},
            headers=app_auth_headers,
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["status"] == selected_status


@pytest.mark.asyncio
async def test_register_rejects_lifecycle_only_statuses(
    app_client, app_auth_headers
) -> None:
    cid = await _seed_contract(status=ContractStatus.draft, complete=True)
    resp = await app_client.patch(
        f"/api/contracts/{cid}",
        json={"status": "void"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text

    null_status = await app_client.patch(
        f"/api/contracts/{cid}",
        json={"status": None},
        headers=app_auth_headers,
    )
    assert null_status.status_code == 422, null_status.text


@pytest.mark.asyncio
async def test_register_status_updates_client_active_consultants(
    app_client, app_auth_headers
) -> None:
    """Active dodaje konsultanta do profilu klienta, inny status go usuwa."""

    cid = await _seed_contract(status=ContractStatus.draft, complete=True)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        assert contract is not None
        client_id = contract.client_id

    activate = await app_client.patch(
        f"/api/contracts/{cid}",
        json={"status": "active"},
        headers=app_auth_headers,
    )
    assert activate.status_code == 200, activate.text
    profile = await app_client.get(
        f"/api/clients/{client_id}/profile", headers=app_auth_headers
    )
    assert profile.status_code == 200, profile.text
    assert cid in {row["contract_id"] for row in profile.json()["active_consultants"]}

    end = await app_client.patch(
        f"/api/contracts/{cid}",
        json={"status": "ended"},
        headers=app_auth_headers,
    )
    assert end.status_code == 200, end.text
    profile = await app_client.get(
        f"/api/clients/{client_id}/profile", headers=app_auth_headers
    )
    assert profile.status_code == 200, profile.text
    assert cid not in {
        row["contract_id"] for row in profile.json()["active_consultants"]
    }


# ── Delete guard + void + reopen (HTTP) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_draft_allowed(app_client, app_auth_headers) -> None:
    cid = await _seed_contract(status=ContractStatus.draft, complete=True)
    resp = await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert resp.status_code == 204, resp.text


@pytest.mark.asyncio
async def test_delete_executed_contract_409_then_void(
    app_client, app_auth_headers
) -> None:
    cid = await _seed_contract(status=ContractStatus.active, complete=True)

    # Hard delete of an executed contract is refused.
    resp = await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert resp.status_code == 409, resp.text
    assert "void_endpoint" in resp.json()["detail"]

    # Void (soft-delete) is the offered alternative and preserves the row.
    void = await app_client.post(
        f"/api/contracts/{cid}/void",
        json={"reason": "pytest"},
        headers=app_auth_headers,
    )
    assert void.status_code == 200, void.text
    assert void.json()["status"] == "void"

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        assert contract is not None  # not hard-deleted
        assert contract.status == ContractStatus.void
        assert contract.voided_at is not None


@pytest.mark.asyncio
async def test_delete_contract_with_completed_signature_409(
    app_client, app_auth_headers
) -> None:
    uid = await _seed_user()
    cid = await _seed_contract(status=ContractStatus.draft, complete=True)
    await _seed_signature(cid, uid, SignatureStatus.completed)
    resp = await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_reopen_reverts_active_to_draft(app_client, app_auth_headers) -> None:
    cid = await _seed_contract(status=ContractStatus.active, complete=True)
    resp = await app_client.post(
        f"/api/contracts/{cid}/reopen",
        json={"reason": "correction"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "draft"


# ── QES fail-closed (service) ─────────────────────────────────────────────────


class _FakeProvider:
    def __init__(self, report: ValidationReport) -> None:
        self._report = report

    async def validate(self, pdf: bytes) -> ValidationReport:
        return self._report


async def _run_finalize(monkeypatch, *, dss_url: str, report: ValidationReport):
    uid = await _seed_user()
    cid = await _seed_contract(status=ContractStatus.ready_for_signature, complete=True)
    sig_id = await _seed_signature(cid, uid, SignatureStatus.sent)
    monkeypatch.setattr(settings, "DSS_VALIDATION_URL", dss_url)
    monkeypatch.setattr(
        signing_sender, "get_provider", lambda name: _FakeProvider(report)
    )
    async with AsyncSessionLocal() as db:
        sig = await db.get(DocumentSignature, sig_id)
        return db, sig


@pytest.mark.asyncio
async def test_qes_failclosed_when_dss_unset(monkeypatch) -> None:
    # DSS unset + non-authoritative fallback report → must NOT complete.
    db, sig = await _run_finalize(
        monkeypatch,
        dss_url="",
        report=ValidationReport(is_qes=False, indication="TOTAL-PASSED"),
    )
    async with db:
        with pytest.raises(HTTPException) as exc:
            await signing_sender.finalize_signed_pdf(
                db, sig, b"%PDF-fake", moved_by=sig.sender_user_id
            )
        assert exc.value.status_code == 422
        assert sig.status == SignatureStatus.sent  # unchanged
        assert sig.signed_document_id is None


@pytest.mark.asyncio
async def test_qes_failclosed_on_indeterminate_dss(monkeypatch) -> None:
    # DSS set but timed-out / INDETERMINATE → must NOT complete.
    db, sig = await _run_finalize(
        monkeypatch,
        dss_url="http://dss.internal/validate",
        report=ValidationReport(
            is_qes=False, indication="INDETERMINATE", sub_indication="DSS_ERROR"
        ),
    )
    async with db:
        with pytest.raises(HTTPException) as exc:
            await signing_sender.finalize_signed_pdf(
                db, sig, b"%PDF-fake", moved_by=sig.sender_user_id
            )
        assert exc.value.status_code == 422
        assert sig.status == SignatureStatus.sent


@pytest.mark.asyncio
async def test_qes_authoritative_pass_completes(monkeypatch) -> None:
    # DSS set + authoritative QES verdict → the document DOES complete.
    monkeypatch.setattr(
        signing_sender.storage_service,
        "save_contract_document",
        lambda *a, **k: ("signed/fake.pdf", 9),
    )
    db, sig = await _run_finalize(
        monkeypatch,
        dss_url="http://dss.internal/validate",
        report=ValidationReport(
            is_qes=True, indication="TOTAL-PASSED", signature_level="QESIG"
        ),
    )
    async with db:
        result = await signing_sender.finalize_signed_pdf(
            db, sig, b"%PDF-fake", moved_by=sig.sender_user_id
        )
        assert result["status"] == "ok"
        assert sig.status == SignatureStatus.completed
