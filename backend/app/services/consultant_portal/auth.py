"""Logowanie do portalu: link z maila, sesja, kod SMS.

Bezpieczeństwo to główne ryzyko tego modułu, stąd reguły:

* **Tokeny tylko jako SHA-256.** Losowe 256 bitów; wyciek bazy nie otwiera portalu.
* **Link jednorazowy i krótki.** Zużycie to warunkowy ``UPDATE``, więc dwa równoległe
  otwarcia nie dadzą dwóch sesji. Skanery poczty otwierają adresy same, dlatego
  sesję zakłada dopiero POST ze strony.
* **Sesja osobna od JWT pracownika.** Losowy token w nagłówku ``X-Portal-Session``,
  a nie w ``Authorization``: pracowniczy JWT tu nie pasuje do żadnego hasha, a token
  portalu nie jest JWT, więc ``get_current_user`` go odrzuca. Sesja padnie, gdy kontrakt
  przestanie działać, zmieni adres albo wypadnie z pilotażu.
* **Ta sama odpowiedź dla każdego adresu.** ``request_link`` nie zdradza, czy konsultant
  istnieje; limit linków na kontrakt też milczy.
* **Kod SMS jako HMAC.** Sześć cyfr z SHA-256 odwraca się w ułamku sekundy, więc hash
  jest kluczowany i związany z sesją. Limit prób, termin, limit wysyłek na kontrakt.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.consultant_portal import CpLink, CpSession, CpSmsCode
from app.services.consultant_portal import identity
from app.services.consultant_portal.identity import Consultant
from app.services.consultant_portal.portal_settings import PortalSettings
from app.services.consultant_portal.sms import current_sender
from app.services.consultant_portal_schema import MAX_SMS_ATTEMPTS

logger = logging.getLogger(__name__)

LOGIN_LINK_TTL = timedelta(minutes=30)
RATING_LINK_TTL = timedelta(days=7)
SESSION_TTL = timedelta(hours=12)
SMS_CODE_TTL = timedelta(minutes=5)
#: Tyle trwa odblokowanie finansów po poprawnym kodzie.
SMS_VERIFIED_TTL = timedelta(minutes=30)
LINKS_PER_HOUR = 3
SMS_RESEND_AFTER = timedelta(seconds=60)
SMS_PER_HOUR = 5
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

    @property
    def finance_open_until(self) -> Optional[datetime]:
        return self.session.sms_verified_until


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


def finance_open(context: PortalContext, now: datetime) -> bool:
    until = context.session.sms_verified_until
    return until is not None and until > now


async def revoke(db: AsyncSession, session: CpSession, *, now: datetime) -> None:
    session.revoked_at = now


# ── Kod SMS ──────────────────────────────────────────────────────────────────


def _code_hash(session_id: int, code: str) -> str:
    key = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(key, f"{session_id}:{code}".encode(), hashlib.sha256).hexdigest()


def phone_hint(phone: Optional[str]) -> Optional[str]:
    digits = [ch for ch in phone or "" if ch.isdigit()]
    return f"••• {''.join(digits[-3:])}" if len(digits) >= 3 else None


def valid_phone(phone: Optional[str]) -> bool:
    digits = sum(ch.isdigit() for ch in phone or "")
    return 9 <= digits <= 15


UNAVAILABLE = (
    "Faktury i raporty są chwilowo niedostępne. Reszta portalu działa, a w tej "
    "sprawie możesz napisać do nas przez nowe zgłoszenie."
)
NO_PHONE = (
    "Nie mamy Twojego numeru telefonu, więc nie możemy wysłać kodu. Załóż zgłoszenie, "
    "a dopiszemy numer."
)
WAIT_FOR_CODE = "Kod właśnie wysłaliśmy. Nowy możesz poprosić za minutę."
TOO_MANY_CODES = "Wysłaliśmy już kilka kodów. Spróbuj ponownie za godzinę."
BAD_CODE = "Ten kod nie pasuje albo wygasł. Sprawdź SMS albo poproś o nowy kod."


async def send_code(db: AsyncSession, context: PortalContext, *, now: datetime) -> None:
    sender = current_sender()
    if not sender.available:
        raise PortalError(UNAVAILABLE, status=503, code="finance_unavailable")
    phone = context.consultant.phone
    if not valid_phone(phone):
        raise PortalError(NO_PHONE, status=409, code="no_phone")
    contract_id = context.consultant.contract_id
    last = await db.scalar(
        select(func.max(CpSmsCode.created_at)).where(
            CpSmsCode.contract_id == contract_id
        )
    )
    if last is not None and now - last < SMS_RESEND_AFTER:
        raise PortalError(WAIT_FOR_CODE, status=429, code="sms_wait")
    sent = await db.scalar(
        select(func.count())
        .select_from(CpSmsCode)
        .where(
            CpSmsCode.contract_id == contract_id,
            CpSmsCode.created_at >= now - timedelta(hours=1),
        )
    )
    if (sent or 0) >= SMS_PER_HOUR:
        raise PortalError(TOO_MANY_CODES, status=429, code="sms_limit")
    code = f"{secrets.randbelow(1_000_000):06d}"
    # Stary kod przestaje działać, gdy przychodzi nowy.
    await db.execute(
        update(CpSmsCode)
        .where(
            CpSmsCode.session_id == context.session.id, CpSmsCode.consumed_at.is_(None)
        )
        .values(consumed_at=now)
    )
    db.add(
        CpSmsCode(
            session_id=context.session.id,
            contract_id=contract_id,
            code_hash=_code_hash(context.session.id, code),
            expires_at=now + SMS_CODE_TTL,
            created_at=now,
        )
    )
    await db.flush()
    delivered = await sender.send(
        to=phone or "",
        text=f"Kod do strefy konsultanta B2B.net: {code}. Ważny 5 minut.",
    )
    if not delivered:
        raise PortalError(UNAVAILABLE, status=503, code="finance_unavailable")


async def verify_code(
    db: AsyncSession, context: PortalContext, code: str, *, now: datetime
) -> bool:
    """Poprawny kod otwiera finanse. Wyczerpany limit prób kasuje kod.

    Licznik rośnie warunkowym ``UPDATE`` przed porównaniem, więc równoległe próby nie
    przejdą ponad limit. Wołający zapisuje wynik także przy odmowie.
    """

    row = await db.scalar(
        select(CpSmsCode.id).where(
            CpSmsCode.session_id == context.session.id,
            CpSmsCode.consumed_at.is_(None),
            CpSmsCode.expires_at > now,
            CpSmsCode.attempts < MAX_SMS_ATTEMPTS,
        )
    )
    if row is None:
        return False
    updated = (
        await db.execute(
            update(CpSmsCode)
            .where(CpSmsCode.id == row, CpSmsCode.attempts < MAX_SMS_ATTEMPTS)
            .values(attempts=CpSmsCode.attempts + 1)
            .returning(CpSmsCode.code_hash, CpSmsCode.attempts)
        )
    ).first()
    if updated is None:
        return False
    stored, attempts = updated
    if hmac.compare_digest(stored, _code_hash(context.session.id, code.strip())):
        await db.execute(
            update(CpSmsCode).where(CpSmsCode.id == row).values(consumed_at=now)
        )
        context.session.sms_verified_until = now + SMS_VERIFIED_TTL
        return True
    if attempts >= MAX_SMS_ATTEMPTS:
        await db.execute(
            update(CpSmsCode).where(CpSmsCode.id == row).values(consumed_at=now)
        )
    return False
