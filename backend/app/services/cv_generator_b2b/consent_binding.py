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
    *,
    candidate_id=None,
    stage_id=None,
    client_id=None,
    cv_sha256=None,
    generated_id=None,
) -> dict:
    # `generated` (generator v3): zgoda dołączana do GOTOWEGO CV — wiązana
    # z wierszem głównym pakietu, nie ze źródłem generacji.
    if generated_id is not None:
        return {
            "mode": "generated",
            "generated_id": generated_id,
            "client_id": client_id,
        }
    if cv_sha256 is not None:
        return {"mode": "upload", "cv_sha256": cv_sha256, "client_id": client_id}
    return {
        "mode": "candidate",
        "candidate_id": candidate_id,
        "stage_id": stage_id,
        "client_id": client_id,
    }


def issue(
    storage_key: str, user_id: int, context: dict, check: dict | None = None
) -> str:
    """``check`` — wynik `cv_consent_check` (27.10.2026). Jedzie podpisany
    w pokwitowaniu i ląduje w ``binding`` przy CV, więc QC CV czyta go bez
    nowej kolumny, a rekruter nie podmieni werdyktu po stronie przeglądarki."""
    now = datetime.now(timezone.utc)
    claims = {
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(hours=8),
        "owner": user_id,
        "context": context,
        "storage_key": storage_key,
    }
    if check is not None:
        claims["check"] = check
    return jwt.encode(claims, _key(), algorithm="HS256")


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
        binding = {
            "version": 1,
            "uploaded_by": user_id,
            "subject": context,
            "uploaded_at": receipt["iat"],
        }
        if isinstance(receipt.get("check"), dict):
            binding["check"] = receipt["check"]
        return {"storage_key": key, "binding": binding}
    except (JWTError, KeyError, TypeError, ValueError):
        raise ValueError(
            "Consent attachment does not match the current source and context"
        ) from None
