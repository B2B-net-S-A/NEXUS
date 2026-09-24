"""Umowa B2B jest bezterminowa, dopóki ktoś jej ręcznie nie zakończy (09.2026).

Data zakończenia umowy B2B trafiała do kontraktu z daty zakończenia
ZAMÓWIENIA — przepisywana przy zakładaniu kontraktu (pole „Contract end"
w oknie „Nowy kontraktor / zamówienie") i przy przedłużeniach. Umowa B2B
z konsultantem trwa jednak do rozstania, a zamówienie klienta wygasa co kilka
miesięcy. Skutek: nocny cron przestawiał taki kontrakt na „Kończący się",
potem „Zakończony", a osoba znikała z aktywnych mimo trwającej współpracy.

Reguła (jedno źródło dla API i dla jednorazowej korekty):

* umowa B2B w statusie innym niż „Zakończony"/„Anulowany" NIE ma daty
  zakończenia, chyba że ktoś ją świadomie zakończył — ``/terminate``
  (wypełnia ``terminated_at`` i ``termination_reason``) albo aneksem
  ``early_termination``;
* umowy zlecenie i o pracę nie są objęte — tam data końca jest częścią umowy.

Datę zakończenia umowy B2B ustawia się więc „Zakończ współpracę" (powód +
data, także przyszła — wtedy umowa jest „Kończąca się" aż do tego dnia) albo
statusem „Zakończony" w rejestrze umów.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract, ContractStatus, ContractType
from app.models.contract_amendment import ContractAmendment, ContractAmendmentType

B2B_END_DATE_REASON = "b2b_end_date_requires_termination"
B2B_END_DATE_MESSAGE = (
    "Umowa B2B jest bezterminowa — nie ma daty zakończenia, dopóki ktoś jej "
    "nie zakończy. Datę ustawia okno „Zakończ współpracę” (powód i data, "
    "także przyszła). Koniec zamówienia u klienta wpisz w zamówieniu, nie "
    "w umowie."
)

# Statusy, w których data zakończenia jest faktem, a nie prognozą: umowa już
# się skończyła (albo została unieważniona), więc jej data zostaje bez zmian.
CLOSED_STATUSES = frozenset({ContractStatus.ended, ContractStatus.void})


def _value(enum_or_str: object) -> str:
    return str(getattr(enum_or_str, "value", enum_or_str))


def is_b2b(contract_type: object) -> bool:
    return _value(contract_type) == ContractType.b2b.value


def has_termination_metadata(contract: Contract) -> bool:
    """Ślad wypowiedzenia na samym wierszu (``/terminate`` wypełnia oba pola)."""
    return contract.terminated_at is not None or contract.termination_reason is not None


async def is_manually_terminated(db: AsyncSession, contract: Contract) -> bool:
    """Czy ktoś ŚWIADOMIE zakończył tę umowę.

    ``/terminate`` zostawia ``terminated_at`` + ``termination_reason``; aneks
    ``early_termination`` przesuwa samą datę i statusu wypowiedzenia na wierszu
    nie zostawia — dlatego trzecie źródło to historia aneksów.
    """
    if has_termination_metadata(contract):
        return True
    return await has_early_termination_amendment(db, contract.id)


async def has_early_termination_amendment(
    db: AsyncSession, contract_id: Optional[int]
) -> bool:
    if contract_id is None:
        return False
    return bool(
        await db.scalar(
            select(
                exists().where(
                    ContractAmendment.contract_id == contract_id,
                    ContractAmendment.amendment_type
                    == ContractAmendmentType.early_termination,
                )
            )
        )
    )


def end_date_allowed(
    *,
    contract_type: object,
    status: object,
    end_date: Optional[date],
    manually_terminated: bool,
) -> bool:
    """Czy wynikowy stan umowy spełnia regułę B2B."""
    if end_date is None or not is_b2b(contract_type):
        return True
    if _value(status) in {s.value for s in CLOSED_STATUSES}:
        return True
    return manually_terminated
