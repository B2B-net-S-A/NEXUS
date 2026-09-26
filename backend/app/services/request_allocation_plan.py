"""Czysty planer przydziału ludzi do requestów (decyzje Artura 24.09.2026).

Bez bazy i bez zegara — dostaje stan świata, oddaje listę zmian. Warstwa
zapisu to ``services/request_allocation``. Reguły:

* **Pula:** requesty „Szukamy kandydatów” bez championa. Request, który z niej
  wyszedł (champion, „Klient milczy”, „Zakończony”), zwalnia swoich ludzi.
* **Kolejność:** najpierw requesty bez nikogo wysłanego do klienta, potem 1–2
  wysłane, potem 3+; w grupie najbliższy termin (brak terminu na końcu).
* **Rekruter czy sourcer:** co najmniej ``sourcer_threshold`` pasujących osób
  w bazie → wystarczy sourcer; mniej albo brak przeglądu bazy → rekruter (on
  ma LinkedIna). Gdy żaden sourcer nie jest dostępny — rekruter.
* **Kto:** 1. priorytet kategorii requestu → 2. priorytet → pozostali.
  W grupie najmniej requestów, potem ten, kto najdawniej coś dostał. Do
  następnej grupy przechodzimy, gdy grupa jest pusta albo jej najmniej
  obłożona osoba ma o więcej niż 1 request więcej niż najmniej obłożona
  osoba w całym zespole — to jest „przelew” między kategoriami.
* **Stabilność:** planer NIE przerzuca działających przypisań, żeby wyrównać
  liczby. Zwalnia tylko wtedy, gdy request wyszedł z puli albo osoba (z
  przypisaniem automatu) przestała być dostępna — i nawet wtedy nie, jeśli ma
  przy tym requeście kandydatów w toku. Ręczne przypisania zostają zawsze.
* **Nieaktywne konto** zwalnia każde swoje przypisanie (także ręczne i z
  kandydatami w toku) — takie konto nie pracuje i nikt go już nie zobaczy
  na pulpicie, a request stałby „pokryty” na zawsze (audyt 25.09.2026).
* **Decyzja człowieka wygrywa:** osoba zdjęta z requestu ręcznie nie wraca
  do niego z automatu, dopóki request nie zmieni stanu (``blocked``).
* **Bez świeżych urlopów** tryb ``auto`` niczego nie przydziela ani nie
  aktywuje — ale osoba „Poza przydziałem” albo bez kategorii jest zwalniana
  zawsze, bo to nie zależy od Compassa (``eligible_ids``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable, Optional

RELEASE_REASONS = {
    "champion": "Mamy championa",
    "client_silent": "Klient milczy",
    "finished": "Request zakończony",
    "to_review": "Request wrócił do przejrzenia",
    "unavailable": "Osoba na urlopie",
    "excluded": "Osoba poza przydziałem",
    "owner_changed": "Zmiana prowadzącego",
    "manual": "Zdjęte ręcznie",
    "inactive": "Konto nieaktywne",
    "mode_off": "Automat wyłączony",
}


@dataclass(frozen=True)
class RequestInfo:
    job_id: int
    categories: frozenset[int]
    primary_category: Optional[int]
    sent: int
    deadline: Optional[date]
    base_matches: Optional[int]


@dataclass(frozen=True)
class PersonInfo:
    user_id: int
    can_recruit: bool
    can_source: bool
    first: frozenset[int]
    second: frozenset[int]
    last_assigned: Optional[datetime] = None


@dataclass(frozen=True)
class LiveAssignment:
    job_id: int
    user_id: int
    role: str
    source: str
    state: str
    in_process: bool = False


@dataclass(frozen=True)
class Change:
    kind: str  # assign | release | activate
    job_id: int
    user_id: int
    role: str
    reason: str


@dataclass
class PlanInput:
    requests: list[RequestInfo]
    people: list[PersonInfo]
    live: list[LiveAssignment]
    out_of_pool: dict[int, str] = field(default_factory=dict)
    sourcer_threshold: int = 15
    mode: str = "shadow"
    # False = brak świeżych danych o urlopach: w trybie automatycznym nikt
    # nie dostaje nowego requestu, bo mógłby go dostać ktoś na urlopie.
    availability_known: bool = True
    # Osoby, które mogłyby dostać request, gdyby nie urlop (rola, kategoria,
    # „Poza przydziałem”). None = nie wiadomo — wtedy zwolnienie czeka na
    # dane o urlopach, jak dotąd.
    eligible_ids: Optional[frozenset[int]] = None
    # Pary (request, osoba) zdjęte ręcznie w bieżącym stanie requestu.
    blocked: frozenset[tuple[int, int]] = frozenset()
    # Konta nieaktywne z żywym przypisaniem — zwalniane zawsze.
    inactive_ids: frozenset[int] = frozenset()


def _bucket(sent: int) -> int:
    return 0 if sent <= 0 else (1 if sent <= 2 else 2)


def request_order(request: RequestInfo) -> tuple:
    return (
        _bucket(request.sent),
        request.deadline or date.max,
        request.job_id,
    )


def needed_role(request: RequestInfo, threshold: int) -> str:
    if request.base_matches is not None and request.base_matches >= threshold:
        return "sourcer"
    return "recruiter"


def _groups(
    request: RequestInfo, people: Iterable[PersonInfo]
) -> list[list[PersonInfo]]:
    first, second, rest = [], [], []
    for person in people:
        if request.categories & person.first:
            first.append(person)
        elif request.categories & person.second:
            second.append(person)
        else:
            rest.append(person)
    return [first, second, rest]


def choose_person(
    request: RequestInfo,
    role: str,
    people: list[PersonInfo],
    load: dict[int, int],
    last: dict[int, float],
) -> Optional[PersonInfo]:
    capable = [
        p for p in people if (p.can_source if role == "sourcer" else p.can_recruit)
    ]
    if not capable:
        return None
    team_min = min(load.get(p.user_id, 0) for p in capable)

    def key(person: PersonInfo) -> tuple:
        return (
            load.get(person.user_id, 0),
            last.get(person.user_id, float("-inf")),
            person.user_id,
        )

    for group in _groups(request, capable):
        if not group:
            continue
        best = min(group, key=key)
        if load.get(best.user_id, 0) <= team_min + 1:
            return best
    return min(capable, key=key)


def _off_mode_releases(data: PlanInput) -> list[Change]:
    """Tryb ``off`` nie przydziela, ale domyka (runda 8, R8-N7-4).

    Bez tego propozycja trybu podglądu przy zamkniętym requeście żyła bez
    końca: filtr „Kto pracuje” ją liczył, pulpit pokazywał „propozycję
    automatu” przy wyłączonym automacie, a po powrocie do ``auto`` była
    aktywowana bez ponownej oceny. Zwalniamy: wyjście z puli, martwe konto
    i każdą propozycję automatu.
    """
    pool = {r.job_id for r in data.requests}
    changes: list[Change] = []
    for row in sorted(data.live, key=lambda r: (r.job_id, r.user_id)):
        if row.job_id not in pool:
            reason = data.out_of_pool.get(row.job_id, "finished")
        elif row.user_id in data.inactive_ids:
            reason = "inactive"
        elif row.state == "proposed":
            reason = "mode_off"
        else:
            continue
        changes.append(Change("release", row.job_id, row.user_id, row.role, reason))
    return changes


def plan_assignments(data: PlanInput) -> list[Change]:
    """Zmiany do zapisania. Czysta funkcja — kolejność wyniku jest stabilna."""
    if data.mode == "off":
        return _off_mode_releases(data)
    changes: list[Change] = []
    people = {p.user_id: p for p in data.people}
    pool = {r.job_id: r for r in data.requests}
    load: dict[int, int] = {}
    covered: set[int] = set()
    # Znaczniki czasu jako liczby: świeżo przydzielona osoba dostaje +inf,
    # więc przy remisie następny request idzie do kogoś innego.
    last = {
        p.user_id: p.last_assigned.timestamp() for p in data.people if p.last_assigned
    }

    for row in sorted(data.live, key=lambda r: (r.job_id, r.user_id)):
        if row.job_id not in pool:
            reason = data.out_of_pool.get(row.job_id, "finished")
            changes.append(Change("release", row.job_id, row.user_id, row.role, reason))
            continue
        if row.user_id in data.inactive_ids:
            # Martwe konto nie pracuje — bez względu na źródło przypisania i
            # kandydatów w toku (tych i tak nikt z tego konta nie poprowadzi).
            changes.append(
                Change("release", row.job_id, row.user_id, row.role, "inactive")
            )
            continue
        person_gone = row.user_id not in people
        if person_gone and row.source == "auto" and not row.in_process:
            not_eligible = (
                data.eligible_ids is not None and row.user_id not in data.eligible_ids
            )
            if not_eligible:
                changes.append(
                    Change("release", row.job_id, row.user_id, row.role, "excluded")
                )
                continue
            if data.availability_known:
                changes.append(
                    Change("release", row.job_id, row.user_id, row.role, "unavailable")
                )
                continue
        # Osoby, której nie ma (urlop, „Poza przydziałem”), nie aktywujemy —
        # także gdy zostaje przy requeście, bo ma kandydatów w toku. Aktywacja
        # zrobiłaby z niej prowadzącą rekrutacji.
        if (
            data.mode == "auto"
            and row.state == "proposed"
            and data.availability_known
            and not person_gone
        ):
            changes.append(Change("activate", row.job_id, row.user_id, row.role, ""))
        covered.add(row.job_id)
        load[row.user_id] = load.get(row.user_id, 0) + 1

    if data.mode == "auto" and not data.availability_known:
        return changes

    sequence = sorted(
        (r for r in data.requests if r.job_id not in covered), key=request_order
    )
    candidates = list(people.values())
    for request in sequence:
        role = needed_role(request, data.sourcer_threshold)
        allowed = [
            p for p in candidates if (request.job_id, p.user_id) not in data.blocked
        ]
        person = choose_person(request, role, allowed, load, last)
        if person is None and role == "sourcer":
            role = "recruiter"
            person = choose_person(request, role, allowed, load, last)
        if person is None:
            continue
        changes.append(Change("assign", request.job_id, person.user_id, role, ""))
        load[person.user_id] = load.get(person.user_id, 0) + 1
        last[person.user_id] = float("inf")
    return changes
