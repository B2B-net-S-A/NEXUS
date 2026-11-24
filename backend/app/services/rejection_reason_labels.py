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

from app.services.close_reasons import labels_by_template_name

# „Nie akceptuje trybu pracy” (14.10.2026, migracja 0442): jedyny powód, który
# coś zapisuje poza procesem — tryb pracy na profilu kandydata
# (`candidate_notes_facts.set_work_mode_from_rejection`). Rozpoznawany po
# kluczu, jak `counter_offer` w ocenie ryzyka.
WORK_MODE_MISMATCH = "work_mode_mismatch"

# „Mieszka poza Polską” (24.11.2026, migracja 0768): drugi powód, który zapisuje
# coś na profilu — kraj zamieszkania (`residence.record_from_rejection`).
OUTSIDE_POLAND = "outside_poland"

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

# „Zatrudniony gdzie indziej” (04.11.2026): ruch zapisuje w profilu „Nie szuka”
# na 3 miesiące (`autofill_feedback.mark_employed_elsewhere`).
EMPLOYED_ELSEWHERE = "Zatrudniony gdzie indziej"

# Sześć powodów, które zespół wpisywał ręcznie pod „Inne” (04.11.2026, migracja
# 0646). Które pokazać przy którym „Kto kończy?”, decyduje okno
# (`reasonFitsEndedBy` na froncie). Nie wymagają opisu i nie są werdyktem o osobie.
NOT_LOOKING_FOR_WORK = "not_looking_for_work"
CLIENT_CONFLICT = "client_conflict"
CONTRACT_FORM = "contract_form"
NO_CONTACT = "no_contact"
CLIENT_NO_REASON = "client_no_reason"
CLIENT_CHOSE_OTHER = "client_chose_other"

# Dwa powody klienta z odczytu maili CPro (19.11.2026, migracja 0740, sprawa B7).
# Tylko przy „Odrzuca klient”. Inny dostawca to sytuacja (duplikat zgłoszenia,
# tańsza oferta), więc nie jest werdyktem o osobie. Słaba rozmowa jest: manager
# poznał osobę i powiedział nie, więc uruchamia weto `hiring_manager_verdicts`.
CLIENT_OTHER_VENDOR = "client_other_vendor"
CLIENT_INTERVIEW_WEAK = "client_interview_weak"

# Końce procesu bez decyzji klienta o osobie (08.11.2026, 0663): zamknięcie
# requestu i klient, który przez 30 dni nie odpowiedział. Nie wybiera się ich
# ręcznie w oknie odrzucenia.
REQUEST_CLOSED = "request_closed"
CLIENT_NO_RESPONSE = "client_no_response"
# Powody, które nie mówią nic o osobie: ranking ich nie liczy jako odrzucenia.
CLIENT_NOT_A_VERDICT = (
    CLIENT_CHOSE_OTHER,
    REQUEST_CLOSED,
    CLIENT_NO_RESPONSE,
    CLIENT_OTHER_VENDOR,
)

OTHER_LABEL = "Inne"

# Etykiety powodów słownika (19.11.2026, `close_reasons.py`) wygrywają ze
# starszymi: ten sam klucz ma w oknie, historii i raportach jedną nazwę.
# Zostają tu tylko nazwy spoza słownika (stare wpisy i końce bez wyboru).
REJECTION_REASON_LABELS: dict[str, str] = {
    CLIENT_CONFLICT: "Pracuje u klienta lub nie chce do klienta",
    REQUEST_CLOSED: "Request zamknięty",
    CLIENT_NO_RESPONSE: "Klient nie odpowiedział",
    "legacy_unknown": "Powód nieznany (import z Traffita)",
    **labels_by_template_name(),
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
