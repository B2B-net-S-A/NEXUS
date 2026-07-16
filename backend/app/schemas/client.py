from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.client import ClientStatus


class ClientCreate(BaseModel):
    name: str
    industry: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    status: ClientStatus = ClientStatus.prospect
    nda_signed: bool = False
    contract_type: Optional[str] = None
    notes: Optional[str] = None
    legal_name: Optional[str] = None
    nip: Optional[str] = None
    regon: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    status: Optional[ClientStatus] = None
    nda_signed: Optional[bool] = None
    contract_type: Optional[str] = None
    notes: Optional[str] = None
    legal_name: Optional[str] = None
    nip: Optional[str] = None
    regon: Optional[str] = None


class ClientSafeResponse(BaseModel):
    """Bezpieczna projekcja klienta (PR 1/7, M1-SEC-02).

    Dla ról bez wglądu w dane prawne (recruiter/sourcer/viewer). Pola
    ``legal_name``/``nip``/``regon``/``notes`` celowo NIE istnieją w tym
    modelu — użytkownik bez prawa nie dostaje ich nawet jako ``null``.
    ``nda_signed`` zostaje: to operacyjny sygnał zgodności, potrzebny
    rekruterom zanim udostępnią dane kandydata.
    """

    id: int
    name: str
    industry: Optional[str]
    website: Optional[str]
    address: Optional[str]
    status: ClientStatus
    nda_signed: bool
    contract_type: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClientResponse(ClientSafeResponse):
    """Pełna projekcja — admin/HoR/DL/TAC (dane prawne + notatki)."""

    notes: Optional[str]
    legal_name: Optional[str] = None
    nip: Optional[str] = None
    regon: Optional[str] = None


# Zwracamy gotowe instancje modeli — brak atrybutów prawnych w wariancie
# safe jednoznacznie wybiera właściwy człon unii przy serializacji.
AnyClientResponse = ClientResponse | ClientSafeResponse


class ClientList(BaseModel):
    items: list[AnyClientResponse]
    total: int
    page: int
    page_size: int
