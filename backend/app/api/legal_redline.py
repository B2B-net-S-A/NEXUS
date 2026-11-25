"""„Popraw dokument” — umowa jako DOCX ze śledzeniem zmian i komentarzami.

``POST /api/legal/redline`` — dokument (plik albo dokument kontraktu) →
         akapity i propozycje zmian (model ``legal_redline`` albo porównanie
         z nową wersją tekstu ``new_text``; bez obu — same akapity do ręcznych zmian).
``POST /api/legal/redline/render`` — ten sam dokument + przyjęte zmiany → DOCX.

Bramki jak pobranie dokumentu kontraktu (pliki umów niosą stawki): sekcja
Delivery, „Stawki i kwoty: podgląd” (``AmountsViewUser``) i zakres klienta
Delivery Leada (``_assert_contract_document_client_access``). Plik z dysku
też idzie w kontekście kontraktu (``contract_id``) albo wiersza rejestru
Generatora (``generated_id``, bramka pobrania DOCX z rejestru) — z niego są
nazwiska i firmy, które przed modelem zamieniamy na znaczniki.

Niczego nie zapisujemy: wynik trafia do Dokumentów kontraktu zwykłym
„Dodaj plik” (``POST /api/contracts/{id}/documents``) z panelu.
Reguła: ``docs/claude/asystent-prawny/popraw-dokument-docx-ze-sledzeniem-zmian.md``.
"""

import hashlib
import json
import logging
import re
from dataclasses import replace
from pathlib import PurePath
from typing import Any, Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.api.b2b_contract_generator import _load_generated_for_download
from app.api.contracts import _assert_contract, _assert_contract_document_client_access
from app.api.permission_access import AmountsViewUser
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import local_now
from app.models.client import Client
from app.models.contract import Contract
from app.models.contract_document import ContractDocument
from app.models.user import User
from app.services import storage_service
from app.services.legal_redline import proposals
from app.services.legal_redline.diff import DiffTooLarge, diff_texts
from app.services.legal_redline.docx_io import load_package, read_paragraphs
from app.services.legal.pseudonymize import partner_entities
from app.services.legal_redline.foundation import Entity, SourcePassage, verify_sources
from app.services.legal_redline.model import (
    ChangeSource,
    NotADocxError,
    RedlineChange,
    RedlineError,
)
from app.services.legal_redline.tracked import apply_changes

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_INSTRUCTION = 4000
MAX_NEW_TEXT = 400_000
MAX_CHANGES = 300


class ParagraphOut(BaseModel):
    index: int
    text: str
    style: Optional[str] = None
    in_table: bool = False
    heading: bool = False


class SourceIO(BaseModel):
    ref: str = Field(..., max_length=200)
    label: str = Field("", max_length=300)
    quote: str = Field("", max_length=4000)
    kind: str = Field("law", max_length=20)
    url: Optional[str] = Field(None, max_length=1000)
    state: Literal["ok", "missing", "mismatch"] = "ok"


class ChangeIO(BaseModel):
    id: str = Field(..., max_length=40)
    kind: Literal["replace", "insert_paragraph", "delete_paragraph"]
    paragraph: int = Field(..., ge=0)
    new_text: str = Field("", max_length=20_000)
    find: str = Field("", max_length=20_000)
    start: Optional[int] = Field(None, ge=0)
    end: Optional[int] = Field(None, ge=0)
    before: bool = False
    reason: str = Field("", max_length=4000)
    sources: list[SourceIO] = Field(default_factory=list, max_length=20)
    blocked: bool = False


class DroppedOut(BaseModel):
    paragraph: Optional[int] = None
    reason: str


class SourceFileOut(BaseModel):
    name: str
    sha256: str
    contract_id: Optional[int] = None
    document_id: Optional[int] = None
    generated_id: Optional[int] = None


class AiOut(BaseModel):
    status: str
    model: Optional[str] = None


class RedlineOut(BaseModel):
    source: SourceFileOut
    paragraphs: list[ParagraphOut]
    changes: list[ChangeIO]
    notes: list[str] = Field(default_factory=list)
    dropped: list[DroppedOut] = Field(default_factory=list)
    ai: AiOut


def _change_out(change: RedlineChange) -> ChangeIO:
    return ChangeIO(
        id=change.id,
        kind=change.kind,
        paragraph=change.paragraph,
        new_text=change.new_text,
        find=change.find,
        start=change.start,
        end=change.end,
        before=change.before,
        reason=change.reason,
        sources=[SourceIO(**s.__dict__) for s in change.sources],
        blocked=change.blocked,
    )


def _change_in(change: ChangeIO) -> RedlineChange:
    return RedlineChange(
        id=change.id,
        kind=change.kind,
        paragraph=change.paragraph,
        new_text=change.new_text,
        find=change.find,
        start=change.start,
        end=change.end,
        before=change.before,
        reason=change.reason,
        sources=tuple(
            ChangeSource(
                ref=s.ref,
                label=s.label,
                quote=s.quote,
                kind=s.kind,
                url=s.url,
                state=s.state,
            )
            for s in change.sources
        ),
    )


# ── źródło dokumentu ────────────────────────────────────────────────────────


class _Source:
    def __init__(
        self,
        data: bytes,
        name: str,
        *,
        contract: Optional[Contract] = None,
        document_id: Optional[int] = None,
        generated_id: Optional[int] = None,
        entities: Optional[list[Entity]] = None,
    ) -> None:
        self.data = data
        self.name = name
        self.contract = contract
        self.document_id = document_id
        self.generated_id = generated_id
        self.entities = entities or []

    def out(self) -> SourceFileOut:
        return SourceFileOut(
            name=self.name,
            sha256=hashlib.sha256(self.data).hexdigest(),
            contract_id=self.contract.id if self.contract else None,
            document_id=self.document_id,
            generated_id=self.generated_id,
        )


def _client_entities(name: Optional[str]) -> list[Entity]:
    return [Entity("KLIENT", name.strip())] if name and name.strip() else []


async def _contract_entities(db: AsyncSession, contract: Contract) -> list[Entity]:
    """Partner kontraktu (umowa z Generatora, a bez niej karta osoby) i klient."""
    from app.services.trainings.agreement import partner_from_contract  # noqa: PLC0415

    out = partner_entities(await partner_from_contract(db, contract.id))
    if contract.client_id:
        client = await db.get(Client, contract.client_id)
        if client is not None:
            out += _client_entities(client.legal_name)
            out += _client_entities(client.name)
    return out


def generated_entities(row: Any) -> list[Entity]:
    """Dane z wiersza rejestru Generatora (``render_payload``, potem kolumny)."""
    from app.services.trainings.agreement import partner_from_sources  # noqa: PLC0415

    partner = partner_from_sources(contract=None, generated=row)
    return partner_entities(partner) + _client_entities(row.client_name)


def _docx_name(name: Optional[str]) -> str:
    name = PurePath(name or "dokument.docx").name
    if not name.lower().endswith(".docx"):
        raise HTTPException(
            status_code=422,
            detail="„Popraw dokument” działa na plikach Worda (DOCX). Zapisz plik jako .docx i spróbuj ponownie.",
        )
    return name


async def _load_source(
    db: AsyncSession,
    current_user: User,
    *,
    file: Optional[UploadFile],
    contract_id: Optional[int],
    document_id: Optional[int],
    generated_id: Optional[int],
) -> _Source:
    contract: Optional[Contract] = None
    entities: list[Entity] = []
    if contract_id is not None:
        contract = await _assert_contract(db, contract_id, current_user)
        await _assert_contract_document_client_access(contract, current_user, db)
        entities += await _contract_entities(db, contract)
    if generated_id is not None:
        row = await _load_generated_for_download(db, current_user, generated_id)
        entities += generated_entities(row)
    if contract is None and generated_id is None:
        raise HTTPException(
            status_code=422,
            detail="Wskaż kontrakt albo umowę z rejestru Generatora, do której należy dokument.",
        )

    if document_id is not None:
        if contract is None:
            raise HTTPException(
                status_code=422, detail="Dokument kontraktu wymaga numeru kontraktu."
            )
        doc = await db.scalar(
            select(ContractDocument).where(
                ContractDocument.id == document_id,
                ContractDocument.contract_id == contract.id,
            )
        )
        if doc is None:
            raise HTTPException(
                status_code=404, detail="Nie ma takiego dokumentu w tym kontrakcie."
            )
        name = _docx_name(doc.filename)
        try:
            path = storage_service.get_contract_document_path(doc.file_path)
            data = await run_in_threadpool(path.read_bytes)
        except (FileNotFoundError, OSError):
            raise HTTPException(
                status_code=410, detail="Pliku nie ma już na dysku — wgraj go ponownie."
            )
        return _Source(
            data, name, contract=contract, document_id=doc.id, entities=entities
        )

    if file is None:
        raise HTTPException(
            status_code=422, detail="Dodaj plik DOCX albo wskaż dokument kontraktu."
        )
    name = _docx_name(file.filename)
    # Odczyt z sufitem (wzorzec ``_read_upload_bounded``): za duży plik nie
    # trafia w całości do pamięci procesu.
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Plik jest za duży (limit {settings.MAX_UPLOAD_SIZE_MB} MB).",
        )
    return _Source(
        data, name, contract=contract, generated_id=generated_id, entities=entities
    )


def _paragraphs(data: bytes):
    try:
        return read_paragraphs(load_package(data))
    except NotADocxError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ── trasy ───────────────────────────────────────────────────────────────────


@router.post("/redline", response_model=RedlineOut)
async def propose_redline(
    current_user: AmountsViewUser,
    db: AsyncSession = Depends(get_db),
    file: Optional[UploadFile] = File(None),
    contract_id: Optional[int] = Form(None),
    document_id: Optional[int] = Form(None),
    generated_id: Optional[int] = Form(None),
    instruction: str = Form("", max_length=MAX_INSTRUCTION),
    new_text: Optional[str] = Form(None, max_length=MAX_NEW_TEXT),
    use_ai: bool = Form(True),
):
    """Akapity dokumentu i propozycje zmian.

    ``new_text`` (poprawiona treść, akapity w wierszach) → zmiany z porównania,
    bez modelu. Inaczej, gdy jest polecenie i ``use_ai`` — propozycje modelu.
    """
    source = await _load_source(
        db,
        current_user,
        file=file,
        contract_id=contract_id,
        document_id=document_id,
        generated_id=generated_id,
    )
    paragraphs = await run_in_threadpool(_paragraphs, source.data)
    source_out = source.out()
    paragraphs_out = [ParagraphOut(**p.__dict__) for p in paragraphs]

    if new_text is not None:
        try:
            # Porównanie to czysty CPU — w wątku, żeby nie stawało pętli zdarzeń.
            changes = await run_in_threadpool(
                diff_texts, [p.text for p in paragraphs], new_text
            )
        except DiffTooLarge as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return RedlineOut(
            source=source_out,
            paragraphs=paragraphs_out,
            changes=[_change_out(c) for c in changes],
            ai=AiOut(status="diff"),
        )
    if not use_ai:
        return RedlineOut(
            source=source_out,
            paragraphs=paragraphs_out,
            changes=[],
            ai=AiOut(status="manual"),
        )
    proposal = await proposals.propose(
        db,
        paragraphs=paragraphs,
        instruction=instruction,
        entities=source.entities,
        user_id=current_user.id,
    )
    return RedlineOut(
        source=source_out,
        paragraphs=paragraphs_out,
        changes=[_change_out(c) for c in proposal.changes],
        notes=proposal.notes,
        dropped=[
            DroppedOut(paragraph=d.paragraph, reason=d.reason) for d in proposal.dropped
        ],
        ai=AiOut(status=proposal.status, model=proposal.model),
    )


#: Znaki spoza XML 1.0 (``\x00``, ``\x0b`` …): lxml nie zapisze ich w DOCX.
_XML_FORBIDDEN = re.compile("[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def _parse_changes(raw: str) -> list[ChangeIO]:
    try:
        items = json.loads(raw)
    except ValueError:
        raise HTTPException(
            status_code=422, detail="Lista zmian nie jest poprawnym JSON-em."
        )
    if not isinstance(items, list) or len(items) > MAX_CHANGES:
        raise HTTPException(
            status_code=422, detail=f"Lista zmian: najwyżej {MAX_CHANGES} pozycji."
        )
    try:
        parsed = [ChangeIO.model_validate(item) for item in items]
    except ValidationError:
        raise HTTPException(status_code=422, detail="Lista zmian ma złe pola.")
    for change in parsed:
        texts = [change.new_text, change.find, change.reason]
        texts += [t for s in change.sources for t in (s.quote, s.label, s.ref)]
        if any(_XML_FORBIDDEN.search(t) for t in texts):
            raise HTTPException(
                status_code=422,
                detail=f"Zmiana {change.id} ma niedozwolone znaki sterujące — usuń je z tekstu.",
            )
    return parsed


def _law_target(ref: str) -> Optional[tuple[str, str]]:
    """(klucz aktu, jednostka) z ``ref`` cytatu: „kc art. 77 § 1” (``search_law``)
    albo „art. 77 § 1 KC”."""
    from app.services.legal import citations, corpus  # noqa: PLC0415

    head, _sep, rest = ref.strip().partition(" ")
    if head.lower() in corpus.act_keys() and rest.lower().startswith("art"):
        return head.lower(), rest.strip()
    found = next(
        (
            c
            for c in citations.extract(ref)
            if c.kind == citations.KIND_LAW and c.act_key
        ),
        None,
    )
    return (found.act_key, found.ref) if found else None


async def _source_passage(
    db: AsyncSession,
    source: ChangeSource,
    document: SourcePassage,
    contract: Optional[Contract],
    client_cache: dict[str, list[SourcePassage]],
) -> Optional[SourcePassage]:
    """Fragment źródła z bazy dla cytatu; ``None`` = nie da się sprawdzić (blokada)."""
    from app.services.legal import corpus, letter_service  # noqa: PLC0415

    if source.ref == proposals.DOCUMENT_REF:
        return document
    try:
        if source.kind == "law":
            target = _law_target(source.ref)
            if target is None:
                return None
            hit = await corpus.get_provision(
                db, target[0], target[1], nearest_parent=True
            )
            return corpus.as_passage(hit) if hit is not None else None
        if source.kind == "client" and contract is not None:
            if "client" not in client_cache:
                client_cache["client"] = await letter_service.client_passages(
                    db, contract.client_id
                )
            return next(
                (p for p in client_cache["client"] if p.ref == source.ref), None
            )
    except Exception as exc:  # noqa: BLE001 — bez źródła cytat jest bez pokrycia
        logger.warning(
            "legal_redline: źródło cytatu nieczytelne (%s)", type(exc).__name__
        )
    return None


async def recheck_changes(
    db: AsyncSession,
    items: list[ChangeIO],
    document: SourcePassage,
    *,
    contract: Optional[Contract],
) -> list[RedlineChange]:
    """Każdy cytat każdej zmiany sprawdzony ze źródłem z bazy (przepis z korpusu,
    umowa ramowa klienta, sam dokument). Rodzaj, którego serwer nie umie
    wczytać (orzeczenie, wzór), jest ``missing``. Zmiana bez pokrycia → 422."""
    out: list[RedlineChange] = []
    client_cache: dict[str, list[SourcePassage]] = {}
    for item in items:
        change = _change_in(item)
        checked: list[ChangeSource] = []
        for source in change.sources:
            passage = await _source_passage(
                db, source, document, contract, client_cache
            )
            if passage is None:
                checked.append(replace(source, state="missing"))
                continue
            checked.extend(verify_sources([source], [replace(passage, ref=source.ref)]))
        change = replace(change, sources=tuple(checked))
        if change.blocked:
            raise HTTPException(
                status_code=422,
                detail=f"Zmiana {change.id} ma cytat bez pokrycia w źródle — popraw ją albo usuń cytat.",
            )
        out.append(change)
    return out


OUTPUT_SUFFIX = " — poprawki asystenta"


def _output_name(name: str) -> str:
    """Nazwa pliku wyniku; druga runda poprawek nie dokleja dopisku drugi raz."""
    stem = name[: -len(".docx")] if name.lower().endswith(".docx") else name
    if not stem.endswith(OUTPUT_SUFFIX):
        stem += OUTPUT_SUFFIX
    return f"{stem}.docx"


def _content_disposition(name: str) -> str:
    ascii_name = name.encode("ascii", "ignore").decode() or "poprawki.docx"
    ascii_name = ascii_name.replace('"', "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


@router.post("/redline/render")
async def render_redline(
    current_user: AmountsViewUser,
    db: AsyncSession = Depends(get_db),
    changes: str = Form(..., max_length=2_000_000),
    file: Optional[UploadFile] = File(None),
    contract_id: Optional[int] = Form(None),
    document_id: Optional[int] = Form(None),
    generated_id: Optional[int] = Form(None),
    sha256: Optional[str] = Form(None, max_length=64),
):
    """Przyjęte zmiany → DOCX ze śledzeniem zmian (autor „Asystent NEXUS”) i komentarzami.

    Cytat bez pokrycia blokuje zmianę (422). Każdy cytat sprawdzamy tu jeszcze
    raz ze źródłem z bazy (``recheck_changes``), a ``state`` z przeglądarki się
    nie liczy — wynik z ``/redline`` mógł przyjść zmieniony. ``sha256``
    z ``/redline`` pilnuje, że to ten sam plik.
    """
    items = _parse_changes(changes)
    source = await _load_source(
        db,
        current_user,
        file=file,
        contract_id=contract_id,
        document_id=document_id,
        generated_id=generated_id,
    )
    if sha256 and sha256 != hashlib.sha256(source.data).hexdigest():
        raise HTTPException(
            status_code=409,
            detail="Plik zmienił się od przygotowania zmian — otwórz „Popraw dokument” jeszcze raz.",
        )
    paragraphs = await run_in_threadpool(_paragraphs, source.data)
    document = SourcePassage(
        kind="contract",
        ref=proposals.DOCUMENT_REF,
        text="\n".join(p.text for p in paragraphs),
        label="Dokument",
    )
    redline = await recheck_changes(db, items, document, contract=source.contract)
    try:
        data = await run_in_threadpool(
            apply_changes, source.data, redline, when=local_now().replace(tzinfo=None)
        )
    except NotADocxError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RedlineError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "redline_conflict",
                "message": str(exc),
                "change_id": exc.change_id,
            },
        )
    name = _output_name(source.name)
    return Response(
        content=data,
        media_type=DOCX_MIME,
        headers={"Content-Disposition": _content_disposition(name)},
    )
