"""Czasy faz startu backendu z logów kontenera — tylko linie `[startup-timing]`.

`backend/entrypoint.sh` wypisuje czas każdej fazy przed `exec uvicorn`
(reaudyt 14.09.2026). Bez dostępu SSH jedyną drogą do tych liczb jest API logów
Coolify. Logi Actions są PUBLICZNE, więc do wyjścia trafia wyłącznie nazwa fazy
(tekst z naszego skryptu) i liczba sekund dopasowane ścisłym wzorcem — żadna
inna linia logu kontenera. Plan skracania przerwy przy deployu (Etap 0).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "cv_ops", Path(__file__).with_name("cv-quality-ops.py")
)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)

_LINE = re.compile(
    r"\[startup-timing\](?P<indent>\s+)(?P<phase>[A-Za-z0-9][A-Za-z0-9 _./+-]{0,80}): "
    r"(?P<seconds>\d{1,5}(?:\.\d)?)s\s*$"
)
FIRST_PHASE = "wait-for-db"
TOTAL_PHASE = "total before uvicorn"


def project(logs: str) -> dict:
    """Fazy OSTATNIEGO startu (od ostatniego `wait-for-db`), posortowane malejąco."""
    entries = []
    for line in logs.splitlines():
        match = _LINE.search(line)
        if not match:
            continue
        entries.append(
            {
                "phase": match.group("phase").strip(),
                "seconds": float(match.group("seconds")),
                # Podfazy siatki DDL są wcięte dodatkowymi spacjami.
                "sub": len(match.group("indent")) > 1,
            }
        )
    starts = [i for i, e in enumerate(entries) if e["phase"] == FIRST_PHASE and not e["sub"]]
    boot = entries[starts[-1]:] if starts else entries
    total = next((e["seconds"] for e in boot if e["phase"] == TOTAL_PHASE), None)
    phases = [e for e in boot if e["phase"] != TOTAL_PHASE]
    return {
        "boot_found": bool(starts),
        "complete": total is not None,
        "total_seconds": total,
        "top_phases": sorted(
            (e for e in phases if not e["sub"]), key=lambda e: -e["seconds"]
        )[:10],
        "top_safety_net_steps": sorted(
            (e for e in phases if e["sub"]), key=lambda e: -e["seconds"]
        )[:10],
    }


def main() -> None:
    api = ops.Api(os.environ)
    app = ops.checked(os.environ["APP_UUID"], r"[A-Za-z0-9-]{1,80}")
    response = api.request("GET", f"/api/v1/applications/{app}/logs?lines=10000")
    if not isinstance(response, dict) or not isinstance(response.get("logs"), str):
        raise ops.OpsError("invalid_log_response")
    print(json.dumps(project(response["logs"]), indent=2))


if __name__ == "__main__":
    try:
        main()
    except ops.OpsError as exc:
        print(json.dumps({"error": str(exc)}))
        raise SystemExit(2) from None
