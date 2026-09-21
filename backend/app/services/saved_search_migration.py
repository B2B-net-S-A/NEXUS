"""Migracja zapisanych wyszukiwań kandydatów na wspólną semantykę filtrów.

Każdy zapis kandydacki (dwa formaty legacy — patrz ``saved_search_payload``)
jest przepisywany na format v3 (``semantics_version: 2``). Zanim to zrobimy,
PORÓWNUJEMY wynik: te same filtry puszczone dotychczasową semantyką (v1)
i wspólną (v2), przez PRAWDZIWE endpointy (in-process, token właściciela — zero
dryfu względem tego, co widzi rekruter i co liczy skaner alertów).

* wynik identyczny → migracja po cichu, alert działa dalej,
* wynik inny → migracja, ale ``requires_reapproval = true``, alert
  WSTRZYMANY (``notify_new_matches = false``, zapamiętane ``alert_was_on``),
  krótki opis różnicy (same LICZBY, bez danych osobowych) i JEDNO powiadomienie
  do właściciela. Akceptacja (istniejące ``confirm_reapproval`` w
  ``PATCH /api/saved-searches/{id}``) wznawia alert z NOWĄ linią bazową, więc
  nie ma burzy ``saved_search_match``.

Idempotentne: zapis już w formacie v3 jest pomijany. Bez DDL — kolumna
``requires_reapproval`` istnieje od wycofania stawek miesięcznych, szczegóły
jadą w JSONB ``filters.migration``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.services import saved_search_payload as payloads

logger = logging.getLogger(__name__)

MARKER_KEY = "saved_search_semantics_migration_v3"

# Ile identyfikatorów porównujemy na zapis (plus `total`). Szerokie wyszukiwanie
# nie może zamienić migracji w skan całej bazy.
COMPARE_ID_CAP = 500
_LIST_PAGE = 100
_SEARCH_PAGE = 200


def _auth_headers(owner: Any) -> dict[str, str]:
    from app.core.security import create_access_token

    token = create_access_token(
        subject=owner.id,
        role=getattr(owner.role, "value", str(owner.role)),
        roles=[role.value for role in owner.get_all_roles()],
        authorization_version=owner.authorization_version,
    )
    return {"Authorization": f"Bearer {token}"}


def _list_query(params: dict[str, Any]) -> list[tuple[str, Any]]:
    query: list[tuple[str, Any]] = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            query.extend((key, v) for v in value)
        elif isinstance(value, bool):
            query.append((key, "true" if value else "false"))
        else:
            query.append((key, value))
    return query


async def _collect_list(
    client: Any, headers: dict[str, str], params: dict[str, Any]
) -> tuple[list[int], int]:
    from app.tasks.saved_search_alerts import build_base_params

    base = build_base_params(params)
    ids: list[int] = []
    total = 0
    for page in range(1, COMPARE_ID_CAP // _LIST_PAGE + 1):
        resp = await client.get(
            "/api/candidates",
            params=_list_query({**base, "page": page}),
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        total = int(data.get("total") or 0)
        batch = [int(item["id"]) for item in data.get("items") or []]
        ids.extend(batch)
        if len(batch) < _LIST_PAGE:
            break
    return ids[:COMPARE_ID_CAP], total


async def _collect_search(
    client: Any, headers: dict[str, str], body: dict[str, Any]
) -> tuple[list[int], int]:
    ids: list[int] = []
    total = 0
    pages = -(-COMPARE_ID_CAP // _SEARCH_PAGE)
    for page in range(1, pages + 1):
        resp = await client.post(
            "/api/search/candidates",
            json={**body, "sort": "recent", "page": page, "page_size": _SEARCH_PAGE},
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        total = int(data.get("total") or 0)
        batch = [int(item["id"]) for item in data.get("items") or []]
        ids.extend(batch)
        if len(batch) < _SEARCH_PAGE:
            break
    return ids[:COMPARE_ID_CAP], total


def _diff_summary(
    legacy: tuple[list[int], int], unified: tuple[list[int], int], **extra: Any
) -> dict[str, Any]:
    """Wyłącznie liczby — żadnych identyfikatorów ani nazwisk."""
    legacy_ids, unified_ids = set(legacy[0]), set(unified[0])
    return {
        "legacy_total": legacy[1],
        "unified_total": unified[1],
        "only_legacy": len(legacy_ids - unified_ids),
        "only_unified": len(unified_ids - legacy_ids),
        "compared_ids": COMPARE_ID_CAP,
        **extra,
    }


async def _compare(
    client: Any,
    db: Any,
    owner: Any,
    filters: dict[str, Any],
    origin: str,
    request: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """→ ``(identyczne, podsumowanie)``."""
    headers = _auth_headers(owner)
    if origin == "candidates_list":
        legacy = await _collect_list(client, headers, dict(filters.get("api") or {}))
        unified = await _collect_list(
            client, headers, payloads.unified_to_list_params(request)
        )
    else:
        legacy_body = {
            k: v for k, v in filters.items() if k not in ("page", "page_size")
        }
        unified_body = payloads.unified_to_search_body(request)
        q = str(legacy_body.get("q") or "").strip()
        if q and legacy_body.get("search_mode") == "hybrid":
            # Tryb semantyczny woła dostawcę embeddingów i nie jest
            # deterministyczny — nie porównujemy go. Jeśli wspólna semantyka
            # potraktuje `q` jako OSOBĘ (dopasowanie dosłowne zamiast hybrydy),
            # wynik jest inny z definicji; w przeciwnym razie ścieżka tekstu
            # jest ta sama po obu stronach i porównujemy same filtry.
            from app.services import candidate_search_predicates as predicates

            interpretation = await predicates.interpret_text(db, q)
            if interpretation.mode == "literal":
                return False, {
                    "reason": "text_mode",
                    "rule": interpretation.rule,
                    "compared_ids": 0,
                }
            legacy_body = {k: v for k, v in legacy_body.items() if k != "q"}
            unified_body = {k: v for k, v in unified_body.items() if k != "q"}
        legacy = await _collect_search(client, headers, legacy_body)
        unified = await _collect_search(client, headers, unified_body)

    identical = legacy[1] == unified[1] and set(legacy[0]) == set(unified[0])
    return identical, _diff_summary(legacy, unified)


async def _notify_owner(db: Any, ss: Any, diff: dict[str, Any]) -> None:
    from app.models.notification import NotificationType
    from app.services.notification_triggers import emit
    from app.tasks.saved_search_alerts import build_link

    if "legacy_total" in diff:
        detail = (
            f"Dotąd {diff['legacy_total']} osób, po zmianie {diff['unified_total']}."
        )
    else:
        detail = "Tekst wyszukiwania jest teraz dopasowywany jako osoba."
    paused = (
        " Alert jest wstrzymany do akceptacji."
        if (ss.filters or {}).get("migration", {}).get("alert_was_on")
        else ""
    )
    await emit(
        db,
        user_id=ss.user_id,
        title=f"Sprawdź zapisane wyszukiwanie: {ss.name}",
        message=(
            "Ujednoliciliśmy filtry listy i wyszukiwarki kandydatów — ten zapis "
            f"zwraca teraz inny zbiór osób. {detail}{paused} Otwórz go i zatwierdź."
        ),
        ntype=NotificationType.saved_search_reapproval,
        related_entity_type="saved_search",
        related_entity_id=ss.id,
        link=build_link(ss.filters, ss.id),
    )


async def migrate_one(
    client: Any, db: Any, ss: Any, owner: Optional[Any], *, dry_run: bool = False
) -> str:
    """Migruje jeden zapis. Zwraca: ``already`` | ``unreadable`` | ``identical``
    | ``different`` | ``unverified``."""
    filters = ss.filters or {}
    fmt, origin, request = payloads.read_saved_search(filters)
    if fmt == "unified":
        return "already"
    if request is None or origin is None:
        return "unreadable"

    now = datetime.now(timezone.utc).isoformat()
    if owner is None or not getattr(owner, "is_active", False):
        # Bez aktywnego właściciela nie ma czyim tokenem porównać wyniku —
        # migrujemy ostrożnie: do akceptacji, bez powiadomienia (nie ma komu).
        outcome, identical, diff = "unverified", False, {"reason": "owner_inactive"}
    else:
        identical, diff = await _compare(client, db, owner, filters, origin, request)
        outcome = "identical" if identical else "different"
    if dry_run:
        return outcome

    alert_was_on = bool(ss.notify_new_matches)
    migration = {
        "from": fmt,
        "migrated_at": now,
        "outcome": outcome,
        "diff": diff,
        "alert_was_on": alert_was_on and not identical,
    }
    ss.filters = payloads.build_unified_payload(
        filters, origin=origin, request=request, migration=migration
    )
    if not identical:
        ss.requires_reapproval = True
        ss.notify_new_matches = False
        if outcome == "different":
            await _notify_owner(db, ss, diff)
    return outcome


async def migrate_saved_searches(*, dry_run: bool = False) -> dict[str, Any]:
    """Przebieg po wszystkich zapisach kandydackich. Commit per zapis — jedna
    awaria nie cofa reszty. Zwraca same liczniki i id (bez treści filtrów)."""
    from httpx import ASGITransport, AsyncClient

    from app.core.database import AsyncSessionLocal
    from app.main import app
    from app.models.saved_search import SavedSearch
    from app.models.user import User

    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "already": 0,
        "unreadable": 0,
        "identical": 0,
        "different": 0,
        "unverified": 0,
        "failed": 0,
        "needs_reapproval_ids": [],
    }
    async with AsyncSessionLocal() as db:
        ids = (
            (
                await db.execute(
                    select(SavedSearch.id)
                    .where(SavedSearch.entity.in_(("candidate", "candidates")))
                    .order_by(SavedSearch.id)
                )
            )
            .scalars()
            .all()
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://saved-search-migration"
        ) as client:
            for search_id in ids:
                try:
                    row = (
                        await db.execute(
                            select(SavedSearch, User)
                            .outerjoin(User, User.id == SavedSearch.user_id)
                            .where(SavedSearch.id == search_id)
                            .with_for_update(of=SavedSearch)
                        )
                    ).first()
                    if row is None:
                        continue
                    ss, owner = row
                    outcome = await migrate_one(client, db, ss, owner, dry_run=dry_run)
                    summary[outcome] += 1
                    if outcome in ("different", "unverified"):
                        summary["needs_reapproval_ids"].append(search_id)
                    if dry_run:
                        await db.rollback()
                    else:
                        await db.commit()
                except Exception as exc:  # noqa: BLE001 — izolacja per zapis
                    logger.warning(
                        "saved_search_migration: search %s failed (%s)",
                        search_id,
                        type(exc).__name__,
                    )
                    summary["failed"] += 1
                    await db.rollback()
    return summary


async def run_once_at_startup() -> Optional[dict[str, Any]]:
    """Jednorazowy przebieg przy starcie (marker w ``app_settings``).

    Włączany flagą ``SAVED_SEARCH_SEMANTICS_MIGRATION_AUTORUN`` — domyślnie OFF:
    migracja wstrzymuje alerty i wysyła powiadomienia, więc moment wybiera
    człowiek (albo admin woła ``POST /api/saved-searches/migrate-semantics``).
    """
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting

    if not getattr(settings, "SAVED_SEARCH_SEMANTICS_MIGRATION_AUTORUN", False):
        return None
    async with AsyncSessionLocal() as db:
        if await db.get(AppSetting, MARKER_KEY) is not None:
            return None
    summary = await migrate_saved_searches()
    await write_receipt(summary)
    return summary


async def write_receipt(summary: dict[str, Any]) -> None:
    """Paragon: liczniki + id zapisów do akceptacji. Upsert — ponowny przebieg
    (z endpointu admina) nadpisuje poprzedni."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting

    value = {**summary, "finished_at": datetime.now(timezone.utc).isoformat()}
    async with AsyncSessionLocal() as db:
        stmt = pg_insert(AppSetting).values(key=MARKER_KEY, value=value)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=[AppSetting.key], set_={"value": value}
            )
        )
        await db.commit()
