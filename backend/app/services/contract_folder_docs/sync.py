"""Synchronizacja SharePoint ↔ NEXUS po pierwszym pobraniu (ticket 9).

**SharePoint → NEXUS.** Każdy bieg czyta cały folder (kilkaset wywołań Graph —
delta nie działa na podfolderze biblioteki SharePoint) i porównuje z
``contract_doc_sp_items``. Nowy plik PDF/JPG w folderze osoby:
pewne dopasowanie → dokument na każdym kontrakcie tej osoby; niepewne albo
kilka folderów → kolejka „Do przypisania” (decyduje admin); folder bez
kontraktu → czeka, aż kontrakt powstanie. Usunięcie pliku w SharePoincie
niczego w NEXUSIE nie kasuje.

**NEXUS → SharePoint.** Dokument dodany w NEXUSIE (upload, wypowiedzenie,
kopia z Generatora) trafia do podfolderu osoby. Zapisany
``sharepoint_item_id`` blokuje ponowny import tego samego pliku („echo”).
Usunięcie dokumentu w NEXUSIE nie usuwa pliku w SharePoincie — SharePoint
jest archiwum działu.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus
from app.models.contract_doc_sharepoint import ContractDocSpItem
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.services import storage_service
from app.services.contract_folder_docs.classify import (
    classify_filename,
    is_importable,
)
from app.services.contract_folder_docs.matching import (
    REASON_DIACRITICS,
    SURE,
    UNCERTAIN,
    Folder,
    folder_display_name,
    is_excluded_folder,
    is_excluded_person,
    match_contracts,
    match_person,
)
from app.services.contract_folder_docs.plan import MAX_FILE_BYTES
from app.services.contract_folder_docs.service import (
    load_contract_people,
    load_settings,
    polish_error,
    save_settings,
)
from app.services.contract_folder_docs.store import (
    FROM_SHAREPOINT,
    SOURCE_SYNC,
    attach_file,
    sha256_hex,
)
from app.services.m365 import sharepoint_docs as sp
from app.services.m365.graph_client import GraphRequestError

logger = logging.getLogger(__name__)

# Tyle dokumentów z NEXUSA wysyłamy w jednym biegu — reszta w następnym.
PUSH_BATCH = 50
PUSH_MAX_ATTEMPTS = 5
# Zamówienia (PDF zamówienia klienta) nie są dokumentami pracownika.
_NOT_PUSHED_TYPES = (ContractDocumentType.order,)

PUSH_SKIP_EXCLUDED = "Filip Jabłoński — dokumenty tej osoby obsługuje człowiek."
PUSH_SKIP_AMBIGUOUS = (
    "Kilka pasujących folderów w SharePoincie — przenieś plik ręcznie."
)
PUSH_SKIP_UNCERTAIN = (
    "Folder w SharePoincie ma inny zapis nazwiska — przenieś plik ręcznie."
)
PUSH_SKIP_NO_PERSON = "Kontrakt bez osoby — nie wiadomo, do którego folderu."
PUSH_SKIP_SAME_NAME = "Kilka osób o tym nazwisku pasuje do folderu w SharePoincie — przenieś plik ręcznie."

# Backend to jeden proces uvicorna: pętla i przycisk „Synchronizuj teraz” nie
# mogą biec naraz (dwa biegi wysłałyby ten sam dokument dwa razy).
_SYNC_LOCK = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SyncStats:
    listed: int = 0
    imported_files: int = 0
    imported_documents: int = 0
    to_review: int = 0
    waiting_contract: int = 0
    skipped: int = 0
    pushed: int = 0
    push_skipped: int = 0
    push_failed: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k != "errors"}


async def run_sync(db: AsyncSession) -> Optional[SyncStats]:
    """Jeden bieg w obie strony. ``None`` = synchronizacja jeszcze nie ma
    folderu albo pierwszego pobrania — nie ma od czego zacząć."""
    if _SYNC_LOCK.locked():
        return None
    async with _SYNC_LOCK:
        return await _run_sync_locked(db)


async def _run_sync_locked(db: AsyncSession) -> Optional[SyncStats]:
    state = await load_settings(db)
    # Spis folderu trwa minuty — bez otwartej transakcji na czas Graphu.
    await db.commit()
    drive_id = state.get("drive_id")
    root_id = state.get("folder_item_id")
    if not drive_id or not root_id or not state.get("initial_import_run_id"):
        return None
    stats = SyncStats()
    try:
        async with sp.graph_client() as client:
            listing = await sp.list_person_files(client, drive_id, root_id)
            await _pull(db, client, drive_id, listing, stats)
            await _push(
                db, client, drive_id, root_id, listing, stats, state.get("push_since")
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("contract_docs_sp: sync failed (%s)", type(exc).__name__)
        await db.rollback()
        stats.errors.append(polish_error(exc))
    await save_settings(
        db,
        {
            "last_sync_at": _now().isoformat(),
            "last_sync_status": "error" if stats.errors else "ok",
            "last_sync_error": stats.errors[0] if stats.errors else None,
            "last_sync_stats": stats.as_dict(),
        },
        None,
    )
    await db.commit()
    return stats


# ── SharePoint → NEXUS ───────────────────────────────────────────────────────


async def _pull(
    db: AsyncSession,
    client: Any,
    drive_id: str,
    listing: sp.FolderListing,
    stats: SyncStats,
) -> None:
    known = {
        row.item_id: row
        for row in (await db.execute(select(ContractDocSpItem))).scalars()
    }
    folders = [Folder.of(f.name, f.id) for f in listing.person_folders]
    contracts = await load_contract_people(db)
    matches = match_contracts(contracts, folders)
    by_folder: dict[str, list[Any]] = {}
    for result in matches:
        if result.match.folder is not None:
            by_folder.setdefault(result.match.folder.name, []).append(result)
    ambiguous_folders = {
        name
        for r in matches
        if r.match.kind == "ambiguous"
        for name in r.match.candidates
    }

    for listed in listing.files:
        stats.listed += 1
        item = listed.item
        row = known.get(item.id)
        if row is not None:
            row.last_seen_at = _now()
            # Decyzja o pliku jest ostateczna: wszedł, został wysłany z NEXUSA,
            # admin go odrzucił albo nie jest PDF/JPG. Zmiana treści pliku pod
            # tym samym id nie dokłada drugiej kopii (dokument wskazuje ten
            # plik przez `sharepoint_item_id`). Wracają tylko pliki czekające
            # na kontrakt; kolejka „Do przypisania” czeka na admina.
            if row.status != "waiting_contract":
                continue
        folder_name = listed.folder.name
        results = by_folder.get(folder_name, [])
        status, reasons, contract_ids = _decide(
            listed.relative_path, item.size, folder_name, results, ambiguous_folders
        )
        if status == "import":
            content = await sp.download(client, drive_id, item.id)
            classified = classify_filename(listed.relative_path)
            for contract_id in contract_ids:
                result = await attach_file(
                    db,
                    contract_id=contract_id,
                    content=content,
                    filename=listed.relative_path,
                    doc_type=classified.doc_type.value,
                    source=SOURCE_SYNC,
                    item_id=item.id,
                    user_id=None,
                    stored_key=f"sp-sync-{item.id}-{contract_id}",
                )
                if result.status == "done":
                    stats.imported_documents += 1
            stats.imported_files += 1
            status = "imported"
        elif status == "review":
            stats.to_review += 1
        elif status == "waiting_contract":
            stats.waiting_contract += 1
        else:
            stats.skipped += 1
        _upsert_item(
            db,
            row,
            item,
            drive_id,
            folder_name,
            listed.relative_path,
            status,
            reasons,
            contract_ids,
        )
        await db.commit()


def folder_candidates(
    contracts: list[Any], folders: list[Folder]
) -> dict[str, set[int]]:
    """Folder → rekordy kandydata, które do niego pasują (pewnie albo niepewnie)."""
    result: dict[str, set[int]] = {}
    for match in match_contracts(contracts, folders):
        if match.match.folder is not None and match.contract.candidate_id is not None:
            result.setdefault(match.match.folder.name, set()).add(
                match.contract.candidate_id
            )
    return result


def _decide(
    relative_path: str,
    size: Optional[int],
    folder_name: str,
    results: list[Any],
    ambiguous_folders: set[str],
) -> tuple[str, list[str], list[int]]:
    """(status, powody, kontrakty) dla pliku z folderu osoby."""
    if is_excluded_folder(folder_name):
        return "skipped", ["excluded"], []
    if not is_importable(relative_path) or (size is not None and size > MAX_FILE_BYTES):
        return "skipped", [], []
    if folder_name in ambiguous_folders and not results:
        return "review", ["multiple_folders"], []
    if not results:
        return "waiting_contract", [], []
    contract_ids = sorted({r.contract.contract_id for r in results})
    if all(r.match.kind == SURE for r in results):
        return "import", [], contract_ids
    reasons = sorted({reason for r in results for reason in r.match.reasons})
    return "review", reasons, contract_ids


def _upsert_item(
    db: AsyncSession,
    row: Optional[ContractDocSpItem],
    item: sp.DriveItem,
    drive_id: str,
    folder_name: str,
    relative_path: str,
    status: str,
    reasons: list[str],
    contract_ids: list[int],
) -> None:
    if row is None:
        db.add(
            ContractDocSpItem(
                item_id=item.id,
                drive_id=drive_id,
                folder_name=folder_name,
                file_name=relative_path,
                size_bytes=item.size,
                c_tag=item.c_tag,
                status=status,
                reasons=reasons,
                proposed_contract_ids=contract_ids,
            )
        )
        return
    row.folder_name = folder_name
    row.file_name = relative_path
    row.size_bytes = item.size
    row.c_tag = item.c_tag
    row.status = status
    row.reasons = reasons
    row.proposed_contract_ids = contract_ids
    row.last_seen_at = _now()


async def decide_review(
    db: AsyncSession,
    *,
    item_id: str,
    action: str,
    contract_ids: list[int],
    user_id: int,
) -> dict[str, int]:
    """Decyzja admina o pliku z kolejki „Do przypisania”."""
    row = await db.get(ContractDocSpItem, item_id, with_for_update=True)
    if row is None or row.status != "review":
        raise LookupError(item_id)
    if action == "dismiss":
        row.status = "dismissed"
        row.decided_by = user_id
        await db.flush()
        return {"imported": 0}
    if not contract_ids:
        raise ValueError("Wskaż co najmniej jeden kontrakt.")
    existing = set(
        (
            await db.execute(
                select(Contract.id).where(
                    Contract.id.in_(contract_ids),
                    Contract.status != ContractStatus.void,
                )
            )
        ).scalars()
    )
    missing = set(contract_ids) - existing
    if missing:
        raise ValueError("Kontrakt nie istnieje albo jest unieważniony.")
    async with sp.graph_client() as client:
        content = await sp.download(client, row.drive_id, row.item_id)
    classified = classify_filename(row.file_name)
    imported = 0
    for contract_id in sorted(existing):
        result = await attach_file(
            db,
            contract_id=contract_id,
            content=content,
            filename=row.file_name,
            doc_type=classified.doc_type.value,
            source=SOURCE_SYNC,
            item_id=row.item_id,
            user_id=user_id,
            stored_key=f"sp-sync-{row.item_id}-{contract_id}",
        )
        imported += int(result.status == "done")
    row.status = "imported"
    row.decided_by = user_id
    await db.flush()
    return {"imported": imported}


# ── NEXUS → SharePoint ───────────────────────────────────────────────────────


async def _push(
    db: AsyncSession,
    client: Any,
    drive_id: str,
    root_id: str,
    listing: sp.FolderListing,
    stats: SyncStats,
    push_since: Optional[str] = None,
) -> None:
    since_filter = []
    if push_since:
        since_filter.append(
            ContractDocument.created_at >= datetime.fromisoformat(push_since)
        )
    rows = (
        await db.execute(
            select(
                ContractDocument,
                Candidate.name,
                Candidate.lastname,
                Contract.candidate_id,
            )
            .join(Contract, Contract.id == ContractDocument.contract_id)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .where(
                ContractDocument.sharepoint_item_id.is_(None),
                or_(
                    ContractDocument.source.is_(None),
                    ContractDocument.source.not_in(FROM_SHAREPOINT),
                ),
                ContractDocument.doc_type.not_in(_NOT_PUSHED_TYPES),
                ContractDocument.source_order_group_id.is_(None),
                *since_filter,
                or_(
                    ContractDocument.sharepoint_push_status.is_(None),
                    (ContractDocument.sharepoint_push_status == "failed")
                    & (ContractDocument.sharepoint_push_attempts < PUSH_MAX_ATTEMPTS),
                ),
            )
            .order_by(ContractDocument.id)
            .limit(PUSH_BATCH)
        )
    ).all()
    if not rows:
        return
    folders = [Folder.of(f.name, f.id) for f in listing.person_folders]
    files_by_folder: dict[str, list[sp.PersonFile]] = {}
    for listed in listing.files:
        files_by_folder.setdefault(listed.folder.id, []).append(listed)
    candidates_by_folder = folder_candidates(await load_contract_people(db), folders)

    for doc, first, last, candidate_id in rows:
        try:
            await _push_one(
                db,
                client,
                drive_id,
                root_id,
                doc,
                first,
                last,
                folders,
                files_by_folder,
                stats,
                candidate_id=candidate_id,
                candidates_by_folder=candidates_by_folder,
            )
        except GraphRequestError as exc:
            doc.sharepoint_push_status = "failed"
            doc.sharepoint_push_attempts = (doc.sharepoint_push_attempts or 0) + 1
            doc.sharepoint_push_error = polish_error(exc)[:255]
            stats.push_failed += 1
        await db.commit()


async def _push_one(
    db: AsyncSession,
    client: Any,
    drive_id: str,
    root_id: str,
    doc: ContractDocument,
    first: Optional[str],
    last: Optional[str],
    folders: list[Folder],
    files_by_folder: dict[str, list[sp.PersonFile]],
    stats: SyncStats,
    *,
    candidate_id: Optional[int] = None,
    candidates_by_folder: Optional[dict[str, set[int]]] = None,
) -> None:
    def skip(reason: str) -> None:
        doc.sharepoint_push_status = "skipped"
        doc.sharepoint_push_error = reason
        stats.push_skipped += 1

    if not (first or last):
        return skip(PUSH_SKIP_NO_PERSON)
    if is_excluded_person(first, last):
        return skip(PUSH_SKIP_EXCLUDED)
    match = match_person(first, last, folders)
    if match.kind == "ambiguous":
        return skip(PUSH_SKIP_AMBIGUOUS)
    if match.kind == UNCERTAIN and set(match.reasons) != {REASON_DIACRITICS}:
        return skip(PUSH_SKIP_UNCERTAIN)
    if match.folder is not None and candidates_by_folder is not None:
        # Dwie różne osoby (rekordy kandydata) o tym nazwisku pasują do tego
        # folderu — nie wiadomo, czyj to folder (ta sama reguła co przy pobieraniu).
        others = candidates_by_folder.get(match.folder.name, set()) - {candidate_id}
        if candidate_id is None or others:
            return skip(PUSH_SKIP_SAME_NAME)
    if match.folder is not None and match.folder.item_id:
        folder_id = match.folder.item_id
    else:
        prospective = Folder.of(folder_display_name(first, last))
        candidates = folder_candidates(await load_contract_people(db), [prospective])
        if candidate_id is None or candidates.get(prospective.name, set()) - {
            candidate_id
        }:
            return skip(PUSH_SKIP_SAME_NAME)
        created = await sp.ensure_person_folder(
            client, drive_id, root_id, folder_display_name(first, last)
        )
        folder_id = created.id
        folders.append(Folder.of(created.name, created.id))

    try:
        content = storage_service.get_contract_document_path(doc.file_path).read_bytes()
    except (FileNotFoundError, OSError):
        return skip("Brak pliku dokumentu na serwerze NEXUSA.")

    # Nazwa i rozmiar zawężają porównanie, ale dopiero treść potwierdza kopię.
    digest = sha256_hex(content)
    for existing in files_by_folder.get(folder_id, []):
        if existing.item.name == doc.filename and existing.item.size == len(content):
            existing_content = await sp.download(client, drive_id, existing.item.id)
            if sha256_hex(existing_content) != digest:
                continue
            await _mark_pushed(db, doc, existing.item, drive_id)
            stats.pushed += 1
            return None
    uploaded = await sp.upload_file(
        client, drive_id, folder_id, doc.filename, content, doc.content_type
    )
    await _mark_pushed(db, doc, uploaded, drive_id)
    stats.pushed += 1
    return None


async def _mark_pushed(
    db: AsyncSession, doc: ContractDocument, item: sp.DriveItem, drive_id: str
) -> None:
    doc.sharepoint_item_id = item.id
    doc.sharepoint_push_status = "done"
    doc.sharepoint_push_error = None
    doc.sharepoint_pushed_at = _now()
    # Stan pliku: synchronizacja SharePoint → NEXUS go pominie. Plik, który już
    # leżał w folderze (np. wszedł pierwszym pobraniem), zostaje przy swoim stanie.
    if await db.get(ContractDocSpItem, item.id) is not None:
        return
    db.add(
        ContractDocSpItem(
            item_id=item.id,
            drive_id=drive_id,
            folder_name=None,
            file_name=item.name,
            size_bytes=item.size,
            c_tag=item.c_tag,
            status="pushed",
        )
    )


# ── Sonda zdrowia i rytm pętli ───────────────────────────────────────────────


def sync_interval_seconds() -> int:
    from app.core.config import settings

    return max(300, int(settings.CONTRACT_DOCS_SP_SYNC_MINUTES) * 60)


async def sync_due(db: AsyncSession) -> bool:
    state = await load_settings(db)
    last = state.get("last_sync_at")
    if not last:
        return True
    try:
        last_at = datetime.fromisoformat(last)
    except ValueError:
        return True
    return (_now() - last_at).total_seconds() >= sync_interval_seconds()


async def health_status(db: AsyncSession) -> str:
    """``unconfigured`` (brak rejestracji) / ``configured`` (jest dostęp, ale
    synchronizacja wyłączona) / ``degraded`` (ostatni bieg padł albo brak
    biegu przez 3 odstępy) / ``healthy``. Informacyjna — nie daje ``unhealthy``."""
    from app.core.config import settings

    if not sp.credentials_configured():
        return "unconfigured"
    if not settings.CONTRACT_DOCS_SP_SYNC_ENABLED:
        return "configured"
    state = await load_settings(db)
    if not state.get("initial_import_run_id"):
        return "configured"
    if state.get("last_sync_status") == "error":
        return "degraded"
    last = state.get("last_sync_at")
    if not last:
        return "degraded"
    try:
        age = (_now() - datetime.fromisoformat(last)).total_seconds()
    except ValueError:
        return "degraded"
    return "degraded" if age > 3 * sync_interval_seconds() else "healthy"
