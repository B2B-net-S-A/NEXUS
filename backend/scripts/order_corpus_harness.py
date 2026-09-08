"""Harness korpusu zamówień: co odczyt daje na REALNYCH PDF-ach.

To jest kontrakt jakości odczytu — nie testy jednostkowe. Zielone testy
z mockami dowodzą ścieżek kodu; ten skrypt mówi, czy 19 polityk klientowych
naprawdę czyta numer, okres, stawkę i osoby z dokumentów, które system będzie
przetwarzał. Korpus i plik oczekiwań leżą POZA repo (dane osobowe).

Użycie::

    python scripts/order_corpus_harness.py ~/Downloads/zamowienia \\
        --expectations ~/Downloads/zamowienia/expectations.json \\
        [--no-llm] [--only <fragment nazwy pliku>] [--dump-text]

Tryby:
  * ``--no-llm`` — bez klucza Anthropic: rozpoznanie klienta + warstwa
    DETERMINISTYCZNA (regexy polityk na wyniku fallbacku regexowego). To jest
    dokładnie to, czemu bramka automatu ufa (proweniencja deterministyczna),
    więc ten tryb mierzy rzecz najważniejszą.
  * pełny — z ``ANTHROPIC_API_KEY``: tryb all-rows parsera + polityki.

``expectations.json``: ``{"<fragment nazwy pliku>": {"client": "<klucz>",
"title": "...", "start": "YYYY-MM-DD", "end": "...", "rate": 1234.5,
"unit": "day", "consultants": ["Nazwisko Imię", …]}}``. Brakujące klucze nie
są sprawdzane (dokument bez okresu nie ma ``start``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.order_document_text import extract_order_text  # noqa: E402
from app.services.order_client_identity import (  # noqa: E402
    ClientRegistry,
    identify_client,
)
from app.services.order_pdf_parser import parse_order_document  # noqa: E402
from app.services.order_policies import (  # noqa: E402
    PolicyContext,
    apply_policies,
    policy_by_key,
)
from app.services.order_policies.known_clients import (  # noqa: E402
    build_registry_from_known_clients,
)


def _dec(v: Any) -> Optional[Decimal]:
    return None if v is None else Decimal(str(v))


def _mark(ok: Optional[bool]) -> str:
    return "  " if ok is None else ("✓ " if ok else "✗ ")


async def run_one(
    path: Path,
    registry: ClientRegistry,
    *,
    use_llm: bool,
    dump_text: bool,
) -> dict[str, Any]:
    doc = extract_order_text(str(path), path.name)
    text = doc.text
    if dump_text:
        print("─" * 80, path.name, "─" * 80)
        print(text[:6000])
    ident = identify_client(text, registry)
    row: dict[str, Any] = {
        "file": path.name,
        "chars": len(text),
        "reextracted": doc.reextracted_with,
        "ocr_capped": doc.ocr_capped,
        "client": ident.client_key,
        "method": ident.method,
        "registry_ids": list(ident.registry_ids_found),
        "candidates": list(ident.candidates),
    }
    if use_llm:
        extraction = await parse_order_document(text, all_rows=True)
    else:
        # Warstwa deterministyczna na fallbacku regexowym — bez modelu.
        os.environ.pop("ANTHROPIC_API_KEY", None)
        extraction = await parse_order_document(text)
    policies = []
    if ident.client_key:
        try:
            policies = [policy_by_key(ident.client_key)]
        except KeyError:
            policies = []
    extraction, applied = apply_policies(
        extraction, PolicyContext(document_text=text, filename=path.name), policies
    )
    # Bez modelu wiersze osób mogą pochodzić wyłącznie z deterministycznego
    # ekstraktora polityki — to jest ten sam mechanizm, którym bramka automatu
    # weryfikuje wiersze modelu.
    if not extraction.consultant_rows:
        for policy in policies:
            rows_fn = getattr(policy, "extract_rows", None)
            if rows_fn is not None:
                extraction.consultant_rows = rows_fn(text)
                break
    row.update(
        {
            "policy": " + ".join(applied) or None,
            "source": extraction.source,
            "title": extraction.title,
            "start": extraction.start_date,
            "end": extraction.end_date,
            "rate": str(extraction.rate_client)
            if extraction.rate_client is not None
            else None,
            "unit": extraction.rate_unit,
            "md_total": str(extraction.md_total)
            if extraction.md_total is not None
            else None,
            "rows": [
                {
                    "name": r.consultant_name,
                    "start": r.start_date,
                    "end": r.end_date,
                    "rate": str(r.rate_client) if r.rate_client is not None else None,
                    "unit": r.rate_unit,
                    "md": str(r.md_total) if r.md_total is not None else None,
                    "uncertain": r.uncertain,
                }
                for r in extraction.consultant_rows
            ],
            "uncertain": extraction.uncertain,
            "reasons": extraction.uncertain_reasons,
            "truncated": extraction.document_truncated,
        }
    )
    return row


def _score(row: dict[str, Any], exp: dict[str, Any]) -> dict[str, Optional[bool]]:
    s: dict[str, Optional[bool]] = {}
    if "client" in exp:
        s["client"] = row["client"] == exp["client"]
    if "title" in exp:
        s["title"] = row["title"] == exp["title"]
    if "start" in exp:
        s["start"] = row["start"] == exp["start"]
    if "end" in exp:
        s["end"] = row["end"] == exp["end"]
    if "rate" in exp:
        s["rate"] = _dec(row["rate"]) == _dec(exp["rate"])
    if "unit" in exp:
        s["unit"] = row["unit"] == exp["unit"]
    if "consultants" in exp:
        got = {r["name"] for r in row["rows"]}
        want = set(exp["consultants"])
        s["consultants"] = got == want
    return s


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_dir")
    ap.add_argument("--expectations")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--dump-text", action="store_true")
    ap.add_argument("--json", help="zapisz surowe wyniki do pliku")
    args = ap.parse_args()

    corpus = Path(args.corpus_dir).expanduser()
    expectations: dict[str, dict[str, Any]] = {}
    if args.expectations:
        expectations = json.loads(
            Path(args.expectations).expanduser().read_text("utf-8")
        )

    use_llm = not args.no_llm and bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not args.no_llm and not use_llm:
        print("!! brak ANTHROPIC_API_KEY — przełączam na --no-llm", file=sys.stderr)

    registry = build_registry_from_known_clients()
    files = sorted(
        p for p in corpus.glob("*.pdf") if not args.only or args.only in p.name
    )
    results: list[dict[str, Any]] = []
    totals: dict[str, list[int]] = {}
    for path in files:
        row = await run_one(path, registry, use_llm=use_llm, dump_text=args.dump_text)
        exp = next((v for k, v in expectations.items() if k in path.name), {})
        score = _score(row, exp) if exp else {}
        row["score"] = score
        results.append(row)
        for k, ok in score.items():
            t = totals.setdefault(k, [0, 0])
            t[1] += 1
            t[0] += int(bool(ok))
        print(
            f"{path.name[:58]:<58} "
            f"{_mark(score.get('client'))}{(row['client'] or '—'):<16} "
            f"{(row['method'] or '—'):<12} "
            f"{_mark(score.get('title'))}{(row['title'] or '—')[:26]:<26} "
            f"{_mark(score.get('start'))}{(row['start'] or '—'):<10} "
            f"{_mark(score.get('end'))}{(row['end'] or '—'):<10} "
            f"{_mark(score.get('rate'))}{(row['rate'] or '—'):<9} "
            f"{(row['unit'] or '—'):<5} "
            f"rows={len(row['rows'])}{_mark(score.get('consultants')).strip()}"
        )
    print()
    for k, (ok, n) in sorted(totals.items()):
        print(f"{k:<12} {ok}/{n}")
    if args.json:
        Path(args.json).expanduser().write_text(
            json.dumps(results, ensure_ascii=False, indent=1, default=str), "utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
