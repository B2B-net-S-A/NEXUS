"""Skutki potwierdzenia podpisu dokumentu pochodnego.

Zasada jak przy umowie B2B („do kontraktu prowadzi jedna droga”): wygenerowanie
dokumentu niczego nie zmienia w kontraktach — zmienia dopiero „Oznacz jako
podpisany”. Dzięki temu aneks, który nie doszedł do skutku, nie zostawia
w kontrakcie stawki, której nikt nie podpisał.

Każdy skutek idzie ISTNIEJĄCĄ ścieżką domeny, nie własną kopią:
* zmiana stawki — handler aneksu z ``api/contracts.py`` (ten sam kod co
  zakładka „Aneksy”: krok harmonogramu, krok bazowy, bramka kwot Finansów);
* rozwiązanie i wypowiedzenie — ``_apply_termination_to_contract`` (zamówienia,
  aneks ``early_termination``, audyt), jak przycisk „Zakończ współpracę”;
  umowę w rejestrze zamyka ta sama synchronizacja co po tym oknie
  (``contract_termination_sync``: migawka, tryb, „Zakończona” dopiero gdy
  kontrakt przejdzie na „Zakończony”) — dokument zostawia na wierszu tylko
  znacznik trybu;
* cofnięcie wypowiedzenia — ``contract_lifecycle.reopen_contract`` (NIE
  ``revert_contract``, który cofa umowę do szkicu).

Import ``app.api.contracts`` jest leniwy: ten moduł woła router z warstwy
serwisów, a router nie może importować serwisu, który importuje router.

``describe`` liczy te same decyzje bez zapisu — okno „Oznacz jako podpisany”
pokazuje użytkownikowi listę zmian, zanim cokolwiek się stanie.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.activity import Activity
from app.models.b2b_contract_document import B2BContractDocument
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_generated_contract_status_event import (
    B2BGeneratedContractStatusEvent,
)
from app.models.candidate import Candidate
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractTerminationReason,
    RateUnit,
)
from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.user import User
from app.services.b2b_documents.registry import DocumentType
from app.services.contract_termination_sync import (
    clear_pending_dissolution,
    close_dissolved_row,
    mark_pending_dissolution,
)
from app.core.scheduling import business_today

logger = logging.getLogger(__name__)


@dataclass
class EffectPlan:
    """Co podpis zmieni — zdania dla człowieka i klucze dla audytu."""

    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _pl(day: date | None) -> str:
    return day.strftime("%d.%m.%Y") if day else "…"


async def _load_contract(db: AsyncSession, contract_id: int | None) -> Contract | None:
    if contract_id is None:
        return None
    return await db.scalar(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
        .with_for_update()
    )


def _payload(doc: B2BContractDocument) -> dict[str, Any]:
    """Pola formularza dokumentu — `render_payload` trzyma je pod `values`
    (obok `refs` i migawki `base`)."""
    payload = doc.render_payload or {}
    return dict(payload.get("values") or {})


# ── opis (bez zapisu) ────────────────────────────────────────────────────────


def _can_change_contracts(user: User) -> bool:
    """Lustro bramek tras `/terminate`, `/reopen`, `/amendments`: rola admin
    albo Delivery Lead (`DeliveryLeadPlus`) + zapis w sekcji Delivery. Samo
    uprawnienie „Oznaczanie podpisu umowy B2B” (także TAC/TCM) nie wystarcza
    — podpis dokumentu nie może być bocznymi drzwiami do zmian w kontrakcie."""
    from app.models.user import UserRole
    from app.services.section_permissions import (
        ProductSection,
        SectionAccess,
        section_access_for_user,
    )

    if not (user.has_role(UserRole.admin) or user.has_role(UserRole.delivery_lead)):
        return False
    return section_access_for_user(user, ProductSection.delivery) >= SectionAccess.write


async def describe(
    db: AsyncSession,
    doc: B2BContractDocument,
    doc_type: DocumentType,
    parent: B2BGeneratedContract | None,
    *,
    user: User | None = None,
) -> EffectPlan:
    plan = EffectPlan()
    values = _payload(doc)
    contract = (
        await db.get(Contract, doc.contract_id) if doc.contract_id is not None else None
    )
    if (
        user is not None
        and contract is not None
        and doc_type.key not in ("preliminary_cez", "notice_withdrawal")
        and not _can_change_contracts(user)
    ):
        plan.blockers.append(
            "Skutki w kontrakcie zatwierdza admin albo Delivery Lead z prawem "
            "zapisu w sekcji Delivery."
        )
    no_contract = (
        "Umowa nie jest powiązana z kontraktem w NEXUSIE — zmieni się tylko "
        "rejestr umów."
    )
    key = doc_type.key
    if key == "annex_rate_change":
        rate = values.get("new_rate")
        eff = _date(values.get("effective_date"))
        if contract is None:
            plan.warnings.append(no_contract)
        else:
            plan.changes.append(
                f"Stawka Partnera {rate} {values.get('currency') or ''}/h od {_pl(eff)} "
                "— nowy krok w harmonogramie stawek kontraktu."
            )
            currency = (contract.rate_candidate_currency or "PLN").upper()
            if (values.get("currency") or "PLN").upper() != currency:
                plan.blockers.append(
                    f"Waluta aneksu różni się od waluty stawki kontraktu ({currency})."
                )
            if contract.rate_unit != RateUnit.hourly:
                # Wzór aneksu mówi o stawce godzinowej — przy kontrakcie
                # miesięcznym 165 zostałoby zapisane jako kwota za miesiąc.
                plan.blockers.append(
                    "Kontrakt nie jest rozliczany godzinowo — aneks mówi o stawce "
                    "za godzinę. Zmień stawkę w zakładce „Aneksy” kontraktu."
                )
            if user is not None:
                from app.api.financial_access import can_manage_finance_amounts

                if not can_manage_finance_amounts(user):
                    plan.blockers.append(
                        "Stawkę w kontrakcie zmienia admin albo Finanse — poproś "
                        "ich o oznaczenie aneksu jako podpisanego."
                    )
    elif key == "annex_start_date":
        new_start = _date(values.get("new_start_date"))
        plan.changes.append(f"Data rozpoczęcia usług: {_pl(new_start)}.")
        if contract is None:
            plan.warnings.append(no_contract)
    elif key == "annex_party_data":
        plan.changes.append(
            f"Partner: {values.get('new_legal_name') or '…'}, "
            f"NIP {values.get('new_nip') or '…'} — w profilu kandydata i rejestrze."
        )
    elif key in ("annex_subcontractor", "annex_mandate"):
        if contract is None:
            plan.warnings.append(no_contract)
        else:
            plan.changes.append("Aneks pojawi się w historii kontraktu.")
    elif key in (
        "termination_agreement",
        "termination_agreement_mandate",
        "termination_notice",
    ):
        when = _date(values.get("termination_date"))
        plan.changes.append(
            f"Koniec współpracy z dniem {_pl(when)} — kontrakt, zamówienia klienta."
        )
        if parent is not None:
            if contract is not None and when is not None and when >= business_today():
                plan.changes.append(
                    "Umowa w rejestrze: „Zakończona” dzień po "
                    f"{_pl(when)} — do tego dnia obowiązuje."
                )
            else:
                plan.changes.append("Umowa w rejestrze: „Zakończona”.")
        if contract is None:
            plan.warnings.append(no_contract)
    elif key == "notice_withdrawal":
        plan.changes.append("Umowa w rejestrze wraca na „Aktywna”.")
        if contract is None:
            plan.warnings.append(no_contract)
        elif contract.terminated_at is not None or contract.status in (
            ContractStatus.ending,
            ContractStatus.ended,
        ):
            # Samo wyczyszczenie dat zostawiłoby skrócone/anulowane zamówienia
            # i aneks `early_termination` — pełne cofnięcie (z zamówieniami)
            # robi „Cofnij zakończenie” w module Kontrakty.
            plan.warnings.append(
                "Kontrakt przywróć przyciskiem „Cofnij zakończenie” w module "
                "Kontrakty — przywraca też zamówienia skrócone wypowiedzeniem."
            )
    elif key == "preliminary_cez":
        plan.changes.append("Brak zmian w kontraktach.")
    if doc_type.sensitive_keys and contract is not None:
        plan.warnings.append(
            "Dokument zawiera dane, których NEXUS nie przechowuje (PESEL, dowód, "
            "adres zamieszkania) — do kontraktu nie trafi plik z pustymi polami. "
            "Dołącz skan podpisanego dokumentu w zakładce Dokumenty kontraktu."
        )
    return plan


# ── zapis ────────────────────────────────────────────────────────────────────


async def _store_docx_on_contract(
    db: AsyncSession,
    contract: Contract,
    doc: B2BContractDocument,
    doc_type: DocumentType,
    data: bytes,
    *,
    actor_id: int | None,
) -> ContractDocument:
    from app.services.storage_service import save_contract_document

    filename = f"{doc_type.label} {doc.document_date.isoformat()}.docx"
    # Stały klucz pliku: ponowienie po awarii między zapisem pliku a commitem
    # nadpisuje ten sam plik zamiast zostawiać sierotę w magazynie.
    path, size = save_contract_document(
        contract.id,
        filename,
        io.BytesIO(data),
        stored_name=f"b2b-document-{doc.id}.docx",
    )
    record = ContractDocument(
        contract_id=contract.id,
        filename=filename,
        file_path=path,
        content_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        size_bytes=size,
        doc_type=(
            ContractDocumentType.annex
            if doc_type.family == "annex"
            else ContractDocumentType.other
        ),
        uploaded_by=actor_id,
    )
    db.add(record)
    await db.flush()
    return record


def _set_register_status(
    db: AsyncSession,
    row: B2BGeneratedContract,
    *,
    to_status: str,
    closure_reason: str | None,
    closure_date: date | None,
    actor_id: int | None,
) -> None:
    previous = row.contract_status
    if previous == to_status and row.closure_date == closure_date:
        return
    row.contract_status = to_status
    row.closure_reason = closure_reason
    row.closure_reason_other = None
    row.closure_date = closure_date
    db.add(
        B2BGeneratedContractStatusEvent(
            generated_contract_id=row.id,
            from_status=previous,
            to_status=to_status,
            effective_date=closure_date,
            reason=closure_reason,
            changed_by=actor_id,
        )
    )


async def apply(
    db: AsyncSession,
    doc: B2BContractDocument,
    doc_type: DocumentType,
    parent: B2BGeneratedContract | None,
    *,
    user: User,
    docx: bytes | None,
) -> dict[str, Any]:
    """Zastosuj skutki podpisu. Wołający trzyma blokadę wiersza dokumentu.

    ``docx is None`` = dokument z danymi wrażliwymi bez ich ponownego podania —
    nie archiwizujemy pliku z pustym PESEL-em/adresem jako „podpisanego”."""

    from app.api import contracts as contracts_api

    values = _payload(doc)
    summary: dict[str, Any] = {"type": doc_type.key}
    contract = await _load_contract(db, doc.contract_id)
    if contract is not None:
        await contracts_api._ensure_delivery_lead_contract_visible(contract, user, db)
        if docx is not None:
            stored = await _store_docx_on_contract(
                db, contract, doc, doc_type, docx, actor_id=user.id
            )
            summary["contract_document_id"] = stored.id
        else:
            stored = None
            summary["docx_not_archived"] = True
        summary["contract_id"] = contract.id
    else:
        stored = None
        summary["contract_id"] = None

    key = doc_type.key
    reason = f"{doc_type.label} z dnia {_pl(doc.document_date)} (dokument #{doc.id})"

    if key == "annex_rate_change" and contract is not None:
        from app.schemas.contract_amendment import ContractAmendmentCreate

        amendment = await contracts_api.create_contract_amendment(
            contract_id=contract.id,
            data=ContractAmendmentCreate(
                amendment_type=ContractAmendmentType.rate_change,
                effective_date=_date(values.get("effective_date")),
                new_rate_candidate=Decimal(str(values.get("new_rate"))),
                reason=reason,
                document_id=stored.id if stored else None,
            ),
            current_user=user,
            db=db,
        )
        summary["amendment_id"] = amendment.id

    elif key == "annex_start_date":
        new_start = _date(values.get("new_start_date"))
        if parent is not None and new_start is not None:
            parent.start_date = new_start
        if contract is not None and new_start is not None:
            old = contract.start_date
            contract.start_date = new_start
            summary["amendment_id"] = await _add_amendment(
                db,
                contract,
                ContractAmendmentType.start_date_change,
                old={"start_date": old.isoformat() if old else None},
                new={
                    "start_date": new_start.isoformat(),
                    "start_date_mode": values.get("new_start_date_mode"),
                },
                effective=new_start,
                reason=reason,
                document_id=stored.id if stored else None,
                actor_id=user.id,
            )
            from app.services.contract_order_sync import resync_contract_safely

            await resync_contract_safely(db, contract, actor_id=user.id)

    elif key == "annex_party_data":
        legal_name = values.get("new_legal_name")
        nip = "".join(ch for ch in str(values.get("new_nip") or "") if ch.isdigit())
        entity = values.get("entity_type")
        candidate_id = doc.candidate_id or (parent.candidate_id if parent else None)
        if candidate_id is not None:
            candidate = await db.get(Candidate, candidate_id)
            if candidate is not None:
                candidate.legal_name = legal_name or candidate.legal_name
                candidate.nip = nip or candidate.nip
                candidate.regon = values.get("new_regon") or candidate.regon
                candidate.business_address = (
                    values.get("new_business_address") or candidate.business_address
                )
                summary["candidate_updated"] = True
        if parent is not None:
            parent.partner_legal_name = legal_name or parent.partner_legal_name
            parent.partner_nip = nip or parent.partner_nip
            if entity in ("sole_trader", "company"):
                parent.partner_entity_type = entity
            if hasattr(parent, "business_data_annex_done_at"):
                parent.business_data_annex_done_at = doc.document_date
        if contract is not None:
            summary["amendment_id"] = await _add_amendment(
                db,
                contract,
                ContractAmendmentType.party_data_change,
                old={},
                new={"legal_name": legal_name, "nip": nip, "entity_type": entity},
                effective=_date(values.get("effective_date")) or doc.document_date,
                reason=reason,
                document_id=stored.id if stored else None,
                actor_id=user.id,
            )

    elif key == "annex_subcontractor" and contract is not None:
        summary["amendment_id"] = await _add_amendment(
            db,
            contract,
            ContractAmendmentType.subcontractor_consent,
            old={},
            new={"delegate_name": values.get("delegate_name")},
            effective=_date(values.get("effective_date")) or doc.document_date,
            reason=reason,
            document_id=stored.id if stored else None,
            actor_id=user.id,
        )

    elif key == "annex_mandate" and contract is not None:
        summary["amendment_id"] = await _add_amendment(
            db,
            contract,
            ContractAmendmentType.mandate_change,
            old={},
            new={
                "period_from": values.get("period_from"),
                "period_to": values.get("period_to"),
                "rate_changed": bool(values.get("change_rate")),
            },
            effective=_date(values.get("effective_date")) or doc.document_date,
            reason=reason,
            document_id=stored.id if stored else None,
            actor_id=user.id,
        )

    elif key in (
        "termination_agreement",
        "termination_agreement_mandate",
        "termination_notice",
    ):
        when = _date(values.get("termination_date"))
        if when is None:
            raise HTTPException(status_code=422, detail="Brak daty rozwiązania umowy.")
        agreement_termination = None
        if key == "termination_notice":
            termination_reason = ContractTerminationReason(
                values.get("termination_reason") or "other"
            )
            mode, party = "notice", "company"
            # Wypowiedzenie przez B2B.net ma komplet danych rozwiązania umowy
            # (0367): strona, data doręczenia, ostatni dzień umowy. Porozumienie
            # nie mówi, która strona je zainicjowała — tam kontrakt dostaje
            # samą datę, a dane rozwiązania uzupełnia okno „Zakończ współpracę”.
            delivered = _date(values.get("delivery_date"))
            signed_on = delivered or doc.document_date
            if delivered is not None and delivered <= when:
                from app.services.contract_termination_sync import (
                    AgreementTermination,
                )

                agreement_termination = AgreementTermination(
                    mode="notice",
                    party="company",
                    signed_on=delivered,
                    last_day=when,
                )
        else:
            termination_reason = ContractTerminationReason.mutual_agreement
            mode, party, signed_on = "mutual_agreement", None, doc.document_date
        # Umowa w rejestrze obowiązuje do daty rozwiązania: dokument zostawia
        # tryb na wierszu, a zamyka go synchronizacja zakończenia kontraktu —
        # teraz przy dacie minionej, inaczej nocny cron (audyt 25.09.2026,
        # runda 3). Znacznik PRZED zakończeniem kontraktu, bo to ono woła
        # synchronizację.
        if parent is not None:
            mark_pending_dissolution(
                parent, mode=mode, party=party, signed_on=signed_on
            )
        if contract is not None:
            await contracts_api._apply_termination_to_contract(
                db,
                contract,
                termination_reason=termination_reason,
                when=when,
                termination_lessons=reason,
                actor_id=user.id,
                agreement_termination=agreement_termination,
            )
            summary["terminated_at"] = when.isoformat()
        if parent is not None:
            await close_dissolved_row(
                db,
                parent,
                contract=contract,
                termination_reason=termination_reason,
                last_day=when,
                mode=mode,
                party=party,
                signed_on=signed_on,
                actor_id=user.id,
            )
            summary["register_status"] = parent.contract_status

    elif key == "notice_withdrawal":
        # Kontrakt NIE jest ruszany: pełne cofnięcie zakończenia (zamówienia,
        # aneks wcześniejszego zakończenia) ma własną ścieżkę w module
        # Kontrakty — okno podpisu mówi o tym wprost.
        summary["contract_left_for_manual_reversal"] = contract is not None
        if parent is not None and parent.contract_status == "closed":
            _set_register_status(
                db,
                parent,
                to_status="active",
                closure_reason=None,
                closure_date=None,
                actor_id=user.id,
            )
            # Tryb rozwiązania opisuje wypowiedzenie, które właśnie cofnięto.
            parent.termination_mode = None
            parent.termination_party = None
            parent.termination_signed_on = None
        elif parent is not None:
            # Wypowiedzenie z przyszłą datą jeszcze nie zamknęło umowy — zdejmij
            # znacznik, żeby nocny cron jej nie zamknął.
            clear_pending_dissolution(parent)

    db.add(
        Activity(
            entity_type="b2b_contract_document",
            entity_id=doc.id,
            action="signed_effect_applied",
            user_id=user.id,
            details={k: v for k, v in summary.items() if not isinstance(v, bytes)},
        )
    )
    doc.effect_applied_at = datetime.now(timezone.utc)
    doc.effect_summary = summary
    return summary


async def _add_amendment(
    db: AsyncSession,
    contract: Contract,
    amendment_type: ContractAmendmentType,
    *,
    old: dict,
    new: dict,
    effective: date | None,
    reason: str,
    document_id: int | None,
    actor_id: int | None,
) -> int:
    amendment = ContractAmendment(
        contract_id=contract.id,
        amendment_type=amendment_type,
        old_values=old,
        new_values=new,
        effective_date=effective or business_today(),
        reason=reason,
        document_id=document_id,
        created_by=actor_id,
    )
    db.add(amendment)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action=f"amendment_{amendment_type.value}",
            user_id=actor_id,
            details={
                "new": new,
                "effective_date": (effective or business_today()).isoformat(),
            },
        )
    )
    await db.flush()
    return amendment.id


async def register_partner_notice(
    db: AsyncSession,
    parent: B2BGeneratedContract,
    *,
    delivered_on: date,
    termination_date: date,
    user: User,
) -> dict[str, Any]:
    """Wypowiedzenie złożone przez Partnera — bez dokumentu po naszej stronie.

    Najczęstszy przypadek w rejestrze działu (106 wzmianek), a wzoru nie ma:
    NEXUS rejestruje fakt i jego skutek (koniec po okresie wypowiedzenia),
    ``notice_withdrawal`` go cofa."""
    from app.api import contracts as contracts_api

    summary: dict[str, Any] = {
        "type": "partner_notice",
        "delivered_on": delivered_on.isoformat(),
        "termination_date": termination_date.isoformat(),
    }
    contract = await _load_contract(db, parent.contract_id)
    # Jak przy dokumencie: umowa obowiązuje do końca okresu wypowiedzenia,
    # zamyka ją synchronizacja zakończenia kontraktu (audyt 25.09.2026, runda 3).
    mark_pending_dissolution(
        parent, mode="notice", party="consultant", signed_on=delivered_on
    )
    if contract is not None:
        await contracts_api._ensure_delivery_lead_contract_visible(contract, user, db)
        await contracts_api._apply_termination_to_contract(
            db,
            contract,
            termination_reason=ContractTerminationReason.consultant_resigned,
            when=termination_date,
            termination_lessons=(
                f"Wypowiedzenie Partnera doręczone {_pl(delivered_on)} "
                f"(umowa {parent.contract_number})"
            ),
            actor_id=user.id,
        )
        summary["contract_id"] = contract.id
    await close_dissolved_row(
        db,
        parent,
        contract=contract,
        termination_reason=ContractTerminationReason.consultant_resigned,
        last_day=termination_date,
        mode="notice",
        party="consultant",
        signed_on=delivered_on,
        actor_id=user.id,
    )
    summary["register_status"] = parent.contract_status
    db.add(
        Activity(
            entity_type="b2b_generated_contract",
            entity_id=parent.id,
            action="partner_notice_registered",
            user_id=user.id,
            details=summary,
        )
    )
    return summary


def ensure_no_blockers(plan: EffectPlan) -> None:
    if plan.blockers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=" ".join(plan.blockers),
        )
