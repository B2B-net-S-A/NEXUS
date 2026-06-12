"""AssemblyAI REST client — Polish call transcription via the EU endpoint.

Modeled on :mod:`app.services.cloudtalk.client` (same async context-manager +
retry/backoff shape). Auth is a single ``authorization`` header carrying the API
key (AssemblyAI does not use Bearer/Basic).

Used by the dialer webhook pipeline: a finished call recording is uploaded (or
referenced by URL), transcription is requested in Polish, and the resulting text
feeds :mod:`app.services.call_note_service`.

CRITICAL — EU AI Act art. 5(1)(f) forbids inferring emotions of candidates in a
recruitment context. This client therefore NEVER sets ``sentiment_analysis`` (or
any affect/emotion feature). Do not add it.

Reference: https://www.assemblyai.com/docs (v2 transcript + upload endpoints).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Terminal transcription states returned by GET /v2/transcript/{id}.
_STATUS_COMPLETED = "completed"
_STATUS_ERROR = "error"


class AssemblyAIError(Exception):
    """Any AssemblyAI integration failure (transport, auth, or job error)."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"AssemblyAI error {status}: {body[:200]}")
        self.status = status
        self.body = body


@dataclass
class AssemblyAIConfig:
    base_url: str
    api_key: str
    timeout_s: float = 60.0
    max_retries: int = 3

    @classmethod
    def from_settings(cls) -> "AssemblyAIConfig":
        """Read from app.core.config.settings. Raises if the key is missing.

        The caller guards with ``settings.OWN_DIALER_ENABLED`` before
        constructing — the killswitch belongs to the API/task layer.
        """
        if not settings.ASSEMBLYAI_API_KEY:
            raise RuntimeError(
                "ASSEMBLYAI_API_KEY must be set in environment (AssemblyAI "
                "dashboard → API key). Use the EU endpoint for candidate data."
            )
        return cls(
            base_url=settings.ASSEMBLYAI_BASE_URL.rstrip("/"),
            api_key=settings.ASSEMBLYAI_API_KEY,
        )


class AssemblyAIClient:
    """Async client. Use as ``async with AssemblyAIClient(config) as c:``."""

    def __init__(self, config: AssemblyAIConfig) -> None:
        self.config = config
        self._http: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "AssemblyAIClient":
        self._http = httpx.AsyncClient(timeout=self.config.timeout_s)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _headers(self) -> dict[str, str]:
        return {"authorization": self.config.api_key}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
        content: Optional[bytes] = None,
    ) -> httpx.Response:
        """Generic request with retry on 429/5xx. Returns the raw 2xx response."""
        assert self._http is not None
        url = path if path.startswith("http") else f"{self.config.base_url}{path}"

        last_resp: Optional[httpx.Response] = None
        for attempt in range(self.config.max_retries + 1):
            headers = self._headers()
            if json_body is not None:
                headers["content-type"] = "application/json"

            resp = await self._http.request(
                method, url, headers=headers, json=json_body, content=content
            )
            last_resp = resp

            if 200 <= resp.status_code < 300:
                return resp

            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self.config.max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "AssemblyAI %s %s HTTP %d — backoff %ds (attempt %d/%d)",
                        method,
                        path,
                        resp.status_code,
                        wait,
                        attempt + 1,
                        self.config.max_retries,
                    )
                    await asyncio.sleep(wait)
                    continue

            raise AssemblyAIError(resp.status_code, resp.text)

        assert last_resp is not None
        raise AssemblyAIError(last_resp.status_code, last_resp.text)

    async def upload(self, audio: bytes) -> str:
        """POST /v2/upload — upload raw audio bytes, return the private upload URL.

        Preferred over passing a public URL: the recording lives in our private
        Object Storage, so we hand AssemblyAI the bytes directly rather than
        exposing the file.
        """
        resp = await self._request("POST", "/v2/upload", content=audio)
        upload_url = resp.json().get("upload_url")
        if not upload_url:
            raise AssemblyAIError(resp.status_code, "upload returned no upload_url")
        return upload_url

    async def submit_transcription(
        self,
        audio_url: str,
        *,
        language_code: str = "pl",
        speaker_labels: bool = True,
        dual_channel: bool = False,
        webhook_url: Optional[str] = None,
    ) -> str:
        """POST /v2/transcript — request transcription, return the transcript id.

        ``dual_channel`` (set when the gateway records recruiter/candidate on
        separate channels) gives perfect speaker attribution; otherwise
        ``speaker_labels`` runs model-based diarization on the mixed mono audio.
        The two are mutually exclusive in the AssemblyAI API, so dual-channel
        wins when requested.

        NEVER pass ``sentiment_analysis`` — see the module docstring (AI Act).
        """
        body: dict[str, Any] = {
            "audio_url": audio_url,
            "language_code": language_code,
        }
        if dual_channel:
            body["dual_channel"] = True
        else:
            body["speaker_labels"] = speaker_labels
        if webhook_url:
            body["webhook_url"] = webhook_url

        resp = await self._request("POST", "/v2/transcript", json_body=body)
        transcript_id = resp.json().get("id")
        if not transcript_id:
            raise AssemblyAIError(resp.status_code, "transcript returned no id")
        return transcript_id

    async def get_transcription(self, transcript_id: str) -> dict[str, Any]:
        """GET /v2/transcript/{id} — current job state + text when completed."""
        resp = await self._request("GET", f"/v2/transcript/{transcript_id}")
        return resp.json()

    async def poll_transcription(
        self, transcript_id: str, *, interval_s: float = 3.0, max_wait_s: float = 600.0
    ) -> dict[str, Any]:
        """Poll until the job reaches a terminal state. Raises on error/timeout.

        Used by the reconciliation task. The live webhook path prefers
        AssemblyAI's own ``webhook_url`` callback over polling.
        """
        waited = 0.0
        while waited < max_wait_s:
            data = await self.get_transcription(transcript_id)
            status = data.get("status")
            if status == _STATUS_COMPLETED:
                return data
            if status == _STATUS_ERROR:
                raise AssemblyAIError(0, data.get("error", "transcription failed"))
            await asyncio.sleep(interval_s)
            waited += interval_s
        raise AssemblyAIError(0, f"transcription {transcript_id} timed out")
