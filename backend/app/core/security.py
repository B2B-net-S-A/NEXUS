from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """Hash a plain-text password."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    subject: Union[str, int],
    role: str,
    expires_delta: Optional[timedelta] = None,
    force_password_change: bool = False,
    roles: Optional[list[str]] = None,
    authorization_version: int = 1,
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
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict = {
        "sub": str(subject),
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "av": authorization_version,
    }
    if roles:
        payload["roles"] = roles
    if force_password_change:
        payload["fpc"] = True
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(
    subject: Union[str, int], authorization_version: int = 1
) -> str:
    """Create a JWT refresh token (longer-lived, no role)."""
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": str(subject),
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
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

    Gdy floor jest ustawiony, porównujemy ``iat`` tokenu z floorem na
    granulacji CAŁYCH sekund, bo JWT ``iat`` ma rozdzielczość sekundową
    (jose koduje datetime jako unixowy int). Floorujemy ``tokens_valid_after``
    do pełnych sekund, żeby NIE odrzucić tokenu wybitego w tej samej sekundzie
    co zdarzenie zmiany hasła (nowe tokeny po zmianie są wybijane później).

    Brak ``iat`` przy ustawionym floorze → nie potrafimy udowodnić świeżości
    tokenu → traktujemy jako unieważniony (bezpieczny kierunek).
    """
    if tokens_valid_after is None:
        return False
    iat = payload.get("iat")
    if iat is None:
        return True
    floor_seconds = int(tokens_valid_after.timestamp())
    return int(iat) < floor_seconds
