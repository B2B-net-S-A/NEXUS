#!/usr/bin/env python3
"""DEP-01 (audyt Codexa, 14.09.2026): TARGET_SHA obok SHA faktycznie serwowanego.

Koalescencja burstów w ``deploy.yml`` jest decyzją (CLAUDE.md, „CI gotchas”):
Coolify klonuje HEAD maina w chwili budowy, więc deploy dla commitu N potrafi
zastać na produkcji N+1 — i to jest sukces, nie awaria. Ale bez śladu w
podsumowaniu biegu nie da się po fakcie odczytać, CO naprawdę wylądowało po
TYM deployu. Ten skrypt WYŁĄCZNIE renderuje: tabelę do ``$GITHUB_STEP_SUMMARY``
i jedną linię ``::notice::`` do logu. Nie zmienia wyniku joba (zawsze kod 0),
nie woła sieci — pokrewieństwo SHA liczy krok w workflow (GitHub compare API)
i podaje je tu jako tekst (``identical`` / ``ahead`` / ``behind`` / …).

Werdykty:

* ``match``      — produkcja serwuje dokładnie TARGET_SHA;
* ``descendant`` — produkcja serwuje POTOMKA TARGET_SHA: koalescencja burstów;
* ``mismatch``   — inny SHA, który nie jest potomkiem (``behind``/``diverged``/
  nieznane pokrewieństwo) — rozjazd do obejrzenia;
* ``missing``    — brak czytelnego odczytu (pusta wersja, ``unknown``, za krótka).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

SHORT = 7
_NO_VALUE = {"", "missing", "unknown", "null", "none", "n/a"}

LABELS = {
    "match": "zgodny z targetem",
    "descendant": "koalescencja burstów — produkcja serwuje potomka targetu",
    "mismatch": "ROZJAZD — SHA nie jest potomkiem targetu",
    "missing": "brak odczytu wersji",
}


@dataclass(frozen=True)
class Verdict:
    target: str
    live: str
    relation: str
    kind: str

    @property
    def label(self) -> str:
        label = LABELS[self.kind]
        if self.kind == "mismatch" and self.relation not in _NO_VALUE:
            label += f" (pokrewieństwo={self.relation})"
        return label

    @property
    def live_short(self) -> str:
        return self.live[:SHORT] if self.kind != "missing" else "—"


def _clean(value: str | None) -> str:
    return (value or "").strip()


def classify(target: str, live: str | None, relation: str | None) -> Verdict:
    """Zaklasyfikuj SHA z produkcji względem targetu.

    ``relation`` to pole ``status`` z GitHub compare ``target...live``: ``identical``
    (ten sam commit), ``ahead`` (live jest POTOMKIEM targetu), ``behind``,
    ``diverged`` albo dowolny tekst, gdy porównanie się nie udało.
    """
    target = _clean(target)
    live_v = _clean(live)
    rel = _clean(relation).lower()
    if live_v.lower() in _NO_VALUE or len(live_v) < SHORT:
        return Verdict(target, live_v, rel, "missing")
    if live_v[:SHORT] == target[:SHORT] or rel == "identical":
        return Verdict(target, live_v, rel, "match")
    if rel == "ahead":
        return Verdict(target, live_v, rel, "descendant")
    return Verdict(target, live_v, rel, "mismatch")


def render_summary(target: str, rows: dict[str, Verdict], rebuild_skipped: bool) -> str:
    """Markdown do podsumowania biegu: tabela cel × oczekiwany × serwowany × werdykt."""
    target_short = _clean(target)[:SHORT] or "?"
    lines = [
        f"### Wersje po deployu — target `{target_short}`",
        "",
        "| Cel | Oczekiwany | Na produkcji | Werdykt |",
        "|---|---|---|---|",
    ]
    for name, verdict in rows.items():
        lines.append(
            f"| {name} | `{target_short}` | `{verdict.live_short}` | {verdict.label} |"
        )
    lines.append("")
    if rebuild_skipped:
        lines.append(
            "Rebuild w Coolify **pominięty** (koalescencja burstów): produkcja serwowała "
            "już target albo jego potomka przed tym biegiem."
        )
    else:
        lines.append("Rebuild w Coolify wykonany w tym biegu.")
    if any(v.kind == "descendant" for v in rows.values()):
        lines.append(
            "Potomek targetu = nasz commit jest wdrożony razem z nowszymi merge'ami "
            "(Coolify klonuje HEAD maina) — to zamierzone zachowanie, nie błąd."
        )
    if any(v.kind == "mismatch" for v in rows.values()):
        lines.append(
            "Rozjazd: produkcja serwuje SHA, który NIE zawiera targetu — sprawdź, "
            "czy deploy nie został wyprzedzony przez rollback albo ręczny redeploy."
        )
    return "\n".join(lines) + "\n"


def render_notice(target: str, rows: dict[str, Verdict], rebuild_skipped: bool) -> str:
    """Jedna linia ``::notice::`` (workflow command musi być jednoliniowy)."""
    target_short = _clean(target)[:SHORT] or "?"
    # W jednej linii logu wystarczy `backend=…`/`frontend=…`; pełna nazwa
    # źródła (`/api/health`, `version.json`) jest w tabeli podsumowania.
    parts = [
        f"{name.split(' ', 1)[0]}={verdict.live_short} ({verdict.label})"
        for name, verdict in rows.items()
    ]
    tail = "; rebuild pominięty (koalescencja burstów)" if rebuild_skipped else ""
    body = f"Deploy target {target_short}: " + ", ".join(parts) + tail
    return "::notice title=Wersje po deployu::" + body.replace("\n", " ")


def build_rows(args: argparse.Namespace) -> dict[str, Verdict]:
    rows = {
        "backend (/api/health)": classify(
            args.target, args.backend_live, args.backend_relation
        )
    }
    if _clean(args.frontend_live) or _clean(args.frontend_relation):
        rows["frontend (version.json)"] = classify(
            args.target, args.frontend_live, args.frontend_relation
        )
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", required=True, help="TARGET_SHA deployu")
    parser.add_argument("--backend-live", default="", help="version z /api/health")
    parser.add_argument(
        "--backend-relation", default="", help="status compare target...live"
    )
    parser.add_argument(
        "--frontend-live", default="", help="sha z version.json frontendu"
    )
    parser.add_argument(
        "--frontend-relation", default="", help="status compare target...live"
    )
    parser.add_argument(
        "--rebuild-skipped", default="false", help="true, gdy precheck pominął rebuild"
    )
    parser.add_argument(
        "--summary-out", required=True, type=Path, help="plik na markdown"
    )
    parser.add_argument(
        "--notice-out", required=True, type=Path, help="plik na linię ::notice::"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    skipped = _clean(args.rebuild_skipped).lower() == "true"
    rows = build_rows(args)
    args.summary_out.write_text(
        render_summary(args.target, rows, skipped), encoding="utf-8"
    )
    args.notice_out.write_text(
        render_notice(args.target, rows, skipped) + "\n", encoding="utf-8"
    )
    # Log jest jedynym miejscem, gdzie werdykt widać bez otwierania podsumowania.
    for name, verdict in rows.items():
        print(
            f"{name}: target={_clean(args.target)[:SHORT]} live={verdict.live_short} → {verdict.label}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
