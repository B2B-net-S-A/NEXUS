"""Polska odmiana nazw technologii ze słownika — wspólna reguła (06.10.2026).

Odczyt maila z requestem (audyt 06.10.2026, P1): klient pisze „znajomość
Javy, Springa, doświadczenie z Dockerem”, a model oddaje albo formę z maila
(„Javy” — zapisywała się odmieniona, bramka krytycznych i tytuł roboczy jej nie
znały), albo formę podstawową („Java” — wiersz wypadał po cichu, bo „Java”
nie stoi w mailu jako całe słowo).

Mechanizm odmiany jest jeden — końcówki z ``dz_review`` (QC CV i przegląd DZ
czytają nim „w Pythonie”, „z Dockerem”). Tu tylko dwa pytania na nim oparte;
z tych samych funkcji korzysta dowód must w wyszukiwaniu.
"""

from __future__ import annotations

from typing import Callable, Optional

from app.services.skill_normalize import is_gate_technology


def dictionary_base_name(
    word: str, *, known: Optional[Callable[[str], bool]] = None
) -> Optional[str]:
    """Forma podstawowa odmienionej technologii ze słownika albo ``None``.

    „Javy” → „Java”, „Dockerem” → „Docker”, „Pythonie” → „Python”. Słowo,
    które już jest nazwą ze słownika, i słowo, którego żadna forma podstawowa
    nie jest technologią, dają ``None``. Wielkość liter idzie za słowem
    z tekstu („javy” → „java”). ``known`` pozwala wskazać inny słownik niż
    ``is_gate_technology`` (odczyt maila pyta katalog podpowiedzi).
    """
    from app.services.dz_review import polish_base_forms  # noqa: PLC0415

    is_known = known or is_gate_technology
    text = (word or "").strip()
    if not text or " " in text or is_known(text):
        return None
    lower = text.casefold()
    for base in polish_base_forms(text):
        if not is_known(base):
            continue
        if lower.startswith(base):
            return text[: len(base)]
        return text[: len(base) - 1] + base[-1]
    return None


def inflected_in_text(name: str, folded_text: str) -> bool:
    """Czy odmieniona forma technologii ``name`` stoi w tekście jako całe słowo.

    ``folded_text`` to tekst bez polskich znaków i małymi literami (jak
    ``job_request_intake._fold``) — końcówki „ę”/„ą” znikają wtedy razem
    z resztą znaków, a „Javą” to po prostu „java”.
    """
    from app.services.dz_review import _inflected_pattern  # noqa: PLC0415

    pattern = _inflected_pattern(name or "")
    return pattern is not None and pattern.search(folded_text) is not None


__all__ = ["dictionary_base_name", "inflected_in_text"]
