"""„Wycofaj wypowiedzenie” — konsultant wycofał wypowiedzenie (zgłoszenie Finansów 17.11.2026).

Wypowiedzenie zapisane aneksem „Wcześniejsze zakończenie” skraca umowę
(np. 15.12 → 31.10). Gdy konsultant je wycofa, w NEXUSIE nie było drogi
powrotu: „Cofnij zakończenie” wraca do stanu z migawki nocnego zakończenia,
czyli do daty 31.10, która minęła (blokada „przedłuż aneksem”), a „Przedłuż”
dla B2B jest wyłączony. Ta akcja zamyka pętlę:

* **kontrakt jeszcze trwa** („Aktywny”/„Kończący się”, nic nie offboardowano):
  dostaje datę końca podaną przez człowieka (B2B domyślnie bez daty) i wraca
  na „Aktywny”, a dane rozwiązania umowy są czyszczone jak przy cofnięciu;
* **kontrakt już zakończony** (albo zakończenie ruszyło zamówienia — otwarta
  migawka, sprawa puli MD): to samo „Cofnij zakończenie”
  (``execute_reversal``) z nadpisaną datą końca — zamówienia, sprawy MD
  i importy wracają tą samą drogą co przy pomyłce.

Ślad: wpis w Aneksach ``custom_change`` o nazwie „Wycofanie wypowiedzenia”
z id wycofanego aneksu (``WITHDRAWN_AMENDMENT_KEY``); od tej chwili tamten
aneks nie liczy się jako ręczne zakończenie (``is_manually_terminated``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.contract import Contract, ContractStatus
from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
from app.models.contract_document import ContractDocument
from app.models.dl_alert import ALERT_CONTRACT_ENDING
from app.services.b2b_contract_end_date import (
    WITHDRAWN_AMENDMENT_KEY,
    is_b2b,
    withdrawn_notice_ids,
)
from app.services.contract_lifecycle import assert_transition
from app.services.contract_termination_reversal import (
    ReversalPlan,
    build_reversal_plan,
    execute_reversal,
    reversal_available,
)
from app.services.dl_alerts import resolve_entity_alerts

NOTICE_WITHDRAWAL_TITLE = "Wycofanie wypowiedzenia"
NOTICE_WITHDRAWAL_ACTION = "notice_withdrawn"

_LIVE_STATUSES = (ContractStatus.active, ContractStatus.ending, ContractStatus.ended)


class NoticeWithdrawalError(Exception):
    """Odmowa z kodem dla API (409/422) i zdaniem po polsku dla człowieka."""

    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class Notice:
    amendment: ContractAmendment
    #: Data końca wpisana wypowiedzeniem (dziś na kontrakcie).
    notice_end: date
    #: Data końca sprzed wypowiedzenia — podpowiedź w oknie.
    end_before_notice: Optional[date]


def _value(raw: Any) -> Any:
    return getattr(raw, "value", raw)


def _parse(raw: Any) -> Optional[date]:
    if raw in (None, ""):
        return None
    return raw if isinstance(raw, date) else date.fromisoformat(str(raw))


def _iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value is not None else None


async def withdrawable_notice(db: AsyncSession, contract: Contract) -> Optional[Notice]:
    """Wypowiedzenie, które da się wycofać: NAJNOWSZY aneks „Wcześniejsze
    zakończenie”, jeszcze nie wycofany, którego data dalej stoi na kontrakcie.

    Inna data końca na kontrakcie = ktoś ją już zmienił po wypowiedzeniu
    (przedłużenie, nowe zakończenie) i wypowiedzenie przestało opisywać stan.
    """
    if ContractStatus(_value(contract.status)) not in _LIVE_STATUSES:
        return None
    amendment = await db.scalar(
        select(ContractAmendment)
        .where(
            ContractAmendment.contract_id == contract.id,
            ContractAmendment.amendment_type == ContractAmendmentType.early_termination,
        )
        .order_by(ContractAmendment.effective_date.desc(), ContractAmendment.id.desc())
        .limit(1)
    )
    if amendment is None:
        return None
    withdrawn = set((await db.scalars(withdrawn_notice_ids(contract.id))).all())
    if amendment.id in withdrawn:
        return None
    notice_end = _parse((amendment.new_values or {}).get("end_date"))
    if notice_end is None or contract.end_date != notice_end:
        return None
    return Notice(
        amendment=amendment,
        notice_end=notice_end,
        end_before_notice=_parse((amendment.old_values or {}).get("end_date")),
    )


def _check_end_date(contract: Contract, end_date: Optional[date]) -> None:
    if end_date is None and not is_b2b(contract.contract_type):
        raise NoticeWithdrawalError(
            "end_date_required",
            "Umowa zlecenie i umowa o pracę mają datę końca w treści umowy — podaj ją.",
        )
    if end_date is not None and end_date < business_today():
        raise NoticeWithdrawalError(
            "end_date_passed",
            f"Data {end_date.strftime('%d.%m.%Y')} już minęła — wybierz dzisiejszą "
            "albo późniejszą albo umowę bezterminową.",
        )
    if (
        end_date is not None
        and contract.start_date is not None
        and end_date < contract.start_date
    ):
        raise NoticeWithdrawalError(
            "end_date_before_start_date",
            "Data końca nie może być wcześniejsza niż start umowy.",
        )


async def _require_notice(db: AsyncSession, contract: Contract) -> Notice:
    notice = await withdrawable_notice(db, contract)
    if notice is None:
        raise NoticeWithdrawalError(
            "no_notice",
            "Ten kontrakt nie ma wypowiedzenia, które można wycofać.",
            status_code=409,
        )
    return notice


def _notice_json(notice: Notice) -> dict[str, Any]:
    return {
        "amendment_id": notice.amendment.id,
        "effective_date": _iso(notice.amendment.effective_date),
        "notice_end": _iso(notice.notice_end),
        "end_before_notice": _iso(notice.end_before_notice),
        "reason": notice.amendment.reason,
    }


async def preview_notice_withdrawal(
    db: AsyncSession, contract: Contract
) -> dict[str, Any]:
    """Okno „Wycofaj wypowiedzenie”: wypowiedzenie, opcje daty i — gdy
    zakończenie już ruszyło zamówienia — plan ich przywrócenia (bez zapisu)."""

    notice = await _require_notice(db, contract)
    reversal: Optional[ReversalPlan] = None
    if await reversal_available(db, contract):
        # Data końca w podglądzie nie zmienia zamówień ani blokad (minionej
        # daty i tak nie da się wybrać), więc wystarczy jeden plan.
        reversal = await build_reversal_plan(db, contract, end_date_override=None)
    return {
        "contract_id": contract.id,
        "contract_type": str(_value(contract.contract_type)),
        "status": str(_value(contract.status)),
        "end_date": _iso(contract.end_date),
        "notice": _notice_json(notice),
        "earliest_end_date": business_today().isoformat(),
        "indefinite_allowed": is_b2b(contract.contract_type),
        "reversal": reversal.as_json() if reversal is not None else None,
    }


async def _check_document(
    db: AsyncSession, contract: Contract, document_id: Optional[int]
) -> None:
    if document_id is None:
        return
    owner = await db.scalar(
        select(ContractDocument.contract_id).where(ContractDocument.id == document_id)
    )
    if owner != contract.id:
        raise NoticeWithdrawalError(
            "document_not_found",
            "Wybrany dokument nie należy do tego kontraktu.",
        )


async def withdraw_notice(
    db: AsyncSession,
    contract: Contract,
    *,
    end_date: Optional[date],
    actor_id: Optional[int],
    note: Optional[str] = None,
    document_id: Optional[int] = None,
) -> dict[str, Any]:
    """Wycofaj wypowiedzenie. Wołający trzyma blokadę kontraktu i commituje
    (``commit_order_write`` — synchronizacja kontrakt ↔ zamówienia).

    Blokada „Cofnij zakończenie” (decyzja o puli MD, „Powrót po przerwie”,
    usunięty klient) przechodzi dalej jako ``ReversalBlocked``.
    """
    notice = await _require_notice(db, contract)
    _check_end_date(contract, end_date)
    await _check_document(db, contract, document_id)
    status_before = ContractStatus(_value(contract.status))
    end_before = contract.end_date

    reversal: Optional[ReversalPlan] = None
    if await reversal_available(db, contract):
        reversal = await execute_reversal(
            db, contract, actor_id=actor_id, end_date_override=end_date
        )
    else:
        # Wypowiedzenie jeszcze biegnie, zamówień nikt nie ruszał: tylko umowa.
        if status_before == ContractStatus.ending:
            assert_transition(status_before, ContractStatus.active)
            contract.status = ContractStatus.active
        contract.end_date = end_date
        contract.terminated_at = None
        contract.termination_reason = None
        contract.termination_lessons = None
        from app.services.contract_termination_sync import undo_contract_termination

        await undo_contract_termination(db, contract, actor_id=actor_id)
        await resolve_entity_alerts(
            db,
            alert_type=ALERT_CONTRACT_ENDING,
            entity_key=f"contract:{contract.id}",
        )

    old_values = {"end_date": _iso(end_before), "status": status_before.value}
    new_values = {
        "annex_title": NOTICE_WITHDRAWAL_TITLE,
        "end_date": _iso(end_date),
        "status": str(_value(contract.status)),
        WITHDRAWN_AMENDMENT_KEY: notice.amendment.id,
    }
    amendment = ContractAmendment(
        contract_id=contract.id,
        amendment_type=ContractAmendmentType.custom_change,
        old_values=old_values,
        new_values=new_values,
        effective_date=business_today(),
        reason=(note or "").strip() or None,
        document_id=document_id,
        created_by=actor_id,
    )
    db.add(amendment)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action=NOTICE_WITHDRAWAL_ACTION,
            user_id=actor_id,
            details={
                "message": NOTICE_WITHDRAWAL_TITLE,
                "withdrawn_amendment_id": notice.amendment.id,
                "old": old_values,
                "new": {k: v for k, v in new_values.items() if k != "annex_title"},
                "restored_order_ids": (
                    [item.order_id for item in reversal.orders] if reversal else []
                ),
            },
        )
    )
    await db.flush()
    return {
        "contract_id": contract.id,
        "amendment_id": amendment.id,
        "withdrawn_amendment_id": notice.amendment.id,
        "status": str(_value(contract.status)),
        "end_date": _iso(contract.end_date),
        "reversal": reversal.as_json() if reversal is not None else None,
    }


__all__ = [
    "NOTICE_WITHDRAWAL_TITLE",
    "Notice",
    "NoticeWithdrawalError",
    "preview_notice_withdrawal",
    "withdraw_notice",
    "withdrawable_notice",
]
