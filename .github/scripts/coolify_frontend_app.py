"""Osobna aplikacja Coolify dla frontu: próba rolling update bez przejmowania ruchu.

Coolify w trybie compose zatrzymuje wszystko przed startem nowych kontenerów,
a aplikacja z Dockerfile ma rolling update. Plan:
``docs/claude/podstawy/przerwa-przy-wdrozeniu.md``. Ten skrypt tworzy aplikację
BEZ domeny, więc Traefik nie kieruje na nią ruchu; przepięcie domen to osobny,
świadomy krok.

Front stoi w osobnej sieci Dockera (destination ``nexus-front``), a nie we wspólnej
``coolify``. ``connect_to_docker_network`` na aplikacji compose wpiąłby do ``coolify``
każdą usługę, także ``postgres``, a w tej sieci Coolify ma własną usługę ``postgres``
(``coolify-db``): nazwa ``postgres`` z backendu miałaby dwa adresy. W ``nexus-front``
są tylko kontenery NEXUSA, front i ``coolify-proxy``.

Tryby: ``plan`` (tylko odczyt), ``create``, ``deploy``. Logi Actions są publiczne,
więc do wyjścia trafiają wyłącznie nazwy zmiennych, flagi i stany, nigdy wartości
ani ciała odpowiedzi API.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable

APP_NAME = "nexus-frontend"
BRANCH = "main"
NETWORK = "nexus-front"

# Tylko to, co czyta front: `grep process.env frontend/` i ARG-i w frontend/Dockerfile.
# Dziś kontener frontu dostaje cały skarbiec (ok. 200 zmiennych, także klucze API).
RUNTIME_ENV_KEYS = (
    "APP_PUBLIC_URL",
    "NEXT_PUBLIC_API_URL",
    "NEXT_PUBLIC_CAREER_HOST",
    "NEXT_PUBLIC_SENTRY_DSN",
    "SENTRY_DSN",
    "SENTRY_ENVIRONMENT",
    "SENTRY_TRACES_SAMPLE_RATE",
    "TZ",
)
BUILD_ONLY_ENV_KEYS = ("SENTRY_AUTH_TOKEN",)
BUILD_ENV_KEYS = ("NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_CAREER_HOST", "NEXT_PUBLIC_SENTRY_DSN")
# `backend` w sieci `nexus-front` pojawi się dopiero po przepięciu (compose dołącza
# tę sieć). Tu stała, nie kopia, bo compose też ją wpisuje na stałe.
FIXED_ENV = {"INTERNAL_API_URL": "http://backend:8000"}

Request = Callable[..., Any]


def frontend_envs(source_envs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Zmienne nowej aplikacji: wyłącznie z listy, bez wariantów podglądu."""
    wanted = {*RUNTIME_ENV_KEYS, *BUILD_ONLY_ENV_KEYS}
    rows = []
    for env in source_envs:
        key = env.get("key")
        if key not in wanted or env.get("is_preview") is True or not env.get("value"):
            continue
        rows.append(
            {
                "key": key,
                "value": env["value"],
                "is_buildtime": key in BUILD_ONLY_ENV_KEYS or key in BUILD_ENV_KEYS,
                "is_runtime": key in RUNTIME_ENV_KEYS,
                "is_literal": True,
            }
        )
    for key, value in FIXED_ENV.items():
        rows.append(
            {"key": key, "value": value, "is_buildtime": False, "is_runtime": True, "is_literal": True}
        )
    return rows


def application_payload(ids: dict[str, str], git_repository: str) -> dict[str, Any]:
    """Bez `domains` i bez `autogenerate_domain`: bez domeny nie ma ruchu."""
    return {
        "name": APP_NAME,
        "project_uuid": ids["project"],
        "environment_uuid": ids["environment"],
        "server_uuid": ids["server"],
        "destination_uuid": ids["destination"],
        "private_key_uuid": ids["private_key"],
        "git_repository": git_repository,
        "git_branch": BRANCH,
        "build_pack": "dockerfile",
        "base_directory": "/frontend",
        "dockerfile_location": "/Dockerfile",
        "ports_exposes": "3000",
        "custom_network_aliases": "frontend",
        "autogenerate_domain": False,
        # Stała nazwa kontenera wyłącza rolling update (ApplicationDeploymentJob).
        "is_consistent_container_name_enabled": False,
        "instant_deploy": False,
        "is_auto_deploy_enabled": False,
        "include_source_commit_in_build": True,
        "limits_memory": "1g",
        "limits_memory_reservation": "256m",
    }


def resolve_ids(request: Request, source: dict[str, Any]) -> dict[str, str]:
    """UUID-y środowiska obecnej aplikacji; brak któregokolwiek zatrzymuje skrypt."""
    destination = source.get("destination") or {}
    server = destination.get("server") or {}
    ids = {"destination": destination.get("uuid"), "server": server.get("uuid")}
    for project in request("GET", "projects"):
        detail = request("GET", "projects/" + project["uuid"])
        for environment in detail.get("environments") or []:
            if environment.get("id") == source.get("environment_id"):
                ids["project"] = project["uuid"]
                ids["environment"] = environment.get("uuid")
    for key in request("GET", "security/keys"):
        if key.get("id") == source.get("private_key_id"):
            ids["private_key"] = key.get("uuid")
    missing = sorted(
        name
        for name in ("project", "environment", "server", "destination", "private_key")
        if not ids.get(name)
    )
    if missing:
        raise ValueError("brak identyfikatorów: " + ", ".join(missing))
    return ids


def find_network(request: Request, server_uuid: str) -> dict[str, Any] | None:
    for destination in request("GET", "servers/" + server_uuid + "/destinations"):
        if destination.get("network") == NETWORK:
            return destination
    return None


def ensure_network(request: Request, server_uuid: str) -> str:
    """Destination `nexus-front`; Coolify tworzy sieć i podłącza do niej proxy."""
    existing = find_network(request, server_uuid)
    if existing:
        return existing["uuid"]
    created = request(
        "POST", "servers/" + server_uuid + "/destinations", {"name": NETWORK, "network": NETWORK}
    )
    return created["uuid"]


def find_frontend(request: Request) -> dict[str, Any] | None:
    matches = [app for app in request("GET", "applications") if app.get("name") == APP_NAME]
    if len(matches) > 1:
        raise ValueError("więcej niż jedna aplikacja " + APP_NAME)
    return matches[0] if matches else None


def describe(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        print(f"  {row['key']}: build={row['is_buildtime']} runtime={row['is_runtime']}")


def plan(request: Request, source_uuid: str) -> None:
    path = "applications/" + source_uuid
    source = request("GET", path)
    ids = resolve_ids(request, source)
    print("identyfikatory: " + ", ".join(sorted(ids)))
    print("istniejąca aplikacja frontu: " + ("tak" if find_frontend(request) else "nie"))
    settings = source.get("settings") or {}
    print("connect_to_docker_network: " + str(settings.get("connect_to_docker_network")))
    print("sieć " + NETWORK + ": " + ("jest" if find_network(request, ids["server"]) else "nie ma"))
    rows = frontend_envs(request("GET", path + "/envs"))
    print(f"zmienne do skopiowania ({len(rows)}):")
    describe(rows)


def create(request: Request, source_uuid: str) -> None:
    path = "applications/" + source_uuid
    if find_frontend(request):
        raise ValueError("aplikacja " + APP_NAME + " już istnieje")
    source = request("GET", path)
    rows = frontend_envs(request("GET", path + "/envs"))
    ids = resolve_ids(request, source)
    ids["destination"] = ensure_network(request, ids["server"])
    created = request(
        "POST",
        "applications/private-deploy-key",
        application_payload(ids, source["git_repository"]),
    )
    uuid = created["uuid"]
    for row in rows:
        request("POST", "applications/" + uuid + "/envs", row)
    # Aplikacji compose nie zmieniamy: backend dołączy do sieci przy przepięciu.
    print(f"utworzono {APP_NAME} w sieci {NETWORK}, zmiennych: {len(rows)}, bez domeny")


def built_sha_line(logs: Any, commit: str) -> bool | None:
    """Czy log builda ma linię `write-version.mjs` z SHA wdrożenia (None = brak logów).

    Log zawiera też wartości zmiennych, więc nie trafia na wyjście; zwracamy flagę.
    """
    if not logs or not commit:
        return None
    return f"(sha={commit})" in (logs if isinstance(logs, str) else json.dumps(logs))


def deploy(
    request: Request,
    expected_sha: str = "",
    poll_seconds: float = 10.0,
    polls: int = 120,
    health_polls: int = 18,
) -> None:
    app = find_frontend(request)
    if app is None:
        raise ValueError("brak aplikacji " + APP_NAME)
    response = request("POST", "deploy?uuid=" + app["uuid"] + "&force=false")
    deployment_uuid = response["deployments"][0]["deployment_uuid"]
    deployment: dict[str, Any] = {}
    status = "unknown"
    for _ in range(polls):
        deployment = request("GET", "deployments/" + deployment_uuid) or {}
        status = deployment.get("status", "unknown")
        if status in {"finished", "failed", "cancelled-by-user"}:
            break
        time.sleep(poll_seconds)
    print("wdrożenie frontu: " + status)
    if status != "finished":
        raise ValueError("wdrożenie nie skończyło się sukcesem")

    # SHA repozytorium jest publiczne, więc można je wypisać.
    commit = str(deployment.get("commit") or "")
    print("commit wdrożenia: " + (commit[:12] or "brak"))
    if expected_sha and commit != expected_sha:
        print("uwaga: main przesunął się od uruchomienia workflow (" + expected_sha[:12] + ")")
    built = built_sha_line(deployment.get("logs"), commit)
    print(
        "version.json z SHA wdrożenia w logu builda: "
        + {True: "tak", False: "NIE", None: "niepotwierdzone (brak logów)"}[built]
    )

    app_status = "unknown"
    for _ in range(health_polls):
        app_status = str((request("GET", "applications/" + app["uuid"]) or {}).get("status"))
        if app_status.startswith("running:healthy"):
            break
        time.sleep(poll_seconds)
    print("stan kontenera frontu: " + app_status)
    if built is False:
        raise ValueError("obraz frontu nie ma version.json z SHA wdrożenia")
    if not app_status.startswith("running:healthy"):
        raise ValueError("kontener frontu nie przeszedł healthchecku")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    base = os.environ["CO_URL"].rstrip("/")
    token = os.environ["CO_TOKEN"]
    source_uuid = os.environ["APP_UUID"]
    if mode not in {"plan", "create", "deploy"} or not base.startswith("https://"):
        print("NEXUS_FRONTEND_APP_FAILED: zły tryb albo adres", file=sys.stderr)
        return 1
    if not re.fullmatch(r"[A-Za-z0-9_-]+", source_uuid):
        print("NEXUS_FRONTEND_APP_FAILED: zły identyfikator aplikacji", file=sys.stderr)
        return 1

    def request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        req = urllib.request.Request(
            base + "/api/v1/" + path,
            method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    try:
        if mode == "plan":
            plan(request, source_uuid)
        elif mode == "create":
            create(request, source_uuid)
        else:
            deploy(request, os.environ.get("EXPECTED_SHA", ""))
    except urllib.error.HTTPError as error:
        print("NEXUS_FRONTEND_APP_FAILED: HTTP " + str(error.code), file=sys.stderr)
        return 1
    except ValueError as error:
        print("NEXUS_FRONTEND_APP_FAILED: " + str(error), file=sys.stderr)
        return 1
    except Exception as error:
        # Treść odpowiedzi API i wyjątków może zawierać dane uwierzytelniające.
        print("NEXUS_FRONTEND_APP_FAILED: " + type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
