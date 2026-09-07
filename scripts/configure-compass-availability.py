"""Provision the dedicated connection using the repository's existing Coolify vault.

The new secret is generated inside the runner and sent directly to the two
validated applications. It never enters workflow inputs, outputs or artifacts.
"""

import json
import os
import secrets
import urllib.error
import urllib.request


def repository_name(value):
    value = str(value or "").strip().removesuffix(".git").rstrip("/")
    value = value.replace("git@github.com:", "")
    return "/".join(value.split("/")[-2:]).casefold()


def compass_application(applications):
    matches = [
        app
        for app in applications
        if repository_name(app.get("git_repository")) == "artur-t-96/compass"
        and app.get("git_branch") == "main"
    ]
    if len(matches) != 1:
        raise ValueError("Expected exactly one COMPASS application on main")
    return matches[0]


def main():
    base = os.environ["COOLIFY_URL"].rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("The configured Coolify endpoint must use HTTPS")
    token = os.environ["COOLIFY_TOKEN"]
    nexus_id = os.environ["COOLIFY_APP_UUID"]
    stage = os.environ.get("AVAILABILITY_STAGE", "export")
    dry_run = os.environ.get("AVAILABILITY_DRY_RUN", "true")
    if stage not in {"export", "consumer"} or dry_run not in {"true", "false"}:
        raise ValueError("Invalid rollout stage or dry-run flag")

    def api(method, path, payload=None):
        request = urllib.request.Request(
            base + "/api/v1" + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method=method,
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
            return json.loads(data) if data else None

    nexus = api("GET", "/applications/" + nexus_id)
    if (
        repository_name(nexus.get("git_repository")) != "artur-t-96/nexus"
        or nexus.get("git_branch") != "main"
    ):
        raise ValueError(
            "Configured NEXUS application does not match the production repository"
        )
    applications = api("GET", "/applications")
    if dry_run == "true":
        print(
            json.dumps(
                {
                    "visible_repositories": [
                        repository_name(app.get("git_repository"))
                        for app in applications
                    ]
                }
            )
        )
    compass = compass_application(applications)
    compass_id = compass["uuid"]

    def envs(app_id):
        return {
            row["key"]: row
            for row in api("GET", "/applications/" + app_id + "/envs")
            if not row.get("is_preview", False)
        }

    compass_env = envs(compass_id)
    nexus_env = envs(nexus_id)
    source_key, target_key = "AVAILABILITY_EXPORT_SECRET", "COMPASS_AVAILABILITY_SECRET"
    source = compass_env.get(source_key, {}).get("value") or ""
    target = nexus_env.get(target_key, {}).get("value") or ""
    changes = (
        [
            "COMPASS:AVAILABILITY_EXPORT_SECRET",
            "NEXUS:COMPASS_AVAILABILITY_SECRET",
            "NEXUS:COMPASS_AVAILABILITY_URL",
        ]
        if stage == "export"
        else [
            "NEXUS:COMPASS_AVAILABILITY_ENABLED",
            "NEXUS:RECRUITMENT_ALLOCATION_ENABLED",
        ]
    )
    print(
        json.dumps(
            {
                "dry_run": dry_run == "true",
                "stage": stage,
                "settings": changes,
                "source_configured": bool(source),
                "consumer_configured": bool(target),
            }
        )
    )
    if dry_run == "true":
        return

    def put(app_id, existing, key, value):
        api(
            "PATCH" if key in existing else "POST",
            "/applications/" + app_id + "/envs",
            {
                "key": key,
                "value": value,
                "is_buildtime": False,
                "is_runtime": True,
                "is_preview": False,
            },
        )

    if stage == "export":
        if source and target and source != target:
            raise ValueError(
                "Existing availability credentials disagree; refusing rotation"
            )
        secret = source or target or secrets.token_urlsafe(48)
        if len(secret) < 32 or "*" in secret:
            raise ValueError(
                "Vault did not return a usable credential; refusing replacement"
            )
        put(compass_id, compass_env, source_key, secret)
        put(nexus_id, nexus_env, target_key, secret)
        put(
            nexus_id,
            nexus_env,
            "COMPASS_AVAILABILITY_URL",
            "https://compass.dynaminds.pl/api/internal/availability",
        )
        restart_id = compass_id
    else:
        if not source or not target:
            raise ValueError(
                "Configure the export connection before enabling the consumer"
            )
        if source != target:
            raise ValueError("Availability credentials disagree")
        put(nexus_id, nexus_env, "COMPASS_AVAILABILITY_ENABLED", "true")
        put(nexus_id, nexus_env, "RECRUITMENT_ALLOCATION_ENABLED", "true")
        restart_id = nexus_id
    result = api("GET", "/deploy?uuid=" + restart_id + "&force=false")
    print(
        json.dumps(
            {
                "configured": True,
                "deployment_ids": [
                    row.get("deployment_uuid")
                    for row in (result or {}).get("deployments", [])
                ],
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        # A vault error response can echo a value; never log its body.
        raise SystemExit(f"Coolify request failed: HTTP {exc.code}") from None
