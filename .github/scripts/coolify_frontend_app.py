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

Tryby: ``plan`` (tylko odczyt), ``create``, ``deploy`` (próbne, z ``COMMIT``),
``switch`` (domeny frontu z compose na aplikację), ``rollback`` i ``stop`` (wycofanie),
``preflight``, ``trigger`` i ``wait`` (kroki workflow Deploy). Logi Actions są publiczne,
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
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from coolify_labels import SHUTDOWN_SETTINGS, decode_labels, encode_labels, with_retry  # noqa: E402

APP_NAME = "nexus-frontend"
BRANCH = "main"
NETWORK = "nexus-front"
COMPOSE_SERVICE = "frontend"
MODES = {"plan", "create", "deploy", "switch", "rollback", "stop", "preflight", "trigger", "wait"}
COMPOSE_NETWORK_RE = re.compile(r"(?ms)^networks:\s*\n(?:[ \t].*\n|\s*\n)*?  nexus-front:")
REDIRECTS = {"www", "non-www", "both"}
SHA_RE = re.compile(r"[0-9a-f]{40}")
UUID_RE = re.compile(r"[A-Za-z0-9_-]+")
# Retry Traefika i łagodne wyłączanie: .github/scripts/coolify_labels.py
RETRY_MIDDLEWARE = "nexus-front-retry"

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
    domains = compose_domains(source)
    front = str((domains.get(COMPOSE_SERVICE) or {}).get("domain") or "")
    print("usługi compose z domeną: " + (", ".join(sorted(domains)) or "brak"))
    print(f"domeny frontu w compose: {len([d for d in front.split(',') if d.strip()])}")


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


def trigger(request: Request, commit: str) -> str:
    """Wdrożenie frontu dokładnie z `commit`.

    Coolify 4.5.3 bierze `git_commit_sha` aplikacji jako commit wdrożenia
    (`queue_application_deployment`); bez przypięcia budowałby HEAD maina z chwili
    startu, który bywa nowszy niż commit backendu i `version.json` by się rozjechał.
    """
    if not SHA_RE.fullmatch(commit):
        raise ValueError("commit frontu musi mieć 40 znaków hex")
    app = find_frontend(request)
    if app is None:
        raise ValueError("brak aplikacji " + APP_NAME)
    request("PATCH", "applications/" + app["uuid"], {"git_commit_sha": commit})
    response = request("POST", "deploy?uuid=" + app["uuid"] + "&force=false")
    deployment_uuid = (response.get("deployments") or [{}])[0].get("deployment_uuid")
    if not deployment_uuid:
        raise ValueError("Coolify nie przyjął wdrożenia frontu")
    print("wdrożenie frontu w kolejce, commit " + commit[:12])
    return deployment_uuid


def compose_commit(
    request: Request, deployment_uuid: str, poll_seconds: float = 5.0, polls: int = 180
) -> str:
    """Commit, który buduje wdrożenie compose (Coolify ustala go dopiero po starcie)."""
    for _ in range(polls):
        deployment = request("GET", "deployments/" + deployment_uuid) or {}
        commit = str(deployment.get("commit") or "")
        if SHA_RE.fullmatch(commit):
            return commit
        if deployment.get("status") in {"failed", "cancelled-by-user"}:
            raise ValueError("wdrożenie compose padło, front zostaje na starej wersji")
        time.sleep(poll_seconds)
    raise ValueError("wdrożenie compose nie ustaliło commitu w czasie")


def wait(
    request: Request,
    deployment_uuid: str,
    poll_seconds: float = 10.0,
    polls: int = 120,
    health_polls: int = 18,
) -> None:
    app = find_frontend(request)
    if app is None:
        raise ValueError("brak aplikacji " + APP_NAME)
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


def deploy(request: Request, commit: str, **timing: Any) -> None:
    wait(request, trigger(request, commit), **timing)


def compose_domains(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = source.get("docker_compose_domains") or "{}"
    data = json.loads(raw) if isinstance(raw, str) else raw
    return data if isinstance(data, dict) else {}


def domain_rows(domains: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Format PATCH: Coolify zastępuje całą listę, więc idą wszystkie usługi."""
    rows = []
    for name, entry in domains.items():
        row = {"name": name, "domain": str(entry.get("domain") or "")}
        if entry.get("redirect") in REDIRECTS:
            row["redirect"] = entry["redirect"]
        rows.append(row)
    return rows


def compose_has_network(source: dict[str, Any]) -> bool:
    """Czy wczytany compose dołącza sieć `nexus-front` (bez niej front nie widzi `backend`)."""
    return bool(COMPOSE_NETWORK_RE.search(str(source.get("docker_compose_raw") or "") + "\n"))


def preflight(request: Request, source_uuid: str, front_required: bool) -> None:
    """Bramka Deploy PRZED wyzwoleniem compose.

    Coolify najpierw zatrzymuje wszystkie kontenery compose, a dopiero przy `up`
    odkrywa brak sieci zewnętrznej — wtedy leży cała produkcja. Po przepięciu
    (`front_required`) compose nie ma już frontu, więc front musi mieć domeny.
    """
    source = request("GET", "applications/" + source_uuid)
    server = ((source.get("destination") or {}).get("server") or {}).get("uuid")
    if not server or not find_network(request, server):
        raise ValueError("brak sieci " + NETWORK + " — najpierw mode=create, compose nie rusza")
    print("sieć " + NETWORK + ": jest")
    if not front_required:
        return
    app = find_frontend(request)
    detail = request("GET", "applications/" + app["uuid"]) if app else {}
    if not str((detail or {}).get("fqdn") or ""):
        raise ValueError("aplikacja frontu nie ma domen — najpierw mode=switch, compose nie rusza")
    if (compose_domains(source).get(COMPOSE_SERVICE) or {}).get("domain"):
        raise ValueError("compose ma jeszcze domeny frontu — najpierw mode=switch, compose nie rusza")
    print("front: osobna aplikacja z domenami, compose bez domen frontu")


def deploy_target(request: Request) -> str | None:
    """UUID aplikacji frontu, którą Deploy ma wdrożyć; None = front jeszcze w compose."""
    app = find_frontend(request)
    if app is None:
        return None
    detail = request("GET", "applications/" + app["uuid"]) or {}
    return app["uuid"] if str(detail.get("fqdn") or "") else None


def set_domains(request: Request, app_uuid: str, domains: str, redirect: Any) -> None:
    """Domeny + etykiety z retry; dalej etykiety trzyma aplikacja, nie Coolify.

    Przy `is_container_label_readonly_enabled=true` Coolify przepisuje etykiety
    z domen przy każdym PATCH domen, więc najpierw generuje je on, potem dokładamy
    retry i wyłączamy przepisywanie (inaczej zmiana domen zgubiłaby retry).
    """
    path = "applications/" + app_uuid
    payload: dict[str, Any] = {
        "domains": domains,
        "force_domain_override": True,
        "is_container_label_readonly_enabled": True,
    }
    if redirect in REDIRECTS:
        payload["redirect"] = redirect
    request("PATCH", path, payload)
    labels = with_retry(
        decode_labels((request("GET", path) or {}).get("custom_labels")), RETRY_MIDDLEWARE
    )
    request(
        "PATCH",
        path,
        {
            "custom_labels": encode_labels(labels),
            "is_container_label_readonly_enabled": False,
            **SHUTDOWN_SETTINGS,
        },
    )
    chained = [label for label in labels if ".routers." in label and RETRY_MIDDLEWARE in label]
    print(f"etykiety frontu: {len(labels)}, routery z retry: {len(chained)}")


def switch(request: Request, source_uuid: str, commit: str, **timing: Any) -> None:
    """Przepięcie domen frontu z compose na `nexus-frontend` bez przerwy.

    1. Aplikacja frontu dostaje domeny i wdraża się (rolling update) — od tej
       chwili Traefik ma dla nich dwa zdrowe kontenery.
    2. Compose traci domeny frontu; stary kontener znika z routingu przy
       najbliższym wdrożeniu compose (PR usuwający usługę `frontend`).
    """
    path = "applications/" + source_uuid
    app = find_frontend(request)
    if app is None:
        raise ValueError("brak aplikacji " + APP_NAME)
    source = request("GET", path)
    if not compose_has_network(source):
        raise ValueError("wdrożony compose nie ma sieci " + NETWORK + " — front nie zobaczy backendu")
    domains = compose_domains(source)
    front = domains.get(COMPOSE_SERVICE) or {}
    if not front.get("domain"):
        raise ValueError("compose nie ma domen frontu — przepięcie już zrobione?")
    set_domains(request, app["uuid"], front["domain"], front.get("redirect"))
    deploy(request, commit, **timing)
    rest = {name: entry for name, entry in domains.items() if name != COMPOSE_SERVICE}
    request("PATCH", path, {"docker_compose_domains": domain_rows(rest)})
    count = len([d for d in str(front["domain"]).split(",") if d.strip()])
    print(f"przeniesiono domen frontu: {count}; compose zachowuje: {', '.join(sorted(rest))}")


def rollback(request: Request, source_uuid: str) -> None:
    """Domeny frontu wracają do usługi `frontend` w compose.

    Coolify przyjmuje domenę tylko dla usługi z wczytanego compose, więc najpierw
    wdrożony musi być compose z usługą `frontend` (revert PR-a z przepięciem).
    Do kolejnego wdrożenia compose ruch dalej obsługuje `nexus-frontend`.
    """
    path = "applications/" + source_uuid
    app = find_frontend(request)
    if app is None:
        raise ValueError("brak aplikacji " + APP_NAME)
    source = request("GET", path)
    services = str(source.get("docker_compose_raw") or "")
    if not re.search(r"(?m)^  " + COMPOSE_SERVICE + r":\s*$", services):
        raise ValueError("wczytany compose nie ma usługi frontend — najpierw revert i Deploy")
    detail = request("GET", "applications/" + app["uuid"]) or {}
    fqdn = str(detail.get("fqdn") or "")
    if not fqdn:
        raise ValueError("aplikacja frontu nie ma domen — nic do cofnięcia")
    domains = compose_domains(source)
    entry: dict[str, Any] = {"domain": fqdn}
    if detail.get("redirect") in REDIRECTS:
        entry["redirect"] = detail["redirect"]
    domains[COMPOSE_SERVICE] = entry
    request("PATCH", path, {"docker_compose_domains": domain_rows(domains), "force_domain_override": True})
    print("domeny frontu wpisane z powrotem do compose; teraz Deploy z force_rebuild=true, potem stop")


def stop(request: Request) -> None:
    app = find_frontend(request)
    if app is None:
        raise ValueError("brak aplikacji " + APP_NAME)
    request("POST", "applications/" + app["uuid"] + "/stop")
    print("zatrzymano " + APP_NAME)


def write_output(name: str, value: str) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    base = os.environ["CO_URL"].rstrip("/")
    token = os.environ["CO_TOKEN"]
    source_uuid = os.environ["APP_UUID"]
    commit = os.environ.get("COMMIT") or os.environ.get("EXPECTED_SHA", "")
    if mode not in MODES or not base.startswith("https://"):
        print("NEXUS_FRONTEND_APP_FAILED: zły tryb albo adres", file=sys.stderr)
        return 1
    if not UUID_RE.fullmatch(source_uuid):
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
        elif mode == "deploy":
            deploy(request, commit)
        elif mode == "switch":
            switch(request, source_uuid, commit)
        elif mode == "rollback":
            rollback(request, source_uuid)
        elif mode == "stop":
            stop(request)
        elif mode == "preflight":
            preflight(request, source_uuid, os.environ.get("FRONTEND_APP_REQUIRED") == "true")
        elif mode == "trigger":
            # Deploy, po udanym compose: front z tego samego commitu co backend.
            compose = os.environ.get("COMPOSE_DEPLOYMENT_UUID", "")
            if not UUID_RE.fullmatch(compose):
                raise ValueError("brak COMPOSE_DEPLOYMENT_UUID")
            if deploy_target(request) is None:
                print("front jeszcze w compose (aplikacja bez domen) — pomijam")
                write_output("deployment_uuid", "")
            else:
                write_output("deployment_uuid", trigger(request, compose_commit(request, compose)))
        else:
            deployment = os.environ.get("FRONTEND_DEPLOYMENT_UUID", "")
            if not UUID_RE.fullmatch(deployment):
                raise ValueError("brak FRONTEND_DEPLOYMENT_UUID")
            wait(request, deployment)
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
