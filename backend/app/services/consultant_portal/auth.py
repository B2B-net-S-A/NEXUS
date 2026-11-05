"""Logowanie do portalu: link z maila i sesja.

Bezpieczeństwo to główne ryzyko tego modułu, stąd reguły:

* **Tokeny tylko jako SHA-256.** Losowe 256 bitów; wyciek bazy nie otwiera portalu.
* **Link jednorazowy i krótki.** Zużycie to warunkowy ``UPDATE``, więc dwa równoległe
  otwarcia nie dadzą dwóch sesji. Skanery poczty otwierają adresy same, dlatego
  sesję zakłada dopiero POST ze strony.
* **Sesja osobna od JWT pracownika.** Losowy token w nagłówku ``X-Portal-Session``,
  a nie w ``Authorization``: pracowniczy JWT tu nie pasuje do żadnego hasha, a token
  portalu nie jest JWT, więc ``get_current_user`` go odrzuca. Sesja padnie, gdy kontrakt
  przestanie działać, zmieni adres albo straci aktywację.
* **Ta sama odpowiedź dla każdego adresu.** ``request_link`` nie zdradza, czy konsultant
  istnieje; limit linków na kontrakt też milczy.

Kod SMS przed finansami usunięto decyzją Artura z 04.11.2026: link z maila jest jedynym
krokiem, a adres potwierdza człowiek przy aktywacji panelu. Tabela ``cp_sms_codes`` zostaje.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consultant_portal import CpLink, CpSession
from app.services.consultant_portal import identity
from app.services.consultant_portal.identity import Consultant
from app.services.consultant_portal.portal_settings import PortalSettings

logger = logging.getLogger(__name__)

LOGIN_LINK_TTL = timedelta(minutes=30)
RATING_LINK_TTL = timedelta(days=7)
SESSION_TTL = timedelta(hours=12)
LINKS_PER_HOUR = 3
TOKEN_MAX_LENGTH = 128


class PortalError(Exception):
    """Odmowa z komunikatem po polsku (bez szczegółów wewnętrznych)."""

    def __init__(self, message: str, *, status: int = 422, code: str = "refused"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, token_hash(raw)


def _usable(raw: Optional[str]) -> bool:
    return bool(raw) and len(raw) <= TOKEN_MAX_LENGTH


# ── Link z maila ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LinkToSend:
    contract_id: int
    email: str
    raw_token: str


async def request_link(
    db: AsyncSession, email: str, *, state: PortalSettings, today: date, now: datetime
) -> Optional[LinkToSend]:
    """Link do wysłania albo ``None``. Wołający odpowiada zawsze tak samo."""

    contract = await identity.resolve_by_email(db, email, settings=state, today=today)
    if contract is None:
        return None
    recent = await db.scalar(
        select(func.count())
        .select_from(CpLink)
        .where(
            CpLink.contract_id == contract.id,
            CpLink.purpose == "login",
            CpLink.created_at >= now - timedelta(hours=1),
        )
    )
    if (recent or 0) >= LINKS_PER_HOUR:
        return None
    raw, digest = new_token()
    address = identity.normalize_email(email)
    db.add(
        CpLink(
            contract_id=contract.id,
            purpose="login",
            email=address,
            token_hash=digest,
            expires_at=now + LOGIN_LINK_TTL,
            created_at=now,
        )
    )
    await db.flush()
    return LinkToSend(contract_id=contract.id, email=address, raw_token=raw)


async def rating_link(
    db: AsyncSession, *, contract_id: int, meeting_id: int, email: str, now: datetime
) -> str:
    """Link do oceny jednej rozmowy; działa bez sesji i wygasa po 7 dniach."""

    raw, digest = new_token()
    db.add(
        CpLink(
            contract_id=contract_id,
            purpose="rating",
            meeting_id=meeting_id,
            email=identity.normalize_email(email),
            token_hash=digest,
            expires_at=now + RATING_LINK_TTL,
            created_at=now,
        )
    )
    await db.flush()
    return raw


async def consume_link(
    db: AsyncSession, raw: Optional[str], *, purpose: str, now: datetime
) -> Optional[CpLink]:
    """Zużywa link warunkowo: drugie otwarcie i wygasły link dają ``None``."""

    if not _usable(raw):
        return None
    link_id = await db.scalar(
        update(CpLink)
        .where(
            CpLink.token_hash == token_hash(raw or ""),
            CpLink.purpose == purpose,
            CpLink.used_at.is_(None),
            CpLink.expires_at > now,
        )
        .values(used_at=now)
        .returning(CpLink.id)
    )
    return await db.get(CpLink, link_id) if link_id else None


async def peek_link(
    db: AsyncSession, raw: Optional[str], *, purpose: str, now: datetime
) -> Optional[CpLink]:
    """Odczyt bez zużycia (formularz oceny pokazuje, czego dotyczy)."""

    if not _usable(raw):
        return None
    return await db.scalar(
        select(CpLink).where(
            CpLink.token_hash == token_hash(raw or ""),
            CpLink.purpose == purpose,
            CpLink.used_at.is_(None),
            CpLink.expires_at > now,
        )
    )


# ── Sesja ────────────────────────────────────────────────────────────────────


async def open_session(
    db: AsyncSession,
    raw_link: Optional[str],
    *,
    state: PortalSettings,
    today: date,
    now: datetime,
) -> Optional[tuple[str, CpSession]]:
    link = await consume_link(db, raw_link, purpose="login", now=now)
    if link is None:
        return None
    consultant = await identity.load_consultant(
        db,
        contract_id=link.contract_id,
        email=link.email,
        settings=state,
        today=today,
    )
    if consultant is None:
        return None
    raw, digest = new_token()
    session = CpSession(
        contract_id=link.contract_id,
        email=link.email,
        token_hash=digest,
        expires_at=now + SESSION_TTL,
        created_at=now,
    )
    db.add(session)
    await db.flush()
    return raw, session


@dataclass(frozen=True)
class PortalContext:
    session: CpSession
    consultant: Consultant


async def load_context(
    db: AsyncSession,
    raw: Optional[str],
    *,
    state: PortalSettings,
    today: date,
    now: datetime,
) -> Optional[PortalContext]:
    if not _usable(raw):
        return None
    session = await db.scalar(
        select(CpSession).where(
            CpSession.token_hash == token_hash(raw or ""),
            CpSession.revoked_at.is_(None),
            CpSession.expires_at > now,
        )
    )
    if session is None:
        return None
    consultant = await identity.load_consultant(
        db,
        contract_id=session.contract_id,
        email=session.email,
        settings=state,
        today=today,
    )
    return PortalContext(session, consultant) if consultant else None


async def revoke(db: AsyncSession, session: CpSession, *, now: datetime) -> None:
    session.revoked_at = now
