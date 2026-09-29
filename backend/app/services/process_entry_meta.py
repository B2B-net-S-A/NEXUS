"""Wynik automatu przy wejściu do rekrutacji (0399, decyzja Artura 29.09.2026).

Do 29.09.2026 auto-match z CV i scraper JJIT/RocketJobs zapisywały wynik jako
NOTATKĘ („Auto-match score: 67/100 …”) — historia kandydata zarastała wpisami
automatów, między którymi ginęły notatki ludzi. Teraz wynik jedzie jako dane
procesu (``recruitment_processes.entry_meta``) i jest plakietką przy procesie:
na karcie Tablicy i w zakładce „Rekrutacje” profilu („Auto-match 67/100 · JJIT”).
"""

from __future__ import annotations

from typing import Any, Optional

AUTO_MATCH_KIND = "auto_match"


def auto_match_entry_meta(
    *,
    score: Optional[float],
    source: str,
    must_hit: list[str],
    must_total: Optional[int],
    trigger: Optional[str] = None,
) -> dict:
    """Kształt ``entry_meta`` dla wejścia z automatu."""
    meta: dict[str, Any] = {
        "kind": AUTO_MATCH_KIND,
        "score": int(round(score or 0)),
        "source": source,
        "must_hit": [str(m)[:80] for m in must_hit[:8]],
        "must_total": must_total,
    }
    if trigger:
        meta["trigger"] = trigger
    return meta


def auto_match_badge(meta: Any) -> Optional[dict]:
    """Plakietka dla frontu — tylko znane pola; cokolwiek innego = ``None``."""
    if not isinstance(meta, dict) or meta.get("kind") != AUTO_MATCH_KIND:
        return None
    score = meta.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return None
    must_hit = meta.get("must_hit")
    must_total = meta.get("must_total")
    return {
        "score": int(round(score)),
        "source": str(meta.get("source") or ""),
        "must_hit": [str(m) for m in must_hit] if isinstance(must_hit, list) else [],
        "must_total": must_total if isinstance(must_total, int) else None,
    }
