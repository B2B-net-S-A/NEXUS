"""Scoped Graph test. Emits only statuses; creates no attendees and cancels its event.

Success proves Graph access/options, not a generated recording or transcript.
"""

import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

TENANT = "e277180c-b58a-418c-b362-bb89ab0b1301"
CLIENT = "b6051b61-559e-4482-841e-0cc8869a4e2e"
ORGANIZER = "ewa.kalata@b2bnetwork.pl"
EXCLUDED = "artur.twardowski@b2bnetwork.pl"
SESSION_ORGANIZER = "klaudia.uliasz@b2bnetwork.pl"
SESSION_SUBJECT = (
    "Prep 1: NEXUS TEST-M365-20260926 — "
    "[NEXUS TEST M365 2026-09-26] Kontrola prepu Teams"
)


def audit_session(graph, opener, token, result):
    """Read only the named owner test; never emit URLs, IDs or spoken content."""
    result.update(session_stage="find_test_event", passed=False)
    query = urllib.parse.urlencode(
        {
            "startDateTime": "2026-09-26T14:00:00Z",
            "endDateTime": "2026-09-26T14:31:00Z",
            "$filter": "subject eq '" + SESSION_SUBJECT.replace("'", "''") + "'",
            "$select": "id,subject,onlineMeeting,attendees",
        }
    )
    path = "/users/" + SESSION_ORGANIZER
    status, data = graph(path + "/calendarView?" + query)
    result["session_calendar_http"] = status
    events = [e for e in data.get("value", []) if e.get("subject") == SESSION_SUBJECT]
    if len(events) != 1 or data.get("@odata.nextLink"):
        result["failed_stage"] = "test_event_not_unique"
        return result
    event = events[0]
    addresses = {
        str(a.get("emailAddress", {}).get("address", "")).lower()
        for a in event.get("attendees", [])
    }
    if not addresses or not addresses.issubset({EXCLUDED, SESSION_ORGANIZER}):
        result["failed_stage"] = "test_attendees_mismatch"
        return result
    join = (event.get("onlineMeeting") or {}).get("joinUrl")
    if not join:
        result["failed_stage"] = "test_join_missing"
        return result
    result["session_stage"] = "find_online_meeting"
    _, organizer = graph(path + "?$select=id")
    aad_path = "/users/" + urllib.parse.quote(organizer["id"], safe="")
    query = urllib.parse.urlencode(
        {"$filter": "JoinWebUrl eq '" + join.replace("'", "''") + "'"}
    )
    _, data = graph(aad_path + "/onlineMeetings?" + query)
    meetings = data.get("value", [])
    if len(meetings) != 1:
        result["failed_stage"] = "test_meeting_not_unique"
        return result
    meeting = meetings[0]
    result["record_automatically"] = meeting.get("recordAutomatically") is True
    result["allow_transcription"] = meeting.get("allowTranscription") is True
    meeting_path = (
        aad_path + "/onlineMeetings/" + urllib.parse.quote(meeting["id"], safe="")
    )
    result["session_stage"] = "list_session_transcripts"
    status, data = graph(meeting_path + "/transcripts")
    result["transcripts_http"] = status
    refs = data.get("value", [])
    if data.get("@odata.nextLink"):
        result["failed_stage"] = "transcript_list_incomplete"
        return result
    result["transcript_count"] = len(refs)
    if not refs:
        result["failed_stage"] = "transcript_not_ready"
        return result
    result["session_stage"] = "read_session_transcripts"
    content_bytes = 0
    cue_count = 0
    for ref in refs:
        url = (
            "https://graph.microsoft.com/v1.0"
            + meeting_path
            + "/transcripts/"
            + urllib.parse.quote(ref["id"], safe="")
            + "/content?$format=text/vtt"
        )
        request = urllib.request.Request(
            url, headers={"Authorization": "Bearer " + token}
        )
        try:
            with opener(request, timeout=25) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raise ProbeError(error.code) from None
        except Exception:
            raise ProbeError() from None
        text = raw.decode("utf-8", errors="replace")
        if not text.lstrip().startswith("WEBVTT"):
            result["failed_stage"] = "transcript_format_invalid"
            return result
        content_bytes += len(raw)
        # A cue must contain speech, rather than only its timestamps/tags.
        in_cue = False
        speech = []
        for line in text.splitlines() + [""]:
            if " --> " in line:
                in_cue = True
                speech = []
            elif not line.strip():
                if in_cue and " ".join(speech).strip():
                    cue_count += 1
                in_cue = False
            elif in_cue:
                speech.append(re.sub(r"<[^>]+>", "", line).strip())
    result.update(
        transcript_content_bytes=content_bytes,
        spoken_cue_count=cue_count,
        transcript_generated_verified=cue_count > 0,
        passed=cue_count > 0,
    )
    if not result["passed"]:
        result["failed_stage"] = "transcript_empty"
    return result


class ProbeError(Exception):
    def __init__(self, status=0):
        self.status = status


def fetch(request, opener):
    try:
        with opener(request, timeout=25) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raise ProbeError(error.code) from None
    except Exception:  # noqa: BLE001 — never expose private HTTP/parsing exceptions
        raise ProbeError() from None


def probe(
    rows,
    *,
    write=False,
    session=False,
    opener=urllib.request.urlopen,
    sleep=time.sleep,
    identity="local",
):
    allowed = {
        "TEAMS_PREP_CLIENT_ID",
        "TEAMS_PREP_CLIENT_SECRET",
        "M365_MAIL_TENANT_ID",
        "M365_TENANT_ID",
    }
    values = {
        row["key"]: str(row.get("value") or "").strip()
        for row in rows
        if row.get("key") in allowed and row.get("is_preview") is not True
    }
    result = {
        "organizer": ORGANIZER,
        "excluded": EXCLUDED,
        "recording_generated_verified": False,
        "transcript_generated_verified": False,
    }
    event_id = None
    token = None
    stage = "configuration"
    user_path = "/users/" + ORGANIZER

    def graph(path, method="GET", payload=None):
        request = urllib.request.Request(
            "https://graph.microsoft.com/v1.0" + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
        )
        return fetch(request, opener)

    try:
        if write and session:
            raise ProbeError()
        if (
            values.get("TEAMS_PREP_CLIENT_ID") != CLIENT
            or (values.get("M365_MAIL_TENANT_ID") or values.get("M365_TENANT_ID"))
            != TENANT
            or not values.get("TEAMS_PREP_CLIENT_SECRET")
        ):
            raise ProbeError()
        stage = "token"
        request = urllib.request.Request(
            "https://login.microsoftonline.com/" + TENANT + "/oauth2/v2.0/token",
            data=urllib.parse.urlencode(
                {
                    "grant_type": "client_credentials",
                    "client_id": CLIENT,
                    "client_secret": values["TEAMS_PREP_CLIENT_SECRET"],
                    "scope": "https://graph.microsoft.com/.default",
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        _, auth = fetch(request, opener)
        token = auth["access_token"]
        result["token_acquired"] = True
        stage = "calendar_scope"
        status, _ = graph(user_path + "/calendar?$select=id")
        result["organizer_calendar_http"] = status
        try:
            denied, _ = graph("/users/" + EXCLUDED + "/calendar?$select=id")
        except ProbeError as error:
            denied = error.status
        result["excluded_calendar_http"] = denied
        if status != 200 or denied != 403:
            raise ProbeError()
        if session:
            stage = "session_audit"
            audit_session(graph, opener, token, result)
            return result
        if not write:
            result["passed"] = True
            return result
        stage = "create_event"
        correlation = str(
            uuid.uuid5(uuid.NAMESPACE_URL, "nexus-teams-probe:" + identity)
        )
        result["correlation"] = correlation
        start = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            minutes=30
        )
        end = start + datetime.timedelta(minutes=10)
        status, event = graph(
            user_path + "/events",
            "POST",
            {
                "subject": "[NEXUS TEST] Graph Teams — kontrola integracji",
                "body": {
                    "contentType": "Text",
                    "content": "Test techniczny NEXUS, bez uczestników. "
                    "Nie dołączaj; system odwoła spotkanie po sprawdzeniu ustawień.",
                },
                "start": {
                    "dateTime": start.replace(tzinfo=None).isoformat(),
                    "timeZone": "UTC",
                },
                "end": {
                    "dateTime": end.replace(tzinfo=None).isoformat(),
                    "timeZone": "UTC",
                },
                "attendees": [],
                "isOnlineMeeting": True,
                "onlineMeetingProvider": "teamsForBusiness",
                "transactionId": correlation,
            },
        )
        event_id = urllib.parse.quote(event["id"], safe="")
        result["event_created"] = status == 201
        stage = "find_meeting"
        _, organizer = graph(user_path + "?$select=id")
        aad_path = "/users/" + urllib.parse.quote(organizer["id"], safe="")
        meeting = None
        for attempt in range(10):
            join = (event.get("onlineMeeting") or {}).get("joinUrl")
            if join:
                query = urllib.parse.urlencode(
                    {"$filter": "JoinWebUrl eq '" + join.replace("'", "''") + "'"}
                )
                _, meetings = graph(aad_path + "/onlineMeetings?" + query)
                if meetings.get("value"):
                    meeting = meetings["value"][0]
                    break
            if attempt < 9:
                sleep(5)
                _, event = graph(user_path + "/events/" + event_id)
        if not meeting:
            raise ProbeError()
        path = (
            aad_path + "/onlineMeetings/" + urllib.parse.quote(meeting["id"], safe="")
        )
        stage = "automatic_recording"
        graph(path, "PATCH", {"recordAutomatically": True, "allowTranscription": True})
        _, options = graph(path)
        result["record_automatically"] = options.get("recordAutomatically") is True
        result["allow_transcription"] = options.get("allowTranscription") is True
        if not (result["record_automatically"] and result["allow_transcription"]):
            raise ProbeError()
        stage = "transcript_access"
        status, _ = graph(path + "/transcripts")
        result["transcripts_http"] = status
        result["passed"] = status == 200
    except ProbeError as error:
        result.update(passed=False, failed_stage=stage, http_status=error.status)
        if stage == "create_event" and error.status == 0:
            result.update(event_creation_uncertain=True, cleanup_required=True)
    except Exception:  # noqa: BLE001 — result remains redacted and cleanup still runs
        result.update(passed=False, failed_stage=stage, http_status=0)
        if stage == "create_event" and not event_id:
            result.update(event_creation_uncertain=True, cleanup_required=True)
    finally:
        if event_id:
            try:
                status, _ = graph(
                    user_path + "/events/" + event_id + "/cancel",
                    "POST",
                    {"comment": "Test techniczny NEXUS zakończony."},
                )
                result["event_cancelled"] = status in (200, 202, 204)
            except ProbeError:
                result["event_cancelled"] = False
            if not result["event_cancelled"]:
                result.update(passed=False, cleanup_required=True)
    return result


def main():
    try:
        base = os.environ["CO_URL"].rstrip("/")
        app_id = os.environ["APP_UUID"]
        if not base.startswith("https://") or not re.fullmatch(
            r"[A-Za-z0-9_-]+", app_id
        ):
            raise ProbeError()
        request = urllib.request.Request(
            base + "/api/v1/applications/" + app_id + "/envs",
            headers={"Authorization": "Bearer " + os.environ["CO_TOKEN"]},
        )
        _, rows = fetch(request, urllib.request.urlopen)
        if not isinstance(rows, list):
            raise ProbeError()
        result = probe(
            rows,
            write=os.environ.get("TEAMS_MEETING_PROBE") == "1",
            session=os.environ.get("TEAMS_SESSION_AUDIT") == "1",
            identity=os.environ.get("GITHUB_RUN_ID", "local")
            + ":"
            + os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("passed") else 1
    except Exception:  # noqa: BLE001 — credentials and private bodies never reach logs
        print(
            "Teams probe failed; no private response content emitted", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
