"""Wypowiedzenia z poczty — odczyt propozycji na karcie i decyzja człowieka.

Karta pokazuje: co przyszło (mail), jak NEXUS doszedł do kontraktu, jakie daty
proponuje, inne propozycje w tym samym wątku i daty, które się rozjechały
(umowa, linia zamówienia, klient). Przyciski karty wołają istniejące trasy
(``POST /api/contracts/{id}/terminate``, ``/notice-withdrawal``,
``PATCH /api/clients/{c}/orders/{o}``); ``decide`` tylko zapisuje wybór, łączy
sprawę z kontraktem, uczy NEXUS adresu nadawcy i domyka sprawę z maila.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, is_business_day
from app.models.admin_case import AdminCase, AdminCaseMessage
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder
from app.models.contract import Contract, ContractStatus
from app.models.notice_mail import NoticeMailProposal
from app.models.user import User
from app.services.admin_cases import notice_mail
from app.services.admin_cases import notice_rules as rules
from app.services.admin_cases import service as cases
from app.services.b2b_documents.contract_versions import notice_end_date
from app.services.hr import audit

EXCERPT_LIMIT = 900
REASON_LABELS: dict[str, str] = {
    "case": "kontrakt przypięty do sprawy",
    "contract_number": "numer umowy z maila",
    "cpro_number": "numer zamówienia z CPro",
    "sender": "adres nadawcy znany przy kontrakcie",
    "name": "imię i nazwisko (jedyny żywy kontrakt)",
    "thread": "ten sam wątek co rozpoznany koniec",
}
DECISIONS = ("confirmed", "rejected")


class NoticeError(Exception):
    def __init__(self, message: str, *, status_code: int = 422, code: str = "invalid"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _next_business_day(day: date) -> date:
    nxt = day + timedelta(days=1)
    while not is_business_day(datetime(nxt.year, nxt.month, nxt.day, 12)):
        nxt += timedelta(days=1)
    return nxt


async def _contract_view(
    db: AsyncSession, contract_id: Optional[int]
) -> Optional[dict]:
    if contract_id is None:
        return None
    row = (
        await db.execute(
            select(Contract, Candidate.name, Candidate.lastname, Client.name)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .outerjoin(Client, Client.id == Contract.client_id)
            .where(Contract.id == contract_id)
        )
    ).first()
    if row is None:
        return None
    contract, first, last, client = row
    exit_case = await db.scalar(
        select(AdminCase.id).where(
            AdminCase.source_key == f"contract:{contract.id}:end",
            AdminCase.status.notin_(("done", "closed")),
        )
    )
    return {
        "id": contract.id,
        "person": " ".join(part for part in (first, last) if part) or None,
        "client": client,
        "client_id": contract.client_id,
        "status": getattr(contract.status, "value", contract.status),
        "contract_type": getattr(
            contract.contract_type, "value", contract.contract_type
        ),
        "start_date": contract.start_date,
        "end_date": contract.end_date,
        "terminated_at": contract.terminated_at,
        "agreement_termination_mode": contract.agreement_termination_mode,
        "exit_case_id": exit_case,
    }


async def _order_view(db: AsyncSession, order_id: Optional[int]) -> Optional[dict]:
    if order_id is None:
        return None
    order = await db.get(ClientOrder, order_id)
    if order is None:
        return None
    return {
        "id": order.id,
        "title": order.title,
        "client_id": order.client_id,
        "status": getattr(order.status, "value", order.status),
        "start_date": order.start_date,
        "end_date": order.end_date,
    }


def _message_view(message: Optional[AdminCaseMessage]) -> Optional[dict]:
    if message is None:
        return None
    excerpt = rules.fresh_text(message.body_text or "").strip()
    return {
        "id": message.id,
        "sender_email": message.sender_email,
        "sender_name": message.sender_name,
        "subject": message.subject,
        "received_at": message.received_at,
        "excerpt": excerpt[:EXCERPT_LIMIT],
        "attachments": [
            item.get("name")
            for item in (message.attachments or [])
            if not item.get("inline")
        ],
    }


def _date_rows(
    proposal: NoticeMailProposal, contract: Optional[dict], order: Optional[dict]
) -> list[dict[str, Any]]:
    """Daty do porównania: umowa, linia zamówienia, klient, propozycja."""

    rows: list[dict[str, Any]] = []
    if contract is not None:
        rows.append(
            {
                "key": "contract",
                "label": "Umowa w NEXUSIE",
                "date": contract["end_date"],
            }
        )
    if order is not None:
        rows.append(
            {
                "key": "order",
                "label": f"Linia zamówienia {order['title']}",
                "date": order["end_date"],
            }
        )
    if proposal.client_end_date is not None:
        rows.append(
            {
                "key": "client",
                "label": "Klient (z maila)",
                "date": proposal.client_end_date,
            }
        )
    if (
        proposal.proposed_last_day is not None
        and proposal.kind != rules.CLIENT_TERMINATION
    ):
        rows.append(
            {
                "key": "proposal",
                "label": "Z tego maila",
                "date": proposal.proposed_last_day,
            }
        )
    dates = {row["date"] for row in rows if row["date"] is not None}
    for row in rows:
        row["differs"] = len(dates) > 1 and row["date"] is not None
    return rows


async def _thread(db: AsyncSession, case_id: int) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(NoticeMailProposal, AdminCaseMessage)
            .outerjoin(
                AdminCaseMessage, AdminCaseMessage.id == NoticeMailProposal.message_id
            )
            .where(NoticeMailProposal.case_id == case_id)
            .order_by(NoticeMailProposal.id)
        )
    ).all()
    return [
        {
            "id": proposal.id,
            "kind": proposal.kind,
            "label": rules.KIND_LABELS.get(proposal.kind, proposal.kind),
            "status": proposal.status,
            "received_at": message.received_at if message else None,
            "sender_name": (message.sender_name or message.sender_email)
            if message
            else None,
            "subject": message.subject if message else None,
            "proposed_last_day": proposal.proposed_last_day,
        }
        for proposal, message in rows
    ]


async def proposal_detail(db: AsyncSession, proposal: NoticeMailProposal) -> dict:
    message = (
        await db.get(AdminCaseMessage, proposal.message_id)
        if proposal.message_id is not None
        else None
    )
    case = await db.get(AdminCase, proposal.case_id)
    # Kontrakt przypięty w sprawie („Kogo dotyczy?”) odblokowuje kartę bez dopasowania.
    contract_id = proposal.contract_id or (case.contract_id if case else None)
    contract = await _contract_view(db, contract_id)
    order = await _order_view(db, proposal.order_id)
    match = proposal.match or {}
    alternatives = [
        view
        for view in [
            await _contract_view(db, cid) for cid in match.get("alternatives") or []
        ]
        if view is not None
    ]
    alternative_last_day = None
    if (
        proposal.kind == rules.CONSULTANT_NOTICE
        and proposal.delivered_on is not None
        and proposal.proposed_last_day is not None
    ):
        # Mail w sobotę wieczorem: przy doręczeniu od następnego dnia
        # roboczego koniec wypada miesiąc później (kontrakt #29, 31.10).
        refs, _ = await notice_mail.notice_period_for(db, proposal.contract_id)
        later = notice_end_date(_next_business_day(proposal.delivered_on), refs)
        if later != proposal.proposed_last_day:
            alternative_last_day = later
    sender_known = bool(
        message is not None
        and contract_id is not None
        and contract_id
        in await notice_mail.contracts_for_sender(db, message.sender_email)
    )
    can_remember = bool(
        message is not None
        and notice_mail.can_remember_sender(proposal)
        and not await notice_mail.is_staff(db, message.sender_email)
    )
    return {
        "id": proposal.id,
        "case_id": proposal.case_id,
        "kind": proposal.kind,
        "label": rules.KIND_LABELS.get(proposal.kind, proposal.kind),
        "status": proposal.status,
        "delivered_on": proposal.delivered_on,
        "proposed_last_day": proposal.proposed_last_day,
        "alternative_last_day": alternative_last_day,
        "client_end_date": proposal.client_end_date,
        "contract_number": proposal.contract_number,
        "cpro_number": proposal.cpro_number,
        "agreement": bool(match.get("agreement")),
        "period_source": match.get("period_source"),
        "client_reason": match.get("reason"),
        "evidence": match.get("evidence") or [],
        "reasons": [
            {"key": key, "label": REASON_LABELS.get(key, key)}
            for key in match.get("reasons") or []
        ],
        "message": _message_view(message),
        "sender_known": sender_known,
        "can_remember_sender": can_remember,
        "contract": contract,
        "alternatives": alternatives,
        "order": order,
        "dates": _date_rows(proposal, contract, order),
        "thread": await _thread(db, proposal.case_id),
        "decision": proposal.decision or None,
        "decided_at": proposal.decided_at,
    }


def _ended_or_ending(contract: Contract) -> bool:
    return contract.terminated_at is not None or contract.status in (
        ContractStatus.ending,
        ContractStatus.ended,
    )


async def decide(
    db: AsyncSession,
    proposal: NoticeMailProposal,
    *,
    actor: User,
    decision: str,
    contract_id: Optional[int],
    remember_sender: bool,
    applied: dict[str, Any],
    note: Optional[str],
) -> NoticeMailProposal:
    """Zapis decyzji. Zmiany w kontrakcie i zamówieniu zrobiły już trasy, które
    wołała karta — tu sprawdzamy, że naprawdę się stały."""

    if decision not in DECISIONS:
        raise NoticeError("Nieznana decyzja.")
    if proposal.status != "pending":
        raise NoticeError(
            "Ta propozycja jest już rozstrzygnięta.", status_code=409, code="decided"
        )
    case = await db.get(AdminCase, proposal.case_id)
    if case is None:
        raise NoticeError("Sprawa nie istnieje.", status_code=404, code="missing")
    now = datetime.now(timezone.utc)
    summary: Optional[str] = None

    if decision == "confirmed":
        target_id = contract_id or proposal.contract_id or case.contract_id
        if target_id is None:
            raise NoticeError("Wskaż kontrakt, którego dotyczy mail.")
        allowed = {
            proposal.contract_id,
            case.contract_id,
            *((proposal.match or {}).get("alternatives") or []),
        } - {None}
        if target_id not in allowed:
            # Inny kontrakt przypina się w sprawie („Kogo dotyczy?”), nie tutaj.
            raise NoticeError(
                "Ten kontrakt nie pasuje do maila — przypnij go w sprawie.",
                code="contract_not_proposed",
            )
        contract = await db.get(Contract, target_id)
        if contract is None:
            raise NoticeError("Kontrakt nie istnieje.", status_code=404, code="missing")
        if proposal.kind == rules.CONSULTANT_NOTICE and not _ended_or_ending(contract):
            raise NoticeError(
                "Najpierw zapisz zakończenie współpracy — kontrakt jest dalej aktywny.",
                status_code=409,
                code="not_terminated",
            )
        if proposal.kind == rules.WITHDRAWAL and contract.terminated_at is not None:
            raise NoticeError(
                "Najpierw wycofaj wypowiedzenie w kontrakcie.",
                status_code=409,
                code="not_withdrawn",
            )
        proposal.contract_id = contract.id
        if case.contract_id is None:
            case.contract_id = contract.id
            audit.record(
                db,
                actor_user_id=actor.id,
                subject_user_id=case.subject_user_id,
                entity_type="admin_case",
                entity_id=case.id,
                action="case_linked",
                details={"contract_id": contract.id, "source": "notice_confirm"},
            )
        if (
            remember_sender
            and proposal.message_id is not None
            and notice_mail.can_remember_sender(proposal)
        ):
            message = await db.get(AdminCaseMessage, proposal.message_id)
            if message is not None:
                applied = {
                    **applied,
                    "sender_remembered": await notice_mail.remember_sender(
                        db,
                        email=message.sender_email,
                        contract_id=contract.id,
                        actor_id=actor.id,
                    ),
                }
        summary = _confirm_summary(proposal, contract, applied)
    else:
        summary = "Propozycja z maila odrzucona: to nie " + {
            rules.CONSULTANT_NOTICE: "wypowiedzenie.",
            rules.CLIENT_TERMINATION: "koniec zamówienia u klienta.",
            rules.DATE_CHANGE: "zmiana daty.",
            rules.WITHDRAWAL: "wycofanie wypowiedzenia.",
        }.get(proposal.kind, "zakończenie.")

    proposal.status = decision
    proposal.decided_by = actor.id
    proposal.decided_at = now
    proposal.decision = {**applied, "note": (note or "").strip()[:500] or None}
    comment = summary + (f" {note.strip()}" if note and note.strip() else "")
    await cases.add_comment(db, case, actor=actor, body=comment[: cases.COMMENT_MAX])
    others_pending = await db.scalar(
        select(NoticeMailProposal.id)
        .where(
            NoticeMailProposal.case_id == case.id,
            NoticeMailProposal.status == "pending",
            NoticeMailProposal.id != proposal.id,
        )
        .limit(1)
    )
    if decision == "rejected" and others_pending is None:
        previous_area = (proposal.match or {}).get("previous_area")
        if previous_area and previous_area != case.area:
            await cases.update_case(
                db, case, actor=actor, changes={"area": previous_area}
            )
    if decision == "confirmed" and others_pending is None:
        # Pracę niesie dalej sprawa wyjścia albo zamówienie; sprawa z maila
        # zostaje w historii z komentarzem, co z niej wynikło. Inna czekająca
        # propozycja w tej sprawie (np. zmiana daty po wypowiedzeniu) trzyma
        # ją otwartą, żeby nie zniknęła z tablicy.
        await cases.update_case(db, case, actor=actor, changes={"status": "done"})
    await db.flush()
    return proposal


def _confirm_summary(
    proposal: NoticeMailProposal, contract: Contract, applied: dict[str, Any]
) -> str:
    day = applied.get("last_day") or applied.get("order_end_date")
    when = ""
    if isinstance(day, str):
        try:
            when = f" ({date.fromisoformat(day):%d.%m.%Y})"
        except ValueError:
            when = ""
    return {
        rules.CONSULTANT_NOTICE: f"Wypowiedzenie z maila potwierdzone na kontrakcie #{contract.id}{when}.",
        rules.CLIENT_TERMINATION: f"Koniec zamówienia u klienta rozstrzygnięty na kontrakcie #{contract.id}{when}.",
        rules.DATE_CHANGE: f"Zmiana daty z maila rozstrzygnięta na kontrakcie #{contract.id}{when}.",
        rules.WITHDRAWAL: f"Wycofanie wypowiedzenia potwierdzone na kontrakcie #{contract.id}.",
    }.get(proposal.kind, f"Propozycja z maila potwierdzona (kontrakt #{contract.id}).")


async def pending_for_contract(db: AsyncSession, contract_id: int) -> list[dict]:
    """Propozycje z maili przy kontrakcie (baner na karcie kontraktu)."""

    rows = (
        await db.execute(
            select(NoticeMailProposal, AdminCaseMessage.received_at)
            .outerjoin(
                AdminCaseMessage, AdminCaseMessage.id == NoticeMailProposal.message_id
            )
            .where(
                NoticeMailProposal.contract_id == contract_id,
                NoticeMailProposal.status.in_(("pending", "confirmed")),
            )
            .order_by(NoticeMailProposal.id)
        )
    ).all()
    today = business_today()
    return [
        {
            "id": p.id,
            "case_id": p.case_id,
            "kind": p.kind,
            "label": rules.KIND_LABELS.get(p.kind, p.kind),
            "status": p.status,
            "received_at": received_at,
            "proposed_last_day": p.proposed_last_day,
            "client_end_date": p.client_end_date,
            "stale": p.status == "pending"
            and p.proposed_last_day is not None
            and p.proposed_last_day < today,
        }
        for p, received_at in rows
    ]
