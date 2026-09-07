"""Wycena kontraktów w pieniądze na KONKRETNY DZIEŃ — wspólna dla kokpitu Rady.

Wyniesione z ``app/api/insights_board.py`` w chwili, gdy drugi konsument
(tabele rok-do-roku) potrzebował tej samej operacji. Powód wyniesienia jest
dosłownie ten sam, który docstring tamtego modułu podaje przy punkcie 5:
import ``api.* → api.*`` po to, żeby policzyć marżę, kończy się kopią funkcji
i cichym rozjazdem. Dwie różne kwoty pod jedną nazwą na jednym ekranie to
najgorszy możliwy wynik tej zmiany — kafel „Marża / mc" i komórka „Marża"
w tabeli obok MUSZĄ pochodzić z tej samej funkcji.

Trzy reguły, których nie wolno tu rozluźnić:

* **Stawki idą z HARMONOGRAMÓW** (``effective_rate_fields``), nigdy z kolumn
  ``contracts.rate_*``. Kolumna trzyma wartość z ostatniego ZAPISU kontraktu,
  więc stawka progresywna i aneks z datą, która już nadeszła, pokazują starą
  kwotę. Konsekwencja operacyjna: ``RATE_SCHEDULE_LOADS`` jest OBOWIĄZKOWE
  przy każdym ``select(Contract)``, którego wynik tu trafia — bez tych trzech
  ``selectinload`` resolver robi lazy-load w sesji async, czyli
  ``MissingGreenlet`` → 500 bez nagłówków CORS (front pokazuje „Network Error").
* **Brak kursu NIE kasuje kwoty po cichu.** Pominięcia są liczone i wracają
  w ``MoneyFold``; wołający ma z czego zbudować degradację kafla.
* **Przychód bez kosztu nie ma marży równej przychodowi.** Taki kontrakt
  wchodzi do przychodu i do ``without_cost_leg``, a jego marża pozostaje
  NIEZNANA — dodanie zera zawyżyłoby marżę firmy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional, Sequence

from app.models.contract import Contract, RateUnit
from app.services.contract_rates import effective_rate_fields
from app.services.contractor_identity import summarize_active_contracts
from app.services.fx_service import amount_to_pln_with_rate

# Etykiety miesięcy po polsku, zamiast `strftime("%b")` — tamto zależy od
# locale kontenera, więc na prodzie i lokalnie potrafi dać różne napisy.
MONTH_LABELS_PL = (
    "sty",
    "lut",
    "mar",
    "kwi",
    "maj",
    "cze",
    "lip",
    "sie",
    "wrz",
    "paź",
    "lis",
    "gru",
)

# Ile godzin kryje się za miesięczną kwotą kontraktu rozliczanego DZIENNIE.
# `Contract.monthly_rate` mnoży stawkę dzienną przez 22 (standardowy miesiąc
# roboczy PL), a jeden dzień roboczy to w tym repozytorium 8 godzin — ta sama
# stała, którą polityka odczytu PDF Banku Pocztowego stosuje jako „netto MD ÷ 8"
# (MD = man-day). Nie jest to zgadywanie: obie liczby są już przyjęte gdzie
# indziej, a tutaj tylko się spotykają.
HOURS_PER_WORKDAY = 8
WORKDAYS_PER_MONTH = 22


def ratio(
    numerator: Optional[int | float | Decimal],
    denominator: Optional[int | float | Decimal],
) -> Optional[float]:
    """Udział procentowy albo ``None`` przy zerowym mianowniku.

    NIE zwraca 0.0 — „policzone, wyszło zero" i „nie było czego dzielić" to na
    dashboardzie rady dwie różne odpowiedzi. Świadomie NIE przycinamy też do
    100%: wynik powyżej stu procent oznacza, że definicje licznika i mianownika
    się rozjechały, i ma to być widoczne, a nie schowane pod sufitem osi.

    Ujemny mianownik też daje ``None``: zmiana procentowa liczona od ujemnej
    marży ma znak odwrotny do intuicji i czyta się jako poprawa tam, gdzie
    jest pogorszenie.
    """
    if numerator is None or denominator is None:
        return None
    if Decimal(str(denominator)) <= 0:
        return None
    return round(float(numerator) / float(denominator) * 100, 1)


def money(value: Optional[Decimal]) -> Optional[float]:
    """Kwota do JSON-a: dwa miejsca po przecinku albo ``None``."""
    if value is None:
        return None
    return float(round(value, 2))


@dataclass(frozen=True)
class MoneyFold:
    """Wynik zwinięcia kontraktów w pieniądze na konkretny dzień.

    Pola ``skipped_*`` istnieją po to, żeby brak kursu nie mógł przejść jako
    mniejsza liczba. Oryginał (`reports.py`) robił w tym miejscu ``continue``.
    """

    revenue: Decimal
    cost: Decimal
    margin: Decimal
    priced_contracts: int
    without_cost_leg: int
    consultants: int
    active_contracts: int
    missing_currencies: frozenset
    skipped_revenue: int
    skipped_margin: int
    # Godziny stojące za kwotami, które WESZŁY do marży — mianownik wskaźnika
    # „marża na godzinę". Liczone tylko dla kontraktów, w których liczba godzin
    # wynika z danych (godzinowe i dzienne); miesięczne jej nie niosą.
    margin_hours: Decimal
    margin_with_known_hours: Decimal
    contracts_without_hours: int

    @property
    def complete(self) -> bool:
        return self.skipped_revenue == 0 and self.skipped_margin == 0


def running_on(contracts: Iterable[Contract], on: date) -> list:
    """Kontrakty WYKONYWANE danego dnia (point-in-time).

    Świadomie inne niż „nachodzące na miesiąc" z `reports.py:1660-1676`:
    tamto wliczało pełną miesięczną kwotę kontraktu, który skończył się
    trzeciego dnia miesiąca. Zdjęcie na dzień jest tą samą operacją co kafel
    MRR, więc ostatni punkt serii równa się kaflowi — a wykres, którego nie da
    się porównać z liczbą nad nim, nie daje się zweryfikować wzrokiem.

    Wypowiedzenie kontraktu USTAWIA ``end_date`` (`contracts.py`, handler
    ``/terminate``), więc filtr po datach nie przepuszcza kogoś, kto odszedł
    przed pierwotnym terminem.
    """
    return [
        c
        for c in contracts
        if c.start_date is not None
        and c.start_date <= on
        and (c.end_date is None or c.end_date >= on)
    ]


def _billable_hours(contract: Contract) -> Optional[Decimal]:
    """Ile godzin kryje się za miesięczną kwotą tego kontraktu.

    ``None`` dla rozliczenia miesięcznego — kwota ryczałtowa nie niesie
    informacji o liczbie godzin, a podstawienie 160 zamieniłoby wskaźnik
    „marża na godzinę" w marżę miesięczną podzieloną przez wymyśloną stałą.
    Taki kontrakt wypada z LICZNIKA i z MIANOWNIKA naraz (patrz ``fold_money``),
    więc średnia zostaje liczona z kontraktów, o których naprawdę wiemy.
    """
    if contract.rate_unit == RateUnit.hourly:
        return Decimal(contract.billing_hours_per_month or 160)
    if contract.rate_unit == RateUnit.daily:
        return Decimal(WORKDAYS_PER_MONTH * HOURS_PER_WORKDAY)
    return None


def fold_money(contracts: Sequence[Contract], on: date, rates: dict) -> MoneyFold:
    """Zwiń kontrakty w przychód/koszt/marżę w PLN na dzień ``on``.

    Nogi przychodu i kosztu przeliczane są niezależnie: brak kursu waluty
    kosztu unieważnia marżę tego kontraktu, ale nie wyrzuca poprawnie
    przeliczonego przychodu. Żadna kwota w obcej walucie nie jest nigdy
    traktowana jak PLN po nominale.
    """
    revenue = Decimal("0")
    cost = Decimal("0")
    margin = Decimal("0")
    margin_hours = Decimal("0")
    margin_with_known_hours = Decimal("0")
    contracts_without_hours = 0
    priced = 0
    without_cost_leg = 0
    missing: set = set()
    skipped_revenue = 0
    skipped_margin = 0

    for contract in contracts:
        eff = effective_rate_fields(contract, on)
        client_amount = eff["monthly_rate_client"]
        candidate_amount = eff["monthly_rate_candidate"]
        client_currency = eff["rate_client_currency"]
        candidate_currency = eff["rate_candidate_currency"]

        if client_amount is None:
            # Kontrakt bez wycenionej nogi przychodu — nie ma czego dodać
            # i nie jest to problem z kursem.
            continue
        priced += 1

        client_pln, client_ok = amount_to_pln_with_rate(
            client_amount, rates.get(client_currency)
        )
        if not client_ok:
            missing.add(client_currency)
            skipped_revenue += 1
            skipped_margin += 1
            continue
        assert client_pln is not None
        revenue += client_pln

        if candidate_amount is None:
            # Przychód bez kosztu: marża tego wiersza jest NIEZNANA, a nie
            # równa przychodowi. Dodanie zera zawyżyłoby marżę firmy.
            without_cost_leg += 1
            continue

        candidate_pln, candidate_ok = amount_to_pln_with_rate(
            candidate_amount, rates.get(candidate_currency)
        )
        if not candidate_ok:
            missing.add(candidate_currency)
            skipped_margin += 1
            continue
        assert candidate_pln is not None
        cost += candidate_pln
        row_margin = client_pln - candidate_pln
        margin += row_margin

        hours = _billable_hours(contract)
        if hours is None or hours <= 0:
            contracts_without_hours += 1
        else:
            margin_hours += hours
            margin_with_known_hours += row_margin

    headcount = summarize_active_contracts(contracts)
    return MoneyFold(
        revenue=revenue,
        cost=cost,
        margin=margin,
        priced_contracts=priced,
        without_cost_leg=without_cost_leg,
        consultants=headcount.contractors,
        active_contracts=headcount.active_contracts,
        missing_currencies=frozenset(missing),
        skipped_revenue=skipped_revenue,
        skipped_margin=skipped_margin,
        margin_hours=margin_hours,
        margin_with_known_hours=margin_with_known_hours,
        contracts_without_hours=contracts_without_hours,
    )


def margin_per_hour(fold: MoneyFold) -> Optional[float]:
    """Marża na godzinę — ważona, z kontraktów o ZNANEJ liczbie godzin.

    ``None``, gdy żaden kontrakt nie niesie godzin: średnia z pustego zbioru
    nie jest zerem. Licznik i mianownik pochodzą z tego samego podzbioru
    kontraktów — wzięcie pełnej marży i dzielenie jej przez godziny części
    kontraktów zawyżyłoby wskaźnik tym bardziej, im więcej jest ryczałtów.
    """
    if fold.margin_hours <= 0:
        return None
    return float(round(fold.margin_with_known_hours / fold.margin_hours, 2))
