"""Kolejka rekrutera dla raportów kompetencji (N6, decyzje Artura 25.11.2026).

Czyste pomocniki dla ``api/competence_reports.py``: opis warunków jednym
wierszem, godziny do terminu, podgląd maila bez prawdziwego tokenu i kto może
być na liście opiekunów. Bez bazy, żeby testy nie potrzebowały Postgresa.

Raport bez reakcji rekrutera wychodzi sam o ``send_due_at`` (zgłoszenie + 23 h);
„Wstrzymaj” (``held_at``) zatrzymuje tę wysyłkę, a kandydat dostał na stronie
obietnicę raportu w 24 godziny — stąd ostrzeżenie przy wstrzymaniu.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.models.user import User, UserRole
from app.services.competence_report_email import ReportLinks, render_report_email
from app.services.competence_report_schema import ReportConditions, ReportSnapshot

#: Stany, w których raport jeszcze czeka na wysyłkę (kolejka „Do wysłania”).
OPEN_STATUSES: tuple[str, ...] = ("waiting_cv", "ready", "failed")
#: „Wyślij teraz” wymaga złożonego snapshotu; ``failed`` = ponowienie.
SENDABLE_STATUSES: tuple[str, ...] = ("ready", "failed")

#: Kto może być opiekunem raportów: zespół rekrutacji (lista ustawiana przez admina).
OWNER_ROLES: tuple[UserRole, ...] = (
    UserRole.recruiter,
    UserRole.head_of_recruitment,
    UserRole.talent_community_manager,
)

HOLD_WARNING = (
    "Kandydat dostał na stronie obietnicę raportu w 24 godziny. "
    "Wstrzymany raport nie wyjdzie sam — wyślij go albo zwolnij przed terminem."
)

#: Linki w podglądzie: kotwice, nigdy prawdziwy token (ten powstaje dopiero przy wysyłce).
PREVIEW_LINKS = ReportLinks(
    edit_conditions_url="#podglad-zmiana-warunkow",
    unsubscribe_url="#podglad-wypis",
    one_click_unsubscribe_url=None,
)

_CONTRACT = {"b2b": "B2B", "uop": "UoP", "any": "B2B lub UoP"}
_MODE = {"remote": "zdalnie", "hybrid": "hybrydowo", "onsite": "w biurze"}
_START = {
    "now": "start od zaraz",
    "1m": "start za miesiąc",
    "2-3m": "start za 2–3 miesiące",
    "browsing": "na razie się rozgląda",
}


def _days(n: int) -> str:
    if n == 0:
        return "bez dni w biurze"
    return f"do {n} {'dnia' if n == 1 else 'dni'} w biurze"


def conditions_summary(raw: dict) -> str:
    """Warunki z formularza jednym wierszem, np. „180 zł/h · B2B · zdalnie · Kraków”."""
    try:
        c = ReportConditions.model_validate(raw or {})
    except ValueError:
        # Wiersz sprzed zmiany schematu: kolejka pokazuje go dalej, bez opisu.
        return "—"
    parts = [f"{c.rate} zł/h"]
    if c.current_rate:
        parts.append(f"teraz {c.current_rate} zł/h")
    parts.append(_CONTRACT[c.contract])
    if c.modes:
        parts.append(", ".join(_MODE[m] for m in c.modes))
    # Sama praca zdalna: dni w biurze nic nie mówią.
    if c.office_days_max is not None and c.modes != ("remote",):
        parts.append(_days(c.office_days_max))
    if c.office_cities:
        parts.append(", ".join(c.office_cities))
    if c.start:
        parts.append(_START[c.start])
    return " · ".join(parts)


def changed_condition_keys(before: dict, after: ReportConditions) -> list[str]:
    """Nazwy pól, które zmienił rekruter — do Historii zdarzeń, bez wartości."""
    new = after.model_dump(mode="json")
    old = dict(before or {})
    return sorted(key for key in new if old.get(key) != new[key])


def hours_left(send_due_at: datetime, now: Optional[datetime] = None) -> float:
    """Godziny do terminu (ujemne po terminie), z dokładnością do 0,1."""
    current = now or datetime.now(timezone.utc)
    return round((send_due_at - current).total_seconds() / 3600, 1)


def snapshot_or_none(raw: Optional[dict]) -> Optional[ReportSnapshot]:
    if not raw:
        return None
    try:
        return ReportSnapshot.model_validate(raw)
    except ValueError:
        return None


def preview_mail(
    raw_snapshot: Optional[dict], first_name: Optional[str]
) -> tuple[Optional[str], Optional[str]]:
    """Temat i HTML maila do podglądu w kolejce (kotwice zamiast linków z tokenem)."""
    snapshot = snapshot_or_none(raw_snapshot)
    if snapshot is None:
        return None, None
    mail = render_report_email(snapshot, first_name=first_name, links=PREVIEW_LINKS)
    return mail.subject, mail.html


def is_owner_eligible(user: Optional[User]) -> bool:
    return bool(user and user.is_active and user.has_any_role(*OWNER_ROLES))
