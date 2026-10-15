"""Autor zapisu kandydata, pliku CV i notatki — osoba z ekranu albo klucz API v1.

API integracyjne v1 (15.10.2026) zakłada kandydatów, wgrywa CV i dopisuje
notatki tym samym kodem co ekran (``candidates.apply_candidate_create``,
``candidates._ingest_candidate_cv_file``, ``notes.apply_note_create``). Ciało
zapisu pyta autora wyłącznie o trzy rzeczy:

* ``user`` / ``user_id`` — osoba (``users.id``) albo ``None`` dla konta
  serwisowego. Kolumny autora (``candidates.created_by``, ``notes.author_id``,
  ``activities.user_id``, ``candidate_documents.uploaded_by``) są nullable,
  a ``details.via`` na ``Activity`` dopisuje stempel sesji klucza
  (``integration_actor.stamp_integration``);
* ``label`` — podpis dla ludzi (karta Teams, tytuł dzwonka wzmianki);
* ``is_integration`` — wpis automatu: notatka systemowa (reguła 0412).

Konto serwisowe nie dostaje wpisu ``UserActivity`` (to ranking ludzi,
a ``user_activities.user_id`` jest NOT NULL) i nie oznacza ludzi w notatkach.
Bramki ról ekranu stoją na trasach (zależności) — ``WriteAuthor`` niczego nie
odblokowuje, a ``IntegrationActor`` nigdy nie trafia do bramki roli.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover
    from app.models.user import User
    from app.services.integration_actor import IntegrationActor


@dataclass(frozen=True)
class WriteAuthor:
    user: Optional[User] = None
    service_label: Optional[str] = None
    is_integration: bool = False

    @classmethod
    def person(cls, user: User, *, is_integration: bool = False) -> WriteAuthor:
        """Osoba z ekranu; ``is_integration`` dla tokenu klienta OAuth (scraper)."""
        return cls(user=user, is_integration=is_integration)

    @classmethod
    def service_account(cls, actor: IntegrationActor) -> WriteAuthor:
        """Konto serwisowe API v1 — podpis „Integracja: <nazwa>”."""
        return cls(service_label=actor.name, is_integration=True)

    @property
    def user_id(self) -> Optional[int]:
        return self.user.id if self.user is not None else None

    @property
    def label(self) -> str:
        # Czytane przy użyciu, nie przy tworzeniu — ekran czytał
        # ``current_user.name or current_user.email`` dokładnie w tym miejscu.
        if self.user is not None:
            return self.user.name or self.user.email
        return self.service_label or ""
