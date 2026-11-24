"""Obecność między dwoma procesami web (test na stagingu, uruchamiany w kontenerze).

Dwie osoby, każda z gniazdem w INNYM procesie uvicorna (sprawdzane przez /proc),
oglądają tę samą kartę. Każda musi zobaczyć drugą. Potem druga zamyka gniazdo
i pierwsza musi zobaczyć, że została sama. Tokeny i nazwiska nie są wypisywane.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import websockets

URL = "ws://127.0.0.1:8000/ws/notifications"
RESOURCE = {"resource_type": "candidate", "resource_id": 990777}


def server_pids() -> list[int]:
    out = subprocess.run(["ps", "-eo", "pid,ppid,args"], capture_output=True, text=True)
    return [
        int(line.split()[0])
        for line in out.stdout.splitlines()[1:]
        if line.split()[1] == "1" and "spawn_main" in line
    ]


def owner_pid(client_port: int, pids: list[int]) -> int | None:
    inode = None
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            rows = open(table).read().splitlines()[1:]
        except FileNotFoundError:
            continue
        for row in rows:
            cols = row.split()
            local, remote = cols[1], cols[2]
            if local.endswith(":1F40") and int(remote.split(":")[1], 16) == client_port:
                inode = cols[9]
    if inode is None:
        return None
    for pid in pids:
        for fd in os.listdir(f"/proc/{pid}/fd"):
            try:
                if os.readlink(f"/proc/{pid}/fd/{fd}") == f"socket:[{inode}]":
                    return pid
            except OSError:
                continue
    return None


def run(*args: str) -> str:
    return subprocess.run(
        [sys.executable, "-m", "scripts.staging_login_as", *args],
        capture_output=True,
        text=True,
        check=True,
        cwd="/app",
    ).stdout


async def open_on(token: str, want_pid: int | None, avoid_pid: int | None, pids):
    for _ in range(40):
        ws = await websockets.connect(URL, subprotocols=["access_token", token])
        port = ws.transport.get_extra_info("sockname")[1]
        await asyncio.sleep(0.2)
        pid = owner_pid(port, pids)
        if (want_pid is None or pid == want_pid) and pid != avoid_pid and pid:
            return ws, pid
        await ws.close()
    raise RuntimeError("nie udało się trafić w wybrany proces")


async def viewers_seen(ws, expect: set[int], seconds: float = 8.0) -> set[int]:
    last: set[int] = set()
    deadline = asyncio.get_running_loop().time() + seconds
    while True:
        left = deadline - asyncio.get_running_loop().time()
        if left <= 0:
            return last
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=left)
        except asyncio.TimeoutError:
            return last
        msg = json.loads(raw)
        if (
            msg.get("type") == "presence:update"
            and msg.get("resource_id") == RESOURCE["resource_id"]
        ):
            last = {v["user_id"] for v in msg["viewers"]}
            if last == expect:
                return last


async def main() -> None:
    pids = server_pids()
    assert len(pids) == 2, pids
    ids = [
        int(line.split("\t")[0])
        for line in run("--role", "recruiter").splitlines()
        if line[:1].isdigit()
    ]
    a_id, b_id = ids[0], ids[1]
    a_token, b_token = (
        run("--user-id", str(a_id)).strip(),
        run("--user-id", str(b_id)).strip(),
    )

    ws_a, pid_a = await open_on(a_token, None, None, pids)
    ws_b, pid_b = await open_on(b_token, None, pid_a, pids)
    print(f"osoba A: gniazdo w procesie {pid_a}; osoba B: w procesie {pid_b}")

    await ws_a.send(json.dumps({"type": "presence:subscribe", **RESOURCE}))
    await asyncio.sleep(0.5)
    await ws_b.send(json.dumps({"type": "presence:subscribe", **RESOURCE}))
    both = {a_id, b_id}
    seen_b = await viewers_seen(ws_b, both)
    seen_a = await viewers_seen(ws_a, both)
    print(f"A widzi obie osoby: {seen_a == both}; B widzi obie osoby: {seen_b == both}")

    await ws_b.close()
    seen_a_after = await viewers_seen(ws_a, {a_id})
    print(f"po zamknięciu gniazda B: A widzi tylko siebie: {seen_a_after == {a_id}}")
    await ws_a.close()
    ok = seen_a == both and seen_b == both and seen_a_after == {a_id} and pid_a != pid_b
    print("WYNIK:", "OK" if ok else "BŁĄD")


asyncio.run(main())
