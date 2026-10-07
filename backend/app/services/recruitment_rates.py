"""Stawki z rekrutacji dla zamówienia i umowy (D7, 08.10.2026).

Dwie liczby pary (kandydat, rekrutacja), obie z wierszy ``candidate_stages``:

* **stawka do klienta** — najnowszy wiersz etapu z wpisaną stawką do klienta
  (tę samą regułę czyta ``stage_client_rate.latest_client_rates``). Wpisuje ją
  Delivery Lead przy wysyłce CV; jest punktem odniesienia dla PRZYCHODU
  w zamówieniu klienta,
* **stawka kandydata** — najnowszy wiersz etapu ze stawką kandydata (okno
  „Zweryfikowany”, zmiana stawki w procesie 0418). Punkt odniesienia dla
  KOSZTU w zamówieniu i w umowie B2B.

Nic tu nie zapisuje i nic nie blokuje. Kto widzi stawkę do klienta, decyduje
wołający (``candidate_access.user_can_view_client_rate``) — ``as_dict``
przyjmuje tę decyzję jawnie.

Trzy wejścia:

* ``for_pairs`` — wprost po parach,
* ``for_contracts`` — para z ``contract.job_id``; kontrakt bez rekrutacji albo
  z rekrutacją bez stawek dostaje najnowszą parę tej osoby u klienta,
* ``for_client`` — najnowsza para osoby w rekrutacjach klienta i klientów
  z nim scalonych (rekrutacja duplikatu zostaje na ukrytym wierszu).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services.recruitment_rate_check import RateRef

Pair = tuple[int, int]


@dataclass(frozen=True)
class RecruitmentRate:
    candidate_id: int
    job_id: int
    job_title: Optional[str] = None
    client_rate_value: Optional[Decimal] = None
    client_rate_unit: Optional[str] = None
    client_rate_currency: Optional[str] = None
    client_rate_at: Optional[datetime] = None
    client_rate_by_name: Optional[str] = None
    candidate_rate_value: Optional[Decimal] = None
    candidate_rate_unit: Optional[str] = None
    candidate_rate_currency: Optional[str] = None
    candidate_rate_at: Optional[datetime] = None

    @property
    def has_any(self) -> bool:
        return (
            self.client_rate_value is not None or self.candidate_rate_value is not None
        )

    def client_ref(self) -> Optional[RateRef]:
        if self.client_rate_value is None:
            return None
        return RateRef(
            value=self.client_rate_value,
            unit=self.client_rate_unit,
            currency=self.client_rate_currency or "PLN",
            label=self.job_title,
        )

    def candidate_ref(self) -> Optional[RateRef]:
        if self.candidate_rate_value is None:
            return None
        return RateRef(
            value=self.candidate_rate_value,
            unit=self.candidate_rate_unit,
            currency=self.candidate_rate_currency or "PLN",
            label=self.job_title,
        )

    def as_dict(self, *, show_client_rate: bool) -> dict[str, Any]:
        """Kształt odpowiedzi API; bez ``show_client_rate`` stawka do klienta znika."""
        data: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "job_id": self.job_id,
            "job_title": self.job_title,
            "candidate_rate_value": self.candidate_rate_value,
            "candidate_rate_unit": self.candidate_rate_unit,
            "candidate_rate_currency": self.candidate_rate_currency,
            "candidate_rate_at": self.candidate_rate_at,
            "client_rate_value": None,
            "client_rate_unit": None,
            "client_rate_currency": None,
            "client_rate_at": None,
            "client_rate_by_name": None,
            "client_rate_redacted": not show_client_rate,
        }
        if show_client_rate:
            data.update(
                client_rate_value=self.client_rate_value,
                client_rate_unit=self.client_rate_unit,
                client_rate_currency=self.client_rate_currency,
                client_rate_at=self.client_rate_at,
                client_rate_by_name=self.client_rate_by_name,
            )
        return data


def _unit(value: Any) -> Optional[str]:
    return getattr(value, "value", value)


async def for_pairs(
    db: AsyncSession, pairs: Iterable[Pair]
) -> dict[Pair, RecruitmentRate]:
    """``{(kandydat, rekrutacja): RecruitmentRate}`` — pary bez stawek pomija."""
    wanted = sorted({(int(c), int(j)) for c, j in pairs if c and j})
    if not wanted:
        return {}
    rows = (
        await db.execute(
            select(
                CandidateStage.candidate_id,
                CandidateStage.job_id,
                CandidateStage.moved_at,
                CandidateStage.client_rate_value,
                CandidateStage.client_rate_unit,
                CandidateStage.client_rate_currency,
                CandidateStage.expected_rate_value,
                CandidateStage.expected_rate_unit,
                CandidateStage.expected_rate_currency,
                User.name,
            )
            .outerjoin(User, User.id == CandidateStage.moved_by)
            .where(
                tuple_(CandidateStage.candidate_id, CandidateStage.job_id).in_(wanted),
                or_(
                    CandidateStage.client_rate_value.is_not(None),
                    CandidateStage.expected_rate_value.is_not(None),
                ),
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        )
    ).all()
    if not rows:
        return {}
    job_ids = sorted({row[1] for row in rows})
    titles = {
        job_id: (working or title)
        for job_id, title, working in (
            await db.execute(
                select(Job.id, Job.title, Job.working_title).where(Job.id.in_(job_ids))
            )
        ).all()
    }
    client: dict[Pair, tuple] = {}
    candidate: dict[Pair, tuple] = {}
    for (
        cand_id,
        job_id,
        moved_at,
        c_value,
        c_unit,
        c_currency,
        e_value,
        e_unit,
        e_currency,
        moved_by_name,
    ) in rows:
        key = (cand_id, job_id)
        # Wiersze idą od najnowszego — pierwsza niepusta wartość wygrywa.
        if c_value is not None and key not in client:
            client[key] = (c_value, _unit(c_unit), c_currency, moved_at, moved_by_name)
        if e_value is not None and key not in candidate:
            candidate[key] = (e_value, _unit(e_unit), e_currency, moved_at)
    out: dict[Pair, RecruitmentRate] = {}
    for key in set(client) | set(candidate):
        c = client.get(key)
        e = candidate.get(key)
        out[key] = RecruitmentRate(
            candidate_id=key[0],
            job_id=key[1],
            job_title=titles.get(key[1]),
            client_rate_value=Decimal(str(c[0])) if c else None,
            client_rate_unit=c[1] if c else None,
            client_rate_currency=(c[2] or "PLN") if c else None,
            client_rate_at=c[3] if c else None,
            client_rate_by_name=c[4] if c else None,
            candidate_rate_value=Decimal(str(e[0])) if e else None,
            candidate_rate_unit=e[1] if e else None,
            candidate_rate_currency=(e[2] or "PLN") if e else None,
            candidate_rate_at=e[3] if e else None,
        )
    return out


async def client_family_ids(db: AsyncSession, client_id: int) -> set[int]:
    """Klient + klienci z nim scaleni + klient, w którego go scalono.

    Od rundy 9 duplikaty scalone wcześniej w źródło wskazują wprost na cel,
    więc jeden krok w każdą stronę wystarcza.
    """
    family = {int(client_id)}
    merged_into = await db.scalar(
        select(Client.merged_into_client_id).where(Client.id == client_id)
    )
    root = int(merged_into) if merged_into else int(client_id)
    family.add(root)
    family.update(
        int(cid)
        for cid in (
            await db.execute(
                select(Client.id).where(Client.merged_into_client_id == root)
            )
        ).scalars()
    )
    return family


def _moment(value: Optional[datetime]) -> float:
    return value.timestamp() if value is not None else float("-inf")


def _pick_newest(rates: Iterable[RecruitmentRate]) -> Optional[RecruitmentRate]:
    """Para z najnowszą stawką do klienta, a bez niej — z najnowszą stawką kandydata."""
    items = list(rates)
    if not items:
        return None
    with_client = [r for r in items if r.client_rate_value is not None]
    if with_client:
        return max(with_client, key=lambda r: (_moment(r.client_rate_at), r.job_id))
    return max(items, key=lambda r: (_moment(r.candidate_rate_at), r.job_id))


async def for_client(
    db: AsyncSession, client_id: int, candidate_ids: Iterable[int]
) -> dict[int, RecruitmentRate]:
    """``{kandydat: najnowsza para ze stawkami w rekrutacjach rodziny klienta}``."""
    ids = sorted({int(c) for c in candidate_ids if c})
    if not ids:
        return {}
    family = await client_family_ids(db, client_id)
    pairs = (
        await db.execute(
            select(CandidateStage.candidate_id, CandidateStage.job_id)
            .join(Job, Job.id == CandidateStage.job_id)
            .where(
                CandidateStage.candidate_id.in_(ids),
                Job.client_id.in_(sorted(family)),
                or_(
                    CandidateStage.client_rate_value.is_not(None),
                    CandidateStage.expected_rate_value.is_not(None),
                ),
            )
            .distinct()
        )
    ).all()
    found = await for_pairs(db, [(c, j) for c, j in pairs])
    by_candidate: dict[int, list[RecruitmentRate]] = {}
    for rate in found.values():
        by_candidate.setdefault(rate.candidate_id, []).append(rate)
    out: dict[int, RecruitmentRate] = {}
    for cand_id, rates in by_candidate.items():
        best = _pick_newest(rates)
        if best is not None:
            out[cand_id] = best
    return out


@dataclass(frozen=True)
class ContractKey:
    contract_id: int
    candidate_id: Optional[int]
    job_id: Optional[int]
    client_id: int


async def for_contracts(
    db: AsyncSession, contracts: Iterable[Any]
) -> dict[int, RecruitmentRate]:
    """``{contract_id: RecruitmentRate}`` dla kontraktów (obiektów albo ``ContractKey``).

    Najpierw para z ``contract.job_id`` (rekrutacja, z której powstał
    kontrakt). Bez niej — najnowsza para tej osoby u klienta kontraktu.
    """
    keys = [
        ContractKey(
            contract_id=int(c.contract_id if isinstance(c, ContractKey) else c.id),
            candidate_id=c.candidate_id,
            job_id=c.job_id,
            client_id=int(c.client_id),
        )
        for c in contracts
    ]
    keys = [k for k in keys if k.candidate_id]
    if not keys:
        return {}
    direct = await for_pairs(
        db, [(k.candidate_id, k.job_id) for k in keys if k.job_id is not None]
    )
    out: dict[int, RecruitmentRate] = {}
    missing_by_client: dict[int, list[ContractKey]] = {}
    for key in keys:
        hit = (
            direct.get((key.candidate_id, key.job_id))
            if key.job_id is not None
            else None
        )
        if hit is not None and hit.has_any:
            out[key.contract_id] = hit
        else:
            missing_by_client.setdefault(key.client_id, []).append(key)
    for client_id, missing in missing_by_client.items():
        found = await for_client(db, client_id, [k.candidate_id for k in missing])
        for key in missing:
            hit = found.get(key.candidate_id)
            if hit is not None:
                out[key.contract_id] = hit
    return out
