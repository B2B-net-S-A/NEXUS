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

Łańcuch (02.11.2026): PR-y z pasa i następny zielony czekający stają jeden na
drugim (``--stack-on``, kolejność z ``queue_migration_lane.stack_order``), reszta
na głowie maina. PR-ów już w kolejce nie przepinamy: push odbiłby się od GH006,
a poprawny stoi tam, gdzie trzeba; zły wypadnie sam po „Jedna głowa Alembica”.

Stdlib + ``gh`` i ``git`` (``GH_TOKEN``). ``--dry-run`` liczy plan, ale nic
nie commituje, nie pushuje i nie komentuje.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Iterator

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import queue_migration_lane as lane  # noqa: E402

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


@dataclass(frozen=True)
class Step:
    number: int
    stackable: bool = False  # staje na poprzednim, póki w pasie jest miejsce
    queued: bool = False  # w kolejce: bez pushu, ale następny stoi na nim


def plan_steps(candidates: list[Candidate], prs: list[lane.Pr]) -> list[Step]:
    """Najpierw pas i zieloni czekający w kolejności pasa, reszta na głowę maina."""
    known = {c.number for c in candidates}
    queued = {p.number for p in prs if p.queue_position is not None}
    order = [n for n in lane.stack_order(prs) if n in known]
    rest = [c.number for c in candidates if c.number not in order]
    return [
        *(Step(n, stackable=True, queued=n in queued) for n in order),
        *(Step(n) for n in rest),
    ]


def run_steps(
    steps: list[Step],
    by_number: dict[int, Candidate],
    rechain: Callable[[Candidate, str | None], Outcome],
) -> Iterator[tuple[Candidate, Outcome, int | None]]:
    """Przepina po kolei; każdy z pasa staje na poprzednim, póki jest miejsce.

    PR, którego nie udało się przepiąć, nie zajmuje miejsca: następny stanie
    tam, gdzie miał stać on, a nie na migracji, która się nie ruszyła.
    """
    stack: list[int] = []
    for step in steps:
        if step.queued:
            stack.append(step.number)
            continue
        candidate = by_number[step.number]
        room = step.stackable and len(stack) < lane.LANE_DEPTH
        ahead = stack[-1] if room and stack else None
        outcome = rechain(candidate, by_number[ahead].branch if ahead else None)
        if room and outcome.state in ("noop", "planned", "pushed"):
            stack.append(step.number)
        yield candidate, outcome, ahead


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
    stack_on: str | None = None,
) -> Outcome:
    pr, branch = candidate.number, candidate.branch
    remote_ref = f"refs/remotes/origin/{branch}"
    try:
        _git(
            runner, repo, "fetch", "-q", "origin", f"+refs/heads/{branch}:{remote_ref}"
        )
        if stack_on:
            _git(
                runner,
                repo,
                "fetch",
                "-q",
                "origin",
                f"+refs/heads/{stack_on}:refs/remotes/origin/{stack_on}",
            )
        _git(runner, repo, "checkout", "-q", "-f", "-B", "rechain-work", remote_ref)
    except RuntimeError as exc:
        return Outcome(pr, "error", f"Nie udało się pobrać gałęzi `{branch}`: {exc}")

    args = ["python3", script, "--base", base]
    if stack_on:
        args += ["--stack-on", f"origin/{stack_on}"]
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
    target = f"migrację z `{stack_on}`" if stack_on else "głowę maina"
    message = (
        f"fix(migracje): przepięcie migracji PR-a na {target} ({head})\n\n"
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


def build_comment(outcome: Outcome, main_sha: str, ahead: int | None = None) -> str:
    log = f"```\n{outcome.log[-3000:]}\n```" if outcome.log else ""
    if outcome.state == "pushed" and ahead is not None:
        head = (
            f"{MARKER}\n**Migracja stoi na migracji #{ahead}** — pas migracji daje temu "
            "PR-owi miejsce zaraz za nim w kolejce, automat `migration-rechain.yml` "
            "wypchnął commit na tę gałąź."
        )
        tail = (
            "Sesja z lokalną kopią gałęzi: przed kolejnym pushem `git pull`. Rodzica nie "
            "ma na tej gałęzi; lokalne `alembic upgrade` zadziała po "
            "`python3 backend/scripts/rechain_migration.py --stub-missing-parent` "
            "(pliku zaślepki nie commituj). Gdy #"
            f"{ahead} wypadnie z kolejki, automat przepnie ten PR na głowę maina."
        )
    elif outcome.state == "pushed":
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


def lane_gh(*args: str, stdin: str | None = None) -> str:
    """Stan pasa tokenem pasa (``LANE_GH_TOKEN``); komentarze zostają na ``GH_TOKEN``."""
    env = {**os.environ}
    if os.environ.get("LANE_GH_TOKEN"):
        env["GH_TOKEN"] = os.environ["LANE_GH_TOKEN"]
    result = subprocess.run(
        ["gh", *args], input=stdin, capture_output=True, text=True, check=False, env=env
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {result.stderr.strip()[:500]}")
    return result.stdout


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

    if args.pr is None:
        try:
            lane_prs = lane.fetch_prs(args.repo, lane_gh)
        except (KeyError, ValueError, RuntimeError) as exc:
            print(f"::warning::Stan pasa niedostępny, wszyscy na głowę maina: {exc}")
            lane_prs = []
    else:
        lane_prs = []
    steps = plan_steps(candidates, lane_prs)

    def rechain(candidate: Candidate, stack_on: str | None) -> Outcome:
        return rechain_branch(
            args.workdir,
            candidate,
            args.script,
            dry_run=args.dry_run,
            stack_on=stack_on,
        )

    by_number = {c.number: c for c in candidates}
    for candidate, outcome, ahead in run_steps(steps, by_number, rechain):
        print(f"\n#{outcome.pr} ({candidate.branch}): {outcome.state}\n{outcome.log}")
        if outcome.state in ("noop", "planned"):
            continue
        body = build_comment(outcome, main_sha, ahead)
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
