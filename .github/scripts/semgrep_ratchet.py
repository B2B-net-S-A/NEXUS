#!/usr/bin/env python3
"""Zapadka Semgrepa: znaleziska z `.semgrep-baseline.json` przechodzą, nowe czerwienią.

    semgrep_ratchet.py include-args <lista-plików>
    semgrep_ratchet.py compare --results semgrep.json [--baseline .semgrep-baseline.json]
    semgrep_ratchet.py update  --results semgrep.json --reason "…" [--status zweryfikowane]

`include-args` zamienia listę zmienionych plików na argumenty `--include=…`.
Semgrep skanuje jawnie podane pliki nawet wtedy, gdy `.semgrepignore` je
pomija; przy skanie katalogów z `--include` ignore działa. Nazwy z `[`, `]`,
`*`, `?` (trasy Next.js typu `[slug]`) trzeba escapować, inaczej wzorzec nic
nie łapie i plik przechodzi bez skanu.

Odcisk znaleziska (`fingerprint`; nie „key”, bo gitleaks bierze heks przy
„key” za klucz API) to reguła + ścieżka + dopasowany fragment kodu (białe znaki
zwinięte), a nie numer linii: kod nad znaleziskiem może się przesuwać, ale
każda zmiana samego dopasowania (np. nowy `{parametr}` w f-stringu SQL) daje
nowy klucz i wymaga ponownego przeglądu. Te same fragmenty w jednym pliku
liczą się jak multizbiór — wpis w baseline pokrywa jedno wystąpienie.

`update` dopisuje nowe znaleziska z podanym powodem, odświeża numery linii
i usuwa wpisy, których już nie ma, wyłącznie w plikach, które Semgrep
przeskanował (wynik skanu częściowego nie kasuje reszty baseline).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

STATUSES = ("zweryfikowane", "do-przegladu")
DEFAULT_BASELINE = ".semgrep-baseline.json"
_GLOB_SPECIAL = "\\[]*?"


def escape_include(path: str) -> str:
    """Wzorzec `--include` dopasowujący dokładnie ten plik od korzenia repo."""
    escaped = "".join("\\" + ch if ch in _GLOB_SPECIAL else ch for ch in path)
    return "/" + escaped.lstrip("/")


def finding_fingerprint(check_id: str, path: str, snippet: str) -> str:
    normalized = "".join(snippet.split())
    raw = "\0".join((check_id, path, normalized)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _snippet(root: Path, result: dict, cache: dict[str, bytes]) -> str:
    path = result["path"]
    if path not in cache:
        cache[path] = (root / path).read_bytes()
    data = cache[path]
    start, end = result["start"].get("offset"), result["end"].get("offset")
    if isinstance(start, int) and isinstance(end, int) and end >= start:
        return data[start:end].decode("utf-8", errors="replace")
    lines = data.decode("utf-8", errors="replace").splitlines()
    return "\n".join(lines[result["start"]["line"] - 1 : result["end"]["line"]])


def load_findings(results_path: Path, root: Path) -> tuple[list[dict], set[str]]:
    """Znaleziska z wyniku `semgrep --json` i zbiór przeskanowanych plików."""
    data = json.loads(results_path.read_text(encoding="utf-8"))
    cache: dict[str, bytes] = {}
    findings = []
    for result in data.get("results", []):
        path = result["path"]
        findings.append(
            {
                "rule": result["check_id"],
                "path": path,
                "line": result["start"]["line"],
                "fingerprint": finding_fingerprint(result["check_id"], path, _snippet(root, result, cache)),
                "message": " ".join(str(result.get("extra", {}).get("message", "")).split()),
            }
        )
    scanned = set(data.get("paths", {}).get("scanned", []))
    scanned |= {f["path"] for f in findings}
    return findings, scanned


def load_baseline(path: Path) -> dict:
    if not path.exists():
        return {"findings": []}
    return json.loads(path.read_text(encoding="utf-8"))


def baseline_problems(baseline: dict) -> list[str]:
    problems = []
    for entry in baseline.get("findings", []):
        where = f"{entry.get('path')}:{entry.get('line')} ({entry.get('rule')})"
        if entry.get("status") not in STATUSES:
            problems.append(f"{where}: status musi być jednym z {', '.join(STATUSES)}")
        if not str(entry.get("reason", "")).strip():
            problems.append(f"{where}: brak uzasadnienia (pole reason)")
        if not entry.get("fingerprint"):
            problems.append(f"{where}: brak odcisku (pole fingerprint)")
    return problems


def split(findings: list[dict], baseline: dict, scanned: set[str]):
    """(nowe, pokryte, nieaktualne) — nieaktualne tylko w przeskanowanych plikach."""
    pool: dict[str, list[dict]] = defaultdict(list)
    for entry in baseline.get("findings", []):
        pool[entry.get("fingerprint", "")].append(entry)
    new, covered = [], []
    for finding in sorted(findings, key=lambda f: (f["path"], f["line"], f["rule"])):
        bucket = pool.get(finding["fingerprint"])
        if bucket:
            covered.append((finding, bucket.pop(0)))
        else:
            new.append(finding)
    stale = [
        entry
        for entries in pool.values()
        for entry in entries
        if entry.get("path") in scanned
    ]
    return new, covered, stale


def _annotation(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _summary(lines: list[str]) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def cmd_include_args(args: argparse.Namespace) -> int:
    files = Path(args.files).read_text(encoding="utf-8").splitlines()
    for name in files:
        name = name.strip()
        if name:
            print("--include=" + escape_include(name))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    findings, scanned = load_findings(Path(args.results), Path(args.root))
    baseline = load_baseline(Path(args.baseline))
    problems = baseline_problems(baseline)
    new, covered, stale = split(findings, baseline, scanned)

    for problem in problems:
        print(f"::error title=Semgrep baseline::{_annotation(problem)}")
    for finding in new:
        print(
            f"::error file={finding['path']},line={finding['line']},"
            f"title=Semgrep {finding['rule'].rsplit('.', 1)[-1]}::"
            + _annotation(finding["message"][:500])
        )
    for entry in stale:
        print(
            f"::notice file={entry['path']},line={entry.get('line', 1)},"
            "title=Semgrep baseline::Znalezisko z baseline już nie występuje — "
            "usuń wpis (semgrep_ratchet.py update)."
        )

    print(
        f"Przeskanowane pliki: {len(scanned)}; znaleziska: {len(findings)}; "
        f"z baseline: {len(covered)}; nowe: {len(new)}; nieaktualne wpisy: {len(stale)}"
    )
    summary = [
        "### Semgrep — zapadka",
        "",
        f"Przeskanowane pliki: **{len(scanned)}**, znaleziska: **{len(findings)}**, "
        f"z baseline: **{len(covered)}**, **nowe: {len(new)}**, nieaktualne wpisy: {len(stale)}.",
    ]
    if new:
        summary += ["", "| Plik:linia | Reguła |", "|---|---|"]
        summary += [f"| `{f['path']}:{f['line']}` | `{f['rule']}` |" for f in new]
        summary += [
            "",
            "Popraw kod albo — gdy to świadomy wyjątek — dopisz go do "
            "`.semgrep-baseline.json` z uzasadnieniem: "
            "`python3 .github/scripts/semgrep_ratchet.py update --results semgrep.json "
            '--status zweryfikowane --reason "…"`.',
        ]
    _summary(summary)
    if new:
        print(
            f"::error::Semgrep: {len(new)} nowych znalezisk. Popraw kod albo dopisz "
            "świadomy wyjątek do .semgrep-baseline.json z uzasadnieniem "
            "(docs/claude/podstawy/skanery-bezpieczenstwa.md)."
        )
    return 1 if new or problems else 0


def cmd_update(args: argparse.Namespace) -> int:
    findings, scanned = load_findings(Path(args.results), Path(args.root))
    baseline_path = Path(args.baseline)
    baseline = load_baseline(baseline_path)
    new, covered, stale = split(findings, baseline, scanned)
    if new and not args.reason.strip():
        print(f"{len(new)} nowych znalezisk — podaj --reason z uzasadnieniem.", file=sys.stderr)
        return 2
    stale_ids = {id(entry) for entry in stale}
    kept = [
        entry
        for entry in baseline.get("findings", [])
        if id(entry) not in stale_ids
    ]
    for finding, entry in covered:
        entry["line"] = finding["line"]
    for finding in new:
        kept.append(
            {
                "rule": finding["rule"],
                "path": finding["path"],
                "line": finding["line"],
                "fingerprint": finding["fingerprint"],
                "status": args.status,
                "reason": args.reason.strip(),
            }
        )
    kept.sort(key=lambda e: (e["path"], e["line"], e["rule"]))
    baseline["findings"] = [
        {k: e[k] for k in ("rule", "path", "line", "fingerprint", "status", "reason")} for e in kept
    ]
    baseline_path.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Baseline: {len(kept)} wpisów (nowe {len(new)}, usunięte {len(stale)}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    inc = sub.add_parser("include-args")
    inc.add_argument("files")
    inc.set_defaults(func=cmd_include_args)

    for name, func in (("compare", cmd_compare), ("update", cmd_update)):
        p = sub.add_parser(name)
        p.add_argument("--results", required=True)
        p.add_argument("--baseline", default=DEFAULT_BASELINE)
        p.add_argument("--root", default=".")
        if name == "update":
            p.add_argument("--reason", default="")
            p.add_argument("--status", choices=STATUSES, default="do-przegladu")
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
