"""Dane silnika „Popraw dokument” — bez logiki i bez bazy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ChangeKind = Literal["replace", "insert_paragraph", "delete_paragraph"]
CitationState = Literal["ok", "missing", "mismatch"]

AUTHOR = "Asystent NEXUS"
AUTHOR_INITIALS = "AN"


@dataclass(frozen=True)
class Paragraph:
    """Akapit treści dokumentu (także w komórce tabeli), w kolejności z pliku."""

    index: int
    text: str
    style: str | None = None
    in_table: bool = False
    heading: bool = False


@dataclass(frozen=True)
class ChangeSource:
    """Cytat, na którym opiera się zmiana: ``quote`` musi stać w źródle ``ref``."""

    ref: str
    label: str
    quote: str
    kind: str = "law"
    url: str | None = None
    state: CitationState = "ok"


@dataclass(frozen=True)
class RedlineChange:
    """Jedna zmiana w dokumencie.

    ``replace``: w akapicie ``paragraph`` fragment ``[start, end)`` (tekst
    ``find``) zamienia się na ``new_text``; pusty ``find`` to wstawka w miejscu
    ``start``, pusty ``new_text`` to skreślenie. ``insert_paragraph``: nowy
    akapit ``new_text`` za akapitem ``paragraph`` (``before=True`` — przed nim).
    ``delete_paragraph``: skreślenie całego akapitu ``paragraph``.
    """

    id: str
    kind: ChangeKind
    paragraph: int
    new_text: str = ""
    find: str = ""
    start: int | None = None
    end: int | None = None
    before: bool = False
    reason: str = ""
    sources: tuple[ChangeSource, ...] = field(default_factory=tuple)

    @property
    def blocked(self) -> bool:
        """Cytat bez pokrycia w źródle blokuje przyjęcie zmiany (decyzja 3 planu)."""
        return any(s.state != "ok" for s in self.sources)


class RedlineError(ValueError):
    """Zmiana nie pasuje do dokumentu — komunikat po polsku dla użytkownika."""

    def __init__(self, message: str, *, change_id: str | None = None) -> None:
        super().__init__(message)
        self.change_id = change_id


class NotADocxError(ValueError):
    """Plik nie jest dokumentem Worda (DOCX)."""
