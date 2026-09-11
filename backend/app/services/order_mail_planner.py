"""Pure order lifecycle plan, shared by ingestion, refresh and the writer.

Existing live orders take priority over drafts. A first order creates a draft,
any single existing draft is filled. A return after a gap creates a NEW order
next to the completed one — a completed order is never rewritten (decision of
2026-09-10): invoices were settled against it. A draft written from another
mail document for a disjoint period counts as a planned order, not an empty
draft (same number or overlapping period = its correction). Actual period
overlaps, ambiguous targets and revisions require review. On MD and cost
orders a person whose engagement ended, or who is not in the system, waits for
a human decision (``ACTION_DECIDE_PERSON``) instead of being revived or created.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
import re
from typing import Optional

from app.services.order_consultant_match import (
    inactive_consultant_reason,
    unknown_consultant_reason,
)
from app.services.order_mail_resolver import ResolvedConsultant
from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction

ACTION_FILL_DRAFT = "fill_draft"
ACTION_FUTURE = "future"
ACTION_NEW = "new"
ACTION_NEW_DRAFT = "new_draft"
#: Powrót po przerwie. Nazwa zostaje historyczna (utrwalone plany i etykiety
#: frontu), ale od 10.09.2026 znaczy „NOWE zamówienie na nowy okres, obok
#: zakończonego" — writer nie dotyka zakończonego zamówienia, więc akcja może
#: zostać automatyczna.
ACTION_REACTIVATE = "reactivate"
ACTION_UNCHANGED = "unchanged"
ACTION_REVISION = "revision"
ACTION_OVERLAP = "overlap"
ACTION_GROUP = "group"
ACTION_SKIP = "skip"
#: Zamówienie MD/kosztowe z osobą, której współpraca u klienta się zakończyła
#: albo której nie ma w systemie (ticket 09.2026, reguła ogólna dla wszystkich
#: klientów rozliczanych w MD lub budżetem). Automat NIE zgaduje: wznowienie
#: kontraktu, zapis historyczny, zastępstwo albo pominięcie osoby to decyzja
#: Delivery Leada. Podejmuje ją w oknie zamówienia (ten sam mechanizm co
#: „Nowe zamówienie" i „Uzupełnij zamówienie"), do którego kolejka prowadzi
#: z tym PDF-em.
ACTION_DECIDE_PERSON = "decide_person"
#: Typy zamówień, dla których osoba nieaktywna/nieznaleziona czeka na decyzję.
#: Zamówienie okresowe zostaje przy decyzji z 10.09.2026: powrót po przerwie
#: to nowe zamówienie, nowa osoba — szkic nowego kontraktora.
DECIDE_PERSON_ORDER_TYPES = frozenset({"md", "cost"})
AUTO_ACTIONS = frozenset(
    {
        ACTION_FILL_DRAFT,
        ACTION_FUTURE,
        ACTION_NEW,
        ACTION_NEW_DRAFT,
        ACTION_REACTIVATE,
        ACTION_UNCHANGED,
    }
)

PLACEHOLDER_TITLE = "(bez numeru)"


@dataclass(frozen=True)
class ExistingOrder:
    id: int
    status: str
    title: str
    start_date: Optional[date]
    end_date: Optional[date]
    order_group_id: Optional[int] = None
    has_file: bool = False
    rate_client: Optional[Decimal] = None
    rate_unit: Optional[str] = None
    #: Zamówienie zapisane już z dokumentu mailowego (Activity ``order_mail_*``).
    #: Jego szkic niesie TAMTO zamówienie, a nie pusty szkic z zatrudnienia.
    from_order_mail: bool = False


@dataclass
class RowProposal:
    row_index: int
    row_name: str
    action: str
    candidate_id: Optional[int] = None
    contract_id: Optional[int] = None
    target_order_id: Optional[int] = None
    title: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    rate_client: Optional[str] = None
    rate_unit: Optional[str] = None
    md_total: Optional[str] = None
    reasons: list[str] = field(default_factory=list)
    previous_end_date: Optional[str] = None
    order_type: str = "periodic"
    total_value: Optional[str] = None


@dataclass
class DocumentProposal:
    client_id: int
    order_number: Optional[str]
    is_group_client: bool
    rows: list[RowProposal]
    blocking: list[str] = field(default_factory=list)

    @property
    def auto_eligible_actions(self) -> bool:
        return bool(self.rows) and all(r.action in AUTO_ACTIONS for r in self.rows)


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _number_variants(title: Optional[str]) -> set[str]:
    """Numer pełny i jego krótkie formy (BIK: ``4500030751`` ↔ ``30751``)."""
    if not title:
        return set()
    t = title.strip()
    out = {t, t.lower()}
    digits = "".join(ch for ch in t if ch.isdigit())
    if len(digits) >= 5:
        out.add(digits)
        out.add(digits.lstrip("0"))
        out.add(digits[-5:])
    return {x for x in out if x}


def titles_collide(a: Optional[str], b: Optional[str]) -> bool:
    # PFRON's labelled title is the same identity as its historical bare number.
    # Strip only this explicit prefix; generic short digit extraction would
    # conflate unrelated order numbers such as ABC/22 and DEF/22.
    a = re.sub(r"^zlecenie\s+nr\.?\s+", "", (a or "").strip(), flags=re.I)
    b = re.sub(r"^zlecenie\s+nr\.?\s+", "", (b or "").strip(), flags=re.I)
    va, vb = _number_variants(a), _number_variants(b)
    if not va or not vb:
        return False
    if a and b and a.strip().lower() == b.strip().lower():
        return True
    da = "".join(ch for ch in (a or "") if ch.isdigit())
    db_ = "".join(ch for ch in (b or "") if ch.isdigit())
    if len(da) >= 5 and len(db_) >= 5 and (da.endswith(db_) or db_.endswith(da)):
        return True
    return False


def _overlaps(order: ExistingOrder, start: date, end: Optional[str]) -> bool:
    """Czy okres zamówienia nachodzi na okres z dokumentu (brak końca = bez końca)."""
    return (order.end_date is None or order.end_date >= start) and (
        end is None
        or order.start_date is None
        or order.start_date <= date.fromisoformat(end)
    )


def _is_draft_shell(
    order: ExistingOrder, number: Optional[str], start: date, end: Optional[str]
) -> bool:
    """Szkic do uzupełnienia — chyba że niesie już zamówienie na INNY okres.

    Dwa zamówienia tej samej osoby przychodzą osobnymi mailami (Alior: wrzesień
    i październik–grudzień). Póki kontrakt nie jest podpisany, szkic wypełniony
    pierwszym PDF-em nie staje się aktywnym zamówieniem — bez tego warunku drugi
    PDF „uzupełniał" go i po cichu nadpisywał numer i okres pierwszego. Szkic
    „niesie zamówienie", gdy zapisano go z maila albo ma dołączony PDF
    zamówienia. Ten sam numer albo nachodzący okres to ten sam dokument (albo
    jego korekta), więc uzupełnienie wolno; rozłączny okres to osobne zamówienie.
    Linia grupy zostaje przy dotychczasowej ścieżce (``ACTION_GROUP``): osobne
    zamówienie obok linii MD rozdwoiłoby współpracę.
    """
    if order.status != "draft":
        return False
    carries_order = order.from_order_mail or order.has_file
    if (
        order.order_group_id is not None
        or not carries_order
        or titles_collide(order.title, number)
    ):
        return True
    return _overlaps(order, start, end)


def _period_for_row(
    row: ConsultantOrderRow, extraction: OrderExtraction
) -> tuple[Optional[str], Optional[str]]:
    return (
        row.start_date or extraction.start_date,
        row.end_date or extraction.end_date,
    )


def _rate_for_row(
    row: ConsultantOrderRow, extraction: OrderExtraction
) -> tuple[Optional[Decimal], Optional[str], Optional[Decimal]]:
    rate = row.rate_client if row.rate_client is not None else extraction.rate_client
    unit = row.rate_unit or extraction.rate_unit
    md = row.md_total if row.md_total is not None else extraction.md_total
    return rate, unit, md


def _person_decision_reason(rp: RowProposal, res: ResolvedConsultant) -> Optional[str]:
    """Komunikat „nie ma już aktywnej współpracy / nie znaleziono" albo ``None``.

    Tylko dla zamówień MD i kosztowych. Tekst pochodzi z tego samego źródła co
    karta w oknie zamówienia (``order_consultant_match``), więc Delivery Lead
    widzi w kolejce dokładnie to zdanie, które zobaczy po otwarciu okna.
    """

    if rp.order_type not in DECIDE_PERSON_ORDER_TYPES:
        return None
    if res.match_kind == "none":
        return unknown_consultant_reason(rp.row_name)
    if res.is_unique_person and res.contract_status == "ended":
        ended_on = (
            date.fromisoformat(res.contract_end_date) if res.contract_end_date else None
        )
        return inactive_consultant_reason(rp.row_name, ended_on=ended_on)
    return None


def plan_document(
    *,
    client_id: int,
    extraction: OrderExtraction,
    resolved: list[ResolvedConsultant],
    existing_orders_by_contract: dict[int, list[ExistingOrder]],
    is_group_client: bool,
    today: date,
    order_type: Optional[str] = None,
) -> DocumentProposal:
    rows = extraction.consultant_rows
    proposal = DocumentProposal(
        client_id=client_id,
        order_number=extraction.title,
        is_group_client=is_group_client,
        rows=[],
    )
    if not rows:
        proposal.blocking.append("Dokument bez rozpoznanych osób")
        return proposal
    if not extraction.title:
        proposal.blocking.append("Brak numeru zamówienia")

    for row, res in zip(rows, resolved):
        start, end = _period_for_row(row, extraction)
        rate, unit, md = _rate_for_row(row, extraction)
        rp = RowProposal(
            row_index=res.row_index,
            row_name=row.consultant_name,
            action=ACTION_SKIP,
            candidate_id=res.candidate_id,
            contract_id=res.contract_id,
            title=extraction.title,
            start_date=start,
            end_date=end,
            rate_client=str(rate) if rate is not None else None,
            rate_unit=unit,
            md_total=str(md) if md is not None else None,
            order_type=order_type or ("md" if is_group_client else "periodic"),
            total_value=str(extraction.total_value)
            if extraction.total_value is not None
            else None,
        )
        decision = _person_decision_reason(rp, res)
        if decision is not None:
            rp.action = ACTION_DECIDE_PERSON
            rp.reasons.append(decision)
            proposal.rows.append(rp)
            continue
        if res.match_kind == "none":
            rp.action = ACTION_NEW_DRAFT
            proposal.rows.append(rp)
            continue
        if not res.is_unique_person or res.contract_id is None:
            rp.reasons.append(res.reason or "Nie ustalono osoby/kontraktu")
            proposal.rows.append(rp)
            continue
        if not start:
            rp.reasons.append("Brak daty początku okresu w dokumencie")
            proposal.rows.append(rp)
            continue

        existing = existing_orders_by_contract.get(res.contract_id, [])
        new_start = date.fromisoformat(start)
        # Punkt odniesienia powrotu to wyłącznie samodzielne zamówienie
        # (okresowe/kosztowe). Linia grupy MD ma własny cykl życia (budżet,
        # zamiana kontraktora, decyzja o MD po offboardingu) i nie jest
        # „poprzednim zamówieniem" osoby — writer i tak jej nie zmieni.
        completed_return = [
            o
            for o in existing
            if o.order_group_id is None
            and o.status == "completed"
            and o.end_date
            and o.end_date < new_start
        ]
        if completed_return and not any(
            o.status in ("active", "paused", "draft") for o in existing
        ):
            target = max(completed_return, key=lambda o: (o.end_date, o.id))
            rp.action = ACTION_REACTIVATE
            rp.target_order_id = target.id
            rp.previous_end_date = _iso(target.end_date)
            rp.reasons.append(
                f"Powrót po {(new_start - target.end_date).days} dniach od zakończenia poprzedniego zamówienia"
            )
            proposal.rows.append(rp)
            continue
        same_number = [
            o
            for o in existing
            if o.status != "draft" and titles_collide(o.title, extraction.title)
        ]
        if len(same_number) == 1:
            target = same_number[0]
            target_unit = {"hourly": "hour", "daily": "day", "monthly": "month"}.get(
                target.rate_unit, target.rate_unit
            )
            if (
                target.start_date,
                _iso(target.end_date),
                target.rate_client,
                target_unit,
            ) == (new_start, end, rate, unit):
                rp.action = ACTION_UNCHANGED
                rp.target_order_id = target.id
                proposal.rows.append(rp)
                continue
        if same_number:
            rp.action = ACTION_REVISION
            rp.target_order_id = same_number[0].id
            rp.reasons.append(
                f"Zamówienie o tym numerze już istnieje (#{same_number[0].id}, "
                f"{_iso(same_number[0].start_date) or '—'} – {_iso(same_number[0].end_date) or 'bezterminowo'}) — porównaj"
            )
            proposal.rows.append(rp)
            continue

        open_live = [o for o in existing if o.status in ("active", "paused")]
        shells = [
            o for o in existing if _is_draft_shell(o, extraction.title, new_start, end)
        ]
        # Szkic z innego PDF-a na rozłączny okres to zaplanowane zamówienie:
        # liczy się jak otwarte, więc ten dokument dostaje osobne zamówienie.
        mail_drafts = [o for o in existing if o.status == "draft" and o not in shells]
        if len(shells) > 1 and not open_live:
            rp.reasons.append("Więcej niż jeden draft tej osoby — wybierz zamówienie")
            proposal.rows.append(rp)
            continue
        if shells and not open_live:
            if shells[0].order_group_id is not None and not titles_collide(
                shells[0].title, extraction.title
            ):
                rp.action = ACTION_GROUP
                rp.reasons.append(
                    "Szkic należy do istniejącej grupy o innym numerze — potwierdź przypisanie"
                )
                proposal.rows.append(rp)
                continue
            rp.action = ACTION_FILL_DRAFT
            rp.target_order_id = shells[0].id
            proposal.rows.append(rp)
            continue

        open_orders = open_live + mail_drafts
        overlapping = [o for o in open_orders if _overlaps(o, new_start, end)]
        if overlapping:
            rp.action = ACTION_OVERLAP
            rp.target_order_id = overlapping[0].id
            rp.reasons.append(
                f"Okres nachodzi na otwarte zamówienie #{overlapping[0].id} "
                f"({overlapping[0].title}, do {_iso(overlapping[0].end_date) or 'bezterminowo'})"
            )
            proposal.rows.append(rp)
            continue
        rp.action = ACTION_FUTURE if open_orders else ACTION_NEW
        proposal.rows.append(rp)
    return proposal
