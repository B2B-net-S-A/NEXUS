"""Korpus czytników: ten sam zestaw prawdziwych przypadków na dwóch rewizjach.

Testy poprawek sprawdzały przykłady napisane razem z poprawką, a nie dane, na
których czytnik się mylił; kolejna poprawka psuła poprzednią (łańcuch Cpro
#3992 → #4020 → #4026, 46 poprawek rozliczeń w 30 dniach). Eval liczy trafienia
czytnika na korpusie przed zmianą i po niej i pokazuje każdy przypadek, który
przestał przechodzić. Wzór: ``scripts/eval_matching.py``.

Użycie (z ``backend/``)::

    python scripts/eval_reader.py rozliczenia --przed origin/main --po HEAD
    python scripts/eval_reader.py cv --przed origin/main --po HEAD
    python scripts/eval_reader.py cv --przed 697c9117a^ --po 697c9117a   # co dała poprawka

Korpus:
* ``backend/tests/corpus/<czytnik>/`` — przypadki zanonimizowane (repo jest publiczne);
* ``~/.nexus-staging/corpus/<czytnik>/`` — pełne przypadki z kopii produkcji
  (``scripts/eval_reader_export.py``), tylko na laptopie.

Rewizje to commity (``git archive``), nie katalog roboczy: niezacommitowana zmiana
nie wchodzi do wyniku, a skrypt o niej ostrzega. Wynik trafia do
``~/.nexus-staging/eval/<gałąź>/<czytnik>.json``; hook
``~/.claude/hooks/eval-czytnikow-gate.js`` wymaga go przy PR-ze, który zmienia
pliki czytnika (``backend/tests/corpus/czytniki.json``). Kod wyjścia 1 = spadek.

Rozliczenia potrzebują Postgresa: ``EVAL_READER_DATABASE_URL`` (serwer, na którym
wolno zakładać bazy) albo jednorazowy kontener ``nexus-eval-reader-pg``
(127.0.0.1:55491), który skrypt stawia sam.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
REGISTRY = BACKEND / "tests" / "corpus" / "czytniki.json"
RUNNER = Path(__file__).resolve().parent / "eval_reader_runner.py"
STAGING = Path(os.environ.get("NEXUS_STAGING_DIR", Path.home() / ".nexus-staging"))
TREES = STAGING / "eval" / "drzewa"
PG_CONTAINER = "nexus-eval-reader-pg"
PG_PORT = 55491
# Jednorazowy kontener bez danych; użytkownik i hasło tylko lokalne.
PG_USER = os.environ.get("EVAL_READER_PG_USER", "eval")
PG_PASSWORD = os.environ.get("EVAL_READER_PG_PASSWORD", "eval")


def pg_url(database: str = "eval") -> str:
    from sqlalchemy.engine import URL

    return URL.create(
        "postgresql+asyncpg",
        username=PG_USER,
        password=PG_PASSWORD,
        host="127.0.0.1",
        port=PG_PORT,
        database=database,
    ).render_as_string(hide_password=False)


# Wartości ze sita CI (publiczny .github/workflows/ci.yml) — nie sekrety.
APP_ENV = {
    "SECRET_KEY": "ci-only-not-for-production-use-at-least-48-chars-long",
    "CANDIDATE_IDENTITY_FINGERPRINT_KEY": "ci-only-distinct-candidate-identity-key-at-least-48-chars",
    "M365_TOKEN_ENCRYPTION_KEY": "0000000000000000000000000000000000000000000=",
    "RUN_LIVE_TESTS": "0",
    "AI_QUOTA_STRICT": "true",
    # Na produkcji wyłączony, a czytnik poczty bez niego stoi (jak conftest testów).
    "HR_PROGRAM_ENABLED": "true",
    "HR_LOOPS_ENABLED": "false",
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip()


def registry() -> dict[str, Any]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))["czytniki"]


def matches(path: str, patterns: list[str]) -> bool:
    return any(
        fnmatch.fnmatch(path, p.replace("**", "*")) or path == p for p in patterns
    )


def tree(sha: str) -> Path:
    """``backend/app`` rewizji, rozpakowane raz do pamięci podręcznej."""

    target = TREES / sha
    if (target / "backend" / "app").is_dir():
        os.utime(target)  # w użyciu: sprzątanie innego biegu go nie ruszy
        return target / "backend"
    TREES.mkdir(parents=True, exist_ok=True)
    partial = Path(tempfile.mkdtemp(prefix=f"{sha[:8]}-", dir=TREES))
    archive = subprocess.run(
        ["git", "archive", "--format=tar", sha, "backend/app"],
        cwd=REPO,
        check=True,
        capture_output=True,
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(partial)], input=archive, check=True)
    if target.exists():
        shutil.rmtree(target)
    partial.rename(target)
    _prune_trees(keep=8)
    return target / "backend"


def _prune_trees(keep: int, idle_hours: float = 3) -> None:
    """Zostawia ``keep`` najnowszych drzew; starsze usuwa tylko, gdy nikt ich nie
    używał od ``idle_hours`` (dwie sesje liczą eval naraz, a drzewo w użyciu
    zniknęło w trakcie biegu: „No module named 'app.models.base'”)."""

    cutoff = time.time() - idle_hours * 3600
    folders = sorted(
        (p for p in TREES.iterdir() if p.is_dir() and len(p.name) == 40),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in folders[keep:]:
        if old.stat().st_mtime < cutoff:
            shutil.rmtree(old, ignore_errors=True)


def ensure_postgres() -> str:
    url = os.environ.get("EVAL_READER_DATABASE_URL")
    if url:
        return url
    running = subprocess.run(
        ["docker", "ps", "-q", "-f", f"name=^{PG_CONTAINER}$"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not running:
        subprocess.run(
            [
                "docker", "run", "-d", "--rm", "--name", PG_CONTAINER,
                "--label", "nexus.eval-reader=1",
                "-p", f"127.0.0.1:{PG_PORT}:5432",
                "-e", f"POSTGRES_USER={PG_USER}", "-e", f"POSTGRES_PASSWORD={PG_PASSWORD}",
                "-e", "POSTGRES_DB=eval", "postgres:16-alpine",
            ],
            check=True,
            capture_output=True,
        )  # fmt: skip
        for _ in range(30):
            ready = subprocess.run(
                ["docker", "exec", PG_CONTAINER, "pg_isready", "-U", PG_USER],
                capture_output=True,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
    return pg_url()


def corpus_dirs(
    reader: str, only_repo: bool, extra: list[str]
) -> list[tuple[str, str]]:
    dirs = [(str(BACKEND / "tests" / "corpus" / reader), "repo")]
    local = STAGING / "corpus" / reader
    if not only_repo and local.is_dir():
        dirs.append((str(local), "lokalny"))
    dirs.extend((d, "dodatkowy") for d in extra)
    return dirs


def copy_database(reader: str, dirs: list[tuple[str, str]]) -> Optional[str]:
    """Kopia produkcji dla przypadków lokalnych ``"baza": "kopia"`` (eksport zapisuje
    nazwę w ``_srodowisko.json``; gdy nocna rotacja ją usunęła, najnowsza kopia)."""

    local = [d for d, label in dirs if label == "lokalny"]
    if reader != "rozliczenia" or not local:
        return None
    env_url = os.environ.get("EVAL_READER_COPY_URL")
    if env_url:
        return env_url
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import eval_reader_export as export

    wanted = ""
    meta = Path(local[0]) / "_srodowisko.json"
    if meta.is_file():
        wanted = json.loads(meta.read_text(encoding="utf-8")).get("baza_kopii", "")
    try:
        newest = export.newest_copy()
        listed = subprocess.run(
            ["docker", "exec", export.PG_CONTAINER, "psql", "-U", "nexus", "-d", "postgres", "-At",
             "-c", "SELECT datname FROM pg_database"],
            capture_output=True, text=True, check=True,
        ).stdout.split()  # fmt: skip
        return export.copy_url(wanted if wanted in listed else newest)
    except (subprocess.CalledProcessError, SystemExit, FileNotFoundError):
        print(
            "Uwaga: brak kopii stagingu — przypadki lokalne rozliczeń nie pobiegną.",
            file=sys.stderr,
        )
        return None


def run_revision(
    reader: str,
    sha: str,
    dirs: list[tuple[str, str]],
    db_url: Optional[str],
    only: str = "",
) -> dict:
    backend = tree(sha)
    env = {**os.environ, **APP_ENV}
    env.pop("PYTHONPATH", None)
    if db_url:
        base = db_url.rsplit("/", 1)[0]
        env["DATABASE_URL"] = f"{base}/eval_{reader}_{sha[:10]}"
    else:
        # CV nie łączy się z bazą; adres tylko dla importu ustawień aplikacji.
        env["DATABASE_URL"] = "postgresql+asyncpg://127.0.0.1:1/brak"
    copy = copy_database(reader, dirs)
    if copy:
        env["EVAL_READER_COPY_URL"] = copy
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        out = Path(handle.name)
    command = [
        sys.executable, str(RUNNER), reader, "--app", str(backend),
        "--korpus", *[d for d, _ in dirs], "--zrodla", *[label for _, label in dirs],
        "--wynik", str(out), *(["--filtr", only] if only else []),
    ]  # fmt: skip
    started = time.monotonic()
    done = subprocess.run(command, env=env, capture_output=True, text=True)
    if done.returncode != 0:
        sys.stderr.write(done.stderr[-4000:])
        raise SystemExit(
            f"przebieg {reader} @ {sha[:10]} nie powiódł się (kod {done.returncode})"
        )
    result = json.loads(out.read_text(encoding="utf-8"))
    out.unlink(missing_ok=True)
    result["sekundy"] = round(time.monotonic() - started, 1)
    return result


def env_errors(units: list[dict]) -> list[str]:
    """Brak pakietu w venv to błąd środowiska, nie czytnika: rewizje różnią się
    zależnościami (#3998 zamienił python-jose na PyJWT), więc wynik nie jest ważny.
    Brak modułu ``app.*`` w starej rewizji to zwykłe nietrafienie (funkcji jeszcze
    nie było)."""

    def broken(error: str) -> bool:
        return error.startswith(("ModuleNotFoundError", "ImportError")) and (
            "No module named 'app" not in error and "from 'app." not in error
        )

    return sorted({u["blad"] for u in units if broken(u.get("blad") or "")})


def totals(units: list[dict], fields: list[str]) -> dict[str, list[int]]:
    out = {f: [0, 0] for f in fields}
    for unit in units:
        slot = out.setdefault(unit["pole"], [0, 0])
        slot[0] += int(unit["ok"])
        slot[1] += 1
    return out


def compare(
    before: list[dict], after: list[dict]
) -> tuple[list[dict], list[dict], list[dict]]:
    """(spadki, naprawione, nowe): po kluczu id + pole."""

    old = {(u["id"], u["pole"]): u for u in before}
    drops, fixes, new = [], [], []
    for unit in after:
        prev = old.get((unit["id"], unit["pole"]))
        if prev is None:
            new.append(unit)
        elif prev["ok"] and not unit["ok"]:
            drops.append({**unit, "przed": prev["jest"]})
        elif not prev["ok"] and unit["ok"]:
            fixes.append(unit)
    gone = {(u["id"], u["pole"]) for u in after}
    for key, prev in old.items():
        if key not in gone and prev["ok"]:
            drops.append(
                {
                    **prev,
                    "ok": False,
                    "jest": "(brak jednostki po zmianie)",
                    "przed": prev["jest"],
                }
            )
    return drops, fixes, new


def pct(ok: int, n: int) -> str:
    return f"{ok}/{n} ({100 * ok / n:.1f}%)" if n else "—"


def short(value: Any, limit: int = 90) -> str:
    text = (
        json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    )
    return text if len(text) <= limit else text[: limit - 1] + "…"


def report(
    reader: str, meta: dict, before: dict, after: dict, fields: list[str]
) -> tuple[str, dict]:
    tb, ta = totals(before["jednostki"], fields), totals(after["jednostki"], fields)
    drops, fixes, new = compare(before["jednostki"], after["jednostki"])
    by_source: dict[str, int] = {}
    for unit in after["jednostki"]:
        case_id = unit["id"].split("#")[0]
        by_source.setdefault(unit.get("zrodlo") or "?", set()).add(case_id)  # type: ignore[arg-type]
    sources = {k: len(v) for k, v in by_source.items()}  # type: ignore[arg-type]
    lines = [
        f"## Eval czytnika `{reader}` — {meta['przed']['ref']} ({meta['przed']['sha'][:10]}) → "
        f"{meta['po']['ref']} ({meta['po']['sha'][:10]})",
        "",
        f"Przypadki: {after['przypadki']} ({', '.join(f'{k}: {v}' for k, v in sorted(sources.items()))}); "
        f"czas {before['sekundy']} s + {after['sekundy']} s.",
        "",
        "| Pole | Przed | Po | Zmiana |",
        "|---|---|---|---|",
    ]
    for field in sorted(set(tb) | set(ta), key=lambda f: (f not in fields, f)):
        b, a = tb.get(field, [0, 0]), ta.get(field, [0, 0])
        delta = (
            (a[0] - b[0])
            if a[1] == b[1]
            else f"{a[0] - b[0]:+d} (jednostek {b[1]}→{a[1]})"
        )
        lines.append(
            f"| {field} | {pct(*b)} | {pct(*a)} | {delta if isinstance(delta, str) else f'{delta:+d}'} |"
        )
    lines.append("")
    broken = {
        "przed": env_errors(before["jednostki"]),
        "po": env_errors(after["jednostki"]),
    }
    for side, errors in broken.items():
        if errors:
            lines += [
                f"**Błąd środowiska ({side}):** {'; '.join(errors)[:300]} — doinstaluj pakiet "
                "w venv (pip install …) i uruchom ponownie; ten wynik nie przechodzi przez hook.",
                "",
            ]
    if drops:
        lines += [
            f"### Spadki ({len(drops)}) — przypadki, które przestały przechodzić",
            "",
        ]
        for unit in drops[:40]:
            lines.append(
                f"- `{unit['id']}` · {unit['pole']}: oczekiwane {short(unit['oczekiwane'])}, "
                f"przed {short(unit['przed'])}, po {short(unit['jest'])}"
            )
        lines.append("")
    else:
        lines += ["Spadków: 0.", ""]
    if fixes:
        lines += [f"### Naprawione ({len(fixes)})", ""]
        lines += [f"- `{u['id']}` · {u['pole']}" for u in fixes[:40]]
        lines.append("")
    failing = [u for u in after["jednostki"] if not u["ok"]]
    if failing:
        lines += [f"### Nadal nietrafione po zmianie ({len(failing)})", ""]
        for unit in failing[:25]:
            extra = f" — {unit['blad']}" if unit.get("blad") else ""
            lines.append(
                f"- `{unit['id']}` · {unit['pole']}: oczekiwane {short(unit['oczekiwane'])}, "
                f"jest {short(unit['jest'])}{extra}"
            )
        lines.append("")
    summary = {
        "czytnik": reader,
        **meta,
        "czas": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "przypadki": after["przypadki"],
        "zrodla": sources,
        "pola": {
            f: {"przed": tb.get(f, [0, 0]), "po": ta.get(f, [0, 0])}
            for f in sorted(set(tb) | set(ta))
        },
        "srodowisko_ok": not (broken["przed"] or broken["po"]),
        "bledy_srodowiska": broken,
        "spadki": len(drops),
        "naprawione": len(fixes),
        "nowe": len(new),
        "lista_spadkow": drops[:200],
    }
    return "\n".join(lines), summary


def result_path(reader: str, branch: str) -> Path:
    base = Path(os.environ.get("EVAL_READER_OUT_DIR", STAGING / "eval"))
    safe = "".join(c if c.isalnum() or c in "._-" else "-" for c in branch)
    return base / safe / f"{reader}.json"


def dirty_reader_files(patterns: list[str]) -> list[str]:
    status = git("status", "--porcelain")
    files = [line[3:].split(" -> ")[-1] for line in status.splitlines() if line]
    return [f for f in files if matches(f, patterns)]


def main(argv: Optional[list[str]] = None) -> int:
    readers = registry()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("czytnik", choices=sorted(readers))
    parser.add_argument("--przed", default="origin/main")
    parser.add_argument("--po", default="HEAD")
    parser.add_argument(
        "--tylko-repo", action="store_true", help="bez lokalnego korpusu z produkcji"
    )
    parser.add_argument(
        "--korpus", nargs="*", default=[], help="dodatkowe katalogi z przypadkami"
    )
    parser.add_argument(
        "--bez-zapisu", action="store_true", help="nie zapisuj wyniku dla hooka"
    )
    parser.add_argument(
        "--filtr",
        default="",
        help="tylko przypadki, których id albo plik zawiera ten tekst",
    )
    parser.add_argument(
        "--json", action="store_true", help="podsumowanie JSON zamiast tabeli"
    )
    args = parser.parse_args(argv)

    spec = readers[args.czytnik]
    fields = spec["pola"]
    before_sha, after_sha = git("rev-parse", args.przed), git("rev-parse", args.po)
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = dirty_reader_files(spec["sciezki"]) if args.po == "HEAD" else []
    if dirty:
        print(
            "Uwaga: niezacommitowane zmiany w czytniku nie wchodzą do wyniku: "
            + ", ".join(dirty),
            file=sys.stderr,
        )
    dirs = corpus_dirs(args.czytnik, args.tylko_repo, args.korpus)
    db_url = ensure_postgres() if spec.get("baza") else None

    before = run_revision(args.czytnik, before_sha, dirs, db_url, args.filtr)
    after = run_revision(args.czytnik, after_sha, dirs, db_url, args.filtr)
    meta = {
        "przed": {"ref": args.przed, "sha": before_sha},
        "po": {"ref": args.po, "sha": after_sha},
        "galaz": branch,
        "tylko_repo": bool(args.tylko_repo),
    }
    text, summary = report(args.czytnik, meta, before, after, fields)
    if args.filtr:
        args.bez_zapisu = True  # wynik części korpusu nie jest wynikiem dla hooka
    if not args.bez_zapisu:
        path = result_path(args.czytnik, branch)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8",
        )
        summary["plik"] = str(path)
    print(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str)
        if args.json
        else text
    )
    if not args.json and not args.bez_zapisu:
        print(f"Wynik dla hooka: {summary['plik']}")
    if not summary["srodowisko_ok"]:
        return 2
    return 1 if summary["spadki"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
