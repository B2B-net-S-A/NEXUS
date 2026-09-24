"""Dopasowania wierszy rejestru z Excela: kandydat, klient, rekruter.

Zasada wspólna: dokładnie jedno trafienie = powiązanie; więcej = BRAK
powiązania i pozycja „wieloznaczne” w raporcie. Zgadywanie przypięłoby umowę
cudzej osobie albo innemu klientowi — błąd, który wychodzi dopiero na
rozliczeniu.

Indeksy są budowane raz na import (jedno zapytanie na tabelę), bo plik ma
~1200 wierszy, a zapytanie per wiersz po ``polish_folded_ilike`` to pełny
przegląd tabeli kandydatów za każdym razem.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_directory import ClientAlias
from app.models.contract import Contract
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services.b2b_register_import.parser import name_tokens, norm
from app.services.client_portfolio_import import (
    loose_client_name,
    normalize_client_name,
)

MatchKind = Literal["matched", "unmatched", "ambiguous", "internal"]


@dataclass(frozen=True)
class Match:
    kind: MatchKind
    id: Optional[int] = None
    count: int = 0
    label: Optional[str] = None


# ── Kandydaci ────────────────────────────────────────────────────────────────


class CandidateIndex:
    def __init__(self, by_tokens: dict[frozenset[str], list[int]]):
        self._by_tokens = by_tokens

    @classmethod
    async def build(cls, db: AsyncSession) -> "CandidateIndex":
        by_tokens: dict[frozenset[str], list[int]] = defaultdict(list)
        result = await db.execute(
            select(Candidate.id, Candidate.name, Candidate.lastname)
        )
        for cid, first, last in result.all():
            tokens = name_tokens(f"{first or ''} {last or ''}")
            if len(tokens) >= 2:
                by_tokens[tokens].append(cid)
        return cls(dict(by_tokens))

    def candidates_for(self, tokens: frozenset[str]) -> list[int]:
        if len(tokens) < 2:
            return []
        return list(self._by_tokens.get(tokens, ()))


async def candidates_linked_to_client(
    db: AsyncSession, candidate_ids: set[int], client_id: int
) -> set[int]:
    """Kandydaci z kontraktem albo procesem rekrutacyjnym u tego klienta."""
    if not candidate_ids:
        return set()
    linked = set(
        (
            await db.execute(
                select(Contract.candidate_id).where(
                    Contract.candidate_id.in_(candidate_ids),
                    Contract.client_id == client_id,
                )
            )
        ).scalars()
    )
    linked.update(
        (
            await db.execute(
                select(CandidateStage.candidate_id)
                .join(Job, Job.id == CandidateStage.job_id)
                .where(
                    CandidateStage.candidate_id.in_(candidate_ids),
                    Job.client_id == client_id,
                )
            )
        ).scalars()
    )
    return {cid for cid in linked if cid is not None}


# ── Klienci ──────────────────────────────────────────────────────────────────

#: Wartości kolumny „Klient”, które znaczą „bez klienta” (umowy wewnętrzne).
INTERNAL_CLIENT_KEYS = frozenset(
    {"b2b net", "b2b net s a", "b2b", "b2b net sa", "brak", "hr", "b2bnet", "-", ""}
)

#: Warianty pisowni z rejestru działu → nazwy szukane w katalogu klientów
#: (w kolejności). Dopasowanie nadal wymaga DOKŁADNIE jednego klienta.
CLIENT_VARIANTS: dict[str, tuple[str, ...]] = {
    "bnp": ("bnp paribas bank polska", "bnp paribas"),
    "bnp paribas": ("bnp paribas bank polska", "bnp paribas"),
    "pko": ("pko bank polski", "pko bp"),
    "pko bp": ("pko bank polski", "pko bp"),
    "ezdrowie": ("centrum e zdrowia",),
    "e zdrowie": ("centrum e zdrowia",),
    "cez": ("centrum e zdrowia",),
    "velobank": ("velobank",),
    "bosch": ("bosch",),
    "ergo": ("ergo hestia", "ergo"),
    "bik": ("biuro informacji kredytowej", "bik"),
    "pfron": ("pfron",),
}


class ClientResolver:
    def __init__(
        self,
        exact: dict[str, set[int]],
        loose: dict[str, set[int]],
        labels: dict[int, str],
    ):
        self._exact = exact
        self._loose = loose
        self._labels = labels

    @classmethod
    async def build(cls, db: AsyncSession) -> "ClientResolver":
        rows = (
            await db.execute(
                select(
                    Client.id,
                    Client.name,
                    Client.display_name,
                    Client.legal_name,
                    Client.merged_into_client_id,
                    Client.deleted_at,
                )
            )
        ).all()
        merged_into = {cid: target for cid, _n, _d, _l, target, _del in rows}
        deleted = {cid for cid, _n, _d, _l, _t, gone in rows if gone is not None}

        def canonical(cid: int) -> Optional[int]:
            seen: set[int] = set()
            while merged_into.get(cid) is not None and cid not in seen:
                seen.add(cid)
                cid = merged_into[cid]  # type: ignore[assignment]
            return None if cid in deleted else cid

        exact: dict[str, set[int]] = defaultdict(set)
        loose: dict[str, set[int]] = defaultdict(set)
        labels: dict[int, str] = {}

        def add(cid: Optional[int], value: Optional[str]) -> None:
            if cid is None or not value:
                return
            if key := normalize_client_name(value):
                exact[key].add(cid)
            if key := loose_client_name(value):
                loose[key].add(cid)

        for cid, name, display, legal, _t, _del in rows:
            target = canonical(cid)
            if target is None:
                continue
            for value in (name, display, legal):
                add(target, value)
            if target == cid:
                labels[cid] = (display or "").strip() or name
        aliases = await db.execute(
            select(ClientAlias.client_id, ClientAlias.alias).where(
                ClientAlias.archived_at.is_(None)
            )
        )
        for cid, alias in aliases.all():
            add(canonical(cid), alias)
        return cls(dict(exact), dict(loose), labels)

    def _lookup(self, value: str) -> set[int]:
        hits = self._exact.get(normalize_client_name(value), set())
        if hits:
            return hits
        return self._loose.get(loose_client_name(value), set())

    def resolve(self, raw: Optional[str]) -> Match:
        key = norm(raw)
        if key in INTERNAL_CLIENT_KEYS:
            return Match("internal")
        # „Nordea/B2B.NET” — część wewnętrzna odpada, reszta musi dać jednego.
        parts = [p for p in (raw or "").split("/") if norm(p)]
        external = [p for p in parts if norm(p) not in INTERNAL_CLIENT_KEYS] or parts
        if len(external) != 1:
            return Match("unmatched")
        value = external[0]
        hits = self._lookup(value)
        if not hits:
            for alternative in CLIENT_VARIANTS.get(norm(value), ()):
                hits = self._lookup(alternative)
                if hits:
                    break
        if len(hits) == 1:
            cid = next(iter(hits))
            return Match("matched", cid, 1, self._labels.get(cid))
        if hits:
            return Match("ambiguous", count=len(hits))
        return Match("unmatched")


# ── Rekruterzy ───────────────────────────────────────────────────────────────

#: Zdrobnienia imion z kolumny „Rekruter” → imię w koncie.
DIMINUTIVES: dict[str, str] = {
    "kasia": "katarzyna",
    "gosia": "malgorzata",
    "ola": "aleksandra",
    "asia": "joanna",
    "basia": "barbara",
    "magda": "magdalena",
    "ania": "anna",
    "tomek": "tomasz",
    "kuba": "jakub",
    "ewelinka": "ewelina",
    "ela": "elzbieta",
    "iza": "izabela",
    "zuza": "zuzanna",
}


class RecruiterResolver:
    def __init__(self, users: list[tuple[int, list[str], bool, str]]):
        self._users = users  # (id, tokeny imienia i nazwiska, aktywny, etykieta)

    @classmethod
    async def build(cls, db: AsyncSession) -> "RecruiterResolver":
        rows = (await db.execute(select(User.id, User.name, User.is_active))).all()
        users = [
            (uid, norm(name).split(), bool(active), name)
            for uid, name, active in rows
            if norm(name)
        ]
        return cls(users)

    @staticmethod
    def _token_matches(wanted: str, have: str) -> bool:
        if len(wanted) == 1:
            return have.startswith(wanted)
        return have == wanted or have == DIMINUTIVES.get(wanted, wanted)

    def resolve(self, raw: Optional[str]) -> Match:
        wanted = norm(raw).split()
        if not wanted:
            return Match("unmatched")
        hits = [
            (uid, active, label)
            for uid, tokens, active, label in self._users
            if all(any(self._token_matches(w, t) for t in tokens) for w in wanted)
        ]
        if len(hits) > 1:
            active_hits = [hit for hit in hits if hit[1]]
            if len(active_hits) == 1:
                hits = active_hits
        if len(hits) == 1:
            return Match("matched", hits[0][0], 1, hits[0][2])
        if hits:
            return Match("ambiguous", count=len(hits))
        return Match("unmatched")
