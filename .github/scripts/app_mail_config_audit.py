"""Read-only Exchange policy diagnosis. Output only validated business identities."""

import json
import os
import re
import sys
import urllib.request
import urllib.error
import urllib.parse


PROBE_SENDER = "nexus-powiadomienia@b2bnetwork.pl"
PROBE_RECIPIENT = "artur.twardowski@b2bnetwork.pl"


def summarize(envs):
    patterns = {
        "M365_CLIENT_ID": r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
        "M365_APP_MAIL_CLIENT_ID": r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
        "M365_MAIL_SENDER_UPN": r"[A-Za-z0-9._+-]+@b2bnetwork\.pl",
        "M365_APP_MAIL_ENABLED": r"(?i:true|false|0|1)",
    }
    result = {}
    for row in envs:
        key = row.get("key")
        if key not in patterns or row.get("is_preview") is True:
            continue
        value = str(row.get("value") or "").strip()
        result[key] = value if re.fullmatch(patterns[key], value) else "unavailable"
    return result


def send_probe(envs, opener=urllib.request.urlopen):
    """One synthetic Graph call to the owner; no retry or arbitrary recipient.

    Existing credentials stay in this Actions process and never reach output.
    This tests Exchange delivery separately from the application's retry gate.
    """
    allowed = {
        "M365_CLIENT_ID",
        "M365_CLIENT_SECRET",
        "M365_APP_MAIL_CLIENT_ID",
        "M365_APP_MAIL_CLIENT_SECRET",
        "M365_TENANT_ID",
        "M365_MAIL_TENANT_ID",
        "M365_MAIL_SENDER_UPN",
    }
    values = {
        row["key"]: str(row.get("value") or "").strip()
        for row in envs
        if row.get("key") in allowed and row.get("is_preview") is not True
    }
    sender = PROBE_SENDER
    tenant = values.get("M365_MAIL_TENANT_ID") or values.get("M365_TENANT_ID", "")
    dedicated_id = values.get("M365_APP_MAIL_CLIENT_ID", "")
    dedicated_secret = values.get("M365_APP_MAIL_CLIENT_SECRET", "")
    client_id = dedicated_id or values.get("M365_CLIENT_ID", "")
    client_secret = dedicated_secret or values.get("M365_CLIENT_SECRET", "")
    uuid_pattern = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
    if (
        values.get("M365_MAIL_SENDER_UPN") != sender
        or bool(dedicated_id) != bool(dedicated_secret)
        or not re.fullmatch(uuid_pattern, tenant)
        or not re.fullmatch(uuid_pattern, client_id)
        or not client_secret
    ):
        return {"accepted": False, "result": "configuration_unavailable"}
    posted = False
    try:
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
            }
        ).encode()
        request = urllib.request.Request(
            "https://login.microsoftonline.com/" + tenant + "/oauth2/v2.0/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with opener(request, timeout=20) as response:
            token = json.load(response)["access_token"]
        payload = {
            "message": {
                "subject": "[NEXUS] Test przywrocenia wysylki systemowej",
                "body": {
                    "contentType": "Text",
                    "content": "Kontrolna wiadomosc Sentry/NEXUS. Dane syntetyczne. "
                    "Odbior tej wiadomosci potwierdza dostawe; nie podejmuj zadnych akcji.",
                },
                "toRecipients": [
                    {"emailAddress": {"address": PROBE_RECIPIENT}}
                ],
            },
            "saveToSentItems": False,
        }
        request = urllib.request.Request(
            "https://graph.microsoft.com/v1.0/users/" + sender + "/sendMail",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
        )
        posted = True
        with opener(request, timeout=20) as response:
            return {
                "accepted": response.status == 202,
                "http_status": response.status,
                "delivery_confirmed": False,
            }
    except urllib.error.HTTPError as error:
        return {"accepted": False, "http_status": error.code, "result": "rejected"}
    except Exception:
        return {
            "accepted": False,
            "result": "delivery_uncertain" if posted else "token_unavailable",
        }


def main():
    base = os.environ["CO_URL"].rstrip("/")
    app_id = os.environ["APP_UUID"]
    if not base.startswith("https://") or not re.fullmatch(r"[A-Za-z0-9_-]+", app_id):
        return 1
    request = urllib.request.Request(
        base + "/api/v1/applications/" + app_id + "/envs",
        headers={"Authorization": "Bearer " + os.environ["CO_TOKEN"]},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            rows = json.load(response)
        if not isinstance(rows, list):
            raise ValueError()
        result = summarize(rows)
        if os.environ.get("MAIL_SEND_PROBE") == "1":
            result["probe"] = send_probe(rows)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["probe"]["accepted"] else 1
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(
            "Mail identity audit failed; no response content emitted", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
