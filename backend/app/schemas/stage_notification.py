"""Pydantic schemas dla CRUD reguł powiadomień stage transition."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.stage_notification import RecipientType
from app.models.user import UserRole

_VALID_ROLE_VALUES = frozenset(role.value for role in UserRole)


class StageNotificationRuleBase(BaseModel):
    """Wspólne pola create/update/response.

    Walidatory cross-field:
    - ``recipient_type=specific_user`` ⇒ ``specific_user_id`` required.
    - ``recipient_type=role`` ⇒ ``role`` required i musi należeć do UserRole.
    """

    recipient_type: RecipientType
    specific_user_id: Optional[int] = None
    role: Optional[str] = Field(default=None, max_length=32)
    notify_inapp: bool = True
    notify_email: bool = False
    is_active: bool = True

    @model_validator(mode="after")
    def _validate_recipient_specifics(self) -> "StageNotificationRuleBase":
        if self.recipient_type == RecipientType.specific_user:
            if self.specific_user_id is None:
                raise ValueError(
                    "specific_user_id is required when recipient_type=specific_user"
                )
            if self.role is not None:
                raise ValueError(
                    "role must be NULL when recipient_type=specific_user"
                )
        elif self.recipient_type == RecipientType.role:
            if self.role is None:
                raise ValueError(
                    "role is required when recipient_type=role"
                )
            if self.role not in _VALID_ROLE_VALUES:
                raise ValueError(
                    f"role must be one of {sorted(_VALID_ROLE_VALUES)}"
                )
            if self.specific_user_id is not None:
                raise ValueError(
                    "specific_user_id must be NULL when recipient_type=role"
                )
        else:
            if self.specific_user_id is not None:
                raise ValueError(
                    "specific_user_id is only allowed when recipient_type=specific_user"
                )
            if self.role is not None:
                raise ValueError(
                    "role is only allowed when recipient_type=role"
                )
        if not (self.notify_inapp or self.notify_email):
            raise ValueError(
                "at least one of notify_inapp / notify_email must be TRUE"
            )
        return self


class StageNotificationRuleCreate(StageNotificationRuleBase):
    pass


class StageNotificationRuleUpdate(BaseModel):
    recipient_type: Optional[RecipientType] = None
    specific_user_id: Optional[int] = None
    role: Optional[str] = Field(default=None, max_length=32)
    notify_inapp: Optional[bool] = None
    notify_email: Optional[bool] = None
    is_active: Optional[bool] = None


class StageNotificationRuleResponse(StageNotificationRuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stage_def_id: int
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime


class ClientStageOverrideCreate(StageNotificationRuleBase):
    stage_def_id: int


class ClientStageOverrideUpdate(StageNotificationRuleUpdate):
    pass


class ClientStageOverrideResponse(StageNotificationRuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    stage_def_id: int
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime


__all__ = [
    "StageNotificationRuleBase",
    "StageNotificationRuleCreate",
    "StageNotificationRuleUpdate",
    "StageNotificationRuleResponse",
    "ClientStageOverrideCreate",
    "ClientStageOverrideUpdate",
    "ClientStageOverrideResponse",
]
