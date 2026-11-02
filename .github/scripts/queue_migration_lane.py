#!/usr/bin/env python3
"""Pas migracji: w kolejce merge'ów najwyżej dwa PR-y z migracją, w łańcuchu.

Po co (29.10.2026): kolejka buduje grupy jedna na drugiej (grupa 2 = main +
PR1 + PR2). Dwa PR-y z migracją przepiętą na tę samą głowę maina dają w grupie
dwie głowy, krok „Jedna głowa Alembica” czerwieni ją po ~1 min, a razem z nią
każdą grupę za nią — także PR-y bez migracji. Od 25 do 28.10 wszystkie 54
czerwone bramki kolejki miały ten powód; 28.10 było naraz 9 PR-ów z 0616.
``migration-rechain.yml`` przepina wszystkich na tę samą nową głowę, więc
w następnej rundzie znowu przechodził tylko pierwszy.

Reguła: w pasie jest najwyżej ``LANE_DEPTH`` PR-ów z migracją (w kolejce albo
z włączonym auto-merge'em i zielonymi checkami). Pierwszy stoi na głowie maina,
drugi na ostatniej migracji pierwszego, więc grupa „main + oba” ma jedną głowę.
Reszta dostaje etykietę ``czeka-na-migracje`` i wyłączony auto-merge;
``auto-enqueue`` ich nie wrzuca. Wolne miejsce w pasie dostaje czekający już
przepięty: na główne miejsce stojący na głowie maina (zielony nieprzepięty
wszedłby do kolejki od razu z dwiema głowami, a przepięcia nie dałoby się już
wypchnąć, GH006; 02.11.2026 tak wypadały #2889 i #2897), na drugie zielony
stojący na pierwszym, i dopiero gdy pierwszy jest już w kolejce: inaczej drugi
mógłby go wyprzedzić i paść. Kolejność migracji między sobą nie ma znaczenia.

Przepustowość (02.11.2026): jeden PR naraz to cykl ok. 36 min (przepięcie 1 +
sito 8–11 + pełne CI 24), więc 7 czekających to ok. 4 h, a z dwoma w pasie
ok. 2,4 h. Gdy pierwszy wypadnie, drugi zostaje bez rodzica: ``enforce`` zdejmuje
go z kolejki i każe przepiąć (``rechain=true``), a gdyby nie zdążył, „Jedna
głowa Alembica” czerwieni jego grupę, więc na main nic osieroconego nie wejdzie.
Wycofanie: ``LANE_DEPTH = 1``; następne przepięcie wraca PR-y na głowę maina.

Komendy:

* ``admit --pr N`` — z ``auto-enqueue.yml`` przed ``gh pr merge --auto``.
  Kod 0 = wpuść, ``WAIT_EXIT`` = PR zaparkowany (etykieta, komentarz).
* ``enforce`` — z ``queue-migration-lane.yml`` (po bramce i CI grup
  w kolejce) i z ``migration-rechain.yml`` (przed przepięciem i po nim):
  zdejmuje z kolejki nadmiarowe PR-y z migracją, parkuje uzbrojone, daje
  kolej następnemu. Gdy trzeba przepiąć, a main się nie zmienił, wypisuje
  ``rechain=true`` do ``$GITHUB_OUTPUT``.

Stdlib + ``gh`` (``GH_TOKEN`` = ``QUEUE_BOT_TOKEN``: etykieta zdjęta tokenem
Actions nie uruchomiłaby ``auto-enqueue``). ``--dry-run`` tylko wypisuje.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, NamedTuple

VERSIONS_PREFIX = "backend/alembic/versions/"
MIGRATION_NUMBER_RE = re.compile(r"^(\d+)_")
WAIT_LABEL = "czeka-na-migracje"
HOLD_LABEL = "wstrzymaj"
MARKER = "<!-- migration-lane -->"
WAIT_EXIT = 10
UNHEALTHY_CHECKS = {"FAILURE", "ERROR"}
LANE_DEPTH = 2
REVISION_RE = re.compile(
    r"^(down_revision|revision)\b[^=\n]*=\s*\(?\s*[\"']([^\"']+)[\"']", re.M
)

PRS_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, baseRefName: "main", first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id number isDraft isCrossRepository mergeable headRefOid
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
    fresh: bool = True  # stoi na głowie maina
    parent: str | None = None  # rodzic pierwszej migracji PR-a; None = nieznany
    tail: str | None = None  # ostatnia migracja PR-a
    orphan: bool = False  # rodzica nie ma na mainie


@dataclass(frozen=True)
class Plan:
    active: int | None
    dequeue: tuple[int, ...] = ()
    park: tuple[int, ...] = ()
    promote: int | None = None
    unlabel: tuple[int, ...] = ()
    lane: tuple[int, ...] = ()
    rechain: bool = False


class MainChain(NamedTuple):
    top: int | None = None  # najwyższy numer migracji
    revisions: frozenset[str] = frozenset()  # nazwy plików bez .py i id głowy
    tip: str | None = None  # id głowy


def chain_ends(sources: list[str]) -> tuple[str | None, str | None]:
    """(rodzic pierwszej migracji, ostatnia migracja) z treści plików PR-a."""
    revisions, downs = set(), set()
    for source in sources:
        for kind, value in REVISION_RE.findall(source):
            (revisions if kind == "revision" else downs).add(value)
    parents = downs - revisions
    tails = revisions - downs
    if len(parents) != 1 or len(tails) != 1:
        return None, None
    return parents.pop(), tails.pop()


def migration_numbers(names: list[str]) -> list[int]:
    matches = (MIGRATION_NUMBER_RE.match(name) for name in names)
    return [int(m.group(1)) for m in matches if m]


def parse_prs(
    nodes: list[dict],
    main_top: int | None = None,
    main: MainChain = MainChain(),
    chains: dict[int, tuple[str | None, str | None]] | None = None,
) -> list[Pr]:
    """PR-y z plikiem migracji; drafty, ``wstrzymaj`` i forki nie biorą udziału.

    ``main_top`` = najwyższy numer migracji na mainie; ``None`` = nieznany.
    ``chains`` = numer PR-a → ``chain_ends`` jego migracji.
    """
    main_top = main.top if main.top is not None else main_top
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
        names = [p.rsplit("/", 1)[-1] for p in paths if p.startswith(VERSIONS_PREFIX)]
        own = migration_numbers(names)
        parent, tail = (chains or {}).get(int(node["number"]), (None, None))
        prs.append(
            Pr(
                number=int(node["number"]),
                node_id=node["id"],
                queue_position=entry["position"] if entry else None,
                armed=node.get("autoMergeRequest") is not None,
                waiting=WAIT_LABEL in labels,
                healthy=rollup.get("state") not in UNHEALTHY_CHECKS
                and node.get("mergeable") != "CONFLICTING",
                fresh=(main_top is None or not own or max(own) > main_top)
                and (main.tip is None or parent is None or parent == main.tip),
                parent=parent,
                tail=tail,
                orphan=bool(main.revisions)
                and parent is not None
                and parent not in main.revisions,
            )
        )
    return sorted(prs, key=lambda p: p.number)


def stacked_on(pr: Pr, ahead: Pr) -> bool:
    return pr.parent is not None and pr.parent == ahead.tail


def plan_lane(prs: list[Pr], depth: int = LANE_DEPTH) -> Plan:
    """Kto zostaje w pasie, kogo zdjąć z kolejki, zaparkować, komu dać kolej.

    Pas = PR-y z kolejki, potem uzbrojone ze zdrowymi checkami, każdy następny
    stojący na poprzednim. Pierwszy zostaje jak dotąd, chyba że stracił rodzica:
    jego grupa i tak padnie. Uzbrojony z czerwonymi checkami nie blokuje pasa,
    ale przy zajętym pasie też traci auto-merge: po zazielenieniu GitHub
    wrzuciłby go do kolejki sam (#2916, 02.11.2026).
    """
    queued = sorted(
        (p for p in prs if p.queue_position is not None),
        key=lambda p: p.queue_position,
    )
    ready = [p for p in prs if p.queue_position is None and p.armed and p.healthy]
    lane: list[Pr] = []
    dequeue: list[Pr] = []

    def fits(p: Pr) -> bool:
        if not lane:
            return not p.orphan
        return len(lane) < depth and stacked_on(p, lane[-1])

    def stays_queued(p: Pr) -> bool:
        # Nieznany łańcuch (błąd odczytu) nie kosztuje grupy pełnego CI: gdyby
        # stan był naprawdę zły, czerwieni go „Jedna głowa Alembica”.
        unknown = lane and (p.parent is None or lane[-1].tail is None)
        return fits(p) or (bool(unknown) and len(lane) < depth)

    for p in queued:
        (lane if stays_queued(p) else dequeue).append(p)
    # Uzbrojony na stosie czeka, aż poprzedni będzie w kolejce: mógłby go wyprzedzić.
    for p in ready:
        if fits(p) and (not lane or lane[-1].queue_position is not None):
            lane.append(p)
    armed = [
        p
        for p in prs
        if p.queue_position is None and p.armed and p not in lane and (lane or p.orphan)
    ]
    parked = {p.number for p in [*dequeue, *armed]}

    waiting = sorted(
        (p for p in prs if p.waiting and p not in lane and p.number not in parked),
        key=lambda p: (not p.healthy, p.number),
    )
    candidates = [p for p in waiting if p.healthy] if lane else waiting
    anchored = [p for p in candidates if (stacked_on(p, lane[-1]) if lane else p.fresh)]
    free = len(lane) < depth
    can_enter = not lane or lane[-1].queue_position is not None
    in_lane = {p.tail for p in lane}
    lost = any(p.orphan and p not in lane and p.parent not in in_lane for p in prs)
    return Plan(
        active=lane[0].number if lane else None,
        dequeue=tuple(p.number for p in dequeue),
        park=tuple(p.number for p in [*dequeue, *armed]),
        promote=anchored[0].number if free and can_enter and anchored else None,
        unlabel=tuple(p.number for p in lane if p.waiting),
        lane=tuple(p.number for p in lane),
        rechain=lost or (free and bool(candidates) and not anchored),
    )


def admit(prs: list[Pr], number: int, depth: int = LANE_DEPTH) -> int | None:
    """Numer PR-a, który zajmuje pas, albo ``None`` = ``number`` może wejść."""
    me = next((p for p in prs if p.number == number), None)
    if me is None:
        return None
    others = [p for p in prs if p.number != number]
    plan = plan_lane(others, depth)
    if not plan.lane:
        return None
    last = next(p for p in others if p.number == plan.lane[-1])
    free = len(plan.lane) < depth
    if free and last.queue_position is not None and stacked_on(me, last):
        return None
    return plan.active


def stack_order(prs: list[Pr], depth: int = LANE_DEPTH) -> list[int]:
    """Kolejność przepinania: pas, potem zieloni czekający. Reszta idzie na głowę."""
    plan = plan_lane(prs, depth)
    rest = [
        p.number
        for p in sorted(prs, key=lambda p: p.number)
        if p.number not in plan.lane and p.waiting and p.healthy
    ]
    return [*plan.lane, *rest]


def park_comment(active: int | None) -> str:
    if active is None:
        return (
            f"{MARKER}\n**Czeka w pasie migracji.** Migracja tego PR-a stała na "
            "migracji PR-a, którego nie ma już w kolejce. Nic nie trzeba robić: "
            f"`migration-rechain.yml` przepnie ją na głowę maina, etykieta `{WAIT_LABEL}` "
            "zejdzie, a PR wejdzie do kolejki sam."
        )
    return (
        f"{MARKER}\n**Czeka w pasie migracji.** W kolejce merge'ów są naraz najwyżej "
        f"{LANE_DEPTH} PR-y z migracją Alembica, każdy na migracji poprzedniego, a pas "
        f"zajmuje #{active}: PR-y na tym samym rodzicu dają w grupie dwie głowy "
        "i wywracają też PR-y za sobą.\n\n"
        f"Nic nie trzeba robić. Gdy przyjdzie kolej, `migration-rechain.yml` przepnie "
        f"migrację tego PR-a, etykieta `{WAIT_LABEL}` zejdzie, a PR wejdzie do kolejki "
        "sam. Ręczne `gh pr merge --auto` nic nie przyspieszy: automat zdejmie PR "
        "z kolejki z powrotem."
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


def raw_file(repo: str, path: str, ref: str, run: Gh = gh) -> str:
    return run(
        "api",
        f"repos/{repo}/contents/{path}?ref={ref}",
        "-H",
        "Accept: application/vnd.github.raw",
    )


def read_main(repo: str, run: Gh = gh) -> MainChain:
    """Odczyt z API, nie z checkoutu: bieg może mieć maina sprzed scalenia.

    Błąd = puste pola, czyli kolej jak przed tą kontrolą; „Jedna głowa
    Alembica” i tak zatrzyma dwie głowy w kolejce.
    """
    path = f"repos/{repo}/contents/{VERSIONS_PREFIX.rstrip('/')}?ref=main"
    try:
        names = run("api", path, "--jq", ".[].name").split()
    except RuntimeError as exc:
        print(f"::warning::Lista migracji maina niedostępna: {exc}")
        return MainChain()
    numbered = [n for n in names if MIGRATION_NUMBER_RE.match(n) and n.endswith(".py")]
    if not numbered:
        return MainChain()
    top_name = max(numbered, key=lambda n: int(MIGRATION_NUMBER_RE.match(n).group(1)))
    stems = {n[:-3] for n in numbered}
    top = int(MIGRATION_NUMBER_RE.match(top_name).group(1))
    try:
        source = raw_file(repo, VERSIONS_PREFIX + top_name, "main", run)
    except RuntimeError as exc:
        print(f"::warning::Głowa migracji maina niedostępna: {exc}")
        return MainChain(top=top)
    tip = next((v for k, v in REVISION_RE.findall(source) if k == "revision"), None)
    if tip is None:
        return MainChain(top=top)
    return MainChain(top=top, revisions=frozenset(stems | {tip}), tip=tip)


def read_chain(
    repo: str, node: dict, main: MainChain, run: Gh = gh
) -> tuple[str | None, str | None]:
    """``chain_ends`` migracji PR-a; błąd = nieznane, PR nie stanie na stosie.

    Plik, który jest już na mainie, nie jest migracją tego PR-a: PR zbudowany na
    gałęzi innego PR-a ma go na liście plików także po squashu tamtego (automat
    nie scala maina do gałęzi), a wtedy nigdy nie stałby na głowie.
    """
    paths = [
        f["path"]
        for f in (node.get("files") or {}).get("nodes", [])
        if f["path"].startswith(VERSIONS_PREFIX)
        and f["path"].endswith(".py")
        and f["path"].rsplit("/", 1)[-1][:-3] not in main.revisions
    ]
    try:
        return chain_ends([raw_file(repo, p, node["headRefOid"], run) for p in paths])
    except (KeyError, RuntimeError) as exc:
        print(f"::warning::#{node.get('number')}: migracje PR-a niedostępne: {exc}")
        return None, None


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
            break
        cursor = page["pageInfo"]["endCursor"]
    # Main po PR-ach: gdy pierwszy scali się w międzyczasie, drugi nie wygląda
    # na PR bez rodzica i nie zostaje zdjęty z kolejki.
    main = read_main(repo, run)
    participants = {p.number for p in parse_prs(nodes)}
    chains = {
        int(node["number"]): read_chain(repo, node, main, run)
        for node in nodes
        if int(node["number"]) in participants
    }
    return parse_prs(nodes, main=main, chains=chains)


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

    def park(self, number: int, active: int | None, dequeue: bool) -> None:
        pr = self.by_number[number]
        if dequeue:
            self._do(
                f"#{number}: zdjęty z kolejki (pas: #{active})",
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
    for number in plan.unlabel:
        actions.unlabel(number)
    if plan.promote is not None:
        actions.promote(plan.promote)
    output = os.environ.get("GITHUB_OUTPUT")
    if plan.rechain and output and not dry_run:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write("rechain=true\n")
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
