"""Słowa według formy współpracy (etap 2, D1 i D4, 17.10.2026).

Prawie cała firma jest na B2B albo zleceniu, umowa o pracę zdarza się
pojedynczo. Od 08.07.2026 inspektor PIP może sam stwierdzić stosunek pracy,
a „wniosek urlopowy” akceptowany przez „przełożonego” to typowy sygnał
podporządkowania. Dlatego każdy tekst modułu (powiadomienia, maile, ekrany,
PDF raportu godzin) bierze słowa z formy osoby:

* umowa o pracę — urlop, wniosek, przełożony, ewidencja czasu pracy, lista płac,
* B2B — przerwa w świadczeniu usług, zgłoszenie, koordynator, raport godzin,
  faktura,
* zlecenie — nieobecność, zgłoszenie, koordynator, potwierdzenie godzin
  (art. 8b ustawy o minimalnym wynagrodzeniu); dokumentem rozliczenia jest
  to samo potwierdzenie godzin z kwotą brutto — bez osobnego rachunku (R3).

Brak formy (osoba bez kartoteki) = jak umowa o pracę. ``EMPLOYMENT_TERMS`` ma
lustro słowo w słowo we froncie (``frontend/src/lib/hr-employment-terms.ts``,
strażnik ``tests/test_hr_employment_terms_mirror.py``); zdania składane tylko
w backendzie (tytuły powiadomień o raporcie godzin, podpisy PDF) są niżej,
w ``BACKEND_TERMS``.
"""

from __future__ import annotations

from typing import Optional

#: Formy, na których nieobecność jest zgłoszeniem, a nie wnioskiem (D5) — to
#: samo co „kontraktor” w urlopach i godzinach: tylko urlop z puli, a dzień puli
#: rozlicza się jak dzień pracy. Jedyne źródło tej listy w module.
REPORT_FORMS: frozenset[str] = frozenset({"b2b", "zlecenie"})

DEFAULT_FORM = "uop"

EMPLOYMENT_TERMS: dict[str, dict[str, str]] = {
    "uop": {
        "form": "Umowa o pracę",
        "form_short": "UoP",
        "flow": "request",
        "absence": "urlop",
        "absence_short": "urlop",
        "absence_accusative": "urlop",
        "absence_instrumental": "urlopem",
        "absences_title": "Urlop",
        "request": "wniosek",
        "submit_action": "Złóż wniosek urlopowy",
        "dialog_title": "Wniosek o nieobecność",
        "coordinator": "przełożony",
        "coordinator_genitive": "przełożonego",
        "timesheet": "Ewidencja czasu pracy",
        "timesheet_accusative": "ewidencję czasu pracy",
        "timesheet_genitive": "ewidencji czasu pracy",
        "review_verb": "akceptuje",
        "review_noun": "akceptacji",
        "settlement": "Lista płac",
        "person": "Pracownik",
    },
    "b2b": {
        "form": "B2B",
        "form_short": "B2B",
        "flow": "report",
        "absence": "przerwa w świadczeniu usług",
        "absence_short": "przerwa",
        "absence_accusative": "przerwę w świadczeniu usług",
        "absence_instrumental": "przerwą w świadczeniu usług",
        "absences_title": "Przerwy",
        "request": "zgłoszenie",
        "submit_action": "Zgłoś przerwę",
        "dialog_title": "Zgłoś przerwę w świadczeniu usług",
        "coordinator": "koordynator",
        "coordinator_genitive": "koordynatora",
        "timesheet": "Raport godzin",
        "timesheet_accusative": "raport godzin",
        "timesheet_genitive": "raportu godzin",
        "review_verb": "potwierdza",
        "review_noun": "potwierdzenia",
        "settlement": "Faktura",
        "person": "Wykonawca",
    },
    "zlecenie": {
        "form": "Umowa zlecenie",
        "form_short": "Zlecenie",
        "flow": "report",
        "absence": "nieobecność",
        "absence_short": "nieobecność",
        "absence_accusative": "nieobecność",
        "absence_instrumental": "nieobecnością",
        "absences_title": "Nieobecności",
        "request": "zgłoszenie",
        "submit_action": "Zgłoś nieobecność",
        "dialog_title": "Zgłoś nieobecność",
        "coordinator": "koordynator",
        "coordinator_genitive": "koordynatora",
        "timesheet": "Potwierdzenie godzin",
        "timesheet_accusative": "potwierdzenie godzin",
        "timesheet_genitive": "potwierdzenia godzin",
        "review_verb": "potwierdza",
        "review_noun": "potwierdzenia",
        "settlement": "Potwierdzenie godzin",
        "person": "Zleceniobiorca",
    },
}

#: Zdania, które składa tylko backend (powiadomienia o raporcie godzin, PDF,
#: powiadomienia o nieobecności). Tytuły bez rodzaju nieobecności (D6).
BACKEND_TERMS: dict[str, dict[str, str]] = {
    "uop": {
        "timesheet_document": "Ewidencja czasu pracy",
        "timesheet_document_note": "",
        "reviewer": "Akceptujący",
        "reviewed_by": "Zaakceptował",
        "timesheet_submitted_title": "Ewidencja czasu pracy do akceptacji",
        "timesheet_approved_title": "Ewidencja czasu pracy zaakceptowana",
        "timesheet_returned_title": "Ewidencja czasu pracy zwrócona do poprawy",
        "timesheet_revoked_title": "Cofnięto akceptację ewidencji czasu pracy",
        "reported_title": "Zgłoszona nieobecność",
        "cancelled_title": "Nieobecność anulowana",
        "conflict_title": "Kolizja z Twoją nieobecnością",
    },
    "b2b": {
        "timesheet_document": "Raport godzin",
        "timesheet_document_note": "",
        "reviewer": "Koordynator",
        "reviewed_by": "Potwierdził",
        "timesheet_submitted_title": "Raport godzin do potwierdzenia",
        "timesheet_approved_title": "Raport godzin potwierdzony",
        "timesheet_returned_title": "Raport godzin zwrócony do poprawy",
        "timesheet_revoked_title": "Cofnięto potwierdzenie raportu godzin",
        "reported_title": "Zgłoszona przerwa w świadczeniu usług",
        "cancelled_title": "Przerwa w świadczeniu usług anulowana",
        "conflict_title": "Kolizja z Twoją przerwą w świadczeniu usług",
    },
    "zlecenie": {
        "timesheet_document": "Potwierdzenie liczby godzin",
        "timesheet_document_note": (
            "art. 8b ustawy o minimalnym wynagrodzeniu za pracę — "
            "przechowywane 3 lata od dnia wypłaty"
        ),
        "reviewer": "Zleceniodawca",
        "reviewed_by": "Potwierdził",
        "timesheet_submitted_title": "Godziny ze zlecenia do potwierdzenia",
        "timesheet_approved_title": "Potwierdzenie godzin przyjęte",
        "timesheet_returned_title": "Potwierdzenie godzin zwrócone do poprawy",
        "timesheet_revoked_title": "Cofnięto przyjęcie potwierdzenia godzin",
        "reported_title": "Zgłoszona nieobecność",
        "cancelled_title": "Nieobecność anulowana",
        "conflict_title": "Kolizja z Twoją nieobecnością",
    },
}

assert set(EMPLOYMENT_TERMS) == set(BACKEND_TERMS)
assert len({frozenset(words) for words in EMPLOYMENT_TERMS.values()}) == 1
assert len({frozenset(words) for words in BACKEND_TERMS.values()}) == 1
assert REPORT_FORMS < set(EMPLOYMENT_TERMS)

#: Nazwa formy (PDF raportu godzin) i jej skrót (eksport płac). Brak klucza =
#: forma nieznana — wołający decyduje, co wtedy pisze („—” w PDF, pusto w XLSX).
FORM_LABELS: dict[str, str] = {
    form: words["form"] for form, words in EMPLOYMENT_TERMS.items()
}
FORM_SHORT_LABELS: dict[str, str] = {
    form: words["form_short"] for form, words in EMPLOYMENT_TERMS.items()
}


def form_of(employment_type: Optional[str]) -> str:
    """Forma do słów: nieznana albo brak = umowa o pracę."""

    return employment_type if employment_type in EMPLOYMENT_TERMS else DEFAULT_FORM


def terms(employment_type: Optional[str]) -> dict[str, str]:
    """Słowa formy (wspólne z frontem i backendowe w jednym słowniku)."""

    form = form_of(employment_type)
    return {**EMPLOYMENT_TERMS[form], **BACKEND_TERMS[form]}


def reports_absence(employment_type: Optional[str]) -> bool:
    """B2B i zlecenie zgłaszają nieobecność, nikt jej nie akceptuje (D5)."""

    return employment_type in REPORT_FORMS


def returned_titles() -> frozenset[str]:
    """Tytuły zwrotu raportu godzin (mail nie niesie wtedy uwag akceptującego)."""

    return frozenset(
        words["timesheet_returned_title"] for words in BACKEND_TERMS.values()
    )


__all__ = [
    "BACKEND_TERMS",
    "EMPLOYMENT_TERMS",
    "FORM_LABELS",
    "FORM_SHORT_LABELS",
    "REPORT_FORMS",
    "form_of",
    "reports_absence",
    "returned_titles",
    "terms",
]
