"""Etykiety powodów odrzucenia / rezygnacji do wyświetlenia.

``rejection_reasons.name`` jest KLUCZEM danych, nie tekstem dla człowieka:
migracja 0068 zasiała powody rezygnacji kodami (``counter_offer``,
``lost_interest``…), 0006 dwa „Inne” z dopiskiem kategorii (bo unikalność to
``(template_id, name, category)`` i czytelne rozróżnienie w panelu szablonów),
a import Traffita stempluje ``legacy_unknown``. Po tych nazwach szukają
importer i ocena ryzyka kandydata, więc zmiana wierszy w bazie zerwałaby
dopasowania — tłumaczymy przy odczycie, w jednym miejscu. Każda powierzchnia,
która pokazuje powód człowiekowi (okno odrzucenia, historia kandydata, weta
hiring managera, Insights), idzie przez :func:`rejection_reason_label`.
"""

from __future__ import annotations

from typing import Optional

REJECTION_REASON_LABELS: dict[str, str] = {
    "counter_offer": "Kontroferta od obecnego pracodawcy",
    "personal_reasons": "Powody osobiste",
    "lost_interest": "Stracił zainteresowanie",
    "accepted_other_offer": "Przyjął inną ofertę",
    "salary_mismatch": "Rozbieżność oczekiwań finansowych",
    "process_too_long": "Za długi proces",
    "legacy_unknown": "Powód nieznany (import z Traffita)",
    "Inne (rejected)": "Inne",
    "Inne (withdrawn)": "Inne",
}


def rejection_reason_label(name: Optional[str]) -> Optional[str]:
    """Polska etykieta powodu; nazwa spoza słownika wraca bez zmian."""
    if name is None:
        return None
    return REJECTION_REASON_LABELS.get(name.strip(), name)
