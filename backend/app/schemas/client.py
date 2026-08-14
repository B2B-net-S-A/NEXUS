from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, computed_field, field_validator

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
    # `name` CELOWO nieobecne: to pole jest Traffit-owned (daily sync robi
    # ON CONFLICT ... SET name=EXCLUDED.name), więc każdy zapis przez API
    # odtwarzałby pierwotny bug „nazwa się cofa". Pydantic po cichu zignoruje
    # `name` w payload — jedyną ścieżką zmiany nazwy jest `display_name`.
    #
    # Sync-odporny override nazwy (Traffit nigdy nie dotyka `display_name` —
    # patrz models/client.py). Edycja nazwy z UI pisze TUTAJ; wyczyszczenie
    # pola (""/whitespace → None) przywraca nazwę źródłową, bo odczyt robi
    # coalesce(nullif(btrim(display_name),''), name).
    display_name: Optional[str] = Field(None, max_length=255)
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
    # Interaktywna wersja CV na publicznym linku (kafelki + chat) dla hiring
    # managerów tego klienta. Niezależne od `cv_content_mode_cap`.
    cv_interactive_enabled: Optional[bool] = None

    @field_validator("display_name")
    @classmethod
    def _blank_display_name_to_none(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None


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
    cv_interactive_enabled: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def multi_consultant_orders_enabled(self) -> bool:
        """Czy zakładka „Zamówienia" ma renderować widok wielo-konsultantowy.

        Wyliczane po stronie serwera, a NIE duplikowane we froncie jak stała
        e-Zdrowia (``frontend/src/lib/ezdrowie.ts``). Tamta lista to jedno
        zaszyte ID; ta jest zmienną środowiskową, którą można zmienić
        w Coolify bez deployu — kopia w bundlu byłaby nieaktualna od pierwszej
        takiej zmiany, a nikt by tego nie zauważył poza zniknięciem zakładki.
        """
        from app.services.multi_consultant_orders import is_multi_consultant_client

        return is_multi_consultant_client(self.id)


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
