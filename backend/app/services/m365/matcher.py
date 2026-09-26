"""Match an incoming email to a candidate in the database.

Precedence (Phase 1 implements strict + smart_domain; Phase 2 adds
smart_thread + smart_name):

1. strict       — any from/to/cc address equals candidate.email        (conf=1.0)
2. smart_thread — another email with the same conversation_id already
                  linked to a candidate (conf inherited, method=smart_thread)
3. smart_domain — sender domain matches EXACTLY ONE candidate's email
                  domain in the recruiter's book, AND the domain is not a
                  public/free-mail provider                              (conf=0.7)
4. smart_name   — subject contains candidate name+lastname as adjacent
                  tokens AND candidate was contacted <90d ago            (conf=0.5)

Below 0.5 confidence → (candidate_id=None, method=unmatched).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contact import Contact
from app.models.m365 import Email, EmailMatchMethod
from app.services.m365.provider import MatchResult

logger = logging.getLogger(__name__)


# Free-mail domains we never use for smart_domain matching (too ambiguous).
PUBLIC_EMAIL_DOMAINS: frozenset[str] = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "yahoo.com",
        "yahoo.co.uk",
        "icloud.com",
        "me.com",
        "protonmail.com",
        "proton.me",
        "wp.pl",
        "onet.pl",
        "onet.eu",
        "interia.pl",
        "interia.eu",
        "o2.pl",
        "tlen.pl",
        "gazeta.pl",
        "poczta.fm",
    }
)


@dataclass(frozen=True)
class IncomingMessage:
    """DB-agnostic DTO so matcher can be unit-tested without SQLAlchemy."""

    from_address: str
    to_addresses: list[str]
    cc_addresses: list[str]
    subject: Optional[str]
    conversation_id: str
    # Adres skrzynki, z której pochodzi mail (runda 6 audytu). Właściciel jest
    # nadawcą albo odbiorcą KAŻDEJ wiadomości w skrzynce, więc jego adres (i
    # domena firmy) nie może wskazywać kandydata.
    owner_address: Optional[str] = None


def _normalize_email(addr: str) -> str:
    return (addr or "").strip().lower()


def _email_domain(addr: str) -> Optional[str]:
    norm = _normalize_email(addr)
    if "@" not in norm:
        return None
    return norm.rsplit("@", 1)[1]


# Litery, których NFKD NIE rozkłada, bo znak diakrytyczny jest wpisany w sam
# glif (kreska przecinająca literę), a nie doklejony jako osobny znak łączący.
# Bez tej mapy `encode("ascii", "ignore")` je KASUJE zamiast uprościć: „Łukasz"
# stawał się „ukasz", więc dopasowanie po nazwisku milczało dla każdego
# kandydata z Ł/ł w imieniu lub nazwisku (Łukasz, Michał, Paweł…) — a to nie
# jest przypadek brzegowy w polskiej bazie.
_UNDECOMPOSABLE = str.maketrans({"Ł": "L", "ł": "l"})


def _fold_diacritics(s: str) -> str:
    """Lowercase + strip Polish diacritics for robust name matching."""
    pre = s.translate(_UNDECOMPOSABLE)
    folded = (
        unicodedata.normalize("NFKD", pre).encode("ascii", "ignore").decode("ascii")
    )
    return folded.lower()


def _contains_name(subject: str, name: str, lastname: str) -> bool:
    """True if `<name> <lastname>` (order-insensitive, diacritic-folded) is in subject."""
    if not subject or not name or not lastname:
        return False
    fs = _fold_diacritics(subject)
    fn = _fold_diacritics(name)
    fl = _fold_diacritics(lastname)
    # Allow both "Jan Kowalski" and "Kowalski Jan"
    return bool(re.search(rf"\b{re.escape(fn)}\b.*\b{re.escape(fl)}\b", fs)) or bool(
        re.search(rf"\b{re.escape(fl)}\b.*\b{re.escape(fn)}\b", fs)
    )


def _internal_domains(owner_address: Optional[str]) -> set[str]:
    """Domeny firmy: SSO + domena właściciela skrzynki (runda 6 audytu)."""
    domains = set(settings.sso_allowed_domains_list)
    owner_domain = _email_domain(owner_address or "")
    if owner_domain:
        domains.add(owner_domain)
    return domains


async def _find_candidate_by_email(
    db: AsyncSession, addresses: list[str], *, owner_address: Optional[str] = None
) -> Optional[Candidate]:
    """Return the first candidate whose email matches any of the given addresses.

    Runda 6 audytu: adres właściciela skrzynki i adresy w domenach firmy są
    pomijane — kandydat z takim adresem (import, pracownik w bazie) przypinał
    do siebie KAŻDY mail skrzynki albo każdy wątek z kolegą w kopii.
    """
    internal = _internal_domains(owner_address)
    owner = _normalize_email(owner_address or "")
    normalized = sorted(
        {
            n
            for n in (_normalize_email(a) for a in addresses if a)
            if n and n != owner and _email_domain(n) not in internal
        }
    )
    if not normalized:
        return None
    stmt = (
        select(Candidate)
        .where(Candidate.email.in_(normalized))
        .order_by(Candidate.id)
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _is_client_domain(db: AsyncSession, domain: str) -> bool:
    """Domena klienta (kontakt u klienta albo strona klienta) — runda 6 audytu.

    Mail od hiring managera klienta nie jest mailem kandydata, nawet jeśli
    w bazie jest dokładnie jeden kandydat z adresem w tej domenie (np. ktoś,
    kto u tego klienta pracował).
    """
    pattern = f"%@{domain}"
    contact_hit = await db.scalar(
        select(exists().where(func.lower(Contact.email).like(pattern)))
    )
    if contact_hit:
        return True
    site_hit = await db.scalar(
        select(
            exists().where(
                or_(
                    func.lower(Client.website).like(f"%://{domain}%"),
                    func.lower(Client.website).like(f"%://www.{domain}%"),
                    func.lower(Client.website) == domain,
                    func.lower(Client.website) == f"www.{domain}",
                )
            )
        )
    )
    return bool(site_hit)


async def _find_candidates_by_domain(db: AsyncSession, domain: str) -> list[Candidate]:
    """Return candidates whose email ends with @{domain} (najwyżej dwóch).

    Liczy się tylko „dokładnie jeden”, więc drugi wiersz wystarcza, żeby
    odmówić — bez ładowania wszystkich kandydatów z popularnej domeny.
    """
    stmt = (
        select(Candidate)
        .where(Candidate.email.ilike(f"%@{domain}"))
        .order_by(Candidate.id)
        .limit(2)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# Okno „kandydat w kontakcie” dla smart_name (docstring modułu, runda 6).
SMART_NAME_CONTACT_WINDOW = timedelta(days=90)
# Sufit trafień po nazwisku i imieniu z tematu — więcej niż jedno = brak
# dopasowania, więc drugi wiersz wystarcza; zapas na odsianie kolejności słów.
_SMART_NAME_ROW_LIMIT = 20
_FOLD_FROM = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"
_FOLD_TO = "acelnoszzACELNOSZZ"


def _folded_sql(column):
    return func.lower(func.translate(column, _FOLD_FROM, _FOLD_TO))


def _subject_tokens(folded_subject: str) -> list[str]:
    tokens: set[str] = set()
    for word in re.findall(r"[a-z]+(?:-[a-z]+)*", folded_subject):
        if len(word) >= 3:
            tokens.add(word)
        for part in word.split("-"):
            if len(part) >= 3:
                tokens.add(part)
    return sorted(tokens)[:50]


async def _find_candidate_by_subject_name(
    db: AsyncSession, subject: str
) -> Optional[int]:
    """Kandydat, którego imię i nazwisko są w temacie (runda 6 audytu).

    Do 26.09.2026 ta reguła ładowała CAŁĄ tabelę kandydatów (~60 tys. pełnych
    obiektów) przy każdym niedopasowanym mailu i blokowała pętlę zdarzeń.
    Teraz zawężenie jest w SQL (imię i nazwisko są słowami tematu, kandydat
    w kontakcie < 90 dni), a przy więcej niż jednej osobie nic nie przypinamy.
    """
    tokens = _subject_tokens(_fold_diacritics(subject))
    if not tokens:
        return None
    cutoff = datetime.now(timezone.utc) - SMART_NAME_CONTACT_WINDOW
    recently_emailed = exists().where(
        Email.candidate_id == Candidate.id, Email.received_at >= cutoff
    )
    stmt = (
        select(Candidate.id, Candidate.name, Candidate.lastname)
        .where(
            Candidate.email.is_not(None),
            Candidate.lastname.is_not(None),
            _folded_sql(Candidate.lastname).in_(tokens),
            _folded_sql(Candidate.name).in_(tokens),
            or_(Candidate.last_contacted_at >= cutoff, recently_emailed),
        )
        .order_by(Candidate.id)
        .limit(_SMART_NAME_ROW_LIMIT)
    )
    rows = (await db.execute(stmt)).all()
    hits = {
        row.id
        for row in rows
        if _contains_name(subject, row.name or "", row.lastname or "")
    }
    return next(iter(hits)) if len(hits) == 1 else None


async def _find_candidate_by_conversation(
    db: AsyncSession, conversation_id: str
) -> Optional[Email]:
    """Return any previously matched email from the same conversation."""
    stmt = (
        select(Email)
        .where(
            Email.m365_conversation_id == conversation_id,
            Email.candidate_id.isnot(None),
        )
        .order_by(Email.received_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def match(db: AsyncSession, msg: IncomingMessage) -> MatchResult:
    """Apply precedence rules and return the best match (or unmatched)."""
    # ── 1. strict (from/to/cc exact) ───────────────────────────────────────
    all_addrs = [msg.from_address, *msg.to_addresses, *msg.cc_addresses]
    candidate = await _find_candidate_by_email(
        db, all_addrs, owner_address=msg.owner_address
    )
    if candidate:
        return MatchResult(
            candidate_id=candidate.id,
            method=EmailMatchMethod.strict.value,
            confidence=1.0,
        )

    # ── 2. smart_thread (Phase 2 — already matched conversation) ───────────
    prior = await _find_candidate_by_conversation(db, msg.conversation_id)
    if prior and prior.candidate_id is not None:
        return MatchResult(
            candidate_id=prior.candidate_id,
            method=EmailMatchMethod.smart_thread.value,
            confidence=prior.match_confidence or 0.9,
        )

    # ── 3. smart_domain (unique domain candidate in book) ──────────────────
    domain = _email_domain(msg.from_address)
    if (
        domain
        and domain not in PUBLIC_EMAIL_DOMAINS
        and domain not in _internal_domains(msg.owner_address)
        and not await _is_client_domain(db, domain)
    ):
        candidates = await _find_candidates_by_domain(db, domain)
        if len(candidates) == 1:
            return MatchResult(
                candidate_id=candidates[0].id,
                method=EmailMatchMethod.smart_domain.value,
                confidence=0.7,
            )

    # ── 4. smart_name (name+lastname in subject, contacted < 90 days) ──────
    if msg.subject:
        candidate_id = await _find_candidate_by_subject_name(db, msg.subject)
        if candidate_id is not None:
            return MatchResult(
                candidate_id=candidate_id,
                method=EmailMatchMethod.smart_name.value,
                confidence=0.5,
            )

    return MatchResult(
        candidate_id=None,
        method=EmailMatchMethod.unmatched.value,
        confidence=None,
    )
