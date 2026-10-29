"""Czysty planer przydziału ludzi do requestów (decyzje Artura 24.09.2026).

Bez bazy i bez zegara — dostaje stan świata, oddaje listę zmian. Warstwa
zapisu to ``services/request_allocation``. Reguły:

* **Pula:** requesty „Szukamy kandydatów” bez championa. Request, który z niej
  wyszedł (champion, „Klient milczy”, „Zakończony”), zwalnia swoich ludzi.
* **Tylko P1** (prośba Head of Recruitment, 12.10.2026): automat dobiera
  i proponuje ludzi wyłącznie do requestów P1 (``automat_assigns``). Request
  P2 zostaje w puli, jego ludzie zostają, ale po zdjęciu osoby nikt nie jest
  dokładany — do tej daty automat brał następną osobę i ręczne zdjęcie
  z requestu P2 niczego nie zmieniało. Propozycja przy takim requeście jest
  zwalniana (``not_p1``). Urlop nie zwalnia osoby z takiego requestu (nikt
  by jej nie zastąpił); „Poza przydziałem” i martwe konto zwalniają jak
  wszędzie, ale bez następcy.
* **Kolejność:** requesty bez nikogo wysłanego do klienta, potem 1–2 wysłane,
  potem 3+; w grupie najbliższy termin (brak terminu na końcu).
* **„Przyjmujemy kandydatów”** (``passive``): jak wyżej — request zostaje
  w puli, jego ludzie zostają, automat nikogo nowego nie dobiera ani nie
  proponuje; propozycja ma własny powód zwolnienia.
* **Ktoś już pracuje:** request z osobą, która nad nim pracuje (aktywne
  przypisanie albo ``staffed`` — osoby bez wiersza, np. ręcznie dopisany
  współpracownik), jest pokryty, a propozycja przy nim jest zwalniana.
  Propozycja to nie praca: pokrywa request i liczy się do obłożenia tylko
  wtedy, gdy nikt przy nim nie pracuje.
* **Kto:** 1. priorytet kategorii requestu → 2. priorytet → pozostali.
  W grupie najmniej requestów P1, potem ten, kto najdawniej coś dostał. Do
  następnej grupy przechodzimy, gdy grupa jest pusta albo jej najmniej
  obłożona osoba ma o więcej niż 1 request więcej niż najmniej obłożona
  osoba w całym zespole — to jest „przelew” między kategoriami.
  **Obłożenie liczy tylko P1** (decyzja Artura 14.10.2026, ta sama liczba co
  „Obłożenie” na pulpicie): request bez priorytetu i „Przyjmujemy” nie czyni
  osoby zajętą.
* **Stabilność:** planer NIE przerzuca działających przypisań, żeby wyrównać
  liczby. Zwalnia tylko wtedy, gdy request wyszedł z puli albo osoba (z
  przypisaniem automatu) przestała być dostępna — i nawet wtedy nie, jeśli ma
  przy tym requeście kandydatów w toku. Ręczne przypisania zostają zawsze.
* **Nieaktywne konto** zwalnia każde swoje przypisanie (także ręczne i z
  kandydatami w toku) — takie konto nie pracuje i nikt go już nie zobaczy
  na pulpicie, a request stałby „pokryty” na zawsze (audyt 25.09.2026).
* **Decyzja człowieka wygrywa:** osoba zdjęta z requestu ręcznie nie wraca
  do niego z automatu, dopóki request nie zmieni stanu (``blocked``).
* **Nieaktualne urlopy z Compassa** (``leave_blocks_auto``): tryb ``auto``
  niczego nie przydziela ani nie aktywuje, bo request mógłby dostać ktoś na
  urlopie. Gdy urlopy z Compassa są wyłączone, nie ma na co czekać — automat
  przydziela od razu. Osoba „Poza przydziałem” albo bez kategorii jest
  zwalniana zawsze, bo to nie zależy od Compassa (``eligible_ids``).
* **Zasady z Ustawień** (``PlanRules``, 29.10.2026): P2, ilu ludzi na P1,
  limit P1 na osobę, przelew, osoby spoza kategorii, kolejność. Domyślne
  wartości = reguły opisane wyżej. Zasady zmieniają tylko **nowe**
  przydziały i propozycje: żadna nie zwalnia osoby, która już pracuje
  (Artur: „nic nie zmieniaj w tych, co są już przydzielone”). Urlop dalej
  zwalnia tylko przy P1 — tam, gdzie automat dobierał przed tą zmianą.
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
    # Ręczne zdjęcie, po którym człowiek przypisał tę samą osobę ponownie.
    "reassigned": "Zdjęte ręcznie, potem przypisane ponownie",
    "inactive": "Konto nieaktywne",
    "mode_off": "Automat wyłączony",
    # 02.10.2026: propozycje do akceptacji przez Head of Recruitment.
    "superseded": "Przydzielono kogoś innego",
    "passive": "Request tylko przyjmuje kandydatów",
    # 12.10.2026: automat dobiera ludzi tylko do P1.
    "not_p1": "Automat dobiera tylko do requestów P1",
    "rejected": "Propozycja odrzucona",
    "replaced": "Wybrano inną osobę",
    # 14.10.2026: zejście z P1 — osoba przeszła do „Poprzedni rekruter”.
    "parked": "Rekrutacja zeszła z P1",
}

# Runda 9 (R9-V2-1): zwolniona PROPOZYCJA automatu (tryb podglądu) nie jest
# śladem tego, że automat wpisał prowadzącego — nigdy nie była aktywna.
# Przedrostek przy powodzie odróżnia ją od zwolnionego aktywnego przydziału.
PROPOSAL_RELEASE_PREFIX = "proposal:"


def release_reason_label(reason: Optional[str], default: Optional[str] = None):
    """Etykieta powodu zwolnienia, także dla zwolnionej propozycji."""
    if reason and reason.startswith(PROPOSAL_RELEASE_PREFIX):
        reason = reason[len(PROPOSAL_RELEASE_PREFIX) :]
    return RELEASE_REASONS.get(reason or "", default)


def is_silent_release(reason: Optional[str]) -> bool:
    """Zwolnienie, które nie jest zmianą obsady.

    Wycofana albo odrzucona PROPOZYCJA: osoba nigdy tego requestu nie dostała,
    więc „Zwolnione: …” mówiłoby o czymś, co się nie wydarzyło. Tak samo
    ręczne zdjęcie, po którym człowiek przypisał tę samą osobę ponownie —
    request ma nadal. Czytają to poranny skrót i „Zmiany od wczoraj” pulpitu.
    """
    return bool(reason) and (
        reason.startswith(PROPOSAL_RELEASE_PREFIX) or reason == "reassigned"
    )


@dataclass(frozen=True)
class RequestInfo:
    job_id: int
    categories: frozenset[int]
    primary_category: Optional[int]
    sent: int
    deadline: Optional[date]
    base_matches: Optional[int]
    # 0 = P1, 1 = reszta (``job_priority.priority_rank``).
    priority_rank: int = 1
    # „Przyjmujemy kandydatów” — nie szukamy aktywnie, automat nikogo nie dobiera.
    passive: bool = False

    @property
    def automat_assigns(self) -> bool:
        """P0/P1 — tu automat dobiera zawsze, z tego liczy się obłożenie,
        i tylko tu urlop zwalnia osobę (bo jest następca)."""
        return self.priority_rank == 0 and not self.passive

    def staffed_by(self, rules: "PlanRules") -> bool:
        """Czy automat dobiera ludzi do tej rekrutacji przy danych zasadach.
        P0/P1 zawsze, P2 tylko z ``include_p2``, „Przyjmujemy” nigdy."""
        if self.passive:
            return False
        return self.priority_rank == 0 or rules.include_p2

    def wanted(self, rules: "PlanRules") -> int:
        """Ilu ludzi automat chce mieć przy rekrutacji. P2 — jedna osoba."""
        return rules.people_per_p1 if self.priority_rank == 0 else 1


@dataclass(frozen=True)
class PersonInfo:
    user_id: int
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


@dataclass(frozen=True)
class PlanRules:
    """Zasady z Ustawień (``request_allocation_rules``). Domyślne = stan
    sprzed 29.10.2026."""

    include_p2: bool = False
    people_per_p1: int = 1
    max_load: Optional[int] = None
    overflow: int = 1
    outsiders: bool = True
    order: str = "sent_first"


@dataclass
class PlanInput:
    requests: list[RequestInfo]
    people: list[PersonInfo]
    live: list[LiveAssignment]
    out_of_pool: dict[int, str] = field(default_factory=dict)
    mode: str = "shadow"
    # False = brak świeżych danych o urlopach: osoby spoza listy dostępnych
    # nie zwalniamy z powodem „na urlopie”, bo tego nie wiemy.
    availability_known: bool = True
    # True = urlopy z Compassa są włączone, ale nieaktualne: w trybie
    # automatycznym nikt nie dostaje nowego requestu, bo mógłby go dostać ktoś
    # na urlopie. Przy wyłączonych urlopach automat przydziela bez czekania.
    leave_blocks_auto: bool = False
    # Osoby, które mogłyby dostać request, gdyby nie urlop (rola, kategoria,
    # „Poza przydziałem”). None = nie wiadomo — wtedy zwolnienie czeka na
    # dane o urlopach, jak dotąd.
    eligible_ids: Optional[frozenset[int]] = None
    # Pary (request, osoba) zdjęte ręcznie w bieżącym stanie requestu.
    blocked: frozenset[tuple[int, int]] = frozenset()
    # Konta nieaktywne z żywym przypisaniem — zwalniane zawsze.
    inactive_ids: frozenset[int] = frozenset()
    # Requesty z puli, nad którymi pracuje ktoś bez aktywnego wiersza
    # przypisania (np. ręcznie dopisany współpracownik) — pokryte, bez nowej
    # propozycji.
    staffed: frozenset[int] = frozenset()
    # Ile takich requestów P1 ma każda osoba — dolicza się do obłożenia.
    extra_load: dict[int, int] = field(default_factory=dict)
    # Osoby bez wiersza przy requeście (job_id → user_id) — liczą się do
    # obsady przy „ilu ludzi na rekrutację” i nie dostają tego requestu
    # drugi raz. Brak wpisu przy requeście ze ``staffed`` = jedna osoba.
    staffed_people: dict[int, frozenset[int]] = field(default_factory=dict)
    # Ile requestów spoza P1 obsadzonych przez automat ma każda osoba — przy
    # wyborze osoby do P2 (obłożenie P1 zostaje miarą limitu i P1).
    other_load: dict[int, int] = field(default_factory=dict)
    rules: PlanRules = field(default_factory=PlanRules)


def _bucket(sent: int) -> int:
    return 0 if sent <= 0 else (1 if sent <= 2 else 2)


def request_order(request: RequestInfo, order: str = "sent_first") -> tuple:
    if order == "deadline_first":
        return (
            request.priority_rank,
            request.deadline or date.max,
            _bucket(request.sent),
            request.job_id,
        )
    return (
        request.priority_rank,
        _bucket(request.sent),
        request.deadline or date.max,
        request.job_id,
    )


# Rola pracy nowego przypisania. Do 0411 automat wybierał między rekruterem
# a sourcerem (próg pasujących w bazie); od połączenia ról jest jedna.
WORK_ROLE = "recruiter"


def category_fit(
    request_categories: Iterable[int], first: Iterable[int], second: Iterable[int]
) -> str:
    """Jak kategorie osoby mają się do requestu: ``first`` (1. priorytet),
    ``second`` (2. priorytet) albo ``other``. Ta sama reguła dobiera osobę
    i opisuje propozycję na pulpicie."""
    wanted = set(request_categories)
    if wanted & set(first):
        return "first"
    if wanted & set(second):
        return "second"
    return "other"


def _groups(
    request: RequestInfo, people: Iterable[PersonInfo]
) -> list[list[PersonInfo]]:
    groups: dict[str, list[PersonInfo]] = {"first": [], "second": [], "other": []}
    for person in people:
        groups[category_fit(request.categories, person.first, person.second)].append(
            person
        )
    return [groups["first"], groups["second"], groups["other"]]


def choose_person(
    request: RequestInfo,
    people: list[PersonInfo],
    load: dict[int, int],
    last: dict[int, float],
    rules: PlanRules = PlanRules(),
) -> Optional[PersonInfo]:
    capable = people
    if not capable:
        return None
    team_min = min(load.get(p.user_id, 0) for p in capable)

    def key(person: PersonInfo) -> tuple:
        return (
            load.get(person.user_id, 0),
            last.get(person.user_id, float("-inf")),
            person.user_id,
        )

    groups = _groups(request, capable)
    if not rules.outsiders:
        # Osoba bez kategorii rekrutacji jej nie dostaje — czeka na człowieka.
        groups = groups[:2]
        capable = [p for group in groups for p in group]
        if not capable:
            return None
    for group in groups:
        if not group:
            continue
        best = min(group, key=key)
        if load.get(best.user_id, 0) <= team_min + rules.overflow:
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


def _own_release_reason(
    row: LiveAssignment,
    data: PlanInput,
    pool: dict[int, RequestInfo],
    people: dict[int, PersonInfo],
) -> Optional[str]:
    """Powód zwolnienia wiersza, który nie zależy od innych osób przy requeście."""
    if row.job_id not in pool:
        return data.out_of_pool.get(row.job_id, "finished")
    if row.user_id in data.inactive_ids:
        # Martwe konto nie pracuje — bez względu na źródło przypisania i
        # kandydatów w toku (tych i tak nikt z tego konta nie poprowadzi).
        return "inactive"
    if row.user_id not in people and row.source == "auto" and not row.in_process:
        if data.eligible_ids is not None and row.user_id not in data.eligible_ids:
            return "excluded"
        # Urlop zwalnia tylko tam, gdzie automat dobierze następcę. Przy
        # requeście innym niż P1 nikt by osoby nie zastąpił, a zwolnienie
        # automatu jest trwałe — request zostałby bez rekrutera na stałe.
        if data.availability_known and pool[row.job_id].automat_assigns:
            return "unavailable"
    return None


def plan_assignments(data: PlanInput) -> list[Change]:
    """Zmiany do zapisania. Czysta funkcja — kolejność wyniku jest stabilna."""
    if data.mode == "off":
        return _off_mode_releases(data)
    changes: list[Change] = []
    people = {p.user_id: p for p in data.people}
    pool = {r.job_id: r for r in data.requests}
    # Osoby bez aktywnego wiersza (np. ręczni współpracownicy) też pracują:
    # ich requesty są pokryte, a obłożenie dolicza się do liczby z wierszy.
    rules = data.rules
    load: dict[int, int] = dict(data.extra_load)
    other_load: dict[int, int] = dict(data.other_load)
    # Kto już jest przy requeście (pracuje albo ma żywą propozycję) — obsada
    # przy „ilu ludzi na rekrutację” i lista osób, których nie dokładamy drugi raz.
    at_job: dict[int, set[int]] = {
        job_id: set(data.staffed_people.get(job_id, frozenset()))
        for job_id in data.staffed
    }
    unseen = {
        job_id: max(1, len(data.staffed_people.get(job_id, frozenset())))
        for job_id in data.staffed
    }
    # Znaczniki czasu jako liczby: świeżo przydzielona osoba dostaje +inf,
    # więc przy remisie następny request idzie do kogoś innego.
    last = {
        p.user_id: p.last_assigned.timestamp() for p in data.people if p.last_assigned
    }

    rows = [
        (row, _own_release_reason(row, data, pool, people))
        for row in sorted(data.live, key=lambda r: (r.job_id, r.user_id))
    ]
    # Requesty, nad którymi ktoś pracuje: aktywne przypisanie, które zostaje,
    # albo osoba bez wiersza. Propozycja się tu nie liczy.
    workers: dict[int, int] = dict(unseen)
    for row, reason in rows:
        if reason is None and row.state != "proposed":
            workers[row.job_id] = workers.get(row.job_id, 0) + 1
    kept_proposals: dict[int, int] = {}
    for row, reason in rows:
        if reason is None and row.state == "proposed":
            # Propozycja to nie praca. Znika, gdy request tylko przyjmuje
            # kandydatów, automat do niego nie dobiera (P2 bez zasady „P2”)
            # albo gdy obsada jest już pełna (Delivery Lead przypisał
            # rekrutera, rekruter wziął request sam) — inaczej Head of
            # Recruitment akceptowałby osobę do requestu, który ma obsadę,
            # a tryb „auto” aktywowałby ją przy P2.
            request = pool[row.job_id]
            filled = workers.get(row.job_id, 0) + kept_proposals.get(row.job_id, 0)
            if request.passive:
                reason = "passive"
            elif not request.staffed_by(rules):
                reason = "not_p1"
            elif filled >= request.wanted(rules):
                reason = "superseded"
            else:
                kept_proposals[row.job_id] = kept_proposals.get(row.job_id, 0) + 1
        if reason is not None:
            changes.append(Change("release", row.job_id, row.user_id, row.role, reason))
            continue
        # Osoby, której nie ma (urlop, „Poza przydziałem”), nie aktywujemy —
        # także gdy zostaje przy requeście, bo ma kandydatów w toku. Aktywacja
        # zrobiłaby z niej prowadzącą rekrutacji.
        if (
            data.mode == "auto"
            and row.state == "proposed"
            and not data.leave_blocks_auto
            and row.user_id in people
        ):
            changes.append(Change("activate", row.job_id, row.user_id, row.role, ""))
        at_job.setdefault(row.job_id, set()).add(row.user_id)
        # Obłożenie = requesty P1, jak na pulpicie (14.10.2026): osoba
        # z requestami spoza P1 nie jest przez nie „zajęta” dla automatu.
        if pool[row.job_id].automat_assigns:
            load[row.user_id] = load.get(row.user_id, 0) + 1
        else:
            other_load[row.user_id] = other_load.get(row.user_id, 0) + 1

    if data.mode == "auto" and data.leave_blocks_auto:
        return changes

    filled = {
        r.job_id: workers.get(r.job_id, 0) + kept_proposals.get(r.job_id, 0)
        for r in data.requests
    }
    sequence = sorted(
        (
            r
            for r in data.requests
            if r.staffed_by(rules) and filled[r.job_id] < r.wanted(rules)
        ),
        key=lambda r: request_order(r, rules.order),
    )
    candidates = list(people.values())
    for request in sequence:
        for _ in range(request.wanted(rules) - filled[request.job_id]):
            taken = at_job.setdefault(request.job_id, set())
            allowed = [
                p
                for p in candidates
                if (request.job_id, p.user_id) not in data.blocked
                and p.user_id not in taken
            ]
            if request.automat_assigns:
                # Limit liczy rekrutacje P1, jak „Obłożenie” na pulpicie.
                if rules.max_load is not None:
                    allowed = [
                        p for p in allowed if load.get(p.user_id, 0) < rules.max_load
                    ]
                person = choose_person(request, allowed, load, last, rules)
            else:
                # P2: obłożenie P1 plus requesty P2 od automatu, żeby kolejne
                # przebiegi nie dawały wszystkiego jednej osobie.
                combined = {
                    p.user_id: load.get(p.user_id, 0) + other_load.get(p.user_id, 0)
                    for p in allowed
                }
                person = choose_person(request, allowed, combined, last, rules)
            if person is None:
                break
            changes.append(
                Change("assign", request.job_id, person.user_id, WORK_ROLE, "")
            )
            taken.add(person.user_id)
            if request.automat_assigns:
                load[person.user_id] = load.get(person.user_id, 0) + 1
            else:
                other_load[person.user_id] = other_load.get(person.user_id, 0) + 1
            last[person.user_id] = float("inf")
    return changes
