"""ALTCHA (MIT) — zagadka proof-of-work zamiast CAPTCHY na anonimowych formularzach.

Decyzja Artura z 28.11.2026 (pakiet „Ochrona wejścia”): przeglądarka kandydata
liczy SHA-256, aż trafi liczbę z wyzwania; bez ciasteczek, bez zewnętrznego
skryptu i bez danych osoby, więc bez zgody RODO. Reguła:
``docs/claude/podstawy/skan-plikow-i-altcha.md``.

Format zgodny z protokołem ALTCHA v1 (własna implementacja HMAC, bez
zależności):

* wyzwanie: ``salt`` = losowe 12 bajtów + ``?expires=<unix>``, ``challenge`` =
  ``sha256(salt + str(number))``, ``signature`` = ``HMAC-SHA256(klucz, challenge)``;
* rozwiązanie z przeglądarki: base64 JSON-a ``{algorithm, challenge, number,
  salt, signature}`` w polu formularza ``altcha``.

Powtórkę tego samego rozwiązania blokuje tabela ``altcha_spent_challenges``
(kilka procesów web nie dzieli pamięci). Zapis idzie w transakcji zgłoszenia:
zgłoszenie, które padło dalej (np. zły e-mail), nie zużywa zagadki.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import parse_qs

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.altcha_schema import TABLE_NAME

logger = logging.getLogger(__name__)

ALGORITHM = "SHA-256"
FIELD = "altcha"
MSG_FAILED = (
    "Nie udało się potwierdzić wysyłki formularza. "
    "Odśwież stronę i wyślij zgłoszenie ponownie."
)
# Karty kariery otwarte przed wdrożeniem 28.11 nie mają zagadki (strony dla osób
# z zewnątrz nie przeładowują się same). Do tej chwili brak rozwiązania
# przechodzi z wpisem w logu; złe rozwiązanie odpada zawsze.
MISSING_ALLOWED_UNTIL = datetime(2026, 12, 1, 7, 0, tzinfo=timezone.utc)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_PAYLOAD_CHARS = 2000


class AltchaRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _key() -> bytes:
    own = (settings.ALTCHA_HMAC_KEY or "").strip()
    if own:
        return own.encode("utf-8")
    # Klucz wyprowadzony: inny niż SECRET_KEY, więc podpis zagadki nie jest
    # podpisem JWT ani niczego innego.
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), b"nexus-altcha-v1", hashlib.sha256
    ).digest()


def _sign(challenge: str) -> str:
    return hmac.new(_key(), challenge.encode("utf-8"), hashlib.sha256).hexdigest()


def create_challenge(*, now: Optional[float] = None) -> dict[str, Any]:
    issued = time.time() if now is None else now
    expires = int(issued) + settings.ALTCHA_TTL_SECONDS
    salt = f"{secrets.token_hex(12)}?expires={expires}"
    number = secrets.randbelow(settings.ALTCHA_MAX_NUMBER + 1)
    challenge = hashlib.sha256(f"{salt}{number}".encode("utf-8")).hexdigest()
    return {
        "algorithm": ALGORITHM,
        "challenge": challenge,
        "maxnumber": settings.ALTCHA_MAX_NUMBER,
        "salt": salt,
        "signature": _sign(challenge),
    }


def _expires_of(salt: str) -> int:
    _, _, query = salt.partition("?")
    values = parse_qs(query).get("expires") or []
    if len(values) != 1 or not values[0].isdigit():
        raise AltchaRejected("malformed")
    return int(values[0])


def check_solution(payload: str, *, now: Optional[float] = None) -> tuple[str, int]:
    """Sprawdza podpis, rozwiązanie i termin; zwraca ``(challenge, expires)``.

    Nie dotyka bazy — powtórkę sprawdza ``verify``.
    """
    if len(payload) > MAX_PAYLOAD_CHARS:
        raise AltchaRejected("malformed")
    try:
        data = json.loads(base64.b64decode(payload, validate=True))
    # RecursionError: głęboko zagnieżdżony JSON pod limitem długości (na części
    # wersji Pythona dekoder C rzuca go zamiast JSONDecodeError).
    except (binascii.Error, ValueError, RecursionError):
        raise AltchaRejected("malformed") from None
    if not isinstance(data, dict):
        raise AltchaRejected("malformed")
    algorithm = data.get("algorithm")
    challenge = data.get("challenge")
    number = data.get("number")
    salt = data.get("salt")
    signature = data.get("signature")
    if (
        not isinstance(challenge, str)
        or not _HEX64.match(challenge)
        or not isinstance(salt, str)
        or len(salt) > 200
        or not isinstance(signature, str)
        or isinstance(number, bool)
        or not isinstance(number, int)
        or number < 0
    ):
        raise AltchaRejected("malformed")
    if algorithm != ALGORITHM:
        raise AltchaRejected("algorithm")
    if not hmac.compare_digest(_sign(challenge), signature):
        raise AltchaRejected("bad_signature")
    solved = hashlib.sha256(f"{salt}{number}".encode("utf-8")).hexdigest()
    if not hmac.compare_digest(solved, challenge):
        raise AltchaRejected("bad_solution")
    expires = _expires_of(salt)
    if expires < (time.time() if now is None else now):
        raise AltchaRejected("expired")
    return challenge, expires


async def _spend(db: AsyncSession, challenge: str, expires: int) -> bool:
    """``True`` = pierwsze użycie. Przy okazji kasuje wygasłe wpisy."""
    await db.execute(text(f"DELETE FROM {TABLE_NAME} WHERE expires_at < now()"))
    row = await db.execute(
        text(
            f"INSERT INTO {TABLE_NAME} (challenge, expires_at) "
            "VALUES (:challenge, :expires_at) "
            "ON CONFLICT (challenge) DO NOTHING RETURNING challenge"
        ),
        {
            "challenge": challenge,
            "expires_at": datetime.fromtimestamp(expires, tz=timezone.utc),
        },
    )
    return row.first() is not None


def _log(outcome: str, *, form: str, reason: Optional[str] = None) -> None:
    fields: dict[str, Any] = {
        "event_kind": "altcha",
        "altcha_outcome": outcome,
        "altcha_form": form,
    }
    if reason:
        fields["reason"] = reason
    level = logging.WARNING if outcome == "rejected" else logging.INFO
    logger.log(level, "altcha", extra=fields)


async def verify(
    db: AsyncSession,
    payload: Optional[str],
    *,
    form: str,
    now: Optional[float] = None,
) -> None:
    """Bramka formularza: złe, wygasłe albo powtórzone rozwiązanie = 400."""
    if not settings.ALTCHA_REQUIRED:
        return
    raw = (payload or "").strip()
    current = time.time() if now is None else now
    if not raw:
        if current < MISSING_ALLOWED_UNTIL.timestamp():
            _log("missing_allowed", form=form)
            return
        _log("rejected", form=form, reason="missing")
        raise HTTPException(status_code=400, detail=MSG_FAILED)
    try:
        challenge, expires = check_solution(raw, now=current)
    except AltchaRejected as exc:
        _log("rejected", form=form, reason=exc.reason)
        raise HTTPException(status_code=400, detail=MSG_FAILED) from None
    if not await _spend(db, challenge, expires):
        _log("rejected", form=form, reason="replayed")
        raise HTTPException(status_code=400, detail=MSG_FAILED)
    _log("accepted", form=form)
