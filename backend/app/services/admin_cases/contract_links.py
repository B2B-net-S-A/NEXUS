"""Sprawa ↔ kontrakt konsultanta: kogo dotyczy sprawa (decyzja 7, 22.10.2026).

Dwie drogi i jedna zasada — automat łączy tylko to, co pewne:

* **mail od konsultanta** — nadawca = e-mail konsultanta z kontraktu (ta sama
  reguła co karta kontraktu i komunikaty: ``contract_candidate_contact`` —
  e-mail z umowy, a bez niego z profilu kandydata). DOKŁADNIE jeden aktywny
  albo kończący się kontrakt z tym adresem = czytnik wpisuje ``contract_id``
  nowej sprawie (``link_new_mail_case``). Kilka = tylko propozycje,
* **mail z firmy klienta** — nadawca = kontakt klienta, a w temacie albo
  treści stoi imię i nazwisko naszego konsultanta z aktywnym kontraktem
  u tego klienta → propozycja „Kogo dotyczy?”, nigdy wpis automatu. Imię
  i nazwisko porównujemy jak karty z Compassa (``care/card_linking``): bez
  wielkości liter, polskich znaków i kolejności słów; samo imię nie wskazuje
  nikogo, odmienione nazwisko („Kowalskiego”) też nie.

Propozycje liczą się przy ODCZYCIE sprawy bez kontraktu
(``link_suggestions``), więc kontrakt dodany po mailu też się pojawi, a sprawa
z importu Compassa (opis „Konsultant: … · klient: …”) dostaje je tak samo.
Nazwisko konsultanta spoza firmy nadawcy też jest propozycją, ale niżej.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_case import AdminCase, AdminCaseMessage
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus
from app.services.care.card_linking import person_key
from app.services.contract_candidate_contact import resolve_contact
from app.services.hr import audit

#: Kontrakty, przy których mail konsultanta wiąże się ze sprawą.
LIVE_STATUSES: tuple[ContractStatus, ...] = (
    ContractStatus.active,
    ContractStatus.ending,
)
MAX_SUGGESTIONS = 5
#: Imię i nazwisko ma 2–4 słowa (jak ``person_key`` przy kartach).
_NAME_WORDS = range(2, 5)
#: Tyle tekstu sprawy przeszukujemy (tytuł, opis, tematy i treści maili).
TEXT_LIMIT = 40_000
MESSAGES_LIMIT = 20

REASON_SENDER = "Nadawca maila to e-mail konsultanta z kontraktu"
REASON_CLIENT_MAIL = "Mail z firmy klienta, w treści: {name}"
REASON_TEXT = "W treści sprawy: {name}"


# ── Reguły bez bazy ──────────────────────────────────────────────────────────


def _words(text: str) -> list[str]:
    """Słowa tekstu jak w ``person_key``: bez polskich znaków i wielkości liter."""

    folded = "".join(
        ch
        for ch in unicodedata.normalize(
            "NFKD", (text or "").replace("Ł", "L").replace("ł", "l")
        )
        if not unicodedata.combining(ch)
    ).casefold()
    return "".join(
        ch if ch.isascii() and ch.isalnum() else " " for ch in folded
    ).split()


def name_windows(text: str) -> frozenset[str]:
    """Klucze ``person_key`` wszystkich ciągów 2–4 kolejnych słów tekstu."""

    words = _words(text[:TEXT_LIMIT])
    keys: set[str] = set()
    for size in _NAME_WORDS:
        for start in range(len(words) - size + 1):
            keys.add(" ".join(sorted(words[start : start + size])))
    return frozenset(keys)


def names_in_text(text: str, people: Mapping[int, Optional[str]]) -> list[int]:
    """Kontrakty (``id → imię i nazwisko``), których osoba stoi w tekście.

    Słowa osoby muszą stać obok siebie (w dowolnej kolejności) — „Anna”
    w pierwszym zdaniu i „Nowak” w trzecim to nie „Anna Nowak”.
    """

    windows = name_windows(text)
    hits = []
    for contract_id, name in people.items():
        key = person_key(name)
        if key and key in windows:
            hits.append(contract_id)
    return sorted(hits)


def sender_contract(contract_ids: Iterable[int]) -> Optional[int]:
    """Kontrakt do wpisania automatem: dokładnie jeden, inaczej nic."""

    unique = set(contract_ids)
    return next(iter(unique)) if len(unique) == 1 else None


@dataclass(frozen=True)
class LiveContract:
    contract_id: int
    client_id: int
    candidate_name: Optional[str]
    client_name: Optional[str]


def rank_suggestions(
    *,
    by_sender: Sequence[int],
    client_named: Sequence[int],
    text_named: Sequence[int],
    contracts: Mapping[int, LiveContract],
    limit: int = MAX_SUGGESTIONS,
) -> list[dict[str, Any]]:
    """Propozycje w kolejności siły dowodu, każdy kontrakt raz."""

    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for ids, template in (
        (by_sender, REASON_SENDER),
        (client_named, REASON_CLIENT_MAIL),
        (text_named, REASON_TEXT),
    ):
        for contract_id in ids:
            contract = contracts.get(contract_id)
            if contract is None or contract_id in seen:
                continue
            seen.add(contract_id)
            name = contract.candidate_name or "konsultant"
            out.append(
                {
                    "contract_id": contract_id,
                    "candidate_name": contract.candidate_name,
                    "client_name": contract.client_name,
                    "reason": template.format(name=name),
                }
            )
            if len(out) >= limit:
                return out
    return out


# ── Odczyt z bazy ────────────────────────────────────────────────────────────


def _email_key(value: Optional[str]) -> Optional[str]:
    cleaned = (value or "").replace("\x00", "").strip().lower()
    return cleaned or None


def _full_name(first: Optional[str], last: Optional[str]) -> Optional[str]:
    joined = " ".join(p.strip() for p in (first, last) if p and p.strip())
    return joined or None


@dataclass(frozen=True)
class _Profile:
    """Profil kandydata dla ``resolve_contact`` (sam e-mail z zapytania)."""

    email: Optional[str]
    phone: Optional[str] = None


def _live_query():
    return (
        select(
            Contract.id,
            Contract.client_id,
            Candidate.name,
            Candidate.lastname,
            Client.name,
        )
        .select_from(Contract)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(Client, Client.id == Contract.client_id)
        .where(Contract.status.in_(LIVE_STATUSES), Contract.voided_at.is_(None))
    )


def _live_rows(rows) -> dict[int, LiveContract]:
    return {
        contract_id: LiveContract(
            contract_id=contract_id,
            client_id=client_id,
            candidate_name=_full_name(first, last),
            client_name=client_name,
        )
        for contract_id, client_id, first, last, client_name in rows
    }


async def live_contracts_for_emails(
    db: AsyncSession, emails: Iterable[Optional[str]]
) -> dict[str, list[int]]:
    """E-mail → aktywne kontrakty, których konsultant ma ten adres.

    Adres jak na karcie kontraktu: wpisany na umowie wygrywa z profilem.
    """

    wanted = sorted({key for key in map(_email_key, emails) if key})
    if not wanted:
        return {}
    rows = (
        await db.execute(
            select(Contract.id, Contract.candidate_email, Candidate.email)
            .select_from(Contract)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .where(
                Contract.status.in_(LIVE_STATUSES),
                Contract.voided_at.is_(None),
                or_(
                    func.lower(func.trim(Contract.candidate_email)).in_(wanted),
                    func.lower(func.trim(Candidate.email)).in_(wanted),
                ),
            )
            .order_by(Contract.id)
        )
    ).all()
    out: dict[str, list[int]] = {}
    for contract_id, contract_email, profile_email in rows:
        resolved = resolve_contact(
            contract_email=contract_email,
            contract_phone=None,
            candidate=_Profile(profile_email),
        )
        key = _email_key(resolved.email)
        if key in wanted:
            out.setdefault(key, []).append(contract_id)
    return out


async def link_new_mail_case(
    db: AsyncSession, case: AdminCase, *, sender_email: Optional[str]
) -> Optional[int]:
    """Nowa sprawa z maila konsultanta → jego kontrakt, gdy jest dokładnie jeden.

    Nie nadpisuje kontraktu wpisanego wcześniej (np. przez odpowiedź na
    komunikat). Nie commituje — wchodzi w punkt zapisu czytnika.
    """

    if case.contract_id is not None:
        return None
    key = _email_key(sender_email)
    if key is None:
        return None
    contract_id = sender_contract(
        (await live_contracts_for_emails(db, [key])).get(key, [])
    )
    if contract_id is None:
        return None
    case.contract_id = contract_id
    audit.record(
        db,
        actor_user_id=None,
        subject_user_id=case.subject_user_id,
        entity_type="admin_case",
        entity_id=case.id,
        action="case_linked",
        details={"contract_id": contract_id, "source": "mail_sender"},
    )
    await db.flush()
    return contract_id


async def _client_ids_of_senders(db: AsyncSession, emails: Sequence[str]) -> set[int]:
    """Klienci, których kontaktem jest nadawca (z klientem docelowym scalenia)."""

    if not emails:
        return set()
    client_ids = set(
        await db.scalars(
            select(Contact.client_id).where(
                func.lower(func.trim(Contact.email)).in_(list(emails))
            )
        )
    )
    if not client_ids:
        return set()
    merged = dict(
        (
            await db.execute(
                select(Client.id, Client.merged_into_client_id).where(
                    Client.id.in_(sorted(client_ids))
                )
            )
        ).all()
    )
    return client_ids | {target for target in merged.values() if target}


async def link_suggestions(db: AsyncSession, case: AdminCase) -> list[dict[str, Any]]:
    """„Kogo dotyczy?” — propozycje kontraktu dla sprawy bez kontraktu.

    Liczone przy odczycie, niczego nie zapisują.
    """

    if case.contract_id is not None:
        return []
    messages = (
        await db.execute(
            select(
                AdminCaseMessage.sender_email,
                AdminCaseMessage.subject,
                AdminCaseMessage.body_text,
            )
            .where(AdminCaseMessage.case_id == case.id)
            .order_by(AdminCaseMessage.id.asc())
            .limit(MESSAGES_LIMIT)
        )
    ).all()
    senders = sorted({key for key in (_email_key(m[0]) for m in messages) if key})
    by_email = await live_contracts_for_emails(db, senders)
    by_sender = sorted({cid for ids in by_email.values() for cid in ids})

    text_value = "\n".join(
        part
        for part in (
            case.title,
            case.description,
            *(m[1] for m in messages),
            *(m[2] for m in messages),
        )
        if part
    )[:TEXT_LIMIT]
    live = _live_rows((await db.execute(_live_query())).all())
    named = names_in_text(
        text_value, {cid: row.candidate_name for cid, row in live.items()}
    )
    sender_clients = await _client_ids_of_senders(db, senders)
    client_named = [cid for cid in named if live[cid].client_id in sender_clients]
    text_named = [cid for cid in named if cid not in client_named]

    return rank_suggestions(
        by_sender=by_sender,
        client_named=client_named,
        text_named=text_named,
        contracts=live,
    )
