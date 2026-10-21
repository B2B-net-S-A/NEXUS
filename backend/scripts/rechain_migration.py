"""Przepięcie migracji Alembica z gałęzi PR-a na aktualną głowę maina.

Po co: równoległe sesje dokładają migracje numerowane po kolei
(``0369_nazwa.py``, ``down_revision`` = poprzednia głowa). Gdy dwa PR-y
wezmą ten sam numer, po scaleniu pierwszego drugi ma dwie głowy i wypada
z kolejki merge'ów. Ręczna naprawa to: nowy wolny numer, ``down_revision``
na głowę maina i podmiana starego numeru TYLKO w liniach dodanych przez
PR — nigdy globalny sed, bo ``backend/entrypoint.sh`` i ``CLAUDE.md``
niosą numery cudzych migracji (np. ``0369: Akademia`` z maina obok
``0369: ocena prepu`` z PR-a). Ten skrypt robi to mechanicznie.

Użycie (na gałęzi PR-a, po ``git fetch``; scalenie ``origin/main`` nie
jest potrzebne — linie PR-a liczymy od merge-base)::

    python3 backend/scripts/rechain_migration.py --dry-run   # sam plan
    python3 backend/scripts/rechain_migration.py             # zmiana plików
    python3 backend/scripts/rechain_migration.py --base origin/main
    python3 backend/scripts/rechain_migration.py --check-heads  # bramka CI

Skrypt nie commituje — po nim przejrzyj ``git diff``, puść testy lustra
migracji i zacommituj. Po każdym pushu na main z nową migracją robi to za
sesje workflow „Przepnij migracje PR-ów” (``migration-rechain.yml``).
Tylko biblioteka standardowa, Python 3.9+.

Pełny identyfikator starego rodzica (np. ``assert down_revision ==
"0496_…"`` w teście PR-a) w liniach dodanych przez PR też dostaje nowego
rodzica — to jedyne miejsce, gdzie PR-y zapisują rodzica poza migracją.

``--check-heads`` liczy głowy w drzewie roboczym i kończy się kodem 1,
gdy nie ma dokładnie jednej. Biegnie jako pierwszy krok wymaganego
„Backend (lint + migrations)”, więc grupa z dwiema głowami wypada z kolejki
po ~1–2 min, a nie po ~25 min pełnego pytesta.

Czego NIE robi: nie obsługuje migracji scalających (krotka w
``down_revision``) dodanych przez PR ani plików migracji, których nie ma
jeszcze w commicie.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

VERSIONS_DIR = "backend/alembic/versions"
NUMBER_RE = re.compile(r"^(\d+)_")

DownRevision = Union[str, Tuple[str, ...], None]


class RechainError(Exception):
    """Błąd, po którym skrypt przerywa pracę bez zmian w plikach."""


@dataclass
class Migration:
    path: str  # ścieżka względem korzenia repo
    revision: str
    down_revision: DownRevision
    source: str = ""
    spans: Dict[str, Tuple[int, int, int, int]] = field(default_factory=dict)

    @property
    def stem(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0]

    @property
    def number(self) -> Optional[str]:
        m = NUMBER_RE.match(self.stem)
        return m.group(1) if m else None


@dataclass
class Rename:
    migration: Migration
    old_number: str
    new_number: str
    new_path: str
    new_revision: str
    new_down_revision: str


def git(repo: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RechainError(f"git {' '.join(args)} zwrócił błąd: {proc.stderr.strip()}")
    return proc.stdout


def parse_migration(path: str, source: str) -> Optional[Migration]:
    """Czyta ``revision``/``down_revision`` (także z adnotacją typu i krotką)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise RechainError(f"nie da się sparsować {path}: {exc}") from exc
    values: Dict[str, object] = {}
    spans: Dict[str, Tuple[int, int, int, int]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id in ("revision", "down_revision"):
            try:
                parsed = ast.literal_eval(value)
            except ValueError:
                raise RechainError(f"{path}: {target.id} nie jest literałem") from None
            if isinstance(parsed, list):
                parsed = tuple(parsed)
            values[target.id] = parsed
            spans[target.id] = (
                value.lineno,
                value.col_offset,
                value.end_lineno,
                value.end_col_offset,
            )
    if not isinstance(values.get("revision"), str):
        return None
    return Migration(
        path=path,
        revision=values["revision"],  # type: ignore[arg-type]
        down_revision=values.get("down_revision"),  # type: ignore[arg-type]
        source=source,
        spans=spans,
    )


def down_list(down: DownRevision) -> List[str]:
    if down is None:
        return []
    if isinstance(down, str):
        return [down]
    return list(down)


def load_base(repo: str, base: str, versions_dir: str) -> List[Migration]:
    listing = git(repo, "ls-tree", "--name-only", f"{base}:{versions_dir}")
    migrations = []
    for name in listing.splitlines():
        if not name.endswith(".py") or name.startswith("__"):
            continue
        path = f"{versions_dir}/{name}"
        mig = parse_migration(path, git(repo, "show", f"{base}:{path}"))
        if mig is not None:
            migrations.append(mig)
    return migrations


def heads_of(migrations: Sequence[Migration]) -> List[str]:
    referenced: Set[str] = set()
    for mig in migrations:
        referenced.update(down_list(mig.down_revision))
    return sorted(m.revision for m in migrations if m.revision not in referenced)


def load_worktree(repo: str, versions_dir: str) -> List[Migration]:
    directory = os.path.join(repo, versions_dir)
    migrations = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".py") or name.startswith("__"):
            continue
        path = f"{versions_dir}/{name}"
        with open(os.path.join(directory, name), encoding="utf-8") as fh:
            mig = parse_migration(path, fh.read())
        if mig is not None:
            migrations.append(mig)
    return migrations


def check_heads(repo: str, versions_dir: str, out=print) -> int:
    """Bramka CI: dokładnie jedna głowa w drzewie roboczym, inaczej kod 1."""
    heads = heads_of(load_worktree(repo, versions_dir))
    if len(heads) == 1:
        out(f"Jedna głowa migracji Alembica: {heads[0]}")
        return 0
    out(
        f"::error::{len(heads)} głowy migracji Alembica zamiast jednej: "
        f"{', '.join(heads) or 'brak'}. Dwie migracje wskazują tego samego "
        "rodzica — PR, który wszedł później, trzeba przepiąć na głowę maina: "
        "`python3 backend/scripts/rechain_migration.py` na gałęzi PR-a. "
        "Po pushu na main robi to sam workflow „Przepnij migracje PR-ów”."
    )
    return 1


def added_migration_paths(repo: str, base: str, versions_dir: str) -> List[str]:
    out = git(
        repo,
        "diff",
        "--no-renames",
        "--name-status",
        "--diff-filter=A",
        f"{base}...HEAD",
        "--",
        versions_dir,
    )
    paths = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        path = parts[1]
        if os.path.dirname(path) == versions_dir and path.endswith(".py"):
            paths.append(path)
    return paths


def order_chain(pr: List[Migration]) -> List[Migration]:
    """Układa migracje PR-a w łańcuch; więcej niż jeden łańcuch = przerwij."""
    by_rev = {m.revision: m for m in pr}
    for mig in pr:
        if isinstance(mig.down_revision, tuple):
            raise RechainError(
                f"{mig.path} to migracja scalająca (krotka w down_revision) — "
                "przepnij ją ręcznie."
            )
    roots = [m for m in pr if m.down_revision not in by_rev]
    children: Dict[str, List[Migration]] = {}
    for mig in pr:
        if mig.down_revision in by_rev:
            children.setdefault(mig.down_revision, []).append(mig)  # type: ignore[arg-type]
    if len(roots) != 1 or any(len(c) > 1 for c in children.values()):
        raise RechainError(
            "migracje dodane przez PR nie tworzą jednego łańcucha "
            f"({', '.join(sorted(by_rev))}) — przepnij je ręcznie."
        )
    chain = [roots[0]]
    while chain[-1].revision in children:
        chain.append(children[chain[-1].revision][0])
    if len(chain) != len(pr):
        raise RechainError("migracje PR-a zawierają cykl — przepnij je ręcznie.")
    return chain


def plan_renames(
    chain: List[Migration], base_migrations: List[Migration], head: str
) -> List[Rename]:
    base_numbers = [m.number for m in base_migrations if m.number]
    if not base_numbers:
        raise RechainError("w bazie nie ma numerowanych migracji.")
    width = max(len(n) for n in base_numbers)
    next_number = max(int(n) for n in base_numbers) + 1
    renames = []
    down = head
    for offset, mig in enumerate(chain):
        old_number = mig.number
        if old_number is None:
            raise RechainError(f"{mig.path}: nazwa pliku nie zaczyna się od numeru.")
        new_number = str(next_number + offset).zfill(width)
        new_stem = new_number + mig.stem[len(old_number) :]
        new_revision = mig.revision
        if new_revision.startswith(old_number):
            new_revision = new_number + new_revision[len(old_number) :]
        renames.append(
            Rename(
                migration=mig,
                old_number=old_number,
                new_number=new_number,
                new_path=f"{os.path.dirname(mig.path)}/{new_stem}.py",
                new_revision=new_revision,
                new_down_revision=down,
            )
        )
        down = new_revision
    return renames


def added_lines(repo: str, base: str) -> Dict[str, Set[int]]:
    """Numery linii (1-based, w drzewie roboczym) dodanych przez PR.

    Diff od merge-base, nie od czubka bazy: gałąź bez scalonego maina miałaby
    inaczej za „dodane” także linie, które main usunął po rozgałęzieniu.
    Po scaleniu maina merge-base = czubek bazy, więc wynik jest ten sam.
    """
    merge_base = git(repo, "merge-base", base, "HEAD").strip()
    out = git(
        repo, "diff", "--no-renames", "--no-ext-diff", "--no-color", "-U0", merge_base
    )
    result: Dict[str, Set[int]] = {}
    current: Optional[str] = None
    hunk = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
    for line in out.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            current = target[2:] if target.startswith("b/") else None
            if current is not None:
                result.setdefault(current, set())
            continue
        m = hunk.match(line)
        if m and current is not None:
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) is not None else 1
            result[current].update(range(start, start + count))
    return result


def replace_span(source: str, span: Tuple[int, int, int, int], text: str) -> str:
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.encode("utf-8")))
    raw = source.encode("utf-8")
    start = offsets[span[0] - 1] + span[1]
    end = offsets[span[2] - 1] + span[3]
    return (raw[:start] + text.encode("utf-8") + raw[end:]).decode("utf-8")


def rewrite_migration_header(rename: Rename, source: str) -> str:
    """Ustawia ``revision``/``down_revision`` (i ``Revises:`` w docstringu).

    ``source`` to treść już po podmianie linii — spany liczymy od nowa, a
    podmiana idzie od końca pliku, żeby wcześniejszy span się nie przesunął.
    """
    mig = parse_migration(rename.migration.path, source)
    if mig is None:
        raise RechainError(f"{rename.migration.path}: brak `revision` po podmianie.")
    edits = []
    if "revision" in mig.spans:
        edits.append((mig.spans["revision"], f'"{rename.new_revision}"'))
    if "down_revision" in mig.spans:
        edits.append((mig.spans["down_revision"], f'"{rename.new_down_revision}"'))
    for span, text in sorted(edits, key=lambda e: (e[0][0], e[0][1]), reverse=True):
        source = replace_span(source, span, text)
    old_down = rename.migration.down_revision
    if isinstance(old_down, str) and old_down != rename.new_down_revision:
        source = re.sub(
            r"^(\s*Revises:\s*)" + re.escape(old_down) + r"(?![\w])",
            lambda m: m.group(1) + rename.new_down_revision,
            source,
            flags=re.MULTILINE,
        )
    return source


def build_line_rewriter(renames: List[Rename], base_migrations: List[Migration]):
    """Zwraca funkcję (linia) -> linia z podmienionymi id/numerami migracji PR-a."""
    full = {r.migration.revision: r.new_revision for r in renames}
    full.update({r.migration.stem: r.new_path.rsplit("/", 1)[1][:-3] for r in renames})
    old_parent = renames[0].migration.down_revision
    if isinstance(old_parent, str):
        full.setdefault(old_parent, renames[0].new_down_revision)
    full = {old: new for old, new in full.items() if old != new}
    bare = {r.old_number: r.new_number for r in renames if r.old_number != r.new_number}
    # Nazwy migracji z bazy z tym samym numerem (kolizja) — linia, która je
    # wymienia, mówi o migracji z maina, więc gołego numeru na niej nie ruszamy.
    base_names: Dict[str, List[str]] = {}
    for mig in base_migrations:
        if mig.number in bare:
            base_names.setdefault(mig.number, []).extend({mig.revision, mig.stem})
    if not full and not bare:
        return lambda line: line
    alternatives = []
    if full:
        ids = sorted(full, key=len, reverse=True)
        alternatives.append(
            r"(?P<full>(?<![\w])(?:" + "|".join(map(re.escape, ids)) + r")(?![\w]))"
        )
    if bare:
        nums = sorted(bare, key=len, reverse=True)
        alternatives.append(
            r"(?P<bare>(?<![\w])(?:" + "|".join(nums) + r")(?![\dA-Za-z]))"
        )
    pattern = re.compile("|".join(alternatives))

    def rewrite(line: str) -> str:
        blocked = {
            num
            for num, names in base_names.items()
            if any(re.search(re.escape(n) + r"(?![\w])", line) for n in names)
        }

        def repl(m: re.Match) -> str:
            if "full" in pattern.groupindex and m.group("full"):
                return full[m.group(0)]
            num = m.group(0)
            if num in blocked:
                return num
            return bare[num]

        return pattern.sub(repl, line)

    return rewrite


def rewrite_added_lines(
    repo: str, path: str, numbers: Set[int], rewrite, dry_run: bool
) -> List[Tuple[int, str, str]]:
    full = os.path.join(repo, path)
    if not os.path.isfile(full):
        return []
    try:
        with open(full, encoding="utf-8", newline="") as fh:
            content = fh.read()
    except UnicodeDecodeError:
        return []
    lines = content.splitlines(keepends=True)
    changes = []
    for no in sorted(numbers):
        if no > len(lines):
            continue
        old = lines[no - 1]
        new = rewrite(old)
        if new != old:
            changes.append((no, old.rstrip("\r\n"), new.rstrip("\r\n")))
            lines[no - 1] = new
    if changes and not dry_run:
        with open(full, "w", encoding="utf-8", newline="") as fh:
            fh.write("".join(lines))
    return changes


def run(repo: str, base: str, versions_dir: str, dry_run: bool, out=print) -> int:
    base_migrations = load_base(repo, base, versions_dir)
    heads = heads_of(base_migrations)
    if len(heads) != 1:
        raise RechainError(
            f"{base} ma {len(heads)} głowy migracji ({', '.join(heads) or 'brak'}) "
            "zamiast jednej — najpierw trzeba to naprawić na mainie."
        )
    head = heads[0]

    paths = added_migration_paths(repo, base, versions_dir)
    if not paths:
        out(f"Gałąź nie dodaje migracji względem {base} — nic do zrobienia.")
        return 0
    pr = []
    for path in paths:
        with open(os.path.join(repo, path), encoding="utf-8") as fh:
            mig = parse_migration(path, fh.read())
        if mig is None:
            raise RechainError(f"{path}: brak `revision` w pliku migracji.")
        pr.append(mig)
    chain = order_chain(pr)

    base_numbers = {m.number for m in base_migrations if m.number}
    base_revisions = {m.revision for m in base_migrations}
    collisions = [
        m for m in chain if m.number in base_numbers or m.revision in base_revisions
    ]
    if chain[0].down_revision == head and not collisions:
        out(
            f"Migracje PR-a ({', '.join(m.revision for m in chain)}) już stoją "
            f"na głowie {base} ({head}) z wolnymi numerami — nic do zrobienia."
        )
        return 0

    renames = plan_renames(chain, base_migrations, head)
    for r in renames:
        if r.new_path != r.migration.path and os.path.exists(
            os.path.join(repo, r.new_path)
        ):
            raise RechainError(f"{r.new_path} już istnieje — przerwano.")

    out(f"Głowa {base}: {head}")
    out("Plan:" if dry_run else "Zmiany:")
    for r in renames:
        mig = r.migration
        out(f"  {mig.path} -> {r.new_path}")
        out(f"    revision:      {mig.revision} -> {r.new_revision}")
        out(f"    down_revision: {mig.down_revision} -> {r.new_down_revision}")

    added = added_lines(repo, base)
    rewrite = build_line_rewriter(renames, base_migrations)
    migration_paths = {r.migration.path for r in renames}

    # 1) same pliki migracji: nagłówek + wszystkie linie (plik jest cały dodany).
    for r in renames:
        mig = r.migration
        source = "".join(rewrite(line) for line in mig.source.splitlines(keepends=True))
        source = rewrite_migration_header(r, source)
        if not dry_run:
            with open(
                os.path.join(repo, mig.path), "w", encoding="utf-8", newline=""
            ) as fh:
                fh.write(source)
            if r.new_path != mig.path:
                git(repo, "mv", mig.path, r.new_path)

    # 2) pozostałe pliki PR-a: tylko linie dodane przez PR.
    touched = 0
    for path, numbers in sorted(added.items()):
        if path in migration_paths or not numbers:
            continue
        changes = rewrite_added_lines(repo, path, numbers, rewrite, dry_run)
        if changes:
            touched += 1
            out(f"  {path}:")
            for no, old, new in changes:
                out(f"    {no}: {old.strip()}")
                out(f"    {' ' * len(str(no))}  -> {new.strip()}")
    if not touched:
        out("  (poza plikami migracji żadna linia PR-a nie wymagała zmiany)")

    if dry_run:
        out("Tryb --dry-run: nic nie zmieniono.")
    else:
        out("Gotowe. Przejrzyj `git diff`, puść testy migracji i zacommituj.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Przepina migracje Alembica z gałęzi PR-a na głowę maina."
    )
    parser.add_argument(
        "--base", default="origin/main", help="ref bazy (domyślnie origin/main)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="pokaż plan bez zmian w plikach"
    )
    parser.add_argument(
        "--versions-dir",
        default=VERSIONS_DIR,
        help=f"katalog migracji względem korzenia repo (domyślnie {VERSIONS_DIR})",
    )
    parser.add_argument(
        "--check-heads",
        action="store_true",
        help="tylko sprawdź, że drzewo robocze ma jedną głowę (kod 1, gdy nie)",
    )
    args = parser.parse_args(argv)
    try:
        repo = git(os.getcwd(), "rev-parse", "--show-toplevel").strip()
        versions_dir = args.versions_dir.strip("/")
        if args.check_heads:
            return check_heads(repo, versions_dir)
        return run(repo, args.base, versions_dir, args.dry_run)
    except RechainError as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
