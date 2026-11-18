"""T3 (18.11.2026): jeden prawdziwy mail „Dziękujemy za zgłoszenie” z kariera@.

Szablon to ``render_terms_email`` z backendu, a forma ta sama co w aplikacji:
MIME z częścią tekstową, ``List-Unsubscribe`` i bez ``Reply-To``. Adresaci są
stali: skrzynka firmowa Artura i jego Gmail z sekretu repo ``T3_PROBE_GMAIL``
(log Actions jest publiczny, więc adresów nie wypisujemy). Link w mailu ma
fikcyjny token: formularz pokaże „link nieprawidłowy”, a cała ścieżka
formularza przeszła T2 na stagingu. Bez ponowień.
"""

import base64
import importlib.util
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path

SENDER = "kariera@b2bnetwork.pl"
OWNER_WORK = "artur.twardowski@b2bnetwork.pl"
PUBLIC_BASE = "https://nexus.b2bnetwork.pl"
API_BASE = "https://api.nexus.dynaminds.pl"
JOB_TITLE = "Senior Java Developer"
_UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
_TEMPLATE = (
    Path(__file__).resolve().parents[2] / "backend/app/services/candidate_terms.py"
)


def _rules():
    spec = importlib.util.spec_from_file_location("candidate_terms", _TEMPLATE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["candidate_terms"] = module  # dataclass szuka modułu po nazwie
    spec.loader.exec_module(module)
    return module


def recipients(gmail):
    found = [OWNER_WORK]
    if gmail and re.fullmatch(r"[A-Za-z0-9._+-]+@gmail\.com", gmail.strip()):
        found.append(gmail.strip())
    return found


def credentials(envs):
    keys = {
        "M365_CLIENT_ID",
        "M365_CLIENT_SECRET",
        "M365_APP_MAIL_CLIENT_ID",
        "M365_APP_MAIL_CLIENT_SECRET",
        "M365_TENANT_ID",
        "M365_MAIL_TENANT_ID",
        "CANDIDATE_MAIL_SENDER_UPN",
    }
    values = {
        row["key"]: str(row.get("value") or "").strip()
        for row in envs
        if row.get("key") in keys and row.get("is_preview") is not True
    }
    tenant = values.get("M365_MAIL_TENANT_ID") or values.get("M365_TENANT_ID", "")
    dedicated_id = values.get("M365_APP_MAIL_CLIENT_ID", "")
    dedicated_secret = values.get("M365_APP_MAIL_CLIENT_SECRET", "")
    client_id = dedicated_id or values.get("M365_CLIENT_ID", "")
    client_secret = dedicated_secret or values.get("M365_CLIENT_SECRET", "")
    if (
        values.get("CANDIDATE_MAIL_SENDER_UPN") != SENDER
        or bool(dedicated_id) != bool(dedicated_secret)
        or not re.fullmatch(_UUID, tenant)
        or not re.fullmatch(_UUID, client_id)
        or not client_secret
    ):
        return None
    return tenant, client_id, client_secret


def mime_message(to, rules=None):
    rules = rules or _rules()
    token = "proba-" + secrets.token_urlsafe(8)
    mail = rules.render_terms_email(
        job_title=JOB_TITLE,
        link=f"{PUBLIC_BASE}/warunki/{token}",
        optout_link=f"{PUBLIC_BASE}/warunki/{token}?wypis=1",
        rodo_url=f"{PUBLIC_BASE}/kariera/rodo",
        logo_url=f"{PUBLIC_BASE}/brand/mail/b2bnetwork-264.png",
        logo_light_url=f"{PUBLIC_BASE}/brand/mail/b2bnetwork-light-240.png",
    )
    msg = EmailMessage()
    msg["From"] = SENDER
    msg["To"] = to
    msg["Subject"] = mail.subject
    msg["List-Unsubscribe"] = (
        f"<{rules.one_click_unsubscribe_url(API_BASE, token)}>"
    )
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(mail.text_body)
    msg.add_alternative(mail.html_body, subtype="html")
    return msg


def send(envs, gmail, opener=urllib.request.urlopen):
    creds = credentials(envs)
    if creds is None:
        return {"result": "configuration_unavailable", "sent": []}
    tenant, client_id, client_secret = creds
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
    try:
        with opener(request, timeout=20) as response:
            token = json.load(response)["access_token"]
    except Exception:
        return {"result": "token_unavailable", "sent": []}
    rules = _rules()
    sent = []
    for index, to in enumerate(recipients(gmail)):
        label = "work" if index == 0 else "gmail"
        raw = base64.b64encode(mime_message(to, rules).as_bytes(policy=SMTP))
        request = urllib.request.Request(
            "https://graph.microsoft.com/v1.0/users/" + SENDER + "/sendMail",
            data=raw,
            headers={"Authorization": "Bearer " + token, "Content-Type": "text/plain"},
        )
        try:
            with opener(request, timeout=20) as response:
                sent.append({"to": label, "http_status": response.status})
        except urllib.error.HTTPError as error:
            sent.append({"to": label, "http_status": error.code})
        except Exception:
            sent.append({"to": label, "result": "delivery_uncertain"})
    ok = all(row.get("http_status") == 202 for row in sent)
    return {"result": "accepted" if ok else "failed", "sent": sent}


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
    except Exception:
        print("Coolify env read failed; no response content emitted", file=sys.stderr)
        return 1
    result = send(rows, os.environ.get("PROBE_GMAIL", ""))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "accepted" else 1


if __name__ == "__main__":
    sys.exit(main())
