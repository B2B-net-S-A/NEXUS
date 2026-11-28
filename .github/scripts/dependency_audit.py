#!/usr/bin/env python3
"""Zapadka audytu zależności: znane podatności z baseline przechodzą, nowe czerwienią.

    dependency_audit.py python --report pip-audit.json [--baseline …]
    dependency_audit.py npm    --report npm-audit.json [--baseline …] [--min-severity high]
    … [--dojo-output raport-do-defectdojo.json]

`python` czyta `pip-audit -f json` (każda podatność się liczy — pip-audit nie
podaje wagi), `npm` czyta `npm audit --json` (v7+) i liczy porady o wadze
co najmniej `--min-severity` (domyślnie high, jak `--audit-level=high`).

Wyjątek w `.github/dependency-audit-baseline.json` pasuje po identyfikatorze
albo aliasie (PYSEC/GHSA/CVE) i ma termin `expires` (RRRR-MM-DD). Po terminie
znów czerwieni: wyjątek bez daty zostałby na zawsze, jak kiedyś `.trivyignore`
przed QA-05. Wpis, którego podatność już nie występuje (w żadnej wadze), daje
notkę do usunięcia.

`--dojo-output` zapisuje raport w tym samym formacie bez podatności z ważnym
wyjątkiem (a w npm także bez pakietów, które są w raporcie tylko przez nie) —
to idzie do DefectDojo i na ekran Ustawienia → Bezpieczeństwo. Wagi poniżej
progu zapadki zostają w raporcie: tam są do przeglądu, nie blokują.
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


def _active_exception_ids(entries: list[dict], today: date) -> set[str]:
    ids: set[str] = set()
    for entry in entries:
        try:
            if date.fromisoformat(str(entry.get("expires", ""))) < today:
                continue
        except ValueError:
            continue
        if str(entry.get("reason", "")).strip():
            ids |= {entry.get("id"), *entry.get("aliases", [])} - {None}
    return ids


def dojo_report(ecosystem: str, report: dict, entries: list[dict], today: date) -> tuple[dict, int]:
    """(raport bez podatności z ważnym wyjątkiem, liczba pominiętych porad)."""
    excepted = _active_exception_ids(entries, today)
    out = json.loads(json.dumps(report))
    skipped = 0
    if ecosystem == "python":
        for dep in out.get("dependencies", []):
            kept = [v for v in dep.get("vulns", []) if not ({v["id"], *v.get("aliases", [])} & excepted)]
            skipped += len(dep.get("vulns", [])) - len(kept)
            dep["vulns"] = kept
        return out, skipped
    vulnerabilities = out.get("vulnerabilities", {})
    for entry in vulnerabilities.values():
        kept = []
        for via in entry.get("via", []):
            match = _GHSA.search(str(via.get("url", ""))) if isinstance(via, dict) else None
            if match and match.group(0) in excepted:
                skipped += 1
                continue
            kept.append(via)
        entry["via"] = kept
    # Pakiet na liście tylko przez łańcuch do usuniętej porady znika razem z nią.
    changed = True
    while changed:
        changed = False
        for name in list(vulnerabilities):
            via = [v for v in vulnerabilities[name].get("via", []) if not isinstance(v, str) or v in vulnerabilities]
            if len(via) != len(vulnerabilities[name].get("via", [])):
                vulnerabilities[name]["via"] = via
                changed = True
            if not via:
                del vulnerabilities[name]
                changed = True
    return out, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ecosystem", choices=("python", "npm"))
    parser.add_argument("--report", required=True)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--min-severity", choices=tuple(SEVERITY), default="high")
    parser.add_argument("--dojo-output", default="")
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
    entries = baseline.get(args.ecosystem, [])
    today = company_today()
    errors, notes = check(vulns, entries, today)
    if args.ecosystem == "npm":
        # Wyjątek dla porady poniżej progu (np. moderate pod bramką high)
        # jest używany przez raport do DefectDojo — to nie „już nie występuje”.
        present = set().union(*(v["ids"] for v in npm_vulns(report, "info")))
        unused = {e.get("id") for e in entries if not ({e.get("id"), *e.get("aliases", [])} & present)}
        notes = [n for n in notes if any(f"Wyjątek {ident} " in n for ident in unused)]
    if args.dojo_output:
        dojo, skipped = dojo_report(args.ecosystem, report, entries, today)
        Path(args.dojo_output).write_text(json.dumps(dojo, ensure_ascii=False), encoding="utf-8")
        print(f"{args.ecosystem}: raport do DefectDojo bez {skipped} porad z ważnym wyjątkiem")

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
