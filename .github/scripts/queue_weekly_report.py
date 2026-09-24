#!/usr/bin/env python3
"""Tygodniowy raport kolejki merge'ów: co wyrzuca PR-y i czego sito nie łapie.

Zbiera biegi CI z ``merge_group`` z ostatnich N dni (domyślnie 7) i liczy:

* biegi razem / czerwone / anulowane, odsetek czerwonych;
* medianę czasu ZIELONYCH biegów kolejki (start → koniec);
* ile razy padał każdy plik testowy (raz na bieg) i każdy PR (wpis ``pr-<N>``);
* które czerwone pliki pytest NIE zostałyby wybrane przez sito PR-a
  (``select_pr_tests.select`` + budżet z ``ci_test_durations.json``) na plikach
  zmienionych w tym PR-ze — to kandydaci na nową regułę sita.

Wynik: jedno issue „Raport kolejki merge'ów — tydzień <ISO>” z etykietą
``raport-kolejki`` (tworzone albo aktualizowane). ``--dry-run`` wypisuje treść.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import queue_failure_feedback as qff  # noqa: E402

LABEL = "raport-kolejki"
TITLE_PREFIX = "Raport kolejki merge'ów — tydzień"
MAX_BODY = 60000
TOP = 25


@dataclass
class RunFailures:
    run_id: int
    url: str
    pr: int | None
    failures: list[qff.Failure] = field(default_factory=list)


def parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def run_minutes(run: dict) -> float | None:
    start, end = run.get("run_started_at"), run.get("updated_at")
    if not start or not end:
        return None
    return (parse_time(end) - parse_time(start)).total_seconds() / 60


def iso_week_label(now: datetime) -> str:
    """Raport z poniedziałku opisuje tydzień, który właśnie minął."""
    year, week, _ = (now - timedelta(days=1)).isocalendar()
    return f"{year}-W{week:02d}"


def summarize_runs(runs: list[dict]) -> dict:
    conclusions = Counter(run.get("conclusion") or run.get("status") for run in runs)
    decided = conclusions["success"] + conclusions["failure"]
    green = [
        m
        for run in runs
        if run.get("conclusion") == "success"
        if (m := run_minutes(run)) is not None
    ]
    return {
        "total": len(runs),
        "success": conclusions["success"],
        "failure": conclusions["failure"],
        "cancelled": conclusions["cancelled"],
        "other": len(runs) - decided - conclusions["cancelled"],
        "fail_rate": (conclusions["failure"] / decided) if decided else 0.0,
        "median_green_minutes": statistics.median(green) if green else None,
    }


def count_failures(results: list[RunFailures]) -> tuple[Counter, Counter]:
    """(plik testowy → liczba czerwonych biegów, PR → liczba czerwonych biegów)."""
    per_file: Counter = Counter()
    per_pr: Counter = Counter()
    for result in results:
        per_file.update({failure.file for failure in result.failures})
        if result.pr is not None:
            per_pr[result.pr] += 1
    return per_file, per_pr


def sieve_misses(
    results: list[RunFailures],
    changed_files: dict[int, list[str]],
    choose,
) -> dict[str, dict[str, set[int]]]:
    """Plik pytest → {"niewybrany": {PR…}, "budżet": {PR…}} dla czerwonych biegów.

    ``choose(changed) -> (wybrane_po_budżecie, pominięte_przez_budżet)``.
    Frontendu nie oceniamy — sito dotyczy tylko pytestu.
    """
    cache: dict[int, tuple[set[str], set[str]]] = {}
    misses: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    for result in results:
        if result.pr is None or result.pr not in changed_files:
            continue
        if result.pr not in cache:
            kept, dropped = choose(changed_files[result.pr])
            cache[result.pr] = (set(kept), set(dropped))
        kept, dropped = cache[result.pr]
        for file in {f.file for f in result.failures if f.kind == "pytest"}:
            if file in kept:
                continue
            misses[file]["budżet" if file in dropped else "niewybrany"].add(result.pr)
    return misses


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def render_report(
    since: datetime,
    until: datetime,
    summary: dict,
    per_file: Counter,
    per_pr: Counter,
    misses: dict[str, dict[str, set[int]]],
    repo: str,
) -> str:
    median = summary["median_green_minutes"]
    lines = [
        f"Okres: {since:%Y-%m-%d %H:%M} – {until:%Y-%m-%d %H:%M} UTC · workflow `CI`, zdarzenie `merge_group`.",
        "",
        "| Biegi | Zielone | Czerwone | Anulowane | Czerwone / rozstrzygnięte | Mediana zielonego biegu |",
        "|---:|---:|---:|---:|---:|---:|",
        f"| {summary['total']} | {summary['success']} | {summary['failure']} | "
        f"{summary['cancelled']} | {_pct(summary['fail_rate'])} | "
        f"{f'{median:.1f} min' if median is not None else '—'} |",
        "",
        f"### Pliki testowe, które wyrzucały z kolejki (top {TOP})",
        "",
    ]
    if per_file:
        lines += ["| Plik | Czerwone biegi |", "|---|---:|"]
        lines += [
            f"| `{name}` | {count} |" for name, count in per_file.most_common(TOP)
        ]
    else:
        lines.append("Brak rozpoznanych czerwonych testów.")
    lines += ["", f"### PR-y wyrzucane z kolejki (top {TOP})", ""]
    if per_pr:
        lines += ["| PR | Czerwone biegi |", "|---|---:|"]
        lines += [f"| #{pr} | {count} |" for pr, count in per_pr.most_common(TOP)]
    else:
        lines.append("Brak.")
    lines += [
        "",
        "### Czego sito PR-a nie wybrało (kandydaci na reguły `select_pr_tests.py`)",
        "",
        "„Niewybrany” = żadna reguła sita nie wskazała pliku dla zmian tego PR-a; "
        "„budżet” = wskazany pośrednio, ale odcięty budżetem czasu. Pliki PR-a są "
        "brane w obecnym stanie, drzewo testów — z maina.",
        "",
    ]
    if misses:
        lines += [
            "| Plik | Niewybrany (PR-y) | Poza budżetem (PR-y) |",
            "|---|---|---|",
        ]
        ordered = sorted(
            misses.items(),
            key=lambda item: (
                -len(item[1].get("niewybrany", ())),
                -per_file[item[0]],
                item[0],
            ),
        )
        for name, kinds in ordered:
            unpicked = (
                ", ".join(f"#{n}" for n in sorted(kinds.get("niewybrany", ()))) or "—"
            )
            budget = ", ".join(f"#{n}" for n in sorted(kinds.get("budżet", ()))) or "—"
            lines.append(f"| `{name}` | {unpicked} | {budget} |")
    else:
        lines.append("Sito wybrało każdy czerwony plik pytest — brak kandydatów.")
    lines += [
        "",
        f"_Wygenerowane przez `.github/workflows/queue-weekly-report.yml` ({repo}). "
        "Issue jest aktualizowane przy ponownym uruchomieniu w tym samym tygodniu._",
    ]
    body = "\n".join(lines)
    if len(body) > MAX_BODY:
        body = body[: MAX_BODY - 40] + "\n\n…(ucięte — limit treści issue)"
    return body


# ── GitHub (gh) ───────────────────────────────────────────────────────────


def list_queue_runs(repo: str, since: datetime) -> list[dict]:
    raw = qff.gh(
        "api",
        "--paginate",
        f"repos/{repo}/actions/workflows/ci.yml/runs?event=merge_group"
        f"&created=>={since:%Y-%m-%dT%H:%M:%SZ}&per_page=100",
        "--jq",
        ".workflow_runs[] | @json",
    )
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def pr_changed_files(repo: str, pr: int) -> list[str] | None:
    try:
        raw = qff.gh(
            "api",
            "--paginate",
            f"repos/{repo}/pulls/{pr}/files?per_page=100",
            "--jq",
            ".[].filename",
        )
    except RuntimeError as exc:
        print(f"::warning::Pliki PR #{pr}: {exc}")
        return None
    return raw.split()


def make_chooser():
    import select_pr_tests as sieve

    try:
        durations = json.loads(sieve._DURATIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        durations = {}

    def choose(changed: list[str]) -> tuple[list[str], list[str]]:
        direct, indirect = sieve.select(changed)
        return sieve.apply_budget(direct, indirect, 300.0, durations)

    return choose


def upsert_issue(repo: str, title: str, body: str) -> str:
    qff.gh(
        "label",
        "create",
        LABEL,
        "--repo",
        repo,
        "--color",
        "B60205",
        "--force",
        "--description",
        "Tygodniowy raport kolejki merge'ów",
    )
    raw = qff.gh(
        "api",
        f"repos/{repo}/issues?labels={LABEL}&state=all&per_page=100",
        "--jq",
        ".[] | [.number, .title] | @json",
    )
    for line in raw.splitlines():
        number, existing = json.loads(line)
        if existing == title:
            qff.gh(
                "api",
                "-X",
                "PATCH",
                f"repos/{repo}/issues/{number}",
                "--input",
                "-",
                stdin=json.dumps({"body": body, "state": "open"}),
            )
            return f"zaktualizowane #{number}"
    out = qff.gh(
        "api",
        "-X",
        "POST",
        f"repos/{repo}/issues",
        "--input",
        "-",
        "--jq",
        ".html_url",
        stdin=json.dumps({"title": title, "body": body, "labels": [LABEL]}),
    )
    return f"utworzone {out.strip()}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    until = datetime.now(timezone.utc).replace(microsecond=0)
    since = until - timedelta(days=args.days)
    runs = list_queue_runs(args.repo, since)
    summary = summarize_runs(runs)
    failed_runs = [run for run in runs if run.get("conclusion") == "failure"]

    def collect(run: dict) -> RunFailures:
        pr, _ = qff.parse_queue_branch(run.get("head_branch", ""))
        try:
            failures, _ = qff.collect_failures(args.repo, run["id"])
        except RuntimeError as exc:
            print(f"::warning::Bieg {run['id']}: {exc}")
            failures = []
        return RunFailures(run["id"], run["html_url"], pr, failures)

    # Logi jobów to kilka MB każdy; ~60 czerwonych biegów × 3 joby po kolei
    # to kilkanaście minut, równolegle — dwie–trzy.
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(collect, failed_runs))
    per_file, per_pr = count_failures(results)
    changed = {}
    for pr in sorted({r.pr for r in results if r.pr is not None}):
        files = pr_changed_files(args.repo, pr)
        if files is not None:
            changed[pr] = files
    misses = sieve_misses(results, changed, make_chooser())
    week = iso_week_label(until)
    title = f"{TITLE_PREFIX} {week}"
    body = render_report(since, until, summary, per_file, per_pr, misses, args.repo)
    if args.dry_run:
        print(f"# {title}\n\n{body}")
        return 0
    print(upsert_issue(args.repo, title, body))
    return 0


if __name__ == "__main__":
    sys.exit(main())
