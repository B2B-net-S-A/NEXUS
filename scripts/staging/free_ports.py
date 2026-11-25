"""Pierwsza wolna para portów dla frontu i backendu gałęzi: 3101–3199 i 8101–8199.

Decyzja Artura z 26.11.2026: każdy worktree bierze własną parę zamiast zawsze
3101/8101, bo w 30 dni było 12 błędów „Port already in use”, a sesje nadpisywały
sobie front gałęzi. Para idzie razem (3100+n, 8100+n), żeby z portu frontu było
widać, który backend jest jego.

    eval "$(python3 scripts/staging/free_ports.py)"   # ustawia FRONT_PORT i BACKEND_PORT

Port jest wolny, gdy da się na nim nasłuchiwać na 127.0.0.1 (tam publikuje Docker
i `next dev`). Dwie sesje w tej samej sekundzie mogą dostać tę samą parę; wtedy
`docker run` albo `next dev` zgłosi zajęty port i wystarczy uruchomić skrypt ponownie.
"""

from __future__ import annotations

import socket
import sys

FRONT_BASE, BACKEND_BASE, SLOTS = 3100, 8100, range(1, 100)


def is_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def free_pair(is_free=is_free) -> tuple[int, int] | None:
    for n in SLOTS:
        front, backend = FRONT_BASE + n, BACKEND_BASE + n
        if is_free(front) and is_free(backend):
            return front, backend
    return None


def main() -> int:
    pair = free_pair()
    if pair is None:
        print("Brak wolnej pary portów 3101–3199 / 8101–8199.", file=sys.stderr)
        return 1
    print(f"FRONT_PORT={pair[0]} BACKEND_PORT={pair[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
