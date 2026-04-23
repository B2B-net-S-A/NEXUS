"""Microsoft 365 integration service package.

Public surface for other backend modules. Keeps imports short at call sites:

    from app.services.m365 import sync_connection, trigger_backfill
"""

from app.services.m365.provider import (
    EmailProvider,
    MatchResult,
    TokenBundle,
)
from app.services.m365.sync import SyncResult, sync_connection, trigger_backfill

__all__ = [
    "EmailProvider",
    "MatchResult",
    "TokenBundle",
    "SyncResult",
    "sync_connection",
    "trigger_backfill",
]
