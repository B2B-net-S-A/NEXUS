#!/usr/bin/env python3
"""DEP-01 (audyt 14.09.2026): wydanie obok SHA faktycznie serwowanego.

Od 15.09.2026 deploy rusza tylko przy zielonej bramce HEAD maina (RELEASE_SHA),
a smoke przyjmuje RELEASE_SHA albo jego potomka z zieloną bramką
(ACCEPTED_SHA). Ten skrypt WYŁĄCZNIE renderuje: tabelę do
``$GITHUB_STEP_SUMMARY`` i jedną linię ``::notice::`` do logu. Nie zmienia
wyniku joba (zawsze kod 0) i nie woła sieci.

Werdykty (względem ACCEPTED_SHA, a bez niego RELEASE_SHA):

* ``match``    — produkcja serwuje dokładnie przyjętą wersję;
* ``mismatch`` — inny SHA: build nie wstał albo ktoś wdrożył coś innego;
* ``missing``  — brak czytelnego odczytu (pusta wersja, ``unknown``, za krótka).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NamedTuple, Optional

SHORT = 7
_NO_VALUE = {"", "missing", "unknown", "null", "none", "n/a"}

LABELS = {
    "match": "zgodny z wydaniem",
    "mismatch": "ROZJAZD — produkcja serwuje inny commit niż przyjęta wersja",
    "missing": "brak odczytu wersji",
}


class Verdict(NamedTuple):
    release: str
    live: str
    kind: str

    @property
    def label(self) -> str:
        return LABELS[self.kind]

    @property
    def live_short(self) -> str:
        return self.live[:SHORT] if self.kind != "missing" else "—"


def _clean(value: Optional[str]) -> str:
    return (value or "").strip()


def classify(release: str, live: Optional[str]) -> Verdict:
    """Porównaj SHA z produkcji z wydaniem (pełny SHA albo prefiks ≥ 7 znaków)."""
    release = _clean(release)
    live_v = _clean(live)
    if live_v.lower() in _NO_VALUE or len(live_v) < SHORT:
        return Verdict(release, live_v, "missing")
    if release and release.startswith(live_v):
        return Verdict(release, live_v, "match")
    return Verdict(release, live_v, "mismatch")


def render_summary(
    target: str,
    release: str,
    rows: dict[str, Verdict],
    rebuild_skipped: bool,
    accepted: str = "",
) -> str:
    target_short = _clean(target)[:SHORT] or "?"
    release_short = _clean(release)[:SHORT] or "?"
    lines = [
        f"### Wersje po deployu — wydanie `{release_short}` (target `{target_short}`)",
        "",
        "| Cel | Wydanie | Na produkcji | Werdykt |",
        "|---|---|---|---|",
    ]
    for name, verdict in rows.items():
        lines.append(
            f"| {name} | `{release_short}` | `{verdict.live_short}` | {verdict.label} |"
        )
    lines.append("")
    if _clean(release) and _clean(release) != _clean(target):
        lines.append(
            "Wydanie jest nowsze niż target: HEAD maina z zieloną bramką CI Gate, "
            "który zawiera target (koalescencja burstów)."
        )
    if _clean(accepted) and _clean(accepted) != _clean(release):
        lines.append(
            f"Smoke przyjął `{_clean(accepted)[:SHORT]}` — potomka wydania z zieloną "
            "bramką (merge w trakcie budowy w Coolify)."
        )
    if rebuild_skipped:
        lines.append(
            "Rebuild w Coolify **pominięty**: produkcja serwowała już to wydanie przed tym biegiem."
        )
    else:
        lines.append("Rebuild w Coolify wykonany w tym biegu.")
    if any(v.kind == "mismatch" for v in rows.values()):
        lines.append(
            "Rozjazd: produkcja serwuje commit inny niż przyjęta wersja — sprawdź log "
            "builda w Coolify, ręczny redeploy albo rollback."
        )
    return "\n".join(lines) + "\n"


def render_notice(release: str, rows: dict[str, Verdict], rebuild_skipped: bool) -> str:
    """Jedna linia ``::notice::`` (workflow command musi być jednoliniowy)."""
    release_short = _clean(release)[:SHORT] or "?"
    parts = [
        f"{name.split(' ', 1)[0]}={verdict.live_short} ({verdict.label})"
        for name, verdict in rows.items()
    ]
    tail = "; rebuild pominięty" if rebuild_skipped else ""
    body = f"Wydanie {release_short}: " + ", ".join(parts) + tail
    return "::notice title=Wersje po deployu::" + body.replace("\n", " ")


def build_rows(args: argparse.Namespace) -> dict[str, Verdict]:
    rows = {"backend (/api/health)": classify(args.release, args.backend_live)}
    if _clean(args.frontend_live):
        rows["frontend (version.json)"] = classify(args.release, args.frontend_live)
    return rows


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", required=True, help="TARGET_SHA deployu")
    parser.add_argument(
        "--release", default="", help="RELEASE_SHA (puste = wybór wydania padł)"
    )
    parser.add_argument("--backend-live", default="", help="version z /api/health")
    parser.add_argument("--frontend-live", default="", help="sha z version.json")
    parser.add_argument(
        "--accepted", default="", help="ACCEPTED_SHA przyjęty przez smoke (puste = brak)"
    )
    parser.add_argument(
        "--rebuild-skipped", default="false", help="true, gdy precheck pominął rebuild"
    )
    parser.add_argument("--summary-out", required=True, type=Path)
    parser.add_argument("--notice-out", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    skipped = _clean(args.rebuild_skipped).lower() == "true"
    release = _clean(args.release) or _clean(args.target)
    accepted = _clean(args.accepted)
    args.release = accepted or release
    rows = build_rows(args)
    args.summary_out.write_text(
        render_summary(args.target, release, rows, skipped, accepted),
        encoding="utf-8",
    )
    args.notice_out.write_text(
        render_notice(release, rows, skipped) + "\n", encoding="utf-8"
    )
    for name, verdict in rows.items():
        print(f"{name}: wydanie={release[:SHORT]} live={verdict.live_short} → {verdict.label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
