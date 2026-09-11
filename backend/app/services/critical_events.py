"""Historia zdarzeń — zapis krytycznych operacji (wykonanych i zablokowanych).

Dwie ścieżki zapisu, bo dwie różne sytuacje transakcyjne:

* **wykonano** — wpis idzie do TEJ SAMEJ sesji co operacja
  (:func:`record_executed`). Gdy endpoint nie commituje sam, commit jest
  wspólny: wycofane usunięcie wycofuje też wpis. Endpointy, które commitują
  w środku (zamówienia, umowy ramowe, B2B), dostają wpis w KOLEJNEJ
  transakcji, zatwierdzanej przez ``get_db`` — nieudany końcowy commit
  zostawia wtedy usunięcie bez wpisu. Świadomie fail-open: dziennik jest
  śladem, nie bramką operacji.
* **zablokowano** — żądanie kończy się odmową (409/403/422), więc jego sesja
  jest wycofywana. Wpis zapisujemy z OSOBNEJ sesji (:func:`record_blocked`),
  inaczej każda zablokowana próba przepadałaby razem z rollbackiem.

:func:`audited_deletion` łączy obie ścieżki dla istniejących endpointów
usuwania: odmowa rzucona wewnątrz bloku zostaje zapisana jako zablokowana
próba (i wyjątek leci dalej bez zmian), a blok zakończony normalnie — jako
wykonana operacja. Brak zapisu nigdy nie wywraca samej operacji: dziennik jest
śladem, nie bramką.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.critical_event import CriticalEvent
from app.models.user import User
from app.services.client_identity import client_display_name

logger = logging.getLogger(__name__)

Outcome = Literal["executed", "blocked"]

# Kategorie obiektów — filtr w Ustawieniach → Historia zdarzeń.
ENTITY_TYPE_LABELS: dict[str, str] = {
    "client": "Klient",
    "contractor": "Kontraktor / konsultant",
    "contract": "Kontrakt",
    "agreement": "Umowa",
    "order": "Zamówienie",
    "user": "Uprawnienia użytkownika",
}

EVENT_TYPE_LABELS: dict[str, str] = {
    "client.delete": "Usunięcie klienta",
    "candidate.delete": "Usunięcie kandydata / kontraktora",
    "order_line.delete": "Usunięcie konsultanta z zamówienia",
    "contract.delete": "Usunięcie kontraktu",
    "contract.force_delete_signed": "Usunięcie kontraktu z podpisaną umową B2B",
    "framework_contract.delete": "Usunięcie umowy ramowej",
    "b2b_agreement.delete": "Usunięcie wygenerowanej umowy B2B",
    "order.delete": "Usunięcie zamówienia",
    "order_group.delete": "Usunięcie zamówienia MD / kosztowego",
    "user.client_delete_permission": "Zmiana uprawnienia do usuwania klientów",
}

OUTCOME_LABELS: dict[str, str] = {
    "executed": "Wykonano",
    "blocked": "Zablokowano",
}

# Odmowy, które są „zablokowaną próbą", a nie błędem żądania. 404 (obiektu
# nie ma) i 5xx (awaria) nie są decyzją systemu o tej operacji.
_BLOCKING_STATUSES = frozenset({403, 409, 422, 423})

_LABEL_LIMIT = 500
_NAME_LIMIT = 255


def _clip(value: Optional[str], limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


def http_detail_text(detail: Any) -> str:
    """Czytelny powód z ``HTTPException.detail`` (tekst albo słownik)."""

    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        for key in ("message", "detail", "reason"):
            value = detail.get(key)
            if isinstance(value, str) and value.strip():
                return value
        code = detail.get("code")
        if isinstance(code, str):
            return code
    if isinstance(detail, list):
        parts = [http_detail_text(item) for item in detail]
        return "; ".join(part for part in parts if part)
    return str(detail) if detail is not None else ""


def _build_event(
    *,
    actor: Optional[User],
    event_type: str,
    entity_type: str,
    entity_id: Optional[int],
    entity_label: Optional[str],
    outcome: Outcome,
    reason_code: Optional[str],
    reason: Optional[str],
    client_id: Optional[int],
    client_name: Optional[str],
    details: Optional[dict[str, Any]],
) -> CriticalEvent:
    return CriticalEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=_clip(entity_label, _LABEL_LIMIT),
        outcome=outcome,
        reason_code=_clip(reason_code, 64),
        reason=reason.strip() if reason else None,
        actor_user_id=getattr(actor, "id", None),
        actor_name=_clip(getattr(actor, "name", None), _NAME_LIMIT),
        actor_email=_clip(getattr(actor, "email", None), _NAME_LIMIT),
        client_id=client_id,
        client_name=_clip(client_name, _NAME_LIMIT),
        details=dict(details or {}),
    )


async def _resolve_client_name(
    db: AsyncSession, client_id: Optional[int], client_name: Optional[str]
) -> Optional[str]:
    if client_name or client_id is None:
        return client_name
    client = await db.scalar(select(Client).where(Client.id == client_id))
    return client_display_name(client) if client is not None else None


async def record_executed(
    db: AsyncSession,
    *,
    actor: Optional[User],
    event_type: str,
    entity_type: str,
    entity_id: Optional[int],
    entity_label: Optional[str] = None,
    client_id: Optional[int] = None,
    client_name: Optional[str] = None,
    reason_code: Optional[str] = None,
    reason: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    outcome: Outcome = "executed",
) -> CriticalEvent:
    """Dopisz wpis do sesji operacji. Commit należy do wołającego."""

    name = await _resolve_client_name(db, client_id, client_name)
    event = _build_event(
        actor=actor,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        outcome=outcome,
        reason_code=reason_code,
        reason=reason,
        client_id=client_id,
        client_name=name,
        details=details,
    )
    db.add(event)
    await db.flush()
    return event


async def record_blocked(
    *,
    actor: Optional[User],
    event_type: str,
    entity_type: str,
    entity_id: Optional[int],
    entity_label: Optional[str] = None,
    client_id: Optional[int] = None,
    client_name: Optional[str] = None,
    reason_code: Optional[str] = None,
    reason: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> bool:
    """Zapisz zablokowaną próbę w OSOBNEJ sesji i od razu ją zatwierdź.

    Nigdy nie rzuca — odmowa, którą zapisujemy, ma dotrzeć do użytkownika
    niezależnie od tego, czy dziennik jest dostępny. Zwraca ``True`` przy
    udanym zapisie.
    """

    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            name = await _resolve_client_name(session, client_id, client_name)
            session.add(
                _build_event(
                    actor=actor,
                    event_type=event_type,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    entity_label=entity_label,
                    outcome="blocked",
                    reason_code=reason_code,
                    reason=reason,
                    client_id=client_id,
                    client_name=name,
                    details=details,
                )
            )
            await session.commit()
        return True
    except Exception:  # noqa: BLE001 — dziennik nie może wywrócić odmowy
        logger.exception(
            "critical_events: blocked attempt not recorded (event=%s entity=%s:%s)",
            event_type,
            entity_type,
            entity_id,
        )
        return False


@dataclass
class DeletionAudit:
    """Opis operacji, uzupełniany w trakcie bloku ``audited_deletion``.

    Etykieta obiektu bywa znana dopiero po jego wczytaniu, więc endpoint
    ustawia ją wewnątrz bloku. Odmowa rzucona PRZED ustawieniem etykiety i tak
    trafia do dziennika — z samym identyfikatorem.
    """

    event_type: str
    entity_type: str
    entity_id: Optional[int]
    entity_label: Optional[str] = None
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)
    # Operacja zakończyła się czymś innym niż usunięcie (np. anulowanie
    # zamówienia zamiast skasowania) — opis trafia do kolumny „powód".
    result_note: Optional[str] = None
    # ``True`` = endpoint sam zdecydował, że operacji nie zapisujemy (np. nic
    # się nie zmieniło). Domyślnie zapisujemy.
    skip: bool = False

    def describe(
        self,
        *,
        label: Optional[str] = None,
        client_id: Optional[int] = None,
        client_name: Optional[str] = None,
        **details: Any,
    ) -> None:
        if label is not None:
            self.entity_label = label
        if client_id is not None:
            self.client_id = client_id
        if client_name is not None:
            self.client_name = client_name
        self.details.update(details)


@asynccontextmanager
async def audited_deletion(
    db: AsyncSession,
    *,
    actor: Optional[User],
    event_type: str,
    entity_type: str,
    entity_id: Optional[int],
    client_id: Optional[int] = None,
) -> AsyncIterator[DeletionAudit]:
    """Owiń istniejące usunięcie wpisem w Historii zdarzeń."""

    audit = DeletionAudit(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        client_id=client_id,
    )
    try:
        yield audit
    except HTTPException as exc:
        if exc.status_code in _BLOCKING_STATUSES:
            await record_blocked(
                actor=actor,
                event_type=audit.event_type,
                entity_type=audit.entity_type,
                entity_id=audit.entity_id,
                entity_label=audit.entity_label,
                client_id=audit.client_id,
                client_name=audit.client_name,
                reason_code=f"http_{exc.status_code}",
                reason=http_detail_text(exc.detail),
                details=audit.details,
            )
        raise
    if audit.skip:
        return
    try:
        # SAVEPOINT: nieudany zapis wpisu nie może zostawić sesji operacji
        # w stanie przerwanym — usunięcie ma się zatwierdzić mimo to.
        async with db.begin_nested():
            await record_executed(
                db,
                actor=actor,
                event_type=audit.event_type,
                entity_type=audit.entity_type,
                entity_id=audit.entity_id,
                entity_label=audit.entity_label,
                client_id=audit.client_id,
                client_name=audit.client_name,
                reason=audit.result_note,
                details=audit.details,
            )
    except Exception:  # noqa: BLE001 — dziennik nie jest bramką operacji
        logger.exception(
            "critical_events: executed operation not recorded (event=%s entity=%s:%s)",
            event_type,
            entity_type,
            entity_id,
        )
