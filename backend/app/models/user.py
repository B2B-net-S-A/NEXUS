import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class UserRole(str, enum.Enum):
    """
    Jedna, skonsolidowana hierarchia ról dla procesu B2B.net:

    - admin               — zarządzanie systemem i userami
    - head_of_recruitment — Olaf-type manager; odbiorca HR-owych agregatów
                            (PowerCalling, daily rollup) z notification_triggers
    - delivery_lead       — kierownik operacyjnego procesu delivery
    - finance             — operacje finansowe i widok executive
    - tac                 — Talent Acquisition Consultant (hybryda ATS + LinkedIn)
    - recruiter           — 100% LinkedIn, dodaje kandydatów
    - sourcer             — 100% ATS + ogłoszenia
    - user                — deprecated legacy viewer; no new provisioning

    ``user`` remains during the expand/contract window so legacy guards keep
    failing closed while accounts are migrated to ``recruiter``.
    """

    admin = "admin"
    head_of_recruitment = "head_of_recruitment"
    delivery_lead = "delivery_lead"
    finance = "finance"
    tac = "tac"
    recruiter = "recruiter"
    sourcer = "sourcer"
    user = "user"


class User(Base, TimestampMixin):
    """
    Użytkownik systemu. Jedna rola = jedno źródło prawdy.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "authorization_version > 0",
            name="ck_users_authorization_version_positive",
        ),
        CheckConstraint(
            "jsonb_typeof(roles) = 'array'",
            name="ck_users_roles_array",
        ),
        CheckConstraint(
            """
            CASE
                WHEN role::text IN ('finance', 'user')
                    THEN roles = jsonb_build_array(role::text)
                ELSE NOT (roles ?| ARRAY['finance', 'user']::text[])
            END
            """,
            name="ck_users_exclusive_finance_viewer_roles",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    # Nullable since migration 0081 — SSO-only userzy nie mają bcrypt hasha.
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="userrole"),
        default=UserRole.recruiter,
        nullable=False,
    )
    # Multi-role support (migracja 0110). Primary role lives in ``role``
    # (one source of truth for token issuance + legacy UI), but a user may
    # hold additional roles listed here — used by AAD RBAC for hybrid
    # delivery_lead/TAC personas and by ``has_role()``/``get_all_roles()``
    # to evaluate permission checks. Invariant: ``role.value`` is always
    # in ``roles`` (enforced by ``ensure_roles_invariant()`` + migration
    # backfill). Stored as JSONB array of role strings.
    roles: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Email-verification gate for self-service registration (POST /api/auth/register).
    # ``True`` = address confirmed (legacy email/password users, Microsoft SSO
    # users, and admin-created accounts are all implicitly verified — backfilled
    # by migration 0139 with server_default true). ``False`` = a self-registered
    # account whose owner has NOT yet clicked the verification link; login is
    # blocked until they do (see app/api/auth.py:login). Set to False only by the
    # self-registration endpoint, flipped to True by POST /api/auth/verify-email.
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    # KPI Coach opt-in flag. Default True → every operational recruiter gets
    # the in-app coaching (praise/remind/eod summary). User can disable in
    # Settings → Coaching. Non-operational roles (admin, head_of_recruitment,
    # delivery_lead, user) are filtered out at API/service layer regardless.
    kpi_coach_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    # First-login onboarding gate.
    # `delivery_lead` and `recruiter` must complete a role-specific onboarding
    # flow (see backend/app/api/onboarding.py) before accessing the app.
    # Existing users with other roles are backfilled to True by migration
    # 0035 so the rollout does not block them.
    profile_completed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    profile_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Force-change-password gate. Po admin-resecie hasła (manual)
    # ustawiamy True; middleware frontendu przekierowuje wszędzie
    # poza /profile, dopóki user nie zmieni hasła sam (POST
    # /api/auth/change-password) — wtedy flagę clearujemy. Pole
    # dodane w migracji 0078_password_reset_infrastructure (z
    # server_default=false dla istniejących userów).
    force_password_change: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    force_password_change_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Server-side session-revocation floor (F-05, migracja 0192).
    # NULL = brak floora → każdy ważny (niewygasły) token jest akceptowany
    # (tak jak dotąd — istniejący userzy nie są dotknięci). Ustawiane na
    # ``now()`` przy KAŻDYM zdarzeniu zmiany hasła: self-service change-password,
    # reset przez token z maila oraz admin-reset. ``get_current_user`` i ścieżka
    # ``/refresh`` odrzucają (401) token, którego ``iat`` jest ściśle wcześniejszy
    # niż ta wartość — dzięki temu wykradziony/wyciekły token NIE przeżywa
    # resetu hasła. Świadomie unieważnia też bieżącą sesję właściciela (musi się
    # zalogować ponownie) — to zamierzone przy „invalidate existing sessions".
    tokens_valid_after: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Monotoniczny numer polityki dostępu osadzany w access i refresh JWT.
    # Zmiana ról zwiększa wartość, więc stary token nie może po cichu odziedziczyć
    # nowych praw po ponownym wczytaniu usera z DB.
    authorization_version: Mapped[int] = mapped_column(
        BigInteger, default=1, server_default="1", nullable=False
    )

    # Last time this user had an active WS connection. Updated by
    # `ConnectionManager.connect/disconnect` in `app.api.ws`. Used by the
    # email-fallback background task: when a chat notification is older
    # than 15 min and the user's last_seen_at is also older than 15 min,
    # send the notification by email instead of just WS.
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # ── SSO identity provider (Faza B, migracja 0081) ────────────────────────
    # NULL = legacy email/password user. Set to "microsoft" przy SSO login;
    # razem z external_id (Azure ``oid``) tworzy partial-unique key.
    oauth_provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    azure_oid: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    microsoft_upn: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # ── AAD group-based RBAC (Phase 7.2, migracja 0107) ───────────────────────
    # List of ``{"id": "<guid>", "displayName": "..."}`` snapshots refreshed on
    # every SSO login when ``AAD_GROUP_RBAC_ENABLED=true``. Role is derived from
    # this list via ``AAD_GROUP_ROLE_MAP_JSON`` (first match wins). The
    # ``displayName`` is retained so admins can audit "which group granted X
    # this role at last login" even after the group is renamed in AAD.
    # Default ``list`` keeps the SQLAlchemy in-memory state consistent with the
    # DB-level ``'[]'::jsonb`` default for rows created via raw SQL.
    aad_group_ids: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )

    # ── CloudTalk telephony (Phase CloudTalk.2, migracja 0099) ──────────────
    # When non-NULL, links this user to a CloudTalk agent. The mapping is set
    # via POST /api/cloudtalk/agents/{id}/assign (or auto-linked on email match
    # by /sync-agents). Required for outbound click-to-call (Phase 3) and
    # webhook user_id resolution (Call.user_id set when webhook payload carries
    # an agent.id that matches this column).
    cloudtalk_agent_id: Mapped[Optional[int]] = mapped_column(
        Integer, unique=True, nullable=True, index=True
    )

    # ── DynaReporter migration (Phase B.0, migracja 0112) ───────────────────
    # Lista identyfikatorów modułów DynaReportera do których user ma dostęp:
    # ``body-leasing``, ``sales``, ``delivery-lead``, ``placements``,
    # ``clients-mrr``, ``competitions``, ``przetargi``, ``board``,
    # ``sales-mgmt``, ``mindy``, ``admin``. Pusta lista (default) = brak
    # dostępu do żadnego modułu DynaReportera. Pattern świadomie analogiczny
    # do ``aad_group_ids`` — JSONB + GIN index → query "którzy userzy mają
    # sekcję X" via `allowed_sections @> '["body-leasing"]'::jsonb`.
    allowed_sections: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )

    # Link do oryginalnego ``users.id`` z systemu DynaReporter (Render /
    # Coolify standalone). Wypełniany przez ETL przy email-match. NULL =
    # user nigdy nie był w DynaReporterze. Partial unique constraint w DB
    # gwarantuje że jeden legacy id mapuje się na najwyżej jednego nexus
    # usera.
    dynareporter_legacy_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )

    # Relationships
    authored_notes = relationship(
        "Note", back_populates="author", foreign_keys="Note.author_id"
    )
    pipeline_moves = relationship(
        "CandidateStage",
        back_populates="moved_by_user",
        foreign_keys="CandidateStage.moved_by",
    )
    activities = relationship("Activity", back_populates="user")
    user_activities = relationship("UserActivity", back_populates="user")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"

    # ── Multi-role helpers (migracja 0110) ───────────────────────────────────
    def get_all_roles(self) -> set[UserRole]:
        """Return the union of primary ``role`` and secondary ``roles``.

        Unknown strings in ``roles`` (e.g. an old role removed from the enum)
        are silently dropped so a stale row never raises ``ValueError`` deep
        in a permission check.
        """
        out: set[UserRole] = set()
        if self.role is not None:
            out.add(self.role)
        for r in self.roles or []:
            try:
                out.add(UserRole(r))
            except ValueError:
                continue
        return out

    def has_role(self, role: UserRole | str) -> bool:
        """True if user holds ``role`` (primary or secondary)."""
        target = role.value if isinstance(role, UserRole) else str(role)
        if self.role is not None and self.role.value == target:
            return True
        return target in (self.roles or [])

    def has_any_role(self, *roles: UserRole) -> bool:
        """True if user holds at least one of the given roles."""
        return any(self.has_role(r) for r in roles)

    def ensure_roles_invariant(self) -> None:
        """Ensure ``role.value`` is present in ``roles``.

        Call this whenever ``role`` is reassigned outside the SSO callback so
        the primary stays inside the multi-role set. Idempotent.
        """
        if self.role is None:
            return
        primary_str = self.role.value
        current = list(self.roles or [])
        if primary_str not in current:
            self.roles = [primary_str] + current

    def ensure_exclusive_roles(self) -> None:
        """Finance and legacy viewer are exclusive personas."""

        role_values = {role.value for role in self.get_all_roles()}
        exclusive = {
            UserRole.finance.value,
            UserRole.user.value,
        }.intersection(role_values)
        if exclusive and len(role_values) != 1:
            role_name = (
                UserRole.finance.value
                if UserRole.finance.value in exclusive
                else UserRole.user.value
            )
            raise ValueError(f"{role_name} role cannot be combined with other roles")
