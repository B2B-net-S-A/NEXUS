"""NEXUS z wnętrza NEXUS-a — kandydat z CV + auto-dopasowanie przez własne API.

Świadoma decyzja: job woła WŁASNE endpointy po pętli zwrotnej
(``JJIT_NEXUS_INTERNAL_URL``, domyślnie ``http://127.0.0.1:8000``) zamiast
wołać serwisy bezpośrednio. Powód: ``/candidates/from-cv`` (dedupe,
enrichment, embedding, przypisanie CC), ``/recommendations`` (scoring,
wykluczenia) i ``/proposals/bulk`` (eligibility, blacklisty, stage template)
to ~600 linii logiki w handlerach, a ten sam przepływ działa już z Maca
(``nexus_pipeline.py``). Jedna ścieżka = jedno zachowanie i rate-limity
egzekwowane tak samo. Jeden worker uvicorna obsługuje loopback bez zakleszczeń,
bo wszystko jest asynchroniczne.

Token: mintowany lokalnie dla klienta OAuth o nazwie ``JJIT_OAUTH_CLIENT_NAME``
(migracja 0311 — token działa jako user serwisowy klienta), bez sekretu.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from sqlalchemy import select

from app.services.auto_match_rules import is_good_match  # noqa: F401 — reguła wspólna z auto-matchem
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.oauth_client import OAuthClient
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

RECOMMENDATIONS_TOP_K = 50
RATE_LIMIT_RETRY_SEC = 65


class NexusClientError(Exception):
    pass


@dataclass
class MatchResult:
    candidate_id: Optional[int] = None
    action: str = ""  # created | existing | error
    error: str = ""
    cv_refresh: str = ""
    matched: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


async def _pick_oauth_client(db) -> OAuthClient:
    """Jedyny włączony klient OAuth o nazwie ``JJIT_OAUTH_CLIENT_NAME``.

    Runda 9 (R9-N9-11): nazwa klienta OAuth nie jest unikalna, a ``scalar``
    brał dowolny pierwszy wiersz — drugi klient o tej samej nazwie (np. kopia
    założona przez admina z innymi scope'ami albo innym użytkownikiem
    serwisowym) mógł po cichu przejąć tożsamość importu. Filtr: włączony,
    z użytkownikiem serwisowym; więcej niż jeden = odmowa.
    """
    rows = (
        (
            await db.execute(
                select(OAuthClient).where(
                    OAuthClient.name == settings.JJIT_OAUTH_CLIENT_NAME,
                    OAuthClient.enabled.is_(True),
                    OAuthClient.acting_user_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        raise NexusClientError(
            f"klient OAuth '{settings.JJIT_OAUTH_CLIENT_NAME}' nie istnieje / wyłączony / bez acting_user"
        )
    if len(rows) > 1:
        raise NexusClientError(
            f"klient OAuth '{settings.JJIT_OAUTH_CLIENT_NAME}' jest niejednoznaczny "
            f"({len(rows)} włączonych o tej nazwie) — zostaw jeden"
        )
    return rows[0]


async def mint_client_token() -> str:
    from app.api.oauth_token import _create_client_token

    async with AsyncSessionLocal() as db:
        client = await _pick_oauth_client(db)
        acting_user = await db.get(User, client.acting_user_id)
    # Runda 9 (R9-N9-1): token i tak zostałby odrzucony w ``deps`` — tu mówimy
    # od razu, DLACZEGO import nie ruszy, zamiast 401 na pierwszym żądaniu.
    if acting_user is None or not acting_user.is_active:
        raise NexusClientError("acting_user klienta OAuth jest nieaktywny")
    if acting_user.has_role(UserRole.admin):
        raise NexusClientError(
            "acting_user klienta OAuth ma rolę admina — integracja potrzebuje "
            "konta z rolą operacyjną"
        )
    scopes = [s for s in (client.scopes or []) if s.endswith(":write")] or list(
        client.scopes or []
    )
    return _create_client_token(client, scopes)


class NexusLoopbackClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http
        self._token: Optional[str] = None
        self.base = settings.JJIT_NEXUS_INTERNAL_URL.rstrip("/")

    async def _headers(self) -> dict:
        if not self._token:
            self._token = await mint_client_token()
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        for attempt in (1, 2):
            resp = await self._http.request(
                method, f"{self.base}{path}", headers=await self._headers(), **kwargs
            )
            if resp.status_code == 401 and attempt == 1:
                self._token = None
                continue
            if resp.status_code == 429 and attempt == 1:
                await asyncio.sleep(RATE_LIMIT_RETRY_SEC)
                continue
            return resp
        return resp

    async def create_from_cv(
        self, data: bytes, filename: str, mime: str
    ) -> tuple[int, str]:
        resp = await self._request(
            "POST",
            "/api/candidates/from-cv",
            files={"file": (filename, data, mime)},
            timeout=180,
        )
        if resp.status_code == 201:
            return int(resp.json()["candidate"]["id"]), "created"
        if resp.status_code == 409:
            body = resp.json()
            existing = body.get("existing_candidate_id") or (
                body.get("detail") or {}
            ).get("existing_candidate_id")
            if existing:
                return int(existing), "existing"
        raise NexusClientError(f"from-cv HTTP {resp.status_code}: {resp.text[:200]}")

    async def upload_cv(
        self, candidate_id: int, data: bytes, filename: str, mime: str
    ) -> str:
        resp = await self._request(
            "POST",
            f"/api/candidates/{candidate_id}/cv",
            files={"file": (filename, data, mime)},
            timeout=120,
        )
        return (
            "uploaded" if resp.status_code < 400 else f"error: HTTP {resp.status_code}"
        )

    async def add_source_event(self, candidate_id: int, note: str) -> None:
        try:
            await self._request(
                "POST",
                f"/api/candidates/{candidate_id}/sources",
                json={
                    "channel": "posting",
                    "utm_source": "jjit",
                    "utm_medium": "job_board",
                    "note": note[:500],
                },
                timeout=20,
            )
        except Exception as e:  # noqa: BLE001 - atrybucja best-effort
            logger.debug("source event error: %s", e)

    async def recommend(self, candidate_id: int) -> list[dict]:
        resp = await self._request(
            "GET",
            f"/api/candidates/{candidate_id}/recommendations",
            params={
                "only_open": "true",
                "top_k": RECOMMENDATIONS_TOP_K,
                "include_breakdown": "true",
            },
            timeout=90,
        )
        if resp.status_code != 200:
            raise NexusClientError(
                f"recommendations HTTP {resp.status_code}: {resp.text[:150]}"
            )
        out = []
        for m in resp.json().get("matches", []):
            job = m.get("job") or {}
            if not job.get("id"):
                continue
            breakdown = m.get("breakdown") or {}
            out.append(
                {
                    "job_id": int(job["id"]),
                    "title": job.get("title") or f"job {job['id']}",
                    "status": job.get("status") or "",
                    "score": float(m.get("total_score") or 0),
                    "matching_must": list(breakdown.get("matching_must") or []),
                    "gap_must": list(breakdown.get("gap_must") or []),
                }
            )
        return out

    async def add_to_job(
        self, job_id: int, candidate_id: int, rec: dict
    ) -> tuple[bool, str]:
        must_hit = list(rec.get("matching_must") or [])
        resp = await self._request(
            "POST",
            f"/api/jobs/{job_id}/proposals/bulk",
            json={
                "candidate_ids": [candidate_id],
                # 0399: bez notatki — wynik jedzie jako dane procesu
                # (plakietka „Auto-match 67/100 · JJIT” przy rekrutacji).
                "auto_match": {
                    "score": max(0.0, min(100.0, float(rec.get("score") or 0))),
                    "source": "jjit",
                    "must_hit": [str(m)[:80] for m in must_hit[:8]],
                    "must_total": len(must_hit) + len(rec.get("gap_must") or []),
                },
                "tags": ["auto-match", "jjit"],
                # Kandydaci z ogłoszeń lądują w „Ogłoszeniach" (etap `posting`,
                # migracja 0317), nie w „Nowi" — rekruter przenosi ręcznie.
                "initial_stage_legacy": "posting",
            },
            timeout=60,
        )
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}: {resp.text[:120]}"
        body = resp.json()
        if candidate_id in (body.get("added") or []):
            return True, ""
        for row in body.get("skipped") or []:
            if row.get("candidate_id") == candidate_id:
                return False, row.get("reason_label") or row.get("reason") or "skipped"
        return False, "not_added"

    async def push_candidate(
        self,
        data: bytes,
        filename: str,
        mime: str,
        *,
        candidate_name: str,
        offer_title: str,
        known_cv_sha: Optional[str],
    ) -> MatchResult:
        """from-cv → (CV dla istniejącego) → źródło → rekomendacje → proposals."""
        result = MatchResult()
        try:
            result.candidate_id, result.action = await self.create_from_cv(
                data, filename, mime
            )
        except Exception as e:  # noqa: BLE001
            return MatchResult(action="error", error=str(e)[:200])

        sha = hashlib.sha256(data).hexdigest()
        if result.action == "existing" and known_cv_sha != sha:
            result.cv_refresh = await self.upload_cv(
                result.candidate_id, data, filename, mime
            )

        note = f"Źródło: JustJoinIT / RocketJobs — oferta: {offer_title}"
        await self.add_source_event(result.candidate_id, note)

        try:
            recommendations = await self.recommend(result.candidate_id)
        except Exception as e:  # noqa: BLE001
            result.error = f"recommendations: {str(e)[:150]}"
            return result

        good = [
            r
            for r in recommendations
            if is_good_match(
                r,
                min_score=float(settings.JJIT_MATCH_MIN_SCORE),
                require_must=bool(settings.JJIT_REQUIRE_MUST_MATCH),
            )
        ]
        for rec in good:
            try:
                added, reason = await self.add_to_job(
                    rec["job_id"], result.candidate_id, rec
                )
            except Exception as e:  # noqa: BLE001
                added, reason = False, str(e)[:120]
            (result.matched if added else result.skipped).append(
                {**rec, "reason": reason}
            )
            await asyncio.sleep(0.5)
        return result
