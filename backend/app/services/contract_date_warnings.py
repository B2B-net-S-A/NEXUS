"""Ostrzeżenia dat kontraktu: „start przed podpisem” i „próg stawki przed startem”.

Przegląd skrzynki działu umów z 23.11.2026: umowę podpisano po starcie pracy
(konsultant pracował kilka dni bez podpisanej umowy), a w podsumowaniu
placementu próg stawki miał datę sprzed startu (literówka w roku). NEXUS
miał obie daty, ale nikt ich nie porównywał.

Oba ostrzeżenia to informacja na stronie kontraktu (pas „Co się dzieje”),
nigdy blokada zapisu. Odpowiedź niesie same daty, bez kwot, więc widzi je
każdy, kto widzi kontrakt.

* **Start przed podpisem:** najwcześniejszy dzień podpisu konsultanta
  (``b2b_generated_contracts.signed_on``, 0654: z podpisu w PDF-ie, z e-podpisu
  albo wpisany przy podpisie odręcznym) umowy podpisanej obustronnie dla tego
  kontraktu jest późniejszy niż ``contracts.start_date``. Nowa umowa z masowej
  wysyłki (E5b) się nie liczy: dostaje datę rozpoczęcia z poprzedniej umowy,
  więc zawsze jest „po starcie”.
* **Próg stawki przed startem:** w harmonogramie stawki konsultanta przed
  startem umowy stoją co najmniej dwa kroki. Wtedy wcześniejszy nigdy nie
  obowiązuje (resolver bierze najpóźniejszy krok ≤ dzień), a najczęściej to
  pomyłka w dacie progu. Jeden krok sprzed startu (stawka początkowa wpisana
  od 1. dnia miesiąca) jest w porządku.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_mass_send import B2BMassSendItem
from app.models.contract import Contract

__all__ = [
    "START_BEFORE_SIGNATURE",
    "RATE_STEP_BEFORE_START",
    "DateWarning",
    "contract_date_warnings",
    "dead_steps_before_start",
    "first_consultant_signature",
]

START_BEFORE_SIGNATURE = "start_before_signature"
RATE_STEP_BEFORE_START = "rate_step_before_start"


@dataclass(frozen=True)
class DateWarning:
    code: str
    start_date: date
    # Dzień podpisu konsultanta albo data progu stawki — zależnie od ``code``.
    day: date

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "start_date": self.start_date.isoformat(),
            "day": self.day.isoformat(),
        }


def dead_steps_before_start(
    start_date: Optional[date], steps: Iterable[tuple[date, int]]
) -> list[date]:
    """Daty kroków sprzed startu, które nigdy nie obowiązują.

    ``steps`` to pary (``effective_from``, id). Krok obowiązujący w dniu startu
    to najpóźniejszy krok ≤ start (remis rozstrzyga kolejność dopisania, jak
    w ``Contract.effective_candidate_rate``); każdy wcześniejszy krok sprzed
    startu jest martwy.
    """
    if start_date is None:
        return []
    covering = sorted(step for step in steps if step[0] <= start_date)
    if len(covering) < 2:
        return []
    return sorted({day for day, _ in covering[:-1] if day < start_date})


async def first_consultant_signature(
    db: AsyncSession, contract_id: int
) -> Optional[date]:
    """Najwcześniejszy dzień podpisu konsultanta umowy tego kontraktu."""
    mass_send_rows = select(B2BMassSendItem.generated_contract_id).where(
        B2BMassSendItem.generated_contract_id.is_not(None)
    )
    return await db.scalar(
        select(func.min(B2BGeneratedContract.signed_on)).where(
            B2BGeneratedContract.contract_id == contract_id,
            B2BGeneratedContract.signature_status == "signed_both",
            B2BGeneratedContract.signed_on.is_not(None),
            B2BGeneratedContract.id.not_in(mass_send_rows),
        )
    )


async def contract_date_warnings(
    db: AsyncSession, contract: Contract
) -> list[DateWarning]:
    """Ostrzeżenia dat kontraktu. ``candidate_rate_schedule`` musi być wczytany."""
    start = contract.start_date
    if start is None:
        return []
    warnings: list[DateWarning] = []
    signed_on = await first_consultant_signature(db, contract.id)
    if signed_on is not None and signed_on > start:
        warnings.append(DateWarning(START_BEFORE_SIGNATURE, start, signed_on))
    dead = dead_steps_before_start(
        start,
        (
            (step.effective_from, step.id or 0)
            for step in contract.candidate_rate_schedule
        ),
    )
    if dead:
        warnings.append(DateWarning(RATE_STEP_BEFORE_START, start, dead[0]))
    return warnings
