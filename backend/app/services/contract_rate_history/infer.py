"""Historia stawek kontraktu z faktur KSeF — czysta reguła, bez bazy.

Audyt finansów 25.11.2026: kontrakty często mają tylko bieżącą stawkę klienta
i kosztową, a gdy stawki zmieniły się w ciągu roku, marża i MRR za wcześniejsze
miesiące są złe. Faktury KSeF niosą historię:

* **stawka klienta** = cena jednostkowa pozycji faktury sprzedaży z osobą
  (MD ÷ 8 → zł/h). Nordea ma rabat 2,5% w netto, a kontrakt trzyma cenę
  z pozycji — porównujemy więc cenę, nie netto;
* **stawka kosztowa** = netto faktur konsultanta za miesiąc ÷ godziny z faktury
  do klienta za ten miesiąc.

Wejście to obserwacje miesiąc po miesiącu (``MonthObservation``, zbiera je
``collect.py``) i harmonogram z NEXUSA; wyjście to kroki do wpisania
(``LegProposal``) z kategorią i powodami, dla których wpis wymaga człowieka.

Reguła:

* **Stała stawka** = co najmniej ``MIN_MONTHS`` miesięcy z rzędu wśród miesięcy
  z obserwacją, w których stawka mieści się w ±``TOLERANCE`` od mediany okresu.
  Pojedynczy miesiąc odstający (inne godziny konsultanta, faktura w złym
  miesiącu) nie jest dowodem i nie przerywa okresu, gdy po nim wraca ta sama
  stawka.
* **Krok** wpisujemy od pierwszego dnia pierwszego miesiąca okresu, gdy stawka
  NEXUSA w którymkolwiek miesiącu okresu różni się o więcej niż ±1%. Kroki
  liczymy po kolei na harmonogramie już z poprzednimi propozycjami, więc po
  okresie „starej” stawki wraca krok z bieżącą, jeśli NEXUS miał tylko ją.
* **Do sprawdzenia** zamiast wpisu: krok sprzed startu kontraktu, krok
  w NEXUSIE wewnątrz okresu z inną stawką (ktoś go wpisał świadomie), osoba
  dopasowana niejednoznacznie (``weak_identity``), otwarte rozliczenie
  w miesiącach od kroku, kontrakt nie w zł/h.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional, Sequence

TOLERANCE = Decimal("0.01")
MAX_AUTO_CHANGE = Decimal("0.50")
MIN_MONTHS = 2
#: Mediana bliżej pełnego złotego niż 0,15% → pełny złoty (netto ÷ godziny
#: daje 168,4999…, a umowa mówi 168,50 albo 170).
WHOLE_SNAP = Decimal("0.0015")
CENT = Decimal("0.01")

CLIENT, COST = "client", "cost"
LEGS = (CLIENT, COST)

#: Kategorie kontraktu w pomiarze i na liście.
OK = "zgodne"
NO_HISTORY = "brak_historii"
CURRENT_GAP = "rozjazd_biezacy"
PAST_ONE_LEG = "rozjazd_w_przeszlosci"

REASON_BEFORE_START = "Okres z faktur zaczyna się przed startem kontraktu."
REASON_HUMAN_STEP = (
    "W NEXUSIE jest krok wewnątrz okresu z faktur — ktoś go wpisał z inną datą."
)
REASON_GAP = (
    "Między poprzednią stawką a tą jest miesiąc bez dowodu — data zmiany niepewna."
)
REASON_LATER = "Po tym okresie faktury pokazują stawkę, której krok nie wyjaśnia."
REASON_BIG = "Różnica ponad 50% — możliwa inna jednostka albo pomyłka w kontrakcie."
REASON_WEAK_IDENTITY = (
    "Osoba na fakturze dopasowana tylko po części nazwiska albo jest imiennik."
)
REASON_OPEN_SETTLEMENT = "Rozliczenie miesiąca od daty kroku nie jest jeszcze przyjęte."
REASON_UNIT = "Kontrakt nie jest w zł/h — stawki z faktur nie da się porównać."
REASON_TODAY = (
    "Krok zmienia dzisiejszą stawkę (a z nią zamówienia i MRR) — decyduje człowiek."
)
REASON_NO_START = "Kontrakt bez daty startu — nie wiadomo, od kiedy liczyć krok bazowy."
BASELINE_NOTE = "Stawka sprzed historii z faktur KSeF"


@dataclass(frozen=True)
class Step:
    effective_from: date
    rate: Decimal


@dataclass(frozen=True)
class MonthObservation:
    """Jedna strona kontraktu w jednym miesiącu (``month`` = 'RRRR-MM')."""

    month: str
    rate: Decimal
    hours: Decimal
    #: Numery faktur, z których wyszła stawka (dowód na karcie, bez kwot osób).
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Period:
    months: tuple[str, ...]
    rate: Decimal

    @property
    def first(self) -> str:
        return self.months[0]


@dataclass(frozen=True)
class ProposedStep:
    leg: str
    effective_from: date
    rate: Decimal
    nexus_rate: Optional[Decimal]
    months: tuple[str, ...]
    evidence: tuple[str, ...]
    reasons: tuple[str, ...] = ()
    #: (stawka z faktur − stawka NEXUSA) × godziny w miesiącach okresu, zł.
    impact: Decimal = Decimal(0)
    #: Krok bazowy od startu kontraktu z dotychczasową stawką: bez niego
    #: miesiące przed pierwszym krokiem z faktur dostałyby jego stawkę
    #: (harmonogram przed pierwszym krokiem czyta najwcześniejszy krok).
    baseline: bool = False

    @property
    def automatic(self) -> bool:
        return not self.reasons


@dataclass(frozen=True)
class ContractInput:
    contract_id: int
    start_date: Optional[date]
    hourly_pln: bool
    client_schedule: tuple[Step, ...]
    cost_schedule: tuple[Step, ...]
    client_scalar: Optional[Decimal]
    cost_scalar: Optional[Decimal]
    client_obs: tuple[MonthObservation, ...] = ()
    cost_obs: tuple[MonthObservation, ...] = ()
    weak_identity: bool = False
    #: Miesiące z rozliczeniem w stanie innym niż „przyjęte”.
    open_settlement_months: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ContractResult:
    contract_id: int
    category: str
    steps: tuple[ProposedStep, ...] = ()
    periods: dict[str, tuple[Period, ...]] = field(default_factory=dict)

    @property
    def automatic(self) -> bool:
        real = [s for s in self.steps if not s.baseline]
        return bool(real) and all(s.automatic for s in real)


def month_start(month: str) -> date:
    return date(int(month[:4]), int(month[5:7]), 1)


def close(a: Decimal, b: Optional[Decimal]) -> bool:
    if b is None or b == 0:
        return False
    return abs(a - b) / abs(b) <= TOLERANCE


def rate_on(
    schedule: Sequence[Step], scalar: Optional[Decimal], day: date
) -> Optional[Decimal]:
    """Stawka NEXUSA w dniu — lustro ``Contract._resolve_scheduled_rate``.

    Ostatni krok ≤ dnia (remis dat: późniejszy wpis); przed wszystkimi krokami
    najwcześniejszy krok; pusty harmonogram — kolumna kontraktu.
    """

    if not schedule:
        return scalar
    past = [(i, s) for i, s in enumerate(schedule) if s.effective_from <= day]
    if past:
        return max(past, key=lambda x: (x[1].effective_from, x[0]))[1].rate
    earliest = min(s.effective_from for s in schedule)
    return max(
        ((i, s) for i, s in enumerate(schedule) if s.effective_from == earliest),
        key=lambda x: x[0],
    )[1].rate


def snap(value: Decimal) -> Decimal:
    whole = value.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if whole and abs(value - whole) / whole <= WHOLE_SNAP:
        return whole
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def periods(observations: Iterable[MonthObservation]) -> tuple[Period, ...]:
    """Okresy stałej stawki (≥ ``MIN_MONTHS`` miesięcy) w kolejności miesięcy.

    Pojedynczy miesiąc odstający między dwoma miesiącami tej samej stawki nie
    przerywa okresu (nie jest dowodem zmiany).
    """

    obs = sorted(observations, key=lambda o: o.month)
    groups: list[list[MonthObservation]] = []
    for o in obs:
        if groups:
            median = Decimal(statistics.median(x.rate for x in groups[-1]))
            if close(o.rate, median):
                groups[-1].append(o)
                continue
        groups.append([o])
    # Odstający pojedynczy miesiąc między dwiema grupami tej samej stawki: sklej.
    merged: list[list[MonthObservation]] = []
    i = 0
    while i < len(groups):
        g = groups[i]
        if (
            merged
            and len(g) == 1
            and i + 1 < len(groups)
            and close(
                Decimal(statistics.median(x.rate for x in groups[i + 1])),
                Decimal(statistics.median(x.rate for x in merged[-1])),
            )
        ):
            merged[-1].extend(groups[i + 1])
            i += 2
            continue
        merged.append(list(g))
        i += 1
    out = []
    for g in merged:
        if len(g) < MIN_MONTHS:
            continue
        rate = snap(Decimal(statistics.median(x.rate for x in g)))
        out.append(Period(months=tuple(x.month for x in g), rate=rate))
    return tuple(out)


def _evidence(
    obs: Sequence[MonthObservation], months: Sequence[str]
) -> tuple[str, ...]:
    wanted = set(months)
    seen: list[str] = []
    for o in obs:
        if o.month in wanted:
            seen.extend(e for e in o.evidence if e not in seen)
    return tuple(seen)


def _next_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y + m // 12}-{m % 12 + 1:02d}"


def _month_end(month: str) -> date:
    return date.fromordinal(month_start(_next_month(month)).toordinal() - 1)


def propose_leg(
    leg: str,
    obs: Sequence[MonthObservation],
    schedule: Sequence[Step],
    scalar: Optional[Decimal],
    *,
    start_date: Optional[date],
    today: date,
    base_reasons: tuple[str, ...] = (),
    open_months: frozenset[str] = frozenset(),
) -> tuple[tuple[Period, ...], tuple[ProposedStep, ...]]:
    found = periods(obs)
    planned: list[Step] = list(schedule)
    steps: list[ProposedStep] = []
    previous: Optional[Period] = None
    for period in found:
        mismatch = [
            m
            for m in period.months
            if not close(period.rate, rate_on(planned, scalar, month_start(m)))
        ]
        if not mismatch:
            previous = period
            continue
        frm = month_start(period.first)
        # Okres zgodny ze stawką z NEXUSA (przed propozycjami) wraca dokładnie
        # do niej — 169,48 z faktur przy 169 w kontrakcie to 169.
        original = rate_on(schedule, scalar, frm)
        value = (
            original
            if original is not None
            and all(
                close(period.rate, rate_on(schedule, scalar, month_start(m)))
                for m in period.months
            )
            else period.rate
        )
        current = rate_on(planned, scalar, frm)
        reasons = list(base_reasons)
        if start_date is not None and frm < start_date.replace(day=1):
            reasons.append(REASON_BEFORE_START)
        last = _month_end(period.months[-1])
        if any(frm < s.effective_from <= last for s in schedule):
            reasons.append(REASON_HUMAN_STEP)
        if previous is not None and _next_month(previous.months[-1]) != period.first:
            reasons.append(REASON_GAP)
        if current and abs(value - current) / current > MAX_AUTO_CHANGE:
            reasons.append(REASON_BIG)
        if any(m >= period.first for m in open_months):
            reasons.append(REASON_OPEN_SETTLEMENT)
        hours = {o.month: o.hours for o in obs}
        impact = sum(
            (
                (value - (rate_on(schedule, scalar, month_start(m)) or value))
                * hours.get(m, Decimal(0))
                for m in period.months
            ),
            Decimal(0),
        )
        steps.append(
            ProposedStep(
                leg=leg,
                effective_from=frm,
                rate=value,
                nexus_rate=original,
                months=period.months,
                evidence=_evidence(obs, period.months),
                reasons=tuple(dict.fromkeys(reasons)),
                impact=impact.quantize(CENT, rounding=ROUND_HALF_UP),
            )
        )
        planned.append(Step(frm, value))
        previous = period
    if not steps:
        return found, ()
    first = min(s.effective_from for s in steps)
    baseline: Optional[ProposedStep] = None
    extra: tuple[str, ...] = ()
    if not schedule or first < min(s.effective_from for s in schedule):
        if start_date is None:
            extra += (REASON_NO_START,)
        elif start_date < first:
            original = rate_on(schedule, scalar, start_date)
            if original is not None:
                baseline = ProposedStep(
                    leg=leg,
                    effective_from=start_date,
                    rate=original,
                    nexus_rate=original,
                    months=(),
                    evidence=(),
                    baseline=True,
                )
                planned.insert(0, Step(start_date, original))
    if not close(
        rate_on(planned, scalar, today) or Decimal(0), rate_on(schedule, scalar, today)
    ):
        extra += (REASON_TODAY,)
    # Miesiąc po okresie kroku, którego harmonogram z propozycjami nie
    # tłumaczy (np. jeden miesiąc innej stawki na końcu danych): krok sięgałby
    # do dziś, a nie wiemy, do kiedy obowiązywał.
    checked = [baseline] if baseline is not None else []
    for step in steps:
        later = [
            o
            for o in obs
            if o.month > step.months[-1]
            and not close(o.rate, rate_on(planned, scalar, month_start(o.month)))
        ]
        more = extra + ((REASON_LATER,) if later else ())
        reasons = tuple(dict.fromkeys(step.reasons + more))
        checked.append(replace(step, reasons=reasons))
    return found, tuple(checked)


def _category(
    data: ContractInput,
    found: dict[str, tuple[Period, ...]],
    steps: Sequence[ProposedStep],
) -> str:
    if not steps:
        return OK
    schedules = {
        CLIENT: (data.client_schedule, data.client_scalar),
        COST: (data.cost_schedule, data.cost_scalar),
    }
    for leg in LEGS:
        if not found[leg]:
            continue
        latest = found[leg][-1]
        schedule, scalar = schedules[leg]
        if not close(
            latest.rate, rate_on(schedule, scalar, month_start(latest.months[-1]))
        ):
            return CURRENT_GAP
    legs_changed = {s.leg for s in steps}
    if legs_changed == set(LEGS):
        client_months = {m for s in steps if s.leg == CLIENT for m in s.months}
        cost_months = {m for s in steps if s.leg == COST for m in s.months}
        if client_months & cost_months:
            return NO_HISTORY
    return PAST_ONE_LEG


def infer(data: ContractInput, today: date) -> ContractResult:
    base: tuple[str, ...] = ()
    if not data.hourly_pln:
        base += (REASON_UNIT,)
    if data.weak_identity:
        base += (REASON_WEAK_IDENTITY,)
    found: dict[str, tuple[Period, ...]] = {}
    steps: list[ProposedStep] = []
    for leg, obs, schedule, scalar in (
        (CLIENT, data.client_obs, data.client_schedule, data.client_scalar),
        (COST, data.cost_obs, data.cost_schedule, data.cost_scalar),
    ):
        found[leg], leg_steps = propose_leg(
            leg,
            obs,
            schedule,
            scalar,
            start_date=data.start_date,
            today=today,
            base_reasons=base,
            open_months=data.open_settlement_months,
        )
        steps.extend(leg_steps)
    return ContractResult(
        contract_id=data.contract_id,
        category=_category(data, found, steps),
        steps=tuple(steps),
        periods=found,
    )
