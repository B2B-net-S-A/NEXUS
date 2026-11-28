"""ALTCHA na anonimowych formularzach zgłoszeń — ścieżki odmowy bez bazy.

Powtórkę (ten sam payload drugi raz) przy prawdziwej bazie sprawdza
``test_public_apply_protection.py``; tutaj ``_spend`` jest podmieniony.
Reguła: ``docs/claude/podstawy/skan-plikow-i-altcha.md``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.services import altcha

AFTER_GRACE = altcha.MISSING_ALLOWED_UNTIL.timestamp() + 60


@pytest.fixture(autouse=True)
def _required(monkeypatch):
    monkeypatch.setattr(settings, "ALTCHA_REQUIRED", True)
    monkeypatch.setattr(settings, "ALTCHA_HMAC_KEY", "")
    # Mała trudność, żeby rozwiązanie w teście trwało milisekundy.
    monkeypatch.setattr(settings, "ALTCHA_MAX_NUMBER", 500)


def solve(challenge: dict) -> str:
    """To samo, co liczy przeglądarka (``frontend/src/lib/altcha.ts``)."""
    for number in range(challenge["maxnumber"] + 1):
        digest = hashlib.sha256(f"{challenge['salt']}{number}".encode()).hexdigest()
        if digest == challenge["challenge"]:
            break
    else:  # pragma: no cover
        raise AssertionError("brak rozwiązania")
    return encode({**challenge, "number": number})


def encode(data: dict) -> str:
    fields = ("algorithm", "challenge", "number", "salt", "signature")
    return base64.b64encode(
        json.dumps({k: data[k] for k in fields if k in data}).encode()
    ).decode()


class _Spent:
    def __init__(self) -> None:
        self.seen: set[str] = set()

    async def __call__(self, db, challenge: str, expires: int) -> bool:
        if challenge in self.seen:
            return False
        self.seen.add(challenge)
        return True


@pytest.fixture
def spent(monkeypatch):
    store = _Spent()
    monkeypatch.setattr(altcha, "_spend", store)
    return store


async def _verify(payload, now=AFTER_GRACE):
    await altcha.verify(None, payload, form="career", now=now)


def _reason_of(caplog) -> str:
    (record,) = [
        r for r in caplog.records if getattr(r, "event_kind", None) == "altcha"
    ]
    return getattr(record, "reason", record.altcha_outcome)


@pytest.mark.asyncio
async def test_solved_challenge_is_accepted_once(spent):
    payload = solve(altcha.create_challenge(now=AFTER_GRACE - 10))
    await _verify(payload)
    with pytest.raises(HTTPException) as exc:
        await _verify(payload)
    assert exc.value.status_code == 400
    assert exc.value.detail == altcha.MSG_FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, "", "   "])
async def test_missing_solution_is_rejected_after_grace(spent, caplog, payload):
    with pytest.raises(HTTPException) as exc:
        await _verify(payload)
    assert exc.value.status_code == 400
    assert _reason_of(caplog) == "missing"


@pytest.mark.asyncio
async def test_missing_solution_passes_during_rollout_grace(spent, caplog):
    caplog.set_level(logging.INFO)
    before = altcha.MISSING_ALLOWED_UNTIL.timestamp() - 60
    await _verify(None, now=before)
    assert _reason_of(caplog) == "missing_allowed"


@pytest.mark.asyncio
async def test_bad_solution_is_rejected_even_during_grace(spent, caplog):
    before = altcha.MISSING_ALLOWED_UNTIL.timestamp() - 60
    challenge = altcha.create_challenge(now=before)
    payload = json.loads(base64.b64decode(solve(challenge)))
    payload["number"] += 1
    with pytest.raises(HTTPException):
        await _verify(encode(payload), now=before)
    assert _reason_of(caplog) == "bad_solution"


@pytest.mark.asyncio
async def test_forged_signature_is_rejected(spent, caplog):
    """Bot liczy własną zagadkę bez naszego klucza."""
    salt = f"abc?expires={int(AFTER_GRACE) + 600}"
    challenge = hashlib.sha256(f"{salt}7".encode()).hexdigest()
    forged = hmac.new(
        b"zgadniety-klucz", challenge.encode(), hashlib.sha256
    ).hexdigest()
    payload = encode(
        {
            "algorithm": "SHA-256",
            "challenge": challenge,
            "number": 7,
            "salt": salt,
            "signature": forged,
        }
    )
    with pytest.raises(HTTPException):
        await _verify(payload)
    assert _reason_of(caplog) == "bad_signature"


@pytest.mark.asyncio
async def test_tampered_expiry_breaks_the_solution(spent, caplog):
    """Przedłużenie ważności w soli zmienia skrót, więc rozwiązanie przestaje pasować."""
    challenge = altcha.create_challenge(now=AFTER_GRACE - 4000)
    data = json.loads(base64.b64decode(solve(challenge)))
    random_part = data["salt"].split("?")[0]
    data["salt"] = f"{random_part}?expires={int(AFTER_GRACE) + 3600}"
    with pytest.raises(HTTPException):
        await _verify(encode(data))
    assert _reason_of(caplog) == "bad_solution"


@pytest.mark.asyncio
async def test_expired_challenge_is_rejected(spent, caplog):
    issued = AFTER_GRACE - settings.ALTCHA_TTL_SECONDS - 5
    payload = solve(altcha.create_challenge(now=issued))
    with pytest.raises(HTTPException):
        await _verify(payload)
    assert _reason_of(caplog) == "expired"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        "nie-base64!!",
        base64.b64encode(b"[1,2]").decode(),
        base64.b64encode(b"{}").decode(),
        "A" * (altcha.MAX_PAYLOAD_CHARS + 1),
        # Przegląd bezpieczeństwa 28.11: głęboko zagnieżdżony JSON pod limitem
        # długości dawał RecursionError (500) zamiast 400.
        base64.b64encode(b"[" * 1400).decode(),
    ],
)
async def test_malformed_payload_is_rejected(spent, caplog, payload):
    with pytest.raises(HTTPException):
        await _verify(payload)
    assert _reason_of(caplog) == "malformed"


@pytest.mark.asyncio
async def test_boolean_number_is_malformed(spent, caplog):
    challenge = altcha.create_challenge(now=AFTER_GRACE - 10)
    data = json.loads(base64.b64decode(solve(challenge)))
    data["number"] = True
    with pytest.raises(HTTPException):
        await _verify(encode(data))
    assert _reason_of(caplog) == "malformed"


@pytest.mark.asyncio
async def test_other_algorithm_is_rejected(spent, caplog):
    challenge = altcha.create_challenge(now=AFTER_GRACE - 10)
    data = json.loads(base64.b64decode(solve(challenge)))
    data["algorithm"] = "SHA-1"
    with pytest.raises(HTTPException):
        await _verify(encode(data))
    assert _reason_of(caplog) == "algorithm"


@pytest.mark.asyncio
async def test_own_key_from_env_replaces_derived_key(spent, monkeypatch):
    payload = solve(altcha.create_challenge(now=AFTER_GRACE - 10))
    monkeypatch.setattr(settings, "ALTCHA_HMAC_KEY", "nowy-sekret-z-coolify")
    with pytest.raises(HTTPException):
        await _verify(payload)


@pytest.mark.asyncio
async def test_kill_switch_skips_the_gate(spent, monkeypatch):
    monkeypatch.setattr(settings, "ALTCHA_REQUIRED", False)
    await _verify(None)
    await _verify("śmieci")


def test_challenge_shape_matches_altcha_protocol():
    challenge = altcha.create_challenge(now=time.time())
    assert set(challenge) == {
        "algorithm",
        "challenge",
        "maxnumber",
        "salt",
        "signature",
    }
    assert challenge["algorithm"] == "SHA-256"
    assert "?expires=" in challenge["salt"]
    assert len(challenge["signature"]) == 64
    # Klucz wyprowadzony z SECRET_KEY nie jest samym SECRET_KEY.
    assert altcha._key() != settings.SECRET_KEY.encode()
