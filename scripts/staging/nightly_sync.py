#!/usr/bin/env python3
"""Co noc: staging na laptopie staje się aktualną kopią produkcji.

Wnioski ze stagingu idą do decyzji Artura. 02.11.2026 staging nie miał flag
z produkcji, a jego Qdrant był 10 dni starszy od bazy, więc raport i pomiar miały
złe liczby, choć staging działał normalnie.

Przebieg (decyzja Artura z 02.11.2026, docs/claude/podstawy/staging-na-laptopie.md):
flagi z procesu backendu produkcji → zrzut → nowa baza
``nexus_staging_nightly_<RRRRMMDD>`` → dosłanie plików CV → przełączenie
``STAGING_DATABASE_NAME`` → wyrównanie Qdranta → strażnik rankingu → porządki.

Każdy błąd przed przełączeniem zostawia staging na poprzedniej kopii. Produkcja
jest tylko czytana. Do raportu trafiają wyłącznie nasze komunikaty, a wyjście
procesów do prywatnego logu w ~/.nexus-staging/logs.

Kod wyjścia: 0 = kopia i ranking w porządku, 1 = błąd przed przełączeniem,
2 = przełączenie cofnięte, 3 = nowa kopia działa, ale ranking się nie zgadza,
5 = bieg pominięty (poza oknem albo inny bieg trwa).
"""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timedelta, timezone
import http.client
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from typing import Callable
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

WARSAW = ZoneInfo("Europe/Warsaw")
REPO = Path(__file__).resolve().parents[2]
CLONE_SCRIPT = REPO / "scripts/staging/clone_from_hetzner.py"
SCORING_SERVICE = REPO / "backend/app/services/scoring_service.py"

NIGHTLY_DB = re.compile(r"nexus_staging_nightly_(\d{8})\Z")
DATE_DIR = re.compile(r"\d{8}\Z")
KEEP_COPIES = 2

# Poza stemplem `ranker_version`, a zmieniają pulę i kolejność.
RANKING_POOL_FLAGS = (
    "HYBRID_POOL_ENABLED",
    "KNOWN_PEOPLE_BOOST_ENABLED",
    "KEYWORD_SEARCH_FOLDED_FTS",
    "MATCH_POOL_SIZE",
)
# Listy klientów decydują, co widać na karcie klienta. 03.11.2026 bez pierwszej z nich
# staging pokazywał 8 zamówień klienta zamiast 50, bo chował stare bez `order_type`.
CLIENT_LIST_FLAGS = (
    "MULTI_CONSULTANT_ORDER_CLIENT_IDS",
    "COST_ORDER_CLIENT_IDS",
    "EXTENDED_ORDER_ALERT_CLIENT_IDS",
)
SECRET_NAME = r"(SECRET|PASSWORD|_TOKEN(_|$)|DSN|CREDENTIAL|_KEY(_|$)|_URL(_|$))"
SAFE_VALUE = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")
# Sekret nie opuszcza serwera: filtr nazw działa już w procesie po stronie produkcji.
SETTINGS_SNIPPET = (
    "import json, re, sys\n"
    "from app.core.config import settings\n"
    "names = set(sys.argv[1:])\n"
    f"secret = re.compile({SECRET_NAME!r})\n"
    "print(json.dumps({k: v for k, v in settings.model_dump().items()"
    " if not secret.search(k) and (k in names or isinstance(v, (bool, int, float)))}))"
)

# Termin zrzutu sprzed przeniesienia backupu produkcji na 06:30 UTC (08.11.2026). Start tylko w nocy:
# rutyna odpala się po otwarciu aplikacji, a przełączenie w dzień przerwałoby pracę sesji.
DUMP_DEADLINE_UTC = (2, 15)
WINDOW_START_UTC_HOUR = 22
WINDOW_END_UTC_HOUR = 1
# Wdrożenie restartuje Postgresa produkcji, a nocą scalenia wchodzą same.
DUMP_ATTEMPTS = 4
DUMP_RETRY_PAUSE = 120
DEPLOY_INTERRUPTED = (
    "source_container_changed",
    "source_connection_terminated",
    "source_connection_closed",
    "source_connection_reset",
    "source_connection_broken_pipe",
)
PROD_WAIT_ATTEMPTS = 20
PROD_WAIT_INTERVAL = 60
# Pełne przeliczenie to ok. 70 tys. osób i kilka godzin w środku nocnych rutyn.
# Tyle różnic oznacza zmianę tekstu albo modelu, a to decyzja człowieka.
MAX_REEMBED_PEOPLE = 5000
# Limit w skrypcie to 1 h (`--max-duration`). Tu zapas na start kontenera i ostatnie pliki.
CV_FILES_TIMEOUT = 75 * 60
# 07.11.2026 strumień COPY stanął po 8 min, a limit 2 h przy normie 8–10 min zabrał całą
# noc i trzymał DROP DATABASE innej sesji. Cisza 5 min = przerwij i jedno ponowienie z manifestu.
RESTORE_TIMEOUT = 40 * 60
RESTORE_STALL_SECONDS = 5 * 60
RESTORE_POLL_SECONDS = 30
RESTORE_ATTEMPTS = 2

POSTGRES_USER = "nexus"
BACKEND = "nexus-staging-backend-1"
API = "http://localhost:8100"
FRONT = "http://localhost:3100"
HEALTH_ATTEMPTS = 60
HEALTH_INTERVAL = 15

OK_MARKER = "copy-ok.json"
LOG_DAYS = 14
EXIT_OK, EXIT_BEFORE_SWITCH, EXIT_ROLLED_BACK, EXIT_RANKING, EXIT_SKIPPED = (
    0,
    1,
    2,
    3,
    5,
)


class SyncError(Exception):
    """Bezpieczny komunikat do raportu: bez wyjścia procesów i danych."""


class Report:
    """Ślady dla Porannego raportu w formacie z ~/.claude/nexus-rutyny/ZASADY.md."""

    NAME = "staging-kopia"

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.done: list[str] = []
        self.waiting: list[str] = []

    def write(self, *, exit_code: int, sha: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(WARSAW).strftime("%H:%M")
        (self.directory / f"{self.NAME}.ok").write_text(
            f"{stamp} main={sha or 'nieznany'} kod={exit_code}\n"
        )
        details = self.directory / f"{self.NAME}.md"
        details.unlink(missing_ok=True)
        if not self.waiting and exit_code == EXIT_OK:
            return
        lines = [
            "## Zrobione",
            *(f"- {line}" for line in self.done),
            "",
            "## Czeka na Artura",
        ]
        lines += [f"- {line}" for line in self.waiting]
        details.write_text("\n".join(lines) + "\n")


def scoring_inputs(source: str) -> tuple[str, ...]:
    """`_SCORING_CACHE_INPUTS` bez importu backendu: skrypt działa na czystym Pythonie hosta."""
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.AnnAssign)
            and getattr(node.target, "id", "") == "_SCORING_CACHE_INPUTS"
        ):
            return tuple(ast.literal_eval(node.value))
    raise SyncError("Brak _SCORING_CACHE_INPUTS w scoring_service.py")


def allowed_flags(source: str) -> tuple[str, ...]:
    return scoring_inputs(source) + RANKING_POOL_FLAGS + CLIENT_LIST_FLAGS


def client_list_text(name: str, value: object) -> str:
    """Same identyfikatory: inny wpis pomija też `config.py`, więc literówka nie zatrzyma kopii."""
    if not isinstance(value, str):
        raise SyncError(f"Lista {name} nie jest tekstem, plik flag nie powstał")
    chunks = (chunk.strip() for chunk in value.split(","))
    return ",".join(chunk for chunk in chunks if re.fullmatch(r"[0-9]+", chunk))


def flag_lines(values: dict, allowed: tuple[str, ...]) -> str:
    """Treść pliku flag: tylko lista dozwolonych, tylko proste wartości."""
    lines = []
    for name in allowed:
        if name not in values:
            continue
        value = values[name]
        if name in CLIENT_LIST_FLAGS:
            text = client_list_text(name, value)
        elif isinstance(value, bool):
            text = "true" if value else "false"
        elif isinstance(value, (int, float)):
            text = str(value)
        elif isinstance(value, str) and SAFE_VALUE.fullmatch(value):
            text = value
        else:
            raise SyncError(
                f"Flaga {name} ma wartość inną niż prosta, plik flag nie powstał"
            )
        lines.append(f"{name}={text}")
    return "\n".join(lines) + "\n"


def other_differences(
    prod: dict, staging: dict, allowed: tuple[str, ...]
) -> dict[str, list]:
    """Inne ustawienia bool i liczbowe niż na produkcji. Tylko do raportu."""
    return {
        name: [prod[name], staging[name]]
        for name in sorted(prod.keys() & staging.keys())
        if name not in allowed
        and not re.search(SECRET_NAME, name)
        and isinstance(prod[name], (bool, int, float))
        and isinstance(staging[name], (bool, int, float))
        and prod[name] != staging[name]
    }


def window_refusal(now_utc: datetime) -> str | None:
    if now_utc.hour >= WINDOW_START_UTC_HOUR or now_utc.hour < WINDOW_END_UTC_HOUR:
        return None
    return (
        f"Start o {now_utc:%H:%M} UTC jest poza nocnym oknem "
        f"({WINDOW_START_UTC_HOUR}:00–0{WINDOW_END_UTC_HOUR}:00 UTC). Staging został na poprzedniej kopii."
    )


def dump_deadline(now_utc: datetime) -> datetime:
    deadline = now_utc.replace(
        hour=DUMP_DEADLINE_UTC[0], minute=DUMP_DEADLINE_UTC[1], second=0, microsecond=0
    )
    return deadline if deadline > now_utc else deadline + timedelta(days=1)


def active_database(env_text: str) -> str:
    names = re.findall(r"^STAGING_DATABASE_NAME=(\S+)$", env_text, re.M)
    if len(names) != 1:
        raise SyncError(
            "Plik env stagingu musi mieć dokładnie jeden wpis STAGING_DATABASE_NAME"
        )
    return names[0]


def switched_env(env_text: str, database: str) -> str:
    active_database(env_text)
    return re.sub(
        r"^STAGING_DATABASE_NAME=\S+$",
        f"STAGING_DATABASE_NAME={database}",
        env_text,
        flags=re.M,
    )


def atomic_write(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(text)
    os.replace(temporary, path)


def nightly_date(database: str) -> str | None:
    match = NIGHTLY_DB.fullmatch(database)
    return match.group(1) if match else None


def retention_plan(
    databases: set[str],
    directories: set[str],
    ok_dates: set[str],
    *,
    active: str,
    connected: set[str],
    keep: int = KEEP_COPIES,
) -> tuple[list[str], list[str]]:
    """Co usunąć: wyłącznie bazy i katalogi nocne, poza dwiema ostatnimi dobrymi kopiami."""
    nightly = {db: nightly_date(db) for db in databases if nightly_date(db)}
    good = sorted(ok_dates & set(nightly.values()))
    keep_dates = set(good[-keep:]) if keep else set()
    in_use = {date for db, date in nightly.items() if db == active or db in connected}
    drop = sorted(
        db
        for db, date in nightly.items()
        if date not in keep_dates and date not in in_use
    )
    remove = sorted(
        d
        for d in directories
        if DATE_DIR.fullmatch(d) and d not in keep_dates and d not in in_use
    )
    return drop, remove


def parse_parity(stdout: str) -> tuple[str, int]:
    """Linia strażnika i liczba osób z innym wektorem."""
    for line in stdout.splitlines():
        match = re.fullmatch(r"ranker_version=\S+ kopia=\S+ stale=(\d+)", line.strip())
        if match:
            return line.strip(), int(match.group(1))
    raise SyncError("Strażnik rankingu nie wypisał wyniku")


class Log:
    """Prywatny log poza repo: tam idzie wyjście procesów, nigdy do raportu."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path

    def write(self, text: str) -> None:
        if self.path is None or not text:
            return
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as out:
            out.write(text if text.endswith("\n") else text + "\n")


LOG = Log()


def run_cmd(
    command: list[str],
    *,
    timeout: float = 1800,
    check: bool = True,
    env: dict | None = None,
    what: str = "Komenda",
    stalled: Callable[[], bool] | None = None,
    poll: float = RESTORE_POLL_SECONDS,
) -> subprocess.CompletedProcess:
    """Własna grupa procesów, żeby timeout zabił też ssh, którego uruchomił klon.

    `stalled` jest pytane co `poll` sekund; prawda przerywa komendę przed limitem czasu.
    """
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
        start_new_session=True,
        env=env,
    )
    deadline = time.monotonic() + timeout
    reason = ""
    while True:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            # Ponowne communicate po TimeoutExpired nie gubi wyjścia (dokumentacja subprocess).
            stdout, stderr = process.communicate(
                timeout=min(remaining, poll) if stalled else remaining
            )
            break
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                reason = f"przekroczony czas {int(timeout // 60)} min"
            elif stalled is not None and stalled():
                reason = f"brak postępu przez {RESTORE_STALL_SECONDS // 60} min"
            if reason:
                break
    if reason:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        raise SyncError(f"{what}: {reason}")
    LOG.write(stdout)
    LOG.write(stderr)
    if check and process.returncode:
        raise SyncError(
            f"{what}: kod wyjścia {process.returncode}, szczegóły w prywatnym logu"
        )
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


class Config:
    def __init__(self, args: argparse.Namespace) -> None:
        self.ssh_host: str = args.ssh_host
        self.ssh_identity: Path = args.ssh_identity
        self.repo = Path(os.environ.get("NEXUS_REPO", str(Path.home() / "NEXUS")))
        self.code = Path(
            os.environ.get("STAGING_CODE_DIR", str(Path.home() / ".nexus-staging/code"))
        )
        self.env_file = Path(
            os.environ.get(
                "STAGING_ENV_FILE",
                str(
                    Path.home()
                    / ".codex/worktrees/nexus-staging-data-promotion/.env.staging.local"
                ),
            )
        )
        # Obok pliku głównego, bo w ten sam katalog patrzą backendy gałęzi.
        self.flags_file = self.env_file.with_name(".env.staging-flags.local")
        self.root = Path.home() / ".local/share/nexus-staging-nightly"
        self.lock = Path(
            os.environ.get(
                "STAGING_SYNC_LOCK",
                str(Path.home() / ".nexus-staging/nightly-sync.pid"),
            )
        )
        self.settings_snapshot = (
            Path.home() / ".nexus-staging/settings-differences.json"
        )
        self.logs = Path.home() / ".nexus-staging/logs"


def ssh(
    cfg: Config, remote: list[str], *, timeout: float = 120, what: str
) -> subprocess.CompletedProcess:
    command = [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "IdentitiesOnly=yes",
        "-i",
        str(cfg.ssh_identity),
        "--",
        cfg.ssh_host,
        shlex.join(remote),
    ]
    return run_cmd(command, timeout=timeout, what=what)


def prod_container(cfg: Config, prefix: str) -> str:
    """Nazwa i id zmieniają się przy wdrożeniu, więc ustalane przy każdym biegu."""
    out = ssh(
        cfg,
        ["docker", "ps", "--no-trunc", "--format", "{{.ID}} {{.Names}}"],
        what="Lista kontenerów produkcji",
    ).stdout
    ids = [
        line.split()[0]
        for line in out.splitlines()
        if len(line.split()) == 2 and line.split()[1].startswith(prefix)
    ]
    if len(ids) != 1:
        raise SyncError(
            f"Kontener {prefix}* na produkcji: {len(ids)} zamiast 1 (wdrożenie w toku?)"
        )
    return ids[0]


def wait_for_prod_container(cfg: Config, prefix: str) -> str:
    """Wdrożenie na chwilę usuwa kontenery produkcji, także Postgresa."""
    for attempt in range(PROD_WAIT_ATTEMPTS):
        try:
            return prod_container(cfg, prefix)
        except SyncError:
            if attempt == PROD_WAIT_ATTEMPTS - 1:
                raise
            time.sleep(PROD_WAIT_INTERVAL)
    raise AssertionError("unreachable")


def read_prod_settings(cfg: Config, allowed: tuple[str, ...]) -> dict:
    backend = wait_for_prod_container(cfg, "backend-ocgkw")
    out = ssh(
        cfg,
        ["docker", "exec", backend, "python", "-c", SETTINGS_SNIPPET, *allowed],
        what="Odczyt ustawień produkcji",
    ).stdout
    return json.loads(out.strip().splitlines()[-1])


def read_staging_settings(allowed: tuple[str, ...]) -> dict:
    out = run_cmd(
        ["docker", "exec", BACKEND, "python", "-c", SETTINGS_SNIPPET, *allowed],
        timeout=120,
        what="Odczyt ustawień stagingu",
    ).stdout
    return json.loads(out.strip().splitlines()[-1])


def local_postgres() -> str:
    out = run_cmd(
        [
            "docker",
            "ps",
            "--no-trunc",
            "--filter",
            "label=com.docker.compose.project=nexus-staging",
            "--filter",
            "label=com.docker.compose.service=postgres",
            "--format",
            "{{.ID}}",
        ],
        timeout=60,
        what="Postgres stagingu",
    ).stdout.split()
    if len(out) != 1:
        raise SyncError("Postgres stagingu nie działa")
    return out[0]


def psql(postgres: str, database: str, sql: str, *, timeout: float = 300) -> str:
    return run_cmd(
        [
            "docker",
            "exec",
            "-i",
            postgres,
            "psql",
            "-X",
            "-U",
            POSTGRES_USER,
            "-d",
            database,
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ],
        timeout=timeout,
        what="Zapytanie do Postgresa stagingu",
    ).stdout


def existing_databases(postgres: str) -> set[str]:
    return set(psql(postgres, "postgres", "SELECT datname FROM pg_database").split())


def connections(postgres: str, database: str) -> int:
    if not re.fullmatch(r"[a-z0-9_]+", database):
        raise SyncError("Niedozwolona nazwa bazy")
    return int(
        psql(
            postgres,
            "postgres",
            f"SELECT count(*) FROM pg_stat_activity WHERE datname = '{database}'",
        ).strip()
    )


def clone_step(
    arguments: list[str],
    *,
    timeout: float,
    what: str,
    stalled: Callable[[], bool] | None = None,
) -> str:
    """Komunikat błędu klona jest bezpieczny z założenia (clone_from_hetzner.py)."""
    result = run_cmd(
        [sys.executable, str(CLONE_SCRIPT), *arguments],
        timeout=timeout,
        check=False,
        what=what,
        stalled=stalled,
    )
    if result.returncode:
        raise SyncError(f"{what}: {result.stderr.strip()[:300]}")
    return result.stdout.strip().rsplit(" ", 1)[-1]


def dump_production(cfg: Config, database: str, output_root: Path) -> Path:
    arguments = [
        "--dump-only",
        "--ssh-host",
        cfg.ssh_host,
        "--ssh-identity",
        str(cfg.ssh_identity),
        "--target-db",
        database,
        "--output-root",
        str(output_root),
    ]
    deadline = dump_deadline(datetime.now(timezone.utc))
    for attempt in range(1, DUMP_ATTEMPTS + 1):
        source = wait_for_prod_container(cfg, "postgres-ocgkw")
        seconds = (deadline - datetime.now(timezone.utc)).total_seconds()
        if seconds <= 0:
            raise SyncError("Zrzut produkcji: minął termin przed backupem produkcji")
        try:
            return Path(
                clone_step(
                    [*arguments, "--source-container", source],
                    timeout=seconds,
                    what="Zrzut produkcji",
                )
            )
        except SyncError as error:
            # 03.11.2026: scalenie o północy zrestartowało Postgresa w 9. minucie zrzutu.
            if attempt == DUMP_ATTEMPTS or not any(
                reason in str(error) for reason in DEPLOY_INTERRUPTED
            ):
                raise
            time.sleep(DUMP_RETRY_PAUSE)
    raise AssertionError("unreachable")


def restore_progress(postgres: str, database: str) -> str:
    """Odcisk postępu odtwarzania: rozmiar bazy, wiersze COPY i start bieżącej instrukcji.

    Z bazy `postgres`, żeby sonda nie zmieniała sama `query_start` odtwarzanej bazy.
    """
    if not re.fullmatch(r"[a-z0-9_]+", database):
        raise SyncError("Niedozwolona nazwa bazy")
    return psql(
        postgres,
        "postgres",
        f"SELECT pg_database_size('{database}')::text"
        " || ':' || coalesce((SELECT sum(tuples_processed)::text"
        f" FROM pg_stat_progress_copy WHERE datname = '{database}'), '0')"
        " || ':' || coalesce((SELECT max(query_start)::text"
        f" FROM pg_stat_activity WHERE datname = '{database}'), '')",
        timeout=RESTORE_POLL_SECONDS,
    ).strip()


class RestoreWatch:
    """Liczy ciszę od ostatniej zmiany odcisku; sonda bez odpowiedzi to też cisza."""

    def __init__(
        self, postgres: str, database: str, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.postgres = postgres
        self.database = database
        self.clock = clock
        self.mark = ""
        self.changed = clock()

    def stalled(self) -> bool:
        try:
            mark = restore_progress(self.postgres, self.database)
        except (SyncError, OSError, ValueError):
            mark = self.mark
        if mark != self.mark:
            self.mark = mark
            self.changed = self.clock()
        return self.clock() - self.changed >= RESTORE_STALL_SECONDS


def drop_failed_restore(postgres: str, database: str) -> None:
    """Tylko baza z tej nocy: `sync` nie zaczyna, gdy taka nazwa już istnieje.

    FORCE kończy backend czekający na strumień, który po 07.11 trzymał DROP innej bazy.
    """
    if not NIGHTLY_DB.fullmatch(database):
        raise SyncError("Niedozwolona nazwa bazy")
    psql(postgres, "postgres", f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')


def restore_copy(postgres: str, database: str, manifest: Path) -> int:
    """Zwraca numer podejścia, które się udało."""
    for attempt in range(1, RESTORE_ATTEMPTS + 1):
        try:
            clone_step(
                [
                    "--restore-manifest",
                    str(manifest),
                    "--target-db",
                    database,
                    "--local-postgres-container",
                    postgres,
                ],
                timeout=RESTORE_TIMEOUT,
                what="Odtworzenie kopii",
                stalled=RestoreWatch(postgres, database).stalled,
            )
            break
        except SyncError as error:
            if attempt == RESTORE_ATTEMPTS:
                raise
            LOG.write(f"{error}; ponawiam z manifestu\n")
            drop_failed_restore(postgres, database)
    if not int(psql(postgres, database, "SELECT count(*) FROM candidates").strip()):
        raise SyncError("Nowa kopia nie ma żadnego kandydata")
    return attempt


def compose(cfg: Config) -> list[str]:
    command = [
        "docker",
        "compose",
        "-p",
        "nexus-staging",
        "--project-directory",
        str(cfg.code),
        "-f",
        str(cfg.code / "docker-compose.staging.yml"),
        "--env-file",
        str(cfg.env_file),
    ]
    if cfg.flags_file.exists():
        command += ["--env-file", str(cfg.flags_file)]
    return command


def compose_env(sha: str) -> dict:
    return {
        **os.environ,
        "GIT_SHA": sha,
        "BUILT_AT": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def origin_main(cfg: Config) -> str:
    run_cmd(
        ["git", "-C", str(cfg.repo), "fetch", "--quiet", "origin", "main"],
        timeout=300,
        what="git fetch",
    )
    return run_cmd(
        ["git", "-C", str(cfg.repo), "rev-parse", "origin/main"],
        timeout=60,
        what="git rev-parse",
    ).stdout.strip()


def health() -> dict:
    try:
        with urllib.request.urlopen(f"{API}/api/health", timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # 503 przy `unhealthy` też ma treść JSON.
        try:
            return json.load(error)
        except ValueError:
            return {}
    except (OSError, ValueError, http.client.HTTPException):
        return {}


def front_answers() -> bool:
    try:
        with urllib.request.urlopen(f"{FRONT}/login", timeout=10) as response:
            return response.status == 200
    except (OSError, http.client.HTTPException):
        return False


def build_code(cfg: Config, sha: str) -> None:
    """Przed przełączeniem: nieudany build zostawia staging na starej kopii i starym kodzie."""
    if cfg.code.exists():
        run_cmd(
            ["git", "-C", str(cfg.code), "checkout", "--quiet", "--detach", sha],
            timeout=120,
            what="Checkout kodu",
        )
    else:
        cfg.code.parent.mkdir(parents=True, exist_ok=True)
        run_cmd(
            [
                "git",
                "-C",
                str(cfg.repo),
                "worktree",
                "add",
                "--quiet",
                "--detach",
                str(cfg.code),
                sha,
            ],
            timeout=300,
            what="Worktree kodu",
        )
    link = cfg.code / ".env.staging.local"
    if link.is_symlink() or not link.exists():
        link.unlink(missing_ok=True)
        link.symlink_to(cfg.env_file)
    if health().get("version") != sha:
        run_cmd(
            [*compose(cfg), "build", "backend", "worker", "frontend"],
            timeout=3600,
            env=compose_env(sha),
            what="Build stagingu",
        )


def start_staging(cfg: Config, sha: str) -> None:
    run_cmd(
        [*compose(cfg), "up", "-d", "--no-deps", "--no-build", "backend", "worker", "frontend"],
        timeout=600,
        env=compose_env(sha),
        what="Start stagingu",
    )


def wait_healthy(
    postgres: str, database: str, sha: str, *, attempts: int = HEALTH_ATTEMPTS
) -> str | None:
    """None = zdrowy na tej bazie. Inaczej powód; pierwszy start wykonuje migracje, stąd długie okno."""
    reason = "brak odpowiedzi API"
    for _ in range(attempts):
        data = health()
        checks = data.get("checks") or {}
        if data.get("version") != sha:
            reason = f"wersja {str(data.get('version'))[:12]} zamiast {sha[:12]}"
        elif data.get("status") == "unhealthy" or checks.get("database") != "healthy":
            reason = "baza niezdrowa w /api/health"
        elif str(checks.get("migrations", "")).startswith("unhealthy"):
            # Zdarza się przy rewizji, której main nie zna: nowy kod na starym schemacie.
            return "schemat kopii nieaktualny (checks.migrations)"
        elif not front_answers():
            reason = "front nie odpowiada"
        elif connections(postgres, database) == 0:
            reason = "backend nie jest podłączony do tej bazy"
        else:
            return None
        time.sleep(HEALTH_INTERVAL)
    return reason


def cv_files_stats(log: str) -> tuple[int, int]:
    """(pliki, bajty) z ostatnich statystyk rclone. Compose pisze w tym samym strumieniu."""
    for line in reversed(log.splitlines()):
        try:
            stats = json.loads(line)["stats"]
        except (ValueError, LookupError, TypeError):
            continue
        return stats["transfers"], stats["bytes"]
    raise SyncError("rclone nie wypisał statystyk, szczegóły w prywatnym logu")


def send_cv_files(cfg: Config, report: Report) -> None:
    """Pliki z dzisiejszej bazy, zanim ta baza zacznie działać na stagingu.

    Błąd nie zatrzymuje kopii: świeża baza z brakami w nowych plikach jest lepsza niż
    wczorajsza, a następna noc dosyła resztę. Wymaga `build_code`, bo skrypt i link do
    pliku env leżą w katalogu kodu.
    """
    try:
        result = run_cmd(
            [
                *compose(cfg),
                "--profile",
                "restore",
                "run",
                "--rm",
                "-T",
                "--no-deps",
                "--entrypoint",
                "/bin/sh",
                "restore",
                "/staging/sync_cv_files.sh",
            ],
            timeout=CV_FILES_TIMEOUT,
            what="Dosłanie plików CV",
        )
        files, size = cv_files_stats(result.stderr)
    except (SyncError, OSError, ValueError, LookupError, TypeError) as error:
        report.waiting.append(
            f"Pliki CV niedosłane: {error}. Nowe rekordy mogą dawać 503 w podglądzie oryginału, "
            "a QC pisać „Brak tekstu oryginalnego CV”, więc nie opieraj na nich wniosków. "
            "Warianty: 1) sprawdzić log i uruchomić krok ręcznie (rekomendowane), 2) poczekać na następną noc."
        )
        return
    report.done.append(f"Pliki CV z produkcji: dosłane {files}, {size / 2**20:.0f} MB.")


def run_parity() -> tuple[int, str, int, list[str]]:
    result = run_cmd(
        ["docker", "exec", BACKEND, "python", "-m", "scripts.staging_ranking_parity"],
        timeout=3600,
        check=False,
        what="Strażnik rankingu",
    )
    line, stale = parse_parity(result.stdout)
    warnings = [row for row in result.stderr.splitlines() if row.startswith("UWAGA:")]
    return result.returncode, line, stale, warnings


def align_qdrant(report: Report) -> None:
    _, _, stale, _ = run_parity()
    report.done.append(f"Qdrant przed wyrównaniem: stale={stale}.")
    if stale > MAX_REEMBED_PEOPLE:
        report.waiting.append(
            f"Qdrant niewyrównany: stale={stale}, limit nocy {MAX_REEMBED_PEOPLE}. Możliwa zmiana tekstu albo modelu. "
            "Warianty: 1) sprawdzić przyczynę i wyrównać ręcznie (rekomendowane), 2) zostawić do następnej nocy."
        )
        return
    for target in (
        ["--target", "candidates", "--resume"],
        ["--target", "jobs", "--only-missing"],
    ):
        run_cmd(
            [
                "docker",
                "exec",
                BACKEND,
                "python",
                "-m",
                "scripts.reembed_collections",
                *target,
                "--commit",
            ],
            timeout=2 * 3600,
            what="Wyrównanie Qdranta " + target[1],
        )


def report_setting_differences(
    cfg: Config, prod: dict, allowed: tuple[str, ...], report: Report
) -> None:
    """Tylko nowe względem poprzedniej nocy: integracje różnią się celowo i co noc."""
    differences = other_differences(prod, read_staging_settings(allowed), allowed)
    try:
        previous = json.loads(cfg.settings_snapshot.read_text())
    except (OSError, ValueError):
        previous = {}
    new = {
        name: values
        for name, values in differences.items()
        if previous.get(name) != values
    }
    atomic_write(cfg.settings_snapshot, json.dumps(differences, indent=1) + "\n")
    report.done.append(
        f"Inne ustawienia bool i liczbowe niż na produkcji: {len(differences)}, nowe: {len(new)}."
    )
    if new:
        rows = ", ".join(
            f"{name}: produkcja {p}, staging {s}"
            for name, (p, s) in sorted(new.items())
        )
        report.waiting.append(
            f"Nowe różnice ustawień: {rows}. Warianty: 1) zostawić, gdy różnica jest celowa (rekomendowane), "
            "2) dopisać do listy flag w nightly_sync.py i docker-compose.staging.yml."
        )


def apply_retention(cfg: Config, postgres: str, report: Report) -> None:
    databases = {db for db in existing_databases(postgres) if nightly_date(db)}
    directories = (
        {p.name for p in cfg.root.iterdir() if p.is_dir() and not p.is_symlink()}
        if cfg.root.exists()
        else set()
    )
    ok_dates = {name for name in directories if (cfg.root / name / OK_MARKER).exists()}
    connected = {db for db in databases if connections(postgres, db) > 0}
    drop, remove = retention_plan(
        databases,
        directories,
        ok_dates,
        active=active_database(cfg.env_file.read_text()),
        connected=connected,
    )
    for database in drop:
        # Bez FORCE: ktoś podłączony w tej chwili = Postgres odmawia i baza zostaje.
        if run_cmd(
            [
                "docker",
                "exec",
                "-i",
                postgres,
                "psql",
                "-X",
                "-U",
                POSTGRES_USER,
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                f'DROP DATABASE "{database}"',
            ],
            timeout=600,
            check=False,
            what="DROP",
        ).returncode:
            remove = [d for d in remove if d != nightly_date(database)]
            report.done.append(
                f"Porządki: {database} zostaje, Postgres odmówił usunięcia."
            )
    for name in remove:
        shutil.rmtree(cfg.root / name)
    report.done.append(
        f"Porządki: usunięte bazy {drop or 'brak'}, katalogi {remove or 'brak'}."
    )
    cutoff = time.time() - LOG_DAYS * 86400
    for log in cfg.logs.glob("*.log"):
        if log.stat().st_mtime < cutoff:
            log.unlink()
    if connected:
        report.done.append(f"Kopie nocne z podłączeniami: {sorted(connected)}.")


def acquire_lock(lock: Path) -> bool:
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            os.kill(int(lock.read_text().strip()), 0)
            return False
        except (ValueError, ProcessLookupError):
            lock.unlink(missing_ok=True)
            return acquire_lock(lock)
    with os.fdopen(fd, "w") as out:
        out.write(str(os.getpid()))
    return True


def sync(cfg: Config, report: Report, now_utc: datetime, date: str) -> tuple[int, str]:
    refusal = window_refusal(now_utc)
    if refusal:
        report.waiting.append(
            refusal
            + " Warianty: 1) poczekać na następną noc (rekomendowane), 2) zostawić bez reakcji."
        )
        return EXIT_SKIPPED, ""

    database = f"nexus_staging_nightly_{date}"
    sha = ""
    try:
        allowed = allowed_flags(SCORING_SERVICE.read_text())
        active_database(cfg.env_file.read_text())
        postgres = local_postgres()
        if database in existing_databases(postgres):
            raise SyncError(f"Baza {database} już istnieje; zostawiona bez zmian")
        date_dir = cfg.root / date
        cfg.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        date_dir.mkdir(mode=0o700, exist_ok=True)
        sha = origin_main(cfg)

        prod_settings = read_prod_settings(cfg, allowed)
        flags = flag_lines(prod_settings, allowed)
        report.done.append(
            f"Flagi z produkcji: {len(flags.splitlines())} z listy dozwolonych."
        )

        started = time.monotonic()
        manifest = dump_production(cfg, database, date_dir)
        size = json.loads(manifest.read_text())["dump"]["bytes"]
        dumped = time.monotonic()
        attempt = restore_copy(postgres, database, manifest)
        retried = " Odtworzenie udało się za drugim podejściem." if attempt == 2 else ""
        report.done.append(
            f"Kopia {database}: zrzut {size / 2**30:.1f} GB w {(dumped - started) / 60:.0f} min, "
            f"odtworzenie {(time.monotonic() - dumped) / 60:.0f} min.{retried}"
        )
        build_code(cfg, sha)
        send_cv_files(cfg, report)
    except (SyncError, OSError, ValueError, LookupError) as error:
        report.waiting.append(
            f"Kopia nieudana przed przełączeniem: {error}. Staging został na poprzedniej kopii. "
            "Warianty: 1) poczekać na następną noc (rekomendowane), 2) sprawdzić log i uruchomić ręcznie w oknie."
        )
        return EXIT_BEFORE_SWITCH, sha

    # Czytane dopiero tutaj: zrzut trwa długo, a ręczna zmiana pliku w nocy ma przetrwać.
    env_before = cfg.env_file.read_text()
    previous = active_database(env_before)
    flags_before = cfg.flags_file.read_text() if cfg.flags_file.exists() else None
    code = EXIT_OK
    try:
        atomic_write(cfg.flags_file, flags)
        atomic_write(cfg.env_file, switched_env(env_before, database))
        start_staging(cfg, sha)
        failure = wait_healthy(postgres, database, sha)
        if failure:
            raise SyncError(failure)
    except (SyncError, OSError, ValueError) as error:
        atomic_write(cfg.env_file, env_before)
        if flags_before is None:
            cfg.flags_file.unlink(missing_ok=True)
        else:
            atomic_write(cfg.flags_file, flags_before)
        back = "nie odpowiada"
        try:
            start_staging(cfg, sha)
            back = wait_healthy(postgres, previous, sha) or "zdrowy"
        except (SyncError, OSError):
            pass
        report.waiting.append(
            f"Przełączenie na {database} cofnięte: {error}. Staging na {previous}: {back}. "
            "Warianty: 1) sprawdzić log z tej nocy (rekomendowane), 2) poczekać na następną noc."
        )
        return EXIT_ROLLED_BACK, sha

    atomic_write(
        date_dir / OK_MARKER, json.dumps({"database": database, "sha": sha}) + "\n"
    )
    report.done.append(
        f"Staging przełączony z {previous} na {database}, kod {sha[:12]}."
    )
    try:
        align_qdrant(report)
        parity_code, line, _, warnings = run_parity()
        report.done.append(f"Strażnik rankingu po wyrównaniu: {line}.")
        if parity_code:
            code = EXIT_RANKING
            report.waiting.append(
                "Ranking na stagingu nie zgadza się z produkcją: "
                + " ".join(warnings)
                + " Warianty: 1) sprawdzić flagi i kontrakt w kodzie (rekomendowane), 2) nie opierać dziś wniosków na stagingu."
            )
    except (SyncError, OSError, ValueError) as error:
        code = EXIT_RANKING
        report.waiting.append(
            f"Nowa kopia działa, ale wyrównanie rankingu padło: {error}. "
            "Warianty: 1) uruchomić wyrównanie ręcznie (rekomendowane), 2) poczekać na następną noc."
        )
    try:
        report_setting_differences(cfg, prod_settings, allowed, report)
    except (SyncError, OSError, ValueError) as error:
        report.done.append(f"Różnice ustawień niesprawdzone: {error}.")
    return code, sha


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--ssh-identity", required=True, type=Path)
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args()
    cfg = Config(args)
    cfg.logs.mkdir(mode=0o700, parents=True, exist_ok=True)
    LOG.path = cfg.logs / f"{datetime.now(WARSAW):%Y%m%d}.log"
    report = Report(
        args.report_dir
        or Path.home()
        / ".claude/nexus-rutyny/raporty"
        / datetime.now(WARSAW).strftime("%F")
    )
    if not acquire_lock(cfg.lock):
        report.waiting.append(
            "Poprzedni bieg kopii jeszcze trwa, ten pominięty. Warianty: 1) sprawdzić proces (rekomendowane), 2) poczekać na następną noc."
        )
        report.write(exit_code=EXIT_SKIPPED, sha="")
        return EXIT_SKIPPED
    code, sha = EXIT_BEFORE_SWITCH, ""
    try:
        code, sha = sync(
            cfg,
            report,
            datetime.now(timezone.utc),
            datetime.now(WARSAW).strftime("%Y%m%d"),
        )
        if code != EXIT_SKIPPED:
            apply_retention(cfg, local_postgres(), report)
    except (SyncError, OSError, ValueError) as error:
        report.waiting.append(
            f"Porządki po kopii niedokończone: {error}. Warianty: 1) sprawdzić log (rekomendowane), 2) następna noc powtórzy."
        )
    finally:
        cfg.lock.unlink(missing_ok=True)
        report.write(exit_code=code, sha=sha)
    print("\n".join(report.done + report.waiting))
    return code


if __name__ == "__main__":
    sys.exit(main())
