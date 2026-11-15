"""Przypomnienia o terminach raportów dla klienta — czysta funkcja, bez bazy.

Decyzja Artura 15.11.2026: osoba, która przygotowuje raport, dostaje dzwonek
kilka dni przed terminem, w kategorii „Raporty dla klientów”. Bazę czyta
i zapisuje pętla ``app/tasks/client_report_reminders.py``; tu zapada decyzja,
komu i o którym okresie przypomnieć.

Kiedy:

* **przed terminem** — termin w paśmie od dziś do ``LEAD_WORKDAYS`` dni
  roboczych naprzód (kalendarz firmy). Pasmo, nie równość z jednym dniem, z tego
  samego powodu co w ``dl_portal_expiry_scanner``: dzień bez biegu pętli albo
  definicja dodana dwa dni przed terminem nie mogą zgubić przypomnienia;
* **po terminie** — termin minął, a okres nie ma wysyłki (``status='sent'``
  w ``client_report_runs``). Wychodzi od pierwszego dnia po terminie przez
  ``OVERDUE_CATCHUP_WORKDAYS`` dni roboczych (siatka na dzień bez biegu).
  Jedno: starsze zaległości pokazuje kalendarz katalogu, nie dzwonek.

Każdy epizod (odbiorca, definicja, okres, rodzaj) wychodzi raz: klucz epizodu
stoi w treści powiadomienia (:func:`episode_phrase`), jak data końca w treści
alertów końca zamówień. Okresy sprzed ``catalog.tracking_start`` się nie liczą,
bo NEXUS ich wtedy nie pilnował.

Odbiorca: ``preparer_user_id`` definicji, a gdy go nie ma i raport
przygotowuje Delivery Lead (``preparer == 'dl'``) — aktywni DL-e przypisani do
klienta. Finanse, Zarząd, IOD, konsultanci i klient bez wskazanej osoby nie
dostają nic: to zespoły albo ludzie spoza NEXUSA, a dzwonek „do wszystkich
z Finansów” byłby szumem, którego nikt nie gasi. Wtedy termin pilnuje DL
w kalendarzu katalogu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping, Optional, Sequence

from app.models.client_report import ClientReportDefinition
from app.services.client_reports import schedule
from app.services.client_reports.catalog import Assignment, tracking_start

#: Ile dni roboczych przed terminem zaczyna się przypominanie.
LEAD_WORKDAYS = 3
#: Ile dni roboczych po terminie wolno jeszcze wysłać „termin minął”.
OVERDUE_CATCHUP_WORKDAYS = 3

_TITLE_MAX = 255

UPCOMING = "upcoming"
OVERDUE = "overdue"

#: Ile okresów wstecz sprawdzić per rytm — z zapasem na najdłuższy termin
#: (``MAX_OFFSET_DAYS`` dni po okresie albo stały dzień w kolejnym roku).
_PERIODS_BACK: dict[str, int] = {
    "weekly": 20,
    "monthly": 14,
    "quarterly": 6,
    "semiannual": 4,
    "annual": 3,
    "contract_year": 3,
}


@dataclass(frozen=True)
class Reminder:
    user_id: int
    definition_id: int
    client_id: int
    name: str
    period_key: str
    period_label: str
    due: date
    kind: str

    @property
    def phrase(self) -> str:
        return episode_phrase(self.kind, self.period_key, self.due)


def episode_phrase(kind: str, period_key: str, due: date) -> str:
    """Fragment treści, który jest zarazem kluczem epizodu w dedupie.

    Jedno źródło dla treści i dla sprawdzenia „już wysłano”: rozjazd (np. inny
    format daty tylko w treści) zamieniłby dedup w codzienne powtórki. Fraza
    „po terminie” nie zawiera frazy „przed terminem” i odwrotnie.
    """
    if kind == OVERDUE:
        return f"termin minął {due.isoformat()} (okres {period_key})"
    return f"termin {due.isoformat()} (okres {period_key})"


def recipients(
    definition: ClientReportDefinition,
    assignments: Mapping[int, Sequence[Assignment]],
) -> list[int]:
    """Kto dostaje przypomnienie; pusta lista = nikt (patrz docstring modułu)."""
    if definition.preparer_user_id is not None:
        return [definition.preparer_user_id]
    if definition.preparer == "dl":
        seen: list[int] = []
        for assignment in assignments.get(definition.client_id) or ():
            if assignment.user_id not in seen:
                seen.append(assignment.user_id)
        return seen
    return []


def reminder_kind(due: date, today: date) -> Optional[str]:
    if today <= due <= schedule.add_workdays(today, LEAD_WORKDAYS):
        return UPCOMING
    if due < today <= schedule.add_workdays(due, OVERDUE_CATCHUP_WORKDAYS):
        return OVERDUE
    return None


def _open_periods(
    definition: ClientReportDefinition, today: date, sent_keys: Iterable[str]
) -> list[tuple[schedule.Period, date, str]]:
    """Okresy definicji z terminem w paśmie przypomnień, bez wysyłki."""
    rule = definition.due_rule or {}
    if definition.status != "active":
        return []
    if definition.rhythm not in schedule.CALENDAR_RHYTHMS:
        return []
    if (rule.get("type") or "none") == "none":
        return []
    try:
        periods = schedule.recent_periods(
            definition.rhythm,
            today,
            _PERIODS_BACK[definition.rhythm],
            rule,
            definition.valid_from,
        )
    except schedule.ScheduleError:
        return []
    sent = set(sent_keys)
    start = tracking_start(definition)
    out: list[tuple[schedule.Period, date, str]] = []
    for period in periods:
        due = schedule.due_date(rule, period)
        if due is None or period.key in sent:
            continue
        if start is not None and (due < start or period.end < start):
            continue
        if definition.valid_to is not None and period.start > definition.valid_to:
            continue
        kind = reminder_kind(due, today)
        if kind is not None:
            out.append((period, due, kind))
    return out


def plan_reminders(
    definitions: Iterable[ClientReportDefinition],
    *,
    today: date,
    sent: Mapping[int, Iterable[str]],
    assignments: Mapping[int, Sequence[Assignment]],
    already_sent: Mapping[tuple[int, int], Sequence[str]],
) -> list[Reminder]:
    """Przypomnienia do wysłania dziś.

    ``sent`` — klucze okresów z wysyłką per definicja; ``already_sent`` — treści
    wcześniejszych powiadomień ``client_report_due`` per (adresat, definicja).
    Najpierw „termin minął”, potem najbliższe terminy.
    """
    out: list[Reminder] = []
    for definition in definitions:
        people = recipients(definition, assignments)
        if not people:
            continue
        for period, due, kind in _open_periods(
            definition, today, sent.get(definition.id, ())
        ):
            phrase = episode_phrase(kind, period.key, due)
            for user_id in people:
                previous = already_sent.get((user_id, definition.id), ())
                if any(phrase in message for message in previous):
                    continue
                out.append(
                    Reminder(
                        user_id=user_id,
                        definition_id=definition.id,
                        client_id=definition.client_id,
                        name=definition.name,
                        period_key=period.key,
                        period_label=period.label,
                        due=due,
                        kind=kind,
                    )
                )
    out.sort(key=lambda r: (r.kind != OVERDUE, r.due, r.definition_id, r.user_id))
    return out


def _days_phrase(days: int) -> str:
    if days <= 0:
        return "dziś"
    if days == 1:
        return "jutro"
    return f"za {days} dni"


def title(reminder: Reminder, today: date) -> str:
    if reminder.kind == OVERDUE:
        text = f"Raport dla klienta — termin minął: {reminder.name}"
    else:
        lead = _days_phrase((reminder.due - today).days)
        text = f"Raport dla klienta — termin {lead}: {reminder.name}"
    # `notifications.title` to VARCHAR(255), a nazwa raportu ma do 200 znaków.
    return text if len(text) <= _TITLE_MAX else text[: _TITLE_MAX - 1] + "…"


def message(reminder: Reminder, client_name: Optional[str]) -> str:
    """Treść z frazą epizodu dosłownie — po niej idzie dedup."""
    who = client_name or "klient"
    if reminder.kind == OVERDUE:
        action = "Wyślij raport i zapisz wysyłkę w katalogu raportów."
    else:
        action = "Przygotuj raport, a po wysłaniu zapisz wysyłkę w katalogu."
    return f"{who}: {reminder.period_label}, {reminder.phrase}. {action}"


def link(reminder: Reminder) -> str:
    # Klucz zakładki z `frontend/src/lib/client-tab.ts`.
    return f"/clients/{reminder.client_id}?tab=raporty"
