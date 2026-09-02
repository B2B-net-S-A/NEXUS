"""Plan zapisu zamówienia z maila — CZYSTY (bez bazy): co i gdzie powstałoby.

Klasyfikacja z ticketu §3, per osoba:
* konsultant ma DRAFT (szkic-zaślepkę „(bez numeru)" albo szkic bez okresu)
  → ``fill_draft``: uzupełniamy ten szkic zamiast zakładać nowy rekord;
* konsultant ma AKTYWNE zamówienie, a nowe jest jego kontynuacją na nowy
  okres (start po końcu dotychczasowego) → ``future``: nowe zamówienie z
  przyszłą datą startu;
* brak zamówienia → ``new``.

Do tego dwa przypadki, których ticket nie nazywa, a korpus ma:
* ``revision`` — zamówienie o tym numerze już istnieje u tego kontraktu
  (Fieldglass „Rev. 13" zmienia okres istniejącego, BIK ma numer długi
  ``4500030751`` i krótki ``30751``) → zawsze kolejka z diffem;
* ``overlap`` — nowy okres nachodzi na otwarte zamówienie o innym numerze →
  kolejka (addytywność: automat nie skraca ani nie nakłada).

Klient wielo-konsultantowy (grupa nad ``client_orders``) → ``group`` — writer
v1 obsługuje wyłącznie zamówienia samodzielne, więc grupa idzie do kolejki
z opisem linii. BIK/Polsat/Polkomtel i tak nie mają okresu w dokumencie.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from app.services.order_mail_resolver import ResolvedConsultant
from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction

ACTION_FILL_DRAFT = "fill_draft"
ACTION_FUTURE = "future"
ACTION_NEW = "new"
ACTION_REVISION = "revision"
ACTION_OVERLAP = "overlap"
ACTION_GROUP = "group"
ACTION_SKIP = "skip"
AUTO_ACTIONS = frozenset({ACTION_FILL_DRAFT, ACTION_FUTURE, ACTION_NEW})

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


def _is_draft_shell(order: ExistingOrder) -> bool:
    return order.status == "draft" and (
        order.title.strip() == PLACEHOLDER_TITLE
        or not order.title.strip()
        or order.start_date is None
    )


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


def plan_document(
    *,
    client_id: int,
    extraction: OrderExtraction,
    resolved: list[ResolvedConsultant],
    existing_orders_by_contract: dict[int, list[ExistingOrder]],
    is_group_client: bool,
    today: date,
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
        )
        if not res.is_unique_person or res.contract_id is None:
            rp.reasons.append(res.reason or "Nie ustalono osoby/kontraktu")
            proposal.rows.append(rp)
            continue
        if is_group_client:
            rp.action = ACTION_GROUP
            rp.reasons.append(
                "Klient wielo-konsultantowy — linia grupy zamówień (zapis ręczny w v1)"
            )
            proposal.rows.append(rp)
            continue
        if not start:
            rp.reasons.append("Brak daty początku okresu w dokumencie")
            proposal.rows.append(rp)
            continue

        existing = existing_orders_by_contract.get(res.contract_id, [])
        same_number = [o for o in existing if titles_collide(o.title, extraction.title)]
        if same_number:
            rp.action = ACTION_REVISION
            rp.target_order_id = same_number[0].id
            rp.reasons.append(
                f"Zamówienie o tym numerze już istnieje (#{same_number[0].id}, "
                f"{_iso(same_number[0].start_date) or '—'} – {_iso(same_number[0].end_date) or 'bezterminowo'}) — porównaj"
            )
            proposal.rows.append(rp)
            continue

        shells = [o for o in existing if _is_draft_shell(o)]
        if shells:
            rp.action = ACTION_FILL_DRAFT
            rp.target_order_id = shells[0].id
            proposal.rows.append(rp)
            continue

        open_orders = [o for o in existing if o.status in ("active", "paused", "draft")]
        new_start = date.fromisoformat(start)
        overlapping = [
            o
            for o in open_orders
            if (o.end_date is None or o.end_date >= new_start)
            and (
                end is None
                or o.start_date is None
                or o.start_date <= date.fromisoformat(end)
            )
        ]
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
