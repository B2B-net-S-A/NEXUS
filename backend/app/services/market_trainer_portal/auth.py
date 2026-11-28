"""Link z maila i sesja trenera z rynku — te same zasady co panel konsultanta
(``consultant_portal/auth``), osobne tabele.

* Tokeny tylko jako SHA-256, link jednorazowy na 30 minut, zużycie warunkowym
  ``UPDATE`` (dwa otwarcia nie dadzą dwóch sesji), sesję zakłada dopiero POST.
* Sesja w nagłówku ``X-Portal-Session``, ale w ``mt_portal_sessions``: token trenera
  nie pasuje do ``cp_sessions``, więc nie otworzy żadnej trasy konsultanta.
* Ta sama odpowiedź dla każdego adresu; limit linków milczy.
* Sesja pada, gdy panel zamknięto, trener wypadł z bazy, adres się zmienił albo
  włącznik jest wyłączony.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.website_intake import (
    MarketTrainerApplication,
    MtPortalLink,
    MtPortalSession,
)
from app.services.consultant_portal.auth import new_token, token_hash
from app.services.consultant_portal.identity import normalize_email

LOGIN_LINK_TTL = timedelta(minutes=30)
SESSION_TTL = timedelta(hours=12)
LINKS_PER_HOUR = 3
TOKEN_MAX_LENGTH = 128


@dataclass(frozen=True)
class LinkToSend:
    application_id: int
    email: str
    raw_token: str


@dataclass(frozen=True)
class TrainerContext:
    session: MtPortalSession
    trainer: MarketTrainerApplication

    @property
    def market_id(self) -> int:
        return self.trainer.id


def _usable(raw: Optional[str]) -> bool:
    return bool(raw) and len(raw or "") <= TOKEN_MAX_LENGTH


async def _open_trainer(
    db: AsyncSession, *, application_id: Optional[int] = None, email: str = ""
) -> Optional[MarketTrainerApplication]:
    """Trener z otwartym panelem: po id (sesja) albo po adresie logowania (link)."""
    query = select(MarketTrainerApplication).where(
        MarketTrainerApplication.status == "accepted",
        MarketTrainerApplication.panel_opened_at.is_not(None),
        MarketTrainerApplication.panel_closed_at.is_(None),
    )
    if application_id is not None:
        query = query.where(MarketTrainerApplication.id == application_id)
    else:
        query = query.where(
            func.lower(MarketTrainerApplication.panel_email) == normalize_email(email)
        )
    rows = (await db.scalars(query.limit(2))).all()
    # Ten sam adres u dwóch trenerów nie otwiera niczego (jak w panelu konsultanta).
    return rows[0] if len(rows) == 1 else None


async def request_link(
    db: AsyncSession, email: str, *, now: datetime
) -> Optional[LinkToSend]:
    """Link do wysłania albo ``None``. Wołający odpowiada zawsze tak samo."""
    address = normalize_email(email)
    if not address:
        return None
    trainer = await _open_trainer(db, email=address)
    if trainer is None:
        return None
    recent = await db.scalar(
        select(func.count())
        .select_from(MtPortalLink)
        .where(
            MtPortalLink.application_id == trainer.id,
            MtPortalLink.created_at >= now - timedelta(hours=1),
        )
    )
    if (recent or 0) >= LINKS_PER_HOUR:
        return None
    raw, digest = new_token()
    db.add(
        MtPortalLink(
            application_id=trainer.id,
            email=address,
            token_hash=digest,
            expires_at=now + LOGIN_LINK_TTL,
            created_at=now,
        )
    )
    await db.flush()
    return LinkToSend(application_id=trainer.id, email=address, raw_token=raw)


async def issue_link(
    db: AsyncSession, trainer: MarketTrainerApplication, *, now: datetime
) -> str:
    """Link do maila z zaproszeniem przy otwarciu panelu przez TCM."""
    raw, digest = new_token()
    db.add(
        MtPortalLink(
            application_id=trainer.id,
            email=normalize_email(trainer.panel_email),
            token_hash=digest,
            expires_at=now + LOGIN_LINK_TTL,
            created_at=now,
        )
    )
    await db.flush()
    return raw


async def open_session(
    db: AsyncSession, raw_link: Optional[str], *, now: datetime
) -> Optional[tuple[str, MtPortalSession]]:
    if not _usable(raw_link):
        return None
    link_id = await db.scalar(
        update(MtPortalLink)
        .where(
            MtPortalLink.token_hash == token_hash(raw_link or ""),
            MtPortalLink.used_at.is_(None),
            MtPortalLink.expires_at > now,
        )
        .values(used_at=now)
        .returning(MtPortalLink.id)
    )
    link = await db.get(MtPortalLink, link_id) if link_id else None
    if link is None:
        return None
    trainer = await _open_trainer(db, application_id=link.application_id)
    if trainer is None or normalize_email(trainer.panel_email) != link.email:
        return None
    raw, digest = new_token()
    session = MtPortalSession(
        application_id=trainer.id,
        email=link.email,
        token_hash=digest,
        expires_at=now + SESSION_TTL,
        created_at=now,
    )
    db.add(session)
    await db.flush()
    return raw, session


async def load_context(
    db: AsyncSession, raw: Optional[str], *, now: datetime
) -> Optional[TrainerContext]:
    if not _usable(raw):
        return None
    session = await db.scalar(
        select(MtPortalSession).where(
            MtPortalSession.token_hash == token_hash(raw or ""),
            MtPortalSession.revoked_at.is_(None),
            MtPortalSession.expires_at > now,
        )
    )
    if session is None:
        return None
    trainer = await _open_trainer(db, application_id=session.application_id)
    # Zmieniony adres logowania zamyka stare sesje: link wyszedłby na inny adres.
    if trainer is None or normalize_email(trainer.panel_email) != session.email:
        return None
    return TrainerContext(session=session, trainer=trainer)


async def revoke_all(db: AsyncSession, application_id: int, *, now: datetime) -> None:
    await db.execute(
        update(MtPortalSession)
        .where(
            MtPortalSession.application_id == application_id,
            MtPortalSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
