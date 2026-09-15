"""Odczyt czasów faz startu z logów kontenera przepuszcza WYŁĄCZNIE `[startup-timing]`.

Logi Actions są publiczne, a log kontenera backendu niesie wszystko (JSON
żądań, ostrzeżenia z danymi). Skrypt ``.github/scripts/startup-timing-logs.py``
ma zwrócić nazwy faz i sekundy ostatniego startu — nic więcej.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

_SCRIPTS = Path(__file__).parents[2] / ".github/scripts"
_SPEC = importlib.util.spec_from_file_location(
    "startup_timing_logs", _SCRIPTS / "startup-timing-logs.py"
)
timing = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(timing)

_ENTRYPOINT = Path(__file__).parents[1] / "entrypoint.sh"

LOGS = """\
2026-09-15T08:20:00Z [startup-timing] wait-for-db: 9s
2026-09-15T08:20:00Z [startup-timing] total before uvicorn: 99s
2026-09-15T08:24:01Z === Nexus ATS Backend Starting (as appuser) ===
2026-09-15T08:24:03Z [startup-timing] wait-for-db: 2s
2026-09-15T08:24:10Z [startup-timing] alembic-upgrade: 7s
2026-09-15T08:24:40Z [startup-timing]   safety-net enum+column DDL: 12.4s
2026-09-15T08:24:58Z [startup-timing]   safety-net data statements + seeds: 18.0s
2026-09-15T08:25:00Z {"event":"http_outcome","path":"/api/candidates/42","email":"jan@example.com"}
2026-09-15T08:25:01Z [startup-timing] safety-net-ddl-data-indexes: 31s
2026-09-15T08:25:04Z [startup-timing] seed: 3s
2026-09-15T08:25:04Z WARNING something [startup-timing] fake: jan@example.com
2026-09-15T08:25:05Z [startup-timing] total before uvicorn: 44s
"""


def test_projects_last_boot_sorted_by_duration() -> None:
    result = timing.project(LOGS)
    assert result["boot_found"] is True
    assert result["complete"] is True
    assert result["total_seconds"] == 44
    assert [p["phase"] for p in result["top_phases"]] == [
        "safety-net-ddl-data-indexes",
        "alembic-upgrade",
        "seed",
        "wait-for-db",
    ]
    assert [p["phase"] for p in result["top_safety_net_steps"]] == [
        "safety-net data statements + seeds",
        "safety-net enum+column DDL",
    ]


def test_no_other_log_content_leaks() -> None:
    dumped = json.dumps(timing.project(LOGS))
    assert "example.com" not in dumped
    assert "candidates" not in dumped
    assert "fake" not in dumped


def test_every_entrypoint_phase_label_matches_the_pattern() -> None:
    """Nowa faza w entrypoincie nie może cicho wypaść z raportu przez wzorzec."""
    src = _ENTRYPOINT.read_text(encoding="utf-8")
    labels = [l for l in re.findall(r'startup_phase "([^"]*)"', src) if l]
    labels += [f"safety-net {l}" for l in re.findall(r'_timing\("([^"]+)"', src)]
    assert labels, "wzorzec testu nie znalazł faz w entrypoincie"
    for label in labels:
        indent = "   " if label.startswith("safety-net ") and " " in label else " "
        line = f"[startup-timing]{indent}{label}: 1s"
        assert timing._LINE.search(line), label


def test_missing_boot_marker_is_reported() -> None:
    result = timing.project("nothing here\n")
    assert result == {
        "boot_found": False,
        "complete": False,
        "total_seconds": None,
        "top_phases": [],
        "top_safety_net_steps": [],
    }
