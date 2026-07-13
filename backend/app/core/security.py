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
    }
    if roles:
        payload["roles"] = roles
    if force_password_change:
        payload["fpc"] = True
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(subject: Union[str, int]) -> str:
    """Create a JWT refresh token (longer-lived, no role)."""
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": str(subject),
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises JWTError on failure."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
