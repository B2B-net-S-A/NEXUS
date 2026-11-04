"""Foldery w zakładce Dokumenty kontraktu (0494, ticket Ani 21.10.2026).

Zasady (``docs/claude/kontrakty/foldery-w-dokumentach-kontraktu.md``):

- plik bez folderu = sekcja „Aktualna umowa”; folder ma jeden poziom;
- folder „Zamówienia” wynika z typu dokumentu (``order``) — zamówienia nie
  przenosi się ręcznie, a w ``folder_id`` niczego dla nich nie zapisujemy;
- usunięcie folderu nie usuwa plików (FK ``ON DELETE SET NULL``);
- podpowiedź „Poprzednia umowa” czyta numer umowy z nazwy pliku i niczego
  sama nie przenosi — decyduje człowiek.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.b2b_contract_detail import B2BContractDetail
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.contract import Contract, ContractStatus
from app.models.contract_document import (
    ContractDocument,
    ContractDocumentFolder,
    ContractDocumentType,
)

ORDERS_FOLDER_DEFAULT_NAME = "Zamówienia"
FOLDER_NAME_MAX = 120
MOVE_MAX = 500

# Numer umowy w nazwie pliku: „361-2019”, „518_2026”, „1434/2026”. Bez kropki
# (daty „04.05.2026”) i bez cyfry albo separatora tuż przed numerem — inaczej
# „01-10-2026” dałoby numer „10-2026”.
_NUMBER_RE = re.compile(r"(?<![\d./\-])(\d{1,5})\s*[-_/]\s*((?:19|20)\d{2})(?!\d)")

# Numer z nazwy pliku czytamy tylko z dokumentów umowy — „ZUS 03-2026.pdf”
# to miesiąc, nie numer umowy.
_NUMBERED_TYPES = frozenset(
    {
        ContractDocumentType.contract,
        ContractDocumentType.annex,
        ContractDocumentType.termination_notice,
        ContractDocumentType.termination_agreement,
    }
)
_TERMINATION_TYPES = frozenset(
    {
        ContractDocumentType.termination_notice,
        ContractDocumentType.termination_agreement,
    }
)
_LIVE_STATUSES = frozenset({ContractStatus.active, ContractStatus.ending})

ContractNumber = tuple[int, int]  # (numer, rok)


@dataclass(frozen=True)
class FolderSuggestion:
    number: str
    folder_name: str
    folder_id: Optional[int]
    document_ids: list[int]


def parse_contract_number(text: Optional[str]) -> Optional[ContractNumber]:
    if not text:
        return None
    match = _NUMBER_RE.search(text)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def format_contract_number(number: ContractNumber) -> str:
    return f"{number[0]}-{number[1]}"


def clean_folder_name(raw: str) -> str:
    name = " ".join((raw or "").split())
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Podaj nazwę folderu.",
        )
    if len(name) > FOLDER_NAME_MAX:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Nazwa folderu może mieć najwyżej {FOLDER_NAME_MAX} znaków.",
        )
    return name


async def list_folders(
    db: AsyncSession, contract_id: int
) -> tuple[list[ContractDocumentFolder], str]:
    """Foldery użytkownika (od najstarszego) i nazwa folderu „Zamówienia”."""
    rows = list(
        (
            await db.execute(
                select(ContractDocumentFolder)
                .where(ContractDocumentFolder.contract_id == contract_id)
                .order_by(ContractDocumentFolder.created_at, ContractDocumentFolder.id)
            )
        ).scalars()
    )
    orders_name = next(
        (f.name for f in rows if f.kind == "orders"), ORDERS_FOLDER_DEFAULT_NAME
    )
    return [f for f in rows if f.kind == "user"], orders_name


async def get_user_folder(
    db: AsyncSession, contract_id: int, folder_id: int
) -> ContractDocumentFolder:
    folder = await db.scalar(
        select(ContractDocumentFolder).where(
            ContractDocumentFolder.id == folder_id,
            ContractDocumentFolder.contract_id == contract_id,
            ContractDocumentFolder.kind == "user",
        )
    )
    if folder is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego folderu.")
    return folder


async def _assert_name_free(
    db: AsyncSession, contract_id: int, name: str, *, except_id: Optional[int]
) -> None:
    folders, orders_name = await list_folders(db, contract_id)
    taken = {f.name.casefold() for f in folders if f.id != except_id}
    # Nazwa folderu „Zamówienia” blokuje też foldery użytkownika — dwa
    # wiersze „Zamówienia” na liście czytają się jak jeden.
    taken.add(orders_name.casefold())
    if name.casefold() in taken:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Folder „{name}” już jest w tym kontrakcie.",
        )


async def _documents_for_move(
    db: AsyncSession, contract_id: int, document_ids: Iterable[int]
) -> list[ContractDocument]:
    ids = sorted(set(document_ids))
    if not ids:
        return []
    if len(ids) > MOVE_MAX:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Naraz można przenieść najwyżej {MOVE_MAX} plików.",
        )
    docs = list(
        (
            await db.execute(
                select(ContractDocument).where(
                    ContractDocument.id.in_(ids),
                    ContractDocument.contract_id == contract_id,
                )
            )
        ).scalars()
    )
    if len(docs) != len(ids):
        raise HTTPException(
            status_code=404,
            detail="Część plików nie należy już do tego kontraktu — odśwież listę.",
        )
    if any(d.doc_type == ContractDocumentType.order for d in docs):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Zamówienia zawsze leżą w folderze „Zamówienia” — odznacz je.",
        )
    return docs


async def create_folder(
    db: AsyncSession,
    contract_id: int,
    *,
    name: str,
    user_id: Optional[int],
    document_ids: Iterable[int] = (),
) -> tuple[ContractDocumentFolder, int]:
    """Nowy folder, opcjonalnie od razu z zaznaczonymi plikami."""
    name = clean_folder_name(name)
    await _assert_name_free(db, contract_id, name, except_id=None)
    docs = await _documents_for_move(db, contract_id, document_ids)
    folder = ContractDocumentFolder(
        contract_id=contract_id, name=name, kind="user", created_by=user_id
    )
    db.add(folder)
    await db.flush()
    for doc in docs:
        doc.folder_id = folder.id
    await db.flush()
    return folder, len(docs)


async def rename_folder(
    db: AsyncSession, contract_id: int, folder_id: int, *, name: str
) -> ContractDocumentFolder:
    folder = await get_user_folder(db, contract_id, folder_id)
    name = clean_folder_name(name)
    if name != folder.name:
        await _assert_name_free(db, contract_id, name, except_id=folder.id)
        folder.name = name
        await db.flush()
    return folder


async def rename_orders_folder(
    db: AsyncSession, contract_id: int, *, name: str, user_id: Optional[int]
) -> str:
    name = clean_folder_name(name)
    row = await db.scalar(
        select(ContractDocumentFolder).where(
            ContractDocumentFolder.contract_id == contract_id,
            ContractDocumentFolder.kind == "orders",
        )
    )
    current = row.name if row else ORDERS_FOLDER_DEFAULT_NAME
    if name == current:
        return name
    folders, _ = await list_folders(db, contract_id)
    if name.casefold() in {f.name.casefold() for f in folders}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Folder „{name}” już jest w tym kontrakcie.",
        )
    if row is None:
        db.add(
            ContractDocumentFolder(
                contract_id=contract_id, name=name, kind="orders", created_by=user_id
            )
        )
    else:
        row.name = name
    await db.flush()
    return name


async def delete_folder(db: AsyncSession, contract_id: int, folder_id: int) -> int:
    """Usuwa folder; pliki wracają do „Aktualnej umowy”. Zwraca ich liczbę."""
    folder = await get_user_folder(db, contract_id, folder_id)
    released = await db.scalar(
        select(func.count(ContractDocument.id)).where(
            ContractDocument.folder_id == folder.id
        )
    )
    # Jawnie, nie tylko przez FK: ta sama sesja ma te dokumenty w pamięci.
    docs = (
        await db.execute(
            select(ContractDocument).where(ContractDocument.folder_id == folder.id)
        )
    ).scalars()
    for doc in docs:
        doc.folder_id = None
    await db.delete(folder)
    await db.flush()
    return int(released or 0)


async def move_documents(
    db: AsyncSession,
    contract_id: int,
    *,
    document_ids: Iterable[int],
    folder_id: Optional[int],
) -> int:
    if folder_id is not None:
        await get_user_folder(db, contract_id, folder_id)
    docs = await _documents_for_move(db, contract_id, document_ids)
    if not docs:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Zaznacz co najmniej jeden plik.",
        )
    for doc in docs:
        doc.folder_id = folder_id
    await db.flush()
    return len(docs)


async def _current_contract_number(
    db: AsyncSession, contract_id: int
) -> Optional[ContractNumber]:
    detail_number = await db.scalar(
        select(B2BContractDetail.contract_number).where(
            B2BContractDetail.contract_id == contract_id
        )
    )
    parsed = parse_contract_number(detail_number)
    if parsed:
        return parsed
    generated = await db.scalar(
        select(B2BGeneratedContract.contract_number)
        .where(B2BGeneratedContract.contract_id == contract_id)
        .order_by(B2BGeneratedContract.created_at.desc())
        .limit(1)
    )
    return parse_contract_number(generated)


def build_suggestions(
    docs: list[ContractDocument],
    folders: list[ContractDocumentFolder],
    *,
    current: Optional[ContractNumber],
    contract_live: bool,
) -> tuple[Optional[ContractNumber], list[FolderSuggestion]]:
    """Grupy plików „poprzedniej umowy” wśród plików bez folderu.

    Bieżący numer: z danych umowy B2B, a gdy ich brak — najnowszy numer
    (rok, numer) z nazw dokumentów umowy. Wypowiedzenie albo porozumienie
    bez numeru dołączamy tylko przy żywym kontrakcie i tylko, gdy starsza
    umowa jest jedna — przy dwóch nie zgadujemy, do której należy.
    """
    loose = [d for d in docs if d.folder_id is None and d.doc_type in _NUMBERED_TYPES]
    numbered: dict[ContractNumber, list[int]] = {}
    unnumbered_terminations: list[int] = []
    for doc in loose:
        number = parse_contract_number(doc.filename)
        if number is None:
            if doc.doc_type in _TERMINATION_TYPES:
                unnumbered_terminations.append(doc.id)
            continue
        numbered.setdefault(number, []).append(doc.id)
    if current is None:
        if not numbered:
            return None, []
        current = max(numbered, key=lambda n: (n[1], n[0]))
    older = {n: ids for n, ids in numbered.items() if n != current}
    if not older:
        return current, []
    if contract_live and len(older) == 1 and unnumbered_terminations:
        only = next(iter(older))
        older[only] = older[only] + unnumbered_terminations
    by_name = {f.name.casefold(): f.id for f in folders}
    out: list[FolderSuggestion] = []
    for number in sorted(older, key=lambda n: (n[1], n[0]), reverse=True):
        label = format_contract_number(number)
        name = f"Poprzednia umowa – nr {label}"
        out.append(
            FolderSuggestion(
                number=label,
                folder_name=name,
                folder_id=by_name.get(name.casefold()),
                document_ids=sorted(older[number]),
            )
        )
    return current, out


async def suggestions_for(
    db: AsyncSession, contract: Contract, folders: list[ContractDocumentFolder]
) -> tuple[Optional[str], list[FolderSuggestion]]:
    docs = list(
        (
            await db.execute(
                select(ContractDocument).where(
                    ContractDocument.contract_id == contract.id
                )
            )
        ).scalars()
    )
    current, suggestions = build_suggestions(
        docs,
        folders,
        current=await _current_contract_number(db, contract.id),
        contract_live=contract.status in _LIVE_STATUSES,
    )
    return (format_contract_number(current) if current else None), suggestions
