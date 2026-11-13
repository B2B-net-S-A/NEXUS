"""Bilet do odtwarzania pliku szkolenia w ``<video>``/``<audio>``.

Odtwarzacz przeglądarki pobiera plik sam, kawałkami (nagłówek ``Range``), i nie dołoży
nagłówka sesji panelu (``X-Portal-Session``) ani tokenu pracownika. Dlatego trasa z sesją
wydaje bilet: HMAC z ``SECRET_KEY`` nad (id pliku, termin), ważny ``TTL`` — tyle, żeby
obejrzeć trzygodzinne szkolenie z przerwą. Bilet otwiera wyłącznie ten jeden plik i nie
jest sesją. Trafia do adresu, więc widać go w logu dostępu: dlatego krótki termin
i zakres jednego pliku, a nie sesja w adresie.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from app.core.config import settings

TTL = timedelta(hours=6)
_PURPOSE = b"training-media:v1"


def _sign(file_id: int, expires: int) -> str:
    message = _PURPOSE + f":{file_id}:{expires}".encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def issue(file_id: int, *, now: datetime) -> str:
    expires = int((now + TTL).timestamp())
    return f"{expires}.{_sign(file_id, expires)}"


def valid(file_id: int, ticket: str, *, now: datetime) -> bool:
    expires_text, _, signature = (ticket or "").partition(".")
    if not expires_text.isdigit() or not signature:
        return False
    expires = int(expires_text)
    if expires < int(now.timestamp()):
        return False
    return hmac.compare_digest(signature, _sign(file_id, expires))


def url(file_id: int, *, now: datetime) -> str:
    return f"/api/public/training-media/{file_id}?t={issue(file_id, now=now)}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
