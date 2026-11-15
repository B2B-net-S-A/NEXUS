"""Kategoria z umowy ramowej na kontrakcie i krok limitu (F1, 15.11.2026).

Trzy wejścia, jeden zapis limitu (``_write_limit_step``):

* **COA klienta** — wiersz zamówienia niesie kategorię i poziom
  (``ConsultantOrderRow.client_category``). Po zapisie zamówienia z maila
  (``order_mail_apply.apply_document``) i przy „Przelicz kategorie z COA”
  (``recompute_from_coa``) kontrakt dostaje pozycję cennika i krok limitu od
  początku zamówienia. Tylko pewne dopasowanie osoby (``MATCH_AUTO``).
* **Delivery Lead** (``set_by_delivery_lead``) — wybiera kategorię, gdy COA
  jej nie ma, i wpisuje przyznaną dopłatę z potwierdzeniem klienta.
* Dopłata NIE zmienia zamówienia ani stawki przychodowej — tylko limit
  (decyzja Artura z 15.11.2026). Wyższa cena w nowym COA to nowa stawka
  przychodowa, którą zapisuje synchronizacja zamówienie → kontrakt.

Limit to ``maksimum z cennika × (1 + dopłata)`` (``framework_limits``). Cennik
bez pozycji dla etykiety = zapisujemy samą etykietę, limitu nie ruszamy.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.scheduling import business_today
from app.models.client_order import ClientOrder
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.contract_framework_rate import ContractFrameworkRate
from app.models.rate_card import RateCard, RateCardAdder
from app.services.framework_limits import (
    AdderView,
    CardView,
    addon_choices,
    category_label,
    framework_limit,
    match_card,
    percent_text,
)

logger = logging.getLogger(__name__)

SOURCE_COA = "coa"
SOURCE_DL = "dl"
LIVE_STATUSES = (ContractStatus.active, ContractStatus.ending)
RECOMPUTE_PAGE = 20


class FrameworkCategoryError(ValueError):
    """Błąd do pokazania użytkownikowi (422)."""


@dataclass(frozen=True)
class ClientTerms:
    cards: tuple[CardView, ...]
    adders: tuple[AdderView, ...]

    def card(self, card_id: Optional[int]) -> Optional[CardView]:
        return next((c for c in self.cards if c.id == card_id), None)


async def load_terms(db: AsyncSession, client_id: int) -> ClientTerms:
    cards = (
        await db.execute(
            select(RateCard)
            .where(
                RateCard.client_id == client_id, RateCard.rate_unit == RateUnit.hourly
            )
            .order_by(RateCard.id)
        )
    ).scalars()
    adders = (
        await db.execute(
            select(RateCardAdder)
            .where(RateCardAdder.client_id == client_id)
            .order_by(RateCardAdder.id)
        )
    ).scalars()
    return ClientTerms(
        cards=tuple(CardView.of(c) for c in cards),
        adders=tuple(AdderView.of(a) for a in adders),
    )


def eligible_addon(
    terms: ClientTerms, card: CardView, technology: Optional[str], on: date
) -> Optional[AdderView]:
    if not technology:
        return None
    wanted = technology.strip().casefold()
    return next(
        (
            a
            for a in addon_choices(terms.adders, card, on=on)
            if a.technology.casefold() == wanted
        ),
        None,
    )


def _write_limit_step(
    db: AsyncSession,
    contract: Contract,
    limit: Decimal,
    *,
    effective_from: date,
    note: str,
    actor_id: Optional[int],
) -> bool:
    """Krok limitu od ``effective_from``; ``False`` = limit w tym dniu już taki był."""
    if contract.effective_framework_rate(effective_from) == limit:
        return False
    same_day = [
        s
        for s in contract.framework_rate_schedule
        if s.effective_from == effective_from
    ]
    if same_day:
        step = same_day[-1]
        step.rate = limit
        step.note = note[:500]
    else:
        step = ContractFrameworkRate(
            contract_id=contract.id,
            rate=limit,
            effective_from=effective_from,
            note=note[:500],
            created_by=actor_id,
        )
        db.add(step)
        contract.framework_rate_schedule.append(step)
    contract.framework_rate = contract.effective_framework_rate(business_today())
    return True


def _current_addon(contract: Contract) -> Optional[Decimal]:
    return (
        contract.framework_addon_percent
        if contract.framework_addon_technology
        else None
    )


def apply_category(
    db: AsyncSession,
    contract: Contract,
    terms: ClientTerms,
    label: Optional[str],
    *,
    effective_from: date,
    actor_id: Optional[int],
) -> str:
    """Kategoria z wiersza COA → kontrakt. Zwraca wynik do raportu.

    ``no_label`` — wiersz bez kategorii; ``no_card`` — cennik klienta nie ma
    takiej pozycji (etykieta zostaje zapisana); ``higher_limit_kept`` — limit
    na kontrakcie jest wyższy niż z cennika (np. dawna dopłata bez technologii),
    więc zostaje; ``unchanged`` / ``updated``.
    """
    if not label:
        return "no_label"
    contract.rate_card_coa_label = label[:255]
    card = match_card(terms.cards, label, on=effective_from)
    if card is None:
        return "no_card"
    if any(s.effective_from > effective_from for s in contract.framework_rate_schedule):
        # Nowszy krok limitu (np. z importu albo od DL) obowiązuje po tym COA —
        # kategoria z COA mogłaby już nie pasować do limitu. Decyduje DL.
        return "newer_limit_kept"
    changed = contract.client_rate_card_id != card.id
    contract.client_rate_card_id = card.id
    contract.rate_card_source = SOURCE_COA
    addon = eligible_addon(
        terms, card, contract.framework_addon_technology, effective_from
    )
    limit = framework_limit(card, addon.percent if addon else None)
    if limit is None:
        return "updated" if changed else "unchanged"
    current = contract.effective_framework_rate(effective_from)
    if current is not None and limit < current:
        # Limit wyższy niż cennik bywa dopłatą zapisaną dawniej samą liczbą
        # (195,80 = 178 + 10%) bez technologii na kontrakcie. Odczyt COA go nie
        # obniża — kategoria jest zapisana, decyzję o limicie podejmuje DL.
        return "higher_limit_kept"
    suffix = f" +{percent_text(addon.percent)}% {addon.technology}" if addon else ""
    stepped = _write_limit_step(
        db,
        contract,
        limit,
        effective_from=effective_from,
        note=f"Z COA: {category_label(card.role, card.seniority)}{suffix}",
        actor_id=actor_id,
    )
    return "updated" if (changed or stepped) else "unchanged"


def set_by_delivery_lead(
    db: AsyncSession,
    contract: Contract,
    terms: ClientTerms,
    *,
    rate_card_id: int,
    addon_technology: Optional[str],
    confirmed_by: Optional[str],
    confirmed_on: Optional[date],
    evidence: Optional[str],
    effective_from: date,
    actor_id: int,
) -> None:
    """Kategoria i dopłata wpisane przez DL. Dopłata wymaga potwierdzenia klienta."""
    card = terms.card(rate_card_id)
    if card is None:
        raise FrameworkCategoryError(
            "Ta pozycja cennika nie należy do klienta tego kontraktu."
        )
    addon = None
    if addon_technology:
        addon = eligible_addon(terms, card, addon_technology, effective_from)
        if addon is None:
            raise FrameworkCategoryError(
                f"Umowa ramowa nie przewiduje dopłaty za „{addon_technology}” "
                f"w kategorii {category_label(card.role, card.seniority)}."
            )
        if not (confirmed_by or "").strip() or confirmed_on is None:
            raise FrameworkCategoryError(
                "Dopłatę wpisz z potwierdzeniem klienta: kto potwierdził i kiedy."
            )
    if contract.client_rate_card_id != card.id:
        contract.client_rate_card_id = card.id
        contract.rate_card_source = SOURCE_DL
    contract.framework_addon_technology = addon.technology if addon else None
    contract.framework_addon_percent = addon.percent if addon else None
    contract.framework_addon_confirmed_by = (
        (confirmed_by or "").strip()[:255] or None if addon else None
    )
    contract.framework_addon_confirmed_on = confirmed_on if addon else None
    contract.framework_addon_evidence = (
        (evidence or "").strip() or None if addon else None
    )
    contract.framework_addon_set_by_id = actor_id
    contract.framework_addon_set_at = datetime.now(timezone.utc)
    limit = framework_limit(card, addon.percent if addon else None)
    if limit is not None:
        suffix = f" +{percent_text(addon.percent)}% {addon.technology}" if addon else ""
        _write_limit_step(
            db,
            contract,
            limit,
            effective_from=effective_from,
            note=f"Delivery Lead: {category_label(card.role, card.seniority)}{suffix}",
            actor_id=actor_id,
        )


# --- Ponowny odczyt zapisanych COA ------------------------------------------------


@dataclass
class RecomputeRow:
    contract_id: int
    outcome: str
    coa_label: Optional[str] = None
    category_before: Optional[str] = None
    category_after: Optional[str] = None
    limit_before: Optional[Decimal] = None
    limit_after: Optional[Decimal] = None


@dataclass
class RecomputeReport:
    rows: list[RecomputeRow] = field(default_factory=list)
    next_after_id: Optional[int] = None


def _row_extractor(client_id: int):
    from app.services.order_policies.registry import active_policies

    for policy in active_policies(client_id):
        if policy.extract_rows is not None:
            return policy.extract_rows
    return None


def _read_rows(path: str, filename: str, extractor) -> list:
    from app.services.order_document_text import extract_order_text

    return extractor(extract_order_text(path, filename).text)


async def recompute_from_coa(
    db: AsyncSession,
    client_id: int,
    *,
    after_id: int = 0,
    apply: bool,
    actor_id: Optional[int],
) -> RecomputeReport:
    """Porcja kontraktów klienta: kategoria z najnowszego zapisanego COA.

    PDF-y czytamy po jednym (osobny proces z limitem pamięci), porcją
    ``RECOMPUTE_PAGE`` — ekran woła kolejne porcje z ``next_after_id``.
    """
    from app.services import storage_service
    from app.services.order_consultant_match import MATCH_AUTO, match_names

    extractor = _row_extractor(client_id)
    if extractor is None:
        raise FrameworkCategoryError(
            "Odczyt kategorii z zamówienia jest dostępny tylko u klienta z tabelą osób w COA (Nordea)."
        )
    terms = await load_terms(db, client_id)
    contracts = (
        (
            await db.execute(
                select(Contract)
                .options(
                    selectinload(Contract.framework_rate_schedule),
                    selectinload(Contract.candidate),
                )
                .where(
                    Contract.client_id == client_id,
                    Contract.status.in_(LIVE_STATUSES),
                    Contract.id > after_id,
                )
                .order_by(Contract.id)
                .limit(RECOMPUTE_PAGE)
                .with_for_update(of=Contract)
            )
        )
        .scalars()
        .all()
    )
    report = RecomputeReport(
        next_after_id=contracts[-1].id if len(contracts) == RECOMPUTE_PAGE else None
    )
    today = business_today()
    for contract in contracts:
        before_card = terms.card(contract.client_rate_card_id)
        row = RecomputeRow(
            contract_id=contract.id,
            outcome="no_coa",
            category_before=category_label(before_card.role, before_card.seniority)
            if before_card
            else None,
            limit_before=contract.effective_framework_rate(today),
        )
        report.rows.append(row)
        order = await db.scalar(
            select(ClientOrder)
            .where(
                ClientOrder.contract_id == contract.id,
                ClientOrder.file_path.is_not(None),
            )
            .order_by(ClientOrder.start_date.desc().nulls_last(), ClientOrder.id.desc())
            .limit(1)
        )
        if order is None:
            continue
        try:
            path = storage_service.get_client_order_po_path(order.file_path)
            rows = await asyncio.to_thread(
                _read_rows, str(path), order.filename or path.name, extractor
            )
        except FileNotFoundError:
            row.outcome = "file_missing"
            continue
        except Exception as exc:  # noqa: BLE001 — jeden zły PDF nie zatrzymuje porcji
            logger.warning(
                "[framework_category] COA read failed for contract %s (%s)",
                contract.id,
                type(exc).__name__,
            )
            row.outcome = "unreadable"
            continue
        person = (
            f"{contract.candidate.name} {contract.candidate.lastname}"
            if contract.candidate
            else ""
        )
        hits = [
            r
            for r in rows
            if (m := match_names(r.consultant_name, person)) and m.level == MATCH_AUTO
        ]
        if len(hits) != 1:
            row.outcome = "person_not_found" if not hits else "person_ambiguous"
            continue
        row.coa_label = hits[0].client_category
        effective_from = order.start_date or today
        if not apply:
            card = match_card(terms.cards, row.coa_label, on=effective_from)
            row.outcome = (
                "no_label"
                if not row.coa_label
                else ("no_card" if card is None else "preview")
            )
            if card is not None:
                row.category_after = category_label(card.role, card.seniority)
                addon = eligible_addon(
                    terms, card, contract.framework_addon_technology, effective_from
                )
                row.limit_after = framework_limit(
                    card, addon.percent if addon else None
                )
            continue
        row.outcome = apply_category(
            db,
            contract,
            terms,
            row.coa_label,
            effective_from=effective_from,
            actor_id=actor_id,
        )
        after_card = terms.card(contract.client_rate_card_id)
        row.category_after = (
            category_label(after_card.role, after_card.seniority)
            if after_card
            else None
        )
        row.limit_after = contract.effective_framework_rate(today)
    return report


async def sync_from_mail_document(
    db: AsyncSession, doc, result, *, actor_id: Optional[int]
) -> None:
    """Po zapisie zamówienia z maila: kategoria z wiersza COA → kontrakt.

    Dodatek, nie bramka: błąd zostaje w logu, zamówienie jest już zapisane
    (savepoint jak ``resync_contract_safely``).
    """
    from app.services.order_mail_ingest import restore_extraction

    rows = restore_extraction(doc.extraction).consultant_rows
    labelled = {
        r.row_index: rows[r.row_index].client_category
        for r in result.rows
        if r.order_id
        and not r.error
        and 0 <= r.row_index < len(rows)
        and rows[r.row_index].client_category
    }
    if not labelled:
        return
    try:
        async with db.begin_nested():
            terms = await load_terms(db, doc.client_id)
            for applied in result.rows:
                label = labelled.get(applied.row_index)
                if not label:
                    continue
                order = await db.get(ClientOrder, applied.order_id)
                if order is None or order.contract_id is None:
                    continue
                contract = await db.scalar(
                    select(Contract)
                    .options(selectinload(Contract.framework_rate_schedule))
                    .where(Contract.id == order.contract_id)
                    .with_for_update()
                )
                if contract is None:
                    continue
                apply_category(
                    db,
                    contract,
                    terms,
                    label,
                    effective_from=order.start_date or business_today(),
                    actor_id=actor_id,
                )
            await db.flush()
    except Exception:  # noqa: BLE001 — dodatek do zapisu zamówienia
        logger.exception(
            "[framework_category] category from mail document %s failed", doc.id
        )
