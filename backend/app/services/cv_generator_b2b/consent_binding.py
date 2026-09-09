"""Bind a consent upload to its operator, subject and recruitment context.

The signature proves the recorded association, not what the screenshot says.
Existing generated documents keep their stored attachment; only new generation
requires a valid receipt. An upload without a DB candidate is bound to CV bytes.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac

from jose import JWTError, jwt

from app.core.config import settings


AUDIENCE = "nexus:cv-consent:v1"


def _key() -> bytes:
    return hmac.new(
        settings.SECRET_KEY.encode(), AUDIENCE.encode(), hashlib.sha256
    ).digest()


def subject(
    *, candidate_id=None, stage_id=None, client_id=None, cv_sha256=None
) -> dict:
    if cv_sha256 is not None:
        return {"mode": "upload", "cv_sha256": cv_sha256, "client_id": client_id}
    return {
        "mode": "candidate",
        "candidate_id": candidate_id,
        "stage_id": stage_id,
        "client_id": client_id,
    }


def issue(storage_key: str, user_id: int, context: dict) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(hours=8),
            "owner": user_id,
            "context": context,
            "storage_key": storage_key,
        },
        _key(),
        algorithm="HS256",
    )


def verify(token: str, user_id: int, context: dict) -> dict:
    try:
        receipt = jwt.decode(
            token,
            _key(),
            algorithms=["HS256"],
            audience=AUDIENCE,
            options={"require_exp": True, "require_iat": True, "require_aud": True},
        )
        key = receipt["storage_key"]
        if receipt["owner"] != user_id or receipt["context"] != context:
            raise ValueError
        if not isinstance(key, str) or not key.startswith("cv/") or len(key) > 500:
            raise ValueError
        return {
            "storage_key": key,
            "binding": {
                "version": 1,
                "uploaded_by": user_id,
                "subject": context,
                "uploaded_at": receipt["iat"],
            },
        }
    except (JWTError, KeyError, TypeError, ValueError):
        raise ValueError(
            "Consent attachment does not match the current source and context"
        ) from None
