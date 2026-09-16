"""Panel pracodawcy RocketJobs / JustJoinIT — logowanie i API bez przeglądarki.

Port ``rocketjobs_client.py`` ze scrapera na Macu, ale bez Playwrighta:
panel to Next.js z NextAuth, więc logowanie to trzy requesty HTTP
(``/api/auth/csrf`` → ``/api/auth/callback/credentials`` → ``/api/auth/session``),
a dalej to samo JSON API, którego używa frontend panelu (``employer-api``,
nagłówek ``x-api-version: 3`` + ``Authorization: Bearer <accessToken>``).
Spike 2026-09-16: działa z Maca; z serwera sprawdzane przy pierwszym runie
(kill-switch ``JJIT_ENABLED``).

Kształty odpowiedzi (odkryte w ``--discover`` scrapera):
- ogłoszenia: ``{"items": [...], "hasNextPage": bool, ...}``; pole ``state``
  ∈ published|expired|deleted, ``jobBoard`` ∈ justjoinit|rocketjobs,
- aplikacje: kanban ``{"columns": [{"key", "name", "applications": [...]}]}``;
  aplikacja ma ``id``, ``candidateName``, ``candidateEmail``, ``city``,
  ``hasCv``, ``isAnonymized``, ``deletedAt``, ``createdAt``,
- ``appliedFrom`` MUSI być pełnym ISO (sama data daje HTTP 500),
- CV: plik z ``content-disposition``; brak CV → 404.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import unquote

import httpx

logger = logging.getLogger(__name__)

PANEL_URL = "https://rocketjobs.com/panel"
API_BASE = f"{PANEL_URL}/api/employer-api"
SESSION_URL = f"{PANEL_URL}/api/auth/session"
CSRF_URL = f"{PANEL_URL}/api/auth/csrf"
CALLBACK_URL = f"{PANEL_URL}/api/auth/callback/credentials"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) nexus-jjit-import/1.0"
TOKEN_REFRESH_MARGIN_SEC = 120


class PanelAuthError(Exception):
    """Logowanie nie powiodło się albo sesja wygasła."""


@dataclass(frozen=True)
class CvFile:
    data: bytes
    filename: str
    mime: str

    @property
    def size(self) -> int:
        return len(self.data)


def to_iso_timestamp(value: str) -> str:
    """'2026-09-15' → '2026-09-15T00:00:00Z'; pełny ISO zostaje (Z zamiast +00:00)."""
    v = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return f"{v}T00:00:00Z"
    if v.endswith("+00:00"):
        v = v[:-6] + "Z"
    if "T" in v and not v.endswith("Z") and "+" not in v:
        v = v.split(".")[0] + "Z"
    return v


def flatten_kanban(data: Any) -> list[dict]:
    """columns[].applications[] → płaska lista z ``statusKey``/``statusName``."""
    if isinstance(data, dict) and isinstance(data.get("columns"), list):
        flat: list[dict] = []
        for col in data["columns"]:
            for app in col.get("applications") or []:
                flat.append(
                    {
                        **app,
                        "statusKey": col.get("key", ""),
                        "statusName": col.get("name", ""),
                    }
                )
        return flat
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data", "results", "applications"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def application_skip_reason(app: dict) -> Optional[str]:
    if app.get("deletedAt"):
        return "deleted"
    if app.get("isAnonymized"):
        return "anonymized"
    if app.get("hasCv") is False:
        return "no_cv"
    return None


def split_name(full_name: str) -> tuple[str, str]:
    parts = (full_name or "").strip().split(" ", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def filename_from_disposition(disposition: str) -> str:
    m = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.IGNORECASE)
    if m:
        return unquote(m.group(1)).strip().strip('"')
    m = re.search(r'filename="?([^";]+)"?', disposition, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def normalize_mime(mime: str, filename: str, body: bytes) -> str:
    if body[:5] == b"%PDF-" or filename.lower().endswith(".pdf"):
        return "application/pdf"
    if filename.lower().endswith(".docx") or (
        body[:2] == b"PK" and mime != "application/zip"
    ):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if filename.lower().endswith(".doc") or body[:4] == b"\xd0\xcf\x11\xe0":
        return "application/msword"
    return mime


class PanelClient:
    """Jedna sesja HTTP = jedno logowanie; token odświeżany z sesji NextAuth."""

    def __init__(self, email: str, password: str, *, timeout: float = 45.0) -> None:
        self._email = email
        self._password = password
        self._http = httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout,
            headers={"user-agent": USER_AGENT},
        )
        self._token: Optional[str] = None
        self._token_expires_at = 0.0

    async def __aenter__(self) -> "PanelClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._http.aclose()

    # ── auth ────────────────────────────────────────────────────────────

    async def login(self) -> None:
        resp = await self._http.get(CSRF_URL)
        if resp.status_code != 200:
            raise PanelAuthError(f"csrf HTTP {resp.status_code}")
        csrf = (resp.json() or {}).get("csrfToken")
        if not csrf:
            raise PanelAuthError("brak csrfToken")
        resp = await self._http.post(
            CALLBACK_URL,
            data={
                "csrfToken": csrf,
                "email": self._email,
                "password": self._password,
                "callbackUrl": f"{PANEL_URL}/ogloszenia",
                "json": "true",
            },
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        # NextAuth odpowiada 302 zarówno na sukces, jak i na błąd (wtedy
        # Location zawiera ?error=...). Prawdę mówi dopiero /session.
        location = resp.headers.get("location", "")
        if resp.status_code not in (200, 302) or "error=" in location:
            raise PanelAuthError(f"callback HTTP {resp.status_code} {location[:120]}")
        if not await self._refresh_token():
            raise PanelAuthError("po logowaniu sesja nie ma accessToken (złe hasło?)")

    async def _refresh_token(self) -> bool:
        resp = await self._http.get(SESSION_URL, headers={"accept": "application/json"})
        if resp.status_code != 200:
            return False
        data = resp.json() or {}
        token = data.get("accessToken")
        if not token:
            return False
        expires_ms = data.get("accessTokenExpiresAt")
        self._token = token
        self._token_expires_at = (
            expires_ms / 1000.0
            if isinstance(expires_ms, (int, float))
            else time.time() + 900
        )
        return True

    async def _headers(self, *, json_accept: bool = True) -> dict:
        if (
            not self._token
            or time.time() > self._token_expires_at - TOKEN_REFRESH_MARGIN_SEC
        ):
            if not await self._refresh_token():
                raise PanelAuthError("sesja wygasła — brak accessToken")
        headers = {"x-api-version": "3", "authorization": f"Bearer {self._token}"}
        if json_accept:
            headers["accept"] = "application/json"
        return headers

    async def _get_json(self, path: str) -> Any:
        resp = await self._http.get(f"{API_BASE}{path}", headers=await self._headers())
        if resp.status_code in (401, 403):
            raise PanelAuthError(f"HTTP {resp.status_code} dla {path}")
        if resp.status_code >= 400:
            raise RuntimeError(
                f"panel API HTTP {resp.status_code} dla {path}: {resp.text[:200]}"
            )
        return resp.json()

    # ── API ─────────────────────────────────────────────────────────────

    async def list_job_ads(
        self, state: str = "published", page_size: int = 50
    ) -> list[dict]:
        items: list[dict] = []
        page = 1
        while True:
            data = await self._get_json(
                f"/organization-units/me/job-advertisements?pageNumber={page}&pageSize={page_size}"
                f"&state={state}&order=desc&orderBy=createdAt"
            )
            batch = data.get("items") if isinstance(data, dict) else data
            batch = batch or []
            items.extend(batch)
            if not batch or not (isinstance(data, dict) and data.get("hasNextPage")):
                break
            page += 1
        return items

    async def list_applications(
        self, job_ad_id: str, applied_from: Optional[str] = None
    ) -> list[dict]:
        query = f"?appliedFrom={to_iso_timestamp(applied_from)}" if applied_from else ""
        data = await self._get_json(
            f"/organization-units/me/recruitment/job-advertisements/{job_ad_id}/applications{query}"
        )
        return flatten_kanban(data)

    async def download_cv(self, application_id: str) -> Optional[CvFile]:
        resp = await self._http.get(
            f"{API_BASE}/organization-units/me/recruitment/applications/{application_id}/cv",
            headers=await self._headers(json_accept=False),
            timeout=90.0,
        )
        if resp.status_code in (401, 403):
            raise PanelAuthError(f"HTTP {resp.status_code} przy pobieraniu CV")
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise RuntimeError(f"CV HTTP {resp.status_code}: {resp.text[:120]}")
        body = resp.content
        mime = (
            resp.headers.get("content-type", "application/octet-stream")
            .split(";")[0]
            .strip()
        )
        filename = filename_from_disposition(
            resp.headers.get("content-disposition", "")
        )
        if not filename:
            ext = ".pdf" if body[:5] == b"%PDF-" else ".bin"
            filename = f"cv_{application_id}{ext}"
        return CvFile(
            data=body, filename=filename, mime=normalize_mime(mime, filename, body)
        )
