"""Zdjęcie powiązania z kandydatem z prywatnych spotkań Outlooka (runda 8, R8-V3-3).

Prywatne spotkanie z Outlooka wchodzi do NEXUSA jako sam zajęty termin
(``calendar_privacy``). Powiązanie z kandydatem pochodziło z uczestników, więc
od rundy 7 (R7-V1-7) czyszczenie zdejmuje też ``candidate_id``. Wiersze
oczyszczone WCZEŚNIEJ zostały z kandydatem: przebieg starych spotkań
(``_scrub_old_private_events``) ma już ``done`` albo pomija wiersze bez treści,
a delta nie oddaje niezmienionych wydarzeń. Profil kandydata pokazywał więc
„Spotkanie prywatne” — czyli z kim było.

Jednorazowo (marker w ``app_settings`` + advisory lock) zdejmujemy
``candidate_id`` z oczyszczonych prywatnych wierszy z Outlooka: źródło M365,
założone poza NEXUSEM (``operational_owner_id IS NULL`` — ta sama reguła
pochodzenia co w synchronizacji), tytuł prywatny, bez opisu, miejsca, linków
i uczestników. Paragon: liczba i id wierszy, bez treści.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.services.calendar_privacy import PRIVATE_EVENT_TITLE
from app.services.m365.calendar import M365_SOURCE

logger = logging.getLogger(__name__)

REPAIR_MARKER = "m365_private_event_candidate_unlink_2026_09_26"

# Lustro ``calendar_privacy.is_scrubbed`` w SQL (puste = NULL albo '').
UNLINK_SQL = """
UPDATE calendar_events
   SET candidate_id = NULL
 WHERE external_source = :source
   AND operational_owner_id IS NULL
   AND candidate_id IS NOT NULL
   AND title = :title
   AND COALESCE(description, '') = ''
   AND COALESCE(location, '') = ''
   AND COALESCE(teams_link, '') = ''
   AND COALESCE(online_meeting_url, '') = ''
   AND (
        attendees IS NULL
        OR jsonb_typeof(attendees) = 'null'
        OR attendees = '[]'::jsonb
        OR attendees = '{}'::jsonb
   )
RETURNING id
"""


async def run_private_event_unlink(
    db: AsyncSession, *, marker: str = REPAIR_MARKER
) -> Optional[dict[str, Any]]:
    """Wykonaj korektę raz; ``None`` = już wykonana. Wołający commituje."""

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None
    ids = sorted(
        (
            await db.execute(
                text(UNLINK_SQL),
                {"source": M365_SOURCE, "title": PRIVATE_EVENT_TITLE},
            )
        )
        .scalars()
        .all()
    )
    summary = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "unlinked": len(ids),
        "event_ids": ids,
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info("m365 private event unlink: %s rows", len(ids))
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    return f"unlinked {summary['unlinked']} private Outlook events"


__all__ = [
    "REPAIR_MARKER",
    "UNLINK_SQL",
    "run_private_event_unlink",
    "summarize_for_log",
]
