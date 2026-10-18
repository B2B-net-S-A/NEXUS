"""Reguły propozycji struktury u klienta — czyste funkcje, bez bazy (18.10.2026).

Decyzja Artura: „Propozycja automatu + akcept DL”. Automat wskazuje
menedżera konsultanta u klienta i przełożonego osoby klienta z danych, które
NEXUS już ma; zapisuje dopiero Delivery Lead. Każda propozycja niesie źródła
(dlaczego ta osoba) i pewność:

* **pewna** — najmocniejszy kandydat ma co najmniej ``CERTAIN_SCORE`` punktów,
  a żaden inny ich nie ma (tylko pewne idą do „Zatwierdź pewne”),
* **niepewna** — jest kandydat, ale słabszy albo jest dwóch mocnych naraz,
* **bez** — żadne źródło nie wskazuje osoby klienta.

Punkty źródeł menedżera (``MANAGER_WEIGHTS``): pola kontraktu, w które ktoś
wpisał menedżera (e-mail PM, „Line Manager”, „PM po stronie klienta”) — 3;
osoba kontaktowa z zamówienia, hiring manager rekrutacji, z której przyszedł
konsultant, menedżer kolegów z tego samego zespołu albo tej samej rekrutacji —
2 (kolega, którego menedżer to HM tej rekrutacji, się nie liczy — to ten sam
dowód co HM, bo automat D8 wpisuje HM jako menedżera); kierownik działu konsultanta z karty technologicznej — 2, gdy jedyny w dziale,
inaczej 1; nadawca maila z zamówieniem — 1 (bywa nim zakupowiec albo wspólna
skrzynka). Hiring manager sam nie daje pewności — często menedżer to NIE HM.
Każde źródło liczy się raz na osobę, niezależnie od liczby zamówień.

Przełożony osoby klienta (``reports_to_signals``) z tytułów: osoba z tego
samego działu o najbliższym wyższym szczeblu — 3, gdy jedyna i szczebel wyżej
o jeden, inaczej 2; ktoś z najwyższego szczebla firmy dla dyrektora bez
kandydata w dziale — 1; hiring manager rekrutacji, z których przyszli jej
konsultanci (wyższy szczebel albo bez tytułu) — 2. Kandydat, który już
podlega (wprost albo pośrednio) pod tę osobę, odpada — zatwierdzenie
zamknęłoby pętlę.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Optional

from app.services.job_hiring_manager import name_key

Confidence = Literal["certain", "uncertain", "none"]

CERTAIN_SCORE = 3

MANAGER_WEIGHTS: dict[str, int] = {
    "pm_email": 3,
    "line_manager": 3,
    "client_pm_name": 3,
    "order_contact": 2,
    "job_hiring_manager": 2,
    "same_team": 2,
    "same_job": 2,
    "order_sender": 1,
}
#: ``area_manager`` ma wagę zależną od liczby kierowników działu (2 albo 1).
AREA_SOLE_WEIGHT = 2
AREA_SHARED_WEIGHT = 1

TITLE_SAME_DEPARTMENT_SOLE = 3
TITLE_SAME_DEPARTMENT = 2
TITLE_COMPANY = 1
HM_OF_TEAM = 2

#: Szczeble tytułów (wyżej = wyżej w strukturze). Brak tytułu = szczebel nieznany.
_RANK_PATTERNS: tuple[tuple[int, re.Pattern[str]], ...] = (
    (
        4,
        re.compile(
            r"\b(prezes|wiceprezes|zarząd|ceo|cto|cio|coo|cfo|cdo|cso|chief|board|"
            r"vp|vice[- ]president|managing director|dyrektor generaln|"
            r"dyrektor zarządzając)",
            re.IGNORECASE,
        ),
    ),
    (3, re.compile(r"\b(dyrektor|director|head\b)", re.IGNORECASE)),
    (
        2,
        re.compile(
            r"\b(kierownik|manager|menedżer|menadżer|menedzer|lead|lider|leader|"
            r"koordynator|coordinator|naczelnik|szef)",
            re.IGNORECASE,
        ),
    ),
)
#: Tytuł bez żadnego słowa ze szczebli = specjalista (szczebel 1).
SPECIALIST_RANK = 1


def title_rank(position: Optional[str]) -> Optional[int]:
    """Szczebel z tytułu: 4 zarząd, 3 dyrektor/head, 2 kierownik/lead, 1 reszta."""

    text = " ".join((position or "").split())
    if not text:
        return None
    for rank, pattern in _RANK_PATTERNS:
        if pattern.search(text):
            return rank
    return SPECIALIST_RANK


def department_key(area_id: Optional[int], department: Optional[str]) -> Optional[str]:
    """Dział osoby: dział z listy klienta, a bez niego tekst „Dział” kontaktu."""

    if area_id is not None:
        return f"area:{area_id}"
    text = " ".join((department or "").split()).casefold()
    return f"text:{text}" if text else None


def text_key(value: Optional[str]) -> Optional[str]:
    text = " ".join((value or "").split()).casefold()
    return text or None


# ── Kandydaci i pewność ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Signal:
    source: str
    contact_id: int
    weight: int
    #: Co dokładnie wskazało osobę (tekst pola, tytuł rekrutacji, nazwa zespołu).
    detail: Optional[str] = None


@dataclass(frozen=True)
class Candidate:
    contact_id: int
    score: int
    signals: tuple[Signal, ...]


@dataclass(frozen=True)
class Proposal:
    confidence: Confidence
    candidates: tuple[Candidate, ...]

    @property
    def top(self) -> Optional[Candidate]:
        return self.candidates[0] if self.candidates else None

    @property
    def contact_id(self) -> Optional[int]:
        return self.top.contact_id if self.top else None


def rank_candidates(signals: Iterable[Signal]) -> tuple[Candidate, ...]:
    """Kandydaci od najmocniejszego; to samo źródło liczy się raz na osobę
    (najwyższa waga, pierwszy szczegół)."""

    by_contact: dict[int, dict[str, Signal]] = {}
    for signal in signals:
        sources = by_contact.setdefault(signal.contact_id, {})
        current = sources.get(signal.source)
        if current is None or signal.weight > current.weight:
            sources[signal.source] = signal
    candidates = [
        Candidate(
            contact_id=contact_id,
            score=sum(s.weight for s in sources.values()),
            signals=tuple(
                sorted(sources.values(), key=lambda s: (-s.weight, s.source))
            ),
        )
        for contact_id, sources in by_contact.items()
    ]
    candidates.sort(key=lambda c: (-c.score, -len(c.signals), c.contact_id))
    return tuple(candidates)


def decide(signals: Iterable[Signal]) -> Proposal:
    candidates = rank_candidates(signals)
    if not candidates:
        return Proposal("none", ())
    top, rest = candidates[0], candidates[1:]
    certain = top.score >= CERTAIN_SCORE and all(c.score < CERTAIN_SCORE for c in rest)
    return Proposal("certain" if certain else "uncertain", candidates)


# ── Menedżer konsultanta ────────────────────────────────────────────────────


@dataclass(frozen=True)
class PersonRow:
    """Osoba klienta (kontakt) — to, czego reguły potrzebują."""

    id: int
    name: str
    position: Optional[str] = None
    department: Optional[str] = None
    email: Optional[str] = None
    area_id: Optional[int] = None
    reports_to_id: Optional[int] = None


@dataclass(frozen=True)
class ContractFacts:
    """Kontrakt konsultanta i wszystko, co o jego menedżerze wiadomo."""

    contract_id: int
    client_id: int
    line_manager: Optional[str] = None
    client_pm_name: Optional[str] = None
    client_pm_email: Optional[str] = None
    team_name: Optional[str] = None
    job_id: Optional[int] = None
    job_title: Optional[str] = None
    job_hm_contact_id: Optional[int] = None
    #: Osoby kontaktowe odczytane z zamówień (np. „Nordea Contact”).
    order_contacts: tuple[str, ...] = ()
    #: Adresy nadawców maili z zamówieniami tego kontraktu.
    order_senders: tuple[str, ...] = ()
    #: Dział konsultanta z ostatniej karty technologicznej (``client_areas``).
    area_id: Optional[int] = None
    area_name: Optional[str] = None


@dataclass(frozen=True)
class PeerManager:
    """Kolega u tego samego klienta z wpisanym menedżerem."""

    contract_id: int
    manager_id: int
    team_name: Optional[str]
    job_id: Optional[int]
    job_title: Optional[str]


class ContactIndex:
    """Wyszukiwanie osób klienta po imieniu i nazwisku albo e-mailu."""

    def __init__(self, people: Sequence[PersonRow]) -> None:
        self.people = {person.id: person for person in people}
        self._by_name: dict[frozenset[str], int] = {}
        self._by_mail: dict[str, int] = {}
        for person in sorted(people, key=lambda p: p.id):
            key = name_key(person.name)
            if len(key) >= 2:
                self._by_name.setdefault(key, person.id)
            mail = text_key(person.email)
            if mail:
                self._by_mail.setdefault(mail, person.id)

    def by_name(self, text: Optional[str]) -> Optional[int]:
        """Pełne imię i nazwisko (kolejność, wielkość liter i ogonki bez znaczenia).

        Samo imię albo skrót („Michał R.”) nie wskazuje nikogo — przypięcie
        złej osoby zabrałoby opinię innemu menedżerowi.
        """

        key = name_key(text)
        if len(key) < 2:
            return None
        return self._by_name.get(key)

    def by_email(self, text: Optional[str]) -> Optional[int]:
        mail = text_key(text)
        return self._by_mail.get(mail) if mail else None


# ── Nowa osoba z tekstu „Line Manager” ─────────────────────────────────────

#: Słowo imienia albo nazwiska: litery (min. 2), łącznik w środku, przedrostek
#: z apostrofem („O'Neil”, „D’Angelo”).
_NAME_WORD = re.compile(r"(?:[^\W\d_]['’])?[^\W\d_]{2,}(?:-[^\W\d_]{2,})*")
#: Słowa, które w polu menedżera znaczą „nie wiem” albo opisują rolę, nie osobę.
_NOT_A_NAME = frozenset(
    {
        "brak",
        "nie",
        "tbd",
        "nieznany",
        "nieznana",
        "do",
        "ustalenia",
        "team",
        "zespół",
        "zespol",
        "dział",
        "dzial",
        "kierownik",
        "kierowniczka",
        "manager",
        "menedżer",
        "menadżer",
        "lead",
        "leader",
        "lider",
        "pm",
        "head",
        "dyrektor",
        "klient",
        "client",
        "wakat",
        "vacat",
    }
)
NAME_WORDS_MAX = 4


@dataclass(frozen=True)
class NewPersonHint:
    """„Dodaj X jako menedżera” — osoba z pola kontraktu, której nie ma w kontaktach."""

    name: str
    source: str  # line_manager | client_pm_name


def person_name_from_text(value: Optional[str]) -> Optional[str]:
    """Imię i nazwisko z pola tekstowego albo ``None``, gdy to nie wygląda na osobę.

    Dwa do czterech słów z samych liter (łącznik i apostrof w środku dozwolone),
    każde co najmniej dwuliterowe — inicjał („Jan K.”), cyfry, ukośnik, przecinek,
    e-mail czy „brak” odpadają: zakładanie kontaktu z takiego tekstu dałoby
    w strukturze klienta osobę, której nie ma.
    """

    text = _clean(value)
    if text is None:
        return None
    words = text.split(" ")
    if not 2 <= len(words) <= NAME_WORDS_MAX:
        return None
    if not all(_NAME_WORD.fullmatch(word) for word in words):
        return None
    if any(word.casefold() in _NOT_A_NAME for word in words):
        return None
    return text


def new_person_hint(
    facts: ContractFacts, index: ContactIndex
) -> Optional[NewPersonHint]:
    """Osoba z „Line Manager” (a bez niego z „PM po stronie klienta”), gdy żaden
    kontakt klienta nie ma tego imienia i nazwiska. Nic nie zakłada — kontakt
    powstaje dopiero po kliknięciu DL (``find_or_create_contact``, bez duplikatu)."""

    for source, value in (
        ("line_manager", facts.line_manager),
        ("client_pm_name", facts.client_pm_name),
    ):
        name = person_name_from_text(value)
        if name is None:
            continue
        if index.by_name(name) is not None:
            return None
        return NewPersonHint(name=name, source=source)
    return None


def manager_signals(
    facts: ContractFacts,
    index: ContactIndex,
    *,
    peers: Sequence[PeerManager] = (),
) -> list[Signal]:
    """Źródła wskazujące menedżera konsultanta (tylko osoby TEGO klienta)."""

    w = MANAGER_WEIGHTS
    out: list[Signal] = []

    def add(
        source: str,
        contact_id: Optional[int],
        detail: Optional[str],
        weight: Optional[int] = None,
    ) -> None:
        if contact_id is not None and contact_id in index.people:
            out.append(Signal(source, contact_id, weight or w[source], detail))

    add("pm_email", index.by_email(facts.client_pm_email), None)
    add("line_manager", index.by_name(facts.line_manager), _clean(facts.line_manager))
    add(
        "client_pm_name",
        index.by_name(facts.client_pm_name),
        _clean(facts.client_pm_name),
    )
    for text in facts.order_contacts:
        add("order_contact", index.by_name(text), _clean(text))
    add("job_hiring_manager", facts.job_hm_contact_id, facts.job_title)
    for mail in facts.order_senders:
        add("order_sender", index.by_email(mail), None)

    team = text_key(facts.team_name)
    for peer in peers:
        # Kolega z menedżerem = HM tej rekrutacji to ten sam dowód (od 17.10
        # automat D8 wpisuje HM jako menedżera), nie drugie, niezależne źródło.
        if peer.contract_id == facts.contract_id or (
            facts.job_hm_contact_id is not None
            and peer.manager_id == facts.job_hm_contact_id
        ):
            continue
        if team and text_key(peer.team_name) == team:
            add("same_team", peer.manager_id, _clean(facts.team_name))
        if facts.job_id is not None and peer.job_id == facts.job_id:
            add("same_job", peer.manager_id, facts.job_title)

    if facts.area_id is not None:
        leads = [
            person.id
            for person in index.people.values()
            if person.area_id == facts.area_id
            and (title_rank(person.position) or 0) >= 2
        ]
        weight = AREA_SOLE_WEIGHT if len(leads) == 1 else AREA_SHARED_WEIGHT
        for contact_id in leads:
            add("area_manager", contact_id, facts.area_name, weight)
    return out


# ── Przełożony osoby klienta ────────────────────────────────────────────────


def chain_reaches(
    reports_to: Mapping[int, Optional[int]], *, start_id: int, target_id: int
) -> bool:
    """Czy idąc od ``start_id`` w górę „podlega pod” dochodzimy do ``target_id``."""

    current: Optional[int] = start_id
    seen: set[int] = set()
    while current is not None and current not in seen:
        if current == target_id:
            return True
        seen.add(current)
        current = reports_to.get(current)
    return False


def reports_to_signals(
    subject: PersonRow,
    people: Sequence[PersonRow],
    *,
    hm_of_team: Iterable[tuple[int, Optional[str]]] = (),
) -> list[Signal]:
    """Źródła wskazujące przełożonego osoby klienta.

    ``hm_of_team`` — (kontakt, tytuł rekrutacji): hiring managerowie
    rekrutacji, z których przyszli konsultanci tej osoby.
    """

    chain = {person.id: person.reports_to_id for person in people}

    def allowed(other: PersonRow) -> bool:
        return other.id != subject.id and not chain_reaches(
            chain, start_id=other.id, target_id=subject.id
        )

    out: list[Signal] = []
    rank = title_rank(subject.position)
    dept = department_key(subject.area_id, subject.department)
    if rank is not None:
        if dept is not None:
            higher = [
                (other_rank, other)
                for other in people
                if department_key(other.area_id, other.department) == dept
                and (other_rank := title_rank(other.position)) is not None
                and other_rank > rank
                and allowed(other)
            ]
            if higher:
                nearest = min(r for r, _ in higher)
                closest = [other for r, other in higher if r == nearest]
                sole = len(closest) == 1 and nearest - rank == 1
                for other in closest:
                    out.append(
                        Signal(
                            "title_same_department",
                            other.id,
                            TITLE_SAME_DEPARTMENT_SOLE
                            if sole
                            else TITLE_SAME_DEPARTMENT,
                            other.position,
                        )
                    )
        if not out and rank == 3:
            top = [
                other
                for other in people
                if title_rank(other.position) == 4 and allowed(other)
            ]
            for other in top:
                out.append(
                    Signal("title_company", other.id, TITLE_COMPANY, other.position)
                )
    by_id = {person.id: person for person in people}
    for contact_id, job_title in hm_of_team:
        other = by_id.get(contact_id)
        if other is None or not allowed(other):
            continue
        other_rank = title_rank(other.position)
        if rank is None or other_rank is None or other_rank > rank:
            out.append(Signal("hm_of_team", other.id, HM_OF_TEAM, job_title))
    return out


def _clean(value: Optional[str]) -> Optional[str]:
    text = " ".join((value or "").split())
    return text or None
