"""Idempotencja zapisów API integracyjnego v1 (``Idempotency-Key``, 0443).

Automatyzacja ponawia żądanie, gdy nie dostała odpowiedzi — a odpowiedź ginie
właśnie wtedy, gdy NEXUS się wdraża (~2 min przerwy w oknie 18:00–08:00) albo
gdy padnie sieć po stronie integratora. Bez paragonu takie ponowienie
zaksięgowałoby zużycie MD albo fakturę drugi raz.

Kontrakt:

* ``Idempotency-Key`` jest wymagany na każdym zapisie v1 (UUID). Brak = 400.
* Ten sam klucz + ta sama treść → zapisana odpowiedź, bez ponownego zapisu
  (nagłówek ``Idempotent-Replayed: true``).
* Ten sam klucz + INNA treść → 409 ``idempotency_key_reused``. Cicha powtórka
  zignorowałaby nowe dane.
* Paragon ``pending`` wchodzi w TĘ SAMĄ transakcję co zmiana biznesowa,
  a ``finish`` zapisuje odpowiedź przed commitem wołającego. Gdy pomocnik
  domenowy commituje w trakcie (PR 2B: zamówienia), paragon ``pending`` jest
  zatwierdzony razem ze zmianą — powtórka w tym oknie dostaje 409
  ``idempotency_in_progress`` i ma ponowić za chwilę.
* Odpowiedź 4xx nie jest zapamiętywana: wyjątek wycofuje transakcję razem
  z paragonem, więc poprawione żądanie z tym samym kluczem przejdzie.
* ``dry_run`` nie używa paragonów wcale — próba nie może „zająć” klucza.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration_write_receipt import (
    RECEIPT_DONE,
    RECEIPT_PENDING,
    IntegrationWriteReceipt,
)
from app.services.service_account_auth import ServicePrincipal

IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
# Paragon `pending` starszy niż to = operacja przerwana (nie „trwa”).
PENDING_STALE_AFTER = timedelta(minutes=10)
# Paragony (z odpowiedzią) są rejestrem „co zapisała automatyzacja” i kluczem
# idempotencji — 90 dni wystarcza na każde ponowienie, a tabela nie rośnie bez
# końca. Klucz idempotencji jest per operacja, nie wraca po miesiącach.
RECEIPT_RETENTION = timedelta(days=90)


@dataclass(frozen=True)
class Replay:
    status_code: int
    body: Any


def canonical_key(raw: Optional[str]) -> str:
    """UUID z nagłówka w postaci kanonicznej albo 400/422."""
    if not raw or not raw.strip():
        raise HTTPException(
            400,
            detail={
                "error": "idempotency_key_required",
                "message": f"Zapis wymaga nagłówka {IDEMPOTENCY_HEADER} (UUID, "
                "nowy dla każdej operacji, ten sam przy ponowieniu).",
            },
        )
    try:
        return str(UUID(raw.strip()))
    except (ValueError, AttributeError):
        raise HTTPException(
            422,
            detail={
                "error": "idempotency_key_invalid",
                "message": f"{IDEMPOTENCY_HEADER} musi być UUID.",
            },
        ) from None


def payload_digest(method: str, route: str, payload: Any) -> str:
    """Skrót treści żądania — kanoniczny JSON, niezależny od kolejności kluczy."""
    return hashlib.sha256(
        json.dumps(
            {"method": method.upper(), "route": route, "payload": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _lock_key(account_id: int, key: str) -> int:
    return int.from_bytes(
        hashlib.sha256(f"integration-receipt:{account_id}:{key}".encode()).digest()[:8],
        "big",
        signed=True,
    )


async def begin(
    db: AsyncSession,
    principal: ServicePrincipal,
    *,
    raw_key: Optional[str],
    method: str,
    route: str,
    payload: Any,
) -> tuple[Optional[IntegrationWriteReceipt], Optional[Replay]]:
    """Zarezerwuj klucz albo zwróć zapisaną odpowiedź.

    Zwraca ``(paragon, None)`` dla nowej operacji albo ``(None, Replay)`` dla
    powtórki. Blokada doradcza szereguje równoległe żądania z tym samym kluczem.
    """
    key = canonical_key(raw_key)
    digest = payload_digest(method, route, payload)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": _lock_key(principal.account_id, key)},
    )
    existing = await db.scalar(
        select(IntegrationWriteReceipt).where(
            IntegrationWriteReceipt.service_account_id == principal.account_id,
            IntegrationWriteReceipt.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.payload_sha256 != digest:
            raise HTTPException(
                409,
                detail={
                    "error": "idempotency_key_reused",
                    "message": "Ten Idempotency-Key był już użyty z inną treścią "
                    "żądania. Dla nowej operacji wygeneruj nowy klucz.",
                },
            )
        if existing.state != RECEIPT_DONE:
            created = existing.created_at
            if created is not None and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if (
                created is not None
                and datetime.now(timezone.utc) - created > PENDING_STALE_AFTER
            ):
                # Proces padł między zapisem a odpowiedzią (np. wdrożenie w nocy).
                # Zmiana mogła wejść — skasowanie paragonu i powtórka groziłyby
                # podwójnym zapisem, więc mówimy wprost, co zrobić.
                raise HTTPException(
                    409,
                    detail={
                        "error": "idempotency_outcome_unknown",
                        "message": "Operacja z tym Idempotency-Key została przerwana "
                        "i jej wynik jest nieznany. Sprawdź stan odczytem i — jeśli "
                        "zmiany nie ma — wyślij ją z NOWYM kluczem.",
                    },
                )
            raise HTTPException(
                409,
                detail={
                    "error": "idempotency_in_progress",
                    "message": "Operacja z tym Idempotency-Key jeszcze trwa. "
                    "Ponów za kilka sekund.",
                },
            )
        return None, Replay(existing.status_code or 200, existing.response_json)

    await db.execute(
        delete(IntegrationWriteReceipt).where(
            IntegrationWriteReceipt.service_account_id == principal.account_id,
            IntegrationWriteReceipt.created_at
            < datetime.now(timezone.utc) - RECEIPT_RETENTION,
        )
    )
    receipt = IntegrationWriteReceipt(
        service_account_id=principal.account_id,
        key_id=principal.key_id,
        idempotency_key=key,
        method=method.upper()[:8],
        route=route[:255],
        payload_sha256=digest,
        state=RECEIPT_PENDING,
    )
    db.add(receipt)
    await db.flush()
    return receipt, None


async def finish(
    db: AsyncSession,
    receipt: IntegrationWriteReceipt,
    *,
    status_code: int,
    body: Any,
) -> None:
    """Zapamiętaj odpowiedź. Commit robi wołający (razem ze zmianą biznesową)."""
    receipt.state = RECEIPT_DONE
    receipt.status_code = status_code
    receipt.response_json = body
    receipt.completed_at = datetime.now(timezone.utc)
    await db.flush()
