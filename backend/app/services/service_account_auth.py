"""Wystawianie i weryfikacja kluczy API kont serwisowych.

Cały kontakt z sekretem żyje w tym module: generacja, rozbiór formatu z drutu,
porównanie skrótu i decyzja „ważny / nieważny". Endpointy i zależności FastAPI
dostają już tylko obiekt ``ServicePrincipal`` — nigdzie poza tym plikiem nie ma
zmiennej trzymającej sekret.

Format klucza::

    nxs_v2_<24 hex znaki id>_<43 znaki sekretu urlsafe>
    └┬─┘ └┬┘ └──────┬──────┘ └──────────┬─────────────┘
     │    │         │                   └─ 256 bitów z secrets.token_urlsafe
     │    │         └─ jawne id klucza → PK "v2$<hex>" w bazie
     │    └─ wersja schematu (v3 = inna funkcja skrótu, bez zgadywania)
     └─ marker produktu: ``nxs_`` jest grepowalny przez gitleaks i skanery
        sekretów, więc klucz wklejony do repo zapala się w CI zamiast leżeć

Rozbicie na jawne id + sekret jest celowe. Gdyby szukać wiersza po skrócie
sekretu, każde zapytanie do bazy sondowałoby indeks wartością wyprowadzoną
z sekretu, a jawne id nie dałoby się bezpiecznie zalogować — czyli nie byłoby
z czego zrobić audytu „którym kluczem". Tak: SELECT idzie po jawnym id,
a porównanie skrótów robi ``hmac.compare_digest`` w stałym czasie.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.service_account import ServiceAccount, ServiceAccountKey

logger = logging.getLogger(__name__)

# Nagłówek transportowy. Świadomie NIE ``Authorization: Bearer`` — uzasadnienie
# przy ``app/api/deps.py::require_service_scope``.
API_KEY_HEADER = "X-API-Key"

_WIRE_PREFIX = "nxs_v2_"
_KEY_ID_HEX_LEN = 24
_SECRET_BYTES = 32

# Format z drutu waliduje się regexem PRZED dotknięciem bazy: bez tego każdy
# śmieć z internetu generuje zapytanie SQL.
_WIRE_RE = re.compile(
    rf"^{re.escape(_WIRE_PREFIX)}(?P<kid>[0-9a-f]{{{_KEY_ID_HEX_LEN}}})_(?P<secret>[A-Za-z0-9_-]{{32,128}})$"
)


class ServiceKeyError(Exception):
    """Poświadczenie odrzucone. ``reason`` jest etykietą do logów, nie do klienta.

    Klient dostaje zawsze ten sam komunikat (patrz zależność w ``deps.py``) —
    rozróżnianie „nie ma takiego klucza" od „zły sekret" powiedziałoby sondującemu,
    które id istnieją.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ServicePrincipal:
    """Uwierzytelnione konto serwisowe stojące za requestem.

    Osobny typ od ``User`` z rozmysłem: kod, który dostaje ``ServicePrincipal``,
    nie ma jak przez pomyłkę wywołać ``has_role()`` ani wpisać ``user_id`` do
    tabeli domenowej — nie ma takich pól.
    """

    account_id: int
    slug: str
    key_id: str
    scopes: frozenset[str]

    @property
    def audit_label(self) -> str:
        """„Kto + którym kluczem" w jednym stringu do logów i pól ``*_by``."""
        return f"service_account:{self.slug}#{self.key_id}"


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Wygeneruj nowy klucz. Zwraca ``(klucz_na_druty, key_id, secret_sha256)``.

    Klucz z pierwszej pozycji jest jedyną kopią sekretu, jaka kiedykolwiek
    zaistnieje — wywołujący ma go oddać użytkownikowi i zapomnieć.
    """
    key_id_hex = secrets.token_hex(_KEY_ID_HEX_LEN // 2)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    wire = f"{_WIRE_PREFIX}{key_id_hex}_{secret}"
    return wire, f"v2${key_id_hex}", _sha256_hex(secret)


def parse_api_key(raw: str) -> tuple[str, str]:
    """Rozbierz klucz z drutu na ``(key_id, sekret)``.

    Rzuca ``ServiceKeyError`` na czymkolwiek, co nie pasuje do formatu — wliczając
    w to pusty string i klucz w innej wersji niż ``v2``.
    """
    match = _WIRE_RE.match(raw or "")
    if match is None:
        raise ServiceKeyError("malformed_key")
    return f"v2${match.group('kid')}", match.group("secret")


async def authenticate_api_key(
    db: AsyncSession,
    raw_key: str,
) -> tuple[ServicePrincipal, ServiceAccountKey]:
    """Zweryfikuj klucz i zwróć konto, do którego należy.

    Kolejność sprawdzeń jest istotna: najpierw kształt (bez I/O), potem wiersz,
    potem sekret w stałym czasie, a dopiero na końcu stan konta i klucza.
    Sekret weryfikujemy PRZED sprawdzeniem wygaśnięcia i rewokacji, żeby
    odpowiedzi nie różnicowały czasu w zależności od tego, czy podane id
    odpowiada kluczowi żywemu, czy odwołanemu.
    """
    key_id, secret = parse_api_key(raw_key)

    result = await db.execute(
        select(ServiceAccountKey).where(ServiceAccountKey.key_id == key_id)
    )
    key = result.unique().scalar_one_or_none()
    if key is None:
        # Nadal liczymy skrót, żeby ścieżka „nie ma takiego id" nie była mierzalnie
        # szybsza od „jest id, zły sekret".
        _sha256_hex(secret)
        raise ServiceKeyError("unknown_key")

    if not hmac.compare_digest(_sha256_hex(secret), key.secret_sha256):
        raise ServiceKeyError("bad_secret")

    now = datetime.now(timezone.utc)
    if key.revoked_at is not None:
        raise ServiceKeyError("revoked_key")
    if _as_aware(key.expires_at) <= now:
        raise ServiceKeyError("expired_key")

    account: Optional[ServiceAccount] = key.service_account
    if account is None:
        raise ServiceKeyError("orphaned_key")
    if not account.is_active:
        raise ServiceKeyError("inactive_account")

    return (
        ServicePrincipal(
            account_id=account.id,
            slug=account.slug,
            key_id=key.key_id,
            scopes=account.granted_scopes(),
        ),
        key,
    )


def _as_aware(value: datetime) -> datetime:
    """Postgres zwraca TIMESTAMPTZ jako aware, ale fixture/SQLite bywa naiwny.

    Porównanie aware z naiwnym rzuca ``TypeError`` w środku decyzji
    autoryzacyjnej, a to znaczyłoby 500 zamiast 401 — czyli klucz przeterminowany
    dawałby inny błąd niż nieznany, co samo w sobie jest wyciekiem informacji.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def stamp_key_usage(
    db: AsyncSession,
    key_id: str,
    client_ip: Optional[str],
) -> None:
    """Odnotuj użycie klucza — z dławieniem, żeby odczyt nie stał się zapisem.

    Sygnał, o który tu chodzi, to „czy ta integracja jeszcze żyje" (dokładnie ten
    sam, co ``oauth_clients.last_used_at``), a on nie potrzebuje rozdzielczości
    pojedynczego requestu. Bez dławienia każde wywołanie API dokładałoby UPDATE
    do tego samego wiersza, więc ruchliwy klucz zamieniłby się w gorący punkt
    zapisu i łańcuch martwych krotek.

    Warunek ``last_used_at < now() - próg`` siedzi w WHERE, nie w Pythonie —
    dzięki temu równoległe requesty nie ścigają się o odczyt-modyfikację-zapis,
    tylko przegrywają na poziomie bazy, bez błędu.

    Stempel jest świadomie best-effort: wyjątek jest łykany i logowany, bo
    nieudany zapis telemetrii nie może wywrócić już autoryzowanego wywołania.
    """
    throttle = max(int(settings.SERVICE_ACCOUNT_LAST_USED_THROTTLE_SECONDS), 0)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=throttle)
    try:
        await db.execute(
            update(ServiceAccountKey)
            .where(
                ServiceAccountKey.key_id == key_id,
                (ServiceAccountKey.last_used_at.is_(None))
                | (ServiceAccountKey.last_used_at < cutoff),
            )
            .values(
                last_used_at=datetime.now(timezone.utc),
                # IP jest przycinane do rozmiaru kolumny; długi X-Forwarded-For
                # nie ma prawa wywrócić zapisu telemetrii.
                last_used_ip=(client_ip or "")[:64] or None,
            )
        )
        await db.commit()
    except Exception:  # noqa: BLE001 - telemetria nie może psuć autoryzacji
        await db.rollback()
        logger.warning("service_account.stamp_failed", extra={"key_id": key_id})


def default_expires_at(requested_days: Optional[int]) -> datetime:
    """Wylicz ``expires_at`` dla nowego klucza, przycinając do sufitu z configu.

    Brak wartości → domyślny okres z configu. Wartość powyżej sufitu jest
    **przycinana, nie odrzucana**: 400 na „za długi termin" zachęca do kolejnego
    strzału z mniejszą liczbą, a przycięcie po prostu wymusza politykę.
    Sufit i domyślny okres są odczytywane przy każdym wywołaniu, więc zmiana
    env-a działa bez restartu importu modułu.
    """
    default_days = max(int(settings.SERVICE_ACCOUNT_KEY_DEFAULT_TTL_DAYS), 1)
    max_days = max(int(settings.SERVICE_ACCOUNT_KEY_MAX_TTL_DAYS), 1)
    days = default_days if requested_days is None else max(int(requested_days), 1)
    return datetime.now(timezone.utc) + timedelta(days=min(days, max_days))
