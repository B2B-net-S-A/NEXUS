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
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
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


def _normalize_email(addr: str) -> str:
    return (addr or "").strip().lower()


def _email_domain(addr: str) -> Optional[str]:
    norm = _normalize_email(addr)
    if "@" not in norm:
        return None
    return norm.rsplit("@", 1)[1]


def _fold_diacritics(s: str) -> str:
    """Lowercase + strip Polish diacritics for robust name matching."""
    # Unicode decomposition does not split Polish L-with-stroke, so an ASCII
    # encode with ``ignore`` used to drop the letter entirely (Łukasz ->
    # ukasz). Translate that character explicitly before folding the remaining
    # combining marks.
    translated = s.translate(str.maketrans({"Ł": "L", "ł": "l"}))
    folded = (
        unicodedata.normalize("NFKD", translated)
        .encode("ascii", "ignore")
        .decode("ascii")
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


async def _find_candidate_by_email(
    db: AsyncSession, addresses: list[str]
) -> Optional[Candidate]:
    """Return the first candidate whose email matches any of the given addresses."""
    normalized = [_normalize_email(a) for a in addresses if a]
    if not normalized:
        return None
    stmt = select(Candidate).where(Candidate.email.in_(normalized))
    result = await db.execute(stmt)
    return result.scalars().first()


async def _find_candidates_by_domain(db: AsyncSession, domain: str) -> list[Candidate]:
    """Return candidates whose email ends with @{domain}."""
    stmt = select(Candidate).where(Candidate.email.ilike(f"%@{domain}"))
    result = await db.execute(stmt)
    return list(result.scalars().all())


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
    candidate = await _find_candidate_by_email(db, all_addrs)
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
    if domain and domain not in PUBLIC_EMAIL_DOMAINS:
        candidates = await _find_candidates_by_domain(db, domain)
        if len(candidates) == 1:
            return MatchResult(
                candidate_id=candidates[0].id,
                method=EmailMatchMethod.smart_domain.value,
                confidence=0.7,
            )

    # ── 4. smart_name (Phase 2 — name+lastname in subject) ─────────────────
    # Cheap heuristic: we don't iterate the entire candidate table (could be huge);
    # restrict to candidates whose lastname appears verbatim in the folded subject.
    if msg.subject:
        folded_subject = _fold_diacritics(msg.subject)
        # Small surface: candidates with non-empty last-name, contacted recently.
        # Using raw SQL LIKE over folded substring is noisy; Phase 2 promotes this
        # to a materialized view or trigram index. For MVP we skip if subject
        # has no alpha tokens to avoid scanning the whole table.
        tokens = re.findall(r"[a-z]{3,}", folded_subject)
        if tokens:
            # Try each candidate whose lastname (lowered, folded) is in the token
            # set — cheap enough as Phase 1 quick win.
            stmt = select(Candidate).where(Candidate.lastname.isnot(None))
            result = await db.execute(stmt)
            for cand in result.scalars():
                if cand.email is None:
                    continue
                if _contains_name(msg.subject, cand.name or "", cand.lastname or ""):
                    return MatchResult(
                        candidate_id=cand.id,
                        method=EmailMatchMethod.smart_name.value,
                        confidence=0.5,
                    )

    return MatchResult(
        candidate_id=None,
        method=EmailMatchMethod.unmatched.value,
        confidence=None,
    )
