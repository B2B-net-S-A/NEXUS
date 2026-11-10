"""Mapa decyzyjna szansy (lejek Fabryki IT): dodanie, poprawka i usunięcie osoby.

Lista leży w ``custom_fields.atlas.it_factory.decision_map``, tam gdzie położył
ją import z Atlasa. Pola i limity jak w Atlasie (``src/api/it_factory_schemas.py``).

Osoba nie ma własnego id, bo 124 wpisy z Atlasa go nie mają. Klucz osoby to skrót
jej zapisanej treści, więc każda zmiana go zmienia: poprawka wysłana ze starego
ekranu nie znajdzie wpisu i dostanie 409 zamiast nadpisać czyjąś zmianę.

Telefon, mail, LinkedIn i notatka wpisane na mapie uzupełniają też puste pola
kontaktu tej osoby; niczego w kontakcie nie nadpisują (decyzja Artura 02.11.2026).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesContact
from app.services.sales.companies import http_url
from app.services.sales.motion import resolve_contacts

IT_FACTORIES_PIPELINE_KEY = "atlas-it-factories"

ContactStatus = Literal[
    "not_contacted", "in_progress", "first_contact", "regular_dialog"
]
OurRole = Literal[
    "decision_maker",
    "economic_buyer",
    "champion",
    "influencer",
    "blocker",
    "end_user",
]

_OUR_ROLE_WORDS = {
    "decision_maker": "Decydent",
    "economic_buyer": "Budżet",
    "champion": "Champion",
    "influencer": "Wpływa",
    "blocker": "Hamuje",
    "end_user": "Użytkownik",
}
_CONTACT_STATUS_WORDS = {
    "not_contacted": "bez kontaktu",
    "in_progress": "w toku",
    "first_contact": "pierwszy kontakt",
    "regular_dialog": "stały dialog",
}
#: Kolejność i podpisy pól w historii szansy.
_FIELD_WORDS = {
    "name": "imię i nazwisko",
    "role_in_company": "stanowisko",
    "decision_level": "poziom",
    "our_role": "nasza rola",
    "contact_status": "status kontaktu",
    "last_contact_at": "ostatni kontakt",
    "phone": "telefon",
    "email": "e-mail",
    "linkedin_url": "LinkedIn",
    "notes": "notatka",
    # Tylko wpis z importu listy (``research_import.py``); formularz go nie wysyła.
    "source_label": "źródło",
}
#: Pole mapy → limit tej kolumny w ``sales_contacts`` (mapa pozwala czasem na więcej).
_CONTACT_FILL_LIMITS: dict[str, Optional[int]] = {
    "email": 255,
    "phone": 60,
    "linkedin_url": 500,
    "notes": None,
}
#: Chwila ręcznej zmiany statusu albo daty kontaktu w oknie osoby. Automat z Outlooka
#: i telefonów (``decision_map_outlook.py``) pomija zdarzenia sprzed niej: człowiek ma
#: pierwszeństwo.
CONTACT_EDITED_AT = "contact_edited_at"
CONTACT_FIELDS = frozenset({"contact_status", "last_contact_at"})


class _DecisionPersonFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role_in_company: Optional[str] = Field(default=None, max_length=255)
    our_role: Optional[OurRole] = None
    decision_level: Optional[int] = Field(default=None, ge=1, le=4)
    linkedin_url: Optional[str] = Field(default=None, max_length=512)
    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=320)
    last_contact_at: Optional[date] = None
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("role_in_company", "phone", "notes")
    @classmethod
    def _blank_is_none(cls, value: Optional[str]) -> Optional[str]:
        return value or None

    @field_validator("linkedin_url")
    @classmethod
    def _http_only(cls, value: Optional[str]) -> Optional[str]:
        return http_url(value)

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Adres e-mail wygląda na niepełny.")
        return value.lower()


class DecisionPersonCreate(_DecisionPersonFields):
    name: str = Field(min_length=1, max_length=255)
    contact_status: ContactStatus = "not_contacted"


class DecisionPersonUpdate(_DecisionPersonFields):
    """Tylko pola, które handlowiec zmienił: zły adres z Atlasa nie blokuje notatki."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    contact_status: Optional[ContactStatus] = None

    @field_validator("name", "contact_status")
    @classmethod
    def _required_when_sent(cls, value: Optional[str]) -> str:
        if value is None:
            raise ValueError("To pole nie może być puste.")
        return value


def decision_entries(custom_fields: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    atlas = (custom_fields or {}).get("atlas")
    factory = atlas.get("it_factory") if isinstance(atlas, dict) else None
    entries = factory.get("decision_map") if isinstance(factory, dict) else None
    if not isinstance(entries, list):
        return []
    return [dict(entry) for entry in entries if isinstance(entry, dict)]


def with_entries(
    custom_fields: Optional[dict[str, Any]],
    entries: list[dict[str, Any]],
    *,
    user_id: Optional[int],
    now: datetime,
) -> dict[str, Any]:
    """Nowy słownik ``custom_fields`` (SQLAlchemy widzi przypisanie, nie mutację JSON-a).

    ``user_id`` puste = zmiana automatu (Outlook, zapisana rozmowa), nie człowieka.
    """

    custom = dict(custom_fields or {})
    atlas = custom.get("atlas")
    atlas = dict(atlas) if isinstance(atlas, dict) else {}
    factory = atlas.get("it_factory")
    factory = dict(factory) if isinstance(factory, dict) else {}
    factory["decision_map"] = entries
    # ``updated_at`` zostaje datą z Atlasa; ekran mówi, skąd pochodzi stan mapy.
    factory["nexus_updated_at"] = now.isoformat()
    factory["nexus_updated_by_user_id"] = user_id
    atlas["it_factory"] = factory
    custom["atlas"] = atlas
    return custom


def _word(field: str, value: Any) -> str:
    if value in (None, ""):
        return "—"
    if field == "our_role":
        return _OUR_ROLE_WORDS.get(str(value), str(value))
    if field == "contact_status":
        return _CONTACT_STATUS_WORDS.get(str(value), str(value))
    return str(value)


def describe_person(entry: dict[str, Any]) -> str:
    """Cała osoba jednym napisem — wpis w historii przy dodaniu i usunięciu."""

    parts = [
        f"{word}: {_word(field, entry.get(field))}"
        for field, word in _FIELD_WORDS.items()
        if field != "name" and entry.get(field) not in (None, "")
    ]
    name = str(entry.get("name") or "—")
    return f"{name} ({'; '.join(parts)})" if parts else name


def describe_change(
    before: dict[str, Any], after: dict[str, Any], fields: list[str]
) -> tuple[str, str]:
    """Stara i nowa wartość zmienionych pól, z nazwiskiem z przed zmiany."""

    name = str(before.get("name") or "—")
    ordered = [field for field in _FIELD_WORDS if field in fields]
    old = "; ".join(f"{_FIELD_WORDS[f]}: {_word(f, before.get(f))}" for f in ordered)
    new = "; ".join(f"{_FIELD_WORDS[f]}: {_word(f, after.get(f))}" for f in ordered)
    return f"{name} — {old}", f"{name} — {new}"


async def fill_contact(
    db: AsyncSession, company_id: int, entry: dict[str, Any], fields: list[str]
) -> list[str]:
    """Puste pola kontaktu tej osoby dostają wartości z mapy; zwraca podpisy pól.

    Osoba bez kontaktu albo z kontaktem w archiwum: nic. Telefon liczy się jako
    pusty dopiero bez komórki, bo odczyt mapy bierze ``phone or mobile_phone``.
    """

    wanted = [f for f in fields if f in _CONTACT_FILL_LIMITS and entry.get(f)]
    if not wanted:
        return []
    [contact_id] = await resolve_contacts(db, company_id, [entry])
    contact = await db.get(SalesContact, contact_id) if contact_id else None
    if contact is None or contact.archived_at is not None:
        return []
    filled = []
    for field in wanted:
        value = entry[field]
        limit = _CONTACT_FILL_LIMITS[field]
        if getattr(contact, field) or (limit is not None and len(value) > limit):
            continue
        if field == "phone" and contact.mobile_phone:
            continue
        setattr(contact, field, value)
        filled.append(_FIELD_WORDS[field])
    return filled
