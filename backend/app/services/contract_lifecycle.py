"""Contract lifecycle — one guarded state machine, one activation invariant.

The finding (P1-CONTRACT-01): the contract lifecycle had no single hard
invariant. ``status`` was writable from the create/update schemas, ``/activate``
and ``/draft/finalize`` reached ``active`` (and emitted ``contract_signed``) with
no signed evidence, and a hard DELETE could cascade signature evidence away.

This module is the single source of truth for status transitions. Every
side-effectful status change goes through one of the guarded operations below;
no route sets ``status = active`` directly. The rules:

* :data:`ALLOWED_TRANSITIONS` — the only legal (from → to) edges.
* :func:`activate_contract` — the ONLY path to ``active``. It requires the draft
  to be complete AND, when a signature is required, a *completed* qualified
  ``DocumentSignature`` to exist. No signed evidence ⇒ HTTP 409.
* :func:`move_to_ready_for_signature` — a finalized (but unsigned) draft lands
  here, never at ``active``.
* :func:`revert_contract` — the audited replacement for the old free
  ``PATCH {status: draft}`` revert.
* :func:`void_contract` — soft-delete preserving documents + signature hashes.

Isolated from the route handlers so the invariant can be unit-tested without a
FastAPI rig, and reused by the signing pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.services.contract_service import validate_ready_for_activation

# ── State machine ────────────────────────────────────────────────────────────
#
# The only legal transitions. Keyed by the CURRENT status; the value is the set
# of statuses it may move to. ``void`` is terminal. Reactivation edges
# (ended/ending → active, * → draft) exist for the audited heal/revert paths.
ALLOWED_TRANSITIONS: dict[ContractStatus, frozenset[ContractStatus]] = {
    ContractStatus.draft: frozenset(
        {
            ContractStatus.ready_for_signature,
            ContractStatus.active,
            ContractStatus.ended,
            ContractStatus.void,
        }
    ),
    ContractStatus.ready_for_signature: frozenset(
        {
            ContractStatus.active,
            ContractStatus.draft,
            ContractStatus.ended,
            ContractStatus.void,
        }
    ),
    ContractStatus.active: frozenset(
        {
            ContractStatus.ending,
            ContractStatus.ended,
            ContractStatus.draft,
            ContractStatus.void,
        }
    ),
    ContractStatus.ending: frozenset(
        {
            ContractStatus.active,
            ContractStatus.ended,
            ContractStatus.draft,
            ContractStatus.void,
        }
    ),
    ContractStatus.ended: frozenset(
        {
            ContractStatus.active,
            ContractStatus.draft,
            ContractStatus.void,
        }
    ),
    ContractStatus.void: frozenset(),
}


class ContractTransitionError(HTTPException):
    """A status change the state machine forbids → surfaced to the API as 409."""

    def __init__(self, detail: object) -> None:
        super().__init__(status_code=http_status.HTTP_409_CONFLICT, detail=detail)


def assert_transition(current: ContractStatus, target: ContractStatus) -> None:
    """Raise 409 unless ``current → target`` is a declared legal edge."""
    if target == current:
        return
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise ContractTransitionError(
            {
                "message": "Illegal contract status transition",
                "from": current.value,
                "to": target.value,
            }
        )


# ── Signature evidence ───────────────────────────────────────────────────────


async def _has_any_signature(db: AsyncSession, contract_id: int) -> bool:
    """True when any ``DocumentSignature`` row exists for the contract.

    Once a signing process is initiated, activation must wait for a *completed*
    signature — you cannot start signing and then bypass it via ``/activate``.
    """
    found = await db.scalar(
        select(DocumentSignature.id)
        .where(DocumentSignature.contract_id == contract_id)
        .limit(1)
    )
    return found is not None


async def _has_completed_signature(db: AsyncSession, contract_id: int) -> bool:
    """True when at least one ``completed`` signature exists for the contract."""
    found = await db.scalar(
        select(DocumentSignature.id)
        .where(
            DocumentSignature.contract_id == contract_id,
            DocumentSignature.status == SignatureStatus.completed,
        )
        .limit(1)
    )
    return found is not None


def signature_required(contract: Contract, *, has_signatures: bool) -> bool:
    """Whether a completed qualified signature is required to activate.

    Required when:
      * a signing process was ever initiated for the contract (``has_signatures``)
        — you must finish what you started, or
      * the draft was finalized for signing (``ready_for_signature``) AND the
        in-house rail is enabled, or
      * the in-house signing rail is enabled for this signature-requiring type
        (B2B).

    When signing is disabled (``SIGNING_ENABLED=false``, the prod default) and no
    signature was ever started, activation proceeds on field validation alone —
    the legacy manual/offline flow is preserved, no regression.
    """
    if has_signatures:
        return True
    if not settings.SIGNING_ENABLED:
        return False
    if contract.status == ContractStatus.ready_for_signature:
        return True
    return contract.contract_type == ContractType.b2b


# ── Guarded operations ───────────────────────────────────────────────────────


def _audit(
    contract_id: int,
    action: str,
    actor_id: Optional[int],
    *,
    from_status: ContractStatus,
    to_status: ContractStatus,
    extra: Optional[dict] = None,
) -> Activity:
    details = {"from_status": from_status.value, "to_status": to_status.value}
    if extra:
        details.update(extra)
    return Activity(
        entity_type="contract",
        entity_id=contract_id,
        action=action,
        user_id=actor_id,
        details=details,
    )


async def activate_contract(
    db: AsyncSession, contract: Contract, *, actor_id: Optional[int]
) -> None:
    """The ONLY path to ``active``. Adds the audit row; the caller commits.

    Enforces, in order: a legal transition, a complete draft, and — when a
    signature is required — verified signed evidence (a ``completed``
    ``DocumentSignature``). Any failure raises HTTP 409 and leaves state
    unchanged. Downstream side effects (``contract_signed`` notification) MUST be
    emitted by the caller only AFTER the activation commit.
    """
    previous = contract.status
    assert_transition(previous, ContractStatus.active)

    missing = validate_ready_for_activation(contract)
    if missing:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={"message": "Missing required fields", "missing": missing},
        )

    has_sig = await _has_any_signature(db, contract.id)
    if signature_required(contract, has_signatures=has_sig):
        if not await _has_completed_signature(db, contract.id):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail={
                    "message": (
                        "Contract requires a completed qualified signature "
                        "before it can be activated"
                    ),
                    "reason": "signature_required",
                },
            )

    contract.status = ContractStatus.active
    db.add(
        _audit(
            contract.id,
            "contract_activated",
            actor_id,
            from_status=previous,
            to_status=ContractStatus.active,
        )
    )


async def move_to_ready_for_signature(
    db: AsyncSession, contract: Contract, *, actor_id: Optional[int]
) -> None:
    """Finalize an unsigned draft to ``ready_for_signature`` (never ``active``).

    Requires the same complete-draft check as activation, so a contract that
    reaches signing is never missing the fields the signed record depends on.
    """
    previous = contract.status
    assert_transition(previous, ContractStatus.ready_for_signature)

    missing = validate_ready_for_activation(contract)
    if missing:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={"message": "Missing required fields", "missing": missing},
        )

    contract.status = ContractStatus.ready_for_signature
    db.add(
        _audit(
            contract.id,
            "contract_ready_for_signature",
            actor_id,
            from_status=previous,
            to_status=ContractStatus.ready_for_signature,
        )
    )


async def revert_contract(
    db: AsyncSession,
    contract: Contract,
    *,
    actor_id: Optional[int],
    reason: Optional[str] = None,
) -> None:
    """Audited revert to ``draft`` — the replacement for the old free status write.

    Legitimate cases: a mistakenly activated/finalized contract that needs to go
    back to editing. Terminal metadata (termination reason/lessons) is cleared so
    a reverted contract is a clean draft again.
    """
    previous = contract.status
    if previous == ContractStatus.draft:
        return
    assert_transition(previous, ContractStatus.draft)

    contract.status = ContractStatus.draft
    contract.termination_reason = None
    contract.termination_lessons = None
    contract.terminated_at = None
    db.add(
        _audit(
            contract.id,
            "contract_reverted",
            actor_id,
            from_status=previous,
            to_status=ContractStatus.draft,
            extra={"reason": reason} if reason else None,
        )
    )


async def reopen_contract(
    db: AsyncSession, contract: Contract, *, actor_id: Optional[int]
) -> bool:
    """Heal an ``ended``/``ending`` contract back to ``active`` (e.g. on extend).

    Returns True when a change happened. Reactivating an already-executed
    contract is not a fresh activation, so no signature check applies — the
    evidence already exists from when it was first executed.

    UWAGA: ta reguła jest dziś zduplikowana inline w `app/api/contracts.py`
    (bulk `/bulk-extend` ok. :1193 oraz `/amendments` ok. :2450). Obie kopie
    przestawiają `status` wprost, więc omijają `assert_transition` i NIE
    zapisują wiersza `Activity` `contract_reopened` — przejście najściślej
    powiązane z przychodem (zakończony konsultant wracający na `active`) jest
    jedynym bez śladu `from_status`/`to_status` w feedzie. Zmieniając regułę
    (np. dopuszczając leczenie `suspended` albo wymóg sprawdzenia podpisu)
    przemieć WSZYSTKIE trzy miejsca albo — lepiej — zwiń tamte dwie kopie do
    wywołania tej funkcji. Nie myl jej z `reopen_contract_endpoint` w routerze:
    mimo nazwy woła on `revert_contract` (→ `draft`), a nie tę operację.
    """
    previous = contract.status
    if previous not in (ContractStatus.ended, ContractStatus.ending):
        return False
    assert_transition(previous, ContractStatus.active)
    contract.status = ContractStatus.active
    db.add(
        _audit(
            contract.id,
            "contract_reopened",
            actor_id,
            from_status=previous,
            to_status=ContractStatus.active,
        )
    )
    return True


async def void_contract(
    db: AsyncSession,
    contract: Contract,
    *,
    actor_id: Optional[int],
    reason: Optional[str] = None,
) -> None:
    """Soft-delete: annul the contract while preserving documents + signatures.

    The safe alternative to a hard DELETE for executed/active contracts. Sets
    ``status = void`` + ``voided_at`` / ``voided_by``; the caller commits.
    """
    previous = contract.status
    if previous == ContractStatus.void:
        raise ContractTransitionError(
            {"message": "Contract is already void", "from": previous.value}
        )
    assert_transition(previous, ContractStatus.void)

    contract.status = ContractStatus.void
    contract.voided_at = datetime.now(timezone.utc)
    contract.voided_by = actor_id
    db.add(
        _audit(
            contract.id,
            "contract_voided",
            actor_id,
            from_status=previous,
            to_status=ContractStatus.void,
            extra={"reason": reason} if reason else None,
        )
    )


async def can_hard_delete(db: AsyncSession, contract: Contract) -> bool:
    """Only an unexecuted, unaudited ``draft`` may be hard-deleted.

    Everything else (active/ending/ended/ready_for_signature/void, or any
    contract that already has completed signature evidence or an audited manual
    bilateral-signature confirmation) must be voided instead. This preserves
    both cryptographic evidence and the generated-document employment history.
    """
    if contract.status != ContractStatus.draft:
        return False
    if await _has_completed_signature(db, contract.id):
        return False

    # Local import avoids coupling the lifecycle module's import graph to the
    # generator while still treating its one-way audit link as hard-delete
    # evidence. The FK is RESTRICT at the database layer as a final guard.
    from app.models.b2b_generated_contract import B2BGeneratedContract

    generated_confirmation_id = await db.scalar(
        select(B2BGeneratedContract.id)
        .where(
            B2BGeneratedContract.contract_id == contract.id,
            B2BGeneratedContract.signature_status == "signed_both",
        )
        .limit(1)
    )
    return generated_confirmation_id is None
