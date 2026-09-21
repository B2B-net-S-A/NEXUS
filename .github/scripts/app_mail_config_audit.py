"""Read-only Exchange policy diagnosis. Output only validated business identities."""
import json
import os
import re
import sys
import urllib.request


def summarize(envs):
    patterns = {
        "M365_CLIENT_ID": r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
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
        print(json.dumps(summarize(rows), sort_keys=True))
        return 0
    except Exception:
        print("Mail identity audit failed; no response content emitted", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
