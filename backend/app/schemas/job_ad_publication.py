"""Oznaczenie publikacji ogłoszenia na portalu — kształty odpowiedzi.

Osobny plik bez importu usług: wiersz listy rekrutacji (``JobResponse``)
niesie ``ad_publications``, a ``schemas/job.py`` nie może ciągnąć modułów
generatora.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.services.job_ad_publication_schema import URL_MAX

AdPortal = Literal["pracuj", "jjit"]


class JobAdPublicationOut(BaseModel):
    """Aktywne ogłoszenie w wierszu listy rekrutacji."""

    portal: AdPortal
    url: Optional[str] = None
    # Zapisana treść ogłoszenia jest inna niż w chwili oznaczenia publikacji.
    outdated: bool = False


class AdPublicationMail(BaseModel):
    """Mail Pracuj.pl, z którego NEXUS wziął link (26.11.2026)."""

    email_id: int
    subject: str
    received_at: Optional[datetime] = None


class AdPublicationRead(JobAdPublicationOut):
    """Stan portalu w oknie i w sekcji „Zespół i ogłoszenie”."""

    published_at: datetime
    published_by_name: Optional[str] = None
    # Ustawione = zdjęte z portalu (wiersz zostaje jako ślad).
    removed_at: Optional[datetime] = None
    # Link wzięty z maila „Publikacja ogłoszenia na …”; brak = wklejony ręcznie.
    from_mail: Optional[AdPublicationMail] = None


class PracujMailSuggestion(BaseModel):
    """Mail Pracuj.pl, o który okno pyta: „To ta rekrutacja?” (26.11.2026)."""

    email_id: int
    subject: str
    received_at: datetime
    url: str


class AdPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Pusty = ogłoszenie wisi, linku jeszcze nie ma (np. czeka na moderację).
    url: Optional[str] = Field(default=None, max_length=URL_MAX)
    # „Zaktualizowane na portalu”: treść na portalu jest już taka jak zapisana.
    # Sama zmiana linku tego nie potwierdza — plakietka „do aktualizacji”
    # zostaje, tak samo jak data i osoba pierwszego oznaczenia.
    content_updated: bool = False
