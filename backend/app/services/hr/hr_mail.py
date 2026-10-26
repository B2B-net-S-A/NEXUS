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

Premia (`hr_bonus_assigned`, mail obowiązkowy „Masz nową premię” od 26.10.2026)
ma własny mail: `bonus_mail` składa go ze stałych słów formy i z wiersza
premii — za co i za który miesiąc. Kwoty nie ma w mailu nigdy (decyzja Artura
26.10.2026), także wtedy, gdy treść dzwonka by ją kiedyś niosła.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_payroll import HrBonus
from app.models.hr_profile import EmployeeProfile
from app.services.hr.employment_terms import (
    BACKEND_TERMS,
    capitalize,
    returned_titles,
    terms,
)
from app.services.hr.leave_policy import LEAVE_TYPE_LABELS
from app.services.hr.payroll_periods import label as period_label

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
    # Tytuł powiadomienia mówi słowami formy (ewidencja / raport / potwierdzenie
    # godzin), treść — kto i za jaki miesiąc; zdanie zastępcze bez nich.
    "hr_timesheet_submitted": (
        "Godziny do akceptacji",
        "Osoba z Twojego zespołu wysłała godziny — akceptujesz je "
        "w „Ludzie → Akceptacje”.",
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
    "equipment_return_reminder": (
        "Zwrot sprzętu do recepcji",
        "Recepcja prosi o zwrot sprzętu firmy — listę rzeczy znajdziesz "
        "w „Moim czasie” → Kartoteka.",
    ),
    "care_front_office_handoff": (
        "Konsultant dla front office",
        "Konsultant kończy projekt albo chce zmiany — szczegóły znajdziesz w NEXUSIE.",
    ),
    "care_announcement": (
        "Komunikat do konsultantów",
        "Komunikat do konsultantów czeka na Ciebie — szczegóły znajdziesz w NEXUSIE.",
    ),
    "hr_settlement_correction": (
        "Płace proszą o korektę faktury",
        "Porównanie z raportem godzin znajdziesz w „Moim czasie” → Rozliczenie.",
    ),
    "hr_settlement_review": (
        "Rozliczenie do sprawdzenia",
        "Rozliczenie w Płacach czeka na Twoją decyzję — szczegóły znajdziesz w NEXUSIE.",
    ),
    "hr_agreement_update": (
        "Zmiana stanu umowy",
        "Umowa osoby z zespołu zmieniła stan — szczegóły w kartotece w NEXUSIE.",
    ),
    # Mail do decydującego składa `services/hr/approvals/mail.py` (z kwotą);
    # zdanie zastępcze tylko na wypadek, gdyby tamten go nie złożył.
    "hr_approval_requested": (
        "Zgoda do decyzji",
        "Prośba o zgodę czeka na Twoją decyzję w „Ludzie → Akceptacje → Zgody”.",
    ),
    # Uwaga decydującego to wolny tekst — do maila nie idzie.
    "hr_approval_decided": (
        "Decyzja o Twojej zgodzie",
        "Decyzję i uwagę znajdziesz w „Ludzie → Moje zgody”.",
    ),
    "hr_approval_topup_requested": (
        "Prośba o dopłatę do zgody",
        "Faktura wyszła drożej niż zgoda — dopłata czeka na Twoją decyzję "
        "w „Ludzie → Akceptacje → Zgody”.",
    ),
    "hr_subscription_renewal": (
        "Odnowienie subskrypcji",
        "Subskrypcja, której jesteś opiekunem, odnawia się za miesiąc — "
        "potwierdź w „Ludzie → Moje zgody”, czy jest dalej potrzebna.",
    ),
}
_DEFAULT = ("Czas i ludzie", "Szczegóły znajdziesz w NEXUSIE.")

# Treść tych typów to zawsze wolny tekst.
_FREE_TEXT_TYPES = frozenset(
    {"admin_case_assigned", "hr_leave_conflict", "hr_approval_decided"}
)
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


# ── „Masz nową premię” (26.10.2026) ─────────────────────────────────────────

BONUS_EVENTS = ("new", "changed", "cancelled")
# Tytuły dzwonka premii (`payroll_bonuses._notify`, zgody) → zdarzenie. Stałe
# słowa formy — bez kwot; inny tytuł = mail nie wychodzi.
_BONUS_EVENT_BY_TITLE: dict[str, str] = {
    words[f"bonus_{event}_title"]: event
    for words in BACKEND_TERMS.values()
    for event in BONUS_EVENTS
}
# Za co: źródło premii (`hr_payroll_schema.BONUS_SOURCES`).
BONUS_SOURCE_LABELS: dict[str, str] = {
    "contract_placement": "za placement",
    "league": "za wynik w lidze",
    "manual": "ręczna",
    "compass_import": "ręczna",
}


def bonus_text(
    employment_type: str | None,
    *,
    event: str,
    source: str,
    period_year: int,
    period_month: int,
) -> tuple[str, str]:
    """(tytuł, treść) maila o premii: za co i za który miesiąc, bez kwoty."""

    words = terms(employment_type)
    where = f"„Moim czasie” → {capitalize(words['bonuses'])}"
    tail = (
        f"Szczegóły zobaczysz w NEXUSIE, w {where}."
        if event == "cancelled"
        else f"Kwotę zobaczysz w NEXUSIE, w {where}."
    )
    kind = BONUS_SOURCE_LABELS.get(source, BONUS_SOURCE_LABELS["manual"])
    return (
        words[f"bonus_{event}_title"],
        f"Rodzaj: {kind}. Miesiąc rozliczenia: "
        f"{period_label(period_year, period_month)}. {tail}",
    )


async def bonus_mail(db: AsyncSession, notif: Any) -> tuple[str, str] | None:
    """(tytuł, treść) maila z dzwonka premii albo ``None`` (bez maila).

    Bez maila, gdy tytuł nie jest jednym ze stałych tytułów premii albo wiersz
    premii nie należy do adresata (np. starszy dzwonek tego dnia, któremu
    `notify_each(fresh=True)` zdjął id premii).
    """

    event = _BONUS_EVENT_BY_TITLE.get((notif.title or "").strip())
    bonus_id = notif.related_entity_id
    if event is None or bonus_id is None or notif.related_entity_type != "hr_bonus":
        return None
    bonus = await db.get(HrBonus, bonus_id)
    if bonus is None or bonus.recipient_user_id != notif.user_id:
        return None
    form = await db.scalar(
        select(EmployeeProfile.employment_type).where(
            EmployeeProfile.user_id == notif.user_id
        )
    )
    return bonus_text(
        form,
        event=event,
        source=bonus.source,
        period_year=bonus.period_year,
        period_month=bonus.period_month,
    )
