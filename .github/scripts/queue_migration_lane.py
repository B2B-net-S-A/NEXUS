#!/usr/bin/env python3
"""Pas migracji: w kolejce merge'ów najwyżej jeden PR z migracją Alembica.

Po co (29.10.2026): kolejka buduje grupy jedna na drugiej (grupa 2 = main +
PR1 + PR2). Dwa PR-y z migracją przepiętą na tę samą głowę maina dają w grupie
dwie głowy, krok „Jedna głowa Alembica” czerwieni ją po ~1 min, a razem z nią
każdą grupę za nią — także PR-y bez migracji. Od 25 do 28.10 wszystkie 54
czerwone bramki kolejki miały ten powód; 28.10 było naraz 9 PR-ów z 0616.
``migration-rechain.yml`` przepina wszystkich na tę samą nową głowę, więc
w następnej rundzie znowu przechodził tylko pierwszy.

Reguła: aktywny jest jeden PR z migracją (w kolejce albo z włączonym
auto-merge'em i zielonymi checkami). Reszta dostaje etykietę
``czeka-na-migracje`` i wyłączony auto-merge; ``auto-enqueue`` ich nie
wrzuca. Gdy aktywnego nie ma (scalił się, wypadł, ma czerwone checki),
najstarszy czekający dostaje swoją kolej: etykieta zdjęta, auto-merge
włączony. Kolejność migracji między sobą nie ma znaczenia —
``migration-rechain.yml`` po każdym scaleniu przepina czekających na nową
głowę maina.

Komendy:

* ``admit --pr N`` — z ``auto-enqueue.yml`` przed ``gh pr merge --auto``.
  Kod 0 = wpuść, ``WAIT_EXIT`` = PR zaparkowany (etykieta, komentarz).
* ``enforce`` — z ``queue-migration-lane.yml`` (po bramce i CI grup
  w kolejce) i z ``migration-rechain.yml`` (przed przepięciem): zdejmuje
  z kolejki nadmiarowe PR-y z migracją, parkuje uzbrojone, daje kolej
  następnemu.

Stdlib + ``gh`` (``GH_TOKEN`` = ``QUEUE_BOT_TOKEN``: etykieta zdjęta tokenem
Actions nie uruchomiłaby ``auto-enqueue``). ``--dry-run`` tylko wypisuje.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

VERSIONS_PREFIX = "backend/alembic/versions/"
WAIT_LABEL = "czeka-na-migracje"
HOLD_LABEL = "wstrzymaj"
MARKER = "<!-- migration-lane -->"
WAIT_EXIT = 10
UNHEALTHY_CHECKS = {"FAILURE", "ERROR"}

PRS_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, baseRefName: "main", first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id number isDraft isCrossRepository mergeable
        labels(first: 30) { nodes { name } }
        autoMergeRequest { enabledAt }
        mergeQueueEntry { position }
        files(first: 100) { nodes { path } }
        commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class Pr:
    number: int
    node_id: str
    queue_position: int | None
    armed: bool
    waiting: bool
    healthy: bool


@dataclass(frozen=True)
class Plan:
    active: int | None
    dequeue: tuple[int, ...] = ()
    park: tuple[int, ...] = ()
    promote: int | None = None
    unlabel: int | None = None


def parse_prs(nodes: list[dict]) -> list[Pr]:
    """PR-y z plikiem migracji; drafty, ``wstrzymaj`` i forki nie biorą udziału."""
    prs = []
    for node in nodes:
        if node.get("isDraft") or node.get("isCrossRepository"):
            continue
        labels = {lab["name"] for lab in (node.get("labels") or {}).get("nodes", [])}
        if HOLD_LABEL in labels:
            continue
        paths = [f["path"] for f in (node.get("files") or {}).get("nodes", [])]
        if not any(p.startswith(VERSIONS_PREFIX) and p.endswith(".py") for p in paths):
            continue
        commits = (node.get("commits") or {}).get("nodes") or [{}]
        rollup = (commits[-1].get("commit") or {}).get("statusCheckRollup") or {}
        entry = node.get("mergeQueueEntry")
        prs.append(
            Pr(
                number=int(node["number"]),
                node_id=node["id"],
                queue_position=entry["position"] if entry else None,
                armed=node.get("autoMergeRequest") is not None,
                waiting=WAIT_LABEL in labels,
                healthy=rollup.get("state") not in UNHEALTHY_CHECKS
                and node.get("mergeable") != "CONFLICTING",
            )
        )
    return sorted(prs, key=lambda p: p.number)


def plan_lane(prs: list[Pr]) -> Plan:
    """Kto zostaje aktywny, kogo zdjąć z kolejki, zaparkować, komu dać kolej.

    Aktywny = pierwszy PR z migracją w kolejce; bez takiego — najstarszy
    uzbrojony ze zdrowymi checkami. Uzbrojony z czerwonymi checkami nie blokuje
    pasa: do kolejki i tak nie wejdzie, a gdy wejdzie po poprawce, kolejne
    ``enforce`` zostawi tylko jednego.
    """
    queued = sorted(
        (p for p in prs if p.queue_position is not None),
        key=lambda p: p.queue_position,
    )
    ready = [p for p in prs if p.queue_position is None and p.armed and p.healthy]
    if queued:
        active, dequeue, park = queued[0], queued[1:], queued[1:] + ready
    elif ready:
        active, dequeue, park = ready[0], [], ready[1:]
    else:
        waiting = sorted(
            (p for p in prs if p.waiting), key=lambda p: (not p.healthy, p.number)
        )
        promote = waiting[0].number if waiting else None
        return Plan(active=None, promote=promote)
    return Plan(
        active=active.number,
        dequeue=tuple(p.number for p in dequeue),
        park=tuple(p.number for p in park),
        unlabel=active.number if active.waiting else None,
    )


def admit(prs: list[Pr], number: int) -> int | None:
    """Numer PR-a, który zajmuje pas, albo ``None`` = ``number`` może wejść."""
    if not any(p.number == number for p in prs):
        return None
    return plan_lane([p for p in prs if p.number != number]).active


def park_comment(active: int) -> str:
    return (
        f"{MARKER}\n**Czeka w pasie migracji.** W kolejce merge'ów jest naraz "
        f"najwyżej jeden PR z migracją Alembica, a teraz jest nim #{active}: dwa "
        "takie PR-y w jednej grupie dają dwie głowy i wywracają też PR-y za nimi.\n\n"
        f"Nic nie trzeba robić. Gdy #{active} się scali, `migration-rechain.yml` "
        f"przepnie migrację tego PR-a na nową głowę maina, etykieta `{WAIT_LABEL}` "
        "zejdzie, a PR wejdzie do kolejki sam. Ręczne `gh pr merge --auto` nic nie "
        "przyspieszy: automat zdejmie PR z kolejki z powrotem."
    )


def promote_comment() -> str:
    return (
        f"{MARKER}\n**Kolej tego PR-a w pasie migracji** — etykieta `{WAIT_LABEL}` "
        "zdjęta, auto-merge włączony. PR wejdzie do kolejki po zielonych checkach."
    )


# ── GitHub (gh) ───────────────────────────────────────────────────────────

Gh = Callable[..., str]


def gh(*args: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        ["gh", *args], input=stdin, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {result.stderr.strip()[:500]}")
    return result.stdout


def fetch_prs(repo: str, run: Gh = gh) -> list[Pr]:
    owner, name = repo.split("/", 1)
    nodes: list[dict] = []
    cursor = None
    while True:
        args = ["api", "graphql", "-f", f"query={PRS_QUERY}"]
        args += ["-F", f"owner={owner}", "-F", f"name={name}"]
        if cursor:
            args += ["-F", f"cursor={cursor}"]
        page = json.loads(run(*args))["data"]["repository"]["pullRequests"]
        nodes += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return parse_prs(nodes)
        cursor = page["pageInfo"]["endCursor"]


def upsert_comment(repo: str, pr: int, body: str, run: Gh = gh) -> None:
    raw = run(
        "api",
        "--paginate",
        f"repos/{repo}/issues/{pr}/comments?per_page=100",
        "--jq",
        '.[] | select(.body | contains("' + MARKER + '")) | .id',
    )
    payload = json.dumps({"body": body})
    existing = raw.split()
    if existing:
        path = f"repos/{repo}/issues/comments/{existing[0]}"
        run("api", "-X", "PATCH", path, "--input", "-", stdin=payload)
    else:
        path = f"repos/{repo}/issues/{pr}/comments"
        run("api", "-X", "POST", path, "--input", "-", stdin=payload)


class Actions:
    """Wykonanie planu. Każdy krok osobno: błąd jednego PR-a nie zatrzymuje reszty."""

    def __init__(self, repo: str, prs: list[Pr], dry_run: bool, run: Gh = gh):
        self.repo, self.dry_run, self.run = repo, dry_run, run
        self.by_number = {p.number: p for p in prs}
        self.label_ready = False

    def _do(self, what: str, *args: str, stdin: str | None = None) -> bool:
        if self.dry_run:
            print(f"[dry-run] {what}")
            return True
        try:
            self.run(*args, stdin=stdin)
            print(what)
            return True
        except RuntimeError as exc:
            print(f"::warning::{what} — nie wyszło: {exc}")
            return False

    def _ensure_label(self) -> None:
        if self.label_ready or self.dry_run:
            return
        self.label_ready = True
        self._do(
            f"etykieta `{WAIT_LABEL}` w repo",
            "label",
            "create",
            WAIT_LABEL,
            "--repo",
            self.repo,
            "--force",
            "--color",
            "c5def5",
            "--description",
            "PR z migracją czeka, aż pas migracji w kolejce się zwolni",
        )

    def park(self, number: int, active: int, dequeue: bool) -> None:
        pr = self.by_number[number]
        if dequeue:
            self._do(
                f"#{number}: zdjęty z kolejki (pas zajmuje #{active})",
                "api",
                "graphql",
                "-f",
                "query=mutation($id: ID!) { dequeuePullRequest(input: {id: $id}) { mergeQueueEntry { id } } }",
                "-f",
                f"id={pr.node_id}",
            )
        if pr.armed:
            self._do(
                f"#{number}: auto-merge wyłączony",
                "pr",
                "merge",
                str(number),
                "--repo",
                self.repo,
                "--disable-auto",
            )
        self._comment(number, park_comment(active))
        # Etykieta na końcu: jej zdarzenie `labeled` anuluje bieg auto-enqueue
        # tego PR-a, a więc i `admit`, który mógł nas tu wywołać.
        # REST zamiast `gh pr edit`: ten pyta też o projekty, a PAT bez
        # uprawnień do projektów kończy się wtedy błędem GraphQL.
        if not pr.waiting:
            self._ensure_label()
            self._do(
                f"#{number}: etykieta `{WAIT_LABEL}`",
                "api",
                "-X",
                "POST",
                f"repos/{self.repo}/issues/{number}/labels",
                "-f",
                f"labels[]={WAIT_LABEL}",
            )

    def unlabel(self, number: int) -> None:
        self._do(
            f"#{number}: etykieta `{WAIT_LABEL}` zdjęta",
            "api",
            "-X",
            "DELETE",
            f"repos/{self.repo}/issues/{number}/labels/{WAIT_LABEL}",
        )

    def promote(self, number: int) -> None:
        self.unlabel(number)
        self._do(
            f"#{number}: kolej w pasie migracji, auto-merge włączony",
            "pr",
            "merge",
            str(number),
            "--repo",
            self.repo,
            "--squash",
            "--auto",
        )
        self._comment(number, promote_comment())

    def _comment(self, number: int, body: str) -> None:
        if self.dry_run:
            print(f"[dry-run] #{number}: komentarz\n{body}")
            return
        try:
            upsert_comment(self.repo, number, body, run=self.run)
        except RuntimeError as exc:
            print(f"::warning::#{number}: komentarz się nie udał: {exc}")


def enforce(repo: str, dry_run: bool, run: Gh = gh) -> Plan:
    prs = fetch_prs(repo, run)
    plan = plan_lane(prs)
    print(
        f"PR-y z migracją: {', '.join(f'#{p.number}' for p in prs) or 'brak'}; "
        f"aktywny: {f'#{plan.active}' if plan.active else 'brak'}"
    )
    actions = Actions(repo, prs, dry_run, run)
    for number in plan.park:
        actions.park(number, plan.active, dequeue=number in plan.dequeue)
    if plan.unlabel is not None:
        actions.unlabel(plan.unlabel)
    if plan.promote is not None:
        actions.promote(plan.promote)
    return plan


def admit_pr(repo: str, number: int, dry_run: bool, run: Gh = gh) -> int:
    prs = fetch_prs(repo, run)
    active = admit(prs, number)
    me = next((p for p in prs if p.number == number), None)
    if active is None:
        if me is not None and me.waiting:
            Actions(repo, prs, dry_run, run).unlabel(number)
        print(f"#{number}: pas migracji wolny — wpuszczam.")
        return 0
    print(f"#{number}: pas migracji zajmuje #{active} — PR czeka.")
    Actions(repo, prs, dry_run, run).park(number, active, dequeue=False)
    return WAIT_EXIT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("admit", "enforce"))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, help="dla admit: numer PR-a")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "admit":
        if args.pr is None:
            parser.error("admit wymaga --pr")
        return admit_pr(args.repo, args.pr, args.dry_run)
    enforce(args.repo, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
