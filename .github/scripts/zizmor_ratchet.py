#!/usr/bin/env python3
"""Zapadka zizmora: znaleziska z `.github/zizmor-baseline.json` przechodzą, nowe czerwienią.

    zizmor_ratchet.py compare --results zizmor.json [--baseline .github/zizmor-baseline.json]
    zizmor_ratchet.py update  --results zizmor.json --reason "…" [--status zweryfikowane]

zizmor (linter bezpieczeństwa GitHub Actions) skanuje zawsze całe repo
(workflowy, `dependabot.yml`), więc wynik jest pełny i wpis, którego skan już
nie zwraca, jest nieaktualny. Wejście to `zizmor --format json`.

Odcisk (`fingerprint`, nie „key” — patrz `semgrep_ratchet.py`) to audyt +
ścieżka + droga w YAML-u bez indeksów kroków (`jobs.rechain.steps.run`) +
dopasowany fragment (białe znaki zwinięte). Numer linii i pozycja kroku mogą
się przesuwać; każda zmiana samego dopasowania (np. nowe `${{ }}` w tym samym
`run:`) daje nowy odcisk i wymaga ponownego przeglądu. Status, powód
i porównanie wspólne z zapadką Semgrepa.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

DEFAULT_BASELINE = ".github/zizmor-baseline.json"


def _semgrep_ratchet():
    path = Path(__file__).with_name("semgrep_ratchet.py")
    spec = importlib.util.spec_from_file_location("semgrep_ratchet", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SR = _semgrep_ratchet()
STATUSES = _SR.STATUSES
baseline_problems = _SR.baseline_problems


def _primary(finding: dict) -> dict:
    locations = finding.get("locations") or []
    for location in locations:
        if location.get("symbolic", {}).get("kind") == "Primary":
            return location
    if not locations:
        raise ValueError(f"znalezisko {finding.get('ident')} bez lokalizacji")
    return locations[0]


def _path(symbolic: dict) -> str:
    local = symbolic.get("key", {}).get("Local", {})
    path = local.get("verbatim_path") or local.get("given_path") or ""
    return path[2:] if path.startswith("./") else path


def _route(symbolic: dict) -> str:
    keys = [str(part["Key"]) for part in symbolic.get("route", {}).get("route", []) if "Key" in part]
    return ".".join(keys)


def load_findings(results_path: Path) -> list[dict]:
    data = json.loads(results_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("wynik zizmora to nie lista znalezisk (--format json)")
    findings = []
    for result in data:
        location = _primary(result)
        symbolic, concrete = location.get("symbolic", {}), location.get("concrete", {})
        path, route = _path(symbolic), _route(symbolic)
        feature = str(concrete.get("feature", ""))
        line = concrete.get("location", {}).get("start_point", {}).get("row", 0) + 1
        findings.append(
            {
                "rule": result["ident"],
                "path": path,
                "line": line,
                "route": route,
                "fingerprint": _SR.finding_fingerprint(result["ident"], path, route + "\n" + feature),
                "severity": result.get("determinations", {}).get("severity", ""),
                "message": " ".join(
                    f"{result.get('desc', '')}: {symbolic.get('annotation', '')}".split()
                ),
            }
        )
    return findings


def _split(findings: list[dict], baseline: dict):
    # Skan jest zawsze pełny: każdy niedopasowany wpis jest nieaktualny.
    everything = {entry.get("path") for entry in baseline.get("findings", [])}
    return _SR.split(findings, baseline, everything)


def cmd_compare(args: argparse.Namespace) -> int:
    findings = load_findings(Path(args.results))
    baseline = _SR.load_baseline(Path(args.baseline))
    problems = baseline_problems(baseline)
    new, covered, stale = _split(findings, baseline)

    for problem in problems:
        print(f"::error title=zizmor baseline::{_SR._annotation(problem)}")
    for finding in new:
        print(
            f"::error file={finding['path']},line={finding['line']},"
            f"title=zizmor {finding['rule']}::" + _SR._annotation(finding["message"][:500])
        )
    for entry in stale:
        print(
            f"::notice file={entry['path']},line={entry.get('line', 1)},"
            "title=zizmor baseline::Znalezisko z baseline już nie występuje — "
            "usuń wpis (zizmor_ratchet.py update)."
        )
    print(
        f"Znaleziska zizmora: {len(findings)}; z baseline: {len(covered)}; "
        f"nowe: {len(new)}; nieaktualne wpisy: {len(stale)}"
    )
    summary = [
        "### zizmor — zapadka",
        "",
        f"Znaleziska: **{len(findings)}**, z baseline: **{len(covered)}**, "
        f"**nowe: {len(new)}**, nieaktualne wpisy: {len(stale)}.",
    ]
    if new:
        summary += ["", "| Plik:linia | Audyt | Waga |", "|---|---|---|"]
        summary += [
            f"| `{f['path']}:{f['line']}` | `{f['rule']}` | {f['severity']} |" for f in new
        ]
        summary += [
            "",
            "Popraw workflow (opis audytu: https://docs.zizmor.sh/audits/) albo — gdy to "
            "świadomy wyjątek — dopisz go do `.github/zizmor-baseline.json` z uzasadnieniem: "
            "`python3 .github/scripts/zizmor_ratchet.py update --results zizmor.json "
            '--status zweryfikowane --reason "…"`.',
        ]
    _SR._summary(summary)
    if new:
        print(
            f"::error::zizmor: {len(new)} nowych znalezisk w workflowach. Popraw albo dopisz "
            "świadomy wyjątek do .github/zizmor-baseline.json z uzasadnieniem "
            "(docs/claude/podstawy/skanery-bezpieczenstwa.md)."
        )
    return 1 if new or problems else 0


def cmd_update(args: argparse.Namespace) -> int:
    findings = load_findings(Path(args.results))
    baseline_path = Path(args.baseline)
    baseline = _SR.load_baseline(baseline_path)
    new, covered, stale = _split(findings, baseline)
    if new and not args.reason.strip():
        print(f"{len(new)} nowych znalezisk — podaj --reason z uzasadnieniem.", file=sys.stderr)
        return 2
    stale_ids = {id(entry) for entry in stale}
    kept = [entry for entry in baseline.get("findings", []) if id(entry) not in stale_ids]
    for finding, entry in covered:
        entry["line"] = finding["line"]
    for finding in new:
        kept.append(
            {
                "rule": finding["rule"],
                "path": finding["path"],
                "line": finding["line"],
                "route": finding["route"],
                "fingerprint": finding["fingerprint"],
                "status": args.status,
                "reason": args.reason.strip(),
            }
        )
    kept.sort(key=lambda e: (e["path"], e["line"], e["rule"]))
    fields = ("rule", "path", "line", "route", "fingerprint", "status", "reason")
    baseline["findings"] = [{k: e[k] for k in fields if k in e} for e in kept]
    baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Baseline: {len(kept)} wpisów (nowe {len(new)}, usunięte {len(stale)}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in (("compare", cmd_compare), ("update", cmd_update)):
        p = sub.add_parser(name)
        p.add_argument("--results", required=True)
        p.add_argument("--baseline", default=DEFAULT_BASELINE)
        if name == "update":
            p.add_argument("--reason", default="")
            p.add_argument("--status", choices=STATUSES, default="do-przegladu")
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"::error title=zizmor::Nie da się odczytać wyniku zizmora: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
