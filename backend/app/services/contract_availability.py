"""Dostępność osoby, która pracuje u nas — z umowy, nie z notatek (15.10.2026).

Zgłoszenie: profil mówił „Pracuje u nas do 30.11.2026” i jednocześnie
„Dostępność od 1.09.2026” — data pochodziła ze screeningu sprzed zatrudnienia
(pomiar 15.10.2026: 308 z 483 pracujących miało minioną datę „Dostępny od”).

Reguła (D1, decyzja Artura 15.10.2026): dopóki osoba ma żywą umowę, termin =
późniejsza z dat: dzień po końcu pracy u nas (``EmploymentMarker.free_from``,
reguła :func:`employment_marker.contract_free_from`) i data z profilu.
Wcześniejsza data z profilu to dawny screening; późniejsza znaczy, że kandydat
sam podał dalszy termin. Odejście przed końcem zamówienia ustala Delivery.
Bez daty końca albo przed startem umowy terminu nie znamy.

Ten moduł niesie regułę tam, gdzie nie ma znacznika: ocena dopasowania,
filtr „Dostępny do daty”, kolejki Delivery Leada i Cpro, podpowiedzi umów
i prompty AI. Liczy tę samą datę końca pracy co znacznik (:func:`work_end_sql`)
— jedno zapytanie na stronę, bez Delivery Leadów.

Status „Czy szuka pracy” przy żywej umowie (S1–S5, decyzja Artura 15.10.2026):
dopóki osoba ma żywą umowę (także przed startem), status z profilu nie jest
pokazywany ani używany do wybierania ludzi — o tym, czy i od kiedy jest wolna,
mówi znacznik. Status w bazie zostaje i wraca po końcu umowy. Warunek jest ten
sam co ``hidesAvailabilityStatus`` na froncie (znacznik ze źródłem
``contract``): :func:`availability_status_hidden` (Python)
i :func:`without_live_contract_clause` (SQL). Automat notatek nie wpisuje
statusu z notatki sprzed startu ostatniej umowy (:class:`ContractHistory`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.contract import Contract, ContractStatus
from app.schemas.candidate import (
    EmploymentFreeFromBasis,
    EmploymentMarker,
    EmploymentMarkerClient,
)
from app.services.current_employment import LIVE_CONTRACT_STATUSES
from app.services.employment_marker import contract_free_from, work_end_sql

logger = logging.getLogger(__name__)

#: Atrybut kandydata, który czyta ocena dopasowania (``scoring_service``).
ATTRIBUTE = "_contract_free"


@dataclass(frozen=True)
class ContractFree:
    """Od kiedy osoba z żywą umową jest wolna — wynik reguły znacznika."""

    free_from: Optional[date]
    basis: EmploymentFreeFromBasis

    def available_from(self, profile_date: Optional[date]) -> Optional[date]:
        """Termin dostępności; ``None`` = nie wiadomo (bez końca, zaczyna)."""
        if self.basis != "work_end" or self.free_from is None:
            return None
        if profile_date is not None and profile_date > self.free_from:
            return profile_date
        return self.free_from

    def describe(self, profile_date: Optional[date]) -> str:
        """Jedno zdanie dla promptów AI i kolejek: skąd ten termin."""
        if self.basis == "starting":
            return "zaczyna u nas pracę, termin dostępności nieznany"
        if self.basis == "no_end_date":
            return "pracuje u nas bez daty końca zamówienia"
        available = self.available_from(profile_date)
        return (
            f"pracuje u nas, dostępny od {available.isoformat()}" if available else ""
        )


def from_marker(marker: Optional[EmploymentMarker]) -> Optional[ContractFree]:
    """Wynik reguły ze znacznika; ``None`` = osoba bez żywej umowy."""
    if marker is None or marker.source != "contract" or marker.free_from_basis is None:
        return None
    return ContractFree(free_from=marker.free_from, basis=marker.free_from_basis)


def _started(today: date) -> Any:
    return or_(Contract.start_date.is_(None), Contract.start_date <= today)


async def load_contract_free(
    db: AsyncSession, candidate_ids: Iterable[Any], *, today: Optional[date] = None
) -> dict[int, ContractFree]:
    """``{candidate_id: ContractFree}`` tylko dla osób z żywą umową.

    Jedno zapytanie: żywe umowy z datą końca pracy (lustro daty znacznika),
    a reguła :func:`contract_free_from` — ta sama co w znaczniku.
    """
    ids = sorted({int(cid) for cid in candidate_ids if cid is not None})
    if not ids:
        return {}
    today = today or business_today()
    started = _started(today)
    rows = (
        await db.execute(
            select(
                Contract.candidate_id,
                started.label("started"),
                case((started, work_end_sql(today=today)), else_=None).label(
                    "work_end"
                ),
            ).where(
                Contract.candidate_id.in_(ids),
                Contract.status.in_(LIVE_CONTRACT_STATUSES),
            )
        )
    ).all()
    clients: dict[int, list[EmploymentMarkerClient]] = {}
    for row in rows:
        clients.setdefault(int(row.candidate_id), []).append(
            EmploymentMarkerClient(
                phase="working" if row.started else "starting",
                order_end_date=row.work_end if row.started else None,
            )
        )
    out: dict[int, ContractFree] = {}
    for candidate_id, items in clients.items():
        free_from, basis = contract_free_from(items)
        if basis is not None:
            out[candidate_id] = ContractFree(free_from=free_from, basis=basis)
    return out


async def attach_contract_free(
    db: Any, candidates: Iterable[Any], *, today: Optional[date] = None
) -> None:
    """Dołącz :data:`ATTRIBUTE` do kandydatów przed oceną dopasowania.

    Wzorem ``prior_screening.attach_prior_screening``: nigdy nie rzuca —
    błąd zapytania zostawia ocenę na dacie z profilu. Osoba bez żywej umowy
    dostaje ``None`` (ocena wie, że sprawdzono).
    """
    candidates = [c for c in candidates if getattr(c, "id", None) is not None]
    if db is None or not candidates:
        return
    try:
        async with db.begin_nested():
            found = await load_contract_free(
                db, [c.id for c in candidates], today=today
            )
    except Exception:  # noqa: BLE001 — warstwa jest dodatkiem do oceny
        logger.warning("contract availability: lookup failed", exc_info=True)
        return
    for candidate in candidates:
        try:
            setattr(candidate, ATTRIBUTE, found.get(int(candidate.id)))
        except (AttributeError, TypeError):  # obiekt bez __dict__ / zamrożony
            continue


def contract_free_by_clause(
    candidate_id: Any, by_date: date, *, today: Optional[date] = None
) -> Any:
    """Lustro SQL: osoba nie ma żywej umowy, która trzyma ją dłużej niż do
    ``by_date`` — umowa przed startem, bez końca pracy albo z końcem pracy
    ``>= by_date`` (wolna dopiero od dnia po końcu). Datę z profilu sprawdza
    wołający, jak dotąd.
    """
    today = today or business_today()
    holds = (
        select(1)
        .select_from(Contract)
        .where(
            Contract.candidate_id == candidate_id,
            Contract.status.in_(LIVE_CONTRACT_STATUSES),
            or_(
                and_(Contract.start_date.is_not(None), Contract.start_date > today),
                func.coalesce(work_end_sql(today=today), date.max) >= by_date,
            ),
        )
        .exists()
    )
    return ~holds


# ── Status „Czy szuka pracy” przy żywej umowie (15.10.2026, S1–S5) ──────────


def availability_status_hidden(contract: Optional[ContractFree]) -> bool:
    """Status z profilu nie liczy się przy żywej umowie — lustro frontu
    ``hidesAvailabilityStatus``. ``contract`` z :func:`load_contract_free`
    albo :data:`ATTRIBUTE`: wpis istnieje dokładnie dla osób z żywą umową,
    także przed jej startem."""
    return contract is not None


def without_live_contract_clause(candidate_id: Any) -> Any:
    """Lustro SQL :func:`availability_status_hidden`: osoba nie ma żywej
    umowy (``active`` / ``ending``, z dowolną datą startu), więc jej status
    z profilu się liczy."""
    live = (
        select(1)
        .select_from(Contract)
        .where(
            Contract.candidate_id == candidate_id,
            Contract.status.in_(LIVE_CONTRACT_STATUSES),
        )
        .exists()
    )
    return ~live


#: Umowy, których start dzieli notatki na „sprzed umowy” i późniejsze: żywe
#: (także przed startem) i zakończone. Szkic, umowa do podpisu i unieważniona
#: nie są współpracą.
_SIGNED_CONTRACT_STATUSES: tuple[ContractStatus, ...] = (
    *LIVE_CONTRACT_STATUSES,
    ContractStatus.ended,
)


@dataclass(frozen=True)
class ContractHistory:
    """Umowy osoby dla automatu notatek (S2): czy któraś trwa i kiedy
    zaczęła się ostatnia."""

    live: bool
    latest_start: Optional[date]

    def allows_status_from_note(self, note_day: Optional[date]) -> bool:
        """Czy notatka z dnia ``note_day`` może wpisać „Czy szuka pracy”.

        Przy żywej umowie nie: status i tak jest ukryty, a po końcu umowy
        wróciłby jako fakt sprzed współpracy. Po umowie tylko notatka nowsza
        niż start ostatniej umowy; bez dnia notatki tego nie wiadomo, więc też
        nie. Umowa bez daty startu nie ogranicza.
        """
        if self.live:
            return False
        if self.latest_start is None:
            return True
        return note_day is not None and note_day > self.latest_start


#: Osoba bez umów — automat notatek działa jak przed 15.10.2026.
NO_CONTRACTS = ContractHistory(live=False, latest_start=None)


async def load_contract_history(db: AsyncSession, candidate_id: int) -> ContractHistory:
    """Jedno zapytanie: żywa umowa i najpóźniejszy start umowy osoby."""
    row = (
        await db.execute(
            select(
                func.bool_or(Contract.status.in_(LIVE_CONTRACT_STATUSES)),
                func.max(Contract.start_date),
            ).where(
                Contract.candidate_id == candidate_id,
                Contract.status.in_(_SIGNED_CONTRACT_STATUSES),
            )
        )
    ).one()
    return ContractHistory(live=bool(row[0]), latest_start=row[1])


__all__ = [
    "ATTRIBUTE",
    "NO_CONTRACTS",
    "ContractFree",
    "ContractHistory",
    "attach_contract_free",
    "availability_status_hidden",
    "contract_free_by_clause",
    "from_marker",
    "load_contract_free",
    "load_contract_history",
    "without_live_contract_clause",
]
