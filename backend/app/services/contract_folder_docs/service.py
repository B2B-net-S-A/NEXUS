"""Pierwsze pobranie dokumentów z folderu „Umowy pracowników” (ticket 9).

Przebieg: ``listing`` (spis folderu w tle) → ``preview`` (raport do decyzji
admina) → ``applying`` (pobieranie plików w tle) → ``applied`` → opcjonalnie
``rolled_back``. Praca w tle trzyma dzierżawę (``lease_until``); przebieg
przerwany deployem podejmuje pętla ``contract_docs_sharepoint``.

Paragon w ``app_settings`` niesie wyłącznie liczby i ID — nazwiska są tylko
w wierszach przebiegu (widzi je admin w panelu i w raporcie XLSX).
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.export_safety import safe_row
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus
from app.models.contract_doc_sharepoint import (
    ContractDocSpItem,
    ContractDocSpRun,
    ContractDocSpRunItem,
)
from app.models.contract_document import ContractDocument
from app.services import storage_service
from app.services.contract_folder_docs.matching import ContractPerson
from app.services.contract_folder_docs.plan import ListedFile, build_plan, row_dict
from app.services.contract_folder_docs.store import SOURCE_IMPORT, attach_file
from app.services.m365 import sharepoint_docs as sp
from app.services.m365.graph_client import GraphRequestError

logger = logging.getLogger(__name__)

SETTINGS_KEY = "contract_docs_sharepoint"
RECEIPT_PREFIX = "0402_contract_docs_sharepoint_run_"
LEASE = timedelta(minutes=10)


class RunConflict(RuntimeError):
    """Stan przebiegu nie pozwala na tę operację (409 z polskim zdaniem)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def polish_error(exc: BaseException) -> str:
    """Zdanie dla admina — bez treści odpowiedzi Graphu (bywa w niej nazwa pliku)."""
    if isinstance(exc, sp.SharePointNotConfigured):
        return "Brak konfiguracji aplikacji SharePoint w NEXUSIE — dokończ konfigurację w Azure."
    if isinstance(exc, sp.SharePointFolderNotFound):
        return "Nie znaleziono folderu pod tym linkiem albo aplikacja nie ma dostępu do witryny."
    if isinstance(exc, GraphRequestError):
        if exc.status in (401, 403):
            return (
                f"SharePoint odmówił dostępu (HTTP {exc.status}) — sprawdź, czy aplikacja "
                "ma nadany dostęp do tej witryny."
            )
        if exc.status == 404:
            return "SharePoint nie znalazł folderu (HTTP 404)."
        return f"Błąd SharePointa (HTTP {exc.status}). Spróbuj ponownie."
    return f"Nieoczekiwany błąd ({type(exc).__name__}). Spróbuj ponownie."


# ── Ustawienia (link i rozwiązany folder) ───────────────────────────────────


async def load_settings(db: AsyncSession) -> dict[str, Any]:
    row = await db.get(AppSetting, SETTINGS_KEY)
    return dict(row.value) if row is not None else {}


async def save_settings(
    db: AsyncSession, patch: dict[str, Any], user_id: Optional[int]
) -> None:
    row = await db.get(AppSetting, SETTINGS_KEY)
    if row is None:
        db.add(AppSetting(key=SETTINGS_KEY, value=dict(patch), updated_by=user_id))
    else:
        row.value = {**(row.value or {}), **patch}
        row.updated_by = user_id
    await db.flush()


async def load_contract_people(db: AsyncSession) -> list[ContractPerson]:
    """Kontrakty NEXUSA z nazwiskiem osoby — bez unieważnionych."""
    rows = (
        await db.execute(
            select(
                Contract.id, Contract.candidate_id, Candidate.name, Candidate.lastname
            )
            .join(Candidate, Candidate.id == Contract.candidate_id)
            .where(Contract.status != ContractStatus.void)
            .order_by(Contract.id)
        )
    ).all()
    return [
        ContractPerson(
            contract_id=r.id,
            candidate_id=r.candidate_id,
            first=(r.name or "").strip(),
            last=(r.lastname or "").strip(),
        )
        for r in rows
    ]


def listed_files(listing: sp.FolderListing) -> list[ListedFile]:
    files = [
        ListedFile(
            folder_name=f.folder.name,
            item_id=f.item.id,
            relative_path=f.relative_path,
            size=f.item.size,
        )
        for f in listing.files
    ]
    files.extend(
        ListedFile(folder_name=None, item_id=i.id, relative_path=i.name, size=i.size)
        for i in listing.loose_files
    )
    return files


# ── Dzierżawa ────────────────────────────────────────────────────────────────


async def _claim(run_id: int, modes: tuple[str, ...]) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(ContractDocSpRun)
            .where(
                ContractDocSpRun.id == run_id,
                ContractDocSpRun.mode.in_(modes),
                or_(
                    ContractDocSpRun.lease_until.is_(None),
                    ContractDocSpRun.lease_until < func.now(),
                ),
            )
            .values(lease_until=_now() + LEASE)
        )
        await db.commit()
        return bool(result.rowcount)


async def _renew(db: AsyncSession, run_id: int) -> None:
    await db.execute(
        update(ContractDocSpRun)
        .where(ContractDocSpRun.id == run_id)
        .values(lease_until=_now() + LEASE)
    )


# ── Podgląd ──────────────────────────────────────────────────────────────────


async def start_preview(
    db: AsyncSession, *, url: str, folder_name: Optional[str], user_id: int
) -> ContractDocSpRun:
    busy = await db.scalar(
        select(ContractDocSpRun.id).where(
            ContractDocSpRun.mode.in_(("listing", "applying"))
        )
    )
    if busy is not None:
        raise RunConflict("Poprzedni przebieg jeszcze trwa — poczekaj na jego koniec.")
    run = ContractDocSpRun(mode="listing", source_url=url.strip(), created_by=user_id)
    db.add(run)
    await save_settings(
        db,
        {"url": url.strip(), "folder_name": (folder_name or "").strip() or None},
        user_id,
    )
    await db.flush()
    return run


async def build_preview(run_id: int) -> None:
    """Spis folderu + plan przypisań. Nie pobiera plików."""
    if not await _claim(run_id, ("listing",)):
        return
    async with AsyncSessionLocal() as db:
        run = await db.get(ContractDocSpRun, run_id)
        if run is None:
            return
        settings_value = await load_settings(db)
        try:
            async with sp.graph_client() as client:
                folder = await sp.resolve_folder(
                    client,
                    run.source_url or "",
                    folder_name=settings_value.get("folder_name")
                    or sp.DEFAULT_FOLDER_NAME,
                )
                listing = await sp.list_person_files(
                    client, folder.drive_id, folder.item_id
                )
        except Exception as exc:  # noqa: BLE001 — każdy błąd kończy przebieg zdaniem
            logger.warning("contract_docs_sp: listing failed (%s)", type(exc).__name__)
            run.mode = "failed"
            run.error = polish_error(exc)
            run.lease_until = None
            await db.commit()
            return

        contracts = await load_contract_people(db)
        plan = build_plan(
            contracts, [f.name for f in listing.person_folders], listed_files(listing)
        )
        await db.execute(
            delete(ContractDocSpRunItem).where(ContractDocSpRunItem.run_id == run_id)
        )
        for row in plan.rows:
            db.add(ContractDocSpRunItem(run_id=run_id, **row_dict(row)))
        run.drive_id = folder.drive_id
        run.folder_item_id = folder.item_id
        run.counters = plan.counters
        run.mode = "preview"
        run.error = None
        run.lease_until = None
        await save_settings(
            db,
            {
                "drive_id": folder.drive_id,
                "folder_item_id": folder.item_id,
                "folder_label": folder.name,
            },
            run.created_by,
        )
        await db.commit()


# ── Zapis ────────────────────────────────────────────────────────────────────


async def start_apply(
    db: AsyncSession, *, run_id: int, deselected_item_ids: list[int], user_id: int
) -> ContractDocSpRun:
    run = await db.get(ContractDocSpRun, run_id, with_for_update=True)
    if run is None:
        raise LookupError(run_id)
    if run.mode != "preview":
        raise RunConflict("Ten przebieg nie jest podglądem gotowym do zapisu.")
    newer = await db.scalar(
        select(ContractDocSpRun.id).where(
            ContractDocSpRun.id > run_id, ContractDocSpRun.mode != "failed"
        )
    )
    if newer is not None:
        raise RunConflict("Jest nowszy przebieg — zapisz z najnowszego podglądu.")
    if deselected_item_ids:
        await db.execute(
            update(ContractDocSpRunItem)
            .where(
                ContractDocSpRunItem.run_id == run_id,
                ContractDocSpRunItem.kind == "assignment",
                ContractDocSpRunItem.id.in_(deselected_item_ids),
            )
            .values(selected=False, status="not_selected")
        )
    run.mode = "applying"
    run.applied_by = user_id
    run.lease_until = None
    await db.flush()
    return run


async def apply_run(run_id: int) -> None:
    """Pobiera zaznaczone pliki z SharePointa i zapisuje je na kontraktach.

    Plik przypisany do kilku kontraktów (osoba z kilkoma kontraktami) jest
    pobierany raz. Każdy plik to osobna transakcja — przerwanie w połowie
    zostawia gotowe pliki jako gotowe, a reszta idzie przy wznowieniu.
    """
    if not await _claim(run_id, ("applying",)):
        return
    async with AsyncSessionLocal() as db:
        run = await db.get(ContractDocSpRun, run_id)
        if run is None or not run.drive_id:
            return
        drive_id = run.drive_id
        user_id = run.applied_by
        pending = (
            (
                await db.execute(
                    select(ContractDocSpRunItem)
                    .where(
                        ContractDocSpRunItem.run_id == run_id,
                        ContractDocSpRunItem.kind == "assignment",
                        ContractDocSpRunItem.status == "pending",
                    )
                    .order_by(ContractDocSpRunItem.item_id, ContractDocSpRunItem.id)
                )
            )
            .scalars()
            .all()
        )
        by_item: dict[str, list[int]] = {}
        for item in pending:
            by_item.setdefault(item.item_id or "", []).append(item.id)
        await db.commit()

    try:
        async with sp.graph_client() as client:
            for item_id, row_ids in by_item.items():
                try:
                    content = await sp.download(client, drive_id, item_id)
                    download_error: Optional[str] = None
                except GraphRequestError as exc:
                    content = b""
                    download_error = polish_error(exc)
                async with AsyncSessionLocal() as db:
                    for row_id in row_ids:
                        row = await db.get(ContractDocSpRunItem, row_id)
                        if (
                            row is None
                            or row.status != "pending"
                            or row.contract_id is None
                        ):
                            continue
                        if download_error is not None:
                            row.status = "failed"
                            row.error = download_error[:255]
                            continue
                        result = await attach_file(
                            db,
                            contract_id=row.contract_id,
                            content=content,
                            filename=row.file_name or "dokument",
                            doc_type=row.doc_type or "other",
                            source=SOURCE_IMPORT,
                            item_id=item_id,
                            user_id=user_id,
                            run_id=run_id,
                            stored_key=f"sp-{run_id}-{row.id}-{row.file_name or 'dokument'}",
                        )
                        row.status = result.status
                        row.contract_document_id = result.document_id
                    await _renew(db, run_id)
                    await db.commit()
    except Exception as exc:  # noqa: BLE001
        # Dzierżawa wygaśnie, a pętla podejmie przebieg od miejsca przerwania.
        logger.warning("contract_docs_sp: apply interrupted (%s)", type(exc).__name__)
        async with AsyncSessionLocal() as db:
            run = await db.get(ContractDocSpRun, run_id)
            if run is not None:
                run.error = polish_error(exc)
                await db.commit()
        return

    async with AsyncSessionLocal() as db:
        await _finish_apply(db, run_id)
        await db.commit()


async def _finish_apply(db: AsyncSession, run_id: int) -> None:
    run = await db.get(ContractDocSpRun, run_id)
    if run is None:
        return
    status_counts = dict(
        (
            await db.execute(
                select(ContractDocSpRunItem.status, func.count())
                .where(
                    ContractDocSpRunItem.run_id == run_id,
                    ContractDocSpRunItem.kind == "assignment",
                )
                .group_by(ContractDocSpRunItem.status)
            )
        ).all()
    )
    imported_contracts = await db.scalar(
        select(func.count(func.distinct(ContractDocSpRunItem.contract_id))).where(
            ContractDocSpRunItem.run_id == run_id,
            ContractDocSpRunItem.status == "done",
        )
    )
    counters = dict(run.counters or {})
    counters.update(
        {
            "imported": int(status_counts.get("done", 0)),
            "skipped_existing": int(status_counts.get("skipped_existing", 0)),
            "not_selected": int(status_counts.get("not_selected", 0)),
            "failed": int(status_counts.get("failed", 0)),
            "contracts_with_imported_documents": int(imported_contracts or 0),
        }
    )
    run.counters = counters
    run.mode = "applied"
    run.applied_at = _now()
    run.lease_until = None
    run.error = None
    await _record_sp_items(db, run)
    doc_ids = (
        (
            await db.execute(
                select(ContractDocSpRunItem.contract_document_id).where(
                    ContractDocSpRunItem.run_id == run_id,
                    ContractDocSpRunItem.status == "done",
                )
            )
        )
        .scalars()
        .all()
    )
    db.add(
        AppSetting(
            key=f"{RECEIPT_PREFIX}{run_id}",
            value={
                "run_id": run_id,
                "applied_at": run.applied_at.isoformat(),
                "counters": counters,
                "document_ids": sorted(i for i in doc_ids if i is not None),
            },
            updated_by=run.applied_by,
        )
    )
    await save_settings(db, {"initial_import_run_id": run_id}, run.applied_by)


async def _record_sp_items(db: AsyncSession, run: ContractDocSpRun) -> None:
    """Stan każdego pliku po pierwszym pobraniu — synchronizacja zaczyna od
    niego i nie pobiera drugi raz tego, co już weszło."""
    rows = (
        (
            await db.execute(
                select(ContractDocSpRunItem).where(
                    ContractDocSpRunItem.run_id == run.id,
                    ContractDocSpRunItem.item_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    decided: dict[str, tuple[ContractDocSpRunItem, str]] = {}
    for row in rows:
        if row.kind == "assignment":
            status = (
                "dismissed"
                if row.status == "not_selected"
                else (
                    "imported" if row.status in ("done", "skipped_existing") else None
                )
            )
            if status is None:  # failed — synchronizacja spróbuje ponownie
                continue
        elif row.match_kind == "ambiguous":
            status = "review"
        elif row.match_kind == "none" and row.folder_name:
            status = "waiting_contract"
        else:
            status = "skipped"
        previous = decided.get(row.item_id or "")
        # „imported” wygrywa: plik wszedł do co najmniej jednego kontraktu.
        if previous is None or status == "imported":
            decided[row.item_id or ""] = (row, status)
    for item_id, (row, status) in decided.items():
        existing = await db.get(ContractDocSpItem, item_id)
        if existing is None:
            db.add(
                ContractDocSpItem(
                    item_id=item_id,
                    drive_id=run.drive_id or "",
                    folder_name=row.folder_name,
                    file_name=row.file_name or "",
                    size_bytes=row.size_bytes,
                    status=status,
                    reasons=list(row.reasons or []),
                )
            )
        else:
            existing.status = status
            existing.last_seen_at = _now()


# ── Cofnięcie ────────────────────────────────────────────────────────────────


async def rollback_run(
    db: AsyncSession, *, run_id: int, user_id: int
) -> dict[str, int]:
    run = await db.get(ContractDocSpRun, run_id, with_for_update=True)
    if run is None:
        raise LookupError(run_id)
    if run.mode != "applied":
        raise RunConflict("Cofnąć można tylko zapisany przebieg.")
    newer = await db.scalar(
        select(ContractDocSpRun.id).where(
            ContractDocSpRun.id > run_id,
            ContractDocSpRun.mode.in_(("applying", "applied")),
        )
    )
    if newer is not None:
        raise RunConflict("Cofnąć można tylko ostatni zapisany przebieg.")
    docs = (
        (
            await db.execute(
                select(ContractDocument).where(ContractDocument.import_run_id == run_id)
            )
        )
        .scalars()
        .all()
    )
    referenced: set[int] = set()
    if docs:
        from app.models.document_signature import DocumentSignature

        referenced = set(
            (
                await db.execute(
                    select(DocumentSignature.contract_document_id).where(
                        DocumentSignature.contract_document_id.in_([d.id for d in docs])
                    )
                )
            ).scalars()
        )
    paths: list[str] = []
    removed = 0
    for doc in docs:
        if doc.id in referenced:
            continue
        paths.append(doc.file_path)
        await db.delete(doc)
        removed += 1
    # Pliki z tego przebiegu nie wracają z synchronizacją — admin je cofnął.
    item_ids = (
        (
            await db.execute(
                select(ContractDocSpRunItem.item_id).where(
                    ContractDocSpRunItem.run_id == run_id,
                    ContractDocSpRunItem.status.in_(("done", "skipped_existing")),
                )
            )
        )
        .scalars()
        .all()
    )
    if item_ids:
        await db.execute(
            update(ContractDocSpItem)
            .where(ContractDocSpItem.item_id.in_(set(item_ids)))
            .values(status="dismissed", decided_by=user_id)
        )
    run.mode = "rolled_back"
    run.rolled_back_at = _now()
    run.rolled_back_by = user_id
    await db.flush()
    db.info.setdefault("contract_docs_sp_paths_to_delete", []).extend(paths)
    return {"removed": removed, "kept_referenced": len(referenced)}


def delete_files_after_commit(db: AsyncSession) -> None:
    for path in db.info.pop("contract_docs_sp_paths_to_delete", []):
        storage_service.delete_contract_document(path)


# ── Wznowienie przerwanych przebiegów (pętla) ────────────────────────────────


async def resume_interrupted() -> int:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ContractDocSpRun.id, ContractDocSpRun.mode).where(
                    ContractDocSpRun.mode.in_(("listing", "applying")),
                    or_(
                        ContractDocSpRun.lease_until.is_(None),
                        ContractDocSpRun.lease_until < func.now(),
                    ),
                )
            )
        ).all()
    for run_id, mode in rows:
        if mode == "listing":
            await build_preview(run_id)
        else:
            await apply_run(run_id)
    return len(rows)


# ── Raport XLSX ──────────────────────────────────────────────────────────────

MATCH_REASON_LABELS = {
    "diacritics": "różnica w polskich znakach",
    "partial_name": "inny zapis nazwiska (drugie imię albo człon nazwiska)",
    "typo": "możliwa literówka w nazwisku",
    "same_name_people": "kilka rekordów kandydata o tym nazwisku",
    "multiple_folders": "kilka pasujących podfolderów",
}

DOC_TYPE_LABELS = {
    "contract": "Umowa",
    "annex": "Aneks",
    "termination_notice": "Wypowiedzenie",
    "termination_agreement": "Porozumienie",
    "nda": "NDA",
    "oc_policy": "Polisa OC",
    "zus_certificate": "Zaświadczenie ZUS",
    "other": "Inne",
}

STATUS_LABELS = {
    "pending": "Do pobrania",
    "done": "Zapisany",
    "skipped_existing": "Pominięty — kontrakt już ma ten dokument",
    "not_selected": "Odznaczony przy zapisie",
    "failed": "Błąd pobrania",
    "info": "",
}


def _reasons_text(reasons: list[str] | None) -> str:
    return "; ".join(MATCH_REASON_LABELS.get(r, r) for r in reasons or [])


async def report_xlsx(db: AsyncSession, run_id: int) -> bytes:
    from openpyxl import Workbook

    rows = (
        (
            await db.execute(
                select(ContractDocSpRunItem)
                .where(ContractDocSpRunItem.run_id == run_id)
                .order_by(ContractDocSpRunItem.id)
            )
        )
        .scalars()
        .all()
    )
    run = await db.get(ContractDocSpRun, run_id)
    wb = Workbook()
    summary = wb.active
    summary.title = "Podsumowanie"
    counters = (run.counters if run else {}) or {}
    for label, key in (
        ("Kontrakty w NEXUSIE", "contracts_total"),
        ("Kontrakty z dokumentami w folderze", "contracts_with_documents"),
        (
            "Kontrakty, do których zapisano dokumenty",
            "contracts_with_imported_documents",
        ),
        ("Kontrakty bez podfolderu lub dokumentów", "contracts_without_documents"),
        ("Kontrakty z przypisaniem niepewnym", "contracts_uncertain"),
        ("Kontrakty z kilkoma pasującymi folderami", "contracts_ambiguous"),
        ("Kontrakty pominięte (Filip Jabłoński)", "contracts_excluded"),
        ("Foldery bez kontraktu w NEXUSIE", "folders_without_contract"),
        ("Pliki zapisane", "imported"),
        ("Pliki pominięte — już były", "skipped_existing"),
        ("Pliki pominięte — Word i inne formaty", "files_skipped_extension"),
        ("Pliki pominięte — ponad 20 MB", "files_skipped_size"),
        ("Błędy pobrania", "failed"),
    ):
        summary.append([label, counters.get(key, "")])

    def sheet(title: str, header: list[str], data: list[list[Any]]) -> None:
        ws = wb.create_sheet(title)
        ws.append(header)
        for values in data:
            ws.append(safe_row(values))

    assignments = [r for r in rows if r.kind == "assignment"]
    sheet(
        "Przypisane",
        ["Kontrakt", "Osoba", "Folder", "Plik", "Typ", "Stan", "Uwagi"],
        [
            [
                r.contract_id,
                r.person_name,
                r.folder_name,
                r.file_name,
                DOC_TYPE_LABELS.get(r.doc_type or "", r.doc_type),
                STATUS_LABELS.get(r.status, r.status),
                "; ".join(x for x in (r.note, r.error) if x),
            ]
            for r in assignments
        ],
    )
    sheet(
        "Bez folderu lub dokumentów",
        ["Kontrakt", "Osoba", "Powód"],
        [
            [r.contract_id, r.person_name, r.note]
            for r in rows
            if r.kind == "contract" and r.match_kind in ("none", "sure", "uncertain")
        ],
    )
    uncertain: dict[int, ContractDocSpRunItem] = {}
    for r in rows:
        if r.match_kind in ("uncertain", "ambiguous") and r.kind in (
            "assignment",
            "contract",
        ):
            uncertain.setdefault(r.contract_id or 0, r)
    sheet(
        "Do weryfikacji",
        ["Kontrakt", "Osoba", "Folder", "Rodzaj", "Powód"],
        [
            [
                r.contract_id,
                r.person_name,
                r.folder_name or "",
                "niepewne" if r.match_kind == "uncertain" else "nieprzypisane",
                _reasons_text(r.reasons) or (r.note or ""),
            ]
            for r in uncertain.values()
        ],
    )
    sheet(
        "Foldery bez kontraktu",
        ["Folder", "Powód"],
        [[r.folder_name, r.note] for r in rows if r.kind == "folder"],
    )
    sheet(
        "Pominięte pliki",
        ["Folder", "Plik", "Powód"],
        [
            [r.folder_name or "", r.file_name, r.note]
            for r in rows
            if r.kind == "file"
            and r.match_kind not in ("none", "ambiguous", "excluded")
        ],
    )
    sheet(
        "Kontrakty pominięte",
        ["Kontrakt", "Osoba", "Powód"],
        [
            [r.contract_id, r.person_name, r.note]
            for r in rows
            if r.kind == "contract" and r.match_kind == "excluded"
        ],
    )
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
