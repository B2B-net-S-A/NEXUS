"""Pydantic schemas dla DynaReporter Profile endpoint (B.1)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DynaReporterProfileResponse(BaseModel):
    """Profile response — info o zalogowanym userze + lista modułów DR.

    Pola odpowiadają kolumnom z migracji 0111 (allowed_sections,
    dynareporter_legacy_id) + standardowe identity z users table.
    """

    user_id: int = Field(description="Nexus user.id")
    email: str = Field(description="Email loginowy")
    full_name: str = Field(description="users.name — pełna nazwa wyświetlana")
    role: str = Field(description="Primary UserRole (string value)")
    allowed_sections: list[str] = Field(
        default_factory=list,
        description="Lista identyfikatorów modułów DynaReportera "
        "(body-leasing, sales, delivery-lead, placements, clients-mrr, "
        "competitions, przetargi, board, sales-mgmt, mindy, admin). "
        "Admin nadaje per user. Pusta lista = brak dostępu.",
    )
    dynareporter_legacy_id: Optional[int] = Field(
        default=None,
        description="users.id z systemu DynaReporter (Render/Coolify standalone). "
        "Wypełniany przez ETL przy email-match. NULL = user nigdy nie był "
        "w DynaReporterze.",
    )
