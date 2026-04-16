"""Pydantic schemas for pipeline templates CRUD."""

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from app.models.pipeline_template import StageCategoryEnum, TerminalType


# ── StageDef ─────────────────────────────────────────────────────────────────


class StageDefCreate(BaseModel):
    name: str = Field(..., max_length=100)
    order: int = Field(..., ge=0)
    category: StageCategoryEnum
    is_terminal: bool = False
    terminal_type: Optional[TerminalType] = None
    tracker_enabled: bool = False
    tracker_public_name: Optional[str] = Field(None, max_length=100)
    sla_max_days: Optional[int] = Field(None, ge=0)


class StageDefUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    order: Optional[int] = Field(None, ge=0)
    category: Optional[StageCategoryEnum] = None
    is_terminal: Optional[bool] = None
    terminal_type: Optional[TerminalType] = None
    tracker_enabled: Optional[bool] = None
    tracker_public_name: Optional[str] = Field(None, max_length=100)
    sla_max_days: Optional[int] = Field(None, ge=0)


class StageDefResponse(BaseModel):
    id: int
    template_id: int
    name: str
    order: int
    category: StageCategoryEnum
    is_terminal: bool
    terminal_type: Optional[TerminalType]
    tracker_enabled: bool
    tracker_public_name: Optional[str]
    sla_max_days: Optional[int]
    legacy_enum_value: Optional[str]
    scorecard_schema: Optional[Any] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StageReorderItem(BaseModel):
    stage_id: int
    order: int


# ── RejectionReason ──────────────────────────────────────────────────────────


class RejectionReasonCreate(BaseModel):
    name: str = Field(..., max_length=100)
    category: TerminalType
    order: int = 0
    stage_def_id: Optional[int] = None


class RejectionReasonUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    order: Optional[int] = None
    active: Optional[bool] = None


class RejectionReasonResponse(BaseModel):
    id: int
    template_id: int
    stage_def_id: Optional[int]
    name: str
    order: int
    category: TerminalType
    active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── PipelineTemplate ─────────────────────────────────────────────────────────


class PipelineTemplateCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    is_default: bool = False


class PipelineTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    is_default: Optional[bool] = None
    archived: Optional[bool] = None


class PipelineTemplateSummary(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_default: bool
    archived: bool
    stage_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PipelineTemplateDetail(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_default: bool
    archived: bool
    created_at: datetime
    updated_at: datetime
    stages: List[StageDefResponse]
    rejection_reasons: List[RejectionReasonResponse]

    model_config = {"from_attributes": True}


# ── Job assignment ───────────────────────────────────────────────────────────


class AssignTemplatePayload(BaseModel):
    template_id: int
