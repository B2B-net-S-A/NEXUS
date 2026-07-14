from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from passlib.context import CryptContext

from app.core.config import settings
from app.core.jwt import jwt

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
    token_version: int = 0,
) -> str:
    """Create a JWT access token.

    Claim ``fpc`` (force_password_change) jest dodawany TYLKO gdy True —
    dla starych tokenów (sprzed deploya) middleware traktuje brak claim
    jako False (default). Frontend middleware czyta ``fpc`` żeby
    przekierować usera do /profile po admin-resecie hasła.
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
        "ver": token_version,
    }
    if force_password_change:
        payload["fpc"] = True
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(subject: Union[str, int], token_version: int = 0) -> str:
    """Create a JWT refresh token (longer-lived, no role)."""
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": str(subject),
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "ver": token_version,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises JWTError on failure."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


def token_version_matches(payload: dict, current_version: int) -> bool:
    """Fail closed on malformed/stale versions with one bounded legacy escape."""
    claim = payload.get("ver")
    if claim is None:
        return settings.JWT_ALLOW_LEGACY_VERSIONLESS and current_version == 0
    # bool is an int subclass; accepting True as version 1 would be ambiguous.
    return type(claim) is int and claim >= 0 and claim == current_version
