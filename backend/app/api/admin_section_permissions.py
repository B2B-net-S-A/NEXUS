"""Admin-only API for role permissions and per-user grants.

Ekran Ustawienia → Zespół i dostęp → „Osoby i role”: dziewięć uprawnień tak/nie
na rolę i nadania dla pojedynczych osób. Kontrakt odpowiedzi:
``docs/permissions-nine-switches-contract.md`` §7.

Sekcje Delivery i Finanse wynikają z uprawnień, więc tędy się ich nie ustawia.
Sourcing, Pipeline, Insights i poziomy Generatora B2B API przyjmuje jak dotąd,
choć ekran ich już nie pokazuje.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.models.section_permission import (
    RbacPermissionAudit,
    RbacPolicyState,
    RoleActionPermission,
    RoleSectionPermission,
    UserActionOverride,
    UserSectionOverride,
)
from app.models.user import User, UserRole
from app.services import permission_catalog as catalog
from app.services.action_permissions import (
    NAMED_PERMISSIONS,
    UNGRANTABLE_ROLES,
    ActionAccess,
    ProductAction,
    account_accepts_grants,
    base_action_policy_from_rows,
    close_named_permissions,
    serialize_action_access,
)
from app.services.critical_events import record_executed
from app.services.effective_access import effective_access_from_rows
from app.services.section_permissions import (
    DERIVED_SECTIONS,
    ProductSection,
    SectionAccess,
    base_policy_from_rows,
    derived_section_access,
    serialize_section_access,
)


router = APIRouter()

AccessName = Literal["none", "read", "write"]
OverrideName = Literal["inherit", "none", "read", "write"]
ActionAccessName = Literal["none", "view", "generate", "manage"]
ActionOverrideName = Literal["inherit", "none", "view", "generate", "manage"]

_NAMED = frozenset(NAMED_PERMISSIONS)
_UNGRANTABLE_ROLES = UNGRANTABLE_ROLES

_ROLE_LABELS: dict[UserRole, str] = {
    UserRole.admin: "Administrator",
    UserRole.finance: "Finanse",
    UserRole.head_of_recruitment: "Head of Recruitment",
    UserRole.delivery_lead: "Delivery Lead",
    UserRole.talent_community_manager: "Talent Community Manager",
    UserRole.tac: "TAC",
    UserRole.recruiter: "Rekruter",
    UserRole.sourcer: "Sourcer",
    UserRole.user: "Viewer (legacy)",
    UserRole.trainee: "Praktykant",
}


def _reject_levels_for_permission(action: ProductAction, access: str) -> None:
    """Uprawnienie z ekranu jest tak/nie — poziomy ma tylko Generator B2B."""

    if action in _NAMED and access in ("view", "generate"):
        raise ValueError(f"{catalog.label(action.value)}: wybierz Brak lub Dozwolone")


class RolePermissionChange(BaseModel):
    role: UserRole
    section: ProductSection
    access: AccessName


class RoleActionPermissionChange(BaseModel):
    role: UserRole
    action: ProductAction
    access: ActionAccessName

    @model_validator(mode="after")
    def validate_permission_access(self):
        _reject_levels_for_permission(self.action, self.access)
        return self


class RolePermissionUpdate(BaseModel):
    revision: int = Field(..., ge=1)
    changes: list[RolePermissionChange] = Field(
        default_factory=list, max_length=len(UserRole) * len(ProductSection)
    )
    action_changes: list[RoleActionPermissionChange] = Field(
        default_factory=list, max_length=len(UserRole) * len(ProductAction)
    )


class UserPermissionChange(BaseModel):
    section: ProductSection
    access: OverrideName


class UserActionPermissionChange(BaseModel):
    action: ProductAction
    access: ActionOverrideName

    @model_validator(mode="after")
    def validate_permission_access(self):
        _reject_levels_for_permission(self.action, self.access)
        return self


class UserPermissionUpdate(BaseModel):
    revision: int = Field(..., ge=1)
    changes: list[UserPermissionChange] = Field(default_factory=list, max_length=6)
    action_changes: list[UserActionPermissionChange] = Field(
        default_factory=list, max_length=len(ProductAction)
    )


def _unprocessable(code: str, message: str | None = None) -> HTTPException:
    detail: dict[str, str] = {"code": code}
    if message:
        detail["message"] = message
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
    )


def _derived_section_error() -> HTTPException:
    return _unprocessable(
        "derived_section_access",
        "Dostęp do Delivery i Finansów wynika z uprawnień.",
    )


def _role_not_grantable_error() -> HTTPException:
    return _unprocessable(
        "role_not_grantable",
        "Role Viewer i Praktykant nie przyjmują uprawnień z tego ekranu.",
    )


def _role_grantable(role: UserRole) -> bool:
    return role is not UserRole.admin and role not in _UNGRANTABLE_ROLES


_account_grantable = account_accepts_grants


def _in_catalog_order(keys: Iterable[str]) -> list[str]:
    held = set(keys)
    return [key for key in catalog.KEYS if key in held]


def _granted_keys(policy: Mapping[ProductAction, ActionAccess]) -> frozenset[str]:
    return frozenset(
        action.value
        for action in NAMED_PERMISSIONS
        if policy.get(action, ActionAccess.none) >= ActionAccess.manage
    )


async def _policy_state(db: AsyncSession, *, lock: bool = False) -> RbacPolicyState:
    statement = select(RbacPolicyState).where(RbacPolicyState.id == 1)
    if lock:
        statement = statement.with_for_update()
    state_row = await db.scalar(statement)
    if state_row is None:
        # Never reconstruct policy from code in a live request. Missing
        # bootstrap data is an operational fault and must fail closed.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "section_policy_unavailable"},
        )
    return state_row


async def _revalidate_locked_admin(db: AsyncSession, admin: User) -> User:
    """Linearize a policy mutation with concurrent role/status changes."""

    locked_admin = await db.scalar(
        select(User)
        .where(User.id == admin.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        locked_admin is None
        or not locked_admin.is_active
        or not locked_admin.has_role(UserRole.admin)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "administrator_access_changed"},
        )
    return locked_admin


def _assert_unique(items: list[tuple[str, str]]) -> None:
    if len(items) != len(set(items)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "duplicate_permission_change"},
        )


def _assert_revision(state_row: RbacPolicyState, expected: int) -> None:
    if state_row.revision != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale_section_policy",
                "expected_revision": expected,
                "current_revision": state_row.revision,
            },
        )


async def _flush_policy_rows(db: AsyncSession) -> None:
    """Zapisz wiersze polityki; odmowa bazy to czytelny błąd, nie 500.

    Baza, w której siatka przy starcie nie poszerzyła CHECK-a akcji, odrzuca
    wiersz nowego uprawnienia. Admin ma zobaczyć zdanie, a nie „Network Error”.
    """

    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "permission_storage_rejected",
                "message": (
                    "Baza nie przyjęła zmiany uprawnień. "
                    "Zgłoś to administratorowi systemu."
                ),
            },
        ) from exc


async def _matrix_rows(
    db: AsyncSession,
) -> tuple[list[RoleSectionPermission], list[RoleActionPermission]]:
    section_rows = list((await db.scalars(select(RoleSectionPermission))).all())
    action_rows = list((await db.scalars(select(RoleActionPermission))).all())
    return section_rows, action_rows


async def _active_users_per_role(db: AsyncSession) -> Counter[str]:
    """Ile aktywnych kont ma daną rolę (główną albo dodatkową)."""

    counts: Counter[str] = Counter()
    rows = await db.execute(
        select(User.role, User.roles).where(User.is_active.is_(True))
    )
    for primary, secondary in rows.all():
        held = {str(value) for value in (secondary or [])}
        if primary is not None:
            held.add(primary.value if isinstance(primary, UserRole) else str(primary))
        counts.update(held)
    return counts


def _role_payload(
    role: UserRole,
    section_rows: list[RoleSectionPermission],
    action_rows: list[RoleActionPermission],
    users_count: int = 0,
) -> dict[str, object]:
    if role is UserRole.admin:
        permissions = {
            section.value: SectionAccess.write.name for section in ProductSection
        }
        action_permissions = {
            action.value: ActionAccess.manage.name for action in ProductAction
        }
        granted = frozenset(catalog.KEYS)
    else:
        # Ta sama reguła co resolver żądania: rola bez wierszy zasiewu jest
        # liczona funkcją zasiewu z jej zapisanych sekcji.
        stored = base_action_policy_from_rows([role], action_rows, section_rows)
        granted = _granted_keys(stored)
        sections = base_policy_from_rows([role], section_rows)
        sections.update(derived_section_access(catalog.close(granted)))
        sections[ProductSection.system_admin] = SectionAccess.none
        permissions = serialize_section_access(sections)
        action_permissions = serialize_action_access(close_named_permissions(stored))
    effective = catalog.close(granted)
    return {
        "role": role.value,
        "users_count": users_count,
        "grantable": _role_grantable(role),
        "permissions": permissions,
        "action_permissions": action_permissions,
        "named": {
            key: {
                "granted": key in granted,
                "effective": key in effective,
                "implied_by": list(catalog.implied_by(key, granted)),
            }
            for key in catalog.KEYS
        },
        "locked": role is UserRole.admin,
        "locked_sections": [ProductSection.system_admin.value],
    }


async def _role_snapshot(db: AsyncSession) -> dict[str, object]:
    state_row = await _policy_state(db)
    section_rows, action_rows = await _matrix_rows(db)
    users_per_role = await _active_users_per_role(db)
    fixture = catalog.as_fixture()
    return {
        "revision": state_row.revision,
        "sections": [section.value for section in ProductSection],
        "actions": [action.value for action in ProductAction],
        "derived_sections": [
            section.value for section in ProductSection if section in DERIVED_SECTIONS
        ],
        "permission_groups": fixture["groups"],
        "permissions": fixture["permissions"],
        "roles": [
            _role_payload(
                role, section_rows, action_rows, users_per_role.get(role.value, 0)
            )
            for role in UserRole
        ],
        "updated_at": state_row.updated_at,
        "updated_by": state_row.updated_by,
    }


def _user_permission_payload(
    user: User,
    *,
    section_role_rows: list[RoleSectionPermission],
    section_override_rows: list[UserSectionOverride],
    action_role_rows: list[RoleActionPermission],
    action_override_rows: list[UserActionOverride],
) -> dict[str, object]:
    """Uprawnienia jednej osoby: co dają role, co nadano jej, co ma w sumie."""

    from_roles = effective_access_from_rows(
        user,
        section_role_rows=section_role_rows,
        section_override_rows=(),
        action_role_rows=action_role_rows,
        action_override_rows=(),
    )
    effective = effective_access_from_rows(
        user,
        section_role_rows=section_role_rows,
        section_override_rows=section_override_rows,
        action_role_rows=action_role_rows,
        action_override_rows=action_override_rows,
    )
    stored = {
        row.action: row.access
        for row in action_override_rows
        if row.user_id == user.id and row.action in catalog.BY_KEY
    }
    derived = {section.value for section in DERIVED_SECTIONS}
    return {
        "user_id": user.id,
        "name": user.name,
        "role": user.role.value,
        "roles": sorted(role.value for role in user.get_all_roles()),
        "locked": user.has_role(UserRole.admin),
        "grantable": _account_grantable(user),
        "role_permissions": _in_catalog_order(from_roles.permissions),
        "grants": _in_catalog_order(
            key for key, access in stored.items() if access == ActionAccess.manage.name
        ),
        # Stare wyjątki odbierające; nowy ekran ich nie tworzy, tylko zdejmuje.
        "restrictions": _in_catalog_order(
            key for key, access in stored.items() if access != ActionAccess.manage.name
        ),
        "effective": _in_catalog_order(effective.permissions),
        "legacy_section_caps": {
            row.section: row.access
            for row in section_override_rows
            if row.user_id == user.id and row.section in derived
        },
    }


def _labels(keys: Iterable[str]) -> str:
    return ", ".join(f"„{catalog.label(key)}”" for key in keys)


def _describe(groups: list[tuple[str, list[str]]], other: list[str]) -> str:
    """Zdanie do Historii zdarzeń: nazwy uprawnień zamiast kluczy."""

    parts = [f"{title}: {_labels(keys)}." for title, keys in groups if keys]
    if other:
        parts.append(f"Inne: {'; '.join(other)}.")
    return " ".join(parts)


def _other_changes(changes: Mapping[str, Mapping[str, str]]) -> list[str]:
    return [
        f"{key}: {change['from']} → {change['to']}"
        for key, change in changes.items()
        if key not in catalog.BY_KEY
    ]


def _role_summary(changes: Mapping[str, Mapping[str, str]]) -> str:
    named = {key: change for key, change in changes.items() if key in catalog.BY_KEY}
    manage = ActionAccess.manage.name
    return _describe(
        [
            ("Włączono", [k for k, c in named.items() if c["to"] == manage]),
            (
                "Wyłączono",
                [
                    k
                    for k, c in named.items()
                    if c["to"] != manage and c["from"] == manage
                ],
            ),
            # Wiersza nie było, więc dostępu też nie — admin zapisał „nie” wprost.
            (
                "Zapisano brakujący wpis bez zmiany dostępu",
                [
                    k
                    for k, c in named.items()
                    if c["to"] != manage and c["from"] != manage
                ],
            ),
        ],
        _other_changes(changes),
    )


def _user_summary(changes: Mapping[str, Mapping[str, str]]) -> str:
    named = {key: change for key, change in changes.items() if key in catalog.BY_KEY}
    manage = ActionAccess.manage.name
    return _describe(
        [
            ("Nadano", [k for k, c in named.items() if c["to"] == manage]),
            (
                "Zdjęto nadanie",
                [
                    k
                    for k, c in named.items()
                    if c["to"] != manage and c["from"] == manage
                ],
            ),
            (
                "Usunięto ograniczenie",
                [
                    k
                    for k, c in named.items()
                    if c["to"] != manage and c["from"] != manage
                ],
            ),
        ],
        _other_changes(changes),
    )


def _section_event_key(section: str) -> str:
    return f"section:{section}"


def _action_event_key(action: str) -> str:
    return action if action in catalog.BY_KEY else f"action:{action}"


@router.get("")
async def read_role_section_permissions(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Return the role matrix, the permission catalogue and the revision."""

    return await _role_snapshot(db)


@router.get("/users")
async def read_user_section_permissions(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    search: str = Query(default="", max_length=120),
    limit: int = Query(default=100, ge=1, le=250),
):
    """Return accounts with inherited, overridden and effective access."""

    state_row = await _policy_state(db)
    query = select(User).order_by(User.is_active.desc(), User.name, User.id)
    count_query = select(func.count(User.id))
    needle = search.strip()
    if needle:
        predicate = or_(
            User.name.ilike(f"%{needle}%"),
            User.email.ilike(f"%{needle}%"),
        )
        query = query.where(predicate)
        count_query = count_query.where(predicate)
    users = list((await db.scalars(query.limit(limit))).all())
    total = int((await db.scalar(count_query)) or 0)
    role_rows, action_role_rows = await _matrix_rows(db)
    user_ids = [user.id for user in users]
    override_rows = list(
        (
            await db.scalars(
                select(UserSectionOverride).where(
                    UserSectionOverride.user_id.in_(user_ids or [-1])
                )
            )
        ).all()
    )
    overrides_by_user: dict[int, list[UserSectionOverride]] = {}
    for override in override_rows:
        overrides_by_user.setdefault(override.user_id, []).append(override)
    action_override_rows = list(
        (
            await db.scalars(
                select(UserActionOverride).where(
                    UserActionOverride.user_id.in_(user_ids or [-1])
                )
            )
        ).all()
    )
    action_overrides_by_user: dict[int, list[UserActionOverride]] = {}
    for override in action_override_rows:
        action_overrides_by_user.setdefault(override.user_id, []).append(override)

    payload_users: list[dict[str, object]] = []
    for user in users:
        user_overrides = overrides_by_user.get(user.id, [])
        user_action_overrides = action_overrides_by_user.get(user.id, [])
        # Delivery i Finanse wynikają z uprawnień, więc sekcje i akcje liczy
        # jedno wejście — osobno policzone sekcje pokazywałyby tu „brak”.
        inherited = effective_access_from_rows(
            user,
            section_role_rows=role_rows,
            section_override_rows=(),
            action_role_rows=action_role_rows,
            action_override_rows=(),
        )
        effective = effective_access_from_rows(
            user,
            section_role_rows=role_rows,
            section_override_rows=user_overrides,
            action_role_rows=action_role_rows,
            action_override_rows=user_action_overrides,
        )
        payload_users.append(
            {
                "user_id": user.id,
                "name": user.name,
                "email": user.email,
                "role": user.role.value,
                "roles": sorted(role.value for role in user.get_all_roles()),
                "is_active": user.is_active,
                "locked": user.has_role(UserRole.admin),
                "overrides": {row.section: row.access for row in user_overrides},
                "inherited_permissions": serialize_section_access(inherited.sections),
                "effective_permissions": serialize_section_access(effective.sections),
                "action_overrides": {
                    row.action: row.access for row in user_action_overrides
                },
                "inherited_action_permissions": serialize_action_access(
                    inherited.actions
                ),
                "effective_action_permissions": serialize_action_access(
                    effective.actions
                ),
                "scope_summary": (
                    "Tylko przypisani klienci"
                    if user.has_role(UserRole.delivery_lead)
                    and not user.has_any_role(UserRole.admin, UserRole.finance)
                    else "Zakres danych nadal wynika z roli i przypisań"
                ),
            }
        )

    return {"revision": state_row.revision, "users": payload_users, "total": total}


@router.get("/users/{user_id}")
async def read_user_permissions(
    user_id: int,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Uprawnienia jednej osoby do okna „Edytuj użytkownika”."""

    state_row = await _policy_state(db)
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    section_role_rows, action_role_rows = await _matrix_rows(db)
    section_override_rows = list(
        (
            await db.scalars(
                select(UserSectionOverride).where(
                    UserSectionOverride.user_id == user_id
                )
            )
        ).all()
    )
    action_override_rows = list(
        (
            await db.scalars(
                select(UserActionOverride).where(UserActionOverride.user_id == user_id)
            )
        ).all()
    )
    return {
        "revision": state_row.revision,
        "user": _user_permission_payload(
            user,
            section_role_rows=section_role_rows,
            section_override_rows=section_override_rows,
            action_role_rows=action_role_rows,
            action_override_rows=action_override_rows,
        ),
    }


@router.put("/roles")
async def update_role_section_permissions(
    payload: RolePermissionUpdate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Atomically apply section/action changes and revoke affected sessions."""

    if not payload.changes and not payload.action_changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "empty_permission_change"},
        )
    _assert_unique(
        [
            (change.role.value, f"section:{change.section.value}")
            for change in payload.changes
        ]
        + [
            (change.role.value, f"action:{change.action.value}")
            for change in payload.action_changes
        ]
    )
    for change in payload.changes:
        if (
            change.role is UserRole.admin
            or change.section is ProductSection.system_admin
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "immutable_technical_admin_access"},
            )
        if change.section in DERIVED_SECTIONS:
            raise _derived_section_error()
    if any(change.role is UserRole.admin for change in payload.action_changes):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "immutable_admin_access"},
        )
    if any(
        change.action in _NAMED and change.role in _UNGRANTABLE_ROLES
        for change in payload.action_changes
    ):
        raise _role_not_grantable_error()

    state_row = await _policy_state(db, lock=True)
    admin = await _revalidate_locked_admin(db, admin)
    _assert_revision(state_row, payload.revision)
    requested_roles = sorted(
        {change.role.value for change in payload.changes}
        | {change.role.value for change in payload.action_changes}
    )
    existing_rows = list(
        (
            await db.scalars(
                select(RoleSectionPermission)
                .where(RoleSectionPermission.role.in_(requested_roles))
                .with_for_update()
            )
        ).all()
    )
    by_key = {(row.role, row.section): row for row in existing_rows}
    existing_action_rows = list(
        (
            await db.scalars(
                select(RoleActionPermission)
                .where(RoleActionPermission.role.in_(requested_roles))
                .with_for_update()
            )
        ).all()
    )
    action_by_key = {(row.role, row.action): row for row in existing_action_rows}
    # Rola bez ŻADNEGO wiersza zasiewanych uprawnień jest liczona funkcją
    # zasiewu (jak w resolverze). Zapis jednego wiersza zrobiłby z niej rolę
    # „zasianą częściowo”, czyli zamkniętą — dlatego przy pierwszej prawdziwej
    # zmianie zapisujemy komplet. Progi liczymy z sekcji sprzed tego żądania.
    unseeded: dict[str, dict[str, str]] = {}
    for role_value in requested_roles:
        if any((role_value, key) in action_by_key for key in catalog.SEEDED_KEYS):
            continue
        unseeded[role_value] = catalog.seed_rows_for_role(
            role_value,
            {
                section: row.access
                for (row_role, section), row in by_key.items()
                if row_role == role_value
            },
        )
    before: dict[str, str] = {}
    after: dict[str, str] = {}
    changed_roles: set[str] = set()
    event_changes: dict[str, dict[str, dict[str, str]]] = {}
    now = datetime.now(timezone.utc)

    for change in payload.changes:
        key = (change.role.value, change.section.value)
        row = by_key.get(key)
        old_access = row.access if row is not None else SectionAccess.none.name
        before[f"{key[0]}:{key[1]}"] = row.access if row is not None else "missing"
        after[f"{key[0]}:{key[1]}"] = change.access
        # A missing row resolves to ``none`` at runtime, but it must still be
        # materialized when an administrator explicitly saves ``none``.
        # This repairs the matrix without treating absence as a silent no-op.
        if row is not None and old_access == change.access:
            continue
        changed_roles.add(change.role.value)
        event_changes.setdefault(change.role.value, {})[
            _section_event_key(change.section.value)
        ] = {"from": before[f"{key[0]}:{key[1]}"], "to": change.access}
        if row is None:
            row = RoleSectionPermission(
                role=change.role.value,
                section=change.section.value,
                access=change.access,
            )
            db.add(row)
            by_key[key] = row
        else:
            row.access = change.access
        row.updated_by = admin.id
        row.updated_at = now

    for change in payload.action_changes:
        key = (change.role.value, change.action.value)
        audit_key = f"{key[0]}:action:{key[1]}"
        seed = unseeded.get(change.role.value)
        if seed is not None and change.action.value in seed:
            if seed[change.action.value] == change.access:
                # Rola już to ma (albo nie ma) z zasiewu — nie ma czego zapisać.
                before[audit_key] = change.access
                after[audit_key] = change.access
                continue
            for seeded_key, seeded_access in seed.items():
                seeded_row = RoleActionPermission(
                    role=change.role.value, action=seeded_key, access=seeded_access
                )
                db.add(seeded_row)
                action_by_key[(change.role.value, seeded_key)] = seeded_row
                seeded_audit_key = f"{change.role.value}:action:{seeded_key}"
                before.setdefault(seeded_audit_key, seeded_access)
                after.setdefault(seeded_audit_key, seeded_access)
            del unseeded[change.role.value]
        row = action_by_key.get(key)
        old_access = row.access if row is not None else ActionAccess.none.name
        before[audit_key] = row.access if row is not None else "missing"
        after[audit_key] = change.access
        if row is not None and old_access == change.access:
            continue
        changed_roles.add(change.role.value)
        event_changes.setdefault(change.role.value, {})[
            _action_event_key(change.action.value)
        ] = {"from": before[audit_key], "to": change.access}
        if row is None:
            row = RoleActionPermission(
                role=change.role.value,
                action=change.action.value,
                access=change.access,
            )
            db.add(row)
            action_by_key[key] = row
        else:
            row.access = change.access
        row.updated_by = admin.id
        row.updated_at = now

    if not changed_roles:
        return {
            "revision": state_row.revision,
            "changed": False,
            "invalidated_users": 0,
        }

    await _flush_policy_rows(db)
    next_revision = state_row.revision + 1
    state_row.revision = next_revision
    state_row.updated_by = admin.id
    state_row.updated_at = now

    role_conditions = []
    for role_value in changed_roles:
        role_enum = UserRole(role_value)
        role_conditions.extend(
            [User.role == role_enum, User.roles.contains([role_value])]
        )
    invalidation = await db.execute(
        update(User)
        .where(User.is_active.is_(True), or_(*role_conditions))
        .values(
            authorization_version=User.authorization_version + 1,
            tokens_valid_after=now,
        )
        .execution_options(synchronize_session=False)
    )
    invalidated_users = int(getattr(invalidation, "rowcount", 0) or 0)
    db.add(
        RbacPermissionAudit(
            actor_user_id=admin.id,
            target_kind="role",
            target_key=",".join(sorted(changed_roles)),
            revision=next_revision,
            before=before,
            after=after,
        )
    )
    # Historia zdarzeń: jeden wpis na rolę, w tej samej transakcji co zmiana —
    # uprawnienia nie zmieniają się bez widocznego śladu.
    for role_value in sorted(changed_roles):
        role_changes = event_changes.get(role_value, {})
        await record_executed(
            db,
            actor=admin,
            event_type="rbac.role_permissions",
            entity_type="role",
            entity_id=None,
            entity_label=_ROLE_LABELS.get(UserRole(role_value), role_value),
            reason=_role_summary(role_changes),
            details={
                "role": role_value,
                "revision": next_revision,
                "changes": role_changes,
            },
        )
    await db.flush()
    return {
        "revision": next_revision,
        "changed": True,
        "invalidated_users": invalidated_users,
    }


@router.put("/users/{user_id}")
async def update_user_section_permissions(
    user_id: int,
    payload: UserPermissionUpdate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Replace selected user overrides; ``inherit`` removes the stored row."""

    if not payload.changes and not payload.action_changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "empty_permission_change"},
        )
    _assert_unique(
        [
            (str(user_id), f"section:{change.section.value}")
            for change in payload.changes
        ]
        + [
            (str(user_id), f"action:{change.action.value}")
            for change in payload.action_changes
        ]
    )
    for change in payload.changes:
        if change.section is ProductSection.system_admin:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "immutable_technical_admin_access"},
            )
        # Stare ograniczenie Delivery/Finansów da się tylko zdjąć.
        if change.section in DERIVED_SECTIONS and change.access != "inherit":
            raise _derived_section_error()
    if any(
        change.action in _NAMED and change.access == "none"
        for change in payload.action_changes
    ):
        raise _unprocessable(
            "additive_only",
            "Uprawnienia osoby tylko dodają. Żeby coś odebrać, zmień "
            "uprawnienia roli albo rolę tej osoby.",
        )

    state_row = await _policy_state(db, lock=True)
    admin = await _revalidate_locked_admin(db, admin)
    _assert_revision(state_row, payload.revision)
    target = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if target.has_role(UserRole.admin):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "immutable_admin_access"},
        )
    if not _account_grantable(target) and any(
        change.action in _NAMED and change.access == "manage"
        for change in payload.action_changes
    ):
        raise _role_not_grantable_error()

    rows = list(
        (
            await db.scalars(
                select(UserSectionOverride)
                .where(UserSectionOverride.user_id == user_id)
                .with_for_update()
            )
        ).all()
    )
    by_section = {row.section: row for row in rows}
    action_rows = list(
        (
            await db.scalars(
                select(UserActionOverride)
                .where(UserActionOverride.user_id == user_id)
                .with_for_update()
            )
        ).all()
    )
    by_action = {row.action: row for row in action_rows}
    before = {row.section: row.access for row in rows}
    before.update({f"action:{row.action}": row.access for row in action_rows})
    event_changes: dict[str, dict[str, str]] = {}
    now = datetime.now(timezone.utc)
    changed = False
    for change in payload.changes:
        section = change.section.value
        row = by_section.get(section)
        old_access = row.access if row is not None else "inherit"
        if old_access != change.access:
            event_changes[_section_event_key(section)] = {
                "from": old_access,
                "to": change.access,
            }
        if change.access == "inherit":
            if row is not None:
                await db.delete(row)
                by_section.pop(section)
                changed = True
            continue
        if row is None:
            row = UserSectionOverride(
                user_id=user_id,
                section=section,
                access=change.access,
                updated_by=admin.id,
                updated_at=now,
            )
            db.add(row)
            by_section[section] = row
            changed = True
        elif row.access != change.access:
            row.access = change.access
            row.updated_by = admin.id
            row.updated_at = now
            changed = True

    for change in payload.action_changes:
        action = change.action.value
        row = by_action.get(action)
        old_access = row.access if row is not None else "inherit"
        if old_access != change.access:
            event_changes[_action_event_key(action)] = {
                "from": old_access,
                "to": change.access,
            }
        if change.access == "inherit":
            if row is not None:
                await db.delete(row)
                by_action.pop(action)
                changed = True
            continue
        if row is None:
            row = UserActionOverride(
                user_id=user_id,
                action=action,
                access=change.access,
                updated_by=admin.id,
                updated_at=now,
            )
            db.add(row)
            by_action[action] = row
            changed = True
        elif row.access != change.access:
            row.access = change.access
            row.updated_by = admin.id
            row.updated_at = now
            changed = True

    if not changed:
        return {
            "revision": state_row.revision,
            "changed": False,
            "invalidated_users": 0,
        }

    await _flush_policy_rows(db)
    next_revision = state_row.revision + 1
    state_row.revision = next_revision
    state_row.updated_by = admin.id
    state_row.updated_at = now
    target.authorization_version += 1
    target.tokens_valid_after = now
    after = {section: row.access for section, row in sorted(by_section.items())}
    after.update(
        {f"action:{action}": row.access for action, row in sorted(by_action.items())}
    )
    db.add(
        RbacPermissionAudit(
            actor_user_id=admin.id,
            target_kind="user",
            target_key=str(user_id),
            revision=next_revision,
            before=before,
            after=after,
        )
    )
    await record_executed(
        db,
        actor=admin,
        event_type="rbac.user_permissions",
        entity_type="user",
        entity_id=target.id,
        entity_label=f"{target.name} ({target.email})",
        reason=_user_summary(event_changes),
        details={"revision": next_revision, "changes": event_changes},
    )
    await db.flush()
    return {"revision": next_revision, "changed": True, "invalidated_users": 1}
