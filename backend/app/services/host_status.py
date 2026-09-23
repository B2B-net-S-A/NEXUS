"""Stan hosta widziany z kontenera backendu (audyt 22.09 r2, PROD-01).

`/api/health.diskPercent` mierzy wyłącznie `/` kontenera (dysk hosta z
overlay2). Kopie zapasowe leżą na OSOBNYM wolumenie (98 GB, 48% 22.09,
zrzut Postgresa 0,83 → 3,16 GB w 6 dni — pełny ok. 10–12.10), którego nikt
nie obserwował. Cron na hoście co 15 min zapisuje atomowo (plik tymczasowy +
`mv`) `backup-volume.json` do katalogu montowanego read-only w kontenerze:

    {"used_percent": 48, "avail_gb": 51.2, "checked_at": "2026-09-22T10:00:00Z"}

Plik starszy niż `STALE_AFTER` = cron nie działa → procent `None` (sonda
`disk-alert.yml` pomija wtedy kontrolę, a nie alarmuje fałszywie zerem).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

BACKUP_VOLUME_FILE = "backup-volume.json"
STALE_AFTER = timedelta(hours=2)


def read_backup_volume(
    status_dir: str | Path, *, now: Optional[datetime] = None
) -> tuple[Optional[int], Optional[str]]:
    """(procent zajętości albo None, `checked_at` z pliku albo None)."""
    path = Path(status_dir) / BACKUP_VOLUME_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as exc:
        logger.warning("[health] backup-volume status unreadable: %r", exc)
        return None, None
    if not isinstance(raw, dict):
        return None, None
    checked_raw = raw.get("checked_at")
    checked_at: Optional[datetime] = None
    if isinstance(checked_raw, str):
        try:
            checked_at = datetime.fromisoformat(checked_raw.replace("Z", "+00:00"))
        except ValueError:
            checked_at = None
    if checked_at is not None and checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    checked_iso = checked_at.isoformat() if checked_at is not None else None
    now = now or datetime.now(timezone.utc)
    if checked_at is None or now - checked_at > STALE_AFTER:
        return None, checked_iso
    used = raw.get("used_percent")
    if isinstance(used, bool) or not isinstance(used, (int, float)):
        return None, checked_iso
    if not 0 <= used <= 100:
        return None, checked_iso
    return round(used), checked_iso
