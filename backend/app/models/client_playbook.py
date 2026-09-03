"""Karta klienta — standardy współpracy per klient (migracja 0272).

Do 09.2026 wiedza o kliencie (SLA, limit CV, hold, off-limit, onboarding,
dokumenty) była KOPIOWANA do każdej oferty w `jobs.champion_profile`
(sekcja 6 „O kliencie" + 7 „Dokumenty") i do 14 wzorów Word per klient.
Żaden konsument backendu tych pól nie czytał (embedding, prompt CV i
uzasadnienia dopasowań biorą tylko `selling_points`, `consultant_insight`,
`historical_questions`), a KPI/SLA nie miało w bazie żadnego domu.

Jedna karta na klienta (UNIQUE `client_id`), prowadzi ją Delivery Lead,
zapis = obowiązuje (bez bramki zatwierdzenia jak w `client_cv_rules`, bo
seed nigdy nie nadpisuje istniejącego wiersza — DO NOTHING). Każdy zapis
zmieniający treść bumpuje `version` i zostawia wpis w
`client_playbook_events`.

Off-limit NIE jest tu duplikowany — czytany tylko do odczytu z
`client_contract_terms` (umowa ramowa jest źródłem prawdy).
"""

from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ClientPlaybook(Base, TimestampMixin):
    """Jedna karta na klienta (1:1, wymuszone UNIQUE na ``client_id``)."""

    __tablename__ = "client_playbooks"
    __table_args__ = (
        CheckConstraint(
            "(sla_business_days IS NULL "
            "OR (sla_business_days >= 0 AND sla_business_days <= 365)) AND "
            "(sla_min_candidates IS NULL OR sla_min_candidates > 0) AND "
            "(cv_limit_per_process IS NULL OR cv_limit_per_process > 0) AND "
            "(hold_hours IS NULL OR hold_hours > 0) AND "
            "(multi_project_cooldown_days IS NULL "
            "OR multi_project_cooldown_days > 0)",
            name="ck_client_playbooks_numbers",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # ── KPI / SLA (liczby; NULL = klient nie stawia wymogu) ──────────────
    sla_business_days: Mapped[Optional[int]] = mapped_column(Integer)
    sla_min_candidates: Mapped[Optional[int]] = mapped_column(Integer)
    cv_limit_per_process: Mapped[Optional[int]] = mapped_column(Integer)
    hold_hours: Mapped[Optional[int]] = mapped_column(Integer)
    multi_project_cooldown_days: Mapped[Optional[int]] = mapped_column(Integer)
    rate_policy: Mapped[Optional[str]] = mapped_column(String(500))

    # ── Treść (co mówić kandydatowi, reguły, proces, onboarding) ─────────
    about_for_candidate: Mapped[Optional[str]] = mapped_column(Text)
    priority_rules: Mapped[Optional[str]] = mapped_column(Text)
    process_rules_md: Mapped[Optional[str]] = mapped_column(Text)
    onboarding_md: Mapped[Optional[str]] = mapped_column(Text)

    # Lista {"name": ..., "url": ...} — wskaźniki na SharePoint, nie kopie.
    documents: Mapped[Optional[list]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )

    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    # Slug dawnego wzoru Championa per klient, z którego kartę zasiano.
    seed_key: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    client = relationship("Client")
    editor = relationship("User", foreign_keys=[updated_by])

    def __repr__(self) -> str:
        return f"<ClientPlaybook client_id={self.client_id} v{self.version}>"
