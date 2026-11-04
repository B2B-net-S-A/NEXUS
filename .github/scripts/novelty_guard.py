#!/usr/bin/env python3
"""Strażnik Nowości na PR-ze (30.10.2026).

Od 28.10 każda nowość, którą ludzie mają zauważyć, to wpis w
``backend/app/data/novelties/novelties.json`` w PR-ze, który ją wdraża
(``docs/claude/ui/nowosci-do-przeklikania.md``). Reguły nikt nie stosował:
od 26 do 29.10 na main weszło ok. 90 commitów ``feat``, a rejestr miał trzy
wpisy. Decyzja Artura z 30.10.2026: sito na PR-ze ma to łapać.

PR z tytułem ``feat…``, który zmienia ekrany (``frontend/src`` poza testami
i harnessami ``/preview``), przechodzi, gdy dopisuje wpis do rejestru albo
ma w opisie osobną linię ``Nowość: nie — <powód>``. Tytuł, opis i pliki
czytamy z API w chwili biegu, nie z migawki zdarzenia, więc po dopisaniu
linii wystarczy ponowić job.

Wejście: ``PR``, ``REPO`` i ``GH_TOKEN`` w środowisku. Błąd API = ostrzeżenie
i kod 0: strażnik nie może zatrzymać PR-a z powodu awarii GitHuba.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Iterable, Optional

REGISTRY = "backend/app/data/novelties/novelties.json"
FEAT_TITLE = re.compile(r"^feat(\([^)]*\))?!?:", re.IGNORECASE)
OPT_OUT = re.compile(r"^\s*nowość:\s*nie\s*[—–-]\s*\S.{2,}$", re.IGNORECASE | re.MULTILINE)
SCREEN_PREFIX = "frontend/src/"
NOT_SCREEN = re.compile(r"(/__tests__/|\.test\.[jt]sx?$|\.spec\.[jt]sx?$|^frontend/src/app/preview/)")


def changes_screens(files: Iterable[str]) -> bool:
    return any(f.startswith(SCREEN_PREFIX) and not NOT_SCREEN.search(f) for f in files)


def verdict(title: str, body: Optional[str], files: list[str]) -> str:
    """Opis problemu albo pusty napis, gdy PR przechodzi."""
    if not FEAT_TITLE.match(title.strip()):
        return ""
    if REGISTRY in files or not changes_screens(files):
        return ""
    if OPT_OUT.search(body or ""):
        return ""
    return (
        "Nowości: PR „feat” zmienia ekrany, a nie dopisuje wpisu do "
        f"{REGISTRY}. Dopisz wpis (dot / tour / process, opis w "
        "docs/claude/ui/nowosci-do-przeklikania.md) albo dodaj w opisie PR-a "
        "osobną linię „Nowość: nie — <powód>” (np. „Nowość: nie — ekran tylko "
        "dla adminów”) i ponów ten job."
    )


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def main() -> int:
    pr, repo = os.environ.get("PR", ""), os.environ.get("REPO", "")
    try:
        meta = json.loads(_gh("api", f"repos/{repo}/pulls/{pr}"))
        files = _gh("api", "--paginate", f"repos/{repo}/pulls/{pr}/files", "--jq", ".[].filename").split()
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as exc:
        print(f"::warning::Strażnik Nowości nie odczytał PR-a #{pr}: {exc}")
        return 0
    problem = verdict(meta.get("title") or "", meta.get("body"), files)
    if problem:
        print(f"::error::{problem}")
        return 1
    print(f"PR #{pr}: Nowości w porządku.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
