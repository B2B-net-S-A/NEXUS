#!/usr/bin/env python3
"""Raport przerwy widzianej przez użytkowników w trakcie deployu (F03).

Sonda w ``deploy.yml`` co ~2 s zapisuje linie CSV ``epoka_s,cel,kod_http``
dla frontendu (``/login``) i API (``/api/health/live``). Ten skrypt WYŁĄCZNIE
renderuje wynik: tabelę do ``$GITHUB_STEP_SUMMARY`` i linie ``::notice::``.
Nie woła sieci i zawsze kończy się kodem 0 — pomiar nie może zmienić wyniku
deployu.

Do 15.09.2026 raport był wklejony w workflow i podawał w logu tylko MAKSIMUM
z obu celów, więc nie dało się odróżnić przerwy frontendu od przerwy API.
Plan skracania przerwy (Etap 0) potrzebuje obu liczb osobno oraz odpowiedzi,
czy Coolify odtworzył przy deployu kontener Postgresa (zmiana
``pg_postmaster_start_time()`` odczytanego z ``/api/health/deep`` przed
webhookiem i po smoke teście).
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

TARGETS = ("frontend", "api")
_NO_VALUE = {"", "null", "none", "missing", "unknown"}


@dataclass(frozen=True)
class TargetResult:
    target: str
    samples: int
    bad_samples: int
    longest_seconds: int
    longest_from: int | None
    longest_to: int | None
    bad_codes: tuple[str, ...]


def load_samples(path: Path) -> dict[str, list[tuple[int, str]]]:
    rows: dict[str, list[tuple[int, str]]] = defaultdict(list)
    with path.open(encoding="utf-8") as fh:
        for record in csv.reader(fh):
            if len(record) != 3:
                continue  # ucięta linia przy zatrzymaniu sondy
            ts, target, code = record
            try:
                rows[target].append((int(ts), code.strip()))
            except ValueError:
                continue
    return rows


def outages(samples: list[tuple[int, str]]) -> list[tuple[int, int]]:
    """(start, koniec) każdej ciągłej serii bez 200; koniec = pierwsza dobra próbka."""
    ordered = sorted(samples)
    found: list[tuple[int, int]] = []
    start: int | None = None
    for ts, code in ordered:
        if code != "200" and start is None:
            start = ts
        elif code == "200" and start is not None:
            found.append((start, ts))
            start = None
    if start is not None:
        found.append((start, ordered[-1][0]))
    return found


def summarize(target: str, samples: list[tuple[int, str]]) -> TargetResult:
    runs = outages(samples)
    longest = max(runs, key=lambda r: r[1] - r[0], default=None)
    return TargetResult(
        target=target,
        samples=len(samples),
        bad_samples=sum(1 for _, code in samples if code != "200"),
        longest_seconds=(longest[1] - longest[0]) if longest else 0,
        longest_from=longest[0] if longest else None,
        longest_to=longest[1] if longest else None,
        bad_codes=tuple(sorted({code for _, code in samples if code != "200"})),
    )


def postgres_restart(before: str | None, after: str | None) -> str:
    """``restarted`` / ``same`` / ``unknown`` — porównanie czasu startu Postgresa."""
    b = (before or "").strip()
    a = (after or "").strip()
    if b.lower() in _NO_VALUE or a.lower() in _NO_VALUE:
        return "unknown"
    return "same" if a == b else "restarted"


POSTGRES_LABELS = {
    "restarted": "TAK — kontener bazy odtworzony w tym deployu",
    "same": "nie",
    "unknown": "nieznane (brak odczytu przed albo po deployu)",
}


def _fmt(ts: int | None) -> str:
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M:%S UTC")


def render_summary(
    target_sha: str, results: list[TargetResult], postgres: str
) -> str:
    lines = [
        f"### Przerwa widziana przez użytkowników — deploy `{target_sha[:8]}`",
        "",
        "| Cel | Próbki | Bez 200 | Najdłuższa przerwa | Od | Do | Kody |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.target} | {r.samples} | {r.bad_samples} | {r.longest_seconds} s "
            f"| {_fmt(r.longest_from)} | {_fmt(r.longest_to)} "
            f"| {', '.join(r.bad_codes) or '—'} |"
        )
    lines += [
        "",
        f"Postgres restartował: **{POSTGRES_LABELS[postgres]}**.",
        "",
        "Próbki co ~2 s z runnera GitHub. Długość przerwy liczona od pierwszej "
        "złej do pierwszej dobrej próbki — przybliżenie, nie pomiar ciągły.",
    ]
    return "\n".join(lines) + "\n"


def render_notices(results: list[TargetResult], postgres: str) -> list[str]:
    """Linie ``::notice::`` (każda jednoliniowa). Pierwsza zachowuje dawny tekst."""
    worst = max((r.longest_seconds for r in results), default=0)
    notices = [
        "::notice::Najdłuższa przerwa widziana przez użytkowników w tym deployu: "
        f"{worst} s (szczegóły w podsumowaniu biegu)."
    ]
    for r in results:
        codes = ", ".join(r.bad_codes) or "—"
        notices.append(
            f"::notice title=Przerwa {r.target}::{r.target}: {r.longest_seconds} s "
            f"(próbki bez 200: {r.bad_samples}/{r.samples}, kody: {codes})"
        )
    notices.append(f"::notice title=Postgres::Postgres restartował: {POSTGRES_LABELS[postgres]}")
    return notices


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", required=True, type=Path)
    parser.add_argument("--target", required=True, help="TARGET_SHA deployu")
    parser.add_argument("--postgres-before", default="")
    parser.add_argument("--postgres-after", default="")
    parser.add_argument("--summary-out", required=True, type=Path)
    parser.add_argument("--notice-out", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = load_samples(args.samples)
    results = [summarize(t, rows.get(t, [])) for t in TARGETS]
    postgres = postgres_restart(args.postgres_before, args.postgres_after)
    args.summary_out.write_text(
        render_summary(args.target, results, postgres), encoding="utf-8"
    )
    args.notice_out.write_text(
        "\n".join(render_notices(results, postgres)) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
