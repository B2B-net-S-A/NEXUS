"""Mapa wpływu: inne miejsca, które pokazują tę samą informację co zmiana z gałęzi.

Decyzja Artura z 26.11.2026: przy każdej zmianie Claude myśli o całym systemie.
Gdy pole dochodzi na jednym ekranie, ta sama informacja zwykle żyje też w panelu
osoby, profilu, PDF-ie CV, Jarvisie i eksporcie — a rano rekruter zgłasza, że
„tu jest, a tam nie ma”.

Z diffu `origin/main...HEAD` bierze zmienione pola schematów API (pydantic, typy
TS), endpointy i komponenty, szuka ich użyć w `frontend/src` i w backendzie
(szablony PDF/Word/maili, Jarvis, eksporty, przewodniki ekranów) i wypisuje
tabelę `| Miejsce | Decyzja |` z pustą decyzją. Skill `/sciezka` wkleja ją do
paragonu, a hook `sciezka-stagingu-gate.js` sprawdza, że każde miejsce ma decyzję.

    python3 scripts/impact_map.py                 # tabela Markdown
    python3 scripts/impact_map.py --json          # lista kluczy miejsc (dla hooka)
    python3 scripts/impact_map.py --diff A...B

Pliki zmienione w diffie, testy i harnessy `/preview/*` nie są „innym miejscem”.
Pole TS liczy się w `interface`/`type` i w typie wpisanym w sygnaturę, nie we
właściwości obiektu (`timeout:`, `queryKey:`). Symbol z ponad `TOO_BROAD` miejscami ma nazwę zbyt
ogólną, żeby grep znalazł tę samą informację: dostaje jeden wiersz
`<symbol> · *` z decyzją zbiorczą zamiast wiersza na plik (PR #4058: nowy typ
z polami `text`, `source`, `company` dał 2797 miejsc, z których żadne nie
czytało nowej informacji).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import NamedTuple

SEARCH_ROOTS = ("frontend/src", "backend/app")
# Nazwy, które są w każdym pliku: ich użycia nic nie mówią o tej samej informacji.
# Ostatni wiersz: pomiar na PR #4058 (każde z tych słów: od 27 do 1937 miejsc).
GENERIC = frozenset(
    "id name type status data value label title key kind items count total page size "
    "created_at updated_at deleted_at user_id email notes description url path code "
    "message error result results detail children className props "
    "text source company token quote verified issue timeout".split()
)
# Więcej miejsc dla jednego symbolu = jeden wiersz zbiorczy. Mediana z 120 commitów
# maina (26.11.2026) to 22 miejsca na pole; powyżej 50 są już tylko słowa ogólne
# i identyfikatory w rodzaju `contract_id`, których nikt nie przegląda plik po pliku.
TOO_BROAD = 50
PY_FIELD = re.compile(r"^\s{4}([a-z_][a-z0-9_]*)\s*:\s*[^=\s]")
TS_FIELD = re.compile(r"^\s+([a-zA-Z_][a-zA-Z0-9_]*)\??\s*:\s*[^=\s]")
TS_TYPE_DECL = re.compile(r"^(?:export\s+)?(?:declare\s+)?(?:interface|type)\s")
# Deklaracja na najwyższym poziomie; ten sam warunek git stosuje do nagłówka hunka.
TOP_LEVEL = re.compile(r"^[A-Za-z_$]")
HUNK = re.compile(r"^@@ [^@]+ @@ ?(.*)$")
ENDPOINT = re.compile(r"@\w+\.(?:get|post|put|patch|delete)\(\s*[\"']([^\"']+)[\"']")
IGNORE = re.compile(r"(__tests__|\.test\.|\.spec\.|/tests?/|\.stories\.|frontend/src/app/preview/)")


class Line(NamedTuple):
    text: str
    scope: str  # ostatnia deklaracja z najwyższego poziomu nad linią; "" = nieznana


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str  # pole | endpoint | komponent
    fixed: bool = False  # szukaj jako fragmentu tekstu, nie całego słowa


@dataclass(frozen=True)
class Place:
    symbol: str
    label: str
    path: str

    @property
    def key(self) -> str:
        return f"{self.symbol} · {self.path}"


def changed_lines(diff_text: str) -> dict[str, list[Line]]:
    """Plik → dodane i usunięte linie (bez znaku +/-) z deklaracją, w której stoją.

    Deklaracja to nagłówek hunka (`@@ … @@ export interface X {`) albo ostatnia linia
    z najwyższego poziomu w hunku, także z kontekstu.
    """
    out: dict[str, list[Line]] = {}
    current = None
    scope = ""
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
            scope = ""
            if current:
                out.setdefault(current, [])
        elif line.startswith("--- "):
            continue
        elif hunk := HUNK.match(line):
            scope = hunk.group(1)
        elif current and line and line[0] in "+- ":
            text = line[1:]
            if TOP_LEVEL.match(text):
                scope = text
            if line[0] != " ":
                out[current].append(Line(text, scope))
    return out


def _is_ts_type_field(text: str, scope: str) -> bool:
    """Pole typu, nie właściwość obiektu (`timeout:` w opcjach wywołania).

    Poza `interface`/`type` pole typu poznać po `?:` albo `;` na końcu: tak wygląda
    typ wpisany w sygnaturę metody (`create: (data: { a?: number; }) => …`), a
    przypisanie w obiekcie kończy się przecinkiem.
    """
    if not scope or TS_TYPE_DECL.match(scope):
        return True
    code = text.split("//")[0].rstrip()
    return code.endswith(";") or bool(re.match(r"\s*\w+\?:", code))


def _is_schema_py(path: str) -> bool:
    return path.endswith(".py") and ("/schemas/" in path or "schema" in PurePosixPath(path).name)


def _is_types_ts(path: str) -> bool:
    return path.startswith("frontend/src/") and path.endswith(".ts") and (
        "/types/" in path or "/lib/" in path
    )


def symbols_from_diff(files: dict[str, list[Line]]) -> list[Symbol]:
    found: dict[str, Symbol] = {}
    for path, lines in files.items():
        if IGNORE.search(path):
            continue
        for text, scope in lines:
            if _is_schema_py(path):
                m = PY_FIELD.match(text)
                if m and not text.lstrip().startswith(("def ", "return", "#")):
                    found.setdefault(m.group(1), Symbol(m.group(1), "pole"))
            if _is_types_ts(path) and _is_ts_type_field(text, scope):
                m = TS_FIELD.match(text)
                if m and not re.match(r"\s*(case|default|return|const|let)\b", text):
                    found.setdefault(m.group(1), Symbol(m.group(1), "pole"))
            if path.startswith("backend/app/api/") and path.endswith(".py"):
                m = ENDPOINT.search(text)
                if m:
                    # stała część trasy, bez parametrów: tak wygląda w wywołaniach frontu
                    route = m.group(1).split("{")[0].rstrip("/")
                    if len(route) > 3:
                        found.setdefault(route, Symbol(route, "endpoint", fixed=True))
        if path.startswith("frontend/src/components/") and path.endswith(".tsx"):
            name = PurePosixPath(path).stem
            if name[:1].isupper():
                found.setdefault(name, Symbol(name, "komponent"))
    return [s for s in found.values() if s.fixed or (s.name not in GENERIC and len(s.name) >= 4)]


def classify(path: str) -> str | None:
    """Etykieta miejsca dla pliku albo None, gdy plik nie jest miejscem dla ludzi."""
    if IGNORE.search(path):
        return None
    if path.startswith("frontend/src/app/"):
        parts = [p for p in PurePosixPath(path).parts[3:-1] if not p.startswith("(")]
        return "ekran /" + "/".join(parts)
    if path.startswith("frontend/src/components/"):
        return f"komponent {PurePosixPath(path).stem}"
    if not path.startswith("backend/app/"):
        return None
    name = PurePosixPath(path).name.lower()
    if path.startswith("backend/app/templates/"):
        return f"szablon {PurePosixPath(path).name}"
    if "/jarvis/" in path:
        return "Jarvis"
    if path.startswith("backend/app/data/screen_guides/") or "help_screens" in name:
        return "przewodnik ekranu"
    if "export" in name:
        return "eksport"
    if path.startswith("backend/app/services/") and re.search(r"pdf|docx|word|cv_|mail|email", name):
        return "dokument/mail"
    return None


def grep(symbol: Symbol) -> list[str]:
    flags = ["-l", "-F"] + ([] if symbol.fixed else ["-w"])
    res = subprocess.run(
        ["git", "grep", *flags, "-e", symbol.name, "--", *SEARCH_ROOTS],
        capture_output=True,
        text=True,
    )
    return [p for p in res.stdout.splitlines() if p]


def places_for(symbols: list[Symbol], changed: set[str], search=grep) -> list[Place]:
    out: list[Place] = []
    for sym in symbols:
        found = {
            Place(sym.name, label, path)
            for path in search(sym)
            if path not in changed and (label := classify(path))
        }
        if len(found) > TOO_BROAD:
            label = f"za ogólne (miejsc: {len(found)}) — decyzja zbiorcza"
            out.append(Place(sym.name, label, "*"))
        else:
            out += found
    return sorted(out, key=lambda p: (p.symbol, p.label, p.path))


def render(places: list[Place]) -> str:
    lines = ["| Miejsce | Decyzja |", "|---|---|"]
    lines += [f"| {p.label} — `{p.symbol} · {p.path}` |  |" for p in places]
    if not places:
        lines.append("| (brak innych miejsc) | – |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--diff", default="origin/main...HEAD")
    ap.add_argument("--json", action="store_true", help="klucze miejsc jako JSON (dla hooka)")
    args = ap.parse_args()
    diff_text = subprocess.run(["git", "diff", args.diff], capture_output=True, text=True, check=True).stdout
    files = changed_lines(diff_text)
    places = places_for(symbols_from_diff(files), set(files))
    print(json.dumps([p.key for p in places], ensure_ascii=False) if args.json else render(places))
    return 0


if __name__ == "__main__":
    sys.exit(main())
