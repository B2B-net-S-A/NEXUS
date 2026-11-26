"""Pierwsza wolna para portów dla frontu i backendu gałęzi: 3101–3199 i 8101–8199.

Decyzja Artura z 26.11.2026: każdy worktree bierze własną parę zamiast zawsze
3101/8101, bo w 30 dni było 12 błędów „Port already in use”, a sesje nadpisywały
sobie front gałęzi. Para idzie razem (3100+n, 8100+n), żeby z portu frontu było
widać, który backend jest jego.

    eval "$(python3 scripts/staging/free_ports.py)"   # ustawia FRONT_PORT i BACKEND_PORT

Port jest wolny, gdy da się na nim nasłuchiwać na 127.0.0.1 (tam publikuje Docker
i `next dev`). Dwie sesje w tej samej sekundzie mogą dostać tę samą parę; wtedy
`docker run` albo `next dev` zgłosi zajęty port i wystarczy uruchomić skrypt ponownie.

Para jest też zajęta, gdy na stagingu jest już baza `nexus_branch_<port backendu>`
albo kontener `nexus-staging-backend-branch-<port>` (także zatrzymany). Sesja ze
zmianą schematu przez kilka minut kopiuje bazę, zanim cokolwiek nasłuchuje, a 26.11.2026
następna sesja dostała w tym czasie ten sam port. Bez Dockera albo bez stagingu skrypt
sprawdza tylko gniazda.
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys

FRONT_BASE, BACKEND_BASE, SLOTS = 3100, 8100, range(1, 100)
POSTGRES = "nexus-staging-postgres-1"
_BRANCH_DB = re.compile(r"^nexus_branch_(\d+)$")
_BRANCH_CONTAINER = re.compile(r"^nexus-staging-backend-branch-(\d+)$")


def is_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def _lines(command: list[str]) -> list[str]:
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return done.stdout.splitlines() if done.returncode == 0 else []


def ports_from_names(names: list[str]) -> frozenset[int]:
    """Porty backendu z nazw baz i kontenerów gałęzi (inne nazwy pomija)."""

    ports = set()
    for name in names:
        match = _BRANCH_DB.match(name.strip()) or _BRANCH_CONTAINER.match(name.strip())
        if match:
            ports.add(int(match.group(1)))
    return frozenset(ports)


def staging_busy() -> frozenset[int]:
    """Porty backendu zajęte przez bazę albo kontener gałęzi na stagingu."""

    databases = _lines(
        [
            "docker",
            "exec",
            POSTGRES,
            "psql",
            "-U",
            "nexus",
            "-d",
            "postgres",
            "-Atc",
            "select datname from pg_database where datname like 'nexus_branch_%'",
        ]
    )
    containers = _lines(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            "name=nexus-staging-backend-branch-",
            "--format",
            "{{.Names}}",
        ]
    )
    return ports_from_names(databases + containers)


def free_pair(
    is_free=is_free, busy: frozenset[int] = frozenset()
) -> tuple[int, int] | None:
    for n in SLOTS:
        front, backend = FRONT_BASE + n, BACKEND_BASE + n
        if backend not in busy and is_free(front) and is_free(backend):
            return front, backend
    return None


def main() -> int:
    pair = free_pair(busy=staging_busy())
    if pair is None:
        print("Brak wolnej pary portów 3101–3199 / 8101–8199.", file=sys.stderr)
        return 1
    print(f"FRONT_PORT={pair[0]} BACKEND_PORT={pair[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
