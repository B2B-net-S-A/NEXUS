"""Plan przypisań plików z folderu do kontraktów — czysta funkcja (ticket 9).

Wejście: kontrakty NEXUSA z nazwiskiem osoby i spis folderu z SharePointa.
Wyjście: wiersze raportu przebiegu (te same, które zapisuje podgląd, czyta
„Pobierz i zapisz” i składa raport XLSX) oraz liczniki podsumowania z ticketu.
Bez bazy i bez sieci — testy sprawdzają tu całą logikę decyzji.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.contract_folder_docs.classify import classify_filename, is_importable
from app.services.contract_folder_docs.matching import (
    AMBIGUOUS,
    EXCLUDED,
    NONE,
    SURE,
    UNCERTAIN,
    ContractPerson,
    Folder,
    is_excluded_folder,
    match_contracts,
)

# Limit pliku jak przy ręcznym uploadzie (``api/contracts.MAX_UPLOAD_BYTES``).
MAX_FILE_BYTES = 20 * 1024 * 1024

NOTE_NO_FOLDER = "Nie znaleziono podfolderu „Nazwisko Imię”."
NOTE_EMPTY_FOLDER = "Podfolder nie zawiera plików PDF ani JPG."
NOTE_EXCLUDED = (
    "Filip Jabłoński — dokumenty dodawane ręcznie (dwie osoby o tym nazwisku)."
)
NOTE_AMBIGUOUS = "Kilka pasujących podfolderów: {names}."
NOTE_FOLDER_WITHOUT_CONTRACT = (
    "Brak kontraktu tej osoby w NEXUSIE — pliki nie zostały przypisane."
)
NOTE_FOLDER_AMBIGUOUS = (
    "Folder pasuje do osoby, która ma kilka pasujących folderów — do decyzji."
)
NOTE_SKIPPED_EXTENSION = "Pominięty: import bierze tylko PDF i JPG."
NOTE_SKIPPED_SIZE = "Pominięty: plik większy niż 20 MB."
NOTE_LOOSE_FILE = "Plik leży poza folderami osób."


@dataclass(frozen=True)
class ListedFile:
    folder_name: Optional[str]  # None = plik luzem w folderze głównym
    item_id: str
    relative_path: str
    size: Optional[int]


@dataclass
class PlanRow:
    kind: str  # assignment | contract | folder | file
    folder_name: Optional[str] = None
    file_name: Optional[str] = None
    item_id: Optional[str] = None
    size_bytes: Optional[int] = None
    doc_type: Optional[str] = None
    contract_id: Optional[int] = None
    candidate_id: Optional[int] = None
    person_name: Optional[str] = None
    match_kind: Optional[str] = None
    reasons: list[str] = field(default_factory=list)
    note: Optional[str] = None
    selected: bool = True
    status: str = "info"


@dataclass
class Plan:
    rows: list[PlanRow]
    counters: dict[str, int]


def _person_name(contract: ContractPerson) -> str:
    return f"{contract.first} {contract.last}".strip()


def build_plan(
    contracts: Sequence[ContractPerson],
    folder_names: Sequence[str],
    files: Sequence[ListedFile],
) -> Plan:
    folders = [Folder.of(name) for name in folder_names]
    matches = match_contracts(contracts, folders)

    files_by_folder: dict[str, list[ListedFile]] = defaultdict(list)
    loose: list[ListedFile] = []
    for listed in files:
        if listed.folder_name is None:
            loose.append(listed)
        else:
            files_by_folder[listed.folder_name].append(listed)

    rows: list[PlanRow] = []
    used_folders: set[str] = set()
    ambiguous_folders: set[str] = set()
    contracts_with_docs: set[int] = set()
    contracts_without: set[int] = set()
    uncertain_contracts: set[int] = set()
    ambiguous_contracts: set[int] = set()
    excluded_contracts: set[int] = set()

    for result in sorted(
        matches, key=lambda r: (r.contract.last.casefold(), r.contract.contract_id)
    ):
        contract = result.contract
        match = result.match
        base = dict(
            contract_id=contract.contract_id,
            candidate_id=contract.candidate_id,
            person_name=_person_name(contract),
            match_kind=match.kind,
            reasons=list(match.reasons),
        )
        if match.kind == EXCLUDED:
            excluded_contracts.add(contract.contract_id)
            rows.append(PlanRow(kind="contract", note=NOTE_EXCLUDED, **base))
            continue
        if match.kind == NONE:
            contracts_without.add(contract.contract_id)
            rows.append(PlanRow(kind="contract", note=NOTE_NO_FOLDER, **base))
            continue
        if match.kind == AMBIGUOUS:
            ambiguous_contracts.add(contract.contract_id)
            ambiguous_folders.update(match.candidates)
            rows.append(
                PlanRow(
                    kind="contract",
                    note=NOTE_AMBIGUOUS.format(names=", ".join(match.candidates)),
                    **base,
                )
            )
            continue
        assert match.folder is not None and match.kind in (SURE, UNCERTAIN)
        folder_name = match.folder.name
        used_folders.add(folder_name)
        importable = [
            f
            for f in files_by_folder.get(folder_name, [])
            if is_importable(f.relative_path)
            and (f.size is None or f.size <= MAX_FILE_BYTES)
        ]
        if not importable:
            contracts_without.add(contract.contract_id)
            rows.append(
                PlanRow(
                    kind="contract",
                    folder_name=folder_name,
                    note=NOTE_EMPTY_FOLDER,
                    **base,
                )
            )
            continue
        contracts_with_docs.add(contract.contract_id)
        if match.kind == UNCERTAIN:
            uncertain_contracts.add(contract.contract_id)
        for listed in sorted(importable, key=lambda f: f.relative_path.casefold()):
            classified = classify_filename(listed.relative_path)
            rows.append(
                PlanRow(
                    kind="assignment",
                    folder_name=folder_name,
                    file_name=listed.relative_path,
                    item_id=listed.item_id,
                    size_bytes=listed.size,
                    doc_type=classified.doc_type.value,
                    note=classified.note,
                    status="pending",
                    **base,
                )
            )

    folders_without_contract = 0
    for name in sorted(folder_names, key=str.casefold):
        if name in used_folders:
            continue
        if is_excluded_folder(name):
            kind, note = EXCLUDED, NOTE_EXCLUDED
        elif name in ambiguous_folders:
            kind, note = AMBIGUOUS, NOTE_FOLDER_AMBIGUOUS
        else:
            kind, note = NONE, NOTE_FOLDER_WITHOUT_CONTRACT
            folders_without_contract += 1
        rows.append(
            PlanRow(kind="folder", folder_name=name, note=note, match_kind=kind)
        )
        for listed in files_by_folder.get(name, []):
            rows.append(
                PlanRow(
                    kind="file",
                    folder_name=name,
                    file_name=listed.relative_path,
                    item_id=listed.item_id,
                    size_bytes=listed.size,
                    match_kind=kind,
                    note=note,
                )
            )

    skipped_extension = skipped_size = 0
    for name in sorted(used_folders, key=str.casefold):
        for listed in files_by_folder.get(name, []):
            if not is_importable(listed.relative_path):
                skipped_extension += 1
                note = NOTE_SKIPPED_EXTENSION
            elif listed.size is not None and listed.size > MAX_FILE_BYTES:
                skipped_size += 1
                note = NOTE_SKIPPED_SIZE
            else:
                continue
            rows.append(
                PlanRow(
                    kind="file",
                    folder_name=name,
                    file_name=listed.relative_path,
                    item_id=listed.item_id,
                    size_bytes=listed.size,
                    note=note,
                )
            )
    for listed in loose:
        rows.append(
            PlanRow(
                kind="file",
                file_name=listed.relative_path,
                item_id=listed.item_id,
                size_bytes=listed.size,
                note=NOTE_LOOSE_FILE,
            )
        )

    assignments = [r for r in rows if r.kind == "assignment"]
    counters: dict[str, int] = {
        "contracts_total": len(matches),
        "contracts_with_documents": len(contracts_with_docs),
        "contracts_without_documents": len(contracts_without),
        "contracts_uncertain": len(uncertain_contracts),
        "contracts_ambiguous": len(ambiguous_contracts),
        "contracts_excluded": len(excluded_contracts),
        "folders_total": len(folder_names),
        "folders_without_contract": folders_without_contract,
        "files_listed": len(files),
        "assignments": len(assignments),
        "assignments_uncertain": sum(
            1 for r in assignments if r.match_kind == UNCERTAIN
        ),
        "files_skipped_extension": skipped_extension,
        "files_skipped_size": skipped_size,
        "files_loose": len(loose),
    }
    return Plan(rows=rows, counters=counters)


def row_dict(row: PlanRow) -> dict[str, Any]:
    return {
        "kind": row.kind,
        "folder_name": row.folder_name,
        "file_name": row.file_name,
        "item_id": row.item_id,
        "size_bytes": row.size_bytes,
        "doc_type": row.doc_type,
        "contract_id": row.contract_id,
        "candidate_id": row.candidate_id,
        "person_name": row.person_name,
        "match_kind": row.match_kind,
        "reasons": list(row.reasons),
        "note": row.note,
        "selected": row.selected,
        "status": row.status,
    }
