"""Populacja konsultantów — JEDNA definicja utylizacji i ławki.

Audyt 18.09.2026: `GET /api/contract-analytics/utilization` zwracał
``utilization_pct = 0.8`` i ``candidates_on_bench = 56 647`` przy realnym
``91,3%`` i ``45`` osobach na ławce — błąd **114×**. Przyczyną nie była
arytmetyka, tylko MIANOWNIK: endpoint liczył `outerjoin(Contract)` bez filtra
statusu, więc dzielił aktywnych konsultantów przez **całą bazę CV** (62 tys.
osób, w większości kandydatów, którzy nigdy nie mieli u nas kontraktu).

Ten sam ekran przeczył sam sobie: ``avg_bench_days`` liczyło się wyłącznie po
osobach, które MAJĄ jakąś datę końca kontraktu (45), a licznik pod nim mówił
o 56 647 „osobach bez kontraktu”.

Kanoniczna definicja stała obok, w ``analytics/metrics.py``
(``_bench_and_utilization``), z docstringiem mówiącym wprost: „mianownik to
populacja konsultantów…, nie cała baza”. Nie była współdzielona — dlatego
mieszka teraz tutaj i czytają ją oba miejsca.

**Ława to osoba, nie kontrakt.** Duplikaty profili fałdują się po tożsamości
(``contractor_identity``), więc jedna osoba z dwoma profilami liczy się raz —
inaczej utylizacja rosłaby przy każdym scaleniu duplikatów.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Hashable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus
from app.services.contract_rates import REVENUE_BEARING_STATUSES
from app.services.contractor_identity import candidate_identity_key
from app.core.scheduling import business_today

_LIVE_STATUSES = frozenset({ContractStatus.active, ContractStatus.ending})

IdentityKey = tuple[Hashable, ...]


@dataclass(frozen=True)
class ConsultantPopulation:
    """Osoby, które kiedykolwiek pracowały u nas do dnia ``on``."""

    on: date
    active_keys: frozenset[IdentityKey]
    ever_keys: frozenset[IdentityKey]
    #: Ostatni znany koniec kontraktu per osoba — tylko dla osób z ławki.
    bench_last_end: dict[IdentityKey, date]

    @property
    def bench_keys(self) -> frozenset[IdentityKey]:
        return frozenset(self.ever_keys - self.active_keys)

    @property
    def active(self) -> int:
        return len(self.active_keys)

    @property
    def bench(self) -> int:
        return len(self.bench_keys)

    @property
    def total(self) -> int:
        return len(self.ever_keys)

    @property
    def utilization_pct(self) -> float | None:
        """``None`` gdy nie ma kogo liczyć.

        Zero znaczyłoby „nikt z naszych konsultantów nie pracuje” — czyli coś
        zupełnie innego niż „nie mamy jeszcze ani jednego konsultanta”.
        """
        return round(100.0 * self.active / self.total, 1) if self.total else None

    def avg_bench_days(self, *, today: date | None = None) -> float | None:
        """Średnia długość przerwy osób z ławki, po osobach z ZNANĄ datą końca.

        Osoba, której kontrakt nie ma daty końca, nie wnosi przerwy — ale nadal
        jest na ławce i liczy się do ``bench``. Ta asymetria jest zamierzona
        i dlatego obie liczby wychodzą z jednego obiektu: kafel „Śr. dni na
        bench” ma pod sobą licznik osób z TEJ SAMEJ ławki.
        """
        reference = today or business_today()
        gaps = [
            (reference - last_end).days
            for key, last_end in self.bench_last_end.items()
            if key in self.bench_keys and (reference - last_end).days > 0
        ]
        return round(sum(gaps) / len(gaps), 1) if gaps else None


async def consultant_population(
    db: AsyncSession, *, on: date | None = None
) -> ConsultantPopulation:
    """Jedno zapytanie: kto pracował u nas do dnia ``on`` i kto pracuje dziś.

    ``REVENUE_BEARING_STATUSES`` (``active``/``ending``/``ended``), bo ławka
    z definicji składa się z kontraktów ZAKOŃCZONYCH — zbiór „żywych” statusów
    zostawiłby mianownik równy licznikowi i utylizację na sztywne 100%.
    Kontrakt bez daty rozpoczęcia liczy się jak już obowiązujący — ta sama
    reguła co ``contractor_identity.is_current_contract`` (18.09.2026) i kafel
    „aktywne kontrakty” obok (``_started_by``). Do 24.09.2026 był tu pomijany,
    więc osoba z żywym kontraktem bez daty była w kaflu kontraktów, a w
    utylizacji nie było jej wcale.

    Na dziś (i później) aktywny jest tylko kontrakt w żywym statusie: ``ended``
    bez daty końca albo z datą w przyszłości to zakończona współpraca, a kafel
    „aktywne kontrakty” obok liczy po statusie — bez tego osób aktywnych
    wychodziło więcej niż aktywnych kontraktów (kolejka 23.09.2026). Dla dnia
    z przeszłości status mówi o dziś, nie o tamtym dniu, więc decyduje data.
    """
    on = on or business_today()
    status_decides = on >= business_today()
    rows = (
        await db.execute(
            select(
                Candidate.id,
                Candidate.name,
                Candidate.lastname,
                Candidate.email,
                Contract.end_date,
                Contract.status,
            )
            .join(Contract, Contract.candidate_id == Candidate.id)
            .where(
                Contract.status.in_(REVENUE_BEARING_STATUSES),
                or_(Contract.start_date.is_(None), Contract.start_date <= on),
            )
        )
    ).all()

    active_keys: set[IdentityKey] = set()
    ever_keys: set[IdentityKey] = set()
    last_end: dict[IdentityKey, date] = {}
    for row in rows:
        key = candidate_identity_key(row)
        ever_keys.add(key)
        if (row.end_date is None or row.end_date >= on) and (
            not status_decides or row.status in _LIVE_STATUSES
        ):
            active_keys.add(key)
        if row.end_date is not None:
            previous = last_end.get(key)
            if previous is None or row.end_date > previous:
                last_end[key] = row.end_date

    return ConsultantPopulation(
        on=on,
        active_keys=frozenset(active_keys),
        ever_keys=frozenset(ever_keys),
        bench_last_end={
            key: value for key, value in last_end.items() if key not in active_keys
        },
    )
