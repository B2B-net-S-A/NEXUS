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

# „Nie akceptuje trybu pracy” (14.10.2026, migracja 0442): jedyny powód, który
# coś zapisuje poza procesem — tryb pracy na profilu kandydata
# (`candidate_notes_facts.set_work_mode_from_rejection`). Rozpoznawany po
# kluczu, jak `counter_offer` w ocenie ryzyka.
WORK_MODE_MISMATCH = "work_mode_mismatch"

# „Już po rozmowie u tego hiring managera” (20.10.2026, migracja 0484): osoba
# była na rozmowie u managera tej rekrutacji w innym procesie, więc nie idzie
# do niego drugi raz. Powód sytuacyjny, nie ocena osoby.
HM_ALREADY_INTERVIEWED = "hm_already_interviewed"

# „Za drogo” (26.10.2026, prośba Marka): odrzucenie ze słownika szablonu
# domyślnego (0006) i rezygnacja „Rozbieżność oczekiwań finansowych” (0068).
# Przy nich ruch może nieść nową stawkę osoby (`rejection_rate_hourly`) —
# trafia do profilu i „Stawki od” (`api/pipeline._record_rejection_rate`).
RATE_TOO_HIGH_REJECTED = "Za wysokie oczekiwania finansowe"
SALARY_MISMATCH = "salary_mismatch"
RATE_TOO_HIGH = frozenset({RATE_TOO_HIGH_REJECTED, SALARY_MISMATCH})

OTHER_LABEL = "Inne"

REJECTION_REASON_LABELS: dict[str, str] = {
    WORK_MODE_MISMATCH: "Nie akceptuje trybu pracy (biuro / hybryda)",
    HM_ALREADY_INTERVIEWED: "Już po rozmowie u tego hiring managera",
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


def needs_description(name: Optional[str]) -> bool:
    """Czy powód bez opisu nic nie mówi (20.10.2026).

    „Inne” to brak powodu, a „Już po rozmowie u tego hiring managera” bez
    wskazania rozmowy nie da się sprawdzić — przy obu ruch wymaga opisu.
    """
    if name is None:
        return False
    key = name.strip()
    return key == HM_ALREADY_INTERVIEWED or rejection_reason_label(key) == OTHER_LABEL


def is_rate_too_high(name: Optional[str]) -> bool:
    """Czy powód mówi „osoba chce więcej” — okno pyta wtedy o nową stawkę."""
    return name is not None and name.strip() in RATE_TOO_HIGH
