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


# 0404: zgłoszenie z linku rekrutacji po przeglądzie AI — plakietka na karcie
# „Nowi” („AI: pasuje”, „AI: do sprawdzenia”, „AI nie oceniło”).
APPLICATION_SCREENING_KIND = "application_screening"
_SCREENING_VERDICTS = ("fits", "unclear", "not_fit")


def application_screening_entry_meta(
    *,
    verdict: str,
    assessed: bool,
    must_found: int,
    must_total: int,
    overridden: bool = False,
) -> dict:
    """Kształt ``entry_meta`` dla wejścia po przeglądzie zgłoszenia."""
    return {
        "kind": APPLICATION_SCREENING_KIND,
        "verdict": verdict if verdict in _SCREENING_VERDICTS else "unclear",
        "assessed": bool(assessed),
        "must_found": int(must_found),
        "must_total": int(must_total),
        "overridden": bool(overridden),
    }


def application_screening_badge(meta: Any) -> Optional[dict]:
    """Plakietka dla frontu — tylko znane pola; cokolwiek innego = ``None``."""
    if not isinstance(meta, dict) or meta.get("kind") != APPLICATION_SCREENING_KIND:
        return None
    verdict = meta.get("verdict")
    if verdict not in _SCREENING_VERDICTS:
        return None
    must_found = meta.get("must_found")
    must_total = meta.get("must_total")
    return {
        "verdict": verdict,
        "assessed": bool(meta.get("assessed")),
        "must_found": must_found if isinstance(must_found, int) else None,
        "must_total": must_total if isinstance(must_total, int) else None,
        "overridden": bool(meta.get("overridden")),
    }
