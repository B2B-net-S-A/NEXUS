"""Bilet do odtwarzania pliku szkolenia w ``<video>``/``<audio>``.

Odtwarzacz przeglądarki pobiera plik sam, kawałkami (nagłówek ``Range``), i nie dołoży
nagłówka sesji panelu (``X-Portal-Session``) ani tokenu pracownika. Dlatego trasa z sesją
wydaje bilet: HMAC z ``SECRET_KEY`` nad (zakres, id pliku, termin), ważny ``TTL`` — tyle,
żeby obejrzeć trzygodzinne szkolenie z przerwą. Bilet otwiera wyłącznie ten jeden plik
i nie jest sesją. Trafia do adresu, więc widać go w logu dostępu: dlatego krótki termin
i zakres jednego pliku, a nie sesja w adresie.

Zakres ``lib`` (plik z biblioteki) trasa odtwarzania sprawdza przy każdym żądaniu jeszcze
raz, więc wycofanie szkolenia albo pliku z biblioteki zamyka też wydane bilety
(przegląd bezpieczeństwa 13.11.2026). Zakres ``own`` to plik własnego szkolenia trenera
albo podgląd TCM i Finansów przed publikacją.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from app.core.config import settings

TTL = timedelta(hours=6)
Scope = Literal["lib", "own", "reg"]
#: ``reg`` (0695) = nagranie udostępnione zapisanym przed zapłatą; trasa odtwarzania
#: sprawdza przy każdym żądaniu, czy udostępnienie nadal trwa.
SCOPES: tuple[str, ...] = ("lib", "own", "reg")
_PURPOSE = b"training-media:v2"


def _sign(scope: str, file_id: int, expires: int) -> str:
    message = _PURPOSE + f":{scope}:{file_id}:{expires}".encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def issue(file_id: int, *, scope: Scope, now: datetime) -> str:
    expires = int((now + TTL).timestamp())
    return f"{scope}.{expires}.{_sign(scope, file_id, expires)}"


def scope_of(file_id: int, ticket: str, *, now: datetime) -> Optional[str]:
    """Zakres ważnego biletu tego pliku albo ``None`` (także dla śmieci w adresie)."""

    if not ticket or not ticket.isascii():
        return None
    parts = ticket.split(".")
    if len(parts) != 3:
        return None
    scope, expires_text, signature = parts
    if scope not in SCOPES or not expires_text.isdigit() or not signature:
        return None
    expires = int(expires_text)
    if expires < int(now.timestamp()):
        return None
    expected = _sign(scope, file_id, expires).encode()
    if not hmac.compare_digest(signature.encode(), expected):
        return None
    return scope


def url(file_id: int, *, scope: Scope, now: datetime) -> str:
    return (
        f"/api/public/training-media/{file_id}?t={issue(file_id, scope=scope, now=now)}"
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
