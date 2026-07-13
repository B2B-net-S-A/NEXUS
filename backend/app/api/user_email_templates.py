"""User email templates library — Phase 4.5 of the M365 plan.

CRUD + render for per-user M365 outreach templates. Rendered with a
Jinja2 SandboxedEnvironment so user-supplied template source can't reach
Python internals (no access to ``__class__``/``__subclasses__`` etc.).

Endpoints (mounted under /api/user-email-templates):
- GET    /                  — list own + shared
- POST   /                  — create (auto-detects variables from body)
- GET    /{id}              — single (own OR shared)
- PUT    /{id}              — update (owner-only)
- DELETE /{id}              — delete (owner-only)
- POST   /{id}/render       — render Jinja2 with candidate/job context

The render endpoint resolves the optional candidate_id / request_id / job_id
to ORM rows and exposes them to the template under the namespaces
`candidate`, `request`, `job`, `user`, `today`.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from jinja2 import TemplateError, meta, select_autoescape
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.user_email_template import UserEmailTemplate
from app.services.m365.html_sanitize import sanitize_html

router = APIRouter()


# Sandboxed so user-supplied template source can't reach Python internals.
# autoescape=True since rendered output is injected as HTML into Tiptap.
_jinja_env = SandboxedEnvironment(
    autoescape=select_autoescape(["html", "xml"], default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _extract_variables(body_html: str) -> List[str]:
    """Parse Jinja2 source and return the sorted list of referenced vars.

    Returns top-level names (``candidate`` not ``candidate.first_name``) — the
    UI groups by namespace anyway. Empty list if the body has no variables.
    """
    try:
        ast = _jinja_env.parse(body_html)
    except TemplateError:
        # Caller will surface a 422 from validation; for save-time we still
        # want to persist *some* variables list rather than crash here.
        return []
    return sorted(meta.find_undeclared_variables(ast))


def _validate_jinja(template_src: str, field_name: str) -> None:
    """Raise 422 if Jinja2 cannot parse the source."""
    try:
        _jinja_env.parse(template_src)
    except TemplateError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid Jinja2 syntax in {field_name}: {e}",
        )


# ── Pydantic schemas ────────────────────────────────────────────────────────


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    subject: Optional[str] = Field(None, max_length=998)
    body_html: str = Field(..., min_length=1)
    is_shared: bool = False


class TemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    subject: Optional[str] = Field(None, max_length=998)
    body_html: Optional[str] = Field(None, min_length=1)
    is_shared: Optional[bool] = None


class TemplateResponse(BaseModel):
    id: int
    user_id: int
    name: str
    subject: Optional[str]
    body_html: str
    variables: List[str]
    is_shared: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_row(cls, t: UserEmailTemplate) -> "TemplateResponse":
        return cls(
            id=t.id,
            user_id=t.user_id,
            name=t.name,
            subject=t.subject,
            body_html=t.body_html,
            variables=list(t.variables or []),
            is_shared=t.is_shared,
            created_at=t.created_at.isoformat() if t.created_at else "",
            updated_at=t.updated_at.isoformat() if t.updated_at else "",
        )


class RenderRequest(BaseModel):
    candidate_id: Optional[int] = None
    request_id: Optional[int] = None
    job_id: Optional[int] = None


class RenderResponse(BaseModel):
    rendered_subject: str
    rendered_body_html: str
    unresolved_vars: List[str]


# ── Helpers ─────────────────────────────────────────────────────────────────


def _candidate_ctx(c: Optional[Candidate]) -> dict:
    if c is None:
        return {}
    full = f"{c.name} {c.lastname}".strip() if (c.name or c.lastname) else None
    return {
        "id": c.id,
        "first_name": c.name,
        "last_name": c.lastname,
        "full_name": full,
        "email": c.email,
        "phone": c.phone,
        "location": c.location,
        "linkedin": c.linkedin,
    }


def _job_ctx(j: Optional[Job]) -> dict:
    if j is None:
        return {}
    client = getattr(j, "client", None)
    return {
        "id": j.id,
        "title": j.title,
        "role_name": j.title,
        "location": j.location,
        "client_name": client.name if client else None,
        "salary_min": j.salary_min,
        "salary_max": j.salary_max,
    }


def _user_ctx(u) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
    }


def _build_render_context(
    template: UserEmailTemplate,
    current_user,
    candidate: Optional[Candidate],
    job: Optional[Job],
) -> dict:
    """Assemble the dict exposed to Jinja2 templates.

    Keep this shape STABLE — it's effectively the public contract for what
    variables template authors can use. New keys = additive; renames or
    removals will break existing templates in the wild.
    """
    job_ctx = _job_ctx(job)
    return {
        "candidate": _candidate_ctx(candidate),
        "request": job_ctx,
        "job": job_ctx,
        "user": _user_ctx(current_user),
        "today": date.today().isoformat(),
    }


def _collect_unresolved(template_src: str, ctx: dict) -> List[str]:
    """Return Jinja2 top-level vars that aren't present in the render context."""
    try:
        ast = _jinja_env.parse(template_src)
    except TemplateError:
        return []
    return sorted(v for v in meta.find_undeclared_variables(ast) if v not in ctx)


async def _load_template_for_read(
    template_id: int,
    user_id: int,
    db: AsyncSession,
) -> UserEmailTemplate:
    """Owner OR shared. 404 otherwise."""
    t = await db.scalar(
        select(UserEmailTemplate).where(
            UserEmailTemplate.id == template_id,
            or_(
                UserEmailTemplate.user_id == user_id,
                UserEmailTemplate.is_shared.is_(True),
            ),
        )
    )
    if t is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    return t


async def _load_template_for_write(
    template_id: int,
    user_id: int,
    db: AsyncSession,
) -> UserEmailTemplate:
    """Owner only — separated from read to give 404 vs 403 the right semantics."""
    t = await db.scalar(
        select(UserEmailTemplate).where(UserEmailTemplate.id == template_id)
    )
    if t is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    if t.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only modify your own templates",
        )
    return t


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("", response_model=List[TemplateResponse])
async def list_templates(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Own templates + every shared template (from any user)."""
    res = await db.execute(
        select(UserEmailTemplate)
        .where(
            or_(
                UserEmailTemplate.user_id == current_user.id,
                UserEmailTemplate.is_shared.is_(True),
            )
        )
        .order_by(UserEmailTemplate.updated_at.desc())
    )
    return [TemplateResponse.from_orm_row(t) for t in res.scalars().all()]


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: TemplateCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    _validate_jinja(data.body_html, "body_html")
    if data.subject:
        _validate_jinja(data.subject, "subject")

    t = UserEmailTemplate(
        user_id=current_user.id,
        name=data.name,
        subject=data.subject,
        body_html=data.body_html,
        variables=_extract_variables(data.body_html),
        is_shared=data.is_shared,
    )
    db.add(t)
    await db.flush()
    await db.refresh(t)
    await db.commit()
    return TemplateResponse.from_orm_row(t)


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    t = await _load_template_for_read(template_id, current_user.id, db)
    return TemplateResponse.from_orm_row(t)


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: int,
    data: TemplateUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    t = await _load_template_for_write(template_id, current_user.id, db)

    updates = data.model_dump(exclude_unset=True)
    if "body_html" in updates and updates["body_html"] is not None:
        _validate_jinja(updates["body_html"], "body_html")
        updates["variables"] = _extract_variables(updates["body_html"])
    if "subject" in updates and updates["subject"]:
        _validate_jinja(updates["subject"], "subject")

    for k, v in updates.items():
        setattr(t, k, v)
    await db.flush()
    await db.refresh(t)
    await db.commit()
    return TemplateResponse.from_orm_row(t)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    t = await _load_template_for_write(template_id, current_user.id, db)
    await db.delete(t)
    await db.commit()


@router.post("/{template_id}/render", response_model=RenderResponse)
async def render_template(
    template_id: int,
    payload: RenderRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Render the template with the provided candidate/job context.

    Missing entities produce empty namespaces (e.g. no candidate_id →
    `candidate.first_name` resolves to undefined). The response lists
    unresolved top-level vars so the UI can warn the user.
    """
    t = await _load_template_for_read(template_id, current_user.id, db)

    candidate: Optional[Candidate] = None
    if payload.candidate_id is not None:
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == payload.candidate_id)
        )

    # `request_id` is treated as a Job id — Nexus uses the same primary key
    # for "rekrutacja / request" and "job" (one row, dual naming in the
    # product). Frontend may send either field; we pick the first set.
    job_id = payload.job_id if payload.job_id is not None else payload.request_id
    job: Optional[Job] = None
    if job_id is not None:
        job = await db.scalar(
            select(Job).where(Job.id == job_id).options(selectinload(Job.client))
        )

    ctx = _build_render_context(t, current_user, candidate, job)

    try:
        body_tmpl = _jinja_env.from_string(t.body_html)
        rendered_body = sanitize_html(body_tmpl.render(**ctx))
    except TemplateError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Render error in body: {e}",
        )

    rendered_subject = ""
    if t.subject:
        try:
            subj_tmpl = _jinja_env.from_string(t.subject)
            rendered_subject = subj_tmpl.render(**ctx)
        except TemplateError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Render error in subject: {e}",
            )

    unresolved = _collect_unresolved(t.body_html, ctx)
    if t.subject:
        unresolved = sorted(set(unresolved) | set(_collect_unresolved(t.subject, ctx)))

    return RenderResponse(
        rendered_subject=rendered_subject,
        rendered_body_html=rendered_body,
        unresolved_vars=unresolved,
    )
