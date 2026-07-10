"""Fragment „stawka godzinowa" umowy B2B — pojedyncza lub progresywna.

Buduje tekst dla ``{{ b2b.rate_clause }}`` w szablonach DOCX i HTML (zdanie §5:
„…stawki godzinowej w wysokości {rate_clause} netto + VAT”).

Pojedynczy etap bez dat renderuje się IDENTYCZNIE jak historyczne
„{{ rate }} {{ currency }} (słownie: {{ words }})”, więc stare zapisy
``render_payload`` (ponowne pobranie z „Wygenerowanych umów”) dają treściowo
ten sam dokument. Kilka etapów („stawka progresywna”) → wyliczenie z okresami:

    150 PLN (słownie: sto pięćdziesiąt złotych) w okresie od dnia 01.07.2026
    do dnia 31.12.2026, a 160 PLN (słownie: sto sześćdziesiąt złotych)
    od dnia 01.01.2027

Moduł-liść jak ``formatting``/``number_words`` — importuje wyłącznie z tych
dwóch, więc nadaje się i do ``render_context`` (standalone) i do
``_contract_vars`` (ścieżka /generate) bez cykli importów.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence

from app.services.b2b_contract_generator.formatting import format_rate, pl_date
from app.services.b2b_contract_generator.number_words import rate_in_words

# Wizualny placeholder niewypełnionego pola (jak blanki w oryginale umowy).
_DOTS = "………"


@dataclass(frozen=True)
class RateStage:
    """Jeden etap stawki: kwota + opcjonalne „Obowiązuje od/do".

    ``rate`` przyjmuje float/Decimal (formularz vs kolumna Numeric) — oba typy
    przechodzą przez ``format_rate``/``rate_in_words`` bez konwersji.
    """

    rate: Optional[object]
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


def _normalize_language(language: Optional[str]) -> str:
    return "en" if (language or "pl").lower().startswith("en") else "pl"


def _amount_with_words(
    stage: RateStage, currency: str, lang: str, words_override: Optional[str]
) -> str:
    amount = format_rate(stage.rate) or "…"
    words = (
        words_override
        or (rate_in_words(stage.rate, lang, currency) if stage.rate is not None else "")
        or _DOTS
    )
    label = "słownie" if lang == "pl" else "in words"
    return f"{amount} {currency} ({label}: {words})"


def _period_phrase(stage: RateStage, lang: str) -> str:
    """„w okresie od dnia X do dnia Y” / „od dnia X” / „do dnia Y” (albo '')."""
    start, end = stage.effective_from, stage.effective_to
    if start and end:
        if lang == "pl":
            return f"w okresie od dnia {pl_date(start)} do dnia {pl_date(end)}"
        return f"in the period from {pl_date(start)} to {pl_date(end)}"
    if start:
        return f"od dnia {pl_date(start)}" if lang == "pl" else f"from {pl_date(start)}"
    if end:
        return f"do dnia {pl_date(end)}" if lang == "pl" else f"until {pl_date(end)}"
    return ""


def build_rate_clause(
    stages: Sequence[RateStage],
    *,
    language: Optional[str],
    currency: Optional[str],
    words_override: Optional[str] = None,
) -> str:
    """Tekst do ``{{ b2b.rate_clause }}``.

    ``words_override`` (ręczna „stawka słownie”) dotyczy tylko pojedynczego
    etapu — przy progresji każda kwota dostaje własne „słownie” automatycznie.
    Pusta lista → klauzula z placeholderami (jak niewypełniony formularz).
    """
    lang = _normalize_language(language)
    cur = (currency or "PLN").strip() or "PLN"
    if not stages:
        stages = [RateStage(rate=None)]
    parts: list[str] = []
    for stage in stages:
        base = _amount_with_words(
            stage, cur, lang, words_override if len(stages) == 1 else None
        )
        period = _period_phrase(stage, lang)
        parts.append(f"{base} {period}" if period else base)
    joiner = ", a " if lang == "pl" else ", and "
    return joiner.join(parts)
