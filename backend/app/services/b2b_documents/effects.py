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
from app.services import permission_catalog
from app.services.action_permissions import ProductAction, has_permission
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


def project_end_of(values: dict[str, Any], when: date | None) -> date | None:
    """Koniec projektu z porozumienia: ostatni dzień świadczenia usług.

    Runda 10 (R10-N14-2): porozumienie niesie dwie daty — rozwiązanie umowy
    (``termination_date``, ostatni dzień UMOWY) i ostatni dzień świadczenia
    usług (``last_service_date``, koniec PROJEKTU). Do rundy 10 kontrakt
    i zamówienia kończyły się datą rozwiązania, więc MRR, „Zejścia” i Insights
    liczyły dni pracy, których nie było. Data późniejsza niż rozwiązanie
    (dokument sprzed walidacji) liczy się jako rozwiązanie."""
    last_service = _date(values.get("last_service_date"))
    if when is None or last_service is None or last_service > when:
        return when
    return last_service


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


def current_contract_id(
    doc: B2BContractDocument, parent: B2BGeneratedContract | None
) -> int | None:
    """Kontrakt, którego dotyczą skutki podpisu — BIEŻĄCY kontrakt umowy bazowej.

    ``doc.contract_id`` to migawka z chwili generowania dokumentu. Po
    unieważnieniu kontraktu i „Powiąż z kontraktem” umowa bazowa wskazuje nowy
    kontrakt, a skutki trafiały do unieważnionego (runda 6 audytu, DOC-2).
    Dokument bez umowy bazowej (np. zlecenie) zna tylko swoją kolumnę."""
    if parent is not None:
        return parent.contract_id
    return doc.contract_id


VOID_CONTRACT_BLOCKER = (
    "Umowa jest powiązana z unieważnionym kontraktem — powiąż ją z właściwym "
    "kontraktem („Powiąż z kontraktem” w rejestrze umów) i oznacz dokument "
    "ponownie."
)


@dataclass(frozen=True)
class RateStep:
    """Pozycja aneksu stawki w postaci kroku harmonogramu kontraktu."""

    effective: date | None
    rate: Decimal
    until: date | None
    client_id: int | None
    client_name: str | None


def rate_steps(values: dict[str, Any], fallback: date | None) -> list[RateStep]:
    """Pozycje stawki aneksu, chronologicznie. Pozycja bez daty „od” obowiązuje
    od dnia wejścia zmian w życie. Dokument sprzed generatora aneksów niesie
    jedną stawkę w ``new_rate``."""
    from app.services.b2b_documents.registry import parse_amount

    raw_items = values.get("rate_items")
    if not isinstance(raw_items, list) or not raw_items:
        raw_items = (
            [{"rate": values.get("new_rate")}]
            if values.get("new_rate") not in (None, "")
            else []
        )
    effective = _date(values.get("effective_date")) or fallback
    steps: list[RateStep] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        amount = parse_amount(item.get("rate"))
        if amount is None:
            continue
        client_id = item.get("client_id")
        steps.append(
            RateStep(
                effective=_date(item.get("from")) or effective,
                rate=Decimal(str(round(amount, 2))),
                until=_date(item.get("to")),
                client_id=int(client_id) if client_id else None,
                client_name=item.get("client_name") or None,
            )
        )
    return sorted(steps, key=lambda s: s.effective or date.min)


def split_rate_steps(
    steps: list[RateStep], contract: Contract | None
) -> tuple[list[RateStep], list[RateStep]]:
    """(kroki dla klienta tego kontraktu albo bez klienta, kroki innych klientów).

    Stawka dla innego klienta to inny projekt — inny kontrakt; aneks nie może
    przepisać jej na kontrakt tej umowy."""
    if contract is None:
        return steps, []
    mine = [s for s in steps if s.client_id in (None, contract.client_id)]
    other = [s for s in steps if s.client_id not in (None, contract.client_id)]
    return mine, other


def _pl_rate(value: Decimal) -> str:
    text = f"{value:.2f}".replace(".", ",")
    return text[:-3] if text.endswith(",00") else text


def _payload(doc: B2BContractDocument) -> dict[str, Any]:
    """Pola formularza dokumentu — `render_payload` trzyma je pod `values`
    (obok `refs` i migawki `base`)."""
    payload = doc.render_payload or {}
    return dict(payload.get("values") or {})


# ── opis (bez zapisu) ────────────────────────────────────────────────────────


def contract_effect_permission(doc_type: DocumentType) -> ProductAction | None:
    """Uprawnienie z ekranu Osoby i role, którego wymaga skutek w KONTRAKCIE.

    Samo „Umowy B2B: oznaczanie jako podpisane” nie wystarcza — podpis
    dokumentu nie może być bocznymi drzwiami do zmian w kontrakcie, więc
    każdy rodzaj skutku pyta o to samo uprawnienie co odpowiadająca mu trasa
    modułu Kontrakty:

    * rozwiązanie, wypowiedzenie i jego cofnięcie kończą albo przywracają
      współpracę — jak ``/terminate``: „Zakończenie współpracy, zmiana statusu
      kontraktu”,
    * pozostałe aneksy zmieniają dane kontraktu — jak ``/amendments``:
      „Kontrakty i zamówienia: tworzenie i edycja” (także typ dokumentu,
      którego ta funkcja jeszcze nie zna),
    * aneks stawki ma własną bramkę kwot (``can_confirm_rate_annex``),
      a umowa przedwstępna niczego w kontraktach nie zmienia.
    """

    if doc_type.key in ("preliminary_cez", "annex_rate_change"):
        return None
    if doc_type.family == "termination":
        return ProductAction.contract_status
    return ProductAction.contracts_orders_edit


def contract_effect_blocker(permission: ProductAction) -> str:
    """Zdanie blokady w oknie „Oznacz jako podpisany” — nazywa brak wprost."""

    return (
        "Skutki tego dokumentu w kontrakcie zatwierdza osoba z uprawnieniem "
        f"„{permission_catalog.label(permission.value)}”."
    )


RATE_ANNEX_CONFIRMER_BLOCKER = (
    "Aneks zmiany stawki oznacza jako podpisany osoba z uprawnieniem "
    f"„{permission_catalog.label(ProductAction.amounts_edit.value)}” albo — "
    "u klienta ze swojego zakresu — z uprawnieniami "
    f"„{permission_catalog.label(ProductAction.contracts_orders_edit.value)}” "
    f"i „{permission_catalog.label(ProductAction.amounts_view.value)}”."
)


async def can_confirm_rate_annex(
    db: AsyncSession, user: User, client_id: int | None
) -> bool:
    """Kto potwierdza aneks zmiany stawki (decyzja Artura 27.09.2026).

    Ta sama reguła co kwoty zamówienia (``can_write_order_amounts``):
    „Stawki i kwoty: zmiana” (domyślnie admin i Finanse) albo prowadzenie
    kontraktów razem z podglądem kwot tego klienta — czyli, jak dotąd,
    Delivery Lead u klienta ze swojego portfela (granica
    ``resolve_delivery_lead_finance_client_ids``). Dokument bez klienta
    potwierdza wyłącznie posiadacz zmiany kwot, którego portfel nie wiąże.
    """
    from app.api.financial_access import (
        can_manage_finance_amounts,
        can_write_order_amounts,
    )
    from app.services.access_scope import resolve_delivery_lead_finance_client_ids

    portfolio = await resolve_delivery_lead_finance_client_ids(user, db)
    if client_id is None:
        return can_manage_finance_amounts(
            user, client_id=None, delivery_lead_finance_client_ids=portfolio
        )
    return can_write_order_amounts(
        user, client_id=client_id, delivery_lead_finance_client_ids=portfolio
    )


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
    contract_id = current_contract_id(doc, parent)
    contract = await db.get(Contract, contract_id) if contract_id is not None else None
    if (
        contract is not None
        and contract.status == ContractStatus.void
        and doc_type.key != "preliminary_cez"
    ):
        # Unieważniony kontrakt nie przyjmuje zakończenia ani aneksu — odmowa
        # czytelna zamiast 409 z maszyny stanów w połowie zapisu (runda 6
        # audytu, DOC-2).
        plan.blockers.append(VOID_CONTRACT_BLOCKER)
    required = contract_effect_permission(doc_type)
    if (
        user is not None
        and contract is not None
        and required is not None
        and not has_permission(user, required)
    ):
        plan.blockers.append(contract_effect_blocker(required))
    no_contract = (
        "Umowa nie jest powiązana z kontraktem w NEXUSIE — zmieni się tylko "
        "rejestr umów."
    )
    key = doc_type.key
    if key == "annex_rate_change":
        steps = rate_steps(values, doc.document_date)
        currency_label = (values.get("currency") or "PLN").upper()
        if contract is None:
            plan.warnings.append(no_contract)
        else:
            mine, other = split_rate_steps(steps, contract)
            for step in mine:
                plan.changes.append(
                    f"Stawka Partnera {_pl_rate(step.rate)} {currency_label}/h od "
                    f"{_pl(step.effective)} — nowy krok w harmonogramie stawek "
                    "kontraktu."
                )
                if step.until is not None and step is mine[-1]:
                    plan.warnings.append(
                        f"Ostatnia stawka ma datę „do” {_pl(step.until)} — "
                        "harmonogram kontraktu zostawi ją także po tej dacie, "
                        "dopóki nie przyjdzie kolejny aneks."
                    )
            for step in other:
                plan.warnings.append(
                    f"Stawka {_pl_rate(step.rate)} {currency_label}/h dla Klienta "
                    f"{step.client_name or '…'} nie zmieni tego kontraktu (inny "
                    "klient) — zmień ją w kontrakcie Partnera u tego klienta."
                )
            if not mine:
                plan.warnings.append(
                    "Żadna stawka aneksu nie dotyczy klienta tego kontraktu — "
                    "kontrakt się nie zmieni."
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
            if user is not None and not await can_confirm_rate_annex(
                db, user, contract.client_id
            ):
                plan.blockers.append(RATE_ANNEX_CONFIRMER_BLOCKER)
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
        project_end = project_end_of(values, when)
        ended_before = project_already_ended(contract, when)
        if ended_before and contract.status != ContractStatus.ended:
            # Projekt kończy się wcześniej niż umowa (zakończenie zaplanowane
            # oknem) — kontraktu dokument nie rusza (runda 7, R7-V4-1).
            plan.changes.append(
                "Kontrakt ma już zaplanowany koniec projektu "
                f"{_pl(contract.end_date)} — nie zmieni się, zamówienia też nie."
            )
            if parent is not None:
                plan.changes.append(
                    "Umowa w rejestrze: „Zakończona” po końcu projektu, z datą "
                    f"{_pl(when)}."
                )
        elif ended_before:
            # Projekt skończył się wcześniej (umowa czeka w „Umowach bez
            # projektu”) — dokument rozwiązuje umowę B2B, kontraktu nie rusza
            # (runda 6 audytu, DOC-1).
            plan.changes.append(
                "Kontrakt jest już „Zakończony” (koniec projektu "
                f"{_pl(contract.end_date or contract.terminated_at)}) — nie zmieni "
                "się, zamówienia też nie."
            )
            if parent is not None:
                plan.changes.append(
                    f"Umowa w rejestrze: „Zakończona” z dniem {_pl(when)}."
                )
        else:
            plan.changes.append(
                f"Koniec współpracy z dniem {_pl(project_end)} — kontrakt, "
                "zamówienia klienta."
            )
        if parent is not None and not ended_before:
            if project_end != when:
                plan.changes.append(
                    f"Umowa w rejestrze: „Zakończona” z dniem rozwiązania {_pl(when)}."
                )
            elif contract is not None and when is not None and when >= business_today():
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


def project_already_ended(contract: Contract | None, when: date | None = None) -> bool:
    """Projekt (kontrakt) kończy się niezależnie od rozwiązania umowy B2B.

    Umowa w rejestrze bywa wtedy w „Umowach bez projektu” — porozumienie albo
    wypowiedzenie rozwiązuje UMOWĘ z Partnerem, nie projekt. Ponowne
    „Zakończ współpracę” na zakończonym kontrakcie nadpisywało datę, powód,
    wnioski i dane rozwiązania i dokładało drugi wpis 'terminated', bo
    powtórka jest idempotentna tylko przy tej samej dacie (runda 6 audytu,
    DOC-1).

    Runda 7 (R7-V4-1): to samo przy zakończeniu zaplanowanym — kontrakt
    „Kończący się” (``terminated_at`` ustawione oknem, koniec projektu PRZED
    ostatnim dniem umowy ``when``). Typowo: projekt kończy się 30.09,
    wypowiedzenie umowy (miesiąc na koniec miesiąca) — 31.10. Nadpisanie
    przesuwało zejście w Insights o miesiąc i zamieniało powód."""
    if contract is None:
        return False
    if contract.status == ContractStatus.ended:
        return True
    return (
        when is not None
        and contract.status in (ContractStatus.active, ContractStatus.ending)
        and contract.terminated_at is not None
        and contract.end_date is not None
        and contract.end_date < when
    )


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
    contract = await _load_contract(db, current_contract_id(doc, parent))
    if contract is not None and contract.status == ContractStatus.void:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=VOID_CONTRACT_BLOCKER
        )
    if contract is not None:
        # Dokument wskazuje kontrakt, na który faktycznie zadziałał (runda 6
        # audytu, DOC-2) — migawka z generowania mogła wskazywać unieważniony.
        doc.contract_id = contract.id
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

        # Bramkę kwot (zmiana kwot albo prowadzenie kontraktów z podglądem kwot
        # klienta — decyzja 27.09.2026) sprawdza `describe` przed zapisem;
        # handler aneksu dopuszcza sam wyłącznie „Stawki i kwoty: zmiana”,
        # więc wołamy jego wersję z bramką zdjętą.
        if not await can_confirm_rate_annex(db, user, contract.client_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=RATE_ANNEX_CONFIRMER_BLOCKER,
            )
        # Każda pozycja (stawka progresywna) to osobny krok harmonogramu,
        # chronologicznie. Pozycje innych klientów nie ruszają tego kontraktu.
        mine, _other = split_rate_steps(rate_steps(values, doc.document_date), contract)
        amendment_ids: list[int] = []
        for step in mine:
            amendment = await contracts_api.apply_contract_amendment(
                contract_id=contract.id,
                data=ContractAmendmentCreate(
                    amendment_type=ContractAmendmentType.rate_change,
                    effective_date=step.effective or doc.document_date,
                    new_rate_candidate=step.rate,
                    reason=reason,
                    document_id=stored.id if stored else None,
                ),
                current_user=user,
                db=db,
                finance_write_authorized=True,
            )
            amendment_ids.append(amendment.id)
        if amendment_ids:
            summary["amendment_id"] = amendment_ids[0]
            if len(amendment_ids) > 1:
                summary["amendment_ids"] = amendment_ids

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
        # Aneks z generatora aneksów dotyczy zawsze JDG (ticket 29.09.2026);
        # dokument sprzed niego niesie `entity_type` wybrany w formularzu.
        entity = values.get("entity_type") or "sole_trader"
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
        project_end = project_end_of(values, when) or when
        if project_end != when:
            # Umowa trwa dłużej niż projekt: synchronizacja zakończenia
            # kontraktu zamknie wiersz datą ROZWIĄZANIA z tego dokumentu
            # (`contract_termination_sync._signed_dissolution_last_day`). Przy
            # dacie minionej kontrakt kończy się jeszcze w tym zapisie, więc
            # dokument musi być już widoczny jako zastosowany.
            summary["agreement_outlives_project"] = True
            summary["project_end_date"] = project_end.isoformat()
            doc.effect_applied_at = datetime.now(timezone.utc)
            doc.effect_summary = dict(summary)
            await db.flush()
        # Umowa w rejestrze obowiązuje do daty rozwiązania: dokument zostawia
        # tryb na wierszu, a zamyka go synchronizacja zakończenia kontraktu —
        # teraz przy dacie minionej, inaczej nocny cron (audyt 25.09.2026,
        # runda 3). Znacznik PRZED zakończeniem kontraktu, bo to ono woła
        # synchronizację.
        if parent is not None:
            mark_pending_dissolution(
                parent, mode=mode, party=party, signed_on=signed_on
            )
        ended_before = project_already_ended(contract, when)
        if ended_before:
            summary["contract_already_ended"] = True
        elif contract is not None:
            await contracts_api._apply_termination_to_contract(
                db,
                contract,
                termination_reason=termination_reason,
                when=project_end,
                termination_lessons=reason,
                actor_id=user.id,
                agreement_termination=agreement_termination,
            )
            summary["terminated_at"] = project_end.isoformat()
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
                independent_of_contract_end=ended_before,
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
            # Runda 10 (R10-N14-1): migawka zakończenia opisuje stan, który
            # właśnie cofnięto — jak przy ręcznej zmianie statusu w rejestrze.
            # Zostawiona sprawiała, że „Powrót po przerwie” albo nowe zamówienie
            # przywracały z niej „Zakończoną” z trybem wypowiedzenia, a kolejne
            # rozwiązanie nie zostawiało znacznika (`mark_pending_dissolution`).
            parent.termination_restore = None
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


PARTNER_NOTICE_AMBIGUOUS = (
    "Umowa nie jest powiązana z kontraktem, a osoba ma u tego klienta kilka "
    "trwających kontraktów — zakończ właściwy w module Kontrakty („Zakończ "
    "współpracę”), a potem zarejestruj wypowiedzenie."
)
PARTNER_NOTICE_NO_CONTRACT = (
    "Umowa nie jest powiązana z kontraktem, a osoba nie ma u tego klienta "
    "trwającego kontraktu — zmienił się tylko rejestr umów."
)


async def live_contract_ids_for_unlinked_row(
    db: AsyncSession,
    *,
    row_id: int,
    candidate_id: int | None,
    client_id: int | None,
) -> list[int]:
    """Trwające kontrakty osoby u klienta umowy BEZ powiązania z kontraktem.

    Runda 10 (R10-N14-3): wypowiedzenie Partnera do takiej umowy (każdy wiersz
    z Excela działu) zmieniało tylko rejestr, a kontrakt osoby trwał dalej bez
    daty końca. Lustro ``contract_termination_sync._rows_for_contract``:
    kontrakt TEJ osoby u TEGO klienta, który trwa (``active``/``ending``)
    i nie ma własnej żywej umowy w rejestrze — tamten projekt ma swoją umowę.
    """
    if candidate_id is None or client_id is None:
        return []
    own_agreement = (
        select(B2BGeneratedContract.id)
        .where(
            B2BGeneratedContract.contract_id == Contract.id,
            B2BGeneratedContract.id != row_id,
            B2BGeneratedContract.contract_status.in_(
                ("active", "suspended", "in_progress")
            ),
        )
        .exists()
    )
    return list(
        (
            await db.scalars(
                select(Contract.id)
                .where(
                    Contract.candidate_id == candidate_id,
                    Contract.client_id == client_id,
                    Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
                    ~own_agreement,
                )
                .order_by(Contract.id.asc())
            )
        ).all()
    )


async def register_partner_notice(
    db: AsyncSession,
    parent: B2BGeneratedContract,
    *,
    delivered_on: date,
    termination_date: date,
    user: User,
    matched_contract_id: int | None = None,
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
    contract = await _load_contract(db, parent.contract_id or matched_contract_id)
    if parent.contract_id is None and contract is not None:
        # Dopasowany po osobie — wiersz dostaje powiązanie w tym samym zapisie
        # (fill-only, jak synchronizacja zakończenia kontraktu).
        parent.contract_id = contract.id
        summary["contract_matched_by_person"] = True
        await db.flush()
    elif contract is None:
        summary["contract_warning"] = PARTNER_NOTICE_NO_CONTRACT
    # Jak przy dokumencie: umowa obowiązuje do końca okresu wypowiedzenia,
    # zamyka ją synchronizacja zakończenia kontraktu (audyt 25.09.2026, runda 3).
    mark_pending_dissolution(
        parent, mode="notice", party="consultant", signed_on=delivered_on
    )
    if contract is not None and contract.status == ContractStatus.void:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=VOID_CONTRACT_BLOCKER
        )
    if contract is not None:
        await contracts_api._ensure_delivery_lead_contract_visible(contract, user, db)
        summary["contract_id"] = contract.id
    ended_before = project_already_ended(contract, termination_date)
    if ended_before:
        # Projekt skończył się wcześniej — wypowiedzenie rozwiązuje umowę B2B,
        # kontrakt zostaje z datą i powodem końca projektu (runda 6 audytu,
        # DOC-1).
        summary["contract_already_ended"] = True
    elif contract is not None:
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
        independent_of_contract_end=ended_before,
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
