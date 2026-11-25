"""Linki z maila z raportem kompetencji: zmiana warunków i wypis (decyzje Artura 25.11.2026).

Ten sam wzór co prośba o warunki (`candidate_terms`): w bazie tylko skrót SHA-256,
sekret żyje wyłącznie w mailu. Pętla wysyłki wystawia token przy wysyłce, strona
``/raport/[token]`` i trasy ``/api/public/competence-report/{token}`` go sprawdzają.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from app.core.config import settings
from app.services.candidate_terms import new_token, token_hash

TOKEN_TTL = timedelta(days=60)

__all__ = ["TOKEN_TTL", "ReportUrls", "new_token", "report_urls", "token_expiry", "token_hash"]


@dataclass(frozen=True)
class ReportUrls:
    edit_conditions_url: str
    unsubscribe_url: str
    one_click_unsubscribe_url: Optional[str]


def token_expiry(now: datetime) -> datetime:
    return now + TOKEN_TTL


def report_urls(raw_token: str) -> ReportUrls:
    """Adresy do maila. Strona NEXUSA (PUBLIC_BASE_URL) dla ludzi, API dla wypisu jednym kliknięciem (RFC 8058)."""
    base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    api = (settings.PUBLIC_API_BASE_URL or "").rstrip("/")
    return ReportUrls(
        edit_conditions_url=f"{base}/raport/{raw_token}",
        unsubscribe_url=f"{base}/raport/{raw_token}?wypis=1",
        one_click_unsubscribe_url=f"{api}/api/public/competence-report/{raw_token}/opt-out" if api else None,
    )
