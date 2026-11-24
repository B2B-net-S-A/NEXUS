"""Obciążenie + celowy zastój jednego procesu web (test na stagingu).

16 klientów z pulą połączeń keep-alive (jak Traefik) pyta w kółko o URL-e.
Po STALL_AT s wysyła SIGUSR1 do jednego procesu uvicorna w kontenerze:
sitecustomize.py kręci wtedy pętlę Pythona przez STALL_SECONDS (zastój pętli
zdarzeń przy wolnym GIL-u, jak 24.11.2026). Wynik: koszyki po 2 s wg startu
żądania i podsumowanie żądań rozpoczętych w czasie zastoju.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import subprocess
import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8142"
CONTAINER = sys.argv[2] if len(sys.argv) > 2 else "nexus-staging-backend-2web"
LABEL = sys.argv[3] if len(sys.argv) > 3 else "run"
PATHS = ["/api/health/live"]
CLIENTS = 16
DURATION = 60.0
STALL_AT = 10.0
STALL_SECONDS = 30.0
TIMEOUT = 30.0  # przeglądarka zrywa żądanie po ok. 30 s

records: list[tuple[float, float, str]] = []


def child_pids() -> list[int]:
    """PID-y procesów uvicorna, które obsługują HTTP (dzieci nadzorcy albo PID 1)."""
    out = subprocess.run(
        ["docker", "exec", CONTAINER, "ps", "-eo", "pid,ppid,args"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()[1:]
    procs = [line.split(None, 2) for line in out]
    children = [
        int(pid) for pid, ppid, args in procs if ppid == "1" and "spawn_main" in args
    ]
    return children or [1]


async def client(c: httpx.AsyncClient, t0: float, stop: float) -> None:
    i = 0
    while time.monotonic() < stop:
        path = PATHS[i % len(PATHS)]
        i += 1
        start = time.monotonic()
        try:
            r = await c.get(BASE + path)
            outcome = str(r.status_code)
        except httpx.TimeoutException:
            outcome = "timeout"
        except httpx.HTTPError as exc:
            outcome = type(exc).__name__
        records.append((start - t0, time.monotonic() - start, outcome))
        await asyncio.sleep(0.05)


async def stall_one(t0: float, info: dict) -> None:
    await asyncio.sleep(STALL_AT)
    pids = child_pids()
    target = pids[0]
    info["pids"] = pids
    info["stalled_pid"] = target
    info["stall_sent_at"] = round(time.monotonic() - t0, 2)
    subprocess.run(
        ["docker", "exec", CONTAINER, "kill", "-USR1", str(target)], check=True
    )


async def main() -> None:
    limits = httpx.Limits(max_connections=CLIENTS, max_keepalive_connections=CLIENTS)
    info: dict = {}
    async with httpx.AsyncClient(limits=limits, timeout=TIMEOUT) as c:
        t0 = time.monotonic()
        stop = t0 + DURATION
        await asyncio.gather(
            stall_one(t0, info), *(client(c, t0, stop) for _ in range(CLIENTS))
        )
    print(
        f"== {LABEL}: procesy web {info.get('pids')}, zablokowany {info.get('stalled_pid')}"
        f" od {info.get('stall_sent_at')} s na {STALL_SECONDS:.0f} s"
    )
    print(" koszyk  żądań  ok  >1s  błędy  p50_ms  max_ms")
    for b in range(0, int(DURATION), 2):
        rows = [r for r in records if b <= r[0] < b + 2]
        if not rows:
            print(f" {b:>3}-{b + 2:<3} {0:>5}")
            continue
        lat = [r[1] * 1000 for r in rows]
        ok = sum(1 for r in rows if r[2] == "200")
        slow = sum(1 for r in rows if r[1] > 1)
        err = sum(1 for r in rows if r[2] != "200")
        print(
            f" {b:>3}-{b + 2:<3} {len(rows):>5} {ok:>4} {slow:>4} {err:>6} "
            f"{statistics.median(lat):>7.0f} {max(lat):>7.0f}"
        )
    s0 = info.get("stall_sent_at", STALL_AT)
    during = [r for r in records if s0 + 1 <= r[0] < s0 + STALL_SECONDS - 1]
    summary = {
        "label": LABEL,
        "processes": len(info.get("pids") or []),
        "started_during_stall": len(during),
        "ok_within_1s": sum(1 for r in during if r[2] == "200" and r[1] <= 1),
        "slower_than_1s": sum(1 for r in during if r[1] > 1),
        "failed_or_timeout": sum(1 for r in during if r[2] != "200"),
        "max_latency_s": round(max((r[1] for r in during), default=0), 1),
    }
    print(json.dumps(summary, ensure_ascii=False))


asyncio.run(main())
