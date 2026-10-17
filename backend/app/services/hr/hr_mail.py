"""Mail „Czas i ludzie” (`hr_people`) z powiadomienia kadrowego (17.10.2026).

Do 17.10.2026 typy HR dawały tylko dymek zalogowanym (temat `other`,
`services/notification_topics.py`): kto był offline, nie wiedział o wniosku
do decyzji, zastępstwie ani zwróconym timesheecie. Decyzja D6 z
`docs/claude/powiadomienia/pasek-tematy-bez-dzwonka.md` („`other` = dymek
i mail”): typy `notification_delivery.HR_MAIL_TYPES` wychodzą kolejką maili
natychmiast (`tasks/notification_email_outbox.py`), za polityką z Ustawień
i własnym wyłącznikiem osoby.

Mail wychodzi poza aplikację, a treść powiadomienia może nieść więcej, niż
wolno w mailu: przełożony i Kadry mogą w aplikacji widzieć rodzaj
nieobecności (D6), akceptujący pisze uwagi wolnym tekstem, tytuł sprawy
administracja@ przychodzi z cudzej poczty. Dlatego tytuł i treść przechodzą do
maila tylko wtedy, gdy nie ma w nich rodzaju nieobecności ani kwot — w innym
razie mail niesie stałe zdanie typu, a szczegóły są w NEXUSIE pod linkiem.
Wolnego tekstu (uwagi przy zwrocie timesheetu, tytuł sprawy) mail nie niesie
nigdy.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.hr.employment_terms import returned_titles
from app.services.hr.leave_policy import LEAVE_TYPE_LABELS

# Tytuły zwrotu raportu godzin (`time_flow.return_for_fix`, słowa według formy
# z `employment_terms`); treść niesie wtedy uwagi akceptującego — wolny tekst,
# który do maila nie idzie.
RETURNED_TIMESHEET_TITLES = returned_titles()

# Stałe zdania typu: (tytuł, treść), gdy tekst powiadomienia nie może wyjść.
FALLBACK: dict[str, tuple[str, str]] = {
    "hr_leave_requested": (
        "Wniosek o nieobecność do akceptacji",
        "Wniosek osoby z Twojego zespołu czeka na Twoją decyzję.",
    ),
    "hr_leave_decided": (
        "Zmiana w Twojej nieobecności",
        "Szczegóły znajdziesz w „Moim czasie”.",
    ),
    "hr_leave_cancelled": (
        "Nieobecność anulowana",
        "Szczegóły znajdziesz w kalendarzu zespołu.",
    ),
    "hr_leave_substitute": (
        "Zastępstwo",
        "Wyznaczono Cię na zastępcę w czasie czyjejś nieobecności.",
    ),
    "hr_absence_reported": (
        "Zgłoszona nieobecność",
        "Osoba z Twojego zespołu zgłosiła nieobecność.",
    ),
    # Notatka koordynatora to wolny tekst — do maila nie idzie (D5).
    "hr_leave_conflict": (
        "Kolizja z Twoją nieobecnością",
        "Koordynator zgłosił kolizję z terminem — notatkę znajdziesz w „Moim czasie”.",
    ),
    "hr_timesheet_decided": (
        "Zmiana w raporcie godzin",
        "Szczegóły znajdziesz w NEXUSIE.",
    ),
    "hr_timesheet_reminder": (
        "Wyślij godziny za miniony miesiąc",
        "Godziny za miniony miesiąc czekają na wysłanie.",
    ),
    "hr_lifecycle_task": (
        "Zadania: wejście albo odejście",
        "Masz zadania w sprawie wejścia albo odejścia pracownika.",
    ),
    "hr_work_handover": (
        "Przejmujesz pracę",
        "Przekazano Ci pracę osoby, która kończy współpracę.",
    ),
    "admin_case_assigned": (
        "Przypisano Ci sprawę administracja@",
        "Szczegóły sprawy znajdziesz w NEXUSIE.",
    ),
    "equipment_task": (
        "Sprzęt: zadania do zrobienia",
        "Recepcja ma zadania sprzętu na dziś i najbliższe dni.",
    ),
    "equipment_protocol_signed": (
        "Protokół podpisany",
        "Odbierający podpisał protokół — sprawdź podpis i potwierdź protokół.",
    ),
    "care_front_office_handoff": (
        "Konsultant dla front office",
        "Konsultant kończy projekt albo chce zmiany — szczegóły znajdziesz w NEXUSIE.",
    ),
    "care_announcement": (
        "Komunikat do konsultantów",
        "Komunikat do konsultantów czeka na Ciebie — szczegóły znajdziesz w NEXUSIE.",
    ),
}
_DEFAULT = ("Czas i ludzie", "Szczegóły znajdziesz w NEXUSIE.")

# Treść tych typów to zawsze wolny tekst.
_FREE_TEXT_TYPES = frozenset({"admin_case_assigned", "hr_leave_conflict"})
_RETURNED_BODY = "Uwagi akceptującego znajdziesz w „Moim miesiącu”."


def _label_stem(label: str) -> str:
    return re.sub(r"\s*\(.*?\)", "", label).strip().lower()


# Rodzaj nieobecności: nazwy ze słownika urlopów (bez „Inna nieobecność” —
# to samo słowo, które mail i tak pisze) plus formy, których słownik nie ma
# dosłownie („urlopu”, „L4”, „chorobowe”).
_ABSENCE_LABELS = tuple(
    _label_stem(label) for key, label in LEAVE_TYPE_LABELS.items() if key != "other"
)
_ABSENCE_RE = re.compile(
    r"\burlop\w*|\bL4\b|zwolnieni\w*\s+lekarsk|\bchorob\w*|\bart\.\s*188",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(
    r"\d\s*(?:zł|pln|eur|usd|€|\$)|\b(?:stawk|premi|wynagrodz|kwot)\w*",
    re.IGNORECASE,
)


def mail_safe(text: str) -> bool:
    """Czy tekst może wyjść mailem: bez rodzaju nieobecności i bez kwot."""

    lowered = text.lower()
    return not (
        _ABSENCE_RE.search(text)
        or _MONEY_RE.search(text)
        or any(label in lowered for label in _ABSENCE_LABELS)
    )


def mail_text(
    notification_type: Any, title: str | None, message: str | None
) -> tuple[str, str]:
    """(tytuł, treść) maila z powiadomienia kadrowego."""

    value = getattr(notification_type, "value", notification_type)
    fallback_title, fallback_body = FALLBACK.get(value, _DEFAULT)
    title = (title or "").strip()
    message = (message or "").strip()
    out_title = title if title and mail_safe(title) else fallback_title
    if value in _FREE_TEXT_TYPES:
        body = fallback_body
    elif value == "hr_timesheet_decided" and title in RETURNED_TIMESHEET_TITLES:
        body = _RETURNED_BODY
    else:
        body = message if message and mail_safe(message) else fallback_body
    return out_title, body
