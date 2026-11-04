"""Tryb i dane dostępowe EBI24 (``EBI24_MODE`` i pozostałe ``EBI24_*``).

Tryby: ``off`` — nic nie wychodzi (domyślnie), ``uat`` — ``test-api.ebi24.pl``,
``prod`` — ``api.ebi24.pl``. Brak któregoś z czterech pól dostępowych albo klucz
komunikacji inny niż 32 bajty w base64 = integracja wyłączona z powodem.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from typing import Optional

from app.core.config import settings

MODES = ("off", "uat", "prod")
API_URLS = {
    "uat": "https://test-api.ebi24.pl/system/api/v1/",
    "prod": "https://api.ebi24.pl/system/api/v1/",
}
#: AES-256 w ``X-EBI24-CREDENTIALS`` wymaga klucza 32-bajtowego.
COMMUNICATION_KEY_BYTES = 32


def _decode_key(raw: str) -> Optional[bytes]:
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return None
    return key if len(key) == COMMUNICATION_KEY_BYTES else None


@dataclass(frozen=True)
class Ebi24Config:
    mode: str
    user_uuid: str
    account_uuid: str
    #: Sekrety — poza ``repr``, żeby nie trafiły do logów przy wypisaniu obiektu.
    communication_key: str = field(repr=False)
    secret_phrase: str = field(repr=False)

    @property
    def disabled_reason(self) -> Optional[str]:
        if self.mode not in API_URLS:
            return "mode_off"
        if not self.user_uuid:
            return "missing_user_uuid"
        if not self.account_uuid:
            return "missing_account_uuid"
        if not self.communication_key:
            return "missing_communication_key"
        if not self.secret_phrase:
            return "missing_secret_phrase"
        if _decode_key(self.communication_key) is None:
            return "invalid_communication_key"
        return None

    @property
    def enabled(self) -> bool:
        return self.disabled_reason is None

    @property
    def api_url(self) -> Optional[str]:
        return API_URLS.get(self.mode)

    @property
    def key_bytes(self) -> bytes:
        key = _decode_key(self.communication_key)
        if key is None:
            raise ValueError("invalid_communication_key")
        return key


def load_config() -> Ebi24Config:
    mode = str(settings.EBI24_MODE or "off").strip().lower()
    return Ebi24Config(
        mode=mode if mode in MODES else "off",
        user_uuid=settings.EBI24_USER_UUID.strip(),
        account_uuid=settings.EBI24_ACCOUNT_UUID.strip(),
        communication_key=settings.EBI24_COMMUNICATION_KEY.strip(),
        secret_phrase=settings.EBI24_SECRET_PHRASE.strip(),
    )
