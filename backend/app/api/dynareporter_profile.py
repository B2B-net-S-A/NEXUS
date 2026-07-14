"""DynaReporter B.1 — Profile endpoint (readonly).

Phase B.1 of the DynaReporter migration plan
(.claude/plans/zaplanuj-migracje-pelna-nie-parallel-acorn.md).

Pierwszy moduł migracji — walidacja wzorca end-to-end (auth + routing +
layout + API client) BEZ jeszcze migrowania prawdziwych danych
DynaReportera. Endpoint zwraca info o zalogowanym userze + listę
modułów do których ma dostęp (``allowed_sections`` z migracji 0111).

Po smoke test (login → /dynareporter/profile → user info widoczny)
mamy walidację że cały stack (FastAPI router + JWT + Next.js layout +
shadcn UI) działa zanim zaczniemy migrować konkretne dashboardy
(KPI Body Leasing, Sales, etc.) w fazach B.2.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, require_dynareporter_access
from app.schemas.dynareporter_profile import DynaReporterProfileResponse

router = APIRouter(dependencies=[Depends(require_dynareporter_access)])


@router.get(
    "/me",
    response_model=DynaReporterProfileResponse,
    summary="Profile zalogowanego usera + lista modułów DynaReporter",
)
async def get_my_profile(current_user: CurrentUser) -> DynaReporterProfileResponse:
    """Zwraca informacje o zalogowanym userze plus listę modułów DynaReportera.

    Endpoint readonly — żadnych writes. Walidacja wzorca dla B.1.
    """
    return DynaReporterProfileResponse(
        user_id=current_user.id,
        email=current_user.email,
        full_name=current_user.name,
        role=current_user.role.value,
        allowed_sections=list(current_user.allowed_sections or []),
        dynareporter_legacy_id=current_user.dynareporter_legacy_id,
    )
