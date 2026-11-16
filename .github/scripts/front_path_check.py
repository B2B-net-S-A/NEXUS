"""Ścieżka użytkownika przez front: bramka przepięć i sprawdzenie po wdrożeniu.

13.11.2026 front przepięty na osobną aplikację Coolify przeszedł healthcheck
(`wget /`), a nie widział backendu: logowanie Microsoft kończyło się
`/login?error=backend_unreachable` przez ok. godzinę. Healthcheck kontenera nie
sprawdza drogi front → backend, więc robi to ten moduł, z zewnątrz, tak jak
przeglądarka:

- ``/version.json`` — 200 i SHA wdrożenia (to ten kontener, nie stary),
- ``/auth/microsoft/callback?error=access_denied`` — przekierowanie wystawione
  przez backend; ``backend_unreachable`` w adresie = front nie dosięga backendu,
- ``/login`` — 200 (strona renderowana przez Next).

Przed przepięciem nowy kontener ma tylko adres próbny ``CHECK_HOST`` (router HTTP
Traefika, bez certyfikatu i bez rekordu DNS), więc sprawdzamy go po IP serwera
z nagłówkiem ``Host`` — ruch użytkowników go nie dotyka. Logi Actions są
publiczne: na wyjście trafiają ścieżki i kody, nigdy adres serwera ani treść
odpowiedzi.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from typing import Callable

# Adres próbny nowego kontenera przed przepięciem: tylko router HTTP po nagłówku Host.
CHECK_HOST = "front-check.nexus.b2bnetwork.pl"
CALLBACK_PATH = "/auth/microsoft/callback?error=access_denied"
BROKEN_MARK = "backend_unreachable"

# Ten sam UA co sondy w deploy.yml (SMOKE_UA). Domyślny `Python-urllib` z runnera
# dostawał 403 na działającym froncie (13.11.2026), więc Deploy był czerwony bez awarii.
USER_AGENT = "dynaminds-smoke-test/1.0 (+github-actions; nexus)"

# (status, nagłówki małymi literami, ciało); status 0 = brak połączenia.
Fetch = Callable[[str, "str | None"], tuple[int, dict[str, str], bytes]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def fetch(url: str, host: str | None = None) -> tuple[int, dict[str, str], bytes]:
    headers = {"User-Agent": USER_AGENT}
    if host:
        headers["Host"] = host
    request = urllib.request.Request(url, headers=headers)
    try:
        with _OPENER.open(request, timeout=10) as response:
            headers = {k.lower(): v for k, v in response.headers.items()}
            return response.status, headers, response.read(4096)
    except urllib.error.HTTPError as error:
        return error.code, {k.lower(): v for k, v in error.headers.items()}, b""
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError):
        return 0, {}, b""


def check_paths(get: Fetch, base: str, host: str | None, commit: str) -> list[str]:
    """Lista usterek ścieżki (pusta = front działa jak dla użytkownika)."""
    base = base.rstrip("/")
    failures = []
    status, _, body = get(base + "/version.json", host)
    if status != 200:
        failures.append(f"/version.json: HTTP {status}")
    elif commit:
        try:
            sha = json.loads(body or b"{}").get("sha")
        except ValueError:
            sha = None
        if sha != commit:
            failures.append("/version.json: inny commit niż wdrożenie")
    status, headers, _ = get(base + CALLBACK_PATH, host)
    location = headers.get("location") or ""
    if status not in (301, 302, 303, 307, 308) or not location:
        failures.append(f"callback logowania Microsoft: HTTP {status}")
    elif BROKEN_MARK in location:
        failures.append("callback logowania Microsoft: front nie widzi backendu (" + BROKEN_MARK + ")")
    status, _, _ = get(base + "/login", host)
    if status != 200:
        failures.append(f"/login: HTTP {status}")
    return failures


def watch(
    get: Fetch,
    base: str,
    commit: str,
    seconds: float,
    every: float,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    """Obserwacja po przepięciu: usterka w dwóch kolejnych rundach = przerwij.

    Jedna nieudana runda bywa chwilą przełączania kontenerów (retry Traefika ją
    zwykle łapie); dwie z rzędu to już stan, który widzą użytkownicy.
    """
    rounds = max(1, int(seconds // every) if every > 0 else 1)
    previous: list[str] = []
    for index in range(rounds):
        failures = check_paths(get, base, None, commit)
        if failures and previous:
            return failures
        previous = failures
        if index < rounds - 1:
            sleep(every)
    return previous


def report(label: str, failures: list[str]) -> None:
    if not failures:
        print(f"ścieżka użytkownika ({label}): version.json, logowanie Microsoft, /login — OK")
        return
    print(f"ścieżka użytkownika ({label}): USTERKI")
    for failure in failures:
        print("  - " + failure)
