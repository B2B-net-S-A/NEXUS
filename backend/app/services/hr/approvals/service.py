"""Zgody: wysłanie, poprawka, wycofanie, decyzja i odczyty (0483, 20.10.2026).

Droga zgody (``route``):

* **premia poza umową** — prosi Płace albo przełożony osoby
  (``PayrollViewer.manages_bonuses_of``; wniosek przełożonego to już jego
  poparcie), idzie prosto do zatwierdzającego (``pending_final``),
* **wydatek** — najpierw przełożony autora (``recipients.supervisor_of``:
  przełożony z kartoteki albo head pionu; Kadry jako zapas się nie liczą —
  Kadry nie decydują o wydatkach). Do progu z Ustawień jego „Zatwierdź”
  zamyka sprawę, ponad próg to poparcie i sprawa idzie do zatwierdzającego.
  Autor bez przełożonego (zarząd) — od razu do zatwierdzającego.

Zatwierdzający (``rules.final_approver_ids``) decyduje na każdym etapie.
Nikt nie decyduje we własnej sprawie ani o premii dla siebie (CHECK w bazie
i odmowa 403 tutaj). Każda decyzja to warunkowy ``UPDATE … WHERE status``
pod blokadą wiersza — druga decyzja tej samej chwili dostaje 409.

Zatwierdzona premia staje się przyznaną premią w Płacach (``hr_bonuses``,
``source='manual'``, kategoria „Inna”, ``assigned_by`` = zatwierdzający,
``rule_snapshot.approval_request_id``) na miesiąc wypłaty z wniosku — bez
drugiej akceptacji Płac. Zamknięty miesiąc = 409, zgoda zostaje do decyzji.

Premia dla osoby na B2B (także z formą „do uzupełnienia”) wymaga podstawy
w umowie — punktu umowy albo numeru aneksu (``contract_basis``, decyzja
Artura 21.10.2026): uznaniowa nagroda od koordynatora to dla PIP cecha
stosunku pracy. Umowa o pracę i zlecenie bez zmian.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_day_start_utc, local_now
from app.models.client import Client
from app.models.hr_approval import ApprovalRequest
from app.models.hr_payroll import HrBonus
from app.models.hr_profile import EmployeeProfile
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services.hr import (
    audit,
    payroll_access,
    payroll_periods,
    recipients,
    white_list,
)
from app.services.hr.approvals import rules as approval_rules
from app.services.hr.approvals.rules import ApprovalRules
from app.services.hr.employment_terms import bonus_message, terms
from app.services.hr_approval_basis_schema import CONTRACT_BASIS_MAX_LENGTH
from app.services.hr.notify import notify_each
from app.services.hr import payroll_bonuses
from app.services.hr.payroll_errors import PayrollConflict, PayrollError
from app.services.hr.payroll_periods import add_months, label
from app.services.hr_payroll_schema import AUTOMATED_SOURCES
from app.services.hr_approvals_schema import (
    AMOUNT_BASES,
    AMOUNT_MAX,
    CURRENCIES,
    KINDS,
    LINK_MAX_LENGTH,
    NOTE_MAX_LENGTH,
    PAYERS,
    PENDING_STATUSES,
    PURPOSE_MAX_LENGTH,
    RECURRENCES,
    TITLE_MAX_LENGTH,
)

#: Zgody to ekran wielu osób — słowa neutralne: „wynagrodzenie dodatkowe”,
#: nie „premia poza umową” (decyzja Artura 21.10.2026).
KIND_LABELS: dict[str, str] = {
    "bonus": "Wynagrodzenie dodatkowe",
    "subscription": "Subskrypcja",
    "trip": "Koszty podróży",
    "gift": "Prezent",
    "training": "Szkolenie",
    "other": "Inny wydatek",
}
DECISIONS = ("approve", "reject", "return")
#: Miesiąc wypłaty premii: od poprzedniego do dwóch kolejnych.
PAYOUT_MONTHS_BACK = 1
PAYOUT_MONTHS_AHEAD = 2
_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
_AMOUNT_LIMIT = Decimal(AMOUNT_MAX)
_CENT = Decimal("0.01")


class ApprovalError(Exception):
    status_code = 422

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ApprovalForbidden(ApprovalError):
    status_code = 403


class ApprovalNotFound(ApprovalError):
    status_code = 404


class ApprovalConflict(ApprovalError):
    status_code = 409


NOT_FOUND = "Nie ma takiej zgody."


@dataclass(frozen=True)
class RequestInput:
    kind: str
    title: str
    purpose: str
    amount: Decimal
    currency: str = "PLN"
    amount_basis: str = "gross"
    recurrence: str = "once"
    payer: Optional[str] = None
    link_url: Optional[str] = None
    needed_by: Optional[date] = None
    starts_on: Optional[date] = None
    ends_on: Optional[date] = None
    beneficiary_user_id: Optional[int] = None
    payout_year: Optional[int] = None
    payout_month: Optional[int] = None
    #: Etap 3 (0486): klient prezentu (Historia zdarzeń klienta) i NIP
    #: sprzedawcy, jeśli autor go zna (faktura z KSeF przypnie się sama).
    client_id: Optional[int] = None
    seller_nip: Optional[str] = None
    #: 0491: punkt umowy albo numer aneksu — wymagany przy premii dla B2B.
    contract_basis: Optional[str] = None


# ── walidacja ────────────────────────────────────────────────────────────


def clean_amount(value: Decimal) -> Decimal:
    try:
        if not value.is_finite() or value <= 0 or value > _AMOUNT_LIMIT:
            raise ApprovalError("Kwota: od 0,01 do 10 000 000.")
        cleaned = value.quantize(_CENT)
    except InvalidOperation as exc:
        raise ApprovalError("Kwota: od 0,01 do 10 000 000.") from exc
    if cleaned < _CENT:
        raise ApprovalError("Kwota: od 0,01 do 10 000 000.")
    return cleaned


def clean_bonus_amount(value: Decimal) -> Decimal:
    """Kwota premii jak w Płacach: HALF_UP i najwyżej 1 000 000 (CHECK
    ``ck_hr_bonuses_amount``) — inaczej zatwierdzenie dawałoby 500."""

    try:
        return payroll_bonuses.clean_amount(value)
    except PayrollError as exc:
        raise ApprovalError(exc.message) from exc


def _text(
    value: Optional[str], *, limit: int, field: str, required: bool
) -> Optional[str]:
    # Tytuł w jednej linii; „po co” zachowuje akapity.
    raw = value or ""
    cleaned = raw.strip() if field == "purpose" else " ".join(raw.split())
    if required and not cleaned:
        raise ApprovalError(f"Uzupełnij pole: {field_label(field)}.")
    if len(cleaned) > limit:
        raise ApprovalError(f"{field_label(field)}: najwyżej {limit} znaków.")
    return cleaned or None


def field_label(field: str) -> str:
    return {
        "title": "Co dokładnie",
        "purpose": "Po co",
        "note": "Uwaga",
        "contract_basis": "Podstawa w umowie",
    }.get(field, field)


def needs_contract_basis(employment_type: Optional[str], pending: bool) -> bool:
    """Premia dla tej osoby wymaga podstawy w umowie: B2B albo forma
    „do uzupełnienia” (prawie cała firma jest na B2B)."""

    return pending or employment_type == "b2b"


def clean_input(data: RequestInput, *, today: date) -> RequestInput:
    """Wniosek po walidacji; błąd = zdanie dla wnioskującego."""

    if data.kind not in KINDS:
        raise ApprovalError("Nieznany rodzaj zgody.")
    if data.currency not in CURRENCIES:
        raise ApprovalError("Waluta: PLN, EUR albo USD.")
    if data.amount_basis not in AMOUNT_BASES:
        raise ApprovalError("Kwota netto albo brutto.")
    if data.recurrence not in RECURRENCES:
        raise ApprovalError("Jak często: raz, co miesiąc albo co rok.")
    if data.payer is not None and data.payer not in PAYERS:
        raise ApprovalError("Kto płaci: faktura na firmę, karta firmowa albo zwrot.")
    link = (data.link_url or "").strip() or None
    if link is not None and (len(link) > LINK_MAX_LENGTH or not _URL_RE.match(link)):
        raise ApprovalError("Link do oferty zaczyna się od http:// albo https://.")
    if data.starts_on and data.ends_on and data.ends_on < data.starts_on:
        raise ApprovalError("Data końca jest wcześniejsza niż początku.")
    title = _text(data.title, limit=TITLE_MAX_LENGTH, field="title", required=True)
    purpose = _text(
        data.purpose, limit=PURPOSE_MAX_LENGTH, field="purpose", required=True
    )
    if data.kind == "bonus":
        amount = clean_bonus_amount(data.amount)
    else:
        amount = clean_amount(data.amount)
    if data.client_id is not None and data.kind != "gift":
        raise ApprovalError("Klienta wskazuje się przy prezencie dla klienta.")
    contract_basis = _text(
        data.contract_basis,
        limit=CONTRACT_BASIS_MAX_LENGTH,
        field="contract_basis",
        required=False,
    )
    if contract_basis is not None:
        if data.kind != "bonus":
            raise ApprovalError(
                "Podstawę w umowie podaje się przy wynagrodzeniu dodatkowym."
            )
        if not any(char.isdigit() for char in contract_basis):
            raise ApprovalError(
                "Podstawa w umowie: wpisz punkt umowy albo numer aneksu, "
                "np. „§ 6 ust. 2 umowy z 01.03.2025”."
            )
    seller_nip = None
    if data.seller_nip and data.kind != "bonus":
        try:
            seller_nip = white_list.clean_nip(data.seller_nip)
        except white_list.WhiteListError:
            raise ApprovalError(
                "NIP sprzedawcy ma 10 cyfr z poprawną sumą kontrolną."
            ) from None
    if data.kind == "bonus":
        if data.beneficiary_user_id is None:
            raise ApprovalError(
                "Wybierz osobę, której dotyczy wynagrodzenie dodatkowe."
            )
        if data.payout_year is None or data.payout_month is None:
            raise ApprovalError("Wybierz miesiąc wypłaty wynagrodzenia dodatkowego.")
        payroll_periods.validate_period(data.payout_year, data.payout_month)
        earliest = add_months(today.year, today.month, -PAYOUT_MONTHS_BACK)
        latest = add_months(today.year, today.month, PAYOUT_MONTHS_AHEAD)
        if not earliest <= (data.payout_year, data.payout_month) <= latest:
            raise ApprovalError(
                f"Miesiąc wypłaty: od {label(*earliest)} do {label(*latest)}."
            )
        return RequestInput(
            kind="bonus",
            title=title,
            purpose=purpose,
            amount=amount,
            currency=data.currency,
            amount_basis="gross",
            recurrence="once",
            payer=None,
            link_url=link,
            needed_by=data.needed_by,
            beneficiary_user_id=data.beneficiary_user_id,
            payout_year=data.payout_year,
            payout_month=data.payout_month,
            contract_basis=contract_basis,
        )
    return RequestInput(
        kind=data.kind,
        title=title,
        purpose=purpose,
        amount=amount,
        currency=data.currency,
        amount_basis=data.amount_basis,
        recurrence=data.recurrence,
        payer=data.payer,
        link_url=link,
        needed_by=data.needed_by,
        starts_on=data.starts_on,
        ends_on=data.ends_on,
        client_id=data.client_id,
        seller_nip=seller_nip,
    )


async def _assert_client(db: AsyncSession, client_id: Optional[int]) -> None:
    if client_id is None:
        return
    found = await db.scalar(
        select(Client.id).where(Client.id == client_id, Client.deleted_at.is_(None))
    )
    if found is None:
        raise ApprovalError("Nie ma takiego klienta.")


# ── kto decyduje ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Route:
    status: str
    supervisor_user_id: Optional[int]
    needs_final: bool


async def _supervisor_for_spend(
    db: AsyncSession, requester_id: int, finals: list[int]
) -> Optional[int]:
    """Przełożony autora wydatku albo ``None`` (bez kroku przełożonego)."""

    profile = await db.scalar(
        select(EmployeeProfile).where(EmployeeProfile.user_id == requester_id)
    )
    if profile is None:
        return None
    supervisor = await recipients.supervisor_of(db, profile)
    if supervisor.kind == "people_admin" or len(supervisor.user_ids) != 1:
        return None
    (supervisor_id,) = supervisor.user_ids
    if supervisor_id == requester_id or supervisor_id in finals:
        return None
    return supervisor_id


async def route(
    db: AsyncSession,
    data: RequestInput,
    *,
    requester_id: int,
    rules: ApprovalRules,
    finals: list[int],
) -> Route:
    if data.kind == "bonus":
        return Route("pending_final", None, True)
    supervisor_id = await _supervisor_for_spend(db, requester_id, finals)
    within = approval_rules.within_supervisor_limit(
        rules,
        data.kind,
        data.amount,
        currency=data.currency,
        amount_basis=data.amount_basis,
        recurrence=data.recurrence,
    )
    if supervisor_id is None:
        return Route("pending_final", None, True)
    return Route("pending_supervisor", supervisor_id, not within)


def _parties(request: ApprovalRequest) -> set[int]:
    return {
        uid
        for uid in (request.requester_user_id, request.beneficiary_user_id)
        if uid is not None
    }


def can_decide(user_id: int, request: ApprovalRequest, finals: list[int]) -> bool:
    if user_id in _parties(request):
        return False
    if request.status == "pending_supervisor":
        return user_id == request.supervisor_user_id or user_id in finals
    if request.status == "pending_final":
        return user_id in finals
    return False


def deciders_now(request: ApprovalRequest, finals: list[int]) -> list[int]:
    """Kto dostaje dzwonek „zgoda do decyzji” na tym etapie."""

    if request.status == "pending_supervisor" and request.supervisor_user_id:
        targets = [request.supervisor_user_id]
    elif request.status == "pending_final":
        targets = list(finals)
    else:
        targets = []
    parties = _parties(request)
    return [uid for uid in targets if uid not in parties]


async def _finals_for(
    db: AsyncSession, rules: ApprovalRules, request_parties: set[int]
) -> list[int]:
    """Zatwierdzający bez stron sprawy; gdy zatwierdzający jest stroną — admini."""

    finals = [
        uid
        for uid in await approval_rules.final_approver_ids(db, rules)
        if uid not in request_parties
    ]
    if finals:
        return finals
    return [uid for uid in await recipients.admin_ids(db) if uid not in request_parties]


async def finals_for_request(db: AsyncSession, request: ApprovalRequest) -> list[int]:
    rules = await approval_rules.load_rules(db)
    return await _finals_for(db, rules, _parties(request))


async def can_view(db: AsyncSession, user: User, request: ApprovalRequest) -> bool:
    """Autor, przełożony z kroku, popierający, decydujący, zatwierdzający, admin.

    Osoba z premii widzi premię w Płacach dopiero po zatwierdzeniu — samej
    prośby nie (prośba może zostać odrzucona).
    """

    if user.has_role(UserRole.admin):
        return True
    if user.id in {
        request.requester_user_id,
        request.supervisor_user_id,
        request.endorsed_by,
        request.decided_by,
    }:
        return True
    return user.id in await finals_for_request(db, request)


# ── zapis ────────────────────────────────────────────────────────────────


async def _assert_bonus_allowed(
    db: AsyncSession, actor: User, data: RequestInput
) -> None:
    if data.beneficiary_user_id == actor.id:
        raise ApprovalForbidden("O wynagrodzenie dodatkowe dla siebie nie prosisz.")
    viewer = await payroll_access.load_viewer(db, actor)
    if not viewer.manages_bonuses_of(data.beneficiary_user_id or 0):
        raise ApprovalForbidden(
            "O wynagrodzenie dodatkowe prosi koordynator tej osoby albo Płace."
        )
    profile = (
        await db.execute(
            select(
                EmployeeProfile.employment_type,
                EmployeeProfile.employment_type_pending,
            ).where(EmployeeProfile.user_id == data.beneficiary_user_id)
        )
    ).first()
    if profile is None:
        raise ApprovalNotFound("Ta osoba nie ma kartoteki pracownika.")
    if data.contract_basis is None and needs_contract_basis(
        profile.employment_type, bool(profile.employment_type_pending)
    ):
        raise ApprovalError(
            "Ta osoba współpracuje na B2B — podaj podstawę w umowie: "
            "punkt umowy albo numer aneksu, który przewiduje to wynagrodzenie."
        )
    await _assert_payout_open(db, data.payout_year, data.payout_month)


async def _assert_payout_open(
    db: AsyncSession, year: Optional[int], month: Optional[int]
) -> None:
    if year is None or month is None:
        return
    try:
        await payroll_periods.assert_open(db, year, month)
    except PayrollConflict as exc:
        raise ApprovalConflict(f"{exc.message} Wybierz inny miesiąc wypłaty.") from exc


def _apply(request: ApprovalRequest, data: RequestInput) -> None:
    for field_name in (
        "kind",
        "title",
        "purpose",
        "amount",
        "currency",
        "amount_basis",
        "recurrence",
        "payer",
        "link_url",
        "needed_by",
        "starts_on",
        "ends_on",
        "beneficiary_user_id",
        "payout_year",
        "payout_month",
        "client_id",
        "seller_nip",
        "contract_basis",
    ):
        setattr(request, field_name, getattr(data, field_name))


def _audit(
    db: AsyncSession,
    request: ApprovalRequest,
    *,
    actor_id: int,
    action: str,
    **extra: Any,
) -> None:
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=request.beneficiary_user_id or request.requester_user_id,
        entity_type="approval_request",
        entity_id=request.id,
        action=action,
        sensitivity="payroll" if request.kind == "bonus" else "general",
        details={
            "kind": request.kind,
            "status": request.status,
            "amount": str(request.amount),
            "currency": request.currency,
            **extra,
        },
    )


async def _route_and_notify(
    db: AsyncSession, request: ApprovalRequest, data: RequestInput, actor: User
) -> None:
    rules = await approval_rules.load_rules(db)
    finals = await _finals_for(
        db,
        rules,
        {actor.id, *([data.beneficiary_user_id] if data.beneficiary_user_id else [])},
    )
    if not finals:
        raise ApprovalConflict(
            "Nikt nie może zatwierdzić tej zgody — admin ustawia zatwierdzającego "
            "w Ustawieniach."
        )
    planned = await route(db, data, requester_id=actor.id, rules=rules, finals=finals)
    request.status = planned.status
    request.supervisor_user_id = planned.supervisor_user_id
    request.needs_final = planned.needs_final
    await db.flush()
    await _notify_deciders(db, request, finals, requester_name=actor.name)


async def submit(
    db: AsyncSession, actor: User, data: RequestInput, *, today: date
) -> ApprovalRequest:
    data = clean_input(data, today=today)
    if data.kind == "bonus":
        await _assert_bonus_allowed(db, actor, data)
    await _assert_client(db, data.client_id)
    request = ApprovalRequest(requester_user_id=actor.id, status="pending_final")
    _apply(request, data)
    db.add(request)
    await db.flush()
    await _route_and_notify(db, request, data, actor)
    _audit(db, request, actor_id=actor.id, action="approval_submitted")
    return request


async def _locked(db: AsyncSession, request_id: int) -> ApprovalRequest:
    request = await db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if request is None:
        raise ApprovalNotFound(NOT_FOUND)
    return request


async def resubmit(
    db: AsyncSession, actor: User, request_id: int, data: RequestInput, *, today: date
) -> ApprovalRequest:
    """Poprawka zgody zwróconej z pytaniem (albo jeszcze nierozpatrzonej) — od nowa."""

    request = await _locked(db, request_id)
    if request.requester_user_id != actor.id:
        if await can_view(db, actor, request):
            raise ApprovalForbidden("Zgodę poprawia jej autor.")
        raise ApprovalNotFound(NOT_FOUND)
    if request.status not in ("returned", *PENDING_STATUSES):
        raise ApprovalConflict("Ta zgoda jest już rozpatrzona — złóż nową.")
    data = clean_input(data, today=today)
    if data.kind == "bonus":
        await _assert_bonus_allowed(db, actor, data)
    await _assert_client(db, data.client_id)
    _apply(request, data)
    # Poparcie i pytanie dotyczyły starej treści — droga zaczyna się od nowa.
    # Stan przed czyszczeniem decyzji: autoflush przy odczycie zasad zapisałby
    # inaczej „returned” bez decydującego (CHECK ``ck_approval_requests_decided``).
    request.status = "pending_final"
    request.endorsed_by = None
    request.endorsed_at = None
    request.endorse_note = None
    request.decided_by = None
    request.decided_at = None
    request.decided_amount = None
    request.decision_note = None
    request.decision_channel = None
    request.submitted_at = local_now()
    await _route_and_notify(db, request, data, actor)
    _audit(db, request, actor_id=actor.id, action="approval_resubmitted")
    return request


async def withdraw(db: AsyncSession, actor: User, request_id: int) -> ApprovalRequest:
    request = await _locked(db, request_id)
    if request.requester_user_id != actor.id:
        if await can_view(db, actor, request):
            raise ApprovalForbidden("Zgodę wycofuje jej autor.")
        raise ApprovalNotFound(NOT_FOUND)
    if request.status not in ("returned", *PENDING_STATUSES):
        raise ApprovalConflict("Rozpatrzonej zgody nie wycofasz.")
    request.status = "withdrawn"
    await db.flush()
    _audit(db, request, actor_id=actor.id, action="approval_withdrawn")
    return request


def _clean_note(note: Optional[str], *, required: bool) -> Optional[str]:
    cleaned = (note or "").strip()
    if required and not cleaned:
        raise ApprovalError("Napisz jedno zdanie — trafi do autora zgody.")
    if len(cleaned) > NOTE_MAX_LENGTH:
        raise ApprovalError(f"Uwaga: najwyżej {NOTE_MAX_LENGTH} znaków.")
    return cleaned or None


async def decide(
    db: AsyncSession,
    actor: User,
    request_id: int,
    *,
    action: str,
    amount: Optional[Decimal] = None,
    note: Optional[str] = None,
    channel: str = "app",
) -> ApprovalRequest:
    """„Zatwierdź” / „Odrzuć” / „Dopytaj”.

    Przełożony ponad próg zamiast zatwierdzenia popiera (zgoda idzie do
    zatwierdzającego). Inną kwotę ustala tylko decyzja, która zamyka sprawę.
    """

    if action not in DECISIONS:
        raise ApprovalError("Nieznana decyzja.")
    request = await _locked(db, request_id)
    finals = await finals_for_request(db, request)
    if not can_decide(actor.id, request, finals):
        if request.status not in PENDING_STATUSES:
            raise ApprovalConflict("Ta zgoda jest już rozpatrzona.")
        if actor.id in _parties(request):
            raise ApprovalForbidden("We własnej sprawie nie decydujesz.")
        if await can_view(db, actor, request):
            raise ApprovalForbidden("Na tym etapie decyduje ktoś inny.")
        raise ApprovalNotFound(NOT_FOUND)
    note = _clean_note(note, required=action in ("reject", "return"))
    is_final = actor.id in finals
    now = local_now()

    if action == "approve" and not is_final and request.needs_final:
        if amount is not None and clean_amount(amount) != request.amount:
            raise ApprovalError(
                "Inną kwotę ustala zatwierdzający — popierasz wniosek tak, jak jest."
            )
        moved = await _conditional_update(
            db,
            request,
            from_status="pending_supervisor",
            status="pending_final",
            endorsed_by=actor.id,
            endorsed_at=now,
            endorse_note=note,
        )
        _audit(db, moved, actor_id=actor.id, action="approval_endorsed")
        await _notify_deciders(
            db, moved, finals, requester_name=await _name(db, moved.requester_user_id)
        )
        return moved

    decided_amount: Optional[Decimal] = None
    if action == "approve" and amount is not None:
        decided_amount = (
            clean_bonus_amount(amount)
            if request.kind == "bonus"
            else clean_amount(amount)
        )
        if decided_amount == request.amount:
            decided_amount = None
        elif not is_final:
            rules = await approval_rules.load_rules(db)
            if not approval_rules.within_supervisor_limit(
                rules,
                request.kind,
                decided_amount,
                currency=request.currency,
                amount_basis=request.amount_basis,
                recurrence=request.recurrence,
            ):
                raise ApprovalError(
                    "Ta kwota jest ponad Twój próg — zdecyduje zatwierdzający."
                )
    status = {"approve": "approved", "reject": "rejected", "return": "returned"}[action]
    moved = await _conditional_update(
        db,
        request,
        from_status=request.status,
        status=status,
        decided_by=actor.id,
        decided_at=now,
        decided_amount=decided_amount,
        decision_note=note,
        decision_channel=channel,
    )
    if status == "approved" and moved.kind == "bonus":
        await _create_bonus(db, moved, actor)
    elif status == "approved":
        # Etap 3: rozliczenie w Finansach, prezent → Historia klienta,
        # delegacja → obecność (import w funkcji: settlement importuje ten moduł).
        from app.services.hr.approvals import settlement  # noqa: PLC0415

        await settlement.on_approved(db, moved, actor)
    _audit(db, moved, actor_id=actor.id, action=f"approval_{status}", channel=channel)
    await _notify_requester(db, moved, actor)
    return moved


async def _conditional_update(
    db: AsyncSession, request: ApprovalRequest, *, from_status: str, **values: Any
) -> ApprovalRequest:
    result = await db.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.id == request.id, ApprovalRequest.status == from_status)
        .values(**values, updated_at=func.now())
        .returning(ApprovalRequest.id)
    )
    if result.scalar_one_or_none() is None:
        raise ApprovalConflict("Ktoś właśnie zdecydował o tej zgodzie — odśwież widok.")
    await db.refresh(request)
    return request


def bonus_description(
    contract_basis: Optional[str], employment_type: Optional[str] = None
) -> str:
    """Opis przyznanej premii w Płacach i w „Moim czasie” osoby — z podstawą
    w umowie, jeśli jest (osoba widzi punkt własnej umowy). Słowo z formy:
    „Premia poza umową” przy UoP, „Wynagrodzenie dodatkowe” przy B2B
    i zleceniu (decyzja Artura 21.10.2026)."""

    text = terms(employment_type)["bonus_extra_description"]
    if contract_basis:
        return f"{text} · podstawa: {contract_basis}"
    return text


async def _create_bonus(
    db: AsyncSession, request: ApprovalRequest, actor: User
) -> None:
    """Przyznana premia w Płacach z zatwierdzonej zgody (bez drugiej akceptacji)."""

    await _assert_payout_open(db, request.payout_year, request.payout_month)
    amount = request.decided_amount or request.amount
    form = await db.scalar(
        select(EmployeeProfile.employment_type).where(
            EmployeeProfile.user_id == request.beneficiary_user_id
        )
    )
    words = terms(form)
    bonus = HrBonus(
        recipient_user_id=request.beneficiary_user_id,
        proposed_by=request.requester_user_id,
        amount=amount,
        currency=request.currency,
        category="custom",
        period_year=request.payout_year,
        period_month=request.payout_month,
        status="assigned",
        source="manual",
        # Stały opis (plus podstawa w umowie): osoba z premii widzi go w „Moim
        # czasie”, a treść prośby (tytuł, „po co”) zostaje przy zgodzie. Słowo
        # z formy osoby: na B2B i zleceniu bez „premii poza umową” (21.10.2026).
        description=bonus_description(request.contract_basis, form),
        assigned_by=actor.id,
        assigned_at=local_now(),
        rule_snapshot={
            "approval_request_id": request.id,
            **(
                {"contract_basis": request.contract_basis}
                if request.contract_basis
                else {}
            ),
        },
    )
    db.add(bonus)
    await db.flush()
    request.bonus_id = bonus.id
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=bonus.recipient_user_id,
        entity_type="hr_bonus",
        entity_id=bonus.id,
        action="bonus_assigned",
        sensitivity="payroll",
        details={
            "amount": str(bonus.amount),
            "currency": bonus.currency,
            "category": bonus.category,
            "period": f"{bonus.period_year}-{bonus.period_month:02d}",
            "source": bonus.source,
            "status": bonus.status,
            "approval_request_id": request.id,
        },
    )
    await notify_each(
        db,
        [bonus.recipient_user_id],
        title=words["bonus_new_title"],
        message=bonus_message(form, label(bonus.period_year, bonus.period_month)),
        ntype=NotificationType.hr_bonus_assigned,
        link="/my-time?tab=bonuses",
        related_entity_type="hr_bonus",
        related_entity_id=bonus.id,
        log_tag="approvals",
    )


# ── powiadomienia ────────────────────────────────────────────────────────


def money(amount: Decimal, currency: str) -> str:
    whole, _, cents = f"{amount:,.2f}".partition(".")
    text = whole.replace(",", " ")
    if cents != "00":
        text += f",{cents}"
    return f"{text} {'zł' if currency == 'PLN' else currency}"


def amount_text(request: ApprovalRequest) -> str:
    value = money(request.decided_amount or request.amount, request.currency)
    basis = "netto" if request.amount_basis == "net" else "brutto"
    period = {"monthly": " / mies.", "yearly": " / rok"}.get(request.recurrence, "")
    return f"{value} {basis}{period}"


def request_link(request_id: int) -> str:
    """Zgoda w skrzynce decydującego („Ludzie → Akceptacje → Zgody”)."""

    return f"/people/approvals?tab=consents&request={request_id}"


def my_request_link(request_id: int) -> str:
    """Zgoda autora w „Mój czas → Zgody i wydatki” (od 22.10.2026; stary
    ``/people/consents`` przekierowuje tam)."""

    return f"/my-time?tab=consents&request={request_id}"


async def _name(db: AsyncSession, user_id: Optional[int]) -> str:
    if user_id is None:
        return ""
    return (await db.scalar(select(User.name).where(User.id == user_id))) or ""


async def _notify_deciders(
    db: AsyncSession,
    request: ApprovalRequest,
    finals: list[int],
    *,
    requester_name: str,
) -> None:
    subject = KIND_LABELS[request.kind]
    if request.kind == "bonus":
        subject = f"{subject} — {await _name(db, request.beneficiary_user_id)}"
    await notify_each(
        db,
        deciders_now(request, finals),
        title=f"Zgoda do decyzji: {subject}",
        message=f"{requester_name} · {request.title} · {amount_text(request)}",
        ntype=NotificationType.hr_approval_requested,
        link=request_link(request.id),
        related_entity_type="approval_request",
        related_entity_id=request.id,
        log_tag="approvals",
    )


_DECISION_TITLES = {
    "approved": "Zgoda zatwierdzona",
    "rejected": "Zgoda odrzucona",
    "returned": "Pytanie do Twojej zgody",
}


async def _notify_requester(
    db: AsyncSession, request: ApprovalRequest, actor: User
) -> None:
    message = (
        f"{actor.name}: {request.decision_note}"
        if request.decision_note
        else actor.name
    )
    await notify_each(
        db,
        [request.requester_user_id],
        title=f"{_DECISION_TITLES[request.status]}: {request.title}",
        message=message,
        ntype=NotificationType.hr_approval_decided,
        link=my_request_link(request.id),
        related_entity_type="approval_request",
        related_entity_id=request.id,
        log_tag="approvals",
    )


# ── odczyty ──────────────────────────────────────────────────────────────


async def inbox(db: AsyncSession, user: User) -> list[ApprovalRequest]:
    """Zgody, o których ta osoba może teraz zdecydować (najstarsze pierwsze)."""

    rules = await approval_rules.load_rules(db)
    finals_all = await approval_rules.final_approver_ids(db, rules)
    admins = set(await recipients.admin_ids(db))
    clauses = [
        (ApprovalRequest.status == "pending_supervisor")
        & (ApprovalRequest.supervisor_user_id == user.id)
    ]
    # Zatwierdzający (albo admin, gdy zatwierdzający jest stroną sprawy) widzi
    # oba etapy; odsiew stron sprawy niżej, regułą ``can_decide``.
    if user.id in finals_all or user.id in admins:
        clauses.append(ApprovalRequest.status.in_(PENDING_STATUSES))
    rows = list(
        await db.scalars(
            select(ApprovalRequest)
            .where(or_(*clauses))
            .order_by(
                ApprovalRequest.needed_by.asc().nulls_last(),
                ApprovalRequest.submitted_at,
            )
        )
    )
    visible: list[ApprovalRequest] = []
    for request in rows:
        finals = await _finals_for(db, rules, _parties(request))
        if can_decide(user.id, request, finals):
            visible.append(request)
    return visible


async def pending_count(db: AsyncSession, user: User) -> int:
    """Zgody do decyzji i dopłaty do decyzji (etap 3) — licznik ikony i zakładki."""

    from app.services.hr.approvals import settlement  # noqa: PLC0415

    return len(await inbox(db, user)) + len(await settlement.pending_topups(db, user))


async def mine(db: AsyncSession, user: User) -> list[ApprovalRequest]:
    return list(
        await db.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.requester_user_id == user.id)
            .order_by(ApprovalRequest.submitted_at.desc())
            .limit(200)
        )
    )


async def history(
    db: AsyncSession, user: User, *, limit: int = 100
) -> list[ApprovalRequest]:
    """Zgody, o których ta osoba zdecydowała albo które poparła."""

    return list(
        await db.scalars(
            select(ApprovalRequest)
            .where(
                or_(
                    ApprovalRequest.decided_by == user.id,
                    ApprovalRequest.endorsed_by == user.id,
                )
            )
            .order_by(ApprovalRequest.updated_at.desc())
            .limit(limit)
        )
    )


async def get_visible(db: AsyncSession, user: User, request_id: int) -> ApprovalRequest:
    request = await db.get(ApprovalRequest, request_id)
    if request is None or not await can_view(db, user, request):
        raise ApprovalNotFound(NOT_FOUND)
    return request


def _year_bounds(today: date) -> tuple[date, date]:
    return date(today.year, 1, 1), date(today.year + 1, 1, 1)


async def context_for(
    db: AsyncSession,
    request: ApprovalRequest,
    *,
    today: date,
    include_bonuses: bool,
) -> dict[str, Any]:
    """„NEXUS sprawdził” — liczby obok decyzji (tylko PLN, bez innych walut)."""

    month_start = date(today.year, today.month, 1)
    next_month = date(*add_months(today.year, today.month, 1), 1)
    year_start, year_end = _year_bounds(today)
    approved_value = func.coalesce(
        ApprovalRequest.decided_amount, ApprovalRequest.amount
    )

    async def approved_sum(
        start: date,
        end: date,
        *,
        kind: Optional[str] = None,
        exclude_bonuses: bool = False,
    ) -> dict[str, Any]:
        stmt = select(
            func.count(ApprovalRequest.id), func.coalesce(func.sum(approved_value), 0)
        ).where(
            ApprovalRequest.status == "approved",
            ApprovalRequest.currency == "PLN",
            # Północ w strefie firmy, jak Finanse — goła data to północ UTC.
            ApprovalRequest.decided_at >= local_day_start_utc(start),
            ApprovalRequest.decided_at < local_day_start_utc(end),
        )
        if kind is not None:
            stmt = stmt.where(ApprovalRequest.kind == kind)
        if exclude_bonuses:
            stmt = stmt.where(ApprovalRequest.kind != "bonus")
        count, total = (await db.execute(stmt)).one()
        return {"count": int(count), "amount": str(Decimal(total).quantize(_CENT))}

    context: dict[str, Any] = {
        "kind_month": await approved_sum(month_start, next_month, kind=request.kind),
        "kind_year": await approved_sum(year_start, year_end, kind=request.kind),
        # Premie poza umową to kwoty płacowe — w sumie firmy tylko dla
        # zatwierdzającego; przełożony od wydatków widzi same wydatki.
        "all_month": await approved_sum(
            month_start, next_month, exclude_bonuses=not include_bonuses
        ),
    }
    if request.kind == "bonus" and request.beneficiary_user_id is not None:
        rows = await db.execute(
            select(
                HrBonus.source,
                HrBonus.rule_snapshot,
                HrBonus.amount,
                HrBonus.period_year,
                HrBonus.period_month,
            ).where(
                HrBonus.recipient_user_id == request.beneficiary_user_id,
                HrBonus.status == "assigned",
                HrBonus.currency == "PLN",
                HrBonus.period_year == today.year,
            )
        )
        automatic = Decimal(0)
        outside = Decimal(0)
        manual = Decimal(0)
        same_month_automatic = Decimal(0)
        for source, snapshot, amount, year, month in rows.all():
            if source in AUTOMATED_SOURCES:
                automatic += amount
                if (year, month) == (request.payout_year, request.payout_month):
                    same_month_automatic += amount
            elif (snapshot or {}).get("approval_request_id"):
                outside += amount
            else:
                manual += amount
        context["beneficiary_year"] = {
            "automatic": str(automatic.quantize(_CENT)),
            "outside_contract": str(outside.quantize(_CENT)),
            "manual": str(manual.quantize(_CENT)),
            "same_month_automatic": str(same_month_automatic.quantize(_CENT)),
        }
    return context


__all__ = [
    "DECISIONS",
    "KIND_LABELS",
    "ApprovalConflict",
    "ApprovalError",
    "ApprovalForbidden",
    "ApprovalNotFound",
    "RequestInput",
    "Route",
    "amount_text",
    "can_decide",
    "can_view",
    "clean_input",
    "context_for",
    "decide",
    "deciders_now",
    "finals_for_request",
    "get_visible",
    "history",
    "inbox",
    "mine",
    "my_request_link",
    "pending_count",
    "request_link",
    "resubmit",
    "route",
    "submit",
    "withdraw",
]
