"""Traffit — zapis kandydata z CV (szukaj po e-mail, utwórz, wgraj plik).

Istniejący ``services.traffit.client`` jest czytelnikiem (import Traffit →
NEXUS, tylko GET z paginacją). Tu potrzebujemy trzech zapisów, dokładnie
tych, które robi scraper na Macu (``traffit_pipeline.py``): wyszukanie po
e-mailu (``X-Request-Filter``), ``POST /employees/`` i ``POST
/employees/{id}/files/`` (multipart, ``dictionary_file_type=CV``).
Poświadczenia: ``JJIT_TRAFFIT_CLIENT_ID/SECRET`` (klient ze scope ``employee``,
ten sam co scraper) z fallbackiem na ``TRAFFIT_CLIENT_ID/SECRET`` importera;
tenant z ``TRAFFIT_TENANT`` (domyślnie ``b2bnetwork``).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class TraffitWriteError(Exception):
    pass


class TraffitWriter:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http
        self._token: Optional[str] = None
        self._token_expiry = 0.0
        self.tenant = (
            os.environ.get("TRAFFIT_TENANT", "b2bnetwork").strip() or "b2bnetwork"
        )
        self.client_id = (
            os.environ.get("JJIT_TRAFFIT_CLIENT_ID")
            or os.environ.get("TRAFFIT_CLIENT_ID")
            or ""
        ).strip()
        self.client_secret = (
            os.environ.get("JJIT_TRAFFIT_CLIENT_SECRET")
            or os.environ.get("TRAFFIT_CLIENT_SECRET")
            or ""
        ).strip()

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def base(self) -> str:
        return f"https://{self.tenant}.traffit.com"

    async def _token_value(self) -> str:
        if self._token and time.time() < self._token_expiry:
            return self._token
        resp = await self._http.post(
            f"{self.base}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "employee",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            raise TraffitWriteError(
                f"Traffit OAuth {resp.status_code}: {resp.text[:150]}"
            )
        data = resp.json()
        if "access_token" not in data:
            raise TraffitWriteError("Traffit OAuth: brak access_token")
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3600)) - 60
        return self._token

    async def search_by_email(self, email: str) -> Optional[dict]:
        if not email:
            return None
        try:
            token = await self._token_value()
            resp = await self._http.get(
                f"{self.base}/api/integration/v2/employees/",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "X-Request-Filter": json.dumps(
                        {"email": {"value": email, "comparison": "="}}
                    ),
                    "X-Request-Page-Size": "1",
                },
                timeout=15,
            )
            data = resp.json()
            if isinstance(data, list) and data:
                return data[0]
        except Exception as e:  # noqa: BLE001 - dedupe best-effort jak w scraperze
            logger.warning("traffit search error: %s", e)
        return None

    async def create_candidate(self, payload: dict) -> dict[str, Any]:
        token = await self._token_value()
        resp = await self._http.post(
            f"{self.base}/api/integration/v2/employees/",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            data = {"error": f"Non-JSON response: {resp.text[:200]}"}
        return {"status": resp.status_code, "data": data}

    async def upload_cv(
        self, candidate_id: int, data: bytes, filename: str, mime: str
    ) -> None:
        token = await self._token_value()
        resp = await self._http.post(
            f"{self.base}/api/integration/v2/employees/{candidate_id}/files/",
            headers={"Authorization": f"Bearer {token}"},
            files={"file[file]": (filename, data, mime)},
            data={"dictionary_file_type": "CV", "file[isPublic]": "1"},
            timeout=60,
        )
        if resp.status_code not in (200, 201):
            raise TraffitWriteError(
                f"CV upload HTTP {resp.status_code}: {resp.text[:150]}"
            )
