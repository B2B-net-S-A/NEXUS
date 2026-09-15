#!/usr/bin/env python3
"""DEP-01 (audyt 14.09.2026): na produkcję wchodzi tylko commit z zieloną bramką.

Coolify (4.1.2 na produkcji) buduje HEAD maina z chwili budowy — także gdy
aplikacja ma przypięty ``git_commit_sha`` (``check_git_if_build_needed``
nadpisuje go wynikiem ``git ls-remote``; poprawione dopiero w 4.2.0). Do 09.2026
smoke przyjmował każdego POTOMKA commitu, który wyzwolił deploy, więc commit
N+1 z czerwoną albo trwającą bramką „CI Gate” wjeżdżał na produkcję w deployu
zielonego N i nic tego nie widziało.

Skoro nie da się wskazać Coolify commitu, pilnujemy obu końców budowy:

``select`` (przed triggerem)
    Deploy rusza tylko wtedy, gdy HEAD maina ma zieloną bramkę (``push`` na
    main, najnowsza próba). HEAD z bramką w toku = ``defer``: wdroży go jego
    własny przebieg Deploy, gdy bramka skończy się sukcesem. HEAD z czerwoną
    bramką = ``defer`` z ostrzeżeniem: main stoi, dopóki nie przyjdzie zielony
    commit. Ręczny ``workflow_dispatch`` przy niezielonym HEAD kończy się
    błędem — tego Coolify nie da się kazać zbudować starszego commitu.

``accept`` (po buildzie, w smoke)
    Wersja z produkcji jest przyjęta, gdy równa się wybranemu wydaniu, albo
    gdy jest jego POTOMKIEM (merge między wyborem a ``git ls-remote``) i jej
    własna bramka jest zielona — na bramkę w toku czekamy do ``--wait-seconds``.
    Potomek z czerwoną bramką to twardy błąd: taki kod już stoi na produkcji
    i trzeba go wycofać.

Kody wyjścia ``accept``: 0 przyjęte, 1 potomek bez zielonej bramki (błąd),
2 wersja nie jest wydaniem ani jego potomkiem (smoke ponawia — build jeszcze
nie wstał), 3 błąd API GitHuba (smoke ponawia). Wynik trafia do ``$GITHUB_OUTPUT`` / ``$GITHUB_ENV``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, NamedTuple, Optional

SHA_RE = re.compile(r"[0-9a-f]{40}")
GATE_WORKFLOW = "ci-gate.yml"
DEFAULT_MAX_COMMITS = 30
GREEN = "success"
PENDING = {"in_progress", "missing"}

Fetch = Callable[[str], object]


class Selection(NamedTuple):
    release_sha: str  # pusty, gdy deploy odroczony
    head_sha: str
    head_status: str
    defer: bool


def gate_status(fetch: Fetch, repo: str, sha: str, branch: str) -> str:
    """``success`` / ``failure`` / … / ``in_progress`` / ``missing`` dla commitu.

    Liczy się najnowsza próba, wyłącznie ``push`` na gałąź — przebiegi z PR
    mają inny SHA niż squash commit na main.
    """
    query = urllib.parse.urlencode(
        {"head_sha": sha, "branch": branch, "event": "push", "per_page": 5}
    )
    body = fetch(f"repos/{repo}/actions/workflows/{GATE_WORKFLOW}/runs?{query}")
    runs = body.get("workflow_runs", []) if isinstance(body, dict) else []
    runs = [r for r in runs if r.get("head_sha") == sha]
    if not runs:
        return "missing"
    newest = max(
        runs, key=lambda r: (r.get("created_at") or "", r.get("run_attempt") or 0)
    )
    if newest.get("status") != "completed":
        return "in_progress"
    return str(newest.get("conclusion") or "unknown")


def head_commit(fetch: Fetch, repo: str, branch: str) -> str:
    body = fetch(f"repos/{repo}/commits/{urllib.parse.quote(branch)}")
    sha = body.get("sha", "") if isinstance(body, dict) else ""
    if not SHA_RE.fullmatch(sha):
        raise ValueError("unexpected commit payload")
    return sha


def relation(fetch: Fetch, repo: str, base: str, head: str) -> str:
    """Status GitHub compare ``base...head``: ``ahead`` = head jest potomkiem."""
    body = fetch(f"repos/{repo}/compare/{base}...{head}")
    return str(body.get("status", "unknown")) if isinstance(body, dict) else "unknown"


def select_release(
    head: str, target: str, status_of: Callable[[str], str], *, target_is_verified: bool
) -> Selection:
    """HEAD maina z zieloną bramką albo odroczenie."""
    if not SHA_RE.fullmatch(head) or not SHA_RE.fullmatch(target):
        raise ValueError("HEAD and TARGET_SHA must be full 40-character SHAs")
    if head == target and target_is_verified:
        status = GREEN
    else:
        status = status_of(head)
    if status == GREEN:
        return Selection(head, head, status, False)
    return Selection("", head, status, True)


class Acceptance(NamedTuple):
    code: int  # 0 przyjęte, 1 potomek bez zielonej bramki, 2 nie wydanie/potomek
    status: str
    relation: str


def accept_live(
    live: str,
    release: str,
    relation_of: Callable[[str, str], str],
    status_of: Callable[[str], str],
    *,
    wait_seconds: float,
    poll_seconds: float = 20.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Acceptance:
    if live == release:
        return Acceptance(0, GREEN, "identical")
    if not SHA_RE.fullmatch(live):
        return Acceptance(2, "n/a", "unreadable")
    rel = relation_of(release, live)
    if rel != "ahead":
        return Acceptance(2, "n/a", rel)
    deadline = clock() + wait_seconds
    status = status_of(live)
    while status in PENDING and clock() < deadline:
        sleep(poll_seconds)
        status = status_of(live)
    if status == GREEN:
        return Acceptance(0, status, rel)
    return Acceptance(1, status, rel)


def _github_fetch(api_url: str, token: str, attempts: int = 4) -> Fetch:
    def fetch(path: str) -> object:
        req = urllib.request.Request(
            f"{api_url.rstrip('/')}/{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    return json.loads(response.read() or b"null")
            except urllib.error.HTTPError as error:
                # 4xx nie zmieni się po ponowieniu; 5xx/429 bywa chwilowe.
                if error.code < 500 and error.code != 429 or attempt == attempts - 1:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == attempts - 1:
                    raise
            time.sleep(2 ** (attempt + 1))
        raise RuntimeError("unreachable")

    return fetch


def _append(path: Optional[str], lines: list[str]) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("".join(f"{line}\n" for line in lines))


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    select = sub.add_parser("select")
    select.add_argument("--repo", required=True)
    select.add_argument("--branch", default="main")
    select.add_argument("--target", required=True)
    select.add_argument(
        "--target-unverified",
        action="store_true",
        help="workflow_dispatch: target nie przeszedł bramki w tym wyzwoleniu",
    )
    accept = sub.add_parser("accept")
    accept.add_argument("--repo", required=True)
    accept.add_argument("--branch", default="main")
    accept.add_argument("--release", required=True)
    accept.add_argument("--live", required=True)
    accept.add_argument("--wait-seconds", type=float, default=600.0)
    return parser.parse_args(argv)


def _run_select(args: argparse.Namespace, fetch: Fetch) -> int:
    head = head_commit(fetch, args.repo, args.branch)
    selection = select_release(
        head,
        args.target,
        lambda sha: gate_status(fetch, args.repo, sha, args.branch),
        target_is_verified=not args.target_unverified,
    )
    _append(
        os.environ.get("GITHUB_OUTPUT"),
        [
            f"release_sha={selection.release_sha}",
            f"head_sha={selection.head_sha}",
            f"head_status={selection.head_status}",
            f"defer={'true' if selection.defer else 'false'}",
        ],
    )
    if not selection.defer:
        note = "" if head == args.target else f" (zawiera target {args.target[:7]})"
        print(f"Wydanie = HEAD maina {head[:7]} z zieloną bramką CI Gate{note}")
        return 0
    if args.target_unverified:
        print(
            f"::error::HEAD maina {head[:7]} ma bramkę CI Gate = {selection.head_status}. "
            "Coolify buduje zawsze HEAD, więc ręczny deploy starszego commitu nie jest "
            "możliwy — poczekaj na zieloną bramkę albo użyj Redeploy w panelu Coolify.",
            file=sys.stderr,
        )
        return 1
    if selection.head_status in PENDING:
        print(
            f"::notice::Deploy odroczony: HEAD maina {head[:7]} ma bramkę w toku — "
            "wdroży go jego własny przebieg Deploy."
        )
    else:
        print(
            f"::warning::Deploy wstrzymany: HEAD maina {head[:7]} ma bramkę CI Gate = "
            f"{selection.head_status}. Coolify zbudowałoby ten commit, więc produkcja "
            "zostaje na obecnej wersji do następnego zielonego commitu."
        )
    return 0


def _run_accept(args: argparse.Namespace, fetch: Fetch) -> int:
    result = accept_live(
        args.live,
        args.release,
        lambda base, head: relation(fetch, args.repo, base, head),
        lambda sha: gate_status(fetch, args.repo, sha, args.branch),
        wait_seconds=args.wait_seconds,
    )
    if result.code == 0:
        _append(os.environ.get("GITHUB_ENV"), [f"ACCEPTED_SHA={args.live}"])
        if args.live == args.release:
            print(f"Produkcja serwuje wydanie {args.live[:7]}")
        else:
            print(
                f"Produkcja serwuje {args.live[:7]} — potomek wydania {args.release[:7]} "
                "z zieloną bramką CI Gate (merge w trakcie budowy)."
            )
    elif result.code == 1:
        print(
            f"::error::Na produkcji stoi {args.live[:7]} (potomek wydania "
            f"{args.release[:7]}) z bramką CI Gate = {result.status}. Coolify zbudowało "
            "commit bez zielonej bramki — wycofaj go (Coolify → Deployments → Redeploy "
            "poprzedniego) albo napraw main.",
            file=sys.stderr,
        )
    return result.code


def main(argv: Optional[list[str]] = None, fetch: Optional[Fetch] = None) -> int:
    args = parse_args(argv)
    if fetch is None:
        token = os.environ.get("GH_TOKEN", "")
        if not token:
            print("::error::GH_TOKEN nie jest ustawiony", file=sys.stderr)
            return 1
        fetch = _github_fetch(
            os.environ.get("GITHUB_API_URL", "https://api.github.com"), token
        )
    # Błąd API w `accept` to 3, nie 1: smoke ma ponowić, a nie ogłosić, że na
    # produkcji stoi commit z czerwoną bramką.
    failure_code = 1 if args.mode == "select" else 3
    try:
        if args.mode == "select":
            return _run_select(args, fetch)
        return _run_accept(args, fetch)
    except urllib.error.HTTPError as error:
        print(f"::warning::GitHub API HTTP {error.code} ({args.mode})", file=sys.stderr)
        return failure_code
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        print(
            f"::warning::Weryfikacja wydania nie powiodła się ({type(error).__name__})",
            file=sys.stderr,
        )
        return failure_code


if __name__ == "__main__":
    sys.exit(main())
