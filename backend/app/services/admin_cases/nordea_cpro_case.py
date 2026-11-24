"""Sprawa z powiadomienia CPro Nordei: zadanie dla Finansów albo przedłużenie do decyzji.

Czytnik spraw woła ``apply_to_new_case`` dla każdej nowej sprawy z maila. Koniec,
nieprzedłużenie i internalizacja idą jak dotąd propozycją „Klient kończy”
(``notice_mail``), a ich potwierdzenie otwiera sprawę wyjścia. Tu zostają dwa
pozostałe wzorce:

* „Important changes made to contract” ze zmianą danych do faktury → sprawa
  Rozliczeń z wartością „od dnia” i checklistą dla Finansów. Zmiana adresu faktury
  to zmiana nabywcy (priorytet P1): 15.09.2026 przeszła z Abp S.A. na Abp Finland
  i nikt jej nie przekazał, a w 2025 taka sama pomyłka skończyła się notami
  i refakturami. Nabywcę od miesiąca ustawia się w „Nabywcy per kontrakt”
  (``client_invoicing/issue_settings``, historia od miesiąca usługi).
* przedłużenie do decyzji w CPro → tytuł z numerem CoA i terminem decyzji.

Automat zmienia tylko samą sprawę z maila (tytuł, obszar, priorytet, opis,
checklistę). Nie przypina kontraktu, nie zmienia nabywcy ani zamówienia: kontrakt
z numeru CPro podaje w opisie, a decyzję podejmuje człowiek.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date, business_today
from app.models.admin_case import AdminCase, AdminCaseMessage
from app.services.admin_cases import nordea_cpro as cpro
from app.services.admin_cases import rules

TITLE_PREFIX = "Nordea CPro: "
FINANCE_BUYER_ITEM = "Finanse: nabywca od "
FINANCE_INVOICES_ITEM = "Finanse: faktury za "
FINANCE_REFERENCES_ITEM = "Finanse: nowe dane do faktury od "
PROLONGATION_ITEM = "Decyzja Tak/Nie w CPro najpóźniej 5 tygodni przed końcem CoA"


@dataclass(frozen=True)
class CasePlan:
    title: str
    area: str
    priority: str
    description: str
    checklist: tuple[dict[str, Any], ...] = ()


def _contract_line(cpro_number: Optional[str], contract_ids: list[int]) -> str:
    if not cpro_number:
        return "Mail nie ma numeru CoA — kontrakt wskaż w sprawie („Kogo dotyczy?”)."
    if len(contract_ids) == 1:
        return f"Linia zamówienia z numerem CPro {cpro_number}: kontrakt #{contract_ids[0]}."
    if contract_ids:
        listed = ", ".join(f"#{cid}" for cid in contract_ids[:5])
        return (
            f"Numer CPro {cpro_number} mają linie zamówień kilku kontraktów: {listed}."
        )
    return (
        f"Żadna linia zamówienia nie ma numeru CPro {cpro_number} w tytule — "
        "kontrakt wskaż w sprawie („Kogo dotyczy?”)."
    )


def case_plan(
    event: cpro.CproEvent,
    *,
    received_on: date,
    contract_ids: list[int],
) -> Optional[CasePlan]:
    """Co zmienić w sprawie z maila CPro; ``None`` = sprawa zostaje, jak jest."""

    number = event.cpro_number
    coa = f" · CoA {number}" if number else ""
    where = _contract_line(number, contract_ids)
    if event.kind == cpro.CHANGES and event.invoice_reference_changes:
        since = event.effective_from or received_on
        party = event.invoice_party_changed
        lines = [
            f"Zmiana w CPro od {since:%d.%m.%Y}"
            + ("" if event.effective_from else " (data powiadomienia)")
            + ":"
        ]
        lines += [
            f"- {cpro.FIELD_LABELS[change.key]}: {change.old or '—'} → {change.new or '—'}"
            for change in event.invoice_reference_changes
        ]
        lines.append(where)
        month = f"{since:%m.%Y}"
        if party:
            checklist = (
                {
                    "text": f"{FINANCE_BUYER_ITEM}{since:%d.%m.%Y} w Ustawieniach "
                    f"wystawiania → „Nabywcy per kontrakt” (od miesiąca {month})",
                    "done": False,
                },
                {
                    "text": f"{FINANCE_INVOICES_ITEM}{month} i później: sprawdź "
                    "nabywcę; fakturę wysłaną na starego nabywcę skoryguj",
                    "done": False,
                },
            )
        else:
            fields = ", ".join(
                dict.fromkeys(
                    cpro.FIELD_LABELS[change.key]
                    for change in event.invoice_reference_changes
                )
            )
            checklist = (
                {
                    "text": f"{FINANCE_REFERENCES_ITEM}{since:%d.%m.%Y}: {fields}",
                    "done": False,
                },
            )
        topic = "zmiana nabywcy" if party else "dane do faktury"
        return CasePlan(
            title=f"{TITLE_PREFIX}{topic} od {since:%d.%m.%Y}{coa}"[: rules.TITLE_MAX],
            area=rules.SETTLEMENTS_AREA,
            priority="P1" if party else "P2",
            description="\n".join(lines),
            checklist=tuple(rules.normalize_checklist(checklist)),
        )
    if event.kind == cpro.PROLONGATION:
        if event.pending_extensions and not number:
            title = (
                f"{TITLE_PREFIX}przedłużenia do decyzji ({event.pending_extensions})"
            )
        else:
            title = f"{TITLE_PREFIX}przedłużenie do decyzji{coa}"
        lines = [
            "Nordea pyta o przedłużenie w CPro: decyzja Tak/Nie najpóźniej 5 tygodni"
            " przed końcem CoA. Przy obniżce do cennika umowy ramowej (FA) aneks"
            " zmienia koszt i przychód od tej samej daty.",
            where,
        ]
        return CasePlan(
            title=title[: rules.TITLE_MAX],
            area="negotiation",
            priority="P2",
            description="\n".join(lines),
            checklist=tuple(
                rules.normalize_checklist(({"text": PROLONGATION_ITEM, "done": False},))
            ),
        )
    return None


async def apply_to_new_case(
    db: AsyncSession, case: AdminCase, message: AdminCaseMessage
) -> Optional[str]:
    """Nowa sprawa z maila CPro dostaje tytuł, obszar i checklistę; zwraca rodzaj."""

    from app.services.admin_cases.notice_mail import orders_by_cpro  # noqa: PLC0415

    event = cpro.parse(message.subject, message.body_text, message.sender_email)
    if event is None or event.kind in cpro.EXIT_EVENTS:
        return None
    received_on = (
        business_date(message.received_at)
        if message.received_at is not None
        else business_today()
    )
    orders = await orders_by_cpro(db, event.cpro_number)
    plan = case_plan(
        event,
        received_on=received_on,
        contract_ids=sorted({cid for cid, _ in orders}),
    )
    if plan is None:
        return None
    now = datetime.now(timezone.utc)
    case.title = plan.title
    case.area = plan.area
    case.priority = plan.priority
    case.due_on = rules.due_date_for(plan.priority, message.received_at or now)
    case.description = plan.description
    case.checklist = [*(case.checklist or []), *plan.checklist]
    case.updated_at = now
    await db.flush()
    return event.kind
