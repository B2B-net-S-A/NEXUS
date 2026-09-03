"""Persisted, administrator-managed product-section permissions."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


_SECTION_VALUES = (
    "'sourcing', 'pipeline', 'delivery', 'insights', 'finance', 'system_admin'"
)
_ACCESS_VALUES = "'none', 'read', 'write'"
_ROLE_VALUES = (
    "'admin', 'head_of_recruitment', 'delivery_lead', "
    "'talent_community_manager', 'finance', 'tac', 'recruiter', 'sourcer', 'user'"
)


class RbacPolicyState(Base):
    """Single locked row used for optimistic concurrency across the RBAC panel."""

    __tablename__ = "rbac_policy_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_rbac_policy_state_singleton"),
        CheckConstraint("revision > 0", name="ck_rbac_policy_state_revision_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    revision: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1"
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RoleSectionPermission(Base):
    """Base section ceiling for one application role."""

    __tablename__ = "rbac_role_section_permissions"
    __table_args__ = (
        CheckConstraint(
            f"role IN ({_ROLE_VALUES})",
            name="ck_rbac_role_section_permissions_role",
        ),
        CheckConstraint(
            f"section IN ({_SECTION_VALUES})",
            name="ck_rbac_role_section_permissions_section",
        ),
        CheckConstraint(
            f"access IN ({_ACCESS_VALUES})",
            name="ck_rbac_role_section_permissions_access",
        ),
    )

    role: Mapped[str] = mapped_column(String(64), primary_key=True)
    section: Mapped[str] = mapped_column(String(32), primary_key=True)
    access: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UserSectionOverride(Base):
    """Explicit replacement of the role union for one user and section.

    No row means ``inherit``. Keeping inheritance out of the stored values
    makes later role-policy edits flow to users without copying a matrix to
    every account.
    """

    __tablename__ = "rbac_user_section_overrides"
    __table_args__ = (
        CheckConstraint(
            f"section IN ({_SECTION_VALUES})",
            name="ck_rbac_user_section_overrides_section",
        ),
        CheckConstraint(
            f"access IN ({_ACCESS_VALUES})",
            name="ck_rbac_user_section_overrides_access",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    section: Mapped[str] = mapped_column(String(32), primary_key=True)
    access: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RbacPermissionAudit(Base):
    """Immutable admin-only audit trail for section-policy mutations."""

    __tablename__ = "rbac_permission_audit"
    __table_args__ = (
        CheckConstraint(
            "target_kind IN ('role', 'user')",
            name="ck_rbac_permission_audit_target_kind",
        ),
        CheckConstraint(
            "revision > 0", name="ck_rbac_permission_audit_revision_positive"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_key: Mapped[str] = mapped_column(String(128), nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    before: Mapped[dict] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
