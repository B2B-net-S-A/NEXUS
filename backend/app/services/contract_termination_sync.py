"""Zakończenie współpracy ↔ Generator umów B2B (ticket 09.2026, migracja 0367).

Kontrakt w NEXUSIE to PROJEKT (osoba × klient), a umowa z Generatora to umowa
B2B z Partnerem — ta sama osoba może mieć jedną umowę i kolejne projekty.
Okno „Zakończ współpracę" rozróżnia dwa przypadki i ten moduł przenosi je do
Generatora w chwili, w której kontrakt przechodzi na „Zakończony" (dzień po
dacie zakończenia projektu — natychmiast w ``/terminate`` przy dacie
z przeszłości, inaczej w nocnym ``_promote_statuses``):

* **rozwiązanie umowy** (wypowiedzenie / porozumienie stron) → umowa
  ``closed``, „Data zakończenia umowy" = ostatni dzień umowy,
  „Data zakończenia zamówienia" = koniec projektu, tryb i strona zapisane;
* **samo zakończenie projektu** → umowa ``suspended`` („Umowy bez projektu"),
  chyba że osoba ma INNY aktywny projekt — wtedy umowa zostaje bez zmian.

Stan wiersza sprzed zmiany ląduje w ``termination_restore``, więc „Cofnij
zakończenie" (powrót kontraktu na „Aktywny") odtwarza go 1:1. Powrót po
przerwie (nowe zamówienie wskrzesza kontrakt) przy ROZWIĄZANEJ umowie zakłada
nową umowę powiązaną z poprzednią — tamta zostaje w „Zakończonych" bez zmian.

Podpisane w Generatorze rozwiązanie umowy (porozumienie, wypowiedzenie przez
B2B.net, zarejestrowane wypowiedzenie Partnera) idzie TĄ SAMĄ drogą
(audyt 25.09.2026, runda 3): dokument zostawia na wierszu znacznik trybu
(``mark_pending_dissolution``), a wiersz zamyka ta sama synchronizacja, która
zamyka go po oknie „Zakończ współpracę" — z migawką i dopiero wtedy, gdy
kontrakt przechodzi na „Zakończony". Wcześniej dokument zamykał wiersz od razu
(także z datą w przyszłości) i bez migawki, więc „Powrót po przerwie"
przywracał rozwiązaną umowę, a „Cofnij zakończenie" jej nie odtwarzało.

Moduł zna wyłącznie modele i nie importuje routera na poziomie modułu (numer
nowej umowy liczy ``_next_seq`` routera Generatora — import leniwy).
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_generated_contract_status_event import (
    B2BGeneratedContractStatusEvent,
)
from app.models.contract import Contract, ContractStatus, ContractTerminationReason

logger = logging.getLogger(__name__)

AGREEMENT_TERMINATION_MODES = ("notice", "mutual_agreement")
AGREEMENT_TERMINATION_PARTIES = ("consultant", "company")

MODE_LABEL_PL = {"notice": "Wypowiedzenie", "mutual_agreement": "Porozumienie stron"}
PARTY_LABEL_PL = {"consultant": "Konsultant", "company": "b2bnetwork"}

# Powód końca PROJEKTU z Kontraktów → katalog Generatora (0226: powody opisują
# koniec projektu). Wartości bez odpowiednika idą jako „Inny" z opisem — lepiej
# nazwać powód słowami niż wcisnąć go w najbliższą, nieprawdziwą kategorię.
_CLOSURE_REASON = {
    ContractTerminationReason.project_ended: ("project_completed", None),
    ContractTerminationReason.client_budget_cut: ("no_client_budget", None),
    ContractTerminationReason.performance_issue: (
        "contractor_underperformance",
        None,
    ),
    ContractTerminationReason.better_offer: ("contractor_found_other_project", None),
    ContractTerminationReason.poached_by_client: ("internalization", None),
    ContractTerminationReason.consultant_resigned: (
        "other",
        "Rezygnacja konsultanta",
    ),
    ContractTerminationReason.personal_reasons: ("other", "Powody osobiste"),
    ContractTerminationReason.contract_breach: ("other", "Naruszenie umowy"),
    ContractTerminationReason.mutual_agreement: ("other", "Porozumienie stron"),
    ContractTerminationReason.other: ("other", "Inny powód"),
}

# Wiersze, które zakończenie projektu może przestawić. `in_progress` (umowa
# w drodze do podpisu) i `cancelled` nie obowiązują, więc nie ma czego
# rozwiązywać ani zawieszać; `closed` jest już zakończona.
_DISSOLVABLE = ("active", "suspended")


@dataclass(frozen=True)
class AgreementTermination:
    """Rozwiązanie umowy B2B z okna „Zakończ współpracę"."""

    mode: str
    party: str
    signed_on: date
    last_day: date


def closure_reason_for(
    reason: Optional[ContractTerminationReason],
) -> tuple[str, Optional[str]]:
    if reason is None:
        return ("other", "Zakończenie współpracy")
    return _CLOSURE_REASON.get(reason, ("other", "Inny powód"))


def contract_agreement_termination(
    contract: Contract,
) -> Optional[AgreementTermination]:
    if (
        contract.agreement_termination_mode is None
        or contract.agreement_termination_party is None
        or contract.agreement_termination_signed_on is None
        or contract.agreement_last_day is None
    ):
        return None
    return AgreementTermination(
        mode=contract.agreement_termination_mode,
        party=contract.agreement_termination_party,
        signed_on=contract.agreement_termination_signed_on,
        last_day=contract.agreement_last_day,
    )


def set_contract_agreement_termination(
    contract: Contract, termination: Optional[AgreementTermination]
) -> None:
    """Zapisz albo wyczyść rozwiązanie umowy — zawsze komplet (CHECK 0367)."""
    contract.agreement_termination_mode = termination.mode if termination else None
    contract.agreement_termination_party = termination.party if termination else None
    contract.agreement_termination_signed_on = (
        termination.signed_on if termination else None
    )
    contract.agreement_last_day = termination.last_day if termination else None


def termination_details(
    contract: Contract, termination: Optional[AgreementTermination]
) -> dict:
    """Wpis historii: powód, koniec projektu i — przy rozwiązaniu — komplet danych."""
    details: dict = {
        "contract_id": contract.id,
        "termination_reason": (
            getattr(contract.termination_reason, "value", contract.termination_reason)
            if contract.termination_reason
            else None
        ),
        "project_end_date": (
            contract.end_date.isoformat() if contract.end_date else None
        ),
        "agreement_terminated": termination is not None,
    }
    if termination is not None:
        details.update(
            {
                "mode": termination.mode,
                "party": termination.party,
                "signed_on": termination.signed_on.isoformat(),
                "agreement_last_day": termination.last_day.isoformat(),
            }
        )
    return details


async def _rows_for_contract(
    db: AsyncSession, contract: Contract
) -> list[B2BGeneratedContract]:
    """Umowy z Generatora, których dotyczy zakończenie TEGO kontraktu.

    Najpierw umowy powiązane z kontraktem wprost (``contract_id``). Umowa B2B
    jest jednak umową z OSOBĄ, nie z klientem — po powrocie z zawieszenia bywa
    podpięta pod inny kontrakt, a umowy sprzed automatyzacji podpisu nie mają
    linku wcale. Dlatego zapasowo: umowy tej osoby bez kontraktu albo podpięte
    pod kontrakt, który już nie trwa (``ended``/``void``) — nigdy pod inny ŻYWY
    projekt, bo tamten projekt nadal ma swoją umowę.
    """
    linked = list(
        (
            await db.execute(
                select(B2BGeneratedContract)
                .where(B2BGeneratedContract.contract_id == contract.id)
                .order_by(B2BGeneratedContract.id.asc())
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if linked or contract.candidate_id is None:
        return linked
    other = Contract.__table__.alias("other_contract")
    return list(
        (
            await db.execute(
                select(B2BGeneratedContract)
                .outerjoin(other, other.c.id == B2BGeneratedContract.contract_id)
                .where(
                    B2BGeneratedContract.candidate_id == contract.candidate_id,
                    B2BGeneratedContract.contract_status.in_(_DISSOLVABLE),
                    or_(
                        B2BGeneratedContract.contract_id.is_(None),
                        other.c.status.in_(
                            [ContractStatus.ended.value, ContractStatus.void.value]
                        ),
                    ),
                )
                .order_by(B2BGeneratedContract.id.asc())
                .with_for_update(of=B2BGeneratedContract)
            )
        )
        .scalars()
        .all()
    )


async def has_other_active_project(
    db: AsyncSession, contract: Contract, *, today: date
) -> bool:
    """Czy osoba ma inny projekt, który dziś trwa (``active``/``ending``)."""
    if contract.candidate_id is None:
        return False
    found = await db.scalar(
        select(Contract.id)
        .where(
            Contract.candidate_id == contract.candidate_id,
            Contract.id != contract.id,
            Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
            or_(Contract.start_date.is_(None), Contract.start_date <= today),
            or_(Contract.end_date.is_(None), Contract.end_date >= today),
        )
        .limit(1)
    )
    return found is not None


def pending_dissolution(
    row: B2BGeneratedContract,
) -> Optional[tuple[str, Optional[str], Optional[date]]]:
    """Rozwiązanie z podpisanego dokumentu, które czeka na datę końca.

    Znacznik = tryb rozwiązania na wierszu, który jeszcze obowiązuje
    (``active``/``suspended``) i nie niesie migawki zakończenia. Wiersz z
    migawką to umowa, którą zakończenie kontraktu już przestawiło — jego tryb
    opisuje tamto zakończenie, nie czekające rozwiązanie.
    """
    if (
        row.termination_mode is None
        or row.contract_status not in _DISSOLVABLE
        or row.termination_restore is not None
    ):
        return None
    return (row.termination_mode, row.termination_party, row.termination_signed_on)


def mark_pending_dissolution(
    row: B2BGeneratedContract,
    *,
    mode: str,
    party: Optional[str],
    signed_on: Optional[date],
) -> bool:
    """Zapisz na wierszu podpisane rozwiązanie umowy — bez zmiany statusu.

    Umowa obowiązuje do daty rozwiązania; zamknie ją synchronizacja w chwili,
    w której kontrakt przejdzie na „Zakończony" (od razu przy dacie minionej,
    inaczej nocny cron). Zwraca ``False``, gdy wiersza nie ma czego rozwiązywać
    (w drodze do podpisu, anulowany, już zakończony) albo zakończenie kontraktu
    już go przestawiło — wtedy decyduje ``close_dissolved_row``.
    """
    if row.contract_status not in _DISSOLVABLE or row.termination_restore is not None:
        return False
    row.termination_mode = mode
    row.termination_party = party
    row.termination_signed_on = signed_on
    return True


def clear_pending_dissolution(row: B2BGeneratedContract) -> bool:
    """Zdejmij znacznik czekającego rozwiązania (cofnięcie wypowiedzenia,
    „Cofnij zakończenie")."""
    if pending_dissolution(row) is None:
        return False
    row.termination_mode = None
    row.termination_party = None
    row.termination_signed_on = None
    return True


async def contract_dissolved_by_agreement(db: AsyncSession, contract: Contract) -> bool:
    """Czy zakończenie TEGO kontraktu rozwiązało umowę B2B z Partnerem.

    Dwa źródła i oba się liczą: rozwiązanie z okna „Zakończ współpracę” żyje na
    kontrakcie (``agreement_termination_*``), a rozwiązanie z podpisanego
    dokumentu (porozumienie, wypowiedzenie przez B2B.net, wypowiedzenie
    Partnera) — na wierszu rejestru: tryb na umowie, którą zakończenie tego
    kontraktu zamknęło (migawka z ``contract_id``), albo znacznik czekającego
    rozwiązania na umowie podpiętej pod ten kontrakt. Porozumienie nie mówi,
    która strona je zainicjowała, więc na kontrakcie zapisać go nie da się
    (CHECK kompletu 0367) — dlatego pytamy też rejestr (audyt 25.09.2026,
    runda 4: PATCH daty na takim kontrakcie szedł reaktywacją i kasował
    rozwiązanie).
    """
    if contract.agreement_termination_mode is not None:
        return True
    owner = [B2BGeneratedContract.contract_id == contract.id]
    if contract.candidate_id is not None:
        owner.append(B2BGeneratedContract.candidate_id == contract.candidate_id)
    rows = (
        await db.scalars(
            select(B2BGeneratedContract).where(
                B2BGeneratedContract.termination_mode.isnot(None),
                or_(*owner),
            )
        )
    ).all()
    for row in rows:
        restore = row.termination_restore or {}
        if (
            restore.get("contract_id") == contract.id
            and row.contract_status == "closed"
        ):
            return True
        if row.contract_id == contract.id and pending_dissolution(row) is not None:
            return True
    return False


def _snapshot(
    row: B2BGeneratedContract, contract: Contract, *, without_marker: bool = False
) -> dict:
    """Stan wiersza sprzed zakończenia. ``without_marker`` — tryb rozwiązania
    zapisał dopiero podpisany dokument, więc „stan sprzed" go nie zna: cofnięcie
    zakończenia zostawia umowę bez rozwiązania."""
    if without_marker:
        return {
            **_snapshot(row, contract),
            "termination_mode": None,
            "termination_party": None,
            "termination_signed_on": None,
        }
    return {
        "contract_id": contract.id,
        "contract_status": row.contract_status,
        "closure_reason": row.closure_reason,
        "closure_reason_other": row.closure_reason_other,
        "closure_date": row.closure_date.isoformat() if row.closure_date else None,
        "termination_mode": row.termination_mode,
        "termination_party": row.termination_party,
        "termination_signed_on": (
            row.termination_signed_on.isoformat() if row.termination_signed_on else None
        ),
        "project_end_date": (
            row.project_end_date.isoformat() if row.project_end_date else None
        ),
    }


def _record(
    db: AsyncSession,
    row: B2BGeneratedContract,
    *,
    old_status: str,
    actor_id: Optional[int],
    action: str,
    details: dict,
) -> None:
    db.add(
        B2BGeneratedContractStatusEvent(
            generated_contract_id=row.id,
            from_status=old_status,
            to_status=row.contract_status,
            effective_date=row.closure_date,
            reason=row.closure_reason,
            reason_other=row.closure_reason_other,
            changed_by=actor_id,
            details={**details, "source": action},
        )
    )
    db.add(
        Activity(
            entity_type="b2b_generated_contract",
            entity_id=row.id,
            action=action,
            user_id=actor_id,
            details={
                **details,
                "contract_number": row.contract_number,
                "old": old_status,
                "new": row.contract_status,
            },
        )
    )


async def sync_generator_after_contract_ended(
    db: AsyncSession,
    contract: Contract,
    *,
    actor_id: Optional[int],
    today: Optional[date] = None,
) -> int:
    """Przenieś umowę w Generatorze po przejściu kontraktu na „Zakończony".

    Idempotentne: wiersz, który już niesie ``termination_restore`` tego
    kontraktu, jest pomijany (cron i ponowione ``/terminate`` nie dublują
    historii). Zwraca liczbę przestawionych wierszy.
    """
    if contract.status != ContractStatus.ended:
        return 0
    today_ = today or business_today()
    termination = contract_agreement_termination(contract)
    rows = await _rows_for_contract(db, contract)
    if not rows:
        return 0
    other_project: Optional[bool] = None
    reason, reason_other = closure_reason_for(contract.termination_reason)
    project_end = contract.end_date or contract.terminated_at or today_
    details = termination_details(contract, termination)
    changed = 0
    for row in rows:
        restore = row.termination_restore or {}
        if restore.get("contract_id") == contract.id:
            continue
        old_status = row.contract_status
        pending = pending_dissolution(row) if termination is None else None
        row_details = details
        if termination is not None:
            if old_status not in _DISSOLVABLE:
                continue
            snapshot = _snapshot(row, contract)
            row.contract_status = "closed"
            row.closure_date = termination.last_day
            row.termination_mode = termination.mode
            row.termination_party = termination.party
            row.termination_signed_on = termination.signed_on
        elif pending is not None:
            # Rozwiązanie podpisane w Generatorze (porozumienie, wypowiedzenie
            # Partnera) — kontrakt nie niesie jego danych, bo dokument nie mówi,
            # kto je zainicjował. Tryb, strona i data podpisu są już na wierszu.
            snapshot = _snapshot(row, contract, without_marker=True)
            row.contract_status = "closed"
            row.closure_date = contract.terminated_at or project_end
            row_details = {
                **details,
                "agreement_terminated": True,
                "mode": pending[0],
                "party": pending[1],
                "signed_on": pending[2].isoformat() if pending[2] else None,
                "agreement_last_day": row.closure_date.isoformat(),
                "from_signed_document": True,
            }
        else:
            # Samo zakończenie projektu: umowa obowiązuje dalej. Przenosimy ją
            # do „Umów bez projektu" tylko wtedy, gdy była aktywna i osoba nie
            # ma innego trwającego projektu.
            if old_status != "active":
                continue
            if other_project is None:
                other_project = await has_other_active_project(
                    db, contract, today=today_
                )
            if other_project:
                continue
            snapshot = _snapshot(row, contract)
            row.contract_status = "suspended"
            row.closure_date = project_end
            row.termination_mode = None
            row.termination_party = None
            row.termination_signed_on = None
        row.closure_reason = reason
        row.closure_reason_other = reason_other
        row.project_end_date = project_end
        row.termination_restore = snapshot
        # Wiersz dopasowany po osobie (umowa z Excela, sprzed automatyzacji
        # podpisu) dostaje link do kontraktu w tym samym zapisie — tylko gdy
        # go nie ma (`_rows_for_contract` bierze wyłącznie umowy TEJ osoby).
        # Bez linku powrót z „Umów bez projektu" kończył się 409 „brak
        # powiązanego kontraktora" (audyt 25.09.2026, runda 3).
        if row.contract_id is None:
            row.contract_id = contract.id
        _record(
            db,
            row,
            old_status=old_status,
            actor_id=actor_id,
            action="contract_termination_synced",
            details=row_details,
        )
        changed += 1
    return changed


async def close_dissolved_row(
    db: AsyncSession,
    row: B2BGeneratedContract,
    *,
    contract: Optional[Contract],
    termination_reason: Optional[ContractTerminationReason],
    last_day: date,
    mode: str,
    party: Optional[str],
    signed_on: Optional[date],
    actor_id: Optional[int],
) -> bool:
    """Domknij wiersz rozwiązany podpisanym dokumentem, jeśli nikt inny tego nie zrobi.

    Wołane PO zakończeniu kontraktu (``_apply_termination_to_contract``), które
    samo woła synchronizację. Zamyka wiersz tylko wtedy, gdy:

    * dokument nie ma kontraktu — nic go później nie domknie (cron chodzi po
      kontraktach), a rejestr jest jedynym zapisem rozwiązania;
    * kontrakt jest już „Zakończony", a synchronizacja wiersza nie wzięła
      (wiersz podpięty pod inny projekt, zawieszony wcześniej tym samym
      kontraktem albo w statusie, którego nie rozwiązuje).

    Kontrakt z przyszłą datą: wiersz obowiązuje do niej, zamknie go nocny cron
    (znacznik z ``mark_pending_dissolution``). Zwraca, czy zamknął wiersz.
    """
    if row.contract_status in ("closed", "cancelled"):
        return False
    if contract is not None and contract.status != ContractStatus.ended:
        return False
    old_status = row.contract_status
    restore = row.termination_restore or {}
    snapshot = None
    if contract is not None:
        # Wiersz, który zakończenie TEGO kontraktu już zawiesiło, zachowuje
        # swoją migawkę (stan sprzed pierwszej zmiany) — cofnięcie wraca do niej.
        snapshot = (
            restore
            if restore.get("contract_id") == contract.id
            else _snapshot(row, contract, without_marker=True)
        )
    reason, reason_other = closure_reason_for(termination_reason)
    row.contract_status = "closed"
    row.closure_reason = reason
    row.closure_reason_other = reason_other
    row.closure_date = last_day
    row.termination_mode = mode
    row.termination_party = party
    row.termination_signed_on = signed_on
    if contract is not None:
        row.project_end_date = contract.end_date or last_day
        row.termination_restore = snapshot
    details: dict = {
        "contract_id": contract.id if contract is not None else None,
        "agreement_terminated": True,
        "mode": mode,
        "party": party,
        "signed_on": signed_on.isoformat() if signed_on else None,
        "agreement_last_day": last_day.isoformat(),
        "from_signed_document": True,
    }
    _record(
        db,
        row,
        old_status=old_status,
        actor_id=actor_id,
        action="document_dissolution_closed",
        details=details,
    )
    return True


def _parse_day(value: object) -> Optional[date]:
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


async def _rows_changed_by(
    db: AsyncSession, contract: Contract
) -> list[B2BGeneratedContract]:
    rows = (
        (
            await db.execute(
                select(B2BGeneratedContract)
                .where(
                    and_(
                        B2BGeneratedContract.termination_restore.isnot(None),
                        or_(
                            B2BGeneratedContract.contract_id == contract.id,
                            B2BGeneratedContract.candidate_id == contract.candidate_id,
                        ),
                    )
                )
                .order_by(B2BGeneratedContract.id.asc())
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    return [
        row
        for row in rows
        if (row.termination_restore or {}).get("contract_id") == contract.id
    ]


def _restore_row(row: B2BGeneratedContract) -> None:
    snap = row.termination_restore or {}
    row.contract_status = snap.get("contract_status") or "active"
    row.closure_reason = snap.get("closure_reason")
    row.closure_reason_other = snap.get("closure_reason_other")
    row.closure_date = _parse_day(snap.get("closure_date"))
    row.termination_mode = snap.get("termination_mode")
    row.termination_party = snap.get("termination_party")
    row.termination_signed_on = _parse_day(snap.get("termination_signed_on"))
    row.project_end_date = _parse_day(snap.get("project_end_date"))
    row.termination_restore = None


async def _clear_pending_markers(db: AsyncSession, contract: Contract) -> int:
    rows = (
        (
            await db.execute(
                select(B2BGeneratedContract)
                .where(
                    B2BGeneratedContract.contract_id == contract.id,
                    B2BGeneratedContract.termination_mode.isnot(None),
                    B2BGeneratedContract.termination_restore.is_(None),
                    B2BGeneratedContract.contract_status.in_(_DISSOLVABLE),
                )
                .order_by(B2BGeneratedContract.id.asc())
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    return sum(1 for row in rows if clear_pending_dissolution(row))


async def undo_contract_termination(
    db: AsyncSession, contract: Contract, *, actor_id: Optional[int]
) -> int:
    """„Cofnij zakończenie": umowa wraca do stanu sprzed zakończenia.

    Czyści dane rozwiązania umowy na kontrakcie (tryb, strona, daty). Załącznik
    zostaje w „Dokumentach" — to zapis tego, co strony podpisały.
    """
    had_termination = contract_agreement_termination(contract)
    set_contract_agreement_termination(contract, None)
    # Rozwiązanie podpisane dokumentem z przyszłą datą czeka na wierszu
    # (znacznik) — cofnięte zakończenie nie może go zamknąć później.
    await _clear_pending_markers(db, contract)
    # Osoba zostaje na zamówieniu — zaplanowane „Wejdź za konsultanta” za nią
    # nie może w nocy przenieść jej puli (decyzja Artura 25.09.2026). Import
    # leniwy: moduł przejęć stoi wyżej w grafie importów.
    from app.services.order_line_takeover import (
        TAKEOVER_CANCEL_TERMINATION_UNDONE,
        cancel_scheduled_takeovers_for_contract,
    )

    await cancel_scheduled_takeovers_for_contract(
        db, contract, code=TAKEOVER_CANCEL_TERMINATION_UNDONE, actor_id=actor_id
    )
    restored = 0
    for row in await _rows_changed_by(db, contract):
        old_status = row.contract_status
        _restore_row(row)
        _record(
            db,
            row,
            old_status=old_status,
            actor_id=actor_id,
            action="contract_termination_undone",
            details={"contract_id": contract.id},
        )
        restored += 1
    if had_termination is not None or restored:
        db.add(
            Activity(
                entity_type="contract",
                entity_id=contract.id,
                action="termination_undone",
                user_id=actor_id,
                details={
                    "agreement_termination_cleared": had_termination is not None,
                    "generated_contracts_restored": restored,
                },
            )
        )
    return restored


async def _create_follow_up_agreement(
    db: AsyncSession,
    previous: B2BGeneratedContract,
    contract: Contract,
    *,
    actor_id: Optional[int],
    today: date,
) -> Optional[B2BGeneratedContract]:
    # Import leniwy: router Generatora importuje serwisy na poziomie modułu.
    from app.api.b2b_contract_generator import _next_seq

    for _attempt in range(3):
        seq = await _next_seq(db)
        number = f"{seq}/{today.year}"
        payload = (
            copy.deepcopy(previous.render_payload) if previous.render_payload else None
        )
        if payload is not None:
            payload["contract_number"] = number
            payload["signing_date"] = None
            payload["start_date"] = today.isoformat()
        row = B2BGeneratedContract(
            year=today.year,
            seq=seq,
            contract_number=number,
            partner_name=previous.partner_name,
            partner_legal_name=previous.partner_legal_name,
            partner_nip=previous.partner_nip,
            partner_entity_type=previous.partner_entity_type,
            client_name=previous.client_name,
            language=previous.language,
            start_date=today,
            created_by=actor_id or previous.created_by,
            candidate_id=contract.candidate_id,
            job_id=contract.job_id or previous.job_id,
            client_id=contract.client_id,
            contract_id=contract.id,
            contract_status="in_progress",
            signature_status="unsigned",
            previous_generated_contract_id=previous.id,
            render_payload=payload,
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            # Równoległy /render zajął ten numer — licz od nowa.
            logger.warning(
                "follow-up agreement number clash (contract=%s, seq=%s)",
                contract.id,
                seq,
            )
            continue
        return row
    return None


async def on_contract_returned_after_break(
    db: AsyncSession,
    previous: Contract,
    new: Optional[Contract] = None,
    *,
    actor_id: Optional[int],
    today: Optional[date] = None,
) -> None:
    """Powrót po przerwie — konsultant wraca po zakończonej współpracy.

    ``new`` to kontrakt, na którym osoba wraca: NOWY wiersz („Powrót po
    przerwie” zakłada szkic wskazujący poprzedni) albo ten sam kontrakt
    wskrzeszony nowym zamówieniem (``sync_contract_to_live_order``; wtedy
    ``new`` pomijamy).

    * umowa ROZWIĄZANA → nowa umowa w Generatorze w statusie początkowym
      („W trakcie"), powiązana z poprzednią i z kontraktem ``new``;
      poprzednia zostaje w „Zakończonych" bez zmian;
    * umowa tylko zawieszona tym kontraktem → wraca do stanu sprzed
      zakończenia i wskazuje kontrakt ``new`` (umowa obowiązywała cały czas).
    """
    today_ = today or business_today()
    target = new if new is not None else previous
    same_contract = target is previous
    termination = contract_agreement_termination(previous)
    rows = await _rows_changed_by(db, previous)
    created: list[int] = []
    for row in rows:
        old_status = row.contract_status
        if row.contract_status == "closed" and row.termination_mode is not None:
            follow_up = await _create_follow_up_agreement(
                db, row, target, actor_id=actor_id, today=today_
            )
            # Poprzednia umowa zostaje w „Zakończonych"; kasujemy tylko
            # migawkę, żeby „Cofnij zakończenie" nie wskrzesiło jej później.
            row.termination_restore = None
            if follow_up is None:
                continue
            created.append(follow_up.id)
            db.add(
                Activity(
                    entity_type="b2b_generated_contract",
                    entity_id=follow_up.id,
                    action="created_after_break",
                    user_id=actor_id,
                    details={
                        "contract_id": target.id,
                        "previous_contract_id": previous.id,
                        "previous_generated_contract_id": row.id,
                        "previous_contract_number": row.contract_number,
                        "contract_number": follow_up.contract_number,
                    },
                )
            )
            db.add(
                B2BGeneratedContractStatusEvent(
                    generated_contract_id=follow_up.id,
                    from_status=None,
                    to_status="in_progress",
                    changed_by=actor_id,
                    details={
                        "source": "created_after_break",
                        "contract_id": target.id,
                        "previous_generated_contract_id": row.id,
                        "previous_contract_number": row.contract_number,
                    },
                )
            )
            continue
        _restore_row(row)
        if not same_contract:
            row.contract_id = target.id
        _record(
            db,
            row,
            old_status=old_status,
            actor_id=actor_id,
            action="contract_returned_after_break",
            details={"contract_id": target.id, "previous_contract_id": previous.id},
        )
    if same_contract:
        # Wskrzeszony kontrakt nie jest już rozwiązany — dane rozwiązania
        # zostają w historii (Activity, umowa w „Zakończonych").
        set_contract_agreement_termination(previous, None)
        # Tak samo czekające rozwiązanie z dokumentu: znacznik zostawiony na
        # umowie wskrzeszonego kontraktu zamknąłby ją jako „rozwiązaną” przy
        # jego następnym, zwykłym zakończeniu (audyt 25.09.2026, runda 4).
        await _clear_pending_markers(db, previous)
    if termination is not None or rows:
        db.add(
            Activity(
                entity_type="contract",
                entity_id=target.id,
                action="returned_after_break",
                user_id=actor_id,
                details={
                    "previous_contract_id": previous.id,
                    "agreement_was_terminated": termination is not None,
                    "follow_up_generated_contract_ids": created,
                },
            )
        )
