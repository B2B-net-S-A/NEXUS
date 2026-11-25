#!/usr/bin/env python3
"""Gdzie jest PR NEXUSA: jeden wiersz na PR, od kolejki merge'ów do produkcji.

    scripts/gdzie_jest.py 4035 4036     # te PR-y
    scripts/gdzie_jest.py               # PR-y otwarte albo scalone w ostatnich 24 h
    scripts/gdzie_jest.py --godziny 36  # dłuższe okno wyszukiwania

Po co (26.11.2026): w 30 dniach ok. 50 pytań Artura brzmiało „dlaczego nie
wdrożone / czemu wypada z kolejki”, a 12 „sprawdziłeś na produkcji?”. Stan
zmiany jest rozrzucony między PR, kolejkę merge'ów, pas migracji, okno
wdrożeń i ``/api/health``, więc sesja odpowiadała z pamięci. Ten skrypt czyta
wszystkie te miejsca naraz i mówi to jednym wierszem. Bramka Stop
(``~/.claude/hooks/gdzie-jest-gate.js``) wymaga tego wiersza w ostatniej
wiadomości sesji z PR-em, a rutyna „kontrola po wdrożeniu” wysyła rano
zestawienie z wczoraj.

Skąd stan (po kolei, pierwszy pasujący wygrywa):

* zamknięty bez scalenia; draft; etykieta ``wstrzymaj``;
* w kolejce: ``mergeQueueEntry`` z GraphQL. Pola ``isInMergeQueue`` nie
  używamy, bo ``gh pr view --json`` go nie ma;
* pas migracji: etykieta ``czeka-na-migracje`` (``queue_migration_lane.py``);
* wypadł z kolejki: ostatnie zdarzenie kolejki to ``RemovedFromMergeQueueEvent``
  (w REST ``removed_from_merge_queue``) z powodem od GitHuba. Przy
  ``failed_checks`` czerwone testy z logu joba biegu ``merge_group`` dla
  ``gh-readonly-queue/main/pr-<N>-…`` (parser z ``queue_failure_feedback.py``);
* scalony i na produkcji: ``git merge-base --is-ancestor <merge> <version>``,
  gdzie ``version`` to SHA z ``/api/health``. PR, który zmienia ``frontend/``,
  sprawdzamy też z frontem: ``sentry-release`` w HTML strony ``/login``;
* scalony, same pliki poza obrazem (``deploy_needed.INERT_PREFIXES``):
  wdrożenie niepotrzebne, ``/api/health`` może dalej pokazywać starszy SHA;
* scalony, nie na produkcji: Deploy w toku albo czerwony (ostatnie biegi
  ``deploy.yml`` po scaleniu), a bez tego okno wdrożeń: pon–pt 18:00–08:00
  czasu warszawskiego, w weekend zawsze (``docs/claude/podstawy/deploy.md``).

Kod wyjścia 0 także wtedy, gdy któryś PR wypadł: to raport, nie bramka.
Stdlib + ``gh`` (konto z dostępem do repo) + ``git``. Python 3.9.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None  # type: ignore[assignment]

_REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_DIR / ".github" / "scripts"))
from deploy_needed import is_inert  # noqa: E402
from queue_failure_feedback import first_job_error, parse_failures  # noqa: E402

REPO = "B2B-net-S-A/NEXUS"
HEALTH_URL = "https://api.nexus.b2bnetwork.pl/api/health"
LOGIN_URL = "https://nexus.b2bnetwork.pl/login"
WARSAW = ZoneInfo("Europe/Warsaw") if ZoneInfo else timezone(timedelta(hours=1))
WINDOW_CLOSE_HOUR = 8
WINDOW_OPEN_HOUR = 18
FILES_PAGE = 100
TITLE_LIMIT = 60
MAX_LOGS_PER_PR = 2
HOLD_LABEL = "wstrzymaj"
MIGRATION_WAIT_LABEL = "czeka-na-migracje"
MIGRATIONS_PREFIX = "backend/alembic/versions/"
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
SENTRY_RELEASE_RE = re.compile(r"sentry-release=([0-9a-f]{7,40})")

REMOVAL_REASONS = {
    "failed_checks": "czerwone checki grupy",
    "merge_conflict": "konflikt z mainem",
    "manual": "zdjęty ręcznie albo przez pas migracji",
}
QUEUE_STATES = {
    "QUEUED": "czeka na grupę",
    "AWAITING_CHECKS": "testy grupy w toku",
    "MERGEABLE": "grupa zielona, zaraz wejdzie",
    "UNMERGEABLE": "grupa czerwona, zaraz wypadnie",
    "LOCKED": "scalanie",
}
CHECK_STATES = {
    "SUCCESS": "zielone",
    "PENDING": "w toku",
    "EXPECTED": "w toku",
    "FAILURE": "czerwone",
    "ERROR": "czerwone",
}

_PR_FIELDS = (
    """
fragment P on PullRequest {
  number title url state isDraft mergedAt mergeable changedFiles
  mergeCommit { oid }
  autoMergeRequest { enabledAt }
  mergeQueueEntry { state position enqueuedAt }
  labels(first: 30) { nodes { name } }
  files(first: %d) { nodes { path } }
  commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
  timelineItems(last: 20, itemTypes: [ADDED_TO_MERGE_QUEUE_EVENT, REMOVED_FROM_MERGE_QUEUE_EVENT]) {
    nodes {
      __typename
      ... on AddedToMergeQueueEvent { createdAt }
      ... on RemovedFromMergeQueueEvent { createdAt reason }
    }
  }
}
"""
    % FILES_PAGE
)


class Api:
    """Wszystko, co skrypt czyta z zewnątrz. Testy podmieniają go nagraniem."""

    def graphql(self, op: str, query: str, variables: Dict[str, object]) -> dict:
        args = ["gh", "api", "graphql", "-f", f"query={query}"]
        for key, value in variables.items():
            args += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
        # Brak jednego z PR-ów to błąd GraphQL z kodem 1, ale reszta przychodzi w ``data``.
        result = subprocess.run(args, capture_output=True, text=True, timeout=60)
        try:
            payload = json.loads(result.stdout or "{}")
        except ValueError:
            payload = {}
        if result.returncode != 0 and not payload.get("data"):
            raise RuntimeError(f"gh api graphql: {result.stderr.strip()[:300]}")
        return payload

    def rest(self, path: str) -> object:
        return json.loads(_run(["gh", "api", path]))

    def raw(self, path: str) -> str:
        return _run(["gh", "api", path])

    def http(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": "gdzie-jest/1"})
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            return response.read().decode("utf-8", "replace")

    def fetch_main(self) -> None:
        subprocess.run(
            ["git", "-C", str(_REPO_DIR), "fetch", "-q", "origin", "main"],
            capture_output=True,
            timeout=60,
        )

    def is_ancestor(self, commit: str, descendant: str) -> Optional[bool]:
        """True/False z ``git merge-base``; None, gdy git nie zna któregoś SHA."""
        result = subprocess.run(
            [
                "git",
                "-C",
                str(_REPO_DIR),
                "merge-base",
                "--is-ancestor",
                commit,
                descendant,
            ],
            capture_output=True,
            timeout=30,
        )
        return {0: True, 1: False}.get(result.returncode)


def _run(args: List[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])}: {result.stderr.strip()[:300]}")
    return result.stdout


# ── czas ──────────────────────────────────────────────────────────────


def parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def window_open(now: datetime) -> bool:
    """Okno wdrożeń: pon–pt 18:00–08:00 czasu warszawskiego, weekend zawsze."""
    local = now.astimezone(WARSAW)
    if local.weekday() >= 5:
        return True
    return not (WINDOW_CLOSE_HOUR <= local.hour < WINDOW_OPEN_HOUR)


def when(moment: Optional[datetime], now: datetime) -> str:
    """„23:22” dziś, „25.11 23:22” innego dnia (czas warszawski)."""
    if moment is None:
        return "?"
    local, today = moment.astimezone(WARSAW), now.astimezone(WARSAW)
    if local.date() == today.date():
        return local.strftime("%H:%M")
    return local.strftime("%d.%m %H:%M")


# ── produkcja ─────────────────────────────────────────────────────────


class Production:
    """Wersje z produkcji, czytane raz na bieg."""

    def __init__(self, api: Api):
        self.api = api
        self._backend: Optional[str] = None
        self._front: Optional[str] = None
        self.health_error = ""
        self._read = False

    def _load(self) -> None:
        if self._read:
            return
        self._read = True
        try:
            version = str(json.loads(self.api.http(HEALTH_URL)).get("version") or "")
            self._backend = version if SHA_RE.match(version) else None
            self.health_error = "" if self._backend else "brak `version`"
        except Exception as error:  # noqa: BLE001 - np. 503 w trakcie wdrożenia
            self._backend = None
            self.health_error = str(error)[:80]
        try:
            match = SENTRY_RELEASE_RE.search(self.api.http(LOGIN_URL))
            self._front = match.group(1) if match else None
        except Exception:  # noqa: BLE001
            self._front = None

    @property
    def backend(self) -> Optional[str]:
        self._load()
        return self._backend

    @property
    def front(self) -> Optional[str]:
        self._load()
        return self._front


# ── stan PR-a ─────────────────────────────────────────────────────────


class Context:
    def __init__(self, api: Api, now: datetime):
        self.api = api
        self.now = now
        self.prod = Production(api)
        self.fetched = False
        self._deploy_runs: Optional[List[dict]] = None

    def deploy_runs(self) -> List[dict]:
        if self._deploy_runs is None:
            try:
                data = self.api.rest(
                    f"repos/{REPO}/actions/workflows/deploy.yml/runs?branch=main&per_page=20"
                )
                self._deploy_runs = list(data.get("workflow_runs") or [])  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                self._deploy_runs = []
        return self._deploy_runs


def _names(pr: dict, key: str, field: str) -> List[str]:
    return [node[field] for node in ((pr.get(key) or {}).get("nodes") or []) if node]


def pr_files(pr: dict) -> Optional[List[str]]:
    """Ścieżki PR-a albo None, gdy GraphQL dał tylko pierwszą stronę."""
    files = _names(pr, "files", "path")
    if (pr.get("changedFiles") or 0) > len(files):
        return None
    return files


def queue_events(pr: dict) -> List[dict]:
    return [
        node
        for node in ((pr.get("timelineItems") or {}).get("nodes") or [])
        if node
        and node.get("__typename")
        in ("AddedToMergeQueueEvent", "RemovedFromMergeQueueEvent")
    ]


def removals(pr: dict) -> List[dict]:
    return [
        event
        for event in queue_events(pr)
        if event["__typename"] == "RemovedFromMergeQueueEvent"
        and event.get("reason") != "merged"
    ]


def _title(pr: dict) -> str:
    title = " ".join(str(pr.get("title") or "").split())
    return title if len(title) <= TITLE_LIMIT else title[: TITLE_LIMIT - 1] + "…"


def _checks(pr: dict) -> str:
    nodes = (pr.get("commits") or {}).get("nodes") or []
    rollup = (
        ((nodes[-1] or {}).get("commit") or {}).get("statusCheckRollup")
        if nodes
        else None
    )
    state = (rollup or {}).get("state")
    return CHECK_STATES.get(state or "", "brak") if state else "brak"


def removal_detail(pr: dict, removed: dict, ctx: Context) -> str:
    """Dla ``failed_checks``: czerwony test albo job z biegu ``merge_group``."""
    removed_at = parse_time(removed.get("createdAt"))
    if removed_at is None:
        return ""
    since = (removed_at - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    until = (removed_at + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        data = ctx.api.rest(
            f"repos/{REPO}/actions/runs?event=merge_group&created={since}..{until}&per_page=100"
        )
    except Exception:  # noqa: BLE001
        return ""
    prefix = f"gh-readonly-queue/main/pr-{pr['number']}-"
    failed = [
        run
        for run in (data.get("workflow_runs") or [])  # type: ignore[union-attr]
        if str(run.get("head_branch") or "").startswith(prefix)
        and run.get("conclusion") in ("failure", "timed_out", "cancelled")
        and (parse_time(run.get("updated_at")) or removed_at)
        <= removed_at + timedelta(minutes=5)
    ]
    if not failed:
        return ""
    run = max(failed, key=lambda r: str(r.get("updated_at") or ""))
    url = run.get("html_url") or ""
    try:
        jobs = ctx.api.rest(
            f"repos/{REPO}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100"
        )
    except Exception:  # noqa: BLE001
        return f"bieg {url}"
    bad = [
        job for job in (jobs.get("jobs") or []) if job.get("conclusion") == "failure"
    ]  # type: ignore[union-attr]
    for job in bad[:MAX_LOGS_PER_PR]:
        try:
            log = ctx.api.raw(f"repos/{REPO}/actions/jobs/{job['id']}/logs")
        except Exception:  # noqa: BLE001
            continue
        failures = parse_failures(log)
        if failures:
            more = f" (+{len(failures) - 1})" if len(failures) > 1 else ""
            return f"{failures[0].test_id}{more}; bieg {url}"
        error = first_job_error(log)
        if error:
            return f"{job.get('name')}: {error}; bieg {url}"
    if bad:
        steps = [
            s.get("name")
            for s in (bad[0].get("steps") or [])
            if s.get("conclusion") == "failure"
        ]
        step = f" › {steps[0]}" if steps else ""
        return f"{bad[0].get('name')}{step}; bieg {url}"
    return f"{run.get('name')} {run.get('conclusion')}; bieg {url}"


def open_line(pr: dict, ctx: Context) -> str:
    labels = set(_names(pr, "labels", "name"))
    files = pr_files(pr)
    migration = files is None or any(
        path.startswith(MIGRATIONS_PREFIX) for path in files
    )
    removed = removals(pr)
    earlier = f"; wypadał {len(removed)}×" if removed else ""
    if pr.get("isDraft"):
        return "⏸ draft — do kolejki nie wejdzie"
    if HOLD_LABEL in labels:
        return f"⏸ wstrzymany (etykieta `{HOLD_LABEL}`)"
    entry = pr.get("mergeQueueEntry")
    if entry:
        lane = " (pas migracji)" if migration else ""
        state = QUEUE_STATES.get(entry.get("state") or "", entry.get("state") or "?")
        return (
            f"⏳ w kolejce{lane}, pozycja {entry.get('position')}, {state}, "
            f"od {when(parse_time(entry.get('enqueuedAt')), ctx.now)}{earlier}"
        )
    if MIGRATION_WAIT_LABEL in labels:
        return f"⏸ pas migracji — czeka na swoją kolej (etykieta `{MIGRATION_WAIT_LABEL}`){earlier}"
    events = queue_events(pr)
    if events and events[-1]["__typename"] == "RemovedFromMergeQueueEvent" and removed:
        last = removed[-1]
        reason = last.get("reason") or "?"
        text = REMOVAL_REASONS.get(reason, reason)
        detail = removal_detail(pr, last, ctx) if reason == "failed_checks" else ""
        armed = "; auto-merge znów włączony" if pr.get("autoMergeRequest") else ""
        count = f" ({len(removed)}×)" if len(removed) > 1 else ""
        return (
            f"✗ wypadł z kolejki {when(parse_time(last.get('createdAt')), ctx.now)}{count}: {text}"
            + (f" — {detail}" if detail else "")
            + armed
        )
    if pr.get("mergeable") == "CONFLICTING":
        return "✗ otwarty, konflikt z mainem — do kolejki nie wejdzie"
    checks = _checks(pr)
    lane = "; z migracją — do kolejki wprowadzi go pas migracji" if migration else ""
    if pr.get("autoMergeRequest"):
        return f"⏳ otwarty, auto-merge włączony — checki PR-a: {checks}{lane}{earlier}"
    return f"· otwarty, bez auto-merge — checki PR-a: {checks}{lane}{earlier}"


def _deploy_after(merged_at: datetime, ctx: Context) -> Optional[dict]:
    runs = [
        run
        for run in ctx.deploy_runs()
        if (parse_time(run.get("created_at")) or merged_at) >= merged_at
    ]
    running = [run for run in runs if run.get("status") != "completed"]
    if running:
        return running[0]
    done = sorted(runs, key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return done[0] if done else None


def _ancestor(commit: str, descendant: str, ctx: Context) -> Optional[bool]:
    """``git merge-base --is-ancestor``; raz ``git fetch`` na bieg, gdy SHA jest nieznany."""
    result = ctx.api.is_ancestor(commit, descendant)
    if result is None and not ctx.fetched:
        ctx.fetched = True
        ctx.api.fetch_main()
        result = ctx.api.is_ancestor(commit, descendant)
    return result


def _without_health(merge: str, merged_at: datetime, ctx: Context) -> str:
    """``/api/health`` nie odpowiada (np. 503 przy restarcie w trakcie wdrożenia).

    Front wdraża się z tego samego commitu co backend, więc jego ``sentry-release``
    mówi, która wersja była ostatnio wdrożona."""
    health = f"/api/health: {ctx.prod.health_error or 'brak odczytu'}"
    front = ctx.prod.front
    if front and _ancestor(merge, front, ctx):
        return f"✓ na produkcji wg frontu {front[:9]} ({health})"
    run = _deploy_after(merged_at, ctx)
    if run and run.get("status") != "completed":
        return f"⏳ scalony {when(merged_at, ctx.now)}, wdrożenie w toku ({health}) — {run.get('html_url')}"
    return f"? scalony {when(merged_at, ctx.now)}, nie umiem odczytać wersji produkcji ({health})"


def merged_line(pr: dict, ctx: Context) -> str:
    merge = ((pr.get("mergeCommit") or {}).get("oid")) or ""
    merged_at = parse_time(pr.get("mergedAt")) or ctx.now
    files = pr_files(pr)
    touches_front = files is None or any(path.startswith("frontend/") for path in files)
    backend = ctx.prod.backend
    if merge and not backend:
        return _without_health(merge, merged_at, ctx)
    if not merge:
        return (
            f"? scalony {when(merged_at, ctx.now)}, GitHub nie podał commitu scalenia"
        )
    on_backend = _ancestor(merge, backend, ctx)
    if on_backend is None:
        return f"? scalony {when(merged_at, ctx.now)}, git nie zna {merge[:9]} albo {backend[:9]} (git fetch?)"
    if on_backend:
        if not touches_front:
            return f"✓ na produkcji — backend {backend[:9]}"
        front = ctx.prod.front
        on_front = _ancestor(merge, front, ctx) if front else None
        if on_front:
            return f"✓ na produkcji — backend {backend[:9]}, front {front[:9]}"
        if on_front is False:
            return f"⏳ backend na produkcji ({backend[:9]}), front jeszcze nie (front {front[:9]})"
        return f"? backend na produkcji ({backend[:9]}), wersji frontu nie umiem odczytać ({LOGIN_URL})"
    if files is not None and files and all(is_inert(path) for path in files):
        return (
            f"✓ scalony {when(merged_at, ctx.now)}, same pliki poza obrazem — wdrożenie niepotrzebne "
            f"(produkcja {backend[:9]})"
        )
    run = _deploy_after(merged_at, ctx)
    if run and run.get("status") != "completed":
        return f"⏳ scalony {when(merged_at, ctx.now)}, wdrożenie w toku — {run.get('html_url')}"
    if run and run.get("conclusion") == "failure":
        return f"✗ scalony {when(merged_at, ctx.now)}, Deploy czerwony — {run.get('html_url')}"
    if window_open(ctx.now):
        return f"⏳ scalony {when(merged_at, ctx.now)}, okno otwarte — czeka na Deploy (produkcja {backend[:9]})"
    return f"⏳ scalony {when(merged_at, ctx.now)}, czeka na okno 18:00 (produkcja {backend[:9]})"


def describe(pr: dict, ctx: Context) -> str:
    state = pr.get("state")
    if state == "MERGED":
        status = merged_line(pr, ctx)
    elif state == "CLOSED":
        status = "· zamknięty bez scalenia"
    else:
        status = open_line(pr, ctx)
    return f"#{pr['number']} {status} · {_title(pr)}"


# ── pobranie PR-ów ────────────────────────────────────────────────────


def fetch_prs(api: Api, numbers: Sequence[int]) -> List[dict]:
    owner, name = REPO.split("/")
    params = ", ".join(f"$n{i}: Int!" for i in range(len(numbers)))
    body = " ".join(
        f"p{i}: pullRequest(number: $n{i}) {{ ...P }}" for i in range(len(numbers))
    )
    query = (
        f"query GdzieJestPR($owner: String!, $name: String!, {params}) "
        f"{{ repository(owner: $owner, name: $name) {{ {body} }} }}" + _PR_FIELDS
    )
    variables: Dict[str, object] = {"owner": owner, "name": name}
    variables.update({f"n{i}": number for i, number in enumerate(numbers)})
    repo = (api.graphql("GdzieJestPR", query, variables).get("data") or {}).get(
        "repository"
    ) or {}
    found = []
    for i, number in enumerate(numbers):
        pr = repo.get(f"p{i}")
        found.append(pr if pr else {"number": number, "state": "MISSING"})
    return found


def fetch_recent(api: Api, now: datetime, hours: float) -> List[dict]:
    since = (
        (now - timedelta(hours=hours))
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    query = (
        "query GdzieJestOstatnie($open: String!, $merged: String!) { "
        "open: search(query: $open, type: ISSUE, first: 100) { nodes { ...P } } "
        "merged: search(query: $merged, type: ISSUE, first: 100) { nodes { ...P } } }"
        + _PR_FIELDS
    )
    variables: Dict[str, object] = {
        "open": f"repo:{REPO} is:pr is:open updated:>={since}",
        "merged": f"repo:{REPO} is:pr is:merged merged:>={since}",
    }
    data = api.graphql("GdzieJestOstatnie", query, variables).get("data") or {}
    seen: Dict[int, dict] = {}
    for key in ("merged", "open"):
        for node in (data.get(key) or {}).get("nodes") or []:
            if node and node.get("number"):
                seen[node["number"]] = node
    return [seen[number] for number in sorted(seen)]


def report(api: Api, now: datetime, numbers: Sequence[int], hours: float) -> List[str]:
    prs = fetch_prs(api, numbers) if numbers else fetch_recent(api, now, hours)
    ctx = Context(api, now)
    lines = []
    for pr in prs:
        if pr.get("state") == "MISSING":
            lines.append(f"#{pr['number']} ? nie ma takiego PR-a w {REPO}")
        else:
            lines.append(describe(pr, ctx))
    return lines


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Jeden wiersz na PR NEXUSA: kolejka, okno, produkcja."
    )
    parser.add_argument(
        "prs",
        nargs="*",
        help="numery PR-ów (bez = otwarte i scalone w ostatnich --godziny)",
    )
    parser.add_argument(
        "--godziny",
        type=float,
        default=24.0,
        help="okno wyszukiwania bez numerów (domyślnie 24)",
    )
    args = parser.parse_args(argv)
    try:
        args.numbers = [int(str(p).lstrip("#")) for p in args.prs]
    except ValueError:
        parser.error("numer PR-a to liczba, np. 4035 albo #4035")
    return args


def main(
    argv: Optional[Sequence[str]] = None,
    api: Optional[Api] = None,
    now: Optional[datetime] = None,
    out: Callable[[str], None] = print,
) -> int:
    args = parse_args(argv)
    api = api or Api()
    now = now or datetime.now(timezone.utc)
    try:
        lines = report(api, now, args.numbers, args.godziny)
    except RuntimeError as error:
        print(f"gdzie_jest: {error}", file=sys.stderr)
        return 2
    if not lines:
        out(f"Brak PR-ów otwartych ani scalonych w ostatnich {args.godziny:g} h.")
    for line in lines:
        out(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
