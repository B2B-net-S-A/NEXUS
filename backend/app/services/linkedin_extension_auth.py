"""Klucz wtyczki LinkedIn: wydanie, weryfikacja, limit dzienny.

Format jak klucze kont serwisowych (``service_account_auth``), z innym
prefiksem, żeby jednego nie dało się użyć zamiast drugiego::

    nxe_v1_<24 hex id>_<sekret urlsafe>

Klucz należy do osoby, nie do automatu: za nim stoi ``User`` z jego rolami
i uprawnieniami, sprawdzanymi przy każdym żądaniu. Czytają go wyłącznie trasy
``/api/extension/*`` (zależność ``ExtensionUser``), więc nie otwiera reszty API.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_today
from app.models.linkedin_extension import LinkedinExtensionConnection

EXTENSION_KEY_HEADER = "X-Extension-Key"

_WIRE_PREFIX = "nxe_v1_"
_KEY_ID_HEX_LEN = 24
_WIRE_RE = re.compile(
    rf"^{re.escape(_WIRE_PREFIX)}(?P<kid>[0-9a-f]{{{_KEY_ID_HEX_LEN}}})_(?P<secret>[A-Za-z0-9_-]{{32,128}})$"
)
# Stempel ``last_used_at`` najwyżej raz na minutę — odczyt nie może stać się
# zapisem do gorącego wiersza przy każdym kliknięciu w panelu.
_LAST_USED_THROTTLE = timedelta(seconds=60)


class ExtensionKeyError(Exception):
    """Klucz odrzucony. ``reason`` jest do logów; klient dostaje jedno zdanie."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DailyLimitReached(Exception):
    """Osoba wyczerpała dzienny limit odczytów stron LinkedIna."""


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def allowed_extension_ids() -> frozenset[str]:
    return frozenset(
        part.strip()
        for part in (settings.LINKEDIN_EXTENSION_IDS or "").split(",")
        if part.strip()
    )


def generate_extension_key() -> tuple[str, str, str]:
    """``(klucz_na_drut, key_id, secret_sha256)`` — klucz widać tylko raz."""
    kid = secrets.token_hex(_KEY_ID_HEX_LEN // 2)
    secret = secrets.token_urlsafe(32)
    return f"{_WIRE_PREFIX}{kid}_{secret}", f"v1${kid}", _sha256_hex(secret)


def parse_extension_key(raw: str) -> tuple[str, str]:
    match = _WIRE_RE.match(raw or "")
    if match is None:
        raise ExtensionKeyError("malformed_key")
    return f"v1${match.group('kid')}", match.group("secret")


async def issue_connection(
    db: AsyncSession,
    *,
    user_id: int,
    authorization_version: int,
    extension_version: str | None,
) -> tuple[str, LinkedinExtensionConnection]:
    """Połącz wtyczkę z kontem. Wcześniejsze połączenia osoby są odwoływane:
    jedna osoba = jedna aktywna wtyczka, więc „Odłącz” w Ustawieniach zawsze
    odcina tę, z której ktoś faktycznie korzysta."""
    now = datetime.now(timezone.utc)
    # Licznik dnia jest osoby, nie połączenia: ponowne połączenie nie może
    # zerować limitu (przegląd bezpieczeństwa 28.10.2026).
    previous = await db.scalar(
        select(LinkedinExtensionConnection)
        .where(LinkedinExtensionConnection.user_id == user_id)
        .order_by(LinkedinExtensionConnection.created_at.desc())
        .limit(1)
    )
    today = business_today()
    carried = previous is not None and previous.usage_day == today
    await db.execute(
        update(LinkedinExtensionConnection)
        .where(
            LinkedinExtensionConnection.user_id == user_id,
            LinkedinExtensionConnection.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoked_by=user_id)
    )
    wire, key_id, secret_hash = generate_extension_key()
    connection = LinkedinExtensionConnection(
        key_id=key_id,
        user_id=user_id,
        secret_sha256=secret_hash,
        authorization_version=authorization_version,
        extension_version=(extension_version or "")[:32] or None,
        expires_at=now + timedelta(days=max(1, settings.LINKEDIN_EXTENSION_TTL_DAYS)),
        usage_day=today if carried else None,
        reads_today=previous.reads_today if carried else 0,
        adds_today=previous.adds_today if carried else 0,
    )
    db.add(connection)
    await db.flush()
    return wire, connection


async def authenticate_extension_key(
    db: AsyncSession, raw_key: str
) -> LinkedinExtensionConnection:
    """Zweryfikuj klucz. Kolejność jak w kluczach serwisowych: kształt bez I/O,
    wiersz po jawnym id, sekret w stałym czasie, dopiero potem stan."""
    key_id, secret = parse_extension_key(raw_key)
    connection = await db.scalar(
        select(LinkedinExtensionConnection).where(
            LinkedinExtensionConnection.key_id == key_id
        )
    )
    if connection is None:
        _sha256_hex(secret)
        raise ExtensionKeyError("unknown_key")
    if not hmac.compare_digest(_sha256_hex(secret), connection.secret_sha256):
        raise ExtensionKeyError("bad_secret")
    if connection.revoked_at is not None:
        raise ExtensionKeyError("revoked_key")
    if _as_aware(connection.expires_at) <= datetime.now(timezone.utc):
        raise ExtensionKeyError("expired_key")
    user = connection.user
    if user is None or not user.is_active:
        raise ExtensionKeyError("inactive_user")
    # Zmiana roli, uprawnień albo hasła podbija wersję — wtyczka połączona
    # wcześniej przestaje działać, tak jak wylogowuje się sesja w przeglądarce.
    if connection.authorization_version != user.authorization_version:
        raise ExtensionKeyError("authorization_changed")
    # Zmiana albo reset hasła stawia podłogę sesji (``tokens_valid_after``)
    # i nie podbija wersji uprawnień — połączenie sprzed podłogi jest martwe,
    # tak jak JWT sprzed niej (``token_is_revoked``).
    floor = user.tokens_valid_after
    if floor is not None and _as_aware(connection.created_at) <= _as_aware(floor):
        raise ExtensionKeyError("password_changed")
    return connection


async def count_page_read(
    db: AsyncSession, connection: LinkedinExtensionConnection
) -> None:
    """Jeden odczyt strony LinkedIna (profil albo strona wyników).

    Jeden atomowy UPDATE z warunkiem limitu: równoległe żądania nie przeskoczą
    limitu, a nowy dzień zaczyna licznik od 1. Brak wiersza w RETURNING =
    limit wyczerpany → ``DailyLimitReached``.
    """
    today = business_today()
    limit = max(0, settings.LINKEDIN_EXTENSION_DAILY_READ_LIMIT)
    if limit == 0:
        raise DailyLimitReached()
    same_day = LinkedinExtensionConnection.usage_day == today
    row = (
        await db.execute(
            update(LinkedinExtensionConnection)
            .where(
                LinkedinExtensionConnection.key_id == connection.key_id,
                LinkedinExtensionConnection.usage_day.is_(None)
                | (LinkedinExtensionConnection.usage_day != today)
                | (LinkedinExtensionConnection.reads_today < limit),
            )
            .values(
                reads_today=case(
                    (same_day, LinkedinExtensionConnection.reads_today + 1), else_=1
                ),
                adds_today=case(
                    (same_day, LinkedinExtensionConnection.adds_today), else_=0
                ),
                usage_day=today,
            )
            .returning(
                LinkedinExtensionConnection.reads_today,
                LinkedinExtensionConnection.adds_today,
            )
            .execution_options(synchronize_session=False)
        )
    ).first()
    if row is None:
        raise DailyLimitReached()
    _sync_counters(connection, today, row[0], row[1])


async def count_add(db: AsyncSession, connection: LinkedinExtensionConnection) -> None:
    today = business_today()
    same_day = LinkedinExtensionConnection.usage_day == today
    row = (
        await db.execute(
            update(LinkedinExtensionConnection)
            .where(LinkedinExtensionConnection.key_id == connection.key_id)
            .values(
                adds_today=case(
                    (same_day, LinkedinExtensionConnection.adds_today + 1), else_=1
                ),
                reads_today=case(
                    (same_day, LinkedinExtensionConnection.reads_today), else_=0
                ),
                usage_day=today,
            )
            .returning(
                LinkedinExtensionConnection.reads_today,
                LinkedinExtensionConnection.adds_today,
            )
            .execution_options(synchronize_session=False)
        )
    ).first()
    if row is not None:
        _sync_counters(connection, today, row[0], row[1])


def _sync_counters(
    connection: LinkedinExtensionConnection, day, reads: int, adds: int
) -> None:
    """Wartości z bazy do obiektu bez oznaczania go jako zmienionego — flush
    nie może nadpisać licznika starszą wartością z pamięci."""
    from sqlalchemy.orm.attributes import set_committed_value

    set_committed_value(connection, "usage_day", day)
    set_committed_value(connection, "reads_today", reads)
    set_committed_value(connection, "adds_today", adds)


def stamp_last_used(connection: LinkedinExtensionConnection) -> None:
    now = datetime.now(timezone.utc)
    if connection.last_used_at is None or (
        now - _as_aware(connection.last_used_at) >= _LAST_USED_THROTTLE
    ):
        connection.last_used_at = now
