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
    "unavailable": "Osoba niedostępna (urlop albo poza przydziałem)",
    "manual": "Zdjęte ręcznie",
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


def plan_assignments(data: PlanInput) -> list[Change]:
    """Zmiany do zapisania. Czysta funkcja — kolejność wyniku jest stabilna."""
    if data.mode == "off":
        return []
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
        person_gone = row.user_id not in people
        if (
            person_gone
            and row.source == "auto"
            and data.availability_known
            and not row.in_process
        ):
            changes.append(
                Change("release", row.job_id, row.user_id, row.role, "unavailable")
            )
            continue
        if data.mode == "auto" and row.state == "proposed":
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
        person = choose_person(request, role, candidates, load, last)
        if person is None and role == "sourcer":
            role = "recruiter"
            person = choose_person(request, role, candidates, load, last)
        if person is None:
            continue
        changes.append(Change("assign", request.job_id, person.user_id, role, ""))
        load[person.user_id] = load.get(person.user_id, 0) + 1
        last[person.user_id] = float("inf")
    return changes
