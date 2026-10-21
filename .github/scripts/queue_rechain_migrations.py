#!/usr/bin/env python3
"""Przepina migracje otwartych PR-ów na nową głowę maina — bez sesji.

Po co: równoległe sesje dokładają migracje z ``down_revision`` = czubek
maina z chwili otwarcia PR-a. Gdy dwie podepną się w to samo miejsce, druga
po scaleniu pierwszej ma dwie głowy Alembica i wypada z kolejki merge'ów.
21.10.2026 #2520 wypadł tak 6 razy w jeden dzień, a każda naprawa to była
ręczna zmiana nazwy pliku, ``revision``/``down_revision`` i numeru w ~8
miejscach (lustro w entrypoint, testy, komentarze, docs, indeks CLAUDE.md).

Workflow ``migration-rechain.yml`` uruchamia ten skrypt po każdym pushu na
main, który zmienia ``backend/alembic/versions``. Dla każdego otwartego PR-a
z migracją (bez draftów, ``wstrzymaj`` i forków):

1. checkout gałęzi PR-a (bez scalania maina — skrypt przepinający liczy linie
   PR-a od merge-base, a scalenie maina z plikami workflowów odrzuciłby push
   tokenem bez uprawnienia „Workflows”);
2. ``rechain_migration.py --base origin/main`` w kopii z MAINA (kodu z gałęzi
   PR-a z tokenem w ręku nie wykonujemy);
3. brak zmian = PR już stoi na głowie, nic nie robimy; zmiany = commit
   i zwykły push (bez force — gdy sesja wypchnęła coś w międzyczasie, push
   odpada, a następny push na main spróbuje znowu);
4. komentarz na PR-ze (znacznik ``<!-- migration-rechain -->``) z planem
   przepięcia albo z błędem i komendą do ręcznego przepięcia.

Push nowym commitem zdejmuje PR z kolejki, sito biegnie na nowo, a
``auto-enqueue`` wrzuca go z powrotem. Sesja z lokalną kopią gałęzi musi
przed kolejnym pushem zrobić ``git pull`` — mówi o tym komentarz.

Stdlib + ``gh`` i ``git`` (``GH_TOKEN``). ``--dry-run`` liczy plan, ale nic
nie commituje, nie pushuje i nie komentuje.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

MARKER = "<!-- migration-rechain -->"
VERSIONS_PREFIX = "backend/alembic/versions/"
HOLD_LABEL = "wstrzymaj"
BOT_NAME = "nexus-migration-rechain"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
MANUAL = (
    "`git fetch origin && python3 backend/scripts/rechain_migration.py --dry-run`, "
    "potem bez `--dry-run`, przejrzyj `git diff`, commit i push"
)


@dataclass(frozen=True)
class Candidate:
    number: int
    branch: str


@dataclass(frozen=True)
class Outcome:
    pr: int
    state: str  # noop | pushed | planned | error | push_failed
    log: str


Runner = Callable[..., subprocess.CompletedProcess]


def pick_candidates(prs: list[dict]) -> list[Candidate]:
    """Otwarte PR-y z plikiem migracji; drafty, ``wstrzymaj`` i forki pomijamy."""
    picked = []
    for pr in prs:
        if pr.get("isDraft") or pr.get("isCrossRepository"):
            continue
        if any(label.get("name") == HOLD_LABEL for label in pr.get("labels") or []):
            continue
        paths = [f.get("path", "") for f in pr.get("files") or []]
        if not any(p.startswith(VERSIONS_PREFIX) and p.endswith(".py") for p in paths):
            continue
        picked.append(Candidate(number=int(pr["number"]), branch=pr["headRefName"]))
    return sorted(picked, key=lambda c: c.number)


def _run(runner: Runner, cwd: str, *args: str) -> subprocess.CompletedProcess:
    return runner(list(args), cwd=cwd, capture_output=True, text=True, check=False)


def _git(runner: Runner, cwd: str, *args: str) -> str:
    proc = _run(runner, cwd, "git", *args)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: {proc.stderr.strip()[:400]}")
    return proc.stdout


def rechain_branch(
    repo: str,
    candidate: Candidate,
    script: str,
    base: str = "origin/main",
    dry_run: bool = False,
    runner: Runner = subprocess.run,
) -> Outcome:
    pr, branch = candidate.number, candidate.branch
    remote_ref = f"refs/remotes/origin/{branch}"
    try:
        _git(
            runner, repo, "fetch", "-q", "origin", f"+refs/heads/{branch}:{remote_ref}"
        )
        _git(runner, repo, "checkout", "-q", "-f", "-B", "rechain-work", remote_ref)
    except RuntimeError as exc:
        return Outcome(pr, "error", f"Nie udało się pobrać gałęzi `{branch}`: {exc}")

    args = ["python3", script, "--base", base]
    if dry_run:
        args.append("--dry-run")
    proc = _run(runner, repo, *args)
    log = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        return Outcome(pr, "error", log)
    if dry_run:
        state = "noop" if "nic do zrobienia" in log else "planned"
        return Outcome(pr, state, log)
    if not _git(runner, repo, "status", "--porcelain").strip():
        return Outcome(pr, "noop", log)

    head = _git(runner, repo, "rev-parse", "--short", base).strip()
    message = (
        f"fix(migracje): przepięcie migracji PR-a na głowę maina ({head})\n\n"
        "Automat migration-rechain.yml po pushu na main "
        "(backend/scripts/rechain_migration.py)."
    )
    _git(
        runner,
        repo,
        "-c",
        f"user.name={BOT_NAME}",
        "-c",
        f"user.email={BOT_EMAIL}",
        "commit",
        "-q",
        "-a",
        f"--author={BOT_NAME} <{BOT_EMAIL}>",
        "-m",
        message,
    )
    push = _run(
        runner, repo, "git", "push", "-q", "origin", f"HEAD:refs/heads/{branch}"
    )
    if push.returncode != 0:
        return Outcome(pr, "push_failed", f"{log}\n\n{push.stderr.strip()[:400]}")
    return Outcome(pr, "pushed", log)


def build_comment(outcome: Outcome, main_sha: str) -> str:
    log = f"```\n{outcome.log[-3000:]}\n```" if outcome.log else ""
    if outcome.state == "pushed":
        head = (
            f"{MARKER}\n**Migracje przepięte na głowę maina ({main_sha[:9]})** — "
            "automat `migration-rechain.yml` wypchnął commit na tę gałąź."
        )
        tail = (
            "Sesja z lokalną kopią gałęzi: przed kolejnym pushem `git pull` "
            "(inaczej push zostanie odrzucony). Sito i kolejka ruszą same."
        )
    elif outcome.state == "push_failed":
        head = (
            f"{MARKER}\n**Migracje wymagają przepięcia na głowę maina "
            f"({main_sha[:9]}), ale push automatu się nie udał** — gałąź zmieniła się "
            "w międzyczasie albo commit dotyka pliku workflowu."
        )
        tail = f"Ręcznie na gałęzi PR-a: {MANUAL}."
    else:
        head = (
            f"{MARKER}\n**Automat nie przepiął migracji tego PR-a na głowę maina "
            f"({main_sha[:9]})**."
        )
        tail = f"Ręcznie na gałęzi PR-a: {MANUAL}."
    return "\n\n".join(part for part in (head, log, tail) if part)


# ── GitHub (gh) ───────────────────────────────────────────────────────────


def gh(*args: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        ["gh", *args], input=stdin, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {result.stderr.strip()[:500]}")
    return result.stdout


def list_open_prs(repo: str) -> list[dict]:
    raw = gh(
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--base",
        "main",
        "--limit",
        "200",
        "--json",
        "number,headRefName,isDraft,isCrossRepository,labels,files",
    )
    return json.loads(raw)


def upsert_comment(repo: str, pr: int, body: str) -> str:
    raw = gh(
        "api",
        "--paginate",
        f"repos/{repo}/issues/{pr}/comments?per_page=100",
        "--jq",
        '.[] | select(.body | contains("' + MARKER + '")) | .id',
    )
    existing = raw.split()
    payload = json.dumps({"body": body})
    if existing:
        gh(
            "api",
            "-X",
            "PATCH",
            f"repos/{repo}/issues/comments/{existing[0]}",
            "--input",
            "-",
            stdin=payload,
        )
        return f"zaktualizowany komentarz {existing[0]}"
    gh(
        "api",
        "-X",
        "POST",
        f"repos/{repo}/issues/{pr}/comments",
        "--input",
        "-",
        stdin=payload,
    )
    return "nowy komentarz"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument(
        "--workdir", default=".", help="checkout repo (z remote origin)"
    )
    parser.add_argument(
        "--script", required=True, help="kopia rechain_migration.py z maina"
    )
    parser.add_argument("--pr", type=int, help="tylko ten PR")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    _git(
        subprocess.run,
        args.workdir,
        "fetch",
        "-q",
        "origin",
        "+refs/heads/main:refs/remotes/origin/main",
    )
    main_sha = _git(subprocess.run, args.workdir, "rev-parse", "origin/main").strip()
    candidates = pick_candidates(list_open_prs(args.repo))
    if args.pr is not None:
        candidates = [c for c in candidates if c.number == args.pr]
    print(
        f"Main: {main_sha[:9]}; PR-y z migracją: {', '.join(f'#{c.number}' for c in candidates) or 'brak'}"
    )

    for candidate in candidates:
        outcome = rechain_branch(
            args.workdir, candidate, args.script, dry_run=args.dry_run
        )
        print(f"\n#{outcome.pr} ({candidate.branch}): {outcome.state}\n{outcome.log}")
        if outcome.state in ("noop", "planned"):
            continue
        body = build_comment(outcome, main_sha)
        if args.dry_run:
            print(f"--- komentarz #{outcome.pr} ---\n{body}")
            continue
        try:
            print(f"#{outcome.pr}: {upsert_comment(args.repo, outcome.pr, body)}")
        except RuntimeError as exc:
            print(f"::warning::#{outcome.pr}: komentarz się nie udał: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
