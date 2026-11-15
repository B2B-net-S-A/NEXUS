"""Odczyt maila na stanowiska zespołu (Z4): jedno zapytanie klienta → lista ról.

Reguły: ``docs/claude/klienci/zespol-dla-klienta.md`` („Z4 i odczyt maila”).
Model proponuje stanowiska, kod je ugruntowuje tą samą regułą co wiersze
wymagań odczytu requestu (``job_request_intake._ground_row``): słowo kluczowe,
którego nie ma w mailu, wypada, a liczba osób przechodzi tylko z dosłownym
cytatem zawierającym tę liczbę (inaczej 1). Wynik to dodatek: Delivery Lead
i tak zakłada rekrutacje sam, więc wołający zamienia awarię na pustą listę.
"""

from __future__ import annotations

from typing import Any, Optional

from app.models.ai_feature import AIFeatureKey
from app.services import job_request_intake as intake
from app.services import keyword_suggest
from app.services.ai_models import model_for
from app.services.llm_prompts import TEAM_REQUEST_SPLIT

# Telemetria i model jak odczyt requestu na /jobs/new (`api/job_request_intake.py`
# liczy go pod `champion_draft`). Własny klucz wymagałby wartości enuma
# `aifeaturekey`, czyli migracji (zob. reguła zespołu).
FEATURE = AIFeatureKey.champion_draft

MIN_TEXT_CHARS = 20
MAX_TEXT_CHARS = 20_000
MAX_POSITIONS = 30
MAX_WORDS = 8
TITLE_MAX_CHARS = 120
SENIORITY = ("junior", "regular", "senior")


def model_name() -> str:
    return model_for(FEATURE)


def _seniority(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().casefold()
    return cleaned if cleaned in SENIORITY else None


def _words(value: Any, folded_text: str, technologies: set[str]) -> list[str]:
    """Słowa kluczowe stanowiska, każde z maila; bez odpowiedników spoza tekstu."""
    out: list[str] = []
    for raw in value if isinstance(value, list) else []:
        word = intake._text(raw, 100)
        if not word:
            continue
        word = " ".join(word.replace("|", " ").split())
        if len(word) < 2 and keyword_suggest.fold(word) not in technologies:
            continue
        kept = intake._grounded_search_word(word, folded_text, technologies)
        if kept is None or kept.casefold() in {w.casefold() for w in out}:
            continue
        out.append(kept)
        if len(out) >= MAX_WORDS:
            break
    return out


def normalize_positions(raw: Any, text: str) -> list[dict[str, Any]]:
    """Odpowiedź modelu → ``[{title, headcount, seniority, words}]``.

    Zły kształt = pusta lista. Stanowisko bez tytułu wypada. Liczba osób spoza
    1–50 albo bez cytatu z maila = 1 (``job_request_intake._headcount``).
    """
    items = raw.get("positions") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    folded_text = intake._fold(text)
    technologies = intake._technology_keys()
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = intake._text(item.get("title"), TITLE_MAX_CHARS)
        if not title:
            continue
        count, _quote = intake._headcount(item, folded_text)
        out.append(
            {
                "title": title,
                "headcount": count if count is not None else 1,
                "seniority": _seniority(item.get("seniority")),
                "words": _words(item.get("words"), folded_text, technologies),
            }
        )
        if len(out) >= MAX_POSITIONS:
            break
    return out


async def read_positions(text: str) -> list[dict[str, Any]]:
    """Jeden odczyt przez model. Wołający otwiera ``ai_feature``."""
    from app.services.champion_draft_service import _call_claude_json
    from app.services.prompt_fencing import neutralize_tags

    text = text[:MAX_TEXT_CHARS]
    raw = await _call_claude_json(
        prompt=TEAM_REQUEST_SPLIT.render(request_text=neutralize_tags(text)),
        system_prompt=TEAM_REQUEST_SPLIT.system_prompt or "",
        model=model_name(),
        max_tokens=3000,
    )
    return normalize_positions(raw, text)
