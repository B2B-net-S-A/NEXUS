"""Pydantic schemas for ContractEquipment — CRUD + mark-returned shortcut."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from app.models.contract_equipment import (
    EquipmentItemType,
    EquipmentOwner,
    EquipmentReturnStatus,
)


class ContractEquipmentBase(BaseModel):
    item_type: EquipmentItemType
    owner: EquipmentOwner
    brand_model: Optional[str] = None
    serial_number: Optional[str] = None
    description: Optional[str] = None
    deposit_amount: Optional[int] = None
    deposit_currency: Optional[str] = None
    handed_over_date: Optional[date] = None
    return_due_date: Optional[date] = None
    returned_date: Optional[date] = None
    return_status: EquipmentReturnStatus = EquipmentReturnStatus.pending
    notes: Optional[str] = None


class ContractEquipmentCreate(ContractEquipmentBase):
    pass


class ContractEquipmentUpdate(BaseModel):
    item_type: Optional[EquipmentItemType] = None
    owner: Optional[EquipmentOwner] = None
    brand_model: Optional[str] = None
    serial_number: Optional[str] = None
    description: Optional[str] = None
    deposit_amount: Optional[int] = None
    deposit_currency: Optional[str] = None
    handed_over_date: Optional[date] = None
    return_due_date: Optional[date] = None
    returned_date: Optional[date] = None
    return_status: Optional[EquipmentReturnStatus] = None
    notes: Optional[str] = None


class ContractEquipmentResponse(ContractEquipmentBase):
    id: int
    contract_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
