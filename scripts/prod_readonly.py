#!/usr/bin/env python3
"""Odczyt produkcji NEXUSA dla nocnych rutyn: kilka stałych podkomend zamiast dowolnej komendy po SSH.

    prod_readonly.py sql [--csv] -f zapytanie.sql  # tylko SELECT/WITH, sesja i transakcja read-only
    prod_readonly.py sql [--csv] < zapytanie.sql   # to samo ze stdin
    prod_readonly.py env NAZWA [NAZWA…]            # zmienne procesu 1 backendu z białej listy
    prod_readonly.py backup-log [N]                # ostatnie N linii logu backupu (domyślnie 100)
    prod_readonly.py health                        # publiczne /api/health

Reguła zgody Claude Code obejmuje tylko ten plik, więc to, co tu jest, wyznacza,
co rutyna może zrobić na produkcji. Reguła: docs/claude/podstawy/rutyny-nocne.md.

Host i klucz SSH nie leżą w repo (jest publiczne): czyta je plik
``~/.claude/nexus-rutyny/prod-readonly.conf`` (``host=…``, ``key=…``)
albo ścieżka z ``NEXUS_PROD_READONLY_CONF``.

Python 3.9 (systemowy na laptopie), bez zależności spoza biblioteki standardowej.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import urllib.request
from collections.abc import Sequence
from pathlib import Path

HEALTH_URL = "https://api.nexus.b2bnetwork.pl/api/health"
DEFAULT_CONF = Path.home() / ".claude/nexus-rutyny/prod-readonly.conf"
BACKUP_LOG = "/var/log/nexus-backup.log"
BACKUP_LOG_MAX_LINES = 500
SQL_MAX_CHARS = 20_000
STATEMENT_TIMEOUT = "60s"

# Nazwy kontenerów zmieniają się po każdym wdrożeniu, prefiks zostaje (docs/claude/podstawy/deploy.md).
_FIND_CONTAINER = (
    "c=$(docker ps --format '{{{{.Names}}}}' | grep '^{prefix}' | head -1); "
    "[ -n \"$c\" ] || {{ echo 'Brak kontenera {prefix}*.' >&2; exit 3; }}; "
)
POSTGRES_PREFIX = "postgres-ocgkw"
BACKEND_PREFIX = "backend-ocgkw"


class Rejected(ValueError):
    """Wejście odrzucone przed połączeniem z produkcją."""


# --- sql ---------------------------------------------------------------------

# Instrukcja musi zaczynać się od jednego z tych słów.
_ALLOWED_STARTS = {"SELECT", "WITH"}

# Słowa, które w SELECT/WITH oznaczają zapis albo blokadę: CTE z INSERT/UPDATE/DELETE/MERGE,
# SELECT … INTO (tworzy tabelę), SELECT … FOR UPDATE/SHARE (blokady wierszy).
_FORBIDDEN_WORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|INTO|SHARE)\b", re.IGNORECASE
)

# Funkcje ze skutkiem poza transakcją albo wykonujące tekst jako SQL.
_FORBIDDEN_FUNCTIONS = re.compile(
    r"\b("
    r"set_config|pg_terminate_backend|pg_cancel_backend|pg_reload_conf|pg_rotate_logfile|"
    r"pg_switch_wal|pg_promote|pg_sleep\w*|pg_read_file|pg_read_binary_file|pg_ls_\w+|"
    r"pg_stat_file|pg_create_\w+|pg_drop_\w+|pg_logical_\w+|pg_replication_\w+|"
    r"pg_advisory\w*|pg_try_advisory\w*|lo_\w+|dblink\w*|nextval|setval|"
    r"query_to_xml\w*|cursor_to_xml\w*"
    r")\b",
    re.IGNORECASE,
)


def _skeleton(sql: str) -> str:
    """Zapytanie bez komentarzy, z pustymi literałami i identyfikatorami w cudzysłowie.

    Dzięki temu `action = 'update'` albo średnik w literale nie myli bramki,
    a słowo w komentarzu nie przechodzi niezauważone do psql.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch == "-" and nxt == "-":
            end = sql.find("\n", i)
            i = n if end < 0 else end
            out.append(" ")
        elif ch == "/" and nxt == "*":
            end = sql.find("*/", i + 2)
            if end < 0:
                raise Rejected("Niezamknięty komentarz /* … */.")
            if "/*" in sql[i + 2 : end]:
                raise Rejected("Zagnieżdżone komentarze /* … */ nie są obsługiwane.")
            i = end + 2
            out.append(" ")
        elif ch in ("'", '"'):
            j = i + 1
            while True:
                end = sql.find(ch, j)
                if end < 0:
                    raise Rejected(
                        "Niezamknięty literał albo identyfikator w cudzysłowie."
                    )
                if end + 1 < n and sql[end + 1] == ch:  # '' albo "" w środku
                    j = end + 2
                    continue
                break
            out.append(ch * 2)
            i = end + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def validate_sql(sql: str) -> list[str]:
    """Zwraca instrukcje zapytania albo rzuca Rejected. Druga bramka to sesja read-only w bazie."""
    if not sql.strip():
        raise Rejected("Puste zapytanie: podaj SELECT na stdin.")
    if len(sql) > SQL_MAX_CHARS:
        raise Rejected(f"Zapytanie dłuższe niż {SQL_MAX_CHARS} znaków.")
    if "\\" in sql:
        # Polecenia psql (\! powłoka, \copy plik, \g plik, \set) działają poza SQL.
        raise Rejected(
            "Znak \\ jest niedozwolony: polecenia psql nie przechodzą przez ten skrypt."
        )
    if "$" in sql:
        raise Rejected("Znak $ jest niedozwolony (literały $$…$$ omijałyby bramkę).")
    if "\x00" in sql:
        raise Rejected("Znak NUL w zapytaniu.")

    skeleton = _skeleton(sql)
    statements = [s.strip() for s in skeleton.split(";") if s.strip()]
    if not statements:
        raise Rejected("Same komentarze, brak instrukcji.")
    for stmt in statements:
        first = re.match(r"[\s(]*([A-Za-z]+)", stmt)
        word = first.group(1).upper() if first else ""
        if word not in _ALLOWED_STARTS:
            raise Rejected(
                f"Dozwolone tylko SELECT i WITH, a instrukcja zaczyna się od {word or stmt[:20]!r}."
            )
        bad = _FORBIDDEN_WORDS.search(stmt)
        if bad:
            raise Rejected(f"Słowo {bad.group(1).upper()} oznacza zapis albo blokadę.")
        bad = _FORBIDDEN_FUNCTIONS.search(stmt)
        if bad:
            raise Rejected(f"Funkcja {bad.group(1)} jest niedozwolona.")
    return statements


def sql_payload(sql: str) -> str:
    """Tekst dla psql na stdin: sesja i transakcja tylko do odczytu, na końcu ROLLBACK.

    W transakcji READ ONLY nie da się przełączyć na zapis po pierwszym zapytaniu,
    więc nawet zapytanie, które przeszłoby bramkę skryptu, nie zapisze niczego.
    """
    validate_sql(sql)
    body = sql.strip()
    if not body.endswith(";"):
        body += ";"
    return (
        "SET default_transaction_read_only = on;\n"
        f"SET statement_timeout = '{STATEMENT_TIMEOUT}';\n"
        "BEGIN TRANSACTION READ ONLY;\n"
        f"{body}\n"
        "ROLLBACK;\n"
    )


def sql_remote_command(csv: bool) -> str:
    fmt = " --csv" if csv else ""
    return _FIND_CONTAINER.format(prefix=POSTGRES_PREFIX) + (
        'docker exec -i "$c" psql -X -q -U nexus -d nexus -v ON_ERROR_STOP=1 -P pager=off'
        + fmt
    )


# --- env ---------------------------------------------------------------------

# Nazwa wygląda na sekret albo może go zawierać (adres z hasłem, DSN, sól) — nigdy.
_SECRET_NAME = re.compile(
    r"SECRET|PASSWORD|PASSWD|PWD|TOKEN|KEY|DSN|SALT|CREDENTIAL|PRIVATE|AUTH|COOKIE|CERT|URL|URI",
)
_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")

# Biała lista: nazwy wprost i końcówki nazw flag i limitów z app/core/config.py.
ENV_ALLOWED_NAMES = frozenset(
    {
        "DB_STATEMENT_TIMEOUT_MS",
        "NEXUS_ENV",
        "DEBUG",
        "WEB_CONCURRENCY",
        "SOURCE_COMMIT",
        "MUST_GATE_MODE",
    }
)
ENV_ALLOWED_SUFFIXES = ("_ENABLED", "_MS", "_SECONDS", "_DAYS", "_MODEL")


def validate_env_names(names: Sequence[str]) -> list[str]:
    if not names:
        raise Rejected("Podaj co najmniej jedną nazwę zmiennej.")
    if len(names) > 20:
        raise Rejected("Najwyżej 20 nazw naraz.")
    for name in names:
        if not _NAME.match(name):
            raise Rejected(
                f"Nazwa {name!r} nie wygląda jak zmienna środowiskowa (A–Z, 0–9, _)."
            )
        if _SECRET_NAME.search(name):
            raise Rejected(f"{name}: nazwa wygląda na sekret, nie czytam.")
        if name not in ENV_ALLOWED_NAMES and not name.endswith(ENV_ALLOWED_SUFFIXES):
            raise Rejected(
                f"{name}: spoza białej listy (ENV_ALLOWED_NAMES, końcówki {', '.join(ENV_ALLOWED_SUFFIXES)})."
            )
    return list(dict.fromkeys(names))


def env_remote_command(names: Sequence[str]) -> str:
    """Filtr działa na serwerze: z kontenera wychodzą tylko linie z nazwami z listy.

    Czyta środowisko procesu 1 kontenera, nie `printenv` w `docker exec`, bo entrypoint
    eksportuje część zmiennych tuż przed `exec uvicorn` i widzi je tylko proces 1.
    Plik czyta root na hoście (PID z `docker inspect`), bo użytkownik aplikacji
    w kontenerze nie ma prawa do /proc/1/environ. grep z kodem 1 = żadnej nazwy nie ma.
    """
    names = validate_env_names(names)
    alternatives = "|".join(names)
    return _FIND_CONTAINER.format(prefix=BACKEND_PREFIX) + (
        "p=$(docker inspect -f '{{.State.Pid}}' \"$c\"); "
        '[ -r "/proc/$p/environ" ] || { echo "Brak dostępu do środowiska procesu $p." >&2; exit 4; }; '
        "tr '\\0' '\\n' < \"/proc/$p/environ\" | "
        f"grep -E '^({alternatives})='; [ $? -le 1 ]"
    )


def filter_env_output(names: Sequence[str], output: str) -> str:
    """Druga bramka po stronie laptopa i linia „brak” dla nazw, których proces nie ma."""
    found: dict[str, str] = {}
    for line in output.splitlines():
        name, sep, value = line.partition("=")
        if sep and name in names:
            found[name] = value
    return "\n".join(
        f"{n}={found[n]}" if n in found else f"{n}=<brak w procesie 1>" for n in names
    )


# --- backup-log --------------------------------------------------------------


def backup_log_remote_command(lines: int) -> str:
    if not 1 <= lines <= BACKUP_LOG_MAX_LINES:
        raise Rejected(f"Liczba linii od 1 do {BACKUP_LOG_MAX_LINES}.")
    return f"tail -n {int(lines)} {BACKUP_LOG}"


# --- połączenie --------------------------------------------------------------


def load_conf(path: Path | None = None) -> dict[str, str]:
    path = path or Path(os.environ.get("NEXUS_PROD_READONLY_CONF", str(DEFAULT_CONF)))
    if not path.is_file():
        raise SystemExit(f"Brak pliku konfiguracji {path} (host=…, key=…).")
    conf: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            conf[k.strip()] = os.path.expanduser(v.strip())
    if not conf.get("host") or not conf.get("key"):
        raise SystemExit(f"{path}: potrzebne host=… i key=….")
    return conf


def ssh(remote_command: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    conf = load_conf()
    argv = [
        "ssh",
        "-i",
        conf["key"],
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ConnectTimeout=15",
        conf["host"],
        remote_command,
    ]
    return subprocess.run(
        argv, check=False, input=stdin, capture_output=True, text=True, timeout=180
    )


def _finish(proc: subprocess.CompletedProcess, stdout: str | None = None) -> int:
    sys.stdout.write(proc.stdout if stdout is None else stdout + "\n")
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if args else 2
    cmd, rest = args[0], args[1:]
    try:
        if cmd == "sql":
            csv = "--csv" in rest
            rest = [a for a in rest if a != "--csv"]
            if rest and (len(rest) != 2 or rest[0] != "-f"):
                raise Rejected(
                    "sql przyjmuje tylko -f PLIK i --csv; bez -f zapytanie idzie na stdin."
                )
            text = Path(rest[1]).read_text() if rest else sys.stdin.read()
            payload = sql_payload(text)
            return _finish(ssh(sql_remote_command(csv), stdin=payload))
        if cmd == "env":
            names = validate_env_names(rest)
            proc = ssh(env_remote_command(names))
            if proc.returncode != 0:
                return _finish(proc, "")
            return _finish(proc, filter_env_output(names, proc.stdout))
        if cmd == "backup-log":
            if len(rest) > 1 or (rest and not rest[0].isdigit()):
                raise Rejected("backup-log przyjmuje jedną liczbę linii.")
            return _finish(
                ssh(backup_log_remote_command(int(rest[0]) if rest else 100))
            )
        if cmd == "health":
            if rest:
                raise Rejected("health nie przyjmuje argumentów.")
            with urllib.request.urlopen(HEALTH_URL, timeout=20) as resp:
                print(resp.read().decode())
            return 0
        raise Rejected(f"Nieznana podkomenda {cmd!r}: sql, env, backup-log, health.")
    except Rejected as exc:
        print(f"Odrzucone: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
