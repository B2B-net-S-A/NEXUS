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


# 0515 (23.10.2026): osoba dodana przez silnik „Nowi na 20” — plakietka
# „Od systemu · 81%”, powód w panelu osoby i termin decyzji.
AUTOFILL_KIND = "autofill"


def _names(value: Any) -> list[str]:
    return [str(v)[:80] for v in value[:10]] if isinstance(value, list) else []


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _days(n: int) -> str:
    return "1 dzień" if n == 1 else f"{n} dni"


def _zl(value: Any) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return (
        f"{value:.0f}"
        if float(value).is_integer()
        else f"{value:.2f}".replace(".", ",")
    )


def _caution(raw: Any) -> Optional[dict]:
    """Ostrzeżenie z migawki (27.10.2026, km od 29.10.2026) → napis karty i dymek;
    zły kształt = ``None``."""
    if not isinstance(raw, dict):
        return None
    key = raw.get("key")
    required = _int(raw.get("required_days"))
    if key == "budget":
        pct, rate, budget = (
            _int(raw.get("over_pct")),
            _zl(raw.get("rate")),
            _zl(raw.get("budget")),
        )
        if pct is None or rate is None or budget is None:
            return None
        return {
            "key": key,
            "label": f"+{pct}% budżetu",
            "title": f"„Stawka od” {rate} zł/h, budżet {budget} zł/h.",
        }
    if key == "office_city":
        city = raw.get("city") if isinstance(raw.get("city"), str) else None
        office = raw.get("office") if isinstance(raw.get("office"), str) else None
        km = _int(raw.get("km"))
        if km is None and not required:
            return None
        if km is not None:
            label = f"{city} · {km} km" if city else f"{km} km od biura"
            lives = (
                f"Mieszka: {city or 'inne miasto'}, ok. {km} km od najbliższego biura."
            )
        else:
            label = f"Inne miasto: {city}" if city else "Inne miasto"
            lives = f"Mieszka: {city or 'inne miasto'}."
        days = f", {_days(required)} w tygodniu." if required else "."
        return {
            "key": key,
            "label": label,
            "title": f"{lives} Biuro klienta: {office or 'inne miasto'}{days}",
        }
    if not required:
        return None
    if key == "office_days":
        have = _int(raw.get("candidate_days"))
        if have is None:
            return None
        return {
            "key": key,
            "label": f"Biuro: {have} z {_days(required)}",
            "title": (
                f"Według profilu przyjmie {_days(have)} w biurze w tygodniu, "
                f"klient chce {_days(required)}."
            ),
        }
    if key == "remote_only":
        return {
            "key": key,
            "label": "Tylko zdalnie",
            "title": (
                "Według profilu albo notatek chce pracować wyłącznie zdalnie, "
                f"klient chce {_days(required)} w biurze w tygodniu."
            ),
        }
    return None


def autofill_badge(meta: Any, *, waiting_days: Optional[int]) -> Optional[dict]:
    """Plakietka osoby od systemu — tylko znane pola; cokolwiek innego = ``None``."""
    from app.services.autofill_decisions import decided, decision_due

    if not isinstance(meta, dict) or meta.get("kind") != AUTOFILL_KIND:
        return None
    score = meta.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return None
    return {
        "score": int(round(score)),
        "matched_must": _names(meta.get("matched_must")),
        "missing_must": _names(meta.get("missing_must")),
        "rate_known": meta.get("rate_from_hourly") is not None,
        "availability_known": bool(meta.get("availability_date")),
        "decided": decided(meta),
        "waiting_days": waiting_days,
        "decision_due": decision_due(waiting_days),
        "cautions": [
            c
            for c in (_caution(raw) for raw in (meta.get("cautions") or []))
            if c is not None
        ]
        if isinstance(meta.get("cautions"), list)
        else [],
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
    deal_breaker: Optional[str] = None,
    link_owner_id: Optional[int] = None,
) -> dict:
    """Kształt ``entry_meta`` dla wejścia po przeglądzie zgłoszenia.

    ``deal_breaker`` (04.10.2026) = treść warunku „Odpada, gdy…”, który według
    AI może łamać CV (z cytatem obecnym w CV). Tylko plakietka „AI: możliwy
    deal-breaker — sprawdź” — werdykt (`decide`) się od tego nie zmienia.
    """
    meta = {
        "kind": APPLICATION_SCREENING_KIND,
        "verdict": verdict if verdict in _SCREENING_VERDICTS else "unclear",
        "assessed": bool(assessed),
        "must_found": int(must_found),
        "must_total": int(must_total),
        "overridden": bool(overridden),
    }
    if deal_breaker:
        meta["deal_breaker_hit"] = True
        meta["deal_breaker"] = str(deal_breaker)[:300]
    if link_owner_id is not None:
        meta[LINK_OWNER_KEY] = int(link_owner_id)
    return meta


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
        # 04.10.2026: „AI: możliwy deal-breaker — sprawdź”.
        "deal_breaker_hit": meta.get("deal_breaker_hit") is True,
        "deal_breaker": (
            meta["deal_breaker"]
            if meta.get("deal_breaker_hit") is True
            and isinstance(meta.get("deal_breaker"), str)
            else None
        ),
    }


# Etap 2 linków rekrutacji (19.10.2026): czyj link przyprowadził osobę.
# Stempel zostaje przy procesie także wtedy, gdy blokada wygaśnie, karta
# zmieni właściciela albo konto właściciela linku stanie się nieaktywne —
# plakietka „Z linku …” na Tablicy i atrybucja statystyk „Pozyskani z linków”.
APPLICATION_LINK_KIND = "application_link"
LINK_OWNER_KEY = "link_owner_id"
_LINK_OWNER_KINDS = (APPLICATION_LINK_KIND, APPLICATION_SCREENING_KIND)


def application_link_entry_meta(link_owner_id: int) -> dict:
    """Kształt ``entry_meta`` zgłoszenia z linku bez przeglądu AI."""
    return {"kind": APPLICATION_LINK_KIND, LINK_OWNER_KEY: int(link_owner_id)}


def application_link_owner_id(meta: Any) -> Optional[int]:
    """Właściciel linku, z którego przyszło zgłoszenie; ``None`` = nie z linku."""
    if not isinstance(meta, dict) or meta.get("kind") not in _LINK_OWNER_KINDS:
        return None
    owner = meta.get(LINK_OWNER_KEY)
    if not isinstance(owner, int) or isinstance(owner, bool):
        return None
    return owner
