"""Graph app-only dla prepów w Teams (0364): kalendarz organizatora i transkrypty.

Wszystkie wywołania idą przez ``AppGraphClient`` z tokenem OSOBNEJ rejestracji
(``teams_prep_auth``) — patrz tam, dlaczego nie ta od poczty zamówień. Ścieżki
są ``/users/{upn|oid}/...``: aplikacja działa w imieniu organizatora, który
nie musi mieć połączonego konta M365 w NEXUSIE (dziś ma je 2 z ~30 osób).

Funkcje nie dotykają bazy — wołający zapisuje wynik i decyduje, co jest
porażką, a co stanem („transkryptu jeszcze nie ma”).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

from app.services.m365.app_graph_client import AppGraphClient
from app.services.m365.graph_client import GraphRequestError
from app.services.m365.teams_prep_auth import acquire_teams_prep_token

logger = logging.getLogger(__name__)


def _client() -> AppGraphClient:
    return AppGraphClient(token_provider=acquire_teams_prep_token)


def _user(upn_or_oid: str) -> str:
    return f"/users/{quote(upn_or_oid, safe='@.')}"


@dataclass(frozen=True)
class CreatedPrepEvent:
    graph_event_id: str
    change_key: Optional[str]
    join_url: Optional[str]


async def create_event(upn: str, payload: dict) -> CreatedPrepEvent:
    """Wydarzenie z Teams w kalendarzu organizatora. Graph wysyła zaproszenia.

    ``payload`` buduje ``calendar._build_event_payload`` (ten sam kontrakt co
    ścieżka delegowana, z ``transactionId`` — ponowienie nie tworzy duplikatu).
    """
    async with _client() as gc:
        event = await gc.post(f"{_user(upn)}/events", json=payload)
    online = event.get("onlineMeeting") or {}
    return CreatedPrepEvent(
        graph_event_id=event["id"],
        change_key=event.get("changeKey"),
        join_url=online.get("joinUrl") if isinstance(online, dict) else None,
    )


async def update_event(upn: str, graph_event_id: str, payload: dict) -> Optional[str]:
    """PATCH wydarzenia w kalendarzu organizatora → nowy ``changeKey``."""
    async with _client() as gc:
        result = await gc.patch(f"{_user(upn)}/events/{graph_event_id}", json=payload)
    return result.get("changeKey") if isinstance(result, dict) else None


async def cancel_event(upn: str, graph_event_id: str, comment: str) -> str:
    """Odwołanie przez organizatora (uczestnicy dostają odwołanie).

    ``cancelled`` | ``gone`` (w Outlooku już go nie ma). Organizatorem jest
    zawsze skrzynka, w której aplikacja założyła wydarzenie, więc gałęzi
    „nie jesteś organizatorem” (DELETE) tu nie ma — 400/403 to błąd.
    """
    async with _client() as gc:
        try:
            await gc.post(
                f"{_user(upn)}/events/{graph_event_id}/cancel",
                json={"comment": comment},
                expect_json=False,
            )
        except GraphRequestError as exc:
            if exc.status == 404:
                return "gone"
            raise
    return "cancelled"


async def get_event(upn: str, graph_event_id: str) -> Optional[dict]:
    """Termin i stan wydarzenia z kalendarza organizatora (czas w UTC).

    Zwraca ``{"start", "end", "isCancelled", "join_url"}`` (czasy ze strefą).
    404 leci wyżej — wołający traktuje je jak odwołanie.
    """
    from app.services.m365.calendar import _parse_iso_utc

    async with _client() as gc:
        data = await gc._request(
            "GET",
            f"{_user(upn)}/events/{graph_event_id}",
            params={"$select": "start,end,isCancelled,onlineMeeting"},
            headers={"Prefer": 'outlook.timezone="UTC"'},
        )
    if not isinstance(data, dict):
        return None
    online = data.get("onlineMeeting") or {}
    out: dict = {
        "isCancelled": bool(data.get("isCancelled")),
        "join_url": online.get("joinUrl") if isinstance(online, dict) else None,
    }
    for key in ("start", "end"):
        raw = (data.get(key) or {}).get("dateTime")
        out[key] = _parse_iso_utc(raw) if raw else None
    return out


async def resolve_user_id(upn: str) -> Optional[str]:
    """Identyfikator obiektu w Entra (``onlineMeetings`` wymaga go w ścieżce)."""
    async with _client() as gc:
        try:
            data = await gc.get(_user(upn), params={"$select": "id"})
        except GraphRequestError as exc:
            if exc.status == 404:
                return None
            raise
    return data.get("id") if isinstance(data, dict) else None


def _odata_quote(value: str) -> str:
    return value.replace("'", "''")


async def find_online_meeting(user_id: str, join_url: str) -> Optional[str]:
    """Identyfikator spotkania Teams po linku dołączenia albo ``None``."""
    params = {"$filter": f"JoinWebUrl eq '{_odata_quote(join_url)}'"}
    async with _client() as gc:
        data = await gc.get(f"{_user(user_id)}/onlineMeetings", params=params)
    items = (data or {}).get("value") or []
    return items[0].get("id") if items else None


async def enable_auto_transcription(user_id: str, meeting_id: str) -> None:
    """Automatyczne nagrywanie (z transkrypcją) i zgoda na transkrypcję.

    Czy transkrypcja startuje razem z nagraniem, zależy od polityki spotkań
    Teams tenanta — sprawdzane w Fazie 0 na prawdziwym prepie.
    """
    async with _client() as gc:
        await gc.patch(
            f"{_user(user_id)}/onlineMeetings/{meeting_id}",
            json={"recordAutomatically": True, "allowTranscription": True},
        )


@dataclass(frozen=True)
class TranscriptRef:
    id: str
    created: Optional[str]


async def list_transcripts(user_id: str, meeting_id: str) -> list[TranscriptRef]:
    """Transkrypty spotkania od najstarszego (ponowne uruchomienie = kilka)."""
    async with _client() as gc:
        data = await gc.get(f"{_user(user_id)}/onlineMeetings/{meeting_id}/transcripts")
    refs = [
        TranscriptRef(id=str(item["id"]), created=item.get("createdDateTime"))
        for item in (data or {}).get("value") or []
        if item.get("id")
    ]
    return sorted(refs, key=lambda r: r.created or "")


async def transcript_vtt(user_id: str, meeting_id: str, transcript_id: str) -> str:
    """Treść transkryptu w formacie WebVTT."""
    url = (
        f"{_user(user_id)}/onlineMeetings/{meeting_id}/transcripts/"
        f"{transcript_id}/content?$format=text/vtt"
    )
    async with _client() as gc:
        raw = await gc.download(url)
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw or "")
