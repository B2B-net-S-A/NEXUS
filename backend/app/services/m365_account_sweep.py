"""Konto NEXUSA idzie za kontem Microsoft 365 (decyzja Artura 22.10.2026).

Powód: konta zakładane przy pierwszym logowaniu Microsoftem zostawały
aktywne (z rolą i dostępem do bazy kandydatów) po usunięciu konta osoby
w Entra ID — 22.10.2026 dziewięć takich kont trafiło do katalogu „Ludzie”.

Przebieg: dla każdego aktywnego konta z ``azure_oid`` czytamy
``GET /users/{oid}?$select=id,accountEnabled`` tokenem rejestracji
„NEXUS Kadry” (``User.Read.All``, transport ``hr/m365/directory.py``).
Konto wyłączamy wyłącznie na jednoznaczny sygnał z katalogu:

* 404 z kodem ``Request_ResourceNotFound`` — obiektu nie ma w tenancie
  (usunięty, także ten w koszu ``deletedItems``),
* ``accountEnabled`` równe ``false`` — konto zablokowane w Entra ID.

Bezpieczniki:

* tryb z ``M365_ACCOUNT_SWEEP_MODE``: ``off`` — nic; ``report`` (domyślny,
  także przy nieznanej wartości) — log i wynik bez zapisu; ``enforce`` — zapis;
* brak poświadczeń, 401/403 rejestracji — przebieg kończy się bez zmian;
  błąd sieci, 5xx, 429 i każdy inny błąd przy koncie — to konto zostaje
  bez zmian (liczone w ``errors``), wraca przy następnym przebiegu;
* więcej niż ``M365_ACCOUNT_SWEEP_MAX_PER_RUN`` kont do wyłączenia —
  alarm w logu (ERROR → Sentry) i żadnej zmiany: masowy 404 to raczej zły
  tenant albo zła rejestracja niż masowe odejście;
* ostatniego aktywnego admina nie wyłączamy
  (``protect_active_admin_membership``);
* admin, który po naszym wyłączeniu włączył konto z powrotem
  (``active_changed`` na ``true``), wygrywa — przebieg tego konta nie rusza.

Wyłączenie: ``deactivate_account`` (to samo co ``DELETE /api/admin/users/{id}``)
z akcją ``m365_account_gone_deactivated``; listener kartoteki zamyka ją sam.
Pętla (``app/tasks/m365_account_sweep.py``) nie zależy od
``HR_PROGRAM_ENABLED`` — chodzi o dostęp do danych, nie o moduł kadrowy.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.user import User
from app.services.account_deactivation import deactivate_account
from app.services.admin_active_decision import ADMIN_ACTIVE_DECISION_ACTIONS
from app.services.admin_membership import protect_active_admin_membership
from app.services.hr.m365.directory import account_disabled
from app.services.hr.m365.ops import MailboxError

logger = logging.getLogger(__name__)

DEACTIVATION_ACTION = "m365_account_gone_deactivated"
MODES = ("off", "report", "enforce")
#: Kody 404 Graph, które znaczą „takiego obiektu nie ma” — inny kod przy 404
#: (zmiana API, zła ścieżka) to błąd, nie usunięte konto.
GONE_CODES = frozenset({"Request_ResourceNotFound", "ResourceNotFound"})
#: Odmowa dla całej rejestracji — kolejne konta dostałyby to samo.
ABORT_CATEGORIES = frozenset({"auth", "forbidden"})
#: Górna granica kont czytanych w jednym przebiegu (zespół to kilkadziesiąt osób).
MAX_ACCOUNTS = 1000


class AccountDirectory(Protocol):
    async def get_account(self, object_id: str) -> dict[str, Any]: ...

    async def aclose(self) -> None: ...


def current_mode() -> str:
    value = (settings.M365_ACCOUNT_SWEEP_MODE or "").strip().lower()
    return value if value in MODES else "report"


def max_per_run() -> int:
    return max(1, settings.M365_ACCOUNT_SWEEP_MAX_PER_RUN)


def gone_reason(
    data: Optional[dict[str, Any]], error: Optional[MailboxError]
) -> Optional[str]:
    """Odpowiedź katalogu → powód wyłączenia albo ``None`` (konto zostaje)."""

    if error is not None:
        if error.status == 404 and error.code in GONE_CODES:
            return "not_found"
        return None
    if data is not None and account_disabled(data):
        return "disabled"
    return None


def _default_directory() -> AccountDirectory:
    from app.services.hr.m365.directory import GraphDirectoryOps

    return GraphDirectoryOps()


def _credentials_configured() -> bool:
    from app.services.hr.m365.auth import credentials_configured

    return credentials_configured()


async def _kept_by_admin(db: AsyncSession, user_id: int) -> bool:
    """Admin włączył konto po naszym ostatnim wyłączeniu."""

    swept_at = await db.scalar(
        select(func.max(Activity.created_at)).where(
            Activity.entity_type == "user",
            Activity.entity_id == user_id,
            Activity.action == DEACTIVATION_ACTION,
        )
    )
    if swept_at is None:
        return False
    decision = await db.scalar(
        select(Activity)
        .where(
            Activity.entity_type == "user",
            Activity.entity_id == user_id,
            Activity.action.in_(ADMIN_ACTIVE_DECISION_ACTIONS),
            Activity.created_at > swept_at,
        )
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .limit(1)
    )
    if decision is None or decision.action != "active_changed":
        return False
    details = decision.details if isinstance(decision.details, dict) else {}
    return details.get("to") is True


async def _deactivate(
    db: AsyncSession, user_id: int, object_id: str, reason: str, now: datetime
) -> str:
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or not user.is_active or user.azure_oid != object_id:
        await db.rollback()
        return "changed_meanwhile"
    try:
        await protect_active_admin_membership(
            db,
            actor_id=None,
            target=user,
            next_roles=[role.value for role in user.get_all_roles()],
            next_active=False,
            protect_self=False,
        )
    except HTTPException:
        await db.rollback()
        return "last_admin"
    await deactivate_account(
        db,
        user,
        action=DEACTIVATION_ACTION,
        actor_id=None,
        details={
            "target_email": user.email,
            "m365_reason": reason,
            "source": "m365_account_sweep",
        },
        now=now,
    )
    await db.commit()
    return "deactivated"


async def run_once(
    db: AsyncSession,
    *,
    directory: Optional[AccountDirectory] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    mode = current_mode()
    result: dict[str, Any] = {"mode": mode}
    if mode == "off":
        return {**result, "status": "disabled"}
    if directory is None:
        if not _credentials_configured():
            logger.warning(
                "m365_account_sweep: brak poświadczeń „NEXUS Kadry” — bez zmian"
            )
            return {**result, "status": "no_credentials"}
        directory = _default_directory()

    targets = (
        await db.execute(
            select(User.id, User.azure_oid)
            .where(
                User.is_active.is_(True),
                User.azure_oid.is_not(None),
                User.azure_oid != "",
            )
            .order_by(User.id)
            .limit(MAX_ACCOUNTS)
        )
    ).all()
    await db.rollback()

    found: list[tuple[int, str, str]] = []
    errors = 0
    try:
        for user_id, object_id in targets:
            data: Optional[dict[str, Any]] = None
            error: Optional[MailboxError] = None
            try:
                data = await directory.get_account(object_id)
            except MailboxError as exc:
                if exc.category in ABORT_CATEGORIES:
                    logger.warning(
                        "m365_account_sweep: rejestracja odrzucona (%s) — bez zmian",
                        exc.label,
                    )
                    return {**result, "status": "aborted", "error": exc.label}
                error = exc
            reason = gone_reason(data, error)
            if reason is not None:
                found.append((user_id, object_id, reason))
            elif error is not None:
                errors += 1
    finally:
        await directory.aclose()

    result.update(checked=len(targets), errors=errors)
    planned_ids = [user_id for user_id, _, _ in found]
    limit = max_per_run()
    if len(found) > limit:
        logger.error(
            "m365_account_sweep: %d kont do wyłączenia (limit %d) — podejrzenie "
            "złego tenanta albo rejestracji, nic nie wyłączam; user_ids=%s",
            len(found),
            limit,
            planned_ids,
        )
        return {**result, "status": "mass_suspected", "planned": planned_ids}

    kept: list[int] = []
    planned: list[tuple[int, str, str]] = []
    for user_id, object_id, reason in found:
        if await _kept_by_admin(db, user_id):
            kept.append(user_id)
        else:
            planned.append((user_id, object_id, reason))
    await db.rollback()
    result.update(
        status="ok",
        planned=[user_id for user_id, _, _ in planned],
        kept_by_admin=kept,
    )
    if mode != "enforce":
        if planned:
            logger.warning(
                "m365_account_sweep (report): konta do wyłączenia %s",
                [(user_id, reason) for user_id, _, reason in planned],
            )
        return result

    moment = now or datetime.now(timezone.utc)
    outcomes: dict[str, list[int]] = {}
    for user_id, object_id, reason in planned:
        outcome = await _deactivate(db, user_id, object_id, reason, moment)
        outcomes.setdefault(outcome, []).append(user_id)
    if outcomes.get("last_admin"):
        logger.error(
            "m365_account_sweep: ostatni aktywny admin bez konta M365 — zostaje "
            "włączony; user_ids=%s",
            outcomes["last_admin"],
        )
    if outcomes.get("deactivated"):
        logger.warning(
            "m365_account_sweep: wyłączone konta %s", outcomes["deactivated"]
        )
    result.update(
        deactivated=outcomes.get("deactivated", []),
        skipped_last_admin=outcomes.get("last_admin", []),
    )
    return result
