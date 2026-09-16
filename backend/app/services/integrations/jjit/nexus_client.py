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

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.oauth_client import OAuthClient

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


def is_good_match(rec: dict, *, min_score: float, require_must: bool) -> bool:
    """Ta sama reguła co w scraperze: próg + published + ≥1 trafione must-have."""
    if rec["score"] < min_score or rec["status"] not in ("", "published"):
        return False
    if (
        require_must
        and (rec["gap_must"] or rec["matching_must"])
        and not rec["matching_must"]
    ):
        return False
    return True


async def mint_client_token() -> str:
    from app.api.oauth_token import _create_client_token

    async with AsyncSessionLocal() as db:
        client = await db.scalar(
            select(OAuthClient).where(
                OAuthClient.name == settings.JJIT_OAUTH_CLIENT_NAME
            )
        )
    if client is None or not client.enabled or client.acting_user_id is None:
        raise NexusClientError(
            f"klient OAuth '{settings.JJIT_OAUTH_CLIENT_NAME}' nie istnieje / wyłączony / bez acting_user"
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
        self, job_id: int, candidate_id: int, note: str
    ) -> tuple[bool, str]:
        resp = await self._request(
            "POST",
            f"/api/jobs/{job_id}/proposals/bulk",
            json={
                "candidate_ids": [candidate_id],
                "note": note[:2000],
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
            rec_note = (
                f"{note}\nAuto-match score: {rec['score']:.0f}/100 ({candidate_name})\n"
                f"Must-have trafione: {', '.join(rec['matching_must'][:8]) or '—'}"
            )
            try:
                added, reason = await self.add_to_job(
                    rec["job_id"], result.candidate_id, rec_note
                )
            except Exception as e:  # noqa: BLE001
                added, reason = False, str(e)[:120]
            (result.matched if added else result.skipped).append(
                {**rec, "reason": reason}
            )
            await asyncio.sleep(0.5)
        return result
