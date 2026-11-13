"""Graph app-only dla szkoleń w Teams (0697): opcje spotkania, nagranie, obecność.

Ta sama rejestracja co prepy („NEXUS Teams Prep”, ``teams_prep_auth``). Nagranie
i obecność wymagają dwóch uprawnień aplikacji ponad to, co mają prepy:
``OnlineMeetingRecording.Read.All`` i ``OnlineMeetingArtifact.Read.All``, oraz
polityki dostępu aplikacji obejmującej skrzynkę organizatora (szkolenia@).

Funkcje nie dotykają bazy. Plik nagrania idzie strumieniem (1 GB+ nie mieści się
w pamięci procesu web, patrz ``bulk-job-in-backend-container-oom``).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Optional

import httpx
from starlette.concurrency import run_in_threadpool

from app.services.m365.graph_client import GRAPH_BASE, GraphRequestError
from app.services.m365.teams_prep_auth import acquire_teams_prep_token
from app.services.m365.teams_prep_graph import _client, _user

logger = logging.getLogger(__name__)

_CHUNK = 1024 * 1024


async def set_presenters(
    user_id: str, meeting_id: str, presenter_emails: list[str]
) -> str:
    """Prowadzący jako prezenter, reszta jako uczestnicy, bez poczekalni.

    Organizatorem jest skrzynka szkolenia@, której nikt nie obsługuje na żywo, więc
    poczekalnia zatrzymałaby ludzi bez nikogo, kto ich wpuści: ``lobbyBypassSettings``
    = wszyscy z linkiem. Link dostają tylko zapisani.

    Graph nie opisuje roli prezentera dla gościa spoza firmy (trener B2B). Gdy
    ``roleIsPresenter`` zostanie odrzucone, zostaje ``everyone`` — tak jak domyślne
    ustawienie spotkań w tenancie — i wynik mówi o tym wołającemu.
    """
    base = {
        "lobbyBypassSettings": {"scope": "everyone", "isDialInBypassEnabled": False},
        "allowMeetingChat": "enabled",
    }
    async with _client() as gc:
        url = f"{_user(user_id)}/onlineMeetings/{meeting_id}"
        if presenter_emails:
            try:
                await gc.patch(
                    url,
                    json={
                        **base,
                        "allowedPresenters": "roleIsPresenter",
                        "participants": {
                            "attendees": [
                                {"upn": email, "role": "presenter"}
                                for email in presenter_emails
                            ]
                        },
                    },
                )
                return "presenter"
            except GraphRequestError as exc:
                logger.warning(
                    "teams_training_graph: roleIsPresenter refused status=%s",
                    exc.status,
                )
        await gc.patch(url, json={**base, "allowedPresenters": "everyone"})
    return "everyone"


async def rehearsal_settings(user_id: str, meeting_id: str) -> None:
    """Próba techniczna (0698): bez nagrywania, bez poczekalni, każdy prezentuje.

    Polityka nagrywania automatycznego skrzynki szkolenia@ obejmuje każde jej
    spotkanie, więc próbę trzeba wyłączyć wprost."""

    async with _client() as gc:
        await gc.patch(
            f"{_user(user_id)}/onlineMeetings/{meeting_id}",
            json={
                "recordAutomatically": False,
                "allowedPresenters": "everyone",
                "lobbyBypassSettings": {
                    "scope": "everyone",
                    "isDialInBypassEnabled": False,
                },
            },
        )


@dataclass(frozen=True)
class RecordingRef:
    id: str
    created: Optional[str]
    content_url: Optional[str]


async def list_recordings(user_id: str, meeting_id: str) -> list[RecordingRef]:
    """Nagrania spotkania od najstarszego (Teams tnie nagranie co 4 h albo 1,5 GB)."""
    async with _client() as gc:
        data = await gc.get(f"{_user(user_id)}/onlineMeetings/{meeting_id}/recordings")
    refs = [
        RecordingRef(
            id=str(item["id"]),
            created=item.get("createdDateTime"),
            content_url=item.get("recordingContentUrl"),
        )
        for item in (data or {}).get("value") or []
        if item.get("id")
    ]
    return sorted(refs, key=lambda r: r.created or "")


async def stream_recording(
    user_id: str, meeting_id: str, recording_id: str
) -> AsyncIterator[bytes]:
    """Treść MP4 kawałkami; przekierowanie do magazynu Microsoft idzie bez tokenu."""
    token = await run_in_threadpool(acquire_teams_prep_token)
    if not token:
        raise GraphRequestError(401, "app-only token unavailable")
    url = (
        f"{GRAPH_BASE}{_user(user_id)}/onlineMeetings/{meeting_id}/recordings/"
        f"{recording_id}/content"
    )
    timeout = httpx.Timeout(60.0, read=300.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async with client.stream(
            "GET", url, headers={"Authorization": f"Bearer {token}"}
        ) as response:
            if response.status_code >= 400:
                await response.aread()
                raise GraphRequestError(response.status_code, response.text[:300])
            async for chunk in response.aiter_bytes(_CHUNK):
                yield chunk


@dataclass(frozen=True)
class AttendeeTime:
    name: str
    email: str
    seconds: int


async def attendance(user_id: str, meeting_id: str) -> Optional[list[AttendeeTime]]:
    """Najnowszy raport obecności; ``None`` = raportu jeszcze nie ma."""
    base = f"{_user(user_id)}/onlineMeetings/{meeting_id}/attendanceReports"
    async with _client() as gc:
        reports = (await gc.get(base) or {}).get("value") or []
        if not reports:
            return None
        latest = sorted(
            reports, key=lambda r: r.get("meetingEndDateTime") or "", reverse=True
        )[0]
        rows: list[AttendeeTime] = []
        async for page in gc.paginate(f"{base}/{latest['id']}/attendanceRecords"):
            for item in page.get("value") or []:
                identity = item.get("identity") or {}
                rows.append(
                    AttendeeTime(
                        name=str(identity.get("displayName") or ""),
                        email=str(item.get("emailAddress") or ""),
                        seconds=int(item.get("totalAttendanceInSeconds") or 0),
                    )
                )
    return rows
