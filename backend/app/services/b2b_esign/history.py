"""Wysyłki do podpisu w NEXUSIE w historii umowy (etap 1b, 21.10.2026).

Dziennik statusów (`b2b_generated_contract_status_events`) zna tylko zmiany
statusu umowy. Wysyłka, przypomnienie, podpisy, wycofanie i wygaśnięcie żyją
na wierszach `b2b_signing_requests` — tu stają się wpisami tej samej historii,
bez drugiej tabeli i bez migracji.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from app.models.b2b_signing_request import B2BSigningRequest


@dataclass(frozen=True)
class EsignHistoryEntry:
    key: str
    at: datetime
    label: str
    user_id: Optional[int] = None


def esign_history(requests: Iterable[B2BSigningRequest]) -> list[EsignHistoryEntry]:
    """Wpisy historii z wysyłek jednej umowy — rosnąco po czasie."""
    out: list[EsignHistoryEntry] = []
    for r in requests:
        out.append(
            EsignHistoryEntry(
                f"esign-{r.id}-sent",
                r.sent_at,
                "Wysłana do podpisu w NEXUSIE",
                r.sent_by,
            )
        )
        if r.last_reminder_at is not None:
            out.append(
                EsignHistoryEntry(
                    f"esign-{r.id}-reminder",
                    r.last_reminder_at,
                    "Przypomnienie do kontraktora",
                )
            )
        if r.contractor_signed_at is not None:
            out.append(
                EsignHistoryEntry(
                    f"esign-{r.id}-contractor",
                    r.contractor_signed_at,
                    "Kontraktor podpisał — podpis kwalifikowany sprawdzony",
                )
            )
        if r.status == "completed" and r.completed_at is not None:
            out.append(
                EsignHistoryEntry(
                    f"esign-{r.id}-completed",
                    r.completed_at,
                    "Podpis za B2B Network — umowa podpisana przez obie strony",
                    r.company_signer_id,
                )
            )
        if r.status == "withdrawn" and r.closed_at is not None:
            reason = (r.close_reason or "").strip()
            out.append(
                EsignHistoryEntry(
                    f"esign-{r.id}-withdrawn",
                    r.closed_at,
                    f"Wysyłka wycofana — {reason}" if reason else "Wysyłka wycofana",
                    r.closed_by,
                )
            )
        if r.status == "expired" and r.closed_at is not None:
            out.append(
                EsignHistoryEntry(
                    f"esign-{r.id}-expired", r.closed_at, "Link do podpisu wygasł"
                )
            )
    return sorted(out, key=lambda e: e.at)
