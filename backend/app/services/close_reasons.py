"""Jeden słownik powodów zamknięcia procesu kandydata (decyzja Artura 19.11.2026).

Do 19.11 NEXUS pytał o powód z czterech list: okno „Nowych”/„Screeningu”
(powody dla systemu, ``autofill_feedback``), lista z szablonu procesu od
„Zweryfikowanego”, osobne okno rezygnacji i porcja dnia. 8 z 19 powodów okna
lądowało w szablonie jako „Inne” z nazwą w opisie, a „Inne” to 22% odrzuceń
w „Nowych”/„Screeningu” i 27% u klienta (kopia produkcji, 60 dni).

Teraz każdy powód słownika ma własny klucz w ``rejection_reasons`` każdego
szablonu (migracja 0745 + lustro w ``entrypoint.sh``). Klucz słownika jest
jednocześnie powodem dla systemu (``autofill_feedback.reason``), więc okno
pyta raz, a powód z szablonu wynika 1:1. Tam, gdzie szablon miał już powód
o tym znaczeniu, słownik go używa (``Brak doświadczenia``, ``work_mode_mismatch``,
``Zatrudniony gdzie indziej``…): po tych nazwach szukają ocena ryzyka, odczyt
maili CPro, nowa stawka przy „Za drogo” i weto hiring managera.

Okno decyduje, które grupy pokazać (``who`` — kto kończy, ``early_only`` —
tylko „Nowi”/„Screening”); lustro na froncie: ``frontend/src/lib/close-reasons.ts``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

RECRUITER = "recruiter"  # my albo Delivery Lead
CLIENT = "client"
CANDIDATE = "candidate"

_ALL = frozenset({RECRUITER, CLIENT, CANDIDATE})
_US_CLIENT = frozenset({RECRUITER, CLIENT})
_US_CANDIDATE = frozenset({RECRUITER, CANDIDATE})


@dataclass(frozen=True)
class CloseReason:
    key: str
    # Etykieta w historii i raportach. Okno ma krótszą, bo stoi w grupie
    # („Klient → Nie podał powodu”); w historii grupy nie widać.
    label: str
    who: frozenset[str]
    # ``rejection_reasons.name`` przy odrzuceniu (my, DL, klient) i przy
    # rezygnacji (kandydat); ``None`` — ta strona nie wybiera tego powodu.
    rejected: Optional[str] = None
    withdrawn: Optional[str] = None
    early_only: bool = False


def _r(
    key: str,
    label: str,
    who: set[str] | frozenset[str],
    rejected: Optional[str] = None,
    withdrawn: Optional[str] = None,
    early_only: bool = False,
) -> CloseReason:
    if rejected is None and (RECRUITER in who or CLIENT in who):
        rejected = key
    if withdrawn is None and CANDIDATE in who:
        withdrawn = key
    return CloseReason(key, label, frozenset(who), rejected, withdrawn, early_only)


CLOSE_REASON_GROUPS: tuple[tuple[str, tuple[CloseReason, ...]], ...] = (
    (
        "Klient",
        (
            _r("client_chose_other", "Klient wybrał innego kandydata", {CLIENT}),
            _r("client_interview_weak", "Rozmowa u klienta wypadła słabo", {CLIENT}),
            _r(
                "client_project_closed",
                "Klient zamknął projekt / przetarg przegrany",
                {CLIENT},
            ),
            _r("client_after_deadline", "Wysłany do klienta po terminie", {CLIENT}),
            _r("client_no_reason", "Klient nie podał powodu", {CLIENT}),
        ),
    ),
    (
        "Nie pasuje do wymagań",
        (
            _r(
                "missing_skill",
                "Brak kluczowej umiejętności",
                _US_CLIENT,
                rejected="Nie spełnia wymagań technicznych",
            ),
            _r(
                "too_junior",
                "Za mało doświadczenia",
                _US_CLIENT,
                rejected="Brak doświadczenia",
            ),
            _r("overqualified", "Za wysoki poziom (overqualified)", _US_CLIENT),
            _r("other_level_or_role", "Inny poziom lub inna rola", _US_CLIENT),
            _r("no_polish", "Brak polskiego", _US_CLIENT),
            _r("weak_english", "Angielski za słaby", _US_CLIENT),
            _r(
                "culture",
                "Nie pasuje kulturowo",
                _US_CLIENT,
                rejected="Nie pasuje kulturowo",
            ),
        ),
    ),
    (
        "Warunki",
        (
            _r(
                "too_expensive",
                "Za droga",
                _ALL,
                rejected="Za wysokie oczekiwania finansowe",
                withdrawn="salary_mismatch",
            ),
            _r(
                "location_mode",
                "Lokalizacja lub tryb pracy",
                _ALL,
                rejected="work_mode_mismatch",
                withdrawn="work_mode_mismatch",
            ),
            # 0768 (24.11.2026): osoba mieszka za granicą — system już jej nie
            # proponuje (``residence.lives_outside_poland``), a powód domyka
            # profile bez kraju.
            _r("outside_poland", "Mieszka poza Polską", _US_CLIENT),
            _r("contract_form", "Forma umowy (UoP / B2B)", _ALL),
            _r("available_too_late", "Dostępna za późno / wypowiedzenie", _ALL),
        ),
    ),
    (
        "Sprawa osoby",
        (
            _r(
                "not_looking",
                "Nie szuka pracy",
                _US_CANDIDATE,
                rejected="not_looking_for_work",
                withdrawn="not_looking_for_work",
            ),
            _r(
                "accepted_other_offer",
                "Przyjęła inną ofertę",
                _ALL,
                rejected="Zatrudniony gdzie indziej",
            ),
            _r("counter_offer", "Kontroferta od obecnego pracodawcy", {CANDIDATE}),
            _r(
                "lost_interest",
                "Straciła zainteresowanie / za długi proces",
                {CANDIDATE},
            ),
            _r("personal_reasons", "Powody osobiste", {CANDIDATE}),
            _r(
                "no_answer",
                "Nie odbiera / brak kontaktu",
                _US_CANDIDATE,
                rejected="no_contact",
                withdrawn="no_contact",
            ),
            _r("in_other_process", "Już u nas w innym procesie", {RECRUITER}),
            _r(
                "client_employed",
                "Pracuje u klienta / zgłoszona przez inną firmę",
                _US_CLIENT,
                rejected="client_other_vendor",
            ),
            _r("client_refused", "Nie chce do tego klienta", _US_CANDIDATE),
            _r(
                "hm_already_interviewed",
                "Już po rozmowie u tego hiring managera",
                _US_CLIENT,
            ),
        ),
    ),
    (
        "Dane w bazie",
        (
            _r("outdated_cv", "CV nieaktualne", {RECRUITER}, early_only=True),
            _r(
                "profile_mismatch",
                "Profil w bazie się nie zgadza",
                {RECRUITER},
                early_only=True,
            ),
            _r("wrong_phone", "Błędny numer telefonu", {RECRUITER}, early_only=True),
        ),
    ),
)

OTHER = CloseReason(
    "other", "Inne", _ALL, rejected="Inne (rejected)", withdrawn="Inne (withdrawn)"
)

CLOSE_REASONS: tuple[CloseReason, ...] = (
    *(reason for _title, reasons in CLOSE_REASON_GROUPS for reason in reasons),
    OTHER,
)
BY_KEY: dict[str, CloseReason] = {reason.key: reason for reason in CLOSE_REASONS}

# Powody, które słownik dokłada do szablonu (0745). Weto hiring managera
# (``disqualifies_person``) dostają tylko werdykty o osobie, jak „Brak
# doświadczenia”: polski i angielski. Za wysoki poziom i inna rola mówią
# o tej roli, nie o osobie, a reszta to sytuacja.
NEW_REJECTED: tuple[tuple[str, bool], ...] = (
    ("client_project_closed", False),
    ("client_after_deadline", False),
    ("overqualified", False),
    ("other_level_or_role", False),
    ("no_polish", True),
    ("weak_english", True),
    ("available_too_late", False),
    ("in_other_process", False),
    ("client_refused", False),
    ("outdated_cv", False),
    ("profile_mismatch", False),
    ("wrong_phone", False),
)
# Powody dołożone po 0745, każdy własną migracją (nazwa w szablonie, weto).
LATER_REJECTED: tuple[tuple[str, bool], ...] = (("outside_poland", False),)
NEW_WITHDRAWN: tuple[str, ...] = (
    "contract_form",
    "available_too_late",
    "not_looking_for_work",
    "no_contact",
    "client_refused",
)

# Stare nazwy w szablonie, których słownik nie pokazuje, a historia je ma.
# Etykieta = etykieta powodu słownika o tym znaczeniu, więc raporty liczące
# po etykiecie (Insights → etapy) sumują stare i nowe wpisy razem.
# ``client_conflict`` (0646) łączył „pracuje u klienta” i „nie chce do
# klienta”, więc zostaje z własną etykietą; „Kandydat się wycofał” (dopisany
# przez admina) nie mówi dlaczego.
LEGACY_TO_KEY: dict[str, str] = {
    "process_too_long": "lost_interest",
    "Brak odpowiedzi": "no_answer",
    "Kandydat nieosiągalny": "no_answer",
}


def template_name(key: str, *, withdrawn: bool) -> Optional[str]:
    """Nazwa powodu w szablonie dla klucza słownika i strony, która kończy."""
    reason = BY_KEY.get(key)
    if reason is None:
        return None
    return reason.withdrawn if withdrawn else reason.rejected


def labels_by_template_name() -> dict[str, str]:
    """``rejection_reasons.name`` → etykieta słownika (dla historii i raportów)."""
    out: dict[str, str] = {}
    for reason in CLOSE_REASONS:
        for name in (reason.rejected, reason.withdrawn):
            if name is not None:
                out.setdefault(name, reason.label)
    for name, key in LEGACY_TO_KEY.items():
        out[name] = BY_KEY[key].label
    return out
