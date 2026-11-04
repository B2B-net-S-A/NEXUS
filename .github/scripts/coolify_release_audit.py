"""Read-only release configuration audit; never emit environment values."""

import json
import os
import re
import sys
import urllib.error
import urllib.request

KEYS = {
    "GIT_SHA",
    "NEXT_PUBLIC_GIT_SHA",
    "SOURCE_COMMIT",
    "SENTRY_AUTH_TOKEN",
    "SENTRY_DSN",
    "NEXT_PUBLIC_SENTRY_DSN",
}


def summarize(application, envs):
    settings = application.get("settings") or {}
    result = {
        "source_commit_setting_exposed": "include_source_commit_in_build" in settings,
        "source_commit_in_build": (
            settings["include_source_commit_in_build"] is True
            if "include_source_commit_in_build" in settings
            else None
        ),
        "custom_build_command_present": bool(
            application.get("docker_compose_custom_build_command")
        ),
        "revision_is_pinned": bool(
            re.fullmatch(r"[0-9a-f]{40}", str(application.get("git_commit_sha", "")))
        ),
        # Okno wdrożeń 18:00–08:00 (14.10.2026) pilnuje deploy.yml — działa
        # tylko, gdy Coolify nie buduje sam po pushu na main. Same flagi,
        # nigdy wartość sekretu webhooka.
        "auto_deploy_enabled": (
            settings["is_auto_deploy_enabled"] is True
            if "is_auto_deploy_enabled" in settings
            else None
        ),
        "github_push_webhook_secret_set": bool(
            application.get("manual_webhook_secret_github")
        ),
        "envs": [],
    }
    for item in envs:
        if item.get("key") not in KEYS:
            continue
        value = item.get("value")
        row = {"key": item["key"], "value_present": bool(value)}
        for flag in ("is_buildtime", "is_runtime", "is_preview", "is_literal"):
            row[flag] = item.get(flag) is True
        if item["key"] in {"GIT_SHA", "NEXT_PUBLIC_GIT_SHA", "SOURCE_COMMIT"}:
            row["value_is_full_sha"] = bool(
                re.fullmatch(r"[0-9a-f]{40}", str(value or ""))
            )
            row["value_is_unknown"] = value == "unknown"
            row["value_is_reference"] = isinstance(value, str) and "$" in value
            # Classify only known, non-secret variable references. Never echo
            # arbitrary values, even when they happen to contain a dollar sign.
            row["known_reference"] = next(
                (
                    name
                    for name in ("SOURCE_COMMIT", "GIT_SHA", "NEXT_PUBLIC_GIT_SHA")
                    if value in ("$" + name, "${" + name + "}")
                ),
                None,
            )
            row["recognized_default"] = (
                value if value in (
                    "${SOURCE_COMMIT:-unknown}",
                    "${GIT_SHA:-unknown}",
                    "${SOURCE_COMMIT:-${GIT_SHA:-unknown}}",
                ) else None
            )
        result["envs"].append(row)
    return result


def deploy_window_violations(result):
    """Powody, dla których okno wdrożeń z GitHuba może nie trzymać."""
    if result.get("auto_deploy_enabled") is None:
        return ["auto_deploy_setting_missing"]
    if result["auto_deploy_enabled"]:
        return ["auto_deploy_enabled"]
    return []


def main():
    base = os.environ["CO_URL"].rstrip("/")
    token = os.environ["CO_TOKEN"]
    app_id = os.environ["APP_UUID"]
    assert base.startswith("https://") and re.fullmatch(r"[A-Za-z0-9_-]+", app_id)

    def read(path):
        request = urllib.request.Request(
            base + "/api/v1/" + path,
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            if path == "version":
                raw = response.read(200).decode().strip().strip('"')
                return raw if re.fullmatch(r"v?\d+\.\d+\.\d+(?:[-.][A-Za-z0-9.]+)?", raw) else None
            return json.load(response)

    try:
        application = read("applications/" + app_id)
        envs = read("applications/" + app_id + "/envs")
        assert isinstance(application, dict) and isinstance(envs, list)
        result = summarize(application, envs)
        result["server_version"] = read("version")
        from configure_coolify_release import planned_changes

        update, remove = planned_changes(application, envs)
        result["release_wrapper_update_needed"] = update
        result["production_cycles_to_remove"] = len(remove)
        generated = application.get("docker_compose") or ""
        result["generated_image_releases"] = {
            service: sha for service, sha in re.findall(
                r"image:\s*['\"]?[a-z0-9]+_(backend|frontend):([0-9a-f]{40})\b", generated
            )
        }
        print(json.dumps(result, sort_keys=True))
        violations = deploy_window_violations(result)
        if violations:
            print(
                "::error::Okno wdrożeń 18:00–08:00 może nie trzymać: "
                + ", ".join(violations)
                + " — wyłącz Auto Deploy aplikacji w Coolify (Advanced).",
                file=sys.stderr,
            )
            return 1
    except urllib.error.HTTPError as error:
        print(
            "Release configuration read failed: HTTP " + str(error.code),
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            "Release configuration read failed: invalid response or transport error",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
