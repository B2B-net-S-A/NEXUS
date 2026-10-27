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
from zoneinfo import ZoneInfo

from app.models.b2b_signing_request import B2BSigningRequest

_WARSAW = ZoneInfo("Europe/Warsaw")


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
            # Po podpisie kontraktora zamiatacz ponagla reprezentanta firmy.
            to_company = (
                r.contractor_signed_at is not None
                and r.last_reminder_at > r.contractor_signed_at
            )
            out.append(
                EsignHistoryEntry(
                    f"esign-{r.id}-reminder",
                    r.last_reminder_at,
                    "Przypomnienie do podpisu za B2B Network"
                    if to_company
                    else "Przypomnienie do kontraktora",
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
        events = list(getattr(r, "events", None) or [])
        logged_expiry = any(e.get("kind") == "expired" for e in events)
        if r.status == "expired" and r.closed_at is not None and not logged_expiry:
            # Wnioski sprzed dziennika zdarzeń (0531).
            out.append(
                EsignHistoryEntry(
                    f"esign-{r.id}-expired", r.closed_at, "Link do podpisu wygasł"
                )
            )
        for index, event in enumerate(events):
            entry = _event_entry(r.id, index, event)
            if entry is not None:
                out.append(entry)
    return sorted(out, key=lambda e: e.at)


def _day(value: object) -> str:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return ""
    return moment.astimezone(_WARSAW).strftime("%d.%m.%Y")


def _event_entry(
    request_id: int, index: int, event: dict
) -> Optional[EsignHistoryEntry]:
    """Wpis z dziennika zdarzeń wniosku (0531, 27.10.2026)."""
    try:
        at = datetime.fromisoformat(str(event.get("at")))
    except ValueError:
        return None
    kind = event.get("kind")
    user_id = event.get("user_id")
    until = _day(event.get("until"))
    labels = {
        "expired": "Link do podpisu wygasł",
        "contractor_reminder": "Przypomnienie do kontraktora",
        "renewal_requested": "Kontraktor poprosił o nowy link",
        "extended": f"Termin przedłużony do {until}",
        "relinked": f"Nowy link do kontraktora, ten sam PDF, ważny do {until}",
    }
    label = labels.get(str(kind))
    if label is None:
        return None
    return EsignHistoryEntry(
        f"esign-{request_id}-{kind}-{index}",
        at,
        label,
        user_id if isinstance(user_id, int) else None,
    )
