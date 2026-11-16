"""Strażnik widełek przy publikacji ogłoszenia na portalu (16.11.2026).

Od 24.12.2025 (Dz.U. 2025 poz. 807) kandydat na umowę o pracę dostaje
wynagrodzenie albo jego widełki przed rozmową. Publikacja (i ponowna wysyłka)
ogłoszenia bez widełek nie jest zabroniona, ale wymaga jawnego potwierdzenia
z powodem, który zostaje w ``job_postings.options.no_salary_reason``.

Dla B2B tekst mówi „zalecane” i nie przesądza zakresu prawa — Artur zapytał
prawnika. Lustro tekstów na froncie: ``frontend/src/lib/postingSalaryGuard.ts``.
Reguła: ``docs/claude/rekrutacja-tworzenie/widelki-w-ogloszeniu-albo-powod.md``.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

ContractForm = Literal["b2b", "uop"]

REASON_MIN_LENGTH = 3
REASON_MAX_LENGTH = 300

_UOP_WORDS = ("uop", "umowa o pracę", "umowa o prace", "umowę o pracę")


def contract_form(contract: Any) -> ContractForm:
    """Forma umowy z parametru ogłoszenia (``public_params(job)["contract"]``).

    Dziś każda rekrutacja to B2B (``job_public_profile.public_params``), więc
    wynik to ``b2b``; ścieżka UoP czeka na ogłoszenia na umowę o pracę.
    """
    text = " ".join(str(contract or "").casefold().split())
    return "uop" if any(word in text for word in _UOP_WORDS) else "b2b"


def missing_salary_message(form: ContractForm) -> str:
    if form == "uop":
        return (
            "Ogłoszenie nie ma widełek. Przy umowie o pracę prawo wymaga "
            "(od 24.12.2025, Dz.U. 2025 poz. 807), żeby kandydat poznał "
            "wynagrodzenie albo jego widełki przed rozmową. Wpisz widełki albo "
            "podaj powód publikacji bez nich."
        )
    return (
        "Ogłoszenie nie ma widełek. Przy B2B podanie widełek jest zalecane — "
        "czy przepisy o jawności wynagrodzeń obejmują ogłoszenia B2B, sprawdzamy "
        "z prawnikiem. Wpisz widełki albo podaj powód publikacji bez nich."
    )


def missing_reason(options: dict[str, Any]) -> bool:
    """Ogłoszenie bez widełek i bez powodu (ustawienia po ``normalize_options``)."""
    if options.get("salary"):
        return False
    reason: Optional[str] = options.get("no_salary_reason")
    return len((reason or "").strip()) < REASON_MIN_LENGTH
