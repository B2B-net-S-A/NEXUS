#!/usr/bin/env python3
"""Zapadka audytu zależności: znane podatności z baseline przechodzą, nowe czerwienią.

    dependency_audit.py python --report pip-audit.json [--baseline …]
    dependency_audit.py npm    --report npm-audit.json [--baseline …] [--min-severity high]

`python` czyta `pip-audit -f json` (każda podatność się liczy — pip-audit nie
podaje wagi), `npm` czyta `npm audit --json` (v7+) i liczy porady o wadze
co najmniej `--min-severity` (domyślnie high, jak `--audit-level=high`).

Wyjątek w `.github/dependency-audit-baseline.json` pasuje po identyfikatorze
albo aliasie (PYSEC/GHSA/CVE) i ma termin `expires` (RRRR-MM-DD). Po terminie
znów czerwieni: wyjątek bez daty zostałby na zawsze, jak kiedyś `.trivyignore`
przed QA-05. Wpis, którego podatność już nie występuje, daje notkę do usunięcia.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_BASELINE = ".github/dependency-audit-baseline.json"
SEVERITY = {"info": 0, "low": 1, "moderate": 2, "high": 3, "critical": 4}
_GHSA = re.compile(r"GHSA(-[0-9a-z]{4}){3}", re.IGNORECASE)


def company_today() -> date:
    return datetime.now(ZoneInfo("Europe/Warsaw")).date()


def python_vulns(report: dict) -> list[dict]:
    vulns = []
    for dep in report.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            vulns.append(
                {
                    "id": vuln["id"],
                    "ids": {vuln["id"], *vuln.get("aliases", [])},
                    "package": f"{dep['name']}=={dep.get('version', '?')}",
                    "detail": "poprawka: " + (", ".join(vuln.get("fix_versions") or []) or "brak"),
                }
            )
    return vulns


def npm_vulns(report: dict, min_severity: str) -> list[dict]:
    if "error" in report:
        raise ValueError(f"npm audit zwrócił błąd: {report['error']}")
    floor = SEVERITY[min_severity]
    found: dict[str, dict] = {}
    for name, entry in report.get("vulnerabilities", {}).items():
        for via in entry.get("via", []):
            if not isinstance(via, dict):
                continue  # łańcuch zależności — porada jest opisana przy pakiecie źródłowym
            if SEVERITY.get(str(via.get("severity")), 0) < floor:
                continue
            match = _GHSA.search(str(via.get("url", "")))
            ident = match.group(0) if match else f"npm-{via.get('source')}"
            found.setdefault(
                ident,
                {
                    "id": ident,
                    "ids": {ident},
                    "package": f"{via.get('name', name)} {via.get('range', '')}".strip(),
                    "detail": f"{via.get('severity')}: {via.get('title', '')}",
                },
            )
    return list(found.values())


def check(vulns: list[dict], entries: list[dict], today: date) -> tuple[list[str], list[str]]:
    """(błędy, notki)."""
    errors, notes = [], []
    used = set()
    for vuln in sorted(vulns, key=lambda v: v["id"]):
        entry = next(
            (
                (index, e)
                for index, e in enumerate(entries)
                if vuln["ids"] & {e.get("id"), *e.get("aliases", [])}
            ),
            None,
        )
        if entry is None:
            errors.append(
                f"Nowa podatność {vuln['id']} w {vuln['package']} ({vuln['detail']}). "
                "Podbij wersję albo dopisz świadomy wyjątek z uzasadnieniem i terminem "
                f"do {DEFAULT_BASELINE}."
            )
            continue
        index, matched = entry
        used.add(index)
        expires = str(matched.get("expires", ""))
        try:
            expired = date.fromisoformat(expires) < today
        except ValueError:
            errors.append(f"Wyjątek {matched.get('id')}: brak albo zły termin expires ({expires!r}).")
            continue
        if expired:
            errors.append(
                f"Wyjątek {matched.get('id')} ({vuln['package']}) wygasł {expires} — "
                "przejrzyj ponownie: podbij wersję albo przedłuż termin z nowym uzasadnieniem."
            )
    for index, entry in enumerate(entries):
        if not str(entry.get("reason", "")).strip():
            errors.append(f"Wyjątek {entry.get('id')}: brak uzasadnienia (pole reason).")
        if index not in used:
            notes.append(f"Wyjątek {entry.get('id')} już nie występuje — usuń go z {DEFAULT_BASELINE}.")
    return errors, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ecosystem", choices=("python", "npm"))
    parser.add_argument("--report", required=True)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--min-severity", choices=tuple(SEVERITY), default="high")
    args = parser.parse_args(argv)

    try:
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
        vulns = (
            python_vulns(report)
            if args.ecosystem == "python"
            else npm_vulns(report, args.min_severity)
        )
    except (OSError, ValueError, KeyError) as exc:
        # Brak raportu albo zły format = czerwień: cichy pass to skaner, który nie działa.
        print(f"::error title=Audyt zależności ({args.ecosystem})::Nie da się odczytać raportu: {exc}")
        return 1
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    errors, notes = check(vulns, baseline.get(args.ecosystem, []), company_today())

    for message in errors:
        print(f"::error title=Audyt zależności ({args.ecosystem})::{message}")
    for message in notes:
        print(f"::notice title=Audyt zależności ({args.ecosystem})::{message}")
    print(f"{args.ecosystem}: podatności {len(vulns)}, błędy {len(errors)}, notki {len(notes)}")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(f"### Audyt zależności — {args.ecosystem}\n\n")
            handle.write(f"Podatności w raporcie: **{len(vulns)}**, błędy: **{len(errors)}**.\n\n")
            for message in errors:
                handle.write(f"- ❌ {message}\n")
            for message in notes:
                handle.write(f"- ℹ️ {message}\n")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
