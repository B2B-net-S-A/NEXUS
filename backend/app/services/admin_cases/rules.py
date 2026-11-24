"""Reguły spraw administracja@ bez bazy (czyste funkcje, testowane osobno).

* termin z priorytetu (SLA w dniach roboczych, święta z ``holidays`` przez
  ``app/core/scheduling.py``; Compass trzymał własną listę świąt do 2030 r.),
* obszar z tematu maila (proste słowa kluczowe, domyślnie administracja),
* temat wątku bez „RE:/FW:/Odp:” (po nim nie łączymy wątków — od tego jest
  ``conversationId`` i ``In-Reply-To``; tytuł sprawy z maila ma być czytelny),
* checklista: lista ``{text, done}`` po walidacji.
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Iterable, Optional

from app.core.scheduling import business_today
from app.services.admin_cases_schema import TERMINAL_STATUSES
from app.services.candidate_followups import add_business_days

#: Dni robocze na sprawę wg priorytetu (jak w Compassie: P1 2, P2 5, P3 10).
SLA_BUSINESS_DAYS: dict[str, int] = {"P1": 2, "P2": 5, "P3": 10}

TITLE_MAX = 200
CHECKLIST_MAX_ITEMS = 50
CHECKLIST_TEXT_MAX = 300
BODY_TEXT_MAX = 20_000

AREA_LABELS: dict[str, str] = {
    "onboarding": "Onboarding",
    "offboarding": "Offboarding",
    "negotiation": "Negocjacje",
    "administration": "Administracja",
    "settlements": "Rozliczenia",
    "marketing": "Marketing",
    "other": "Inne",
}
STATUS_LABELS: dict[str, str] = {
    "new": "Nowa",
    "in_progress": "W toku",
    "waiting": "Czeka na kogoś",
    "done": "Zrobione",
    "closed": "Zamknięta",
}

# Kolejność ma znaczenie: „zakończenie współpracy” to odejście, nawet gdy
# w temacie stoi też „umowa”; marketing przed administracją („faktura za post”
# zdarza się rzadziej niż „post na LinkedIn”).
_AREA_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "offboarding",
        (
            "offboarding",
            "odejscie",
            "zakonczenie wspolpracy",
            "wypowiedzenie",
            "rozwiazanie umowy",
            "zwrot sprzetu",
            "ostatni dzien",
        ),
    ),
    (
        "onboarding",
        (
            "onboarding",
            "wejscie",
            "rozpoczecie wspolpracy",
            "start wspolpracy",
            "nowy konsultant",
            "pierwszy dzien",
        ),
    ),
    ("negotiation", ("negocjac", "stawk", "aneks", "podwyzk", "oferta wspolpracy")),
    (
        "marketing",
        ("marketing", "linkedin", "kampani", "grafik", "wydarzeni", "publikacj"),
    ),
)
DEFAULT_AREA = "administration"
#: Mail na adres rozliczeń (To/Cc) — decyzja Artura z 19.11.2026; wybiera czytnik spraw.
SETTLEMENTS_AREA = "settlements"

_REPLY_PREFIX = re.compile(
    r"^\s*((re|fw|fwd|odp|pd|aw|wg|sv)\s*(\[\d+\])?\s*:\s*)+", re.IGNORECASE
)
_SPACES = re.compile(r"[ \t\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def fold(value: str) -> str:
    """Małe litery bez polskich znaków (do porównań słów kluczowych)."""

    normalized = unicodedata.normalize(
        "NFKD", value.replace("ł", "l").replace("Ł", "L")
    )
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def area_from_subject(subject: Optional[str]) -> str:
    folded = fold(subject or "")
    for area, needles in _AREA_RULES:
        if any(needle in folded for needle in needles):
            return area
    return DEFAULT_AREA


def due_date_for(priority: str, start: datetime) -> date:
    """Termin sprawy: ``start`` + dni robocze z priorytetu (dzień lokalny)."""

    return add_business_days(start, SLA_BUSINESS_DAYS.get(priority, 5))


def clean_subject(subject: Optional[str]) -> str:
    """Temat bez przedrostków odpowiedzi i przekazania, bez NUL i nadmiaru spacji."""

    text_value = (subject or "").replace("\x00", "")
    text_value = _REPLY_PREFIX.sub("", text_value)
    return _SPACES.sub(" ", text_value).strip()


def case_title_from_subject(subject: Optional[str]) -> str:
    title = clean_subject(subject)
    return (title or "Wiadomość bez tematu")[:TITLE_MAX]


def body_to_text(content: Optional[str], content_type: Optional[str]) -> str:
    """Treść maila jako zwykły tekst: bez znaczników HTML, bez NUL, przycięta."""

    from app.services.m365.html_sanitize import html_to_text

    raw = (content or "").replace("\x00", "")
    if (content_type or "").lower() == "html":
        raw = html.unescape(html_to_text(raw))
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACES.sub(" ", line).strip() for line in raw.split("\n")]
    text_value = _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
    return text_value[:BODY_TEXT_MAX]


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


class ChecklistError(ValueError):
    """Checklista nie przeszła walidacji (komunikat po polsku)."""


def normalize_checklist(items: Iterable[Any]) -> list[dict[str, Any]]:
    """Lista ``{text, done}``: tekst przycięty, puste pozycje odrzucone."""

    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ChecklistError("Pozycja checklisty musi mieć tekst.")
        text_value = str(item.get("text") or "").replace("\x00", "").strip()
        if not text_value:
            continue
        if len(text_value) > CHECKLIST_TEXT_MAX:
            raise ChecklistError(
                f"Pozycja checklisty może mieć najwyżej {CHECKLIST_TEXT_MAX} znaków."
            )
        result.append({"text": text_value, "done": item.get("done") is True})
    if len(result) > CHECKLIST_MAX_ITEMS:
        raise ChecklistError(
            f"Checklista może mieć najwyżej {CHECKLIST_MAX_ITEMS} pozycji."
        )
    return result


#: Pozycje checklisty sprawy „Koniec współpracy” (bez kwot). Pozycja checklisty
#: ma tylko ``{text, done}``, więc krótkie wyjaśnienie (makieta S5) stoi po „—”.
END_EQUIPMENT_ITEM = "Zwrot sprzętu i protokół — pozycja z ewidencji sprzętu"
END_ACCESS_PREFIX = "Odebranie dostępu: "
END_ACCESS_GENERIC = (
    "Odebranie dostępów u klienta — lista z pakietu „Wejście u klienta”"
)
END_FEEDBACK_ITEM = "Ostatnia opinia menedżera — prośba o opinię przed końcem"
END_DECISION_ITEM = "Decyzja: przekaż do front office albo „nie przepinamy”"
END_SETTLEMENT_ITEM = "Rozliczenie ostatniego miesiąca — Finanse, bez kwot"
#: Sprzęt z rejestru ``/equipment`` wydany na kontrakt i niezwrócony (posiadaczem
#: bywa kontrakt B2B — 19.11.2026 27 żywych kontraktów miało taki sprzęt).
END_EQUIPMENT_REGISTER_PREFIX = "Sprzęt do zwrotu z rejestru: "
#: Benefity (przegląd skrzynek back office 24.11.2026): rezygnację zgłasza się do
#: 19. dnia miesiąca i działa od 1. dnia następnego; benefit trwający po końcu
#: współpracy potrąca się z ostatniego przelewu. NEXUS nie ma ewidencji benefitów,
#: więc pozycja mówi, co sprawdzić i do kiedy.
END_BENEFITS_PREFIX = "Benefity: "
BENEFITS_DEADLINE_DAY = 19
#: Od 01.01.2027 PZU znika z oferty, zostaje karta sportowa.
PZU_LAST_DAY = date(2026, 12, 31)
_MONTHS_PL = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)


def _first_of_next_month(day: date) -> date:
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def benefits_item(last_day: Optional[date], today: date) -> str:
    """Pozycja „Benefity” z terminem rezygnacji liczonym od ostatniego dnia.

    Rezygnacja zgłoszona do 19. dnia miesiąca ostatniego dnia działa od 1. dnia
    następnego. Gdy ten termin już minął, najbliższy możliwy to 19. bieżącego
    albo następnego miesiąca, a miesiące między końcem współpracy a wejściem
    rezygnacji potrąca się z ostatniego przelewu.
    """

    names = "karta sportowa"
    if last_day is None or last_day <= PZU_LAST_DAY:
        names = "karta sportowa, PZU do 31.12.2026"
    if last_day is None:
        return (
            f"{END_BENEFITS_PREFIX}sprawdź, czy ma ({names}); rezygnacja do 19. dnia "
            "miesiąca działa od 1. dnia następnego, a benefit po końcu współpracy "
            "potrąć z ostatniego przelewu"
        )
    deadline = date(last_day.year, last_day.month, BENEFITS_DEADLINE_DAY)
    if today > deadline:
        deadline = date(today.year, today.month, BENEFITS_DEADLINE_DAY)
        if today > deadline:
            following = _first_of_next_month(today)
            deadline = date(following.year, following.month, BENEFITS_DEADLINE_DAY)
    effective = _first_of_next_month(deadline)
    text_value = (
        f"{END_BENEFITS_PREFIX}sprawdź, czy ma ({names}); rezygnacja do "
        f"{deadline:%d.%m.%Y}, działa od {effective:%d.%m.%Y}"
    )
    charged: list[str] = []
    month = _first_of_next_month(last_day)
    while month < effective:
        charged.append(f"{_MONTHS_PL[month.month - 1]} {month.year}")
        month = _first_of_next_month(month)
    if charged:
        text_value += f"; potrąć z ostatniego przelewu: {', '.join(charged)}"
    return text_value[:CHECKLIST_TEXT_MAX]


def equipment_register_item(names: Iterable[str]) -> Optional[str]:
    """Pozycja ze sprzętem z rejestru albo ``None``, gdy nic nie jest wydane."""

    cleaned = [" ".join(str(name).split()) for name in names]
    cleaned = [name for name in cleaned if name]
    if not cleaned:
        return None
    text_value = f"{END_EQUIPMENT_REGISTER_PREFIX}{', '.join(cleaned)}"
    if len(text_value) > CHECKLIST_TEXT_MAX:
        text_value = text_value[: CHECKLIST_TEXT_MAX - 1].rstrip(", ") + "…"
    return text_value


def end_of_cooperation_checklist(
    *,
    equipment_ours: bool,
    accesses: Iterable[str],
    feedback_done: bool = False,
    decision_done: bool = False,
    equipment_names: Iterable[str] = (),
    last_day: Optional[date] = None,
    today: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Checklista sprawy „Koniec współpracy” z pakietu klienta i stanu opieki.

    * zwrot sprzętu i protokół — tylko gdy klient ma „sprzęt od nas”,
    * sprzęt do zwrotu z rejestru — egzemplarze wydane na kontrakt, niezwrócone,
    * odebranie dostępów — pozycje „Dostępy” z pakietu klienta (bez pakietu
      jedna pozycja ogólna),
    * ostatnia opinia menedżera — odhaczona, gdy opiekun już ją zapisał,
    * decyzja o przepięciu — odhaczona, gdy wpis „Do przepięcia” jest już
      w toku, zrobiony albo odłożony („nie przepinamy”),
    * benefity — termin rezygnacji (19.) i potrącenie z ostatniego przelewu,
    * rozliczenie ostatniego miesiąca (bez kwot).
    """

    items: list[dict[str, Any]] = []
    if equipment_ours:
        items.append({"text": END_EQUIPMENT_ITEM, "done": False})
    register = equipment_register_item(equipment_names)
    if register is not None:
        items.append({"text": register, "done": False})
    room = CHECKLIST_TEXT_MAX - len(END_ACCESS_PREFIX)
    names = [" ".join(str(name).split())[:room] for name in accesses]
    # Miejsce na siedem stałych pozycji — checklista ma limit pozycji.
    names = [name for name in dict.fromkeys(names) if name][: CHECKLIST_MAX_ITEMS - 7]
    if names:
        items.extend(
            {"text": f"{END_ACCESS_PREFIX}{name}", "done": False} for name in names
        )
    else:
        items.append({"text": END_ACCESS_GENERIC, "done": False})
    items.append({"text": END_FEEDBACK_ITEM, "done": feedback_done})
    items.append({"text": END_DECISION_ITEM, "done": decision_done})
    items.append(
        {"text": benefits_item(last_day, today or business_today()), "done": False}
    )
    items.append({"text": END_SETTLEMENT_ITEM, "done": False})
    return normalize_checklist(items)
