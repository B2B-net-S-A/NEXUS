"""Configure the fixed NEXUS release wrapper using the existing Coolify token."""

import json
import os
import re
import sys
import urllib.error
import urllib.request

COMMAND = "sh .github/scripts/release.sh --project-directory . --env-file /artifacts/build-time.env"


def planned_changes(application, envs):
    if application.get("build_pack") != "dockercompose":
        raise ValueError("expected Docker Compose application")
    if application.get("base_directory") not in (None, "", "/"):
        raise ValueError("unexpected application directory")
    if application.get("docker_compose_location") not in (
        "/docker-compose.yml", "docker-compose.yml"
    ):
        raise ValueError("unexpected compose file")
    command = application.get("docker_compose_custom_build_command")
    if command not in (None, "", COMMAND):
        raise ValueError("an unrelated custom build command already exists")
    remove = []
    for env in envs:
        if env.get("key") != "SOURCE_COMMIT" or env.get("is_preview") is True:
            continue
        # Only repair the exact non-secret cycle found in production.
        # A different explicit override needs investigation, not deletion.
        if env.get("value") != "${GIT_SHA:-unknown}" or env.get("is_preview") is not False:
            raise ValueError("unrecognized SOURCE_COMMIT override")
        uuid = env.get("uuid", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", uuid):
            raise ValueError("missing environment identifier")
        remove.append(uuid)
    return command != COMMAND, remove


def configure(request, app_id):
    path = "applications/" + app_id
    application = request("GET", path)
    envs = request("GET", path + "/envs")
    update, remove = planned_changes(application, envs)
    if update:
        request("PATCH", path, {"docker_compose_custom_build_command": COMMAND})
    for uuid in remove:
        request("DELETE", path + "/envs/" + uuid)
    verified = request("GET", path)
    remaining = request("GET", path + "/envs")
    update_needed, remove_needed = planned_changes(verified, remaining)
    if update_needed or remove_needed:
        raise ValueError("release configuration read-back mismatch")
    print("NEXUS_RELEASE_CONFIGURATION_VERIFIED: fixed build wrapper; no production SOURCE_COMMIT cycle")


def main():
    base = os.environ["COOLIFY_URL"].rstrip("/")
    token = os.environ["COOLIFY_TOKEN"]
    app_id = os.environ["COOLIFY_APP_UUID"]
    if not base.startswith("https://") or not re.fullmatch(r"[A-Za-z0-9_-]+", app_id):
        return 1

    def request(method, path, payload=None):
        req = urllib.request.Request(
            base + "/api/v1/" + path,
            method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": "Bearer " + token, "Accept": "application/json", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    try:
        configure(request, app_id)
    except urllib.error.HTTPError as error:
        print("NEXUS_RELEASE_CONFIGURATION_FAILED: HTTP " + str(error.code), file=sys.stderr)
        return 1
    except Exception:
        # API bodies and exception messages may contain credentials.
        print("NEXUS_RELEASE_CONFIGURATION_FAILED: invalid configuration or transport/read-back failure", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
