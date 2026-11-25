"""Wzory własne Generatora Umów B2B → zakładka Dokumenty (asystent prawny, B).

Trasy pod ``/api/b2b-generator/custom-templates`` obok dokumentów pochodnych:
ta sama bramka sekcji i ``B2BGeneratorAccess``. Tworzy, poprawia i zgłasza
wzór osoba z prawem generowania dokumentów (``_require_contract_generation``);
szkic widzi i zmienia jego autor albo administrator; zatwierdza, zwraca
i wycofuje wyłącznie administrator (``AdminUser``). Dokument ze wzoru własnego
trafia do rejestru dokumentów Generatora (``b2b_contract_documents``) i nie ma
żadnych skutków w kontraktach. Reguła: ``docs/claude/asystent-prawny/``.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any, Optional

import docx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.b2b_contract_generator import (
    _ascii_filename,
    _assert_generator_client_access,
    _load_legal_scoped_job,
    _require_contract_generation,
    _require_generator_rate_content,
    _validate_candidate_job_link,
)
from app.api.b2b_documents import _docx_response
from app.api.contract_access import B2BGeneratorAccess
from app.api.deps import AdminUser
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.b2b_contract_document import B2BContractDocument
from app.models.candidate import Candidate
from app.models.custom_document_template import (
    CustomDocumentTemplate,
    CustomDocumentTemplateVersion,
)
from app.models.user import User
from app.services.ai_quota import ai_feature
from app.services.client_access import assert_client_assignable
from app.services.custom_templates import draft as draft_mod
from app.services.custom_templates import sandbox
from app.services.custom_templates import service as svc
from app.services.custom_templates.base import BASES, BASES_BY_KEY, fields_from_paths
from app.services.custom_templates.detect import detect
from app.services.custom_templates.docx_ops import doc_to_html
from app.services.custom_templates.fields import (
    build_context,
    fields_to_json,
    sample_values,
    strip_sensitive,
    value_problems,
)

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

_DOCX_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
}
NO_MODEL = (
    "Asystent jest teraz niedostępny — szkic został bez zmian. Wgraj plik Word "
    "albo popraw wzór i spróbuj ponownie później."
)


# ── Modele żądań ────────────────────────────────────────────────────────────


class DraftRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=draft_mod.MAX_INSTRUCTION)


class SettingsRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    kind: Optional[str] = None
    client_scope: Optional[str] = None
    client_ids: Optional[list[int]] = None
    signatories: Optional[str] = None
    signature_form: Optional[str] = None
    fields: Optional[list[dict[str, Any]]] = None


class ReviewRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class CustomDocumentRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    candidate_id: Optional[int] = None
    job_id: Optional[int] = None
    client_id: Optional[int] = None


# ── Pomocnicze ──────────────────────────────────────────────────────────────


async def _names(db: AsyncSession, ids: set[int | None]) -> dict[int, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))
    return {uid: name for uid, name in rows.all()}


def _version_user_ids(versions: list[CustomDocumentTemplateVersion]) -> set[int | None]:
    return {
        uid for v in versions for uid in (v.created_by, v.submitted_by, v.reviewed_by)
    }


async def _read_docx(file: UploadFile) -> bytes:
    name = (file.filename or "").lower()
    if not name.endswith(".docx") or (file.content_type or "") not in _DOCX_TYPES:
        raise HTTPException(status_code=422, detail="Wgraj plik Word (.docx).")
    data = await file.read(sandbox.MAX_DOCX_BYTES + 1)
    if len(data) > sandbox.MAX_DOCX_BYTES:
        raise HTTPException(status_code=413, detail="Plik Word jest większy niż 5 MB.")
    return data


async def _detail(
    db: AsyncSession, user: User, template: CustomDocumentTemplate
) -> dict[str, Any]:
    versions = await svc.versions_of(db, template.id)
    working = svc.working_version(versions)
    active = svc.active_version(template, versions)
    names = await _names(db, _version_user_ids(versions) | {template.withdrawn_by})
    if working is not None and not svc.may_see_working(user, working):
        working = None
    if active is None and working is None:
        raise HTTPException(status_code=404, detail="Wzór nie istnieje.")
    return {
        "id": template.id,
        "withdrawn_at": template.withdrawn_at.isoformat()
        if template.withdrawn_at
        else None,
        "withdrawn_by_name": names.get(template.withdrawn_by or -1),
        "withdrawn_reason": template.withdrawn_reason,
        "working": svc.version_public(working, names=names) if working else None,
        "active": svc.version_public(active, names=names, with_content=working is None)
        if active
        else None,
        "history": [
            svc.version_public(v, names=names, with_content=False)
            for v in versions
            if v.status in ("approved", "withdrawn")
        ],
        "can_edit": working is not None and working.status == "draft",
        "can_review": svc.is_admin(user)
        and working is not None
        and working.status == "pending",
        "can_withdraw": svc.is_admin(user)
        and active is not None
        and template.withdrawn_at is None,
        "can_new_version": working is None and active is not None,
    }


async def _load_working(
    db: AsyncSession, user: User, template_id: int, *, lock: bool = True
) -> tuple[CustomDocumentTemplate, CustomDocumentTemplateVersion]:
    template = await svc.load_template(db, template_id, lock=lock)
    version = svc.working_version(await svc.versions_of(db, template.id))
    if version is None:
        raise HTTPException(status_code=409, detail="Ten wzór nie ma szkicu.")
    svc.assert_author(user, version)
    return template, version


def _apply_draft(
    version: CustomDocumentTemplateVersion, result: draft_mod.DraftResult
) -> None:
    svc.set_docx(version, result.docx)
    version.fields = fields_to_json(result.fields)
    version.changes = [*(version.changes or []), *result.changes]
    version.warnings = list(
        dict.fromkeys([*(version.warnings or []), *result.warnings])
    )
    version.ai_used = version.ai_used or result.ai_used
    if result.summary:
        version.description = version.description or result.summary
    if result.title and version.origin == "brief":
        version.name = result.title


async def _run_model(
    db: AsyncSession, user: User, prompt: str
) -> dict[str, Any] | None:
    if not draft_mod.model_available():
        return None
    try:
        async with ai_feature(db, draft_mod.FEATURE, user_id=user.id):
            await db.commit()  # połączenie wraca do puli na czas modelu
            return await draft_mod.ask(prompt)
    except Exception:  # noqa: BLE001 — wyłączona funkcja albo limit: szkic bez modelu
        await db.rollback()
        return None


async def _draft_with_model(
    db: AsyncSession,
    user: User,
    version_id: int,
    instruction: str,
) -> str | None:
    """Szkic zmian modelem na wersji roboczej. Zwraca komunikat dla człowieka,
    gdy model nie pomógł (szkic zostaje bez zmian)."""
    version = await db.get(CustomDocumentTemplateVersion, version_id)
    assert version is not None
    fields = svc.fields_of(version)
    if version.origin == "brief" and not version.fields:
        prompt = draft_mod.brief_prompt(instruction)
    else:
        prompt = await run_in_threadpool(
            draft_mod.change_prompt, version.docx, fields, instruction
        )
    data = await _run_model(db, user, prompt)
    version = await db.get(
        CustomDocumentTemplateVersion, version_id, populate_existing=True
    )
    assert version is not None
    if data is None:
        return NO_MODEL
    if version.origin == "brief" and not version.fields:
        result = await run_in_threadpool(draft_mod.build_from_brief, data)
    else:
        result = await run_in_threadpool(
            draft_mod.apply_changes, version.docx, fields, data, title=version.name
        )
    version.instruction = instruction
    _apply_draft(version, result)
    return None


# ── Trasy: lista, bazy, szczegóły ───────────────────────────────────────────


@router.get("/custom-templates/bases")
async def custom_template_bases(current_user: B2BGeneratorAccess) -> dict:
    """Wzory, od których można zacząć (z repo); zatwierdzone wzory własne
    przychodzą z listy wzorów."""
    return {
        "bases": [
            {"key": b.key, "label": b.label, "description": b.description}
            for b in BASES
        ],
        "model_available": draft_mod.model_available(),
    }


@router.get("/custom-templates")
async def list_custom_templates(
    current_user: B2BGeneratorAccess, db: AsyncSession = Depends(get_db)
) -> dict:
    """Wzory własne: zatwierdzone (wszyscy z Generatora) i robocze — własne,
    a administrator widzi wszystkie (zgłoszone czekają na niego)."""
    templates = list(
        await db.scalars(
            select(CustomDocumentTemplate).order_by(CustomDocumentTemplate.id.desc())
        )
    )
    versions = (
        list(
            await db.scalars(
                select(CustomDocumentTemplateVersion).where(
                    CustomDocumentTemplateVersion.template_id.in_(
                        [t.id for t in templates]
                    )
                )
            )
        )
        if templates
        else []
    )
    names = await _names(db, _version_user_ids(versions))
    by_template: dict[int, list[CustomDocumentTemplateVersion]] = {}
    for v in versions:
        by_template.setdefault(v.template_id, []).append(v)
    items: list[dict[str, Any]] = []
    for t in templates:
        own = by_template.get(t.id, [])
        working = svc.working_version(own)
        active = svc.active_version(t, own)
        visible_working = (
            working if working and svc.may_see_working(current_user, working) else None
        )
        shown = visible_working or active
        if shown is None:
            continue
        items.append(
            {
                "id": t.id,
                "name": shown.name,
                "kind": shown.kind,
                "kind_label": svc.KIND_LABELS.get(shown.kind, shown.kind),
                "description": shown.description,
                "withdrawn": t.withdrawn_at is not None,
                "active_version_no": active.version_no if active else None,
                "active_approved_at": active.reviewed_at.isoformat()
                if active and active.reviewed_at
                else None,
                "working_status": visible_working.status if visible_working else None,
                "working_status_label": svc.STATUS_LABELS.get(visible_working.status)
                if visible_working
                else None,
                "working_version_no": visible_working.version_no
                if visible_working
                else None,
                "author_name": names.get(shown.created_by or -1),
            }
        )
    return {"templates": items, "is_admin": svc.is_admin(current_user)}


@router.get("/custom-templates/{template_id}")
async def custom_template_detail(
    template_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    template = await svc.load_template(db, template_id)
    return await _detail(db, current_user, template)


# ── Trasy: tworzenie i szkic ────────────────────────────────────────────────


@router.post("/custom-templates")
async def create_custom_template(
    current_user: B2BGeneratorAccess,
    origin: str = Form(...),
    name: str = Form("", max_length=150),
    base_key: Optional[str] = Form(None),
    instruction: Optional[str] = Form(None, max_length=draft_mod.MAX_INSTRUCTION),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Nowy wzór: od wzoru bazowego, z wgranego Worda albo z samego opisu.
    Z poleceniem i dostępnym modelem od razu powstaje szkic zmian."""
    _require_contract_generation(current_user)
    instruction = (instruction or "").strip() or None
    warnings: list[str] = []
    if origin == "base":
        source_key = base_key or ""
        if source_key.startswith("custom:"):
            data, fields = await _approved_base(db, source_key)
            label = "wzór własny"
        else:
            base = BASES_BY_KEY.get(source_key)
            if base is None:
                raise HTTPException(status_code=422, detail="Wybierz wzór bazowy.")
            data = base.path.read_bytes()
            fields = await run_in_threadpool(
                lambda: fields_from_paths(sandbox.discover(data))
            )
            label = base.label
        default_name = f"Nowy wzór na bazie „{label}”"
    elif origin == "upload":
        if file is None:
            raise HTTPException(status_code=422, detail="Wgraj plik Word (.docx).")
        raw = await _read_docx(file)
        try:
            found = await run_in_threadpool(detect, raw, title=name or "Wzór własny")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        data, fields, warnings = found.docx, found.fields, found.warnings
        source_key = None
        default_name = (file.filename or "Wzór z pliku Word").removesuffix(".docx")
    elif origin == "brief":
        if not instruction:
            raise HTTPException(status_code=422, detail="Opisz, jaki wzór ma powstać.")
        if not draft_mod.model_available():
            raise HTTPException(
                status_code=503,
                detail="Bez asystenta zacznij od istniejącego wzoru albo pliku Word.",
            )
        data, fields, source_key = b"", [], None
        default_name = "Nowy wzór z opisu"
    else:
        raise HTTPException(status_code=422, detail="Nieznany sposób tworzenia wzoru.")
    template = CustomDocumentTemplate(created_by=current_user.id)
    db.add(template)
    await db.flush()
    version = CustomDocumentTemplateVersion(
        template_id=template.id,
        version_no=1,
        status="draft",
        name=(name.strip() or default_name)[:150],
        kind="contract",
        origin=origin,
        base_key=source_key,
        instruction=instruction,
        docx=data,
        docx_sha256=svc.sha256(data),
        fields=fields_to_json(fields),
        changes=[],
        checks=[],
        warnings=warnings,
        client_ids=[],
        created_by=current_user.id,
    )
    db.add(version)
    db.add(
        Activity(
            entity_type="custom_document_template",
            entity_id=template.id,
            action="created",
            user_id=current_user.id,
            details={"origin": origin, "base_key": source_key},
        )
    )
    await db.commit()
    message = None
    if instruction:
        message = await _draft_with_model(db, current_user, version.id, instruction)
        if message and origin == "brief":
            # Bez modelu wzór z opisu nie ma treści — nie zostawiamy pustego szkicu.
            await db.delete(await db.get(CustomDocumentTemplate, template.id))
            await db.commit()
            raise HTTPException(status_code=503, detail=message)
        await db.commit()
    template = await svc.load_template(db, template.id)
    return {**(await _detail(db, current_user, template)), "message": message}


async def _approved_base(db: AsyncSession, key: str) -> tuple[bytes, list]:
    try:
        template_id = int(key.removeprefix("custom:"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Wybierz wzór bazowy.") from exc
    template = await svc.load_template(db, template_id)
    active = svc.active_version(template, await svc.versions_of(db, template.id))
    if active is None or template.withdrawn_at is not None:
        raise HTTPException(status_code=422, detail="Ten wzór nie jest zatwierdzony.")
    return active.docx, svc.fields_of(active)


@router.post("/custom-templates/{template_id}/draft")
async def redraft_custom_template(
    template_id: int,
    body: DraftRequest,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Kolejne polecenie dla asystenta — zmienia bieżący szkic."""
    _require_contract_generation(current_user)
    template, version = await _load_working(db, current_user, template_id)
    svc.assert_draft(version)
    await db.commit()
    message = await _draft_with_model(
        db, current_user, version.id, body.instruction.strip()
    )
    await db.commit()
    template = await svc.load_template(db, template_id)
    return {**(await _detail(db, current_user, template)), "message": message}


@router.post("/custom-templates/{template_id}/upload")
async def upload_custom_template_docx(
    template_id: int,
    current_user: B2BGeneratorAccess,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Podmień treść szkicu plikiem Word (pola wykrywa kod; poprawione
    ręcznie etykiety pól o tym samym kluczu zostają)."""
    _require_contract_generation(current_user)
    template, version = await _load_working(db, current_user, template_id)
    svc.assert_draft(version)
    raw = await _read_docx(file)
    try:
        found = await run_in_threadpool(detect, raw, title=version.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    previous = {f.key: f for f in svc.fields_of(version)}
    fields = [previous.get(f.key, f) for f in found.fields]
    svc.set_docx(version, found.docx)
    version.fields = fields_to_json(fields)
    version.warnings = found.warnings
    version.changes = []
    await db.commit()
    return await _detail(db, current_user, template)


@router.patch("/custom-templates/{template_id}")
async def update_custom_template(
    template_id: int,
    body: SettingsRequest,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ustawienia i lista pól szkicu (etykiety, rodzaje, grupy, źródła).
    Klucz pola zostaje — to on stoi w treści wzoru."""
    _require_contract_generation(current_user)
    template, version = await _load_working(db, current_user, template_id)
    svc.assert_draft(version)
    raw = body.model_dump(exclude_unset=True)
    fields = raw.pop("fields", None)
    if raw.get("client_ids"):
        for client_id in raw["client_ids"]:
            if await assert_client_assignable(db, client_id) is None:
                raise HTTPException(status_code=422, detail="Klienta nie ma w NEXUSIE.")
    svc.clean_settings(raw, version)
    if fields is not None:
        current = {f.key for f in svc.fields_of(version)}
        if {str(f.get("key")) for f in fields} - current:
            raise HTTPException(
                status_code=422,
                detail="Nowe pole dodaje się w treści wzoru (Word albo asystent).",
            )
        svc.set_fields(version, fields)
    await db.commit()
    return await _detail(db, current_user, template)


@router.delete("/custom-templates/{template_id}/draft", status_code=204)
async def discard_custom_template_draft(
    template_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Odrzuć szkic. Wzór bez żadnej zatwierdzonej wersji znika cały."""
    _require_contract_generation(current_user)
    template, version = await _load_working(db, current_user, template_id)
    svc.assert_draft(version)
    await db.delete(version)
    if template.active_version_id is None:
        await db.delete(template)
    await db.commit()


@router.post("/custom-templates/{template_id}/sample")
async def custom_template_sample(
    template_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Próbny dokument z danymi fikcyjnymi — szkic (autor, administrator)
    albo zatwierdzona wersja. Niczego nie zapisuje."""
    template = await svc.load_template(db, template_id)
    versions = await svc.versions_of(db, template.id)
    version = svc.working_version(versions)
    if version is None or not svc.may_see_working(current_user, version):
        version = svc.active_version(template, versions)
    if version is None:
        raise HTTPException(status_code=404, detail="Wzór nie istnieje.")
    fields = svc.fields_of(version)
    try:
        data = await run_in_threadpool(
            sandbox.render, version.docx, fields, sample_values(fields)
        )
    except sandbox.TemplateInvalid as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "template_invalid",
                "message": "Wzór ma błędy.",
                "problems": exc.problems,
            },
        ) from exc
    filename = _ascii_filename(f"PROBA {version.name} v{version.version_no}") + ".docx"
    return _docx_response(data, filename, None)


# ── Trasy: zatwierdzanie ────────────────────────────────────────────────────


@router.post("/custom-templates/{template_id}/submit")
async def submit_custom_template(
    template_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_contract_generation(current_user)
    template, version = await _load_working(db, current_user, template_id)
    svc.assert_draft(version)
    problems = svc.submit_problems(version)
    if problems:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "template_not_ready",
                "message": "Wzór nie jest gotowy do zatwierdzenia.",
                "problems": problems,
            },
        )
    svc.mark_submitted(version, current_user)
    db.add(
        Activity(
            entity_type="custom_document_template",
            entity_id=template.id,
            action="submitted",
            user_id=current_user.id,
            details={"version_no": version.version_no},
        )
    )
    await db.commit()
    return await _detail(db, current_user, template)


@router.post("/custom-templates/{template_id}/approve")
async def approve_custom_template(
    template_id: int,
    body: ReviewRequest,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Administrator zatwierdza zgłoszoną wersję — od teraz jest w „Nowy dokument”."""
    template = await svc.load_template(db, template_id, lock=True)
    version = svc.working_version(await svc.versions_of(db, template.id))
    if version is None or version.status != "pending":
        raise HTTPException(
            status_code=409, detail="Ten wzór nie czeka na zatwierdzenie."
        )
    problems = svc.submit_problems(version)
    if problems:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "template_not_ready",
                "message": "Wzór ma błędy.",
                "problems": problems,
            },
        )
    previous = template.active_version_id
    svc.mark_approved(
        template, version, current_user, (body.note or "").strip() or None
    )
    db.add(
        Activity(
            entity_type="custom_document_template",
            entity_id=template.id,
            action="approved",
            user_id=current_user.id,
            details={"version_no": version.version_no, "previous_version_id": previous},
        )
    )
    await db.commit()
    return await _detail(db, current_user, template)


@router.post("/custom-templates/{template_id}/return")
async def return_custom_template(
    template_id: int,
    body: ReasonRequest,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Administrator zwraca wzór do poprawy z uwagą dla autora."""
    template = await svc.load_template(db, template_id, lock=True)
    version = svc.working_version(await svc.versions_of(db, template.id))
    if version is None or version.status != "pending":
        raise HTTPException(
            status_code=409, detail="Ten wzór nie czeka na zatwierdzenie."
        )
    svc.mark_returned(version, current_user, body.reason.strip())
    db.add(
        Activity(
            entity_type="custom_document_template",
            entity_id=template.id,
            action="returned",
            user_id=current_user.id,
            details={"version_no": version.version_no},
        )
    )
    await db.commit()
    return await _detail(db, current_user, template)


@router.post("/custom-templates/{template_id}/withdraw")
async def withdraw_custom_template(
    template_id: int,
    body: ReasonRequest,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Wycofaj wzór z „Nowy dokument”. Wydane dokumenty pobierają się dalej."""
    template = await svc.load_template(db, template_id, lock=True)
    if template.withdrawn_at is not None:
        raise HTTPException(status_code=409, detail="Wzór jest już wycofany.")
    active = svc.active_version(template, await svc.versions_of(db, template.id))
    svc.mark_withdrawn(template, active, current_user, body.reason.strip())
    db.add(
        Activity(
            entity_type="custom_document_template",
            entity_id=template.id,
            action="withdrawn",
            user_id=current_user.id,
            details={"reason": body.reason.strip()[:300]},
        )
    )
    await db.commit()
    return await _detail(db, current_user, template)


@router.post("/custom-templates/{template_id}/new-version")
async def new_custom_template_version(
    template_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Szkic kolejnej wersji z zatwierdzonej — działająca wersja zostaje
    w „Nowy dokument” do zatwierdzenia nowej."""
    _require_contract_generation(current_user)
    template = await svc.load_template(db, template_id, lock=True)
    versions = await svc.versions_of(db, template.id)
    if svc.working_version(versions) is not None:
        raise HTTPException(status_code=409, detail="Ten wzór ma już szkic.")
    active = svc.active_version(template, versions)
    if active is None:
        raise HTTPException(
            status_code=409, detail="Ten wzór nie ma zatwierdzonej wersji."
        )
    version = CustomDocumentTemplateVersion(
        template_id=template.id,
        version_no=await svc.next_version_no(db, template.id),
        status="draft",
        name=active.name,
        kind=active.kind,
        description=active.description,
        client_scope=active.client_scope,
        client_ids=list(active.client_ids or []),
        signatories=active.signatories,
        signature_form=active.signature_form,
        origin="base",
        base_key=f"custom:{template.id}",
        docx=active.docx,
        docx_sha256=active.docx_sha256,
        fields=list(active.fields or []),
        changes=[],
        checks=[],
        warnings=[],
        created_by=current_user.id,
    )
    db.add(version)
    await db.commit()
    return await _detail(db, current_user, template)


# ── Trasy: dokument ze wzoru ────────────────────────────────────────────────


async def _issuable(
    db: AsyncSession, user: User, template_id: int
) -> tuple[CustomDocumentTemplate, CustomDocumentTemplateVersion]:
    template = await svc.load_template(db, template_id)
    active = svc.active_version(template, await svc.versions_of(db, template.id))
    if (
        active is None
        or template.withdrawn_at is not None
        or active.status != "approved"
    ):
        raise HTTPException(
            status_code=409, detail="Ten wzór nie jest zatwierdzony do wystawiania."
        )
    return template, active


async def _subject(
    db: AsyncSession,
    user: User,
    version: CustomDocumentTemplateVersion,
    request: CustomDocumentRequest,
) -> dict[str, Any]:
    """Kandydat (przez rekrutację, do której wołający ma dostęp) i klient."""
    links: dict[str, Any] = {"candidate_id": None, "job_id": None, "client_id": None}
    if request.candidate_id is not None or request.job_id is not None:
        if request.candidate_id is None or request.job_id is None:
            raise HTTPException(
                status_code=422,
                detail="Wybierz kandydata razem z rekrutacją, w której uczestniczy.",
            )
        job = await _load_legal_scoped_job(db, user, request.job_id, write=True)
        await _validate_candidate_job_link(
            db, candidate_id=request.candidate_id, job_id=job.id
        )
        links.update(
            candidate_id=request.candidate_id, job_id=job.id, client_id=job.client_id
        )
    elif request.client_id is not None:
        client = await assert_client_assignable(db, request.client_id)
        if client is None:
            raise HTTPException(status_code=422, detail="Klienta nie ma w NEXUSIE.")
        await _assert_generator_client_access(db, user, client.id, write=True)
        links["client_id"] = client.id
    if not svc.offered_to(version, links["client_id"]):
        raise HTTPException(
            status_code=422,
            detail="Ten wzór jest tylko dla wybranych klientów — wskaż jednego z nich.",
        )
    return links


@router.get("/custom-templates/{template_id}/prefill")
async def custom_document_prefill(
    template_id: int,
    current_user: B2BGeneratorAccess,
    candidate_id: Optional[int] = None,
    job_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Wartości startowe pól ze źródłem „kandydat” i „CEIDG” — z profilu
    kandydata, wyłącznie przez rekrutację, do której wołający ma dostęp."""
    _, version = await _issuable(db, current_user, template_id)
    keys = {f.key for f in svc.fields_of(version)}
    values: dict[str, Any] = {}
    for f in svc.fields_of(version):
        if f.kind == "date" and f.key in ("document_date", "agreement_date"):
            values[f.key] = business_today().isoformat()
        if f.kind == "gender":
            values[f.key] = "m"
    if candidate_id is not None:
        if job_id is None:
            raise HTTPException(
                status_code=422,
                detail="Wybierz rekrutację, w której uczestniczy kandydat.",
            )
        job = await _load_legal_scoped_job(db, current_user, job_id, write=True)
        await _validate_candidate_job_link(db, candidate_id=candidate_id, job_id=job.id)
        candidate = await db.get(Candidate, candidate_id)
        if candidate is not None:
            full = f"{candidate.name or ''} {candidate.lastname or ''}".strip()
            known = {
                "partner.name": full,
                "partner.name_instrumental": full,
                "partner.legal_name": candidate.legal_name,
                "partner.company": candidate.legal_name,
                "partner.business_address": candidate.business_address,
                "partner.address": candidate.business_address,
                "partner.nip": candidate.nip,
                "partner.regon": candidate.regon,
                "partner.email": candidate.email,
                "partner.phone": candidate.phone,
            }
            values.update({k: v for k, v in known.items() if k in keys and v})
    return {"values": values}


@router.post("/custom-templates/{template_id}/preview")
async def custom_document_preview(
    template_id: int,
    request: CustomDocumentRequest,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Podgląd HTML wypełnionego dokumentu — niczego nie zapisuje."""
    _, version = await _issuable(db, current_user, template_id)
    fields = svc.fields_of(version)

    def _html() -> str:
        data = sandbox.render(version.docx, fields, request.values)
        return doc_to_html(docx.Document(io.BytesIO(data)))

    try:
        html = await run_in_threadpool(_html)
    except sandbox.TemplateInvalid as exc:
        raise HTTPException(
            status_code=422, detail="Wzór ma błędy — zgłoś to administratorowi."
        ) from exc
    return {"html": html, "missing": value_problems(fields, request.values)}


@router.post("/custom-templates/{template_id}/documents")
async def create_custom_document(
    template_id: int,
    request: CustomDocumentRequest,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Wystaw dokument ze wzoru własnego: DOCX w odpowiedzi + wiersz w rejestrze
    dokumentów Generatora. Żadnych skutków w kontraktach."""
    _require_contract_generation(current_user)
    template, version = await _issuable(db, current_user, template_id)
    fields = svc.fields_of(version)
    problems = value_problems(fields, request.values)
    if problems:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "document_fields_missing",
                "message": "Uzupełnij pola: " + "; ".join(problems) + ".",
                "missing": problems,
            },
        )
    links = await _subject(db, current_user, version, request)
    if any(f.kind == "money" for f in fields):
        # Dokument z kwotą — ta sama widoczność co DOCX umowy (stawki).
        await _require_generator_rate_content(
            db,
            current_user,
            links["client_id"],
            created_by=current_user.id,
            job_id=links["job_id"],
        )
    try:
        data = await run_in_threadpool(
            sandbox.render, version.docx, fields, request.values
        )
    except sandbox.TemplateInvalid as exc:
        raise HTTPException(
            status_code=422, detail="Wzór ma błędy — zgłoś to administratorowi."
        ) from exc
    context = build_context(fields, request.values)
    doc_date = _document_day(fields, request.values)
    partner = context.get("partner") if isinstance(context.get("partner"), dict) else {}
    stored = strip_sensitive(fields, request.values)
    doc = B2BContractDocument(
        document_type=svc.DOCUMENT_TYPE,
        language="pl",
        document_date=doc_date,
        render_payload={
            "values": {
                **stored,
                # Lista i wyszukiwarka rejestru czytają te klucze.
                "partner_name": partner.get("name") or partner.get("name_instrumental"),
                "partner_legal_name": partner.get("legal_name")
                or partner.get("company"),
                "partner_nip": partner.get("nip"),
            },
            "custom_template": {
                "template_id": template.id,
                "version_id": version.id,
                "version_no": version.version_no,
                "name": version.name,
                "kind": version.kind,
                "signatories": version.signatories,
                "fields": fields_to_json(fields),
            },
        },
        template_key=svc.template_key_for(version.id),
        created_by=current_user.id,
        **links,
    )
    db.add(doc)
    await db.flush()
    db.add(
        Activity(
            entity_type="b2b_contract_document",
            entity_id=doc.id,
            action="generated",
            user_id=current_user.id,
            details={
                "document_type": svc.DOCUMENT_TYPE,
                "custom_template_id": template.id,
                "version_no": version.version_no,
            },
        )
    )
    await db.commit()
    who = partner.get("name") or ""
    filename = (
        _ascii_filename(f"{version.name} {who} {doc_date.isoformat()}".strip())
        + ".docx"
    )
    return _docx_response(data, filename, doc.id)


def _day(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _document_day(fields: list, values: dict[str, Any]) -> date:
    """Data dokumentu w rejestrze: pole daty dokumentu albo umowy, inaczej
    pierwsze pole daty, inaczej dziś (kalendarz firmy)."""
    dates = [f.key for f in fields if f.kind == "date"]
    preferred = [k for k in ("document_date", "agreement_date") if k in dates]
    for key in [*preferred, *dates]:
        day = _day(values.get(key))
        if day is not None:
            return day
    return business_today()
