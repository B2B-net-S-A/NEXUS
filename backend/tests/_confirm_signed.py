"""Wywołanie „Oznacz jako podpisaną” w testach: plik obowiązkowy (06.11.2026).

Domyślnie skan bez podpisu elektronicznego (podpis odręczny), więc dzień
podpisu i powód idą w ``payload``; dzień domyślnie dziś w kalendarzu firmy.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional

from app.core.scheduling import business_today
from tests._signed_pdf import blank_pdf

MANUAL_REASON = "podpis odręczny (test)"


def confirm_request(
    payload: Optional[dict[str, Any]] = None,
    *,
    pdf: Optional[bytes] = None,
    signed_on: Optional[date] = None,
    reason: Optional[str] = MANUAL_REASON,
) -> dict[str, Any]:
    """``data`` i ``files`` do ``app_client.post`` na ``confirm-fully-signed``."""
    body: dict[str, Any] = dict(payload or {})
    if pdf is None:
        body.setdefault("signed_on", (signed_on or business_today()).isoformat())
        if reason is not None:
            body.setdefault("signed_on_reason", reason)
    elif signed_on is not None:
        body["signed_on"] = signed_on.isoformat()
    return {
        "data": {"payload": json.dumps(body)},
        "files": {
            "file": ("umowa-podpisana.pdf", pdf or blank_pdf(), "application/pdf")
        },
    }
