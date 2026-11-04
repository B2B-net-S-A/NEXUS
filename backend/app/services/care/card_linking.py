"""Karta technologiczna z Compassa ↔ kontrakt NEXUSA po kliencie, osobie i dacie.

Compass nie wie, który kandydat NEXUSA to jego kontraktor (kolejka
„Tożsamość NEXUS” nie ma ani jednej kotwicy), więc decyzja Artura z 18.10.2026
(„Import + automatyczne parowanie”) łączy kartę z kontraktem tak:

* klient karty = klient kontraktu (po scaleniu klientów — klient docelowy),
* imię i nazwisko konsultanta z Compassa = imię i nazwisko kandydata
  kontraktu — bez wielkości liter, polskich znaków, kolejności słów
  i dopisków z Traffita („[ACTIVE]”, „(czarna lista)”, ``candidate_name_rules``),
* dzień rozmowy w okresie umowy (brak daty startu albo końca = otwarty).

Para jest pewna, gdy w tym okresie pasuje DOKŁADNIE jeden kontrakt — wtedy
import łączy ją sam. Kilka kontraktów w okresie albo kontrakty tej osoby
u klienta poza okresem to propozycje do potwierdzenia przez Delivery Leada
(lista „Karty do połączenia” w zakładce „Technologie” klienta). Brak
kontraktu z tym nazwiskiem = brak propozycji; DL wybiera kontrakt z listy
klienta albo zostawia kartę bez kontraktu (mapa i tak ją liczy).
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.services.candidate_name_rules import without_name_markers

#: Umowy, z którymi karty nie łączymy (jak rozmowy importu).
SKIPPED_STATUSES = (ContractStatus.void, ContractStatus.draft)
#: Ile propozycji pokazać przy jednej karcie.
MAX_SUGGESTIONS = 5

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def person_key(value: Optional[str]) -> str:
    """Klucz osoby: słowa imienia i nazwiska bez znaków, dopisków i kolejności."""

    cleaned = (without_name_markers(value) or "").replace("Ł", "L").replace("ł", "l")
    ascii_value = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", cleaned)
        if not unicodedata.combining(ch)
    )
    words = _NON_ALNUM.sub(" ", ascii_value.casefold()).split()
    return " ".join(sorted(words)) if len(words) >= 2 else ""


@dataclass(frozen=True)
class ContractRow:
    contract_id: int
    candidate_id: int
    client_id: int
    start: Optional[date]
    end: Optional[date]

    def covers(self, day: date) -> bool:
        return (self.start is None or self.start <= day) and (
            self.end is None or self.end >= day
        )

    def distance(self, day: date) -> int:
        """Dni od dnia rozmowy do okresu umowy (0 = w okresie)."""

        if self.start is not None and day < self.start:
            return (self.start - day).days
        if self.end is not None and day > self.end:
            return (day - self.end).days
        return 0


@dataclass(frozen=True)
class Match:
    #: Kontrakt połączony automatycznie (dokładnie jeden w okresie).
    contract_id: Optional[int]
    #: Kontrakty do potwierdzenia, najbliższe dniu rozmowy najpierw.
    suggestions: tuple[int, ...] = ()

    @property
    def contract_ids(self) -> tuple[int, ...]:
        """Wszystkie kontrakty do pokazania przy karcie (pewny najpierw)."""

        if self.contract_id is None:
            return self.suggestions
        return (self.contract_id, *self.suggestions)

    @property
    def state(self) -> str:
        if self.contract_id is not None:
            return "auto"
        return "suggested" if self.suggestions else "none"


@dataclass
class ContractIndex:
    """Kontrakty klientów pogrupowane po (klient, klucz osoby)."""

    by_person: dict[tuple[int, str], list[ContractRow]] = field(default_factory=dict)

    @classmethod
    def build(
        cls, rows: Iterable[tuple[ContractRow, Optional[str]]]
    ) -> "ContractIndex":
        grouped: dict[tuple[int, str], list[ContractRow]] = defaultdict(list)
        for row, name in rows:
            key = person_key(name)
            if key:
                grouped[(row.client_id, key)].append(row)
        return cls(by_person=dict(grouped))

    def match(self, client_id: int, person_name: Optional[str], day: date) -> Match:
        key = person_key(person_name)
        rows = self.by_person.get((client_id, key), []) if key else []
        in_period = [row for row in rows if row.covers(day)]
        # Imiennicy (różni kandydaci pod jednym kluczem) zawsze czekają na
        # potwierdzenie: daty umów w NEXUSIE bywają późniejsze niż praca.
        one_person = len({row.candidate_id for row in rows}) == 1
        if len(in_period) == 1 and one_person:
            return Match(contract_id=in_period[0].contract_id)
        ranked = sorted(rows, key=lambda row: (row.distance(day), -row.contract_id))
        return Match(
            contract_id=None,
            suggestions=tuple(row.contract_id for row in ranked[:MAX_SUGGESTIONS]),
        )


async def final_client_ids(db: AsyncSession) -> dict[int, int]:
    """Klient → klient docelowy po scaleniach (łańcuch, bez pętli)."""

    merged = dict(
        (await db.execute(select(Client.id, Client.merged_into_client_id))).all()
    )
    finals: dict[int, int] = {}
    for client_id in merged:
        current, seen = client_id, set()
        while merged.get(current) and current not in seen:
            seen.add(current)
            current = merged[current]
        finals[client_id] = current
    return finals


async def load_index(
    db: AsyncSession, client_ids: Optional[Iterable[int]] = None
) -> ContractIndex:
    """Kontrakty z kandydatem (bez anulowanych i szkiców), klient po scaleniu.

    ``client_ids`` = klienci docelowi; ``None`` = wszyscy.
    """

    finals = await final_client_ids(db)
    query = (
        select(
            Contract.id,
            Contract.candidate_id,
            Contract.client_id,
            Contract.start_date,
            Contract.end_date,
            Candidate.name,
            Candidate.lastname,
        )
        .join(Candidate, Candidate.id == Contract.candidate_id)
        .where(Contract.status.notin_(SKIPPED_STATUSES))
    )
    wanted = None if client_ids is None else set(client_ids)
    if wanted is not None:
        sources = [cid for cid, final in finals.items() if final in wanted]
        query = query.where(Contract.client_id.in_(sorted(sources) or [-1]))
    rows = []
    for contract_id, candidate_id, client_id, start, end, first, last in (
        await db.execute(query)
    ).all():
        rows.append(
            (
                ContractRow(
                    contract_id=contract_id,
                    candidate_id=candidate_id,
                    client_id=finals.get(client_id, client_id),
                    start=start,
                    end=end,
                ),
                f"{first or ''} {last or ''}",
            )
        )
    return ContractIndex.build(rows)
