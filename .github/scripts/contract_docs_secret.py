#!/usr/bin/env python3
"""One-time encrypted provisioning of the dedicated contract-docs credential.

Private transport key lives only in the receiving hosted runner. Artifacts and
workflow inputs contain only the public offer / RSA-OAEP ciphertext. This is
restricted to one app, one tenant and one Coolify environment key; no deploy.
"""

import base64
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile

CLIENT = "2a905946-22c8-4cb2-a100-22f4f1952075"
TENANT = "e277180c-b58a-418c-b362-bb89ab0b1301"
SITE = "b2bnetsa.sharepoint.com,62a80b82-17bf-4d58-9709-34dfe364feb9,8fbefbc4-4ee5-4c9f-a011-6bda02296f09"
KEY = "CONTRACT_DOCS_SP_CLIENT_SECRET"
WORKFLOW = ".github/workflows/contract-docs-secret.yml"


def gh(path):
    result = subprocess.run(["gh", "api", path], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("GitHub API request failed")
    return result.stdout


def api(url, method="GET", data=None, token=None, form=False):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if data is not None:
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded" if form else "application/json"
        )
        data = (urllib.parse.urlencode(data) if form else json.dumps(data)).encode()
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    return json.loads(body) if body else None


def identity():
    run = os.environ["GITHUB_RUN_ID"]
    attempt = os.environ["GITHUB_RUN_ATTEMPT"]
    if not re.fullmatch(r"[0-9]+", run) or attempt != "1":
        raise ValueError("Start a fresh run; retries cannot reuse transport keys")
    return run + "-" + attempt


def prepare(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    subprocess.run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:4096",
            "-out",
            str(directory / "private.pem"),
        ],
        check=True,
        capture_output=True,
    )
    (directory / "private.pem").chmod(0o600)
    public = subprocess.run(
        ["openssl", "pkey", "-in", str(directory / "private.pem"), "-pubout"],
        check=True,
        capture_output=True,
    ).stdout.decode()
    offer = {
        "identity": identity(),
        "client_id": CLIENT,
        "tenant_id": TENANT,
        "challenge": secrets.token_hex(16),
        "public_key": public,
        "expires_at": int(time.time()) + 900,
    }
    (directory / "offer.json").write_text(json.dumps(offer))
    print("Public transport offer ready; expires in 15 minutes.")


def decrypt(directory, ciphertext):
    offer = json.loads((directory / "offer.json").read_text())
    if time.time() >= offer["expires_at"]:
        raise ValueError("Transport offer expired")
    raw = base64.b64decode(ciphertext, validate=True)
    if len(raw) != 512:
        raise ValueError("Expected RSA-4096 ciphertext")
    result = subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-decrypt",
            "-inkey",
            str(directory / "private.pem"),
            "-pkeyopt",
            "rsa_padding_mode:oaep",
            "-pkeyopt",
            "rsa_oaep_md:sha256",
            "-pkeyopt",
            "rsa_mgf1_md:sha256",
        ],
        input=raw,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError("Invalid encrypted envelope")
    body = json.loads(result.stdout)
    if (
        body.get("identity") != offer["identity"]
        or body.get("challenge") != offer["challenge"]
        or body.get("client_id") != CLIENT
    ):
        raise ValueError("Envelope identity mismatch")
    secret = body.get("secret", "")
    if not isinstance(secret, str) or not re.fullmatch(
        r"[A-Za-z0-9~._-]{20,200}", secret
    ):
        raise ValueError("Unexpected client secret format")
    return secret


def validate_sender(run, receiver):
    return (
        run.get("path") == WORKFLOW
        and run.get("head_branch") == "main"
        and run.get("event") == "workflow_dispatch"
        and run.get("conclusion") == "success"
        and run.get("head_sha") == receiver["head_sha"]
        and run.get("actor", {}).get("id") == receiver["actor"]["id"]
        and run.get("run_attempt") == 1
    )


def provision(secret):
    # Validate the credential and its selected-site access before touching envs.
    auth = api(
        f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
        "POST",
        {
            "client_id": CLIENT,
            "client_secret": secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        },
        form=True,
    )
    token = auth["access_token"]
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==="))
    if (
        set(claims.get("roles", [])) != {"Sites.Selected"}
        or claims.get("tid") != TENANT
    ):
        raise ValueError("Unexpected application token permissions or tenant")
    site = api(f"https://graph.microsoft.com/v1.0/sites/{SITE}?$select=id", token=token)
    if site.get("id") != SITE:
        raise ValueError("Site access verification failed")
    base = os.environ["COOLIFY_URL"].rstrip("/")
    if urllib.parse.urlparse(base).scheme != "https":
        raise ValueError("Coolify HTTPS required")
    endpoint = base + "/api/v1/applications/" + os.environ["COOLIFY_APP_UUID"] + "/envs"
    auth_token = os.environ["COOLIFY_TOKEN"]
    current = api(endpoint, token=auth_token)
    runtime = {e["key"]: e.get("value", "") for e in current if not e.get("is_preview")}
    if runtime.get("CONTRACT_DOCS_SP_CLIENT_ID") != CLIENT:
        raise ValueError("Coolify client ID does not match the dedicated app")
    if runtime.get("M365_MAIL_TENANT_ID") != TENANT:
        raise ValueError("Coolify tenant does not match")
    if runtime.get("CONTRACT_DOCS_SP_SYNC_ENABLED", "").lower() != "false":
        raise ValueError("Initial provisioning requires sync disabled")
    if runtime.get(KEY) and runtime[KEY] != secret:
        raise ValueError("Existing non-empty credential; refusing rotation")
    payload = {
        "key": KEY,
        "value": secret,
        "is_buildtime": False,
        "is_runtime": True,
        "is_preview": False,
    }
    api(endpoint, "PATCH" if KEY in runtime else "POST", payload, token=auth_token)
    verified = api(endpoint, token=auth_token)
    if not any(
        e.get("key") == KEY and e.get("value") == secret and not e.get("is_preview")
        for e in verified
    ):
        raise ValueError("Coolify did not persist the requested credential")
    print(
        "Verified: dedicated Sites.Selected token, Share_B2B access, Coolify credential saved."
    )
    print(
        "Sync remains false. Run the normal Deploy workflow, then the initial import."
    )


def receive(directory):
    repo = os.environ["GITHUB_REPOSITORY"]
    receiver = json.loads(
        gh(f"repos/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    )
    offer = json.loads((directory / "offer.json").read_text())
    name = "contract-docs-envelope-" + identity()
    seen = set()
    while time.time() < offer["expires_at"]:
        listing = json.loads(
            gh(f"repos/{repo}/actions/artifacts?name={name}&per_page=100")
        )
        for artifact in listing["artifacts"]:
            run_id = artifact.get("workflow_run", {}).get("id")
            if not run_id or artifact["id"] in seen:
                continue
            run = json.loads(gh(f"repos/{repo}/actions/runs/{run_id}"))
            if run.get("status") != "completed":
                continue
            seen.add(artifact["id"])
            if not validate_sender(run, receiver) or artifact.get("expired"):
                continue
            archive = gh(f"repos/{repo}/actions/artifacts/{artifact['id']}/zip")
            with zipfile.ZipFile(io.BytesIO(archive)) as z:
                if (
                    z.namelist() != ["envelope.txt"]
                    or z.getinfo("envelope.txt").file_size > 1024
                ):
                    raise ValueError("Unexpected envelope archive")
                ciphertext = z.read("envelope.txt").decode().strip()
            provision(decrypt(directory, ciphertext))
            return
        time.sleep(10)
    raise TimeoutError("No verified encrypted envelope received before expiry")


def submit(directory):
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    inputs = event["inputs"]
    if not re.fullmatch(r"[0-9]+-1", inputs["receiver_identity"]):
        raise ValueError("Expected a fresh receiver run identity")
    encoded = inputs.get("ciphertext", "")
    if len(base64.b64decode(encoded, validate=True)) != 512:
        raise ValueError("Only RSA-4096 ciphertext is accepted")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "envelope.txt").write_text(encoded)


if __name__ == "__main__":
    operation = sys.argv[1]
    directory = Path(os.environ["RUNNER_TEMP"]) / "contract-docs-transport"
    try:
        {"prepare": prepare, "receive": receive, "submit": submit}[operation](directory)
    except Exception as exc:
        # Never print exceptions / HTTP response bodies that may echo credentials.
        print(
            f"Provisioning stopped: {type(exc).__name__}; no secret values logged.",
            file=sys.stderr,
        )
        sys.exit(1)
    finally:
        if operation == "receive":
            (directory / "private.pem").unlink(missing_ok=True)
