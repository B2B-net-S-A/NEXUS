"""Klient API Cloud Signature Consortium (CSC v1) — zdalny podpis kwalifikowany (E1).

Kierunek K1 Artura z 22.11.2026: NEXUS zostaje przy swoich ekranach, a od
kwalifikowanego dostawcy usług zaufania bierze tylko potwierdzenie tożsamości,
certyfikat (własny w chmurze albo jednorazowy) i podpis skrótu. Dostawca nie
jest wybrany (SIGNIUS, Certum, KIR), więc klient trzyma się samej specyfikacji
CSC i nie zna żadnego dostawcy z nazwy. Konfiguracja: ``B2B_ESIGN_CSC_*``
w ``app/core/config.py``; pusta = droga wyłączona.

Przebieg jednego zatwierdzenia:

1. ``POST /csc/v1/info`` — adres serwera OAuth (``oauth2``) dostawcy,
2. przekierowanie na ``{oauth2}/oauth2/authorize`` (kod autoryzacji, ``state``,
   PKCE S256), powrót do NEXUSA,
3. ``{oauth2}/oauth2/token`` — token dostępu (tylko w pamięci procesu),
4. ``credentials/list`` i ``credentials/info`` — certyfikat osoby,
5. ``credentials/authorize`` RAZ dla skrótów wszystkich plików (SCAL 2),
6. ``signatures/signHash`` RAZ dla całej paczki.

Podpis CMS i PAdES składa pyHanko (``CSCSigner`` z paczką skrótów): każdy plik
dostaje przyrostowy podpis dopisany na końcu zamrożonych bajtów, więc
``verdict.builds_on`` zachodzi jak przy pliku wgranym z dysku.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Sequence
from urllib.parse import urlencode

import aiohttp

from app.core.config import settings as app_config
from app.services.b2b_esign.verdict import name_matches

logger = logging.getLogger(__name__)

#: Domyślny zakres usługi ze specyfikacji CSC (lista i opis certyfikatów).
DEFAULT_SCOPE = "service"
#: Ile certyfikatów z ``credentials/list`` sprawdzamy, szukając osoby z umowy.
MAX_CREDENTIALS = 10
REQUEST_TIMEOUT_SECONDS = 30
#: Cała paczka (skróty, zatwierdzenie, podpisy) — potem przerwanie.
SIGN_TIMEOUT_SECONDS = 120

MSG_PROVIDER = (
    "Dostawca podpisu nie odpowiedział poprawnie. Nic nie zostało podpisane, "
    "spróbuj za kilka minut."
)
MSG_NO_CREDENTIAL = (
    "U dostawcy nie ma certyfikatu do podpisu. Dokończ zakładanie certyfikatu "
    "u dostawcy i spróbuj jeszcze raz."
)


def batch_problem(limit: int) -> str:
    return f"Dostawca podpisze najwyżej {limit} plików za jednym razem."


class CscError(Exception):
    """Awaria po stronie dostawcy. ``message`` idzie do człowieka, szczegóły
    (bez tokenów i bez podmiotu certyfikatu) do logu."""

    def __init__(self, message: str = MSG_PROVIDER) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class CscConfig:
    base_url: str
    client_id: str
    client_secret: str
    scopes: str
    label: str

    def endpoint(self, name: str) -> str:
        return f"{self.base_url}/csc/v1/{name}"


def load_config() -> CscConfig | None:
    """Konfiguracja z ``B2B_ESIGN_CSC_*``; brak któregoś pola = ``None``."""
    base = app_config.B2B_ESIGN_CSC_BASE_URL.strip().rstrip("/")
    client_id = app_config.B2B_ESIGN_CSC_CLIENT_ID.strip()
    secret = app_config.B2B_ESIGN_CSC_CLIENT_SECRET.strip()
    label = app_config.B2B_ESIGN_CSC_PROVIDER_LABEL.strip()
    if not (base and client_id and secret and label):
        return None
    scopes = " ".join(app_config.B2B_ESIGN_CSC_SCOPES.split()) or DEFAULT_SCOPE
    return CscConfig(
        base_url=base,
        client_id=client_id,
        client_secret=secret,
        scopes=scopes,
        label=label[:80],
    )


def client_session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    )


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge S256) — RFC 7636."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


async def _post_json(
    session: aiohttp.ClientSession,
    url: str,
    body: dict[str, Any],
    *,
    token: str | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with session.post(url, json=body, headers=headers) as response:
            if response.status >= 400:
                logger.warning(
                    "[b2b_esign.csc] %s odpowiedział %d",
                    _endpoint_name(url),
                    response.status,
                )
                raise CscError()
            data = await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.warning(
            "[b2b_esign.csc] %s nie odpowiedział: %s",
            _endpoint_name(url),
            type(exc).__name__,
        )
        raise CscError() from exc
    if not isinstance(data, dict):
        raise CscError()
    return data


def _endpoint_name(url: str) -> str:
    """Tylko nazwa końcówki do logu, bez adresu dostawcy i parametrów."""
    return "/".join(url.split("?", 1)[0].rstrip("/").split("/")[-2:])


async def oauth_base(session: aiohttp.ClientSession, config: CscConfig) -> str:
    """Adres serwera OAuth dostawcy z ``/csc/v1/info`` (pole ``oauth2``);
    bez niego — adres usługi."""
    data = await _post_json(session, config.endpoint("info"), {"lang": "pl-PL"})
    value = data.get("oauth2")
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        return value.rstrip("/")
    return config.base_url


def authorize_url(
    oauth2: str,
    config: CscConfig,
    *,
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": redirect_uri,
        "scope": config.scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "lang": "pl-PL",
    }
    return f"{oauth2}/oauth2/authorize?{urlencode(params)}"


async def exchange_code(
    session: aiohttp.ClientSession,
    oauth2: str,
    config: CscConfig,
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str | None,
) -> str:
    """Kod autoryzacji → token dostępu (RFC 6749, formularz). Token zostaje
    w pamięci tego zadania, do bazy nie trafia."""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "redirect_uri": redirect_uri,
    }
    if code_verifier:
        form["code_verifier"] = code_verifier
    url = f"{oauth2}/oauth2/token"
    try:
        async with session.post(url, data=form) as response:
            if response.status >= 400:
                logger.warning(
                    "[b2b_esign.csc] oauth2/token odpowiedział %d", response.status
                )
                raise CscError()
            data = await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.warning(
            "[b2b_esign.csc] wymiana kodu OAuth nie odpowiedziała: %s",
            type(exc).__name__,
        )
        raise CscError() from exc
    token = data.get("access_token") if isinstance(data, dict) else None
    if not isinstance(token, str) or not token:
        raise CscError()
    return token


@dataclass(frozen=True)
class Credential:
    session_info: Any  # pyhanko CSCServiceSessionInfo
    info: Any  # pyhanko CSCCredentialInfo

    @property
    def certificate_sha256(self) -> str:
        return hashlib.sha256(self.info.signing_cert.dump()).hexdigest()


async def pick_credential(
    session: aiohttp.ClientSession,
    config: CscConfig,
    *,
    token: str,
    names: Sequence[str],
) -> Credential:
    """Certyfikat osoby z umowy: pierwszy z ``credentials/list``, którego
    podmiot pasuje do jednego z nazwisk (``verdict.name_matches``); bez
    takiego — pierwszy z listy (``judge`` i tak sprawdzi nazwisko)."""
    from pyhanko.sign.general import SigningError
    from pyhanko.sign.signers.csc_signer import (
        CSCServiceSessionInfo,
        fetch_certs_in_csc_credential,
    )

    listed = await _post_json(
        session,
        config.endpoint("credentials/list"),
        {"maxResults": MAX_CREDENTIALS},
        token=token,
    )
    ids = [
        str(value)
        for value in (listed.get("credentialIDs") or [])[:MAX_CREDENTIALS]
        if isinstance(value, (str, int))
    ]
    if not ids:
        raise CscError(MSG_NO_CREDENTIAL)
    first: Credential | None = None
    for credential_id in ids:
        info = CSCServiceSessionInfo(
            service_url=config.base_url, credential_id=credential_id, oauth_token=token
        )
        try:
            details = await fetch_certs_in_csc_credential(
                session, info, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except (SigningError, asyncio.TimeoutError) as exc:
            logger.warning(
                "[b2b_esign.csc] opis certyfikatu nie odpowiedział: %s",
                type(exc).__name__,
            )
            continue
        found = Credential(session_info=info, info=details)
        subject = details.signing_cert.subject.human_friendly
        if any(name_matches(name, subject) for name in names if name):
            return found
        first = first or found
    if first is None:
        raise CscError()
    return first


def _authorization_manager(
    session: aiohttp.ClientSession, credential: Credential, description: str
) -> Any:
    from pyhanko.sign.signers.csc_signer import CSCAuthorizationManager

    class _HashAuthorization(CSCAuthorizationManager):
        """``credentials/authorize`` ze skrótami całej paczki — jedno
        zatwierdzenie na wszystkie pliki (SCAL 2 wiąże je ze skrótami)."""

        async def authorize_signature(self, hash_b64s: list[str]) -> Any:
            body = self.format_csc_auth_request(
                hash_b64s=hash_b64s, description=description[:500]
            )
            data = await _post_json(
                session,
                self.csc_session_info.endpoint_url("credentials/authorize"),
                body,
                token=self.csc_session_info.oauth_token,
            )
            return self.parse_csc_auth_response(data)

    return _HashAuthorization(credential.session_info, credential.info)


async def sign_batch(
    session: aiohttp.ClientSession,
    credential: Credential,
    files: Sequence[tuple[str, bytes]],
    *,
    description: str,
) -> list[bytes]:
    """Podpis PAdES wszystkich plików jednym zatwierdzeniem.

    ``files`` = (nazwa pola podpisu, zamrożone bajty). Każdy wynik zaczyna się
    bajtami wejścia (aktualizacja przyrostowa). Awaria któregokolwiek pliku
    przerywa całą paczkę — nic nie zostaje podpisane połowicznie."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers
    from pyhanko.sign.general import SigningError
    from pyhanko.sign.signers.csc_signer import CSCSigner

    if not files:
        return []
    if credential.info.max_batch_size < len(files):
        raise CscError(batch_problem(credential.info.max_batch_size))
    # Pliki czytane przed zatwierdzeniem: zepsuty PDF nie zostawia paczki
    # czekającej na skrót, który nigdy nie przyjdzie.
    try:
        writers = [
            (field, IncrementalPdfFileWriter(BytesIO(data), strict=False))
            for field, data in files
        ]
    except Exception as exc:  # noqa: BLE001 — pyHanko rzuca różne błędy odczytu
        logger.warning("[b2b_esign.csc] PDF nie do podpisu: %s", type(exc).__name__)
        raise CscError() from exc
    signer = CSCSigner(
        session,
        _authorization_manager(session, credential, description),
        batch_size=len(files),
        sign_timeout=REQUEST_TIMEOUT_SECONDS,
    )

    async def _one(field: str, writer: Any) -> bytes:
        meta = signers.PdfSignatureMetadata(
            field_name=field,
            md_algorithm="sha256",
            subfilter=fields.SigSeedSubFilter.PADES,
        )
        out = await signers.PdfSigner(meta, signer=signer).async_sign_pdf(
            writer, output=BytesIO()
        )
        return out.getvalue()

    tasks = [asyncio.create_task(_one(field, writer)) for field, writer in writers]
    try:
        return list(
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=SIGN_TIMEOUT_SECONDS)
        )
    except CscError:
        raise
    except (SigningError, asyncio.TimeoutError, aiohttp.ClientError) as exc:
        logger.warning("[b2b_esign.csc] podpis paczki: %s", type(exc).__name__)
        raise CscError() from exc
    finally:
        for task in tasks:
            task.cancel()
