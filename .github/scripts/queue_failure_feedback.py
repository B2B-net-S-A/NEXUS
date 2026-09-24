#!/usr/bin/env python3
"""Informuje PR-y, że ich grupa wypadła z kolejki merge'ów.

Po czerwonym biegu CI na ``gh-readonly-queue/main/pr-<N>-<sha>`` GitHub
wyrzuca PR z kolejki, ale checki samego PR-a zostają zielone. Sesja, która
pilnuje PR-a (auto-fix aplikacji patrzy na checki PR-a), nic nie wie, a
``auto-enqueue`` po następnym pushu wrzuca PR z powrotem na ten sam błąd.
Zmierzone 23–24.09.2026: 62 z 99 biegów CI w kolejce czerwone w 27 h,
PR-y wyrzucane po 4–6 razy.

Dla każdego OTWARTEGO PR-a z grupy skrypt:

* ustawia status commita ``Kolejka merge'ów`` = ``failure`` na aktualnym
  HEAD PR-a (znika sam przy nowym commicie — tak ma być; NIE jest wymagany);
* dopisuje albo aktualizuje komentarz (znacznik ``<!-- queue-failure-feedback -->``)
  z listą czerwonych testów i linkiem do biegu.

PR-y w grupie: commity od ``main`` do HEAD gałęzi kolejki (po jednym
squashu na PR, ``(#N)`` w tytule); awaryjnie ``pr-<N>`` z nazwy gałęzi.
Stdlib + ``gh`` (``GH_TOKEN``). ``--dry-run`` tylko wypisuje, co by wysłał.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass

MARKER = "<!-- queue-failure-feedback -->"
STATUS_CONTEXT = "Kolejka merge'ów"
MAX_TESTS = 20
MAX_JOB_ERRORS = 5
MAX_REASON = 160

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z ?")
_QUEUE_BRANCH = re.compile(
    r"^gh-readonly-queue/(?P<base>.+)/pr-(?P<pr>\d+)-(?P<sha>[0-9a-f]{7,40})$"
)
_PR_REF = re.compile(r"\(#(\d+)\)\s*$")
_PYTEST = re.compile(
    r"^(?P<kind>FAILED|ERROR) (?P<id>tests/\S+?)(?: - (?P<reason>.*))?$"
)
_VITEST = re.compile(
    r"^\s*FAIL\s+(?P<id>\S+?\.(?:test|spec)\.[cm]?[jt]sx?(?: > .*?)?)(?:\s+\[ .* \])?\s*$"
)
_TSC = re.compile(
    r"^(?P<file>\S+?\.[cm]?[jt]sx?)\((?P<pos>\d+,\d+)\): error (?P<code>TS\d+): (?P<msg>.*)$"
)
_TSC_ALT = re.compile(
    r"^(?P<file>\S+?\.[cm]?[jt]sx?):(?P<pos>\d+:\d+) - error (?P<code>TS\d+): (?P<msg>.*)$"
)
_ERROR_LINE = re.compile(r"^##\[error\](?P<msg>.*)$")
_VITEST_REASON = re.compile(r"^\s*(?:\w*Error|AssertionError)\b.*")


@dataclass(frozen=True)
class Failure:
    kind: str  # pytest | vitest | tsc
    test_id: str
    reason: str = ""

    @property
    def file(self) -> str:
        if self.kind == "vitest":
            return self.test_id.split(" > ", 1)[0]
        return self.test_id.split("::", 1)[0].split("(", 1)[0]


def clean_line(line: str) -> str:
    """Bez znacznika czasu Actions i kolorów ANSI."""
    return _ANSI.sub("", _TIMESTAMP.sub("", line.rstrip()))


def _short(text: str, limit: int = MAX_REASON) -> str:
    text = " ".join(text.split()).replace("`", "'")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def parse_failures(log_text: str) -> list[Failure]:
    """Czerwone testy z logu joba: pytest (FAILED/ERROR), vitest (FAIL), tsc."""
    lines = [clean_line(raw) for raw in log_text.splitlines()]
    found: list[Failure] = []
    seen: set[str] = set()

    def add(failure: Failure) -> None:
        key = f"{failure.kind}:{failure.test_id}"
        if key not in seen:
            seen.add(key)
            found.append(failure)

    for index, line in enumerate(lines):
        match = _PYTEST.match(line)
        if match:
            add(
                Failure("pytest", match["id"], _short(match["reason"] or match["kind"]))
            )
            continue
        match = _VITEST.match(line)
        if match:
            test_id = match["id"].strip()  # bez „[ plik ]” z nagłówka pliku
            reason = ""
            for following in lines[index + 1 : index + 4]:
                if _VITEST_REASON.match(following):
                    reason = _short(following.strip())
                    break
            add(Failure("vitest", test_id, reason))
            continue
        match = _TSC.match(line) or _TSC_ALT.match(line)
        if match:
            test_id = f"{match['file']}({match['pos'].replace(':', ',')})"
            add(Failure("tsc", test_id, _short(f"{match['code']}: {match['msg']}")))
    return found


def first_job_error(log_text: str) -> str:
    """Pierwszy sensowny ``##[error]`` joba, gdy nie rozpoznano testów."""
    for raw in log_text.splitlines():
        match = _ERROR_LINE.match(clean_line(raw))
        if match and not match["msg"].startswith("Process completed with exit code"):
            return _short(match["msg"])
    return ""


def parse_queue_branch(branch: str) -> tuple[int | None, str | None]:
    """``gh-readonly-queue/main/pr-1766-626bbe…`` → (1766, "626bbe…")."""
    match = _QUEUE_BRANCH.match(branch or "")
    if not match:
        return None, None
    return int(match["pr"]), match["sha"]


def prs_from_compare(compare: dict) -> list[int]:
    """Numery PR-ów z tytułów squashy (``… (#N)``), w kolejności commitów."""
    numbers: list[int] = []
    for commit in compare.get("commits") or []:
        subject = (commit.get("commit", {}).get("message") or "").splitlines()
        match = _PR_REF.search(subject[0]) if subject else None
        if match and int(match.group(1)) not in numbers:
            numbers.append(int(match.group(1)))
    return numbers


def group_prs(compare: dict | None, branch: str) -> list[int]:
    prs = prs_from_compare(compare or {})
    branch_pr, _ = parse_queue_branch(branch)
    if branch_pr is not None and branch_pr not in prs:
        prs.append(branch_pr)
    return prs


def plural_tests(count: int) -> str:
    if count == 1:
        return "1 test"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} testy"
    return f"{count} testów"


def status_description(
    failures: list[Failure], job_errors: list[tuple[str, str]]
) -> str:
    if failures:
        text = (
            f"Wypadł z kolejki: {plural_tests(len(failures))} — szczegóły w komentarzu"
        )
    elif job_errors:
        text = f"Wypadł z kolejki: błąd w jobie {job_errors[0][0]} — szczegóły w komentarzu"
    else:
        text = "Wypadł z kolejki merge'ów — szczegóły w komentarzu"
    return text if len(text) <= 140 else text[:139] + "…"


def build_comment(
    pr: int,
    group: list[int],
    queue_pr: int | None,
    run_url: str,
    failures: list[Failure],
    job_errors: list[tuple[str, str]],
) -> str:
    lines = [
        MARKER,
        "### Wypadł z kolejki merge'ów",
        "",
        f"Bieg CI w kolejce jest czerwony: {run_url}",
        "Checki tego PR-a są zielone, bo na PR-ze leci tylko sito testów; pełny "
        "zestaw biegnie w kolejce na drzewie razem z PR-ami przed nim.",
        "",
    ]
    if failures:
        lines.append(f"**Czerwone testy ({len(failures)}):**")
        for failure in failures[:MAX_TESTS]:
            reason = f" — {failure.reason}" if failure.reason else ""
            lines.append(f"- `{failure.test_id}`{reason}")
        if len(failures) > MAX_TESTS:
            lines.append(
                f"- …i jeszcze {len(failures) - MAX_TESTS} (pełna lista w biegu)"
            )
        lines.append("")
    if job_errors:
        lines.append("**Joby bez rozpoznanych testów:**")
        for job, message in job_errors[:MAX_JOB_ERRORS]:
            lines.append(f"- {job}: {message or 'brak komunikatu — zobacz log'}")
        lines.append("")
    others = [n for n in group if n != pr]
    if others:
        listed = ", ".join(f"#{n}" for n in group)
        lines.append(
            f"**Grupa w kolejce:** {listed}. Winny może być inny PR z tej grupy "
            "(albo dopiero ich połączenie) — sprawdź, czy czerwone testy dotyczą "
            "Twojej zmiany, zanim ją poprawisz."
        )
        if queue_pr is not None and queue_pr != pr:
            lines.append(
                f"Bieg dotyczył wpisu #{queue_pr}; ten PR był przed nim w kolejce "
                "i jego własny bieg mógł przejść osobno."
            )
        lines.append("")
    lines.append(
        f"_Status `{STATUS_CONTEXT}` na HEAD tego PR-a zniknie przy następnym "
        "commicie. Komentarz aktualizuje się przy kolejnym wypadnięciu._"
    )
    return "\n".join(lines)


# ── GitHub (gh) ───────────────────────────────────────────────────────────


def gh(*args: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        ["gh", *args], input=stdin, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {result.stderr.strip()[:500]}")
    return result.stdout


def gh_json(path: str) -> object:
    return json.loads(gh("api", path))


def collect_failures(
    repo: str, run_id: int
) -> tuple[list[Failure], list[tuple[str, str]]]:
    jobs = gh_json(
        f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100&filter=latest"
    )
    failures: list[Failure] = []
    job_errors: list[tuple[str, str]] = []
    seen: set[str] = set()
    for job in jobs.get("jobs", []):
        if job.get("conclusion") not in ("failure", "timed_out"):
            continue
        try:
            log_text = gh("api", f"repos/{repo}/actions/jobs/{job['id']}/logs")
        except RuntimeError as exc:
            job_errors.append((job["name"], f"nie udało się pobrać logu ({exc})"))
            continue
        parsed = parse_failures(log_text)
        for failure in parsed:
            key = f"{failure.kind}:{failure.test_id}"
            if key not in seen:
                seen.add(key)
                failures.append(failure)
        if not parsed:
            job_errors.append((job["name"], first_job_error(log_text)))
    # Job zbiorczy („Backend (pytest)”) tylko powtarza, że shard padł.
    if failures:
        job_errors = [(n, m) for n, m in job_errors if "shard" not in m.lower()]
    return failures, job_errors


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
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--base", default="main")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    run = gh_json(f"repos/{args.repo}/actions/runs/{args.run_id}")
    if run.get("event") != "merge_group" or run.get("conclusion") != "failure":
        print(
            f"Bieg {args.run_id}: event={run.get('event')} conclusion={run.get('conclusion')} — pomijam."
        )
        return 0
    branch, head_sha, run_url = run["head_branch"], run["head_sha"], run["html_url"]
    queue_pr, _ = parse_queue_branch(branch)
    try:
        compare = gh_json(f"repos/{args.repo}/compare/{args.base}...{head_sha}")
    except RuntimeError as exc:
        print(f"::warning::compare {args.base}...{head_sha}: {exc} — PR z nazwy gałęzi")
        compare = None
    group = group_prs(compare, branch)
    if not group:
        print(f"::warning::Nie rozpoznano PR-ów w grupie {branch}")
        return 0
    failures, job_errors = collect_failures(args.repo, args.run_id)
    description = status_description(failures, job_errors)
    print(
        f"Bieg: {run_url}\nGałąź: {branch}\nGrupa: {', '.join(f'#{n}' for n in group)}"
    )
    print(f"Czerwone testy: {len(failures)}; joby bez testów: {len(job_errors)}")
    for failure in failures[:MAX_TESTS]:
        print(f"  {failure.test_id} — {failure.reason}")
    for job, message in job_errors[:MAX_JOB_ERRORS]:
        print(f"  [{job}] {message}")

    for pr in group:
        info = gh_json(f"repos/{args.repo}/pulls/{pr}")
        if info.get("state") != "open":
            state = "zmergowany" if info.get("merged_at") else info.get("state")
            print(f"#{pr}: {state} — pomijam")
            continue
        sha = info["head"]["sha"]
        body = build_comment(pr, group, queue_pr, run_url, failures, job_errors)
        status = {
            "state": "failure",
            "context": STATUS_CONTEXT,
            "description": description,
            "target_url": run_url,
        }
        if args.dry_run:
            print(
                f"\n--- #{pr}: status na {sha[:9]} ---\n{json.dumps(status, ensure_ascii=False)}"
            )
            print(f"--- #{pr}: komentarz ---\n{body}")
            continue
        gh(
            "api",
            "-X",
            "POST",
            f"repos/{args.repo}/statuses/{sha}",
            "--input",
            "-",
            stdin=json.dumps(status),
        )
        print(
            f"#{pr}: status failure na {sha[:9]}; {upsert_comment(args.repo, pr, body)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
