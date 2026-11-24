"""Dzwonek Finansów: aneks dopisał krok stawki konsultanta („stawka od dnia”).

Przegląd skrzynki umowy@ z 23.11.2026: zmiana stawki trafiała do Rozliczeń
tylko jako PDF aneksu mailem. Krok harmonogramu
(``contract_candidate_rates.effective_from``) dopisywały już wszystkie drogi
aneksu stawki (okno „Dodaj aneks”, podpis aneksu w Generatorze, wpis z pliku
w Dokumentach kontraktu — F52), a Rozliczenia czytały go przy przeliczeniu
miesiąca (uwaga „Zmiana stawki DD.MM”). Brakowało sygnału w chwili zmiany.

* **Jedno miejsce:** ``apply_contract_amendment`` (``api/contracts.py``) woła
  ``notify_finance_rate_annex`` po zapisie aneksu ze stawką konsultanta, więc
  każda droga aneksu daje ten sam dzwonek.
* **Odbiorcy:** aktywne konta Finansów i Back office'u
  (``hired_order_status.finance_recipient_ids``), bez autora aneksu.
* **Bez kwot** w treści: dzwonek może iść też mailem, a kwota jest na
  kontrakcie pod bramką stawek.
* **Fail-soft:** savepoint, błąd = log. Aneks jest ważniejszy niż dzwonek.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.models.notification import NotificationType
from app.services.client_identity import client_display_name

logger = logging.getLogger(__name__)

__all__ = ["notify_finance_rate_annex", "rate_annex_message"]

SOURCE_LABELS = {
    "manual": "aneks wpisany w kontrakcie",
    "generator": "podpisany aneks z Generatora",
    "document": "aneks z Dokumentów kontraktu",
}


def rate_annex_message(
    *,
    person: str,
    client_name: Optional[str],
    effective_from: date,
    source: str,
) -> str:
    parts = [person]
    if client_name:
        parts.append(client_name)
    origin = SOURCE_LABELS.get(source, "aneks")
    return (
        " · ".join(parts)
        + f": stawka konsultanta zmienia się od {effective_from:%d.%m.%Y} ({origin}). "
        "Rozliczenie miesiąca z tym dniem liczy się po dwóch stawkach."
    )


async def notify_finance_rate_annex(
    db: AsyncSession,
    *,
    contract: Contract,
    amendment_id: int,
    effective_from: date,
    source: str,
    actor_id: Optional[int],
) -> int:
    """Wyślij dzwonek Finansom. Zwraca liczbę dzwonków; wołający commituje."""
    from app.services.hired_order_status import finance_recipient_ids
    from app.services.notification_triggers import emit

    try:
        async with db.begin_nested():
            recipients = [
                uid for uid in await finance_recipient_ids(db) if uid != actor_id
            ]
            if not recipients:
                return 0
            candidate = (
                await db.get(Candidate, contract.candidate_id)
                if contract.candidate_id is not None
                else None
            )
            person = (
                " ".join(
                    part
                    for part in (
                        getattr(candidate, "name", None),
                        getattr(candidate, "lastname", None),
                    )
                    if part
                )
                or "Kontraktor"
            )
            client = (
                await db.scalar(select(Client).where(Client.id == contract.client_id))
                if contract.client_id is not None
                else None
            )
            message = rate_annex_message(
                person=person,
                client_name=client_display_name(client) if client else None,
                effective_from=effective_from,
                source=source,
            )
            sent = 0
            for user_id in recipients:
                notif = await emit(
                    db,
                    user_id=user_id,
                    title="Zmiana stawki konsultanta z aneksu",
                    message=message,
                    ntype=NotificationType.contract_rate_annex,
                    related_entity_type="contract_amendment",
                    related_entity_id=amendment_id,
                    link=f"/contracts/{contract.id}?tab=amendments",
                )
                if notif is not None:
                    sent += 1
            return sent
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — dzwonek nie może wywrócić aneksu
        logger.exception(
            "contract_rate_annex notification failed for contract %s", contract.id
        )
        return 0
