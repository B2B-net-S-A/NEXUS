"""Zasilenie treści istniejących dokumentów kontraktu (0788, asystent prawny E).

Nowy plik czyta się sam po wgraniu, a każdy inny przy pierwszym pytaniu
(``contract_document_text.index.ensure_indexed``). Ten skrypt nadrabia
dokumenty sprzed 0788 z góry, żeby pierwsze pytanie nie czekało na OCR.

Wznowienie: dokument z aktualnym stanem odczytu odpada z zakresu, więc
przerwany bieg wystarczy uruchomić ponownie (albo z ``--after-id``).
Bez pętli w tle — jeden bieg, dokument po dokumencie, każdy we własnej
transakcji.

    python -m scripts.backfill_contract_document_text --dry-run
    python -m scripts.backfill_contract_document_text --commit --limit 20
    python -m scripts.backfill_contract_document_text --commit --client-id 11
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import or_, select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.contract import Contract  # noqa: E402
from app.models.contract_document import ContractDocument  # noqa: E402
from app.services import storage_service  # noqa: E402
from app.services.contract_document_text import index  # noqa: E402

logger = logging.getLogger("backfill_contract_document_text")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--commit", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--after-id", type=int, default=0, help="Wznowienie od id dokumentu."
    )
    p.add_argument("--client-id", type=int, default=None)
    p.add_argument("--contract-id", type=int, default=None)
    return p.parse_args()


def _on_disk(file_path: str) -> bool:
    try:
        storage_service.get_contract_document_path(file_path)
    except FileNotFoundError:
        return False
    return True


async def _scope(args: argparse.Namespace) -> list[int]:
    query = (
        select(ContractDocument.id)
        .where(
            ContractDocument.doc_type.in_(index.READ_TYPES),
            ContractDocument.id > args.after_id,
            or_(
                ContractDocument.text_file_path.is_(None),
                ContractDocument.text_file_path != ContractDocument.file_path,
            ),
        )
        .order_by(ContractDocument.id)
    )
    if args.contract_id is not None:
        query = query.where(ContractDocument.contract_id == args.contract_id)
    if args.client_id is not None:
        query = query.join(Contract, Contract.id == ContractDocument.contract_id).where(
            Contract.client_id == args.client_id
        )
    if args.limit:
        query = query.limit(args.limit)
    async with AsyncSessionLocal() as db:
        return [int(i) for i in (await db.execute(query)).scalars().all()]


async def _main(args: argparse.Namespace) -> int:
    if args.commit == args.dry_run:
        print("Podaj dokładnie jedno: --commit albo --dry-run.")
        return 2
    ids = await _scope(args)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ContractDocument.id, ContractDocument.file_path).where(
                    ContractDocument.id.in_(ids)
                )
            )
        ).all()
    with_file = [int(r.id) for r in rows if r.file_path and _on_disk(r.file_path)]
    print(
        f"Dokumenty do odczytu: {len(ids)}, z plikiem na dysku: {len(with_file)}, "
        f"bez pliku: {len(ids) - len(with_file)}"
    )
    if args.dry_run:
        return 0
    for position, document_id in enumerate(ids, start=1):
        # Brak pliku też przechodzi przez odczyt: stan ``failed`` z powodem
        # zamiast ponownej próby przy każdym biegu skryptu.
        await index.index_document(document_id)
        if position % 10 == 0:
            print(f"… {position}/{len(ids)} (ostatni id {document_id})")
    async with AsyncSessionLocal() as db:
        states = Counter(
            (
                await db.execute(
                    select(ContractDocument.text_status).where(
                        ContractDocument.id.in_(ids)
                    )
                )
            )
            .scalars()
            .all()
        )
    print(
        "Stany po biegu: "
        + ", ".join(f"{k}={v}" for k, v in sorted(states.items(), key=str))
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(asyncio.run(_main(_parse_args())))
