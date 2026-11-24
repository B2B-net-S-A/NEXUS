"""Wypowiedzenia z poczty — propozycja przy sprawie (decyzje Artura z 23.11.2026).

Czytnik spraw woła ``propose_for_message`` po zapisaniu każdej wiadomości
przychodzącej. Gdy reguły (``notice_rules``) rozpoznają wypowiedzenie, koniec
zamówienia u klienta, zmianę daty albo wycofanie, powstaje wiersz
``notice_mail_proposals`` z dopasowanym kontraktem, linią zamówienia i datami.
Karta sprawy w back office pokazuje go z etykietą rodzaju i przyciskiem
„Potwierdź”, który woła istniejące trasy kontraktu i zamówienia.

Zasada: automat niczego nie zapisuje w kontrakcie, zamówieniu ani w
``admin_cases.contract_id`` — dopasowanie z numeru umowy albo nazwiska to
propozycja. Kontrakt łączy człowiek przy potwierdzeniu (wtedy też uczymy
NEXUS adresu nadawcy, ``known_sender_emails``), bo zły kontrakt przesunąłby
okres wypowiedzenia i zakaz konkurencji niewłaściwej osobie.

Dopasowanie kontraktu, od najpewniejszego:
1. kontrakt już przypięty do sprawy (uwierzytelniony nadawca, odpowiedź na komunikat),
2. numer umowy z tematu albo treści („1234/2026”) → umowa z Generatora,
3. numer CPro → linia zamówienia o tym tytule (zamówienia Nordei mają numer CPro w tytule),
4. adres nadawcy znany z kontraktu, profilu albo ``known_sender_emails``,
5. imię i nazwisko: z adresu ``imie.nazwisko@…``, z nazwy nadawcy albo z tabeli
   CPro — tylko jeden żywy kontrakt o tym kluczu osoby.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date, business_today
from app.models.admin_case import AdminCase, AdminCaseMessage
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.models.notice_mail import KnownSenderEmail, NoticeMailProposal
from app.models.user import User
from app.services.admin_cases import notice_rules as rules
from app.services.b2b_documents.contract_versions import (
    default_refs,
    notice_end_date,
    refs_for,
)
from app.services.care.card_linking import person_key

logger = logging.getLogger(__name__)

LIVE_STATUSES: tuple[ContractStatus, ...] = (
    ContractStatus.active,
    ContractStatus.ending,
)
#: Zakończony też: wycofanie albo zmiana daty przychodzi czasem po nocnym zakończeniu
#: (zgłoszenie Finansów z 17.11.2026, kontrakt zakończony przed wycofaniem).
MATCH_STATUSES: tuple[ContractStatus, ...] = (*LIVE_STATUSES, ContractStatus.ended)
OPEN_ORDER_STATUSES: tuple[ClientOrderStatus, ...] = (
    ClientOrderStatus.active,
    ClientOrderStatus.paused,
    ClientOrderStatus.draft,
)
THREAD_KINDS: tuple[str, ...] = (rules.CONSULTANT_NOTICE, rules.CLIENT_TERMINATION)


@dataclass(frozen=True)
class ContractMatch:
    contract_id: Optional[int]
    order_id: Optional[int]
    reasons: tuple[str, ...]
    #: Inne kontrakty, które pasowały (karta pokazuje „sprawdź, kogo dotyczy”).
    alternatives: tuple[int, ...] = ()


def _email_key(value: Optional[str]) -> Optional[str]:
    cleaned = (value or "").strip().lower()
    return cleaned or None


async def _thread_open_kinds(db: AsyncSession, case_id: int) -> set[str]:
    rows = await db.scalars(
        select(NoticeMailProposal.kind).where(
            NoticeMailProposal.case_id == case_id,
            NoticeMailProposal.kind.in_(THREAD_KINDS),
            NoticeMailProposal.status.in_(("pending", "confirmed")),
        )
    )
    return set(rows.all())


async def _thread_match(db: AsyncSession, case_id: int) -> Optional[ContractMatch]:
    row = (
        await db.execute(
            select(NoticeMailProposal.contract_id, NoticeMailProposal.order_id)
            .where(
                NoticeMailProposal.case_id == case_id,
                NoticeMailProposal.kind.in_(THREAD_KINDS),
                NoticeMailProposal.status.in_(("pending", "confirmed")),
                NoticeMailProposal.contract_id.is_not(None),
            )
            .order_by(NoticeMailProposal.id.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return ContractMatch(contract_id=row[0], order_id=row[1], reasons=("thread",))


async def _contract_by_number(db: AsyncSession, number: Optional[str]) -> list[int]:
    if not number:
        return []
    rows = await db.scalars(
        select(B2BGeneratedContract.contract_id)
        .join(Contract, Contract.id == B2BGeneratedContract.contract_id)
        .where(
            B2BGeneratedContract.contract_number == number,
            Contract.status.in_(MATCH_STATUSES),
            Contract.voided_at.is_(None),
        )
    )
    return sorted({cid for cid in rows.all() if cid is not None})


async def orders_by_cpro(
    db: AsyncSession, number: Optional[str]
) -> list[tuple[int, int]]:
    if not number:
        return []
    rows = await db.execute(
        select(ClientOrder.contract_id, ClientOrder.id)
        .join(Contract, Contract.id == ClientOrder.contract_id)
        .where(
            func.btrim(ClientOrder.title) == number,
            Contract.status.in_(MATCH_STATUSES),
            Contract.voided_at.is_(None),
        )
        .order_by(ClientOrder.end_date.desc().nulls_last(), ClientOrder.id.desc())
    )
    return [(cid, oid) for cid, oid in rows.all()]


async def contracts_for_sender(db: AsyncSession, email: Optional[str]) -> list[int]:
    """Żywe kontrakty konsultanta po adresie: kontrakt, profil, nauczone adresy."""

    key = _email_key(email)
    if key is None:
        return []
    known = select(KnownSenderEmail.candidate_id).where(KnownSenderEmail.email == key)
    rows = await db.scalars(
        select(Contract.id)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .where(
            Contract.status.in_(LIVE_STATUSES),
            Contract.voided_at.is_(None),
            or_(
                func.lower(func.btrim(Contract.candidate_email)) == key,
                func.lower(func.btrim(Candidate.email)) == key,
                Contract.candidate_id.in_(known),
            ),
        )
        .order_by(Contract.id)
    )
    return sorted(set(rows.all()))


async def contracts_for_names(
    db: AsyncSession, names: Iterable[Optional[str]]
) -> list[int]:
    """Żywe kontrakty, których konsultant ma jeden z podanych kluczy osoby."""

    keys = {person_key(name) for name in names if name}
    keys.discard("")
    if not keys:
        return []
    rows = await db.execute(
        select(Contract.id, Candidate.name, Candidate.lastname)
        .join(Candidate, Candidate.id == Contract.candidate_id)
        .where(Contract.status.in_(LIVE_STATUSES), Contract.voided_at.is_(None))
    )
    return sorted(
        {
            cid
            for cid, first, last in rows.all()
            if person_key(f"{first} {last}") in keys
        }
    )


async def is_staff(db: AsyncSession, email: Optional[str]) -> bool:
    key = _email_key(email)
    if key is None:
        return False
    found = await db.scalar(
        select(User.id).where(func.lower(func.btrim(User.email)) == key).limit(1)
    )
    return found is not None


async def _latest_open_order(db: AsyncSession, contract_id: int) -> Optional[int]:
    return await db.scalar(
        select(ClientOrder.id)
        .where(
            ClientOrder.contract_id == contract_id,
            ClientOrder.status.in_(OPEN_ORDER_STATUSES),
        )
        .order_by(ClientOrder.end_date.desc().nulls_first(), ClientOrder.id.desc())
        .limit(1)
    )


async def match_contract(
    db: AsyncSession,
    *,
    case: AdminCase,
    signal: rules.NoticeSignal,
    sender_email: Optional[str],
    sender_name: Optional[str],
) -> ContractMatch:
    reasons: list[str] = []
    order_id: Optional[int] = None
    candidates_found: list[int] = []

    if case.contract_id is not None:
        candidates_found = [case.contract_id]
        reasons.append("case")
    if not candidates_found and signal.contract_number:
        candidates_found = await _contract_by_number(db, signal.contract_number)
        if candidates_found:
            reasons.append("contract_number")
    if signal.cpro_number:
        orders = await orders_by_cpro(db, signal.cpro_number)
        if orders:
            by_cpro = sorted({cid for cid, _ in orders})
            if not candidates_found:
                candidates_found = by_cpro
                reasons.append("cpro_number")
            order_id = next(
                (oid for cid, oid in orders if cid in candidates_found), None
            )
    if not candidates_found:
        by_sender = await contracts_for_sender(db, sender_email)
        if by_sender:
            candidates_found = by_sender
            reasons.append("sender")
    if not candidates_found:
        # Pracownik (konto NEXUSA) pisze O konsultancie, nie jako konsultant —
        # jego imię i nazwisko z adresu ani nazwa nadawcy nic nie mówią.
        staff = await is_staff(db, sender_email)
        by_name = await contracts_for_names(
            db,
            (
                None if staff else rules.name_from_address(sender_email),
                None if staff else sender_name,
                signal.consultant_name,
            ),
        )
        if by_name:
            candidates_found = by_name
            reasons.append("name")

    if len(candidates_found) != 1:
        return ContractMatch(
            contract_id=None,
            order_id=None,
            reasons=tuple(reasons),
            alternatives=tuple(candidates_found[:5]),
        )
    contract_id = candidates_found[0]
    if order_id is None:
        order_id = await _latest_open_order(db, contract_id)
    return ContractMatch(
        contract_id=contract_id, order_id=order_id, reasons=tuple(reasons)
    )


async def notice_period_for(
    db: AsyncSession, contract_id: Optional[int]
) -> tuple[Any, str]:
    """Wersja wzoru umowy kontraktu albo domyślna (2026) — z informacją, skąd."""

    if contract_id is not None:
        version = await db.scalar(
            select(B2BGeneratedContract.template_version)
            .where(B2BGeneratedContract.contract_id == contract_id)
            .order_by(B2BGeneratedContract.id.desc())
            .limit(1)
        )
        refs = refs_for(version)
        if refs is not None:
            return refs, "template"
    return default_refs(), "default"


def _delivered_on(received_at: Optional[datetime]) -> date:
    return business_date(received_at) if received_at is not None else business_today()


async def propose_for_message(
    db: AsyncSession,
    *,
    case: AdminCase,
    message: AdminCaseMessage,
    sender_authenticated: bool = False,
) -> Optional[NoticeMailProposal]:
    """Propozycja dla wiadomości przychodzącej albo ``None``.

    Nie commituje — wchodzi w punkt zapisu czytnika. Błąd tu nie może
    zatrzymać czytnika: wołający łapie wyjątek i zostawia zwykłą sprawę.
    """

    if message.direction != "in":
        return None
    open_kinds = await _thread_open_kinds(db, case.id)
    today = business_today()
    signal = rules.classify(
        subject=message.subject,
        body=message.body_text,
        attachment_names=[
            str(item.get("name") or "") for item in (message.attachments or [])
        ],
        in_notice_thread=bool(open_kinds),
        today=today,
    )
    if signal is None:
        return None
    # Ten sam rodzaj w tej samej sprawie czeka już na decyzję: druga kopia
    # (np. mail na administracja@ i rozliczenia@ naraz) nie robi drugiej karty.
    pending_same = await db.scalar(
        select(NoticeMailProposal.id).where(
            NoticeMailProposal.case_id == case.id,
            NoticeMailProposal.kind == signal.kind,
            NoticeMailProposal.status == "pending",
        )
    )
    if pending_same is not None and signal.kind != rules.DATE_CHANGE:
        return None

    match = await match_contract(
        db,
        case=case,
        signal=signal,
        sender_email=message.sender_email,
        sender_name=message.sender_name,
    )
    if match.contract_id is None and signal.kind in (
        rules.DATE_CHANGE,
        rules.WITHDRAWAL,
    ):
        # Odpowiedź w wątku (np. PM: „chcą go jednak do 31.12”) dotyczy tego
        # samego kontraktu co rozpoznany wcześniej koniec w tej sprawie.
        match = await _thread_match(db, case.id) or match
    delivered_on = _delivered_on(message.received_at)
    proposed_last_day: Optional[date] = None
    period_source: Optional[str] = None
    if signal.kind == rules.CONSULTANT_NOTICE and not signal.agreement:
        refs, period_source = await notice_period_for(db, match.contract_id)
        proposed_last_day = notice_end_date(delivered_on, refs)
    elif signal.kind == rules.DATE_CHANGE:
        proposed_last_day = signal.new_last_day
    elif signal.kind == rules.CLIENT_TERMINATION:
        proposed_last_day = signal.client_end_date

    if signal.kind == rules.DATE_CHANGE and pending_same is not None:
        # Nowsza prośba o datę zastępuje poprzednią, która jeszcze czeka.
        previous = await db.get(NoticeMailProposal, pending_same)
        if previous is not None:
            previous.status = "superseded"
            previous.decided_at = datetime.now(timezone.utc)
            previous.decision = {"superseded_by_message": message.id}

    proposal = NoticeMailProposal(
        case_id=case.id,
        message_id=message.id,
        kind=signal.kind,
        contract_id=match.contract_id,
        order_id=match.order_id,
        delivered_on=delivered_on,
        proposed_last_day=proposed_last_day,
        client_end_date=signal.client_end_date,
        contract_number=signal.contract_number,
        cpro_number=signal.cpro_number,
        match={
            "reasons": list(match.reasons),
            "alternatives": list(match.alternatives),
            "evidence": list(signal.evidence),
            "agreement": signal.agreement,
            "period_source": period_source,
            "consultant_name": signal.consultant_name,
            "reason": signal.reason,
            # Zdarzenie CPro Nordei: koniec, nieprzedłużenie, internalizacja
            # (potwierdzenie otwiera sprawę wyjścia) albo nowa data końca.
            "cpro_event": signal.cpro_event,
            # Adres zapamiętujemy tylko przy uwierzytelnionym nadawcy
            # (``can_remember_sender``) — sam ``From`` łatwo podrobić.
            "sender_authenticated": sender_authenticated,
            # Odrzucenie przywraca obszar sprawy sprzed propozycji.
            "previous_area": case.area,
        },
    )
    db.add(proposal)
    if signal.kind == rules.CONSULTANT_NOTICE and case.area != "offboarding":
        case.area = "offboarding"
    await db.flush()
    return proposal


#: Dopasowania, po których wolno zapamiętać adres nadawcy: numer umowy albo CPro
#: z treści każdy może przepisać, więc nie wiąże adresu z osobą.
REMEMBER_REASONS = frozenset({"case", "sender", "name"})


def can_remember_sender(proposal: NoticeMailProposal) -> bool:
    match = proposal.match or {}
    reasons = set(match.get("reasons") or [])
    return (
        bool(match.get("sender_authenticated"))
        and bool(reasons)
        and reasons <= REMEMBER_REASONS
    )


async def remember_sender(
    db: AsyncSession,
    *,
    email: Optional[str],
    contract_id: int,
    actor_id: Optional[int],
    source: str = "notice_confirm",
) -> bool:
    """Zapamiętaj adres nadawcy przy konsultancie kontraktu (po potwierdzeniu).

    Adres, który kontrakt albo profil już ma, i adres przypisany innej osobie
    zostają bez zmian — nie nadpisujemy cudzego wpisu.
    """

    key = _email_key(email)
    if key is None or await is_staff(db, key):
        # Adres pracownika (konto NEXUSA) to nadawca piszący O konsultancie.
        return False
    contract = await db.get(Contract, contract_id)
    if contract is None or contract.candidate_id is None:
        return False
    if contract_id in await contracts_for_sender(db, key):
        return False
    existing = await db.get(KnownSenderEmail, key)
    if existing is not None:
        return False
    db.add(
        KnownSenderEmail(
            email=key,
            candidate_id=contract.candidate_id,
            source=source,
            confirmed_by=actor_id,
        )
    )
    await db.flush()
    return True
