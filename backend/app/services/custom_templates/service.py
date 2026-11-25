"""Wzory własne: cykl życia wzoru i wersji (zapis w bazie, nie w kodzie).

``draft`` (autor poprawia) → ``pending`` (zgłoszony) → ``approved`` (zatwierdził
administrator, wzór w „Nowy dokument”) albo z powrotem ``draft`` z uwagą.
Zmiana zatwierdzonego wzoru = nowa wersja (``draft`` obok działającej
``approved``); po zatwierdzeniu nowej wydane dokumenty zostają na swojej
(``b2b_contract_documents.template_key = custom_v<id wersji>``). Wycofanie
wzoru zdejmuje go z „Nowy dokument”; wydane dokumenty pobierają się dalej.
"""

from __future__ import annotations

import hashlib
import html as _html
import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import docx
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_document_template import (
    CustomDocumentTemplate,
    CustomDocumentTemplateVersion,
)
from app.models.user import User, UserRole
from app.services.custom_templates import checks as checks_mod
from app.services.custom_templates import sandbox
from app.services.custom_templates.docx_ops import doc_to_html
from app.services.custom_templates.fields import (
    CustomField,
    FieldsError,
    fields_to_json,
    parse_fields,
)
from app.services.custom_templates.schema import (
    CLIENT_SCOPES,
    KINDS,
    NAME_MAX,
    SIGNATORIES,
    SIGNATURE_FORMS,
)

if TYPE_CHECKING:
    from app.services.b2b_documents.registry import DocumentType

#: Typ dokumentu w rejestrze dokumentów Generatora (``B2B_DOCUMENT_TYPES``).
DOCUMENT_TYPE = "custom_template"
KIND_LABELS: dict[str, str] = {
    "contract": "Umowa",
    "preliminary": "Umowa przedwstępna",
    "annex": "Aneks",
    "letter": "Porozumienie / pismo",
}
STATUS_LABELS: dict[str, str] = {
    "draft": "szkic",
    "pending": "do zatwierdzenia",
    "approved": "zatwierdzony",
    "withdrawn": "wycofany",
}
MAX_CLIENTS = 50


def template_key_for(version_id: int) -> str:
    return f"custom_v{version_id}"


def version_id_from_key(key: str | None) -> int | None:
    m = re.fullmatch(r"custom_v(\d{1,9})", key or "")
    return int(m.group(1)) if m else None


def is_admin(user: User) -> bool:
    return user.has_role(UserRole.admin)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Odczyt ──────────────────────────────────────────────────────────────────


async def load_template(db: AsyncSession, template_id: int, *, lock: bool = False):
    stmt = select(CustomDocumentTemplate).where(
        CustomDocumentTemplate.id == template_id
    )
    if lock:
        stmt = stmt.with_for_update()
    template = await db.scalar(stmt)
    if template is None:
        raise HTTPException(status_code=404, detail="Wzór nie istnieje.")
    return template


async def versions_of(
    db: AsyncSession, template_id: int
) -> list[CustomDocumentTemplateVersion]:
    rows = await db.scalars(
        select(CustomDocumentTemplateVersion)
        .where(CustomDocumentTemplateVersion.template_id == template_id)
        .order_by(CustomDocumentTemplateVersion.version_no)
    )
    return list(rows)


def working_version(
    versions: list[CustomDocumentTemplateVersion],
) -> CustomDocumentTemplateVersion | None:
    return next((v for v in versions if v.status in ("draft", "pending")), None)


def active_version(
    template: CustomDocumentTemplate, versions: list[CustomDocumentTemplateVersion]
) -> CustomDocumentTemplateVersion | None:
    if template.active_version_id is None:
        return None
    return next((v for v in versions if v.id == template.active_version_id), None)


def may_see_working(user: User, version: CustomDocumentTemplateVersion) -> bool:
    """Szkic widzi autor wersji i administrator (zgłoszony — też administrator
    do zatwierdzenia); zatwierdzony wzór widzą wszyscy z Generatora."""
    return is_admin(user) or version.created_by == user.id


def assert_author(user: User, version: CustomDocumentTemplateVersion) -> None:
    if not may_see_working(user, version):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Szkic wzoru zmienia jego autor albo administrator.",
        )


def assert_draft(
    version: CustomDocumentTemplateVersion | None,
) -> CustomDocumentTemplateVersion:
    if version is None or version.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wzór czeka na zatwierdzenie — zmiany po decyzji administratora."
                if version is not None and version.status == "pending"
                else "Ten wzór nie ma szkicu do zmiany."
            ),
        )
    return version


def fields_of(version: CustomDocumentTemplateVersion) -> list[CustomField]:
    try:
        return parse_fields(version.fields or [])
    except FieldsError:
        # Zapis przeszedł walidację; zepsuta lista to błąd danych — pusto
        # zamiast 500, a walidacja szablonu pokaże każde pole jako nieznane.
        return []


# ── Opis wersji dla frontu ──────────────────────────────────────────────────

_FIELD_IN_HTML = re.compile(r"\{\{\s*([a-z][a-z0-9_.]*)\s*\}\}")
_CONTROL_IN_HTML = re.compile(r"\{%.*?%\}", re.S)


def preview_html(docx_bytes: bytes, fields: list[CustomField]) -> str:
    """Treść wzoru jako HTML z polami jako znacznikami (etykieta pola)."""
    try:
        html = doc_to_html(docx.Document(io.BytesIO(docx_bytes)))
    except Exception:  # noqa: BLE001 — uszkodzony plik pokaże walidacja
        return ""
    labels = {f.key: f.label for f in fields}

    def field_tag(m: re.Match) -> str:
        key = m.group(1)
        label = labels.get(key) or labels.get(key.removesuffix("_words"))
        if key.endswith("_words") and label:
            label = f"{label} — słownie"
        if key.startswith("g."):
            label = "forma Pan/Pani"
        if key.startswith("company."):
            label = "dane B2B.net"
        text = _html.escape(label or key)
        return f'<span class="tpl-field" data-field="{_html.escape(key)}">{text}</span>'

    html = _FIELD_IN_HTML.sub(field_tag, html)
    return _CONTROL_IN_HTML.sub(
        lambda m: f'<span class="tpl-control">{m.group(0)}</span>', html
    )


@dataclass
class Review:
    problems: list[str]
    unused: list[str]
    checks: list[dict[str, Any]]


def review(version: CustomDocumentTemplateVersion) -> Review:
    fields = fields_of(version)
    check = sandbox.validate(version.docx, fields)
    try:
        text = checks_mod.document_text(version.docx)
    except Exception:  # noqa: BLE001
        text = ""
    found = checks_mod.run_checks(text, fields, signature_form=version.signature_form)
    return Review(
        problems=check.problems,
        unused=check.unused(fields),
        checks=[c.to_public() for c in found],
    )


def version_public(
    version: CustomDocumentTemplateVersion,
    *,
    names: dict[int, str],
    with_content: bool = True,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": version.id,
        "version_no": version.version_no,
        "status": version.status,
        "status_label": STATUS_LABELS.get(version.status, version.status),
        "name": version.name,
        "kind": version.kind,
        "kind_label": KIND_LABELS.get(version.kind, version.kind),
        "description": version.description,
        "client_scope": version.client_scope,
        "client_ids": list(version.client_ids or []),
        "signatories": version.signatories,
        "signature_form": version.signature_form,
        "origin": version.origin,
        "base_key": version.base_key,
        "instruction": version.instruction,
        "ai_used": version.ai_used,
        "created_by_name": names.get(version.created_by or -1),
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "submitted_by_name": names.get(version.submitted_by or -1),
        "submitted_at": version.submitted_at.isoformat()
        if version.submitted_at
        else None,
        "reviewed_by_name": names.get(version.reviewed_by or -1),
        "reviewed_at": version.reviewed_at.isoformat() if version.reviewed_at else None,
        "review_note": version.review_note,
    }
    fields = fields_of(version)
    data["fields"] = [f.to_public() for f in fields]
    if with_content:
        result = review(version)
        data.update(
            changes=list(version.changes or []),
            warnings=list(version.warnings or []),
            checks=result.checks,
            problems=result.problems,
            unused_fields=result.unused,
            preview_html=preview_html(version.docx, fields),
        )
    return data


# ── Zapis ───────────────────────────────────────────────────────────────────


def clean_settings(raw: dict[str, Any], version: CustomDocumentTemplateVersion) -> None:
    """Ustawienia z kroku „Zapis i zatwierdzenie” — walidacja na granicy."""
    if "name" in raw:
        name = str(raw.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Podaj nazwę wzoru.")
        version.name = name[:NAME_MAX]
    if "description" in raw:
        version.description = str(raw.get("description") or "").strip()[:1000]
    choices = (
        ("kind", KINDS),
        ("client_scope", CLIENT_SCOPES),
        ("signatories", SIGNATORIES),
        ("signature_form", SIGNATURE_FORMS),
    )
    for key, allowed in choices:
        if key in raw:
            value = str(raw.get(key) or "")
            if value not in allowed:
                raise HTTPException(status_code=422, detail=f"Nieznana wartość: {key}.")
            setattr(version, key, value)
    if "client_ids" in raw:
        ids = raw.get("client_ids") or []
        if not isinstance(ids, list) or len(ids) > MAX_CLIENTS:
            raise HTTPException(status_code=422, detail="Niepoprawna lista klientów.")
        try:
            version.client_ids = sorted({int(i) for i in ids})
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail="Niepoprawna lista klientów."
            ) from exc


def set_fields(version: CustomDocumentTemplateVersion, raw: object) -> None:
    try:
        fields = parse_fields(raw)
    except FieldsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    version.fields = fields_to_json(fields)


def set_docx(version: CustomDocumentTemplateVersion, data: bytes) -> None:
    version.docx = data
    version.docx_sha256 = sha256(data)


async def next_version_no(db: AsyncSession, template_id: int) -> int:
    current = await db.scalar(
        select(func.max(CustomDocumentTemplateVersion.version_no)).where(
            CustomDocumentTemplateVersion.template_id == template_id
        )
    )
    return int(current or 0) + 1


def submit_problems(version: CustomDocumentTemplateVersion) -> list[str]:
    """Co blokuje zgłoszenie do zatwierdzenia (i samo zatwierdzenie)."""
    result = review(version)
    problems = list(result.problems)
    problems += checks_mod.blocking(result.checks)
    if not fields_of(version):
        problems.append("Wzór nie ma żadnego pola do wypełnienia.")
    if version.client_scope == "selected" and not version.client_ids:
        problems.append("Wybierz klientów, dla których jest wzór.")
    if not (version.name or "").strip():
        problems.append("Podaj nazwę wzoru.")
    return problems


def mark_submitted(version: CustomDocumentTemplateVersion, user: User) -> None:
    # Migawka sprawdzeń z chwili zgłoszenia — ślad, co widział zatwierdzający.
    version.checks = review(version).checks
    version.status = "pending"
    version.submitted_by = user.id
    version.submitted_at = _now()
    version.review_note = None


def mark_approved(
    template: CustomDocumentTemplate,
    version: CustomDocumentTemplateVersion,
    user: User,
    note: str | None,
) -> None:
    version.status = "approved"
    version.reviewed_by = user.id
    version.reviewed_at = _now()
    version.review_note = note
    template.active_version_id = version.id
    template.withdrawn_at = None
    template.withdrawn_by = None
    template.withdrawn_reason = None


def mark_returned(
    version: CustomDocumentTemplateVersion, user: User, note: str
) -> None:
    version.status = "draft"
    version.reviewed_by = user.id
    version.reviewed_at = _now()
    version.review_note = note


def mark_withdrawn(
    template: CustomDocumentTemplate,
    active: CustomDocumentTemplateVersion | None,
    user: User,
    reason: str,
) -> None:
    template.withdrawn_at = _now()
    template.withdrawn_by = user.id
    template.withdrawn_reason = reason
    if active is not None:
        active.status = "withdrawn"


def offered_to(version: CustomDocumentTemplateVersion, client_id: int | None) -> bool:
    """Czy wzór wolno wystawić dla klienta (``client_scope``)."""
    if version.client_scope == "all":
        return True
    return client_id is not None and client_id in set(version.client_ids or [])


# ── Dokument ze wzoru w rejestrze dokumentów Generatora ─────────────────────

_FIELD_KINDS_FOR_REGISTRY = {
    "list": "textarea",
}


def document_type_for(payload: dict[str, Any] | None) -> DocumentType:
    """Typ wydanego dokumentu ze wzoru własnego — z migawki w ``render_payload``
    (nazwa, pola, podpisujący), nie z bieżącej wersji wzoru: lista dokumentów,
    widoczność kwot i dane wrażliwe liczą się tak, jak przy wydaniu."""
    from app.services.b2b_documents.registry import DocumentType, FieldDef  # noqa: PLC0415

    snapshot = (payload or {}).get("custom_template") or {}
    try:
        fields = parse_fields(snapshot.get("fields") or [])
    except FieldsError:
        fields = []
    signatories = snapshot.get("signatories")
    return DocumentType(
        key=DOCUMENT_TYPE,
        label=str(snapshot.get("name") or "Wzór własny"),
        family="custom",
        languages=("pl",),
        parent="none",
        fields=tuple(
            FieldDef(
                key=f.key,
                label=f.label,
                kind=_FIELD_KINDS_FOR_REGISTRY.get(f.kind, f.kind),  # type: ignore[arg-type]
                required=f.required,
                sensitive=f.sensitive,
            )
            for f in fields
        ),
        effect_label="Bez skutków w kontraktach — dokument ze wzoru własnego.",
        signatories=signatories if signatories in SIGNATORIES else "both",  # type: ignore[arg-type]
        uses_refs=False,
    )


async def render_issued(db: AsyncSession, doc: Any, values: dict[str, Any]) -> bytes:
    """DOCX wydanego dokumentu tą wersją wzoru, którą go wydano."""
    version_id = version_id_from_key(doc.template_key)
    version = (
        await db.get(CustomDocumentTemplateVersion, version_id)
        if version_id is not None
        else None
    )
    if version is None:
        raise HTTPException(status_code=500, detail="Brak wersji wzoru tego dokumentu.")
    from starlette.concurrency import run_in_threadpool  # noqa: PLC0415

    try:
        return await run_in_threadpool(
            sandbox.render, version.docx, fields_of(version), values
        )
    except sandbox.TemplateInvalid as exc:
        raise HTTPException(
            status_code=500, detail="Wzór tego dokumentu ma błędy."
        ) from exc


async def offered_types(db: AsyncSession) -> list[dict[str, Any]]:
    """Zatwierdzone, niewycofane wzory własne dla „Nowy dokument”."""
    rows = await db.execute(
        select(CustomDocumentTemplate, CustomDocumentTemplateVersion)
        .join(
            CustomDocumentTemplateVersion,
            CustomDocumentTemplateVersion.id
            == CustomDocumentTemplate.active_version_id,
        )
        .where(
            CustomDocumentTemplate.withdrawn_at.is_(None),
            CustomDocumentTemplateVersion.status == "approved",
        )
        .order_by(CustomDocumentTemplateVersion.name)
    )
    out: list[dict[str, Any]] = []
    for template, version in rows.all():
        fields = fields_of(version)
        out.append(
            {
                "key": f"custom:{template.id}",
                "template_id": template.id,
                "version_id": version.id,
                "version_no": version.version_no,
                "label": version.name,
                "description": version.description,
                "kind": version.kind,
                "kind_label": KIND_LABELS.get(version.kind, version.kind),
                "client_scope": version.client_scope,
                "client_ids": list(version.client_ids or []),
                "signatories": version.signatories,
                "signature_form": version.signature_form,
                "approved_at": version.reviewed_at.isoformat()
                if version.reviewed_at
                else None,
                "fields": [f.to_public() for f in fields],
            }
        )
    return out
