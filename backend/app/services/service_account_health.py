"""Sonda `checks.service_account_keys` w `/api/health` (runda 9, R9-N9-9).

Klucze kont serwisowych mają obowiązkowy termin (`expires_at`, domyślnie
90 dni). Do rundy 9 nic nie ostrzegało, że termin się zbliża — integracja
(np. COMPASS → NEXUS po `contractors:read`) przestawała działać w dniu
wygaśnięcia, a pierwszym sygnałem był 401 po drugiej stronie.

`degraded`, gdy AKTYWNE konto nie ma ważnego klucza albo jego najpóźniej
wygasający ważny klucz wygasa w ciągu `EXPIRY_WARNING_DAYS`. Sonda jest
informacyjna — nigdy `unhealthy`, nie zmienia `status` ani kodu HTTP.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import text

EXPIRY_WARNING_DAYS = 14

_LATEST_VALID_KEY_SQL = text(
    """
    SELECT a.id,
           max(k.expires_at) FILTER (
               WHERE k.revoked_at IS NULL AND k.expires_at > now()
           ) AS latest_valid_expiry
    FROM service_accounts a
    LEFT JOIN service_account_keys k ON k.service_account_id = a.id
    WHERE a.is_active
    GROUP BY a.id
    """
)


def service_account_keys_verdict(
    latest_valid_expiry: Iterable[Optional[datetime]], *, now: datetime
) -> str:
    """``unconfigured`` / ``healthy`` / ``degraded`` — czysta funkcja.

    Wejście: dla każdego aktywnego konta termin jego najpóźniej wygasającego
    WAŻNEGO klucza (``None`` = konto bez ważnego klucza).
    """
    rows = list(latest_valid_expiry)
    if not rows:
        return "unconfigured"
    horizon = now + timedelta(days=EXPIRY_WARNING_DAYS)
    for expiry in rows:
        if expiry is None or expiry <= horizon:
            return "degraded"
    return "healthy"


async def load_latest_valid_expiry(session) -> list[Optional[datetime]]:
    """Po jednym wierszu na aktywne konto serwisowe."""
    result = await session.execute(_LATEST_VALID_KEY_SQL)
    return [row[1] for row in result.all()]


__all__ = [
    "EXPIRY_WARNING_DAYS",
    "load_latest_valid_expiry",
    "service_account_keys_verdict",
]
