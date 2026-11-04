"""Import umów ramowych i aneksów klientów z paczki plików (30.10.2026).

Dział trzyma umowy na OneDrive: folder per klient, a w nim umowa i aneksy.
W NEXUSIE jest 39 rekordów umów z datami, ale prawie bez plików. Import dokłada
plik do istniejącego rekordu, zakłada brakujące umowy i aneksy.

Co jest czym, wskazuje człowiek w manifeście JSON (poza repo, bo niesie nazwy
klientów i plików): nazwa pliku nie mówi prawdy („Umowa Bosch.pdf” to umowa
powierzenia, a w folderach zamówień leżą aneksy do zamówień). Daty też idą
z manifestu — treść e-podpisanej umowy zwykle nie ma daty zawarcia.

Bieg jest idempotentny, a paragon w ``app_settings`` (same liczby i ID) pozwala
go cofnąć. Istniejącego pliku import nie nadpisuje.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.client_contract_amendment import ClientContractAmendment
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractSignedVia,
    FrameworkContractStatus,
)
from app.services import storage_service

SOURCE_SYSTEM = "client_contract_docs"
RECEIPT_KEY_PREFIX = "client_contract_docs_import_"
MAX_FILE_BYTES = 100 * 1024 * 1024
ALLOWED_SUFFIXES = (".pdf", ".docx")

ATTACH = "attach_file"
CREATE_CONTRACT = "create_contract"
CREATE_AMENDMENT = "create_amendment"
ALREADY_DONE = "already_done"
HAS_OTHER_FILE = "has_other_file"
BLOCKED = "blocked"


class ManifestDocument(BaseModel):
    key: str = Field(..., min_length=1, max_length=200)
    kind: Literal["contract", "amendment"]
    client_id: int
    # Bezpiecznik: identyfikatory z kopii bazy mogą się rozjechać z produkcją.
    client_name: Optional[str] = None
    source: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    framework_contract_id: Optional[int] = None
    contract_key: Optional[str] = None
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    status: FrameworkContractStatus = FrameworkContractStatus.active

    @model_validator(mode="after")
    def _kind_rules(self) -> "ManifestDocument":
        if self.kind == "amendment":
            if self.effective_date is None:
                raise ValueError(f"{self.key}: aneks musi mieć datę")
            if (self.framework_contract_id is None) == (self.contract_key is None):
                raise ValueError(
                    f"{self.key}: aneks wskazuje framework_contract_id albo contract_key"
                )
        return self


class Manifest(BaseModel):
    documents: list[ManifestDocument]

    @model_validator(mode="after")
    def _unique_keys(self) -> "Manifest":
        keys = [document.key for document in self.documents]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ValueError(f"Powtórzone klucze: {duplicates}")
        contracts = {d.key for d in self.documents if d.kind == "contract"}
        for document in self.documents:
            if document.contract_key and document.contract_key not in contracts:
                raise ValueError(
                    f"{document.key}: nie ma umowy o kluczu {document.contract_key}"
                )
        return self


@dataclass
class PlanRow:
    key: str
    kind: str
    action: str
    reason: Optional[str] = None
    framework_contract_id: Optional[int] = None
    amendment_id: Optional[int] = None


@dataclass
class ImportReport:
    manifest_sha256: str
    rows: list[PlanRow] = field(default_factory=list)
    applied: bool = False
    receipt_key: Optional[str] = None

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row.action] = counts.get(row.action, 0) + 1
        return counts

    @property
    def blocked(self) -> list[PlanRow]:
        return [row for row in self.rows if row.action == BLOCKED]


def load_manifest(raw: bytes) -> tuple[Manifest, str]:
    return Manifest.model_validate(json.loads(raw)), hashlib.sha256(raw).hexdigest()


def _source_key(document: ManifestDocument) -> str:
    return hashlib.sha256(document.key.encode("utf-8")).hexdigest()[:32]


def _source_problem(root: Path, document: ManifestDocument) -> Optional[str]:
    """Plik musi leżeć w katalogu paczki, mieć dozwolony typ i rozmiar."""
    path = (root / document.source).resolve()
    if not path.is_relative_to(root.resolve()):
        return "plik poza katalogiem paczki"
    if not path.is_file():
        return "brak pliku w paczce"
    if not document.filename.lower().endswith(ALLOWED_SUFFIXES):
        return "tylko PDF albo DOCX"
    if path.stat().st_size > MAX_FILE_BYTES:
        return "plik większy niż 100 MB"
    return None


async def _plan_contract(
    db: AsyncSession, document: ManifestDocument
) -> tuple[PlanRow, Optional[ClientFrameworkContract]]:
    row = PlanRow(key=document.key, kind=document.kind, action=CREATE_CONTRACT)
    contract: Optional[ClientFrameworkContract] = None
    if document.framework_contract_id is not None:
        contract = await db.get(ClientFrameworkContract, document.framework_contract_id)
        if contract is None or contract.client_id != document.client_id:
            row.action, row.reason = BLOCKED, "rekord umowy nie należy do tego klienta"
            return row, None
    else:
        contract = await db.scalar(
            select(ClientFrameworkContract).where(
                ClientFrameworkContract.source_system == SOURCE_SYSTEM,
                ClientFrameworkContract.source_key == _source_key(document),
            )
        )
    if contract is None:
        return row, None
    row.framework_contract_id = contract.id
    if contract.file_path is None:
        row.action = ATTACH
    elif contract.filename == document.filename:
        row.action = ALREADY_DONE
    else:
        row.action, row.reason = HAS_OTHER_FILE, "rekord ma już inny plik"
    return row, contract


async def _plan_amendment(
    db: AsyncSession,
    document: ManifestDocument,
    parents: dict[str, PlanRow],
) -> PlanRow:
    row = PlanRow(key=document.key, kind=document.kind, action=CREATE_AMENDMENT)
    if document.contract_key is not None:
        parent = parents[document.contract_key]
        if parent.action == BLOCKED:
            row.action, row.reason = BLOCKED, "umowa z manifestu jest zablokowana"
            return row
        row.framework_contract_id = parent.framework_contract_id
    else:
        contract = await db.get(ClientFrameworkContract, document.framework_contract_id)
        if contract is None or contract.client_id != document.client_id:
            row.action, row.reason = BLOCKED, "rekord umowy nie należy do tego klienta"
            return row
        row.framework_contract_id = contract.id
    if row.framework_contract_id is None:
        return row
    existing = await db.scalar(
        select(ClientContractAmendment.id).where(
            ClientContractAmendment.framework_contract_id == row.framework_contract_id,
            ClientContractAmendment.filename == document.filename,
            ClientContractAmendment.effective_date == document.effective_date,
        )
    )
    if existing is not None:
        row.action, row.amendment_id = ALREADY_DONE, int(existing)
    return row


async def build_plan(
    db: AsyncSession, manifest: Manifest, sha: str, root: Path
) -> ImportReport:
    """Co zrobi bieg, bez żadnego zapisu."""
    report = ImportReport(manifest_sha256=sha)
    parents: dict[str, PlanRow] = {}
    # Umowy pierwsze: aneks może wskazywać umowę z tego samego manifestu.
    ordered = sorted(manifest.documents, key=lambda d: d.kind != "contract")
    for document in ordered:
        problem = _source_problem(root, document)
        client = await db.get(Client, document.client_id)
        if client is None or client.deleted_at is not None:
            problem = "klient nie istnieje albo jest usunięty"
        elif document.client_name and client.name.strip() != document.client_name:
            problem = "nazwa klienta inna niż w manifeście"
        if problem is not None:
            row = PlanRow(document.key, document.kind, BLOCKED, problem)
        elif document.kind == "contract":
            row, _contract = await _plan_contract(db, document)
        else:
            row = await _plan_amendment(db, document, parents)
        if document.kind == "contract":
            parents[document.key] = row
        report.rows.append(row)
    return report


def _save_contract_file(root: Path, document: ManifestDocument) -> tuple[str, int]:
    with (root / document.source).open("rb") as source:
        return storage_service.save_client_framework_contract(
            client_id=document.client_id,
            upload_filename=document.filename,
            source=source,
        )


def _attach(
    contract: ClientFrameworkContract,
    document: ManifestDocument,
    relative_path: str,
    size: int,
) -> None:
    contract.filename = document.filename
    contract.file_path = relative_path
    contract.size_bytes = size
    contract.content_type = (
        "application/pdf" if document.filename.lower().endswith(".pdf") else None
    )
    contract.uploaded_at = datetime.now(timezone.utc)


async def apply_import(
    db: AsyncSession, manifest: Manifest, sha: str, root: Path
) -> ImportReport:
    """Zapisuje plan. Blokada w planie = zero zapisu."""
    report = await build_plan(db, manifest, sha, root)
    if report.blocked:
        return report
    documents = {document.key: document for document in manifest.documents}
    attached: list[int] = []
    created_contracts: list[int] = []
    created_amendments: list[int] = []
    contract_ids: dict[str, int] = {}

    for row in report.rows:
        document = documents[row.key]
        if row.kind == "contract" and row.framework_contract_id is not None:
            contract_ids[row.key] = row.framework_contract_id
        if row.action == ATTACH:
            contract = await db.get(ClientFrameworkContract, row.framework_contract_id)
            relative_path, size = _save_contract_file(root, document)
            _attach(contract, document, relative_path, size)
            attached.append(contract.id)
        elif row.action == CREATE_CONTRACT:
            relative_path, size = _save_contract_file(root, document)
            contract = ClientFrameworkContract(
                client_id=document.client_id,
                name=document.name,
                status=document.status,
                effective_date=document.effective_date,
                expiry_date=document.expiry_date,
                signed_via=FrameworkContractSignedVia.upload,
                source_system=SOURCE_SYSTEM,
                source_key=_source_key(document),
            )
            _attach(contract, document, relative_path, size)
            db.add(contract)
            await db.flush()
            row.framework_contract_id = contract.id
            contract_ids[row.key] = contract.id
            created_contracts.append(contract.id)
        elif row.action == CREATE_AMENDMENT:
            parent_id = (
                document.framework_contract_id or contract_ids[document.contract_key]
            )
            with (root / document.source).open("rb") as source:
                relative_path, size = storage_service.save_client_contract_amendment(
                    framework_contract_id=parent_id,
                    upload_filename=document.filename,
                    source=source,
                )
            amendment = ClientContractAmendment(
                framework_contract_id=parent_id,
                name=document.name,
                effective_date=document.effective_date,
                filename=document.filename,
                file_path=relative_path,
                size_bytes=size,
                content_type=(
                    "application/pdf"
                    if document.filename.lower().endswith(".pdf")
                    else None
                ),
                uploaded_at=datetime.now(timezone.utc),
            )
            db.add(amendment)
            await db.flush()
            row.framework_contract_id = parent_id
            row.amendment_id = amendment.id
            created_amendments.append(amendment.id)
        else:
            continue
        db.add(
            Activity(
                entity_type="client",
                entity_id=document.client_id,
                action="framework_contract_document_imported",
                details={
                    "kind": row.kind,
                    "fc_id": row.framework_contract_id,
                    "amendment_id": row.amendment_id,
                },
            )
        )
        await db.commit()

    receipt_key = f"{RECEIPT_KEY_PREFIX}{sha[:12]}"
    receipt = await db.get(AppSetting, receipt_key)
    previous = receipt.value if receipt is not None else {}
    value = {
        "manifest_sha256": sha,
        "applied_at": previous.get("applied_at")
        or datetime.now(timezone.utc).isoformat(),
        "attached_contract_ids": [
            *previous.get("attached_contract_ids", []),
            *attached,
        ],
        "created_contract_ids": [
            *previous.get("created_contract_ids", []),
            *created_contracts,
        ],
        "created_amendment_ids": [
            *previous.get("created_amendment_ids", []),
            *created_amendments,
        ],
    }
    if receipt is None:
        db.add(AppSetting(key=receipt_key, value=value))
    else:
        receipt.value = value
    await db.commit()
    report.applied = True
    report.receipt_key = receipt_key
    return report


async def undo_import(db: AsyncSession, receipt_key: str) -> dict[str, int]:
    """Cofa bieg z paragonu: usuwa to, co założył, i zdejmuje dołożone pliki."""
    receipt = await db.get(AppSetting, receipt_key)
    if receipt is None or not receipt_key.startswith(RECEIPT_KEY_PREFIX):
        raise ValueError("Nie ma takiego paragonu importu.")
    value = receipt.value
    files: list[tuple[str, str]] = []
    amendments = 0
    for amendment_id in value.get("created_amendment_ids", []):
        amendment = await db.get(ClientContractAmendment, amendment_id)
        if amendment is not None:
            if amendment.file_path:
                files.append(("amendment", amendment.file_path))
            await db.delete(amendment)
            amendments += 1
    contracts = 0
    for contract_id in value.get("created_contract_ids", []):
        contract = await db.get(ClientFrameworkContract, contract_id)
        if contract is not None:
            if contract.file_path:
                files.append(("contract", contract.file_path))
            await db.delete(contract)
            contracts += 1
    detached = 0
    for contract_id in value.get("attached_contract_ids", []):
        contract = await db.get(ClientFrameworkContract, contract_id)
        if contract is not None and contract.file_path:
            files.append(("contract", contract.file_path))
            contract.file_path = None
            contract.filename = None
            contract.size_bytes = None
            contract.content_type = None
            contract.uploaded_at = None
            detached += 1
    await db.delete(receipt)
    await db.commit()
    # Pliki kasujemy PO udanym commicie, jak trasy umów (audyt W3).
    for kind, path in files:
        if kind == "amendment":
            storage_service.delete_client_contract_amendment(path)
        else:
            storage_service.delete_client_framework_contract(path)
    return {
        "amendments_deleted": amendments,
        "contracts_deleted": contracts,
        "files_detached": detached,
    }
