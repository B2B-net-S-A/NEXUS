"""Idempotentny seed Generatora Umów B2B.

Wstawia brakujące role (po `slug`) oraz 2 szablony HTML (po
`contract_type='b2b' + language`). NIGDY nie nadpisuje istniejących rekordów —
edycje z UI są bezpieczne. Wywoływany przy starcie aplikacji (lifespan).
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.b2b_roles import B2B_ROLES
from app.models.b2b_contract_role import B2BContractRole
from app.models.contract_template import ContractTemplate

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "contract"
# (language, template name, html asset)
_TEMPLATES = [
    ("pl", "Umowa B2B (PL)", "umowa_b2b_pl.html"),
    ("en", "Umowa B2B (EN)", "umowa_b2b_en.html"),
]


async def ensure_b2b_seed_data(db: AsyncSession) -> None:
    await _seed_roles(db)
    await _seed_templates(db)
    await db.commit()


async def _seed_roles(db: AsyncSession) -> None:
    existing = set((await db.execute(select(B2BContractRole.slug))).scalars().all())
    added = 0
    for r in B2B_ROLES:
        if r["slug"] in existing:
            continue
        db.add(
            B2BContractRole(
                category_key=r["category_key"],
                category_label_pl=r["category_label_pl"],
                category_label_en=r["category_label_en"],
                slug=r["slug"],
                name_pl=r["name_pl"],
                name_en=r["name_en"],
                area_label_pl=r["area_label_pl"],
                area_label_en=r["area_label_en"],
                scope_pl=r["scope_pl"],
                scope_en=r["scope_en"],
                display_order=r["display_order"],
            )
        )
        added += 1
    if added:
        logger.info("B2B roles seeded: %d new (of %d)", added, len(B2B_ROLES))


async def _seed_templates(db: AsyncSession) -> None:
    for lang, name, fname in _TEMPLATES:
        exists = await db.scalar(
            select(ContractTemplate.id).where(
                ContractTemplate.contract_type == "b2b",
                ContractTemplate.language == lang,
            )
        )
        if exists:
            continue
        path = _TEMPLATE_DIR / fname
        if not path.is_file():
            logger.warning("B2B template html missing, skip seed: %s", path)
            continue
        db.add(
            ContractTemplate(
                name=name,
                contract_type="b2b",
                language=lang,
                content_jinja=path.read_text(encoding="utf-8"),
                is_default=False,
            )
        )
        logger.info("B2B contract template seeded: %s", name)
