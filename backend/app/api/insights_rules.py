"""`/api/insights/rules-overview`: co dziś obowiązuje, do zakładki Insights → Zasady.

Bramka jak przy zapisie zasad: administrator i Head of Recruitment. Ekrany edycji
zostają na swoich trasach i mają własne bramki, ta trasa tylko je podsumowuje.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.user import UserRole
from app.services.insights_rules_overview import build_overview

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)


@router.get("/rules-overview")
async def rules_overview(
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {
        "rules": await build_overview(
            db, is_admin=current_user.has_any_role(UserRole.admin)
        )
    }
