#!/usr/bin/env python3
"""Szybkie sprawdzenie stempli przeglądu — bez zapisu, sama biblioteka standardowa.

To samo, co ``tests/test_screen_guides_freshness.py`` i
``tests/test_orders_procedure_freshness.py`` sprawdzają w CI, tylko lokalnie
i w ułamku sekundy — żeby rozjechany stempel wyszedł przed commitem, a nie
dopiero w kolejce merge'ów:

    python3 backend/scripts/check_stamps.py               # wszystko
    python3 backend/scripts/check_stamps.py plik1 plik2   # tylko gdy któryś
                                                          # jest obserwowany

Hook pre-commit (``.pre-commit-config.yaml``, id ``review-stamps``) podaje
listę plików w commicie; bez obserwowanego pliku skrypt kończy się od razu.
Naprawa: ``cd backend && python3 scripts/stamp_screen_guides.py`` albo
``python3 scripts/stamp_orders_procedure.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.procedures import ORDERS_LOGIC_SOURCES  # noqa: E402
from app.data.review_stamps import (  # noqa: E402
    GUIDE_STAMPS_REL,
    GUIDES_HINT,
    GUIDES_REL,
    ORDERS_HINT,
    ORDERS_STAMPS_REL,
    REPO_ROOT,
    guide_drift,
    load_raw_guides,
    orders_drift,
    orders_watched,
    orphan_guide_stamps,
    stamped_orders_sources,
)


def _checkable(relative: str) -> bool:
    """Checkout bez frontu (np. sam backend) nie ma czego porównać."""
    return not relative.startswith("frontend/") or (REPO_ROOT / "frontend").is_dir()


def _watched_paths() -> set:
    guide_sources = {
        rel for entry in load_raw_guides().values() for rel in entry.get("sources", [])
    }
    return guide_sources | set(orders_watched()) | {GUIDES_REL}


def _relevant(paths: list) -> bool:
    watched = _watched_paths()
    stamp_dirs = (GUIDE_STAMPS_REL + "/", ORDERS_STAMPS_REL + "/")
    return any(p in watched or p.startswith(stamp_dirs) for p in paths)


def _guide_problems() -> list:
    problems = [
        f"{key} ({', '.join(reasons)})"
        for key, reasons in guide_drift(checkable=_checkable).items()
    ]
    problems.extend(f"{key} (stempel bez przewodnika)" for key in orphan_guide_stamps())
    return problems


def _orders_problems() -> list:
    problems = orders_drift(checkable=_checkable)
    declared = set(orders_watched(ORDERS_LOGIC_SOURCES))
    problems.extend(
        f"{rel} (stempel spoza listy ORDERS_LOGIC_SOURCES)"
        for rel in stamped_orders_sources()
        if rel not in declared
    )
    return problems


def main(argv: list) -> int:
    paths = [Path(p).as_posix() for p in argv]
    if paths and not _relevant(paths):
        return 0

    failed = False
    guides = _guide_problems()
    if guides:
        failed = True
        print(
            "Zmienił się ekran (albo przewodnik), a przewodnik Jarvisa nie został "
            "przejrzany:\n  · " + "\n  · ".join(guides) + GUIDES_HINT + "\n",
            file=sys.stderr,
        )
    orders = _orders_problems()
    if orders:
        failed = True
        print(
            "Zmieniła się logika procesu zamówień, a instrukcja w Pomoc → Procedury "
            "nie została od tego czasu przejrzana.\n\nZmienione pliki:\n  · "
            + "\n  · ".join(orders)
            + ORDERS_HINT
            + "\n",
            file=sys.stderr,
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
