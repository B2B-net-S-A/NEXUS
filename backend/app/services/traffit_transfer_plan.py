"""Plan przeniesienia jednej rekrutacji z Traffita — czysta logika, bez bazy i sieci.

Wejście: kto na jakim stanie stoi DZIŚ w Traffit (lista osób per stan z
``/recruitments/{id}/states/{stan}/employees``) oraz wszystkie wiersze
``candidate_stages`` tej rekrutacji w NEXUSIE. Wyjście: co trzeba poprawić,
żeby Tablica pokazywała to samo co Traffit w chwili przeniesienia.

Pomiar na produkcji 11.10.2026 (185 rekrutacji, 6 310 osób): 99,2% osób stoi
w NEXUSIE na tym samym stanie co w Traffit. Reszta to trzy przypadki i każdy
ma tu własną akcję:

* **remis czasu** — Traffit zapisuje dwa wpisy historii z tą samą datą
  („Nowy” i „Screening” w jednej sekundzie), a bieżący etap pary liczy się po
  ``(moved_at, id)``. Import czyta historię od najnowszych, więc nowszy wpis
  dostaje NIŻSZE ``id`` i przegrywa remis. Właściwy wiersz już jest w bazie —
  wystarczy go wysunąć o milisekundę (:class:`Promote`), bez nowego zdarzenia
  w statystykach;
* **brak wiersza** — osoba stoi w Traffit na stanie, którego NEXUS nie ma
  w historii pary (wpis pominięty przy imporcie) → nowy wiersz
  (:class:`Insert`);
* **osoba zdjęta z rekrutacji w Traffit** — import czyta tylko historię
  ruchów, więc o zdjęciu nie wie i karta zostaje → :class:`Remove`.

Ruch zrobiony w NEXUSIE wygrywa: para, której ostatni wiersz nie pochodzi
z Traffita, nie jest poprawiana ani zdejmowana. Karty bez żadnego wiersza
z Traffita (dodane w NEXUSIE, ze scrapera) zostają nietknięte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Mapping, Optional, Sequence

TRAFFIT = "traffit"
#: O ile wysuwamy wiersz, który przegrał remis czasu.
TIE_STEP = timedelta(milliseconds=1)


@dataclass(frozen=True)
class StageRow:
    """Jeden wiersz ``candidate_stages`` rekrutacji."""

    row_id: int
    candidate_id: int
    #: Numer osoby w Traffit, gdy kandydat pochodzi z Traffita.
    emp: Optional[str]
    #: ``candidate_stages.external_source`` (``traffit`` albo ruch NEXUSA).
    source: Optional[str]
    #: Numer stanu Traffita, na który wskazuje etap wiersza (``None`` = etap NEXUSA).
    state_ext: Optional[str]
    moved_at: datetime


@dataclass(frozen=True)
class Promote:
    """Wiersz właściwego stanu przegrał remis czasu — wysuń go na wierzch."""

    candidate_id: int
    row_id: int
    moved_at: datetime


@dataclass(frozen=True)
class Insert:
    """Pary brakuje wiersza stanu, na którym osoba stoi w Traffit."""

    candidate_id: int
    emp: str
    state_ext: str


@dataclass(frozen=True)
class Remove:
    """Osoba zdjęta z rekrutacji w Traffit — karta schodzi z Tablicy."""

    candidate_id: int
    row_id: int


@dataclass
class JobPlan:
    people_in_traffit: int = 0
    matched: int = 0
    #: Ostatni ruch pary zrobiono w NEXUSIE — zostaje jak jest.
    nexus_on_top: int = 0
    #: Karty bez żadnego wiersza z Traffita (NEXUS, scraper) — nietknięte.
    nexus_only: int = 0
    #: Ostatni wiersz z Traffita, ale kandydat nie ma numeru osoby Traffita
    #: (np. po scaleniu) — nie da się sprawdzić, więc nie ruszamy.
    unverified: int = 0
    promotes: list[Promote] = field(default_factory=list)
    inserts: list[Insert] = field(default_factory=list)
    removes: list[Remove] = field(default_factory=list)
    #: Osoby z Traffita, których NEXUS nie ma wcale (np. karta-duplikat).
    unknown_people: list[str] = field(default_factory=list)

    @property
    def corrections(self) -> int:
        return len(self.promotes) + len(self.inserts) + len(self.removes)


def _latest(rows: Sequence[StageRow]) -> StageRow:
    """Bieżący wiersz pary — ten sam porządek co ``pipeline_latest``."""
    return max(rows, key=lambda r: (r.moved_at, r.row_id))


def plan_job(
    traffit: Mapping[str, str],
    rows: Sequence[StageRow],
    emp_to_candidate: Mapping[str, int],
) -> JobPlan:
    """Porównaj stan z Traffita z wierszami NEXUSA i ułóż poprawki.

    ``traffit``: numer osoby → numer stanu, na którym stoi dziś.
    ``emp_to_candidate``: kandydaci NEXUSA dla osób z ``traffit`` (także ci
    bez żadnego wiersza w tej rekrutacji).
    """
    plan = JobPlan(people_in_traffit=len(traffit))
    by_candidate: dict[int, list[StageRow]] = {}
    for row in rows:
        by_candidate.setdefault(row.candidate_id, []).append(row)

    by_emp: dict[str, list[StageRow]] = {}
    for candidate_rows in by_candidate.values():
        emp = candidate_rows[0].emp
        if emp:
            by_emp[emp] = candidate_rows

    for emp, state in traffit.items():
        candidate_rows = by_emp.get(emp)
        if candidate_rows is None:
            candidate_id = emp_to_candidate.get(emp)
            if candidate_id is None:
                plan.unknown_people.append(emp)
            elif candidate_id in by_candidate:
                # Kandydat ma tu kartę, ale pod innym numerem osoby — nie
                # zgadujemy, która karta Traffita jest tą właściwą.
                plan.unverified += 1
            else:
                plan.inserts.append(Insert(candidate_id, emp, state))
            continue
        latest = _latest(candidate_rows)
        if latest.source != TRAFFIT:
            plan.nexus_on_top += 1
        elif latest.state_ext == state:
            plan.matched += 1
        else:
            tied = [
                r
                for r in candidate_rows
                if r.source == TRAFFIT
                and r.state_ext == state
                and r.moved_at == latest.moved_at
            ]
            if tied:
                winner = max(tied, key=lambda r: r.row_id)
                plan.promotes.append(
                    Promote(
                        winner.candidate_id, winner.row_id, latest.moved_at + TIE_STEP
                    )
                )
            else:
                plan.inserts.append(Insert(latest.candidate_id, emp, state))

    for candidate_rows in by_candidate.values():
        emp = candidate_rows[0].emp
        if emp and emp in traffit:
            continue
        latest = _latest(candidate_rows)
        if not any(r.source == TRAFFIT for r in candidate_rows):
            plan.nexus_only += 1
        elif latest.source != TRAFFIT:
            plan.nexus_on_top += 1
        elif not emp:
            plan.unverified += 1
        else:
            plan.removes.append(Remove(latest.candidate_id, latest.row_id))
    return plan


def roster_is_trustworthy(
    traffit: Mapping[str, str], roster_total: Optional[int]
) -> bool:
    """Czy lista „osoby per stan” jest kompletna.

    Suma osób ze stanów musi się zgadzać z licznikiem składu rekrutacji
    (``/recruitments/{id}/employees``). Urwana odpowiedź Traffita wyglądałaby
    inaczej jak masowe zdjęcie ludzi z rekrutacji — wtedy niczego nie
    poprawiamy.
    """
    return roster_total is not None and roster_total == len(traffit)


__all__ = [
    "Insert",
    "JobPlan",
    "Promote",
    "Remove",
    "StageRow",
    "TIE_STEP",
    "plan_job",
    "roster_is_trustworthy",
]
