"""Flagi stagingu obok flag produkcji, z zaznaczeniem tych, których dotyka diff gałęzi.

Krok 0 skilla `/sciezka` i warunek bramki `sciezka-stagingu-gate.js`: 25.11.2026
Nowe CV było na stagingu wyłączone (`CV_NEW_LAYOUT_ENABLED`), a na produkcji
włączone, więc ścieżka na stagingu pokazywała inny ekran niż u rekruterów.

Wypisuje tabelę Markdown `| flaga | staging | prod | w diffie? |`, którą skill
wkleja do paragonu. Kod wyjścia 1, gdy różni się flaga, której nazwa pada w diffie.

    python3 scripts/staging/compare_flags.py --ssh-host <host> --ssh-identity <klucz>
    python3 scripts/staging/compare_flags.py --diff origin/main...HEAD --ssh-host … --ssh-identity …

Odczyt produkcji idzie tą samą drogą co `nightly_sync.py` (filtr sekretów po
stronie serwera). Wartości, które nie są bool ani liczbą, nie są porównywane.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLAG_NAME = re.compile(r"\b[A-Z][A-Z0-9_]*_(ENABLED|SIZE|LIMIT|IDS)\b")


def _sync():
    spec = importlib.util.spec_from_file_location("nightly_sync", HERE / "nightly_sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def flags_in_diff(diff_text: str) -> set[str]:
    return {m.group(0) for m in FLAG_NAME.finditer(diff_text)}


def compare(staging: dict, prod: dict, touched: set[str]) -> tuple[list[tuple], bool]:
    """Wiersze (flaga, staging, prod, w diffie) tylko dla flag, które się różnią
    albo których dotyka diff. Drugi element: czy jest różnica blokująca."""
    rows: list[tuple] = []
    blocking = False
    for name in sorted(staging.keys() | prod.keys()):
        s, p = staging.get(name), prod.get(name)
        if not isinstance(s, (bool, int, float)) or not isinstance(p, (bool, int, float)):
            if name not in touched:
                continue
        differs = s != p
        in_diff = name in touched
        if not differs and not in_diff:
            continue
        if differs and in_diff:
            blocking = True
        rows.append((name, s, p, "tak → blokada" if differs and in_diff else ("tak" if in_diff else "nie")))
    return rows, blocking


def fmt(v) -> str:
    return "brak" if v is None else str(v).lower() if isinstance(v, bool) else str(v)


def render(rows: list[tuple]) -> str:
    out = ["| flaga | staging | prod | w diffie? |", "|---|---|---|---|"]
    out += [f"| {n} | {fmt(s)} | {fmt(p)} | {d} |" for n, s, p, d in rows]
    if len(out) == 2:
        out.append("| (brak różnic) | – | – | – |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ssh-host", required=True)
    ap.add_argument("--ssh-identity", required=True, type=Path)
    ap.add_argument("--diff", default="origin/main...HEAD", help="zakres gita; pusty = bez diffu")
    args = ap.parse_args()

    diff_text = ""
    if args.diff:
        diff_text = subprocess.run(["git", "diff", args.diff], capture_output=True, text=True, check=True).stdout
    touched = flags_in_diff(diff_text)

    sync = _sync()
    cfg = sync.Config(argparse.Namespace(ssh_host=args.ssh_host, ssh_identity=args.ssh_identity))
    names = tuple(sorted(touched))
    prod = sync.read_prod_settings(cfg, names)
    staging = sync.read_staging_settings(names)
    rows, blocking = compare(staging, prod, touched)
    print(render(rows))
    if blocking:
        print(
            "\nRóżni się flaga z diffu: ustaw ją w .env.staging-flags.local i przebuduj backend gałęzi.",
            file=sys.stderr,
        )
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
