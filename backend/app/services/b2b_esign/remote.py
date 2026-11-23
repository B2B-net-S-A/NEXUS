"""Sesje zdalnego podpisu przez API CSC (E1, 0757) — start, powrót, stan.

Sesja wiąże jedno zatwierdzenie u dostawcy z wnioskami NEXUSA:

* ``state`` OAuth jest losowy, w bazie tylko jego skrót SHA-256; powrót
  z innym ``state``, po ``SESSION_MINUTES`` minutach albo drugi raz z tym
  samym — odmowa, wniosek bez zmian;
* kontraktor wraca na ``/sign/b2b/{token}``, a w bazie jest tylko skrót
  tokenu linku, więc token leży przy sesji zaszyfrowany kluczem z ``state``
  (zrzut bazy go nie odda) i znika przy powrocie albo po czasie sesji;
* kod autoryzacji i token dostępu dostawcy żyją tylko w pamięci zadania,
  które podpisuje; ``code_verifier`` (PKCE) kasuje się po użyciu.

Samo podpisanie i przyjęcie plików (te same bramki co wgranie z dysku) robi
warstwa tras (``api/b2b_esign.py``), bo po podpisie idą tam dzwonki, maile
i „Dokumenty do startu”.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.b2b_esign_remote_session import B2BEsignRemoteSession
from app.services.b2b_esign import csc

SESSION_MINUTES = 15
#: Podpis trwający dłużej (np. restart procesu w trakcie) = „nie udało się”.
SIGNING_STALE = timedelta(minutes=30)

OPEN_STATES = ("waiting_for_user", "signing")

MSG_OFF = (
    "Podpis u dostawcy nie jest teraz dostępny. Pobierz plik i podpisz go "
    "podpisem kwalifikowanym jak dotąd."
)
MSG_CANCELLED = (
    "Podpis u dostawcy został przerwany. Nic nie zostało podpisane, możesz "
    "spróbować jeszcze raz."
)
MSG_TIMEOUT = (
    "Czas na potwierdzenie u dostawcy minął. Nic nie zostało podpisane, "
    "zacznij jeszcze raz."
)
MSG_STATE = "Ten powrót od dostawcy podpisu jest nieważny albo został już użyty."
MSG_STALE = (
    "Podpis u dostawcy trwał za długo i został przerwany. Sprawdź stan "
    "dokumentów i spróbuj jeszcze raz."
)
MSG_SESSION = "Nie ma takiej sesji podpisu."
MSG_FAILED = (
    "Nie udało się przyjąć podpisanych plików. Nic nie zostało zapisane, "
    "spróbuj jeszcze raz albo pobierz plik i podpisz go jak dotąd."
)


@dataclass(frozen=True)
class Availability:
    available: bool
    provider_label: Optional[str]


def availability() -> Availability:
    """Konfiguracja kompletna = droga istnieje; czy ten wniosek może z niej
    skorzystać, mówi wołający (stan wniosku)."""
    config = csc.load_config()
    if config is None:
        return Availability(False, None)
    return Availability(True, config.label)


def require_config() -> csc.CscConfig:
    config = csc.load_config()
    if config is None:
        raise HTTPException(status_code=404, detail=MSG_OFF)
    return config


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _seal_key(state: str) -> bytes:
    raw = hashlib.sha256(f"b2b-esign-remote:{state}".encode()).digest()
    return base64.urlsafe_b64encode(raw)


def seal(token: str, state: str) -> str:
    return Fernet(_seal_key(state)).encrypt(token.encode()).decode()


def unseal(sealed: str, state: str) -> str:
    try:
        return Fernet(_seal_key(state)).decrypt(sealed.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise HTTPException(status_code=400, detail=MSG_STATE) from exc


async def _close_open(
    db: AsyncSession,
    *,
    party: str,
    now: datetime,
    request_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> None:
    """Nowa sesja zamyka wcześniejsze, na które nikt jeszcze nie wrócił —
    zostaje jedna sesja w toku na wniosek kontraktora albo reprezentanta."""
    query = update(B2BEsignRemoteSession).where(
        B2BEsignRemoteSession.party == party,
        B2BEsignRemoteSession.status == "waiting_for_user",
    )
    if request_id is not None:
        query = query.where(B2BEsignRemoteSession.request_ids.contains([request_id]))
    if user_id is not None:
        query = query.where(B2BEsignRemoteSession.user_id == user_id)
    await db.execute(
        query.values(
            status="cancelled",
            message=MSG_CANCELLED,
            sealed_token=None,
            code_verifier=None,
            finished_at=now,
        )
    )


async def start(
    db: AsyncSession,
    *,
    party: str,
    request_ids: Sequence[int],
    document_ids: Sequence[int] = (),
    method: Optional[str] = None,
    user_id: Optional[int] = None,
    token: Optional[str] = None,
    redirect_uri: str,
    now: datetime,
) -> tuple[B2BEsignRemoteSession, str]:
    """Nowa sesja i adres strony dostawcy. Wołający sprawdził wnioski
    i uprawnienia; commit robi wołający. Awaria dostawcy = 503."""
    config = require_config()
    state = secrets.token_urlsafe(32)
    verifier, challenge = csc.pkce_pair()
    # Dostawca odpowiada do 30 s — bez otwartej transakcji (jak walidacja).
    await db.commit()
    try:
        async with csc.client_session() as http:
            oauth2 = await csc.oauth_base(http, config)
    except csc.CscError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
    if party == "contractor":
        await _close_open(db, party=party, request_id=request_ids[0], now=now)
    else:
        await _close_open(db, party=party, user_id=user_id, now=now)
    session = B2BEsignRemoteSession(
        public_id=secrets.token_urlsafe(16),
        party=party,
        request_ids=list(dict.fromkeys(request_ids)),
        document_ids=list(dict.fromkeys(document_ids)),
        method=method,
        user_id=user_id,
        state_hash=_digest(state),
        code_verifier=verifier,
        sealed_token=seal(token, state) if token else None,
        status="waiting_for_user",
        done_request_ids=[],
        expires_at=now + timedelta(minutes=SESSION_MINUTES),
    )
    db.add(session)
    await db.flush()
    url = csc.authorize_url(
        oauth2,
        config,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=challenge,
    )
    return session, url


@dataclass(frozen=True)
class Callback:
    session_id: int
    public_id: str
    # Token linku kontraktora do adresu powrotu (``None`` u reprezentanta).
    token: Optional[str]
    # Kod przyjęty — wołający uruchamia podpis.
    proceed: bool


async def accept_callback(
    db: AsyncSession,
    *,
    party: str,
    state: Optional[str],
    code: Optional[str],
    error: Optional[str],
    now: datetime,
    user_id: Optional[int] = None,
) -> Callback:
    """Powrót od dostawcy. Sesja działa raz: po tym wywołaniu nie czeka już
    na użytkownika, a token linku znika z bazy. Commit robi wołający."""
    if not state:
        raise HTTPException(status_code=400, detail=MSG_STATE)
    session = await db.scalar(
        select(B2BEsignRemoteSession)
        .where(B2BEsignRemoteSession.state_hash == _digest(state))
        .with_for_update()
    )
    if session is None or session.party != party:
        raise HTTPException(status_code=400, detail=MSG_STATE)
    if party == "company" and session.user_id != user_id:
        # Powrót z cudzej sesji (inne konto w przeglądarce) — jak nieznany state.
        raise HTTPException(status_code=400, detail=MSG_STATE)
    if session.status != "waiting_for_user":
        raise HTTPException(status_code=409, detail=MSG_STATE)
    token = unseal(session.sealed_token, state) if session.sealed_token else None
    if party == "contractor" and token is None:
        raise HTTPException(status_code=409, detail=MSG_STATE)
    session.sealed_token = None
    session.callback_at = now
    proceed = False
    if session.expires_at <= now:
        _finish(session, "cancelled", MSG_TIMEOUT, now)
    elif error or not code:
        _finish(session, "cancelled", MSG_CANCELLED, now)
    else:
        session.status = "signing"
        proceed = True
    await db.flush()
    return Callback(
        session_id=session.id,
        public_id=session.public_id,
        token=token,
        proceed=proceed,
    )


def _finish(
    session: B2BEsignRemoteSession, status: str, message: Optional[str], now: datetime
) -> None:
    session.status = status
    session.message = message
    session.finished_at = now
    session.code_verifier = None
    session.sealed_token = None


async def mark(
    db: AsyncSession,
    session_id: int,
    *,
    status: str,
    message: Optional[str],
    now: datetime,
    done_request_ids: Sequence[int] = (),
    evidence: Optional[dict] = None,
) -> None:
    """Wynik podpisu w sesji. Commit robi wołający."""
    session = await db.scalar(
        select(B2BEsignRemoteSession)
        .where(B2BEsignRemoteSession.id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if session is None:
        return
    _finish(session, status, message, now)
    session.done_request_ids = list(done_request_ids)
    if evidence is not None:
        session.evidence = evidence
    await db.flush()


async def load(
    db: AsyncSession,
    public_id: str,
    *,
    party: str,
    now: datetime,
    request_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> B2BEsignRemoteSession:
    """Sesja do odczytu stanu: tylko swojego wniosku (kontraktor) albo swoja
    (reprezentant). Sesja po czasie albo zawieszona w podpisie zamyka się tu,
    zanim pętla przypomnień do niej dojdzie."""
    session = await db.scalar(
        select(B2BEsignRemoteSession).where(
            B2BEsignRemoteSession.public_id == public_id
        )
    )
    if session is None or session.party != party:
        raise HTTPException(status_code=404, detail=MSG_SESSION)
    if request_id is not None and session.request_ids != [request_id]:
        raise HTTPException(status_code=404, detail=MSG_SESSION)
    if user_id is not None and session.user_id != user_id:
        raise HTTPException(status_code=404, detail=MSG_SESSION)
    if _close_if_stale(session, now):
        await db.commit()
    return session


def _close_if_stale(session: B2BEsignRemoteSession, now: datetime) -> bool:
    if session.status == "waiting_for_user" and session.expires_at <= now:
        _finish(session, "cancelled", MSG_TIMEOUT, now)
        return True
    if (
        session.status == "signing"
        and session.callback_at is not None
        and session.callback_at + SIGNING_STALE <= now
    ):
        _finish(session, "failed", MSG_STALE, now)
        return True
    return False


async def expire_sessions(db: AsyncSession, now: datetime) -> None:
    """Pętla przypomnień: sesje po czasie bez tokenu linku i bez PKCE."""
    await db.execute(
        update(B2BEsignRemoteSession)
        .where(
            B2BEsignRemoteSession.status == "waiting_for_user",
            B2BEsignRemoteSession.expires_at <= now,
        )
        .values(
            status="cancelled",
            message=MSG_TIMEOUT,
            sealed_token=None,
            code_verifier=None,
            finished_at=now,
        )
    )
    await db.execute(
        update(B2BEsignRemoteSession)
        .where(
            B2BEsignRemoteSession.status == "signing",
            B2BEsignRemoteSession.callback_at <= now - SIGNING_STALE,
        )
        .values(
            status="failed",
            message=MSG_STALE,
            code_verifier=None,
            finished_at=now,
        )
    )


@dataclass(frozen=True)
class Signed:
    files: list[bytes]
    evidence: dict


async def sign(
    *,
    code: str,
    code_verifier: Optional[str],
    redirect_uri: str,
    files: Sequence[tuple[str, bytes]],
    names: Sequence[str],
    method: Optional[str],
    description: str,
) -> Signed:
    """Kod → token → certyfikat osoby → jedno zatwierdzenie → podpisy.

    Rzuca ``csc.CscError`` z komunikatem dla człowieka."""
    config = csc.load_config()
    if config is None:
        raise csc.CscError(MSG_OFF)
    async with csc.client_session() as http:
        oauth2 = await csc.oauth_base(http, config)
        token = await csc.exchange_code(
            http,
            oauth2,
            config,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )
        credential = await csc.pick_credential(http, config, token=token, names=names)
        signed = await csc.sign_batch(http, credential, files, description=description)
    return Signed(
        files=signed,
        evidence={
            "provider": config.label,
            "method": method,
            "credential_id": credential.session_info.credential_id,
            "certificate_sha256": credential.certificate_sha256,
            "files": len(signed),
        },
    )
