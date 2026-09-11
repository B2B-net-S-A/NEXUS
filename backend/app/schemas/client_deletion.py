from typing import Literal, Optional

from pydantic import BaseModel


class DeletionBlockerOut(BaseModel):
    code: str
    label: str
    count: int
    items: list[str]


class DeletionHistoryItemOut(BaseModel):
    code: str
    label: str
    count: int


class ClientDeletionCheckResponse(BaseModel):
    client_id: int
    client_name: str
    status: Optional[str] = None
    # blocked = nie można usunąć; purge = usunięcie trwałe (klient pusty);
    # archive = usunięcie z zachowaniem danych historycznych.
    mode: Literal["blocked", "purge", "archive"]
    can_delete: bool
    blockers: list[DeletionBlockerOut]
    history: list[DeletionHistoryItemOut]
    history_sentence: Optional[str] = None
    confirmation_phrase: str


class ClientDeletionResult(BaseModel):
    client_id: int
    client_name: str
    # purged = usunięty trwale; archived = usunięty, historia zachowana.
    result: Literal["purged", "archived"]
    history: list[DeletionHistoryItemOut]
    history_sentence: Optional[str] = None
