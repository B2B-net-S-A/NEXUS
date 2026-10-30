"""Import umów i aneksów klientów z paczki plików i manifestu spoza repo.

Examples:

    python -m app.cli.client_contract_docs_import --manifest m.json --root pliki
    python -m app.cli.client_contract_docs_import --manifest m.json --root pliki --apply
    python -m app.cli.client_contract_docs_import --undo client_contract_docs_import_ab12

Bez ``--apply`` to próba na sucho. Odczyt treści (OCR skanów) biegnie po zapisie,
jeden dokument naraz; przerwany odczyt dokończy pierwsze pytanie o umowę.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.core.database import AsyncSessionLocal
from app.services import framework_contract_index
from app.services.client_contract_docs_import import (
    ALREADY_DONE,
    ATTACH,
    CREATE_AMENDMENT,
    CREATE_CONTRACT,
    ImportReport,
    apply_import,
    build_plan,
    load_manifest,
    undo_import,
)


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


async def _read_contents(report: ImportReport) -> None:
    """Odczyt wszystkiego, co bieg dołożył albo zastał bez aktualnego tekstu."""
    for row in report.rows:
        if row.action not in (ATTACH, CREATE_CONTRACT, CREATE_AMENDMENT, ALREADY_DONE):
            continue
        if row.amendment_id is not None:
            await framework_contract_index.index_amendment(row.amendment_id)
        elif row.kind == "contract" and row.framework_contract_id is not None:
            await framework_contract_index.index_contract(row.framework_contract_id)
        print(f"przeczytano {row.key}", file=sys.stderr, flush=True)


async def _run(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as db:
        if args.undo:
            _print(await undo_import(db, args.undo))
            return 0
        manifest, sha = load_manifest(Path(args.manifest).read_bytes())
        root = Path(args.root)
        report = (
            await apply_import(db, manifest, sha, root)
            if args.apply
            else await build_plan(db, manifest, sha, root)
        )
    if args.apply and report.applied and not args.skip_reading:
        await _read_contents(report)
    _print(
        {
            "manifest_sha256": sha,
            "applied": report.applied,
            "receipt_key": report.receipt_key,
            "counts": report.counts,
            "rows": [asdict(row) for row in report.rows],
        }
    )
    return 1 if report.blocked else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest")
    parser.add_argument("--root")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--skip-reading", action="store_true")
    parser.add_argument("--undo")
    args = parser.parse_args()
    if not args.undo and not (args.manifest and args.root):
        parser.error("podaj --manifest i --root albo --undo")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
