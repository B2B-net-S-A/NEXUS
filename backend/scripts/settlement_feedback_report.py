#!/usr/bin/env python3
"""Odczyt informacji zwrotnej o wadach rozliczenia: wady, komunikaty, adresaci.

Po co: powtórka próby rozliczeń na kopii produkcji liczy, ile komunikatów
wysłałby (tryb ``dry_run``) albo wysłał NEXUS przy każdym przypadku
(kontrakt × miesiąc) i do kogo. Czyta tabelę ``client_settlement_feedback``
(``services/client_settlements/feedback.report``), niczego nie zapisuje.

Użycie (w kontenerze backendu z ``DATABASE_URL`` kopii)::

    python -m scripts.settlement_feedback_report --months 2026-09,2026-10
    python -m scripts.settlement_feedback_report --months 2026-10 --json > wynik.json

Domyślnie bez imion, nazwisk i adresów (kontrakt, klient, kod, adresat
z rodzajem). ``--names`` dokłada osobę i adres — tylko terminal na laptopie,
nigdy repo ani logi Actions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

MONTH = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


def months_arg(raw: str) -> list[str]:
    months = [part.strip() for part in raw.split(",") if part.strip()]
    bad = [m for m in months if not MONTH.match(m)]
    if not months or bad:
        raise argparse.ArgumentTypeError(f"miesiące RRRR-MM po przecinku, nie {bad}")
    return months


def _private(row: dict[str, Any]) -> dict[str, Any]:
    """Wiersz bez osoby, adresów i treści (do wklejenia w notatkę próby)."""

    return {
        **{k: v for k, v in row.items() if k not in ("person", "sends")},
        "sends": [
            {
                k: v
                for k, v in entry.items()
                if k not in ("address", "cc", "subject", "text")
            }
            for entry in row["sends"]
        ],
    }


def lines(rows: list[dict[str, Any]], *, names: bool) -> list[str]:
    out = [
        "miesiąc\tklient\tkontrakt\twada\tpoprawia\tpierwsze\tpoprawione\t"
        "komunikaty\tostatni: komu (dlaczego) · wynik"
        + ("\tosoba\tadres" if names else "")
    ]
    for row in rows:
        last = row["sends"][-1] if row["sends"] else {}
        route = (
            f"{last.get('on')} {last.get('to')}"
            + (f" ({last['why']})" if last.get("why") else "")
            + f" · {last.get('outcome')}"
            if last
            else "—"
        )
        cells = [
            row["month"],
            row["client_name"] or "—",
            str(row["contract_id"]),
            row["code"],
            row["audience"],
            row["first_seen_on"],
            row["resolved_on"] or "—",
            str(len(row["sends"])),
            route,
        ]
        if names:
            cells += [row["person"] or "—", (last.get("address") or "—")]
        out.append("\t".join(cells))
    return out


async def _run(args: argparse.Namespace) -> int:
    from app.core.database import AsyncSessionLocal
    from app.services.client_settlements import feedback

    async with AsyncSessionLocal() as db:
        rows = await feedback.report(
            db, args.months, client_id=args.client_id, open_only=args.open_only
        )
    summary = feedback.summarize(rows)
    if args.json:
        shown = rows if args.names else [_private(r) for r in rows]
        print(json.dumps({"summary": summary, "rows": shown}, ensure_ascii=False))
        return 0
    for line in lines(rows, names=args.names):
        print(line)
    print()
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--months", type=months_arg, required=True)
    parser.add_argument("--client-id", type=int)
    parser.add_argument("--open-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--names", action="store_true")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
