"""Ta sama operacja na innym pliku (wyciąg dzienny i miesięczny) — jednym zapytaniem.

E3 (zapłaty faktur kosztowych), R9 (wypłaty dla zespołu) i E8 (wpłaty
klientów) uznają operację za duplikat, gdy ich tabela ma już zapis z innego
pliku z tą samą referencją banku (``statement_line_ref`` kończy się
``:<bank_ref[:48]>``), kwotą i dniem księgowania. Do 18.11.2026 każda ścieżka
pytała o to osobno dla każdej operacji — przy kilkuset operacjach setki
zapytań w jednym żądaniu (``POST /api/ledger/bank/import``: 1057 zapytań,
66,6 s). Tu: jedno zapytanie o kandydatów (dni i kwoty z pliku), reszta
warunku w pamięci, z tą samą semantyką.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.hr.bank.parsed import StatementLine


async def seen_elsewhere(
    db: AsyncSession,
    model: Any,
    lines: Iterable[StatementLine],
    sha: str,
    *,
    money: Callable[[Decimal], Decimal],
) -> set[str]:
    """``line_ref`` operacji, które ``model`` ma już z innego pliku wyciągu."""

    wanted = [line for line in lines if line.bank_ref]
    if not wanted:
        return set()
    rows = await db.execute(
        select(model.statement_line_ref, model.amount, model.booked_on).where(
            model.kind == "statement_line",
            model.statement_sha256 != sha,
            model.booked_on.in_({line.booked_on for line in wanted}),
            model.amount.in_({money(line.amount) for line in wanted}),
        )
    )
    known: dict[tuple[Any, Decimal], list[str]] = {}
    for ref, amount, booked_on in rows.all():
        if ref:
            known.setdefault((booked_on, Decimal(amount)), []).append(ref)
    out: set[str] = set()
    for line in wanted:
        suffix = f":{line.bank_ref[:48]}"
        refs = known.get((line.booked_on, money(line.amount)), ())
        if any(ref.endswith(suffix) for ref in refs):
            out.add(line.line_ref)
    return out
