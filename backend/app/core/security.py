import hmac
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional, Union

import bcrypt
from jose import jwt

from app.core.config import settings

ALGORITHM = "HS256"

# Bezpośrednio pyca/bcrypt, nie passlib. passlib (ostatnie wydanie 2020,
# projekt nieutrzymywany) przy inicjalizacji backendu odpala detect_wrap_bug
# z >72-bajtowym hasłem testowym, a bcrypt 5 na >72 B rzuca ValueError
# zamiast po cichu ucinać — więc każde verify()/hash() wybuchało na starcie.
# Jawne ucięcie do 72 bajtów odtwarza semantykę passliba (bcrypt z definicji
# liczy tylko pierwsze 72 bajty), dzięki czemu istniejące hashe — także
# haseł dłuższych niż 72 bajty — weryfikują się bez zmian.
_BCRYPT_MAX_BYTES = 72
# Tyle co dotychczasowy default passliba — nowe hashe zostają $2b$12$.
_BCRYPT_ROUNDS = 12

# Stała do wyrównania czasu, nie sekret (hash literału "nexus-timing-equalizer").
# Ścieżka invalid-hash odpada w mikrosekundy, a prawdziwy verify to ~setki ms —
# bez spalenia kosztu czas odpowiedzi /api/auth/login zdradzałby, które konta
# mają placeholder z importu Traffita. Ta sama zasada co bcrypt liczony na obu
# ścieżkach rejestracji (anti-enumeration).
_DUMMY_HASH = b"$2b$12$XIC4ez/F8wAC/Y/.sa.A6.CIqyRSrsapLIgL5LYOcebe3w8RNw7Xu"


# dzień UTC celowo: epoka Unix (punkt zero ``iat``), nie data kalendarzowa.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
# Runda 14: tokeny z całkowitym ``iat`` wybijał wyłącznie kod sprzed wdrożenia
# rundy 13 (28.09.2026 13:38 UTC; stare kontenery obsługują ruch najwyżej
# kilka minut dłużej). Taki token z ``iat`` późniejszym niż ta chwila nie mógł
# powstać legalnie, a po 30 dniach (``REFRESH_TOKEN_EXPIRE_DAYS``) wszystkie
# wygasają — wtedy porównanie po pełnych sekundach przestaje mieć komu służyć.
# dzień UTC celowo: znacznik chwili wdrożenia, nie data kalendarzowa.
_LEGACY_INT_IAT_UNTIL = int(
    datetime(2026, 9, 28, 14, 30, tzinfo=timezone.utc).timestamp()
)
_MICROSECOND = timedelta(microseconds=1)


def _issued_at(moment: datetime) -> float:
    """``iat`` z mikrosekundami (RFC 7519 NumericDate dopuszcza ułamek).

    Runda 13 (AUTH): jose koduje ``datetime`` jako pełne sekundy, a wtedy
    token wybity w tej samej sekundzie co podłoga unieważnienia — przed nią
    albo po niej — był nie do odróżnienia. Ułamek pozwala porównać dokładnie.
    """
    return round(moment.timestamp(), 6)


def _microseconds(moment: datetime) -> int:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment - _EPOCH) // _MICROSECOND


def secrets_equal(presented: Optional[str], expected: Optional[str]) -> bool:
    """Porównanie sekretów w stałym czasie, odporne na znaki spoza ASCII.

    Runda 9 (R9-N9-6): ``hmac.compare_digest`` na dwóch ``str`` rzuca
    ``TypeError``, gdy którykolwiek ma znak spoza ASCII — nagłówek HTTP
    (Starlette dekoduje latin-1) albo pole JSON z „ł” dawało 500 zamiast
    odmowy. Porównujemy bajty UTF-8; tekst nie do zakodowania = zły sekret.
    """
    if presented is None or expected is None:
        return False
    try:
        presented_bytes = presented.encode("utf-8")
        expected_bytes = expected.encode("utf-8")
    except (AttributeError, UnicodeEncodeError):
        return False
    return hmac.compare_digest(presented_bytes, expected_bytes)


def _bcrypt_secret(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """Hash a plain-text password."""
    return bcrypt.hashpw(
        _bcrypt_secret(password), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    ).decode("utf-8")


def has_usable_password(hashed_password: Optional[str]) -> bool:
    """Czy konto ma hasło, którym da się zalogować (hash bcrypta).

    ``None`` = konto tylko SSO (Microsoft), placeholder importu Traffita
    (``!imported-from-traffit-no-login!``) też nie jest hasłem.
    """
    return bool(hashed_password) and hashed_password.startswith("$2")


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    """Verify a plain-text password against a hash.

    Nie-bcryptowy ``hashed_password`` zwraca ``False`` zamiast rzucać.
    To zmiana względem passliba (``UnknownHashError``) i celowa naprawa:
    konta z importu Traffita mają placeholder
    ``!imported-from-traffit-no-login!``, więc próba logowania na nie
    kończyła się nieobsłużonym wyjątkiem (500) w ``auth.py`` zamiast
    zwykłego 401 „Invalid credentials".

    Brak hasha (konto tylko SSO, ``password_hash IS NULL``) też daje
    ``False`` — do 09.2026 kończył się ``AttributeError`` i 500 (AUTH-04).
    """
    if not hashed_password:
        # Spal koszt bcrypta, żeby odpowiedź trwała tyle co zwykły verify.
        bcrypt.checkpw(_bcrypt_secret(plain_password), _DUMMY_HASH)
        return False
    try:
        return bcrypt.checkpw(
            _bcrypt_secret(plain_password), hashed_password.encode("utf-8")
        )
    except ValueError:
        # Spal koszt bcrypta, żeby odpowiedź trwała tyle co zwykły verify.
        bcrypt.checkpw(_bcrypt_secret(plain_password), _DUMMY_HASH)
        return False


def create_access_token(
    subject: Union[str, int],
    role: str,
    expires_delta: Optional[timedelta] = None,
    force_password_change: bool = False,
    roles: Optional[list[str]] = None,
    authorization_version: int = 1,
    section_access: Mapping[str, str] | None = None,
) -> str:
    """Create a JWT access token.

    Claim ``fpc`` (force_password_change) jest dodawany TYLKO gdy True —
    dla starych tokenów (sprzed deploya) middleware traktuje brak claim
    jako False (default). Frontend middleware czyta ``fpc`` żeby
    przekierować usera do /profile po admin-resecie hasła.

    Claim ``roles`` (unia primary + secondary) pozwala middleware'owi frontu
    sprawdzać RBAC po PEŁNYM zestawie ról — dotąd JWT niósł tylko ``role``
    (primary), więc user primary=recruiter + secondary=tac widział link (Sidebar
    czyta roles[]) i przechodził backend guard, ale middleware rzucał /403.
    Dodawany tylko gdy podany (stare tokeny bez ``roles`` → fallback na ``role``).
    """
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict = {
        "sub": str(subject),
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": _issued_at(now),
        "av": authorization_version,
    }
    if roles:
        payload["roles"] = roles
    if section_access is not None:
        # Signed UX snapshot for Next middleware. Backend authorization always
        # resolves the current database policy independently on each request.
        payload["sa"] = dict(section_access)
    if force_password_change:
        payload["fpc"] = True
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(
    subject: Union[str, int], authorization_version: int = 1
) -> str:
    """Create a JWT refresh token (longer-lived, no role)."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(subject),
        "type": "refresh",
        "exp": expire,
        "iat": _issued_at(now),
        "av": authorization_version,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def token_authorization_version_matches(
    payload: dict,
    current_version: int,
) -> bool:
    """Require the signed JWT to carry the exact current integer version."""

    raw = payload.get("av")
    return type(raw) is int and raw == current_version


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises JWTError on failure."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


def token_is_revoked(payload: dict, tokens_valid_after: Optional[datetime]) -> bool:
    """True gdy token jest unieważniony przez session-revocation floor (F-05).

    ``tokens_valid_after`` = None → brak floora → nigdy nie unieważnione
    (istniejący userzy bez zdarzenia zmiany hasła nie są dotknięci).

    Gdy floor jest ustawiony, porównujemy ``iat`` z floorem z dokładnością
    do mikrosekundy. Runda 13 (AUTH): do tej rundy porównanie szło po pełnych
    sekundach, więc token wybity w tej samej sekundzie co zmiana hasła, ale
    PRZED nią, przeżywał unieważnienie. Nowe tokeny mają ``iat`` z ułamkiem
    (``_issued_at``, JSON zachowuje go także przy ``.0``) i są wybijane po
    postawieniu podłogi z zegara aplikacji, więc ``iat >= floor`` (równość =
    ważny).

    Token sprzed wdrożenia ma ``iat`` całkowite (obcięte do sekundy), więc
    w sekundzie podłogi nie da się ustalić, czy powstał przed nią, czy po niej
    — a „po” to np. para z odpowiedzi zmiany hasła albo logowanie SSO, które
    samo postawiło podłogę. Dla takich tokenów zostaje porównanie po pełnych
    sekundach: wdrożenie nikogo nie wylogowuje, a podłogi stawiane po
    wdrożeniu i tak są późniejsze niż każdy token w starym formacie.

    Brak ``iat`` przy ustawionym floorze → nie potrafimy udowodnić świeżości
    tokenu → traktujemy jako unieważniony (bezpieczny kierunek).
    """
    if tokens_valid_after is None:
        return False
    iat = payload.get("iat")
    if iat is None or isinstance(iat, bool):
        return True
    floor_us = _microseconds(tokens_valid_after)
    if isinstance(iat, int):
        if iat >= _LEGACY_INT_IAT_UNTIL:
            return True
        return iat < floor_us // 1_000_000
    try:
        issued_us = round(float(iat) * 1_000_000)
    except (TypeError, ValueError, OverflowError):
        return True
    return issued_us < floor_us
