"""Dopasowanie osób z wierszy zamówienia do ROSTERA klienta (nie całej bazy).

Ticket: przy wielu konsultantach na jednym zamówieniu system nie bierze
pierwszej pasującej osoby z całej bazy — dopasowuje wyłącznie wśród
konsultantów pracujących u danego klienta. Roster jest SZERSZY niż picker
(``active`` + ``ending``): przedłużenie po przerwie dotyczy osoby, której
kontrakt jest już ``ended`` — to zamówienie go wskrzesza — więc bierzemy też
``draft`` i zakończone w ostatnich N miesiącach. Roster służy do NAZWANIA
osoby; czy automat może na niej zapisać, rozstrzyga bramka (status kontraktu).

Dwa rodzaje trafienia, celowo rozróżniane:
* **exact** — równoważne po normalizacji (diakrytyki, kolejność imię/nazwisko,
  myślniki); jedyne, które bramka automatu akceptuje;
* **rescued** — uratowane przez ``_safe_token_distance`` (transpozycja
  sąsiednich znaków); literówka jest sygnałem, że dokument i baza się nie
  zgadzają, więc idzie do kolejki (korpus: „Podwin" w dokumencie CA vs
  „Padwin" na karcie).

Osoba to nie kontrakt: writer potrzebuje KONTRAKTU. Przy dwóch żywych
kontraktach tej samej osoby u klienta ``_contract_for_candidate`` wybiera po
cichu najpóźniejszy — my nie: to niejednoznaczność do kolejki.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus
from app.services.order_pdf_parser import (
    ConsultantOrderRow,
    _name_match_score,
    _names_exactly_equivalent,
)

MATCH_EXACT = "exact"
MATCH_RESCUED = "rescued"
MATCH_AMBIGUOUS = "ambiguous"
MATCH_NONE = "none"

LIVE_STATUSES = (ContractStatus.active, ContractStatus.ending)
ROSTER_STATUSES = LIVE_STATUSES + (ContractStatus.draft,)


@dataclass(frozen=True)
class RosterContract:
    contract_id: int
    status: str
    start_date: Optional[date]
    end_date: Optional[date]


@dataclass(frozen=True)
class RosterPerson:
    candidate_id: int
    name: str
    lastname: str
    contracts: tuple[RosterContract, ...]

    @property
    def full_name(self) -> str:
        return f"{self.name} {self.lastname}".strip()


@dataclass(frozen=True)
class ResolvedConsultant:
    row_index: int
    row_name: str
    match_kind: str
    candidate_id: Optional[int] = None
    contract_id: Optional[int] = None
    contract_status: Optional[str] = None
    #: ID kandydatów, które pasowały (>1 = niejednoznaczne).
    candidate_ids: tuple[int, ...] = ()
    #: Kontrakty kandydata u klienta (>1 żywy = niejednoznaczne dla automatu).
    live_contract_ids: tuple[int, ...] = ()
    reason: str = ""

    @property
    def is_unique_person(self) -> bool:
        return (
            self.match_kind in (MATCH_EXACT, MATCH_RESCUED)
            and self.candidate_id is not None
        )

    @property
    def has_single_live_contract(self) -> bool:
        return len(self.live_contract_ids) == 1


async def load_roster(
    db: AsyncSession,
    client_id: int,
    *,
    ended_within_months: int = 6,
    today: Optional[date] = None,
) -> list[RosterPerson]:
    """Osoby z kontraktem u klienta: żywe + szkice + zakończone w ostatnich N mies."""
    today = today or date.today()
    cutoff = today - timedelta(days=30 * ended_within_months)
    stmt = (
        select(
            Candidate.id,
            Candidate.name,
            Candidate.lastname,
            Contract.id,
            Contract.status,
            Contract.start_date,
            Contract.end_date,
        )
        .join(Contract, Contract.candidate_id == Candidate.id)
        .where(
            Contract.client_id == client_id,
            or_(
                Contract.status.in_(ROSTER_STATUSES),
                (Contract.status == ContractStatus.ended)
                & (Contract.end_date >= cutoff),
            ),
        )
        .order_by(Candidate.id, Contract.start_date.desc().nullslast())
    )
    people: dict[int, dict] = {}
    for cid, name, lastname, contract_id, status, start, end in (
        await db.execute(stmt)
    ).all():
        person = people.setdefault(
            cid, {"name": name or "", "lastname": lastname or "", "contracts": []}
        )
        person["contracts"].append(
            RosterContract(
                contract_id=contract_id,
                status=status.value if hasattr(status, "value") else str(status),
                start_date=start,
                end_date=end,
            )
        )
    return [
        RosterPerson(
            candidate_id=cid,
            name=p["name"],
            lastname=p["lastname"],
            contracts=tuple(p["contracts"]),
        )
        for cid, p in people.items()
    ]


def _pick_contract(
    person: RosterPerson,
) -> tuple[Optional[RosterContract], tuple[int, ...]]:
    """Kontrakt do zapisu: żywy (jeśli dokładnie jeden), potem szkic, potem zakończony."""
    live = [c for c in person.contracts if c.status in ("active", "ending")]
    live_ids = tuple(c.contract_id for c in live)
    if len(live) == 1:
        return live[0], live_ids
    if len(live) > 1:
        return None, live_ids
    drafts = [c for c in person.contracts if c.status == "draft"]
    if drafts:
        return drafts[0], live_ids
    ended = sorted(
        (c for c in person.contracts if c.status == "ended"),
        key=lambda c: c.end_date or date.min,
        reverse=True,
    )
    return (ended[0] if ended else None), live_ids


def resolve_rows(
    rows: list[ConsultantOrderRow], roster: list[RosterPerson]
) -> list[ResolvedConsultant]:
    out: list[ResolvedConsultant] = []
    for idx, row in enumerate(rows):
        exact = [
            p
            for p in roster
            if _names_exactly_equivalent(row.consultant_name, p.full_name)
        ]
        rescued: list[RosterPerson] = []
        if not exact:
            rescued = [
                p
                for p in roster
                if _name_match_score(
                    row.consultant_name, p.full_name, consultant_given_names=p.name
                )
                is not None
            ]
        pool, kind = (exact, MATCH_EXACT) if exact else (rescued, MATCH_RESCUED)
        if not pool:
            out.append(
                ResolvedConsultant(
                    row_index=idx,
                    row_name=row.consultant_name,
                    match_kind=MATCH_NONE,
                    reason="Brak takiej osoby wśród konsultantów tego klienta",
                )
            )
            continue
        if len(pool) > 1:
            out.append(
                ResolvedConsultant(
                    row_index=idx,
                    row_name=row.consultant_name,
                    match_kind=MATCH_AMBIGUOUS,
                    candidate_ids=tuple(p.candidate_id for p in pool),
                    reason=f"Pasuje {len(pool)} osób u tego klienta — wybierz ręcznie",
                )
            )
            continue
        person = pool[0]
        contract, live_ids = _pick_contract(person)
        out.append(
            ResolvedConsultant(
                row_index=idx,
                row_name=row.consultant_name,
                match_kind=kind,
                candidate_id=person.candidate_id,
                contract_id=contract.contract_id if contract else None,
                contract_status=contract.status if contract else None,
                candidate_ids=(person.candidate_id,),
                live_contract_ids=live_ids,
                reason=(
                    "Dopasowanie dokładne"
                    if kind == MATCH_EXACT
                    else "Dopasowanie z literówką — potwierdź osobę"
                )
                if contract
                else (
                    "Osoba bez kontraktu do zapisu u tego klienta"
                    if not live_ids
                    else f"Osoba ma {len(live_ids)} żywe kontrakty u klienta — wybierz ręcznie"
                ),
            )
        )
    return out
