from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr

from app.models.client import ClientStatus


class ClientCreate(BaseModel):
    name: str
    industry: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    contact_person: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    status: ClientStatus = ClientStatus.prospect
    nda_signed: bool = False
    contract_type: Optional[str] = None
    notes: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    contact_person: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    status: Optional[ClientStatus] = None
    nda_signed: Optional[bool] = None
    contract_type: Optional[str] = None
    notes: Optional[str] = None


class ClientResponse(BaseModel):
    id: int
    name: str
    industry: Optional[str]
    website: Optional[str]
    address: Optional[str]
    contact_person: Optional[str]
    contact_email: Optional[str]
    contact_phone: Optional[str]
    status: ClientStatus
    nda_signed: bool
    contract_type: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClientList(BaseModel):
    items: list[ClientResponse]
    total: int
    page: int
    page_size: int
