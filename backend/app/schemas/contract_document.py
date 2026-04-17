from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from app.models.contract_document import ContractDocumentType


class ContractDocumentResponse(BaseModel):
    id: int
    contract_id: int
    filename: str
    doc_type: ContractDocumentType
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    expiry_date: Optional[date] = None
    uploaded_by: Optional[int] = None
    uploaded_by_email: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContractDocumentUpdate(BaseModel):
    doc_type: Optional[ContractDocumentType] = None
    expiry_date: Optional[date] = None
