"""Faktura kontraktora w kolejce „Koszty” a rozliczenie jego miesiąca (22.11.2026).

Wstępna weryfikacja faktur kontraktorów (prośba księgowej z 18.11.2026) polega
na sprawdzeniu, czy faktura zgadza się z rozliczeniem miesiąca: RCP przyjęte,
kwota równa wyliczeniu z RCP, zapłata dozwolona. Nic nie liczymy od nowa —
to są te same kontrole co karta osoby w „Rozliczeniach” klienta
(``client_settlements/contractor_invoices.card``: kwota z tolerancją reguły
``ci.amount``, korekty, NIP nabywcy, biała lista, termin) i bramka zapłaty
(``service.payment``, ta sama co w planie przelewów — ``payments._client_gates``).

Rozliczenie = kontrakt i ``period_month`` faktury, rodzaj ``actual``. Faktura bez
kontraktu albo miesiąca (np. dokument wydatku przeniesiony do „Kontraktorów”)
nie ma z czym się porównać — mówimy to wprost, zamiast pokazywać „zgodna”.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_settlement import ClientContractorInvoice, ClientSettlement
from app.models.finance_ledger import FinanceCostEntry
from app.services.client_settlements import contractor_invoices
from app.services.client_settlements import service as settlement_service
from app.services.finance_ledger import journals

RCP_LABELS = {
    "accepted": "RCP przyjęte",
    "needs_fix": "RCP do poprawy",
    "no_md": "RCP bez MD",
}
#: Stan porównania → etykieta (krótka, do kolejki).
STATE_LABELS = {
    "match": "Zgodna z rozliczeniem",
    "differs": "Inna kwota niż wyliczenie z RCP",
    "waiting": "Rozliczenie bez kwoty — RCP nieprzyjęte",
    "unchecked": "Kwoty nie porównujemy (reguła klienta wyłączona)",
    "nip_check": "NIP kontraktora do zatwierdzenia",
    "nip_rejected": "NIP odrzucony — faktura nie należy do kontraktu",
    "missing": "Brak rozliczenia miesiąca w NEXUSIE",
    "no_contract": "Bez kontraktu i miesiąca — porównaj z RCP ręcznie",
}
STATE_TONES = {
    "match": "ok",
    "differs": "fail",
    "waiting": "warn",
    "unchecked": "none",
    "nip_check": "warn",
    "nip_rejected": "warn",
    "missing": "warn",
    "no_contract": "none",
}


def _rcp_label(settlement: ClientSettlement) -> str:
    return RCP_LABELS.get(settlement.status, "RCP w sprawdzaniu")


def summarize(
    settlement: Optional[ClientSettlement],
    invoices: list[ClientContractorInvoice],
    rules: dict[str, dict[str, Any]],
) -> str:
    """Stan porównania faktury (i jej korekt z tego miesiąca) z rozliczeniem."""

    if settlement is None:
        return "missing"
    state = contractor_invoices.state(settlement, invoices, rules)
    if state == contractor_invoices.NIP_CHECK:
        return "nip_check"
    if state == contractor_invoices.DIFFERS:
        return "differs"
    if settlement.amount_cost is None:
        return "waiting"
    if rules["ci.amount"]["level"] == "off":
        return "unchecked"
    if state == contractor_invoices.IN_KSEF:
        return "match"
    return "waiting"


def _payload(state: str, **extra: Any) -> dict[str, Any]:
    return {
        "state": state,
        "label": STATE_LABELS[state],
        "tone": STATE_TONES[state],
        **extra,
    }


async def for_entries(
    db: AsyncSession, entries: Iterable[FinanceCostEntry], *, detail: bool = False
) -> dict[int, dict[str, Any]]:
    """Porównanie z rozliczeniem dla faktur z dziennika „Kontraktorzy”.

    Faktury osób zespołu pomijamy (ich rozliczenie to Płace — „Kogo dotyczy”).
    ``detail`` = karta: miesiąc, stan RCP, kontrole z karty osoby i zapłata.
    """

    chosen = [
        entry
        for entry in entries
        if journals.journal_of(entry.category) == "contractors"
        and entry.source_type != "payroll_invoice"
    ]
    if not chosen:
        return {}
    ids = [e.source_id for e in chosen if e.source_type == "contractor_invoice"]
    invoices = {
        invoice.id: invoice
        for invoice in (
            await db.scalars(
                select(ClientContractorInvoice).where(
                    ClientContractorInvoice.id.in_(ids or [0])
                )
            )
        )
    }
    keys = {
        (invoice.contract_id, invoice.period_month)
        for invoice in invoices.values()
        if invoice.contract_id is not None and invoice.period_month
    }
    settlements: dict[tuple[int, str], ClientSettlement] = {}
    month_invoices: dict[tuple[int, str], list[ClientContractorInvoice]] = {}
    if keys:
        for s in await db.scalars(
            select(ClientSettlement).where(
                ClientSettlement.kind == "actual",
                ClientSettlement.contract_id.in_({c for c, _ in keys}),
                ClientSettlement.period_month.in_({m for _, m in keys}),
            )
        ):
            settlements[(s.contract_id, s.period_month)] = s
        for month in {m for _, m in keys}:
            by_contract = await contractor_invoices.for_month(
                db, [c for c, m in keys if m == month], month
            )
            for contract_id, rows in by_contract.items():
                month_invoices[(contract_id, month)] = rows
    rule_sets: dict[tuple[int, str], dict[str, dict[str, Any]]] = {}
    result: dict[int, dict[str, Any]] = {}
    for entry in chosen:
        invoice = (
            invoices.get(entry.source_id)
            if entry.source_type == ("contractor_invoice")
            else None
        )
        if invoice is None or invoice.contract_id is None or not invoice.period_month:
            result[entry.id] = _payload("no_contract")
            continue
        # Porównanie miesiąca liczy faktury przypięte do kontraktu; własna
        # faktura z NIP-em odrzuconym albo do zatwierdzenia nie jest jego
        # częścią, więc nie dostaje „zgodnej” od innej faktury tego miesiąca.
        if invoice.nip_state == contractor_invoices.REJECTED:
            result[entry.id] = _payload("nip_rejected")
            continue
        if invoice.nip_state not in contractor_invoices.BOUND:
            result[entry.id] = _payload("nip_check")
            continue
        key = (invoice.contract_id, invoice.period_month)
        settlement = settlements.get(key)
        rows = month_invoices.get(key) or [invoice]
        month = f"{invoice.period_month[5:7]}.{invoice.period_month[:4]}"
        if settlement is None:
            result[entry.id] = _payload("missing", month=month)
            continue
        rule_key = (settlement.client_id, invoice.period_month)
        if rule_key not in rule_sets:
            rule_sets[rule_key] = await settlement_service.rules_for(
                db, settlement.client_id, invoice.period_month
            )
        rules = rule_sets[rule_key]
        payload = _payload(
            summarize(settlement, rows, rules),
            month=month,
            rcp=_rcp_label(settlement),
        )
        if detail:
            block = contractor_invoices.card(settlement, rows, rules, amounts=True)
            payload.update(
                settlement_id=settlement.id,
                client_id=settlement.client_id,
                amount_cost=(
                    f"{settlement.amount_cost:.2f}"
                    if settlement.amount_cost is not None
                    else None
                ),
                invoices=block["invoices"],
                checks=block["checks"],
                payment=settlement_service.payment(settlement, rules),
            )
        result[entry.id] = payload
    return result
