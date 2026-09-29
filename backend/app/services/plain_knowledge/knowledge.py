"""Zapis i odczyt wspólnej bazy wiedzy: terminy, role, opis klienta.

Zajęcie wiersza zamiast blokady: ``claim_*`` wstawia wiersz ze
``status='researching'`` (albo przejmuje wiersz, którego research padł dawno
albo utknął), a research robi tylko ten, kto go zajął. Dwie rekrutacje z tym
samym nowym terminem nie płacą dwa razy, a połączenie z bazą nie wisi na
czas wyszukiwania w internecie.

Wiersz poprawiony przez człowieka (``origin='manual'``) nigdy nie jest
nadpisywany przez research.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_playbook import ClientPlaybook
from app.models.client_playbook_event import ClientPlaybookEvent
from app.models.plain_knowledge import PlainTerm, RoleProfile

logger = logging.getLogger(__name__)

STALE_CLAIM_MINUTES = 5
FAILED_RETRY_HOURS = 24
MAX_TERM_CHARS = 60
MAX_TERM_WORDS = 4

_inflight_clients: set[int] = set()


def term_key_for(name: str) -> str:
    """Klucz terminu = nazwa kanoniczna ze słownika (małe litery), inaczej sama nazwa."""
    from app.services.skill_normalize import canonical_of

    return canonical_of(re.sub(r"\s+", " ", name or "").strip())[:200]


def researchable_term(name: str) -> bool:
    """Czy nazwa nadaje się na hasło słowniczka (a nie zdanie z wymaganiem)."""
    from app.services.skill_normalize import is_taxonomy_technology

    clean = re.sub(r"\s+", " ", name or "").strip()
    if not clean:
        return False
    if is_taxonomy_technology(clean):
        return True
    return (
        len(clean) <= MAX_TERM_CHARS
        and len(clean.split(" ")) <= MAX_TERM_WORDS
        and not re.search(r"\d+\s*\+?\s*(lat|lata|years?)", clean, re.IGNORECASE)
    )


def needs_research(row: Any) -> bool:
    """Czy hasło trzeba (ponownie) zbadać: brak wiersza, research padł albo utknął.

    Zajęcie porzucone przez proces (deploy w trakcie researchu, błąd bazy przy
    zapisie wyniku) zostaje w ``researching`` — bez tej gałęzi hasło wisiałoby
    tak na zawsze. Czy research naprawdę ruszy, rozstrzyga ``claim_term``
    (ponowienie ``failed`` dopiero po ``FAILED_RETRY_HOURS``).
    """
    if row is None:
        return True
    if row.status == "failed":
        return True
    if row.status == "researching":
        claimed = row.claimed_at
        if claimed is None:
            return True
        if claimed.tzinfo is None:
            claimed = claimed.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - claimed > timedelta(
            minutes=STALE_CLAIM_MINUTES
        )
    return False


def slugify(name: str) -> str:
    norm = unicodedata.normalize(
        "NFKD", (name or "").replace("ł", "l").replace("Ł", "L")
    )
    ascii_ = norm.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_).strip("-")[:120] or "rola"


async def terms_by_key(db: AsyncSession, keys: Iterable[str]) -> dict[str, PlainTerm]:
    wanted = sorted({k for k in keys if k})
    if not wanted:
        return {}
    rows = (
        await db.execute(select(PlainTerm).where(PlainTerm.term_key.in_(wanted)))
    ).scalars()
    return {row.term_key: row for row in rows}


_CLAIM_TERM_SQL = text(
    f"""
    INSERT INTO plain_terms (term_key, display_name, origin, status, claimed_at)
    VALUES (:key, :display, 'ai', 'researching', now())
    ON CONFLICT (term_key) DO UPDATE
       SET status = 'researching', claimed_at = now()
     WHERE plain_terms.origin <> 'manual'
       AND (
            (plain_terms.status = 'failed'
             AND plain_terms.updated_at < now() - interval '{FAILED_RETRY_HOURS} hours')
         OR (plain_terms.status = 'researching'
             AND (plain_terms.claimed_at IS NULL
                  OR plain_terms.claimed_at < now() - interval '{STALE_CLAIM_MINUTES} minutes'))
       )
    RETURNING id
    """
)


async def claim_term(db: AsyncSession, key: str, display: str) -> bool:
    got = (
        await db.execute(_CLAIM_TERM_SQL, {"key": key, "display": display[:200]})
    ).first()
    await db.commit()
    return got is not None


async def finish_term(
    db: AsyncSession, key: str, result: Optional[dict[str, Any]]
) -> None:
    row = (
        await db.execute(
            select(PlainTerm).where(PlainTerm.term_key == key).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.origin == "manual" or row.status != "researching":
        await db.commit()
        return
    if not result or not result.get("summary"):
        row.status = "failed"
        row.claimed_at = None
    else:
        row.display_name = result.get("display_name") or row.display_name
        row.summary = result.get("summary")
        row.does = result.get("does")
        row.cv_hints = result.get("cv_hints") or []
        row.confused_with = result.get("confused_with")
        row.sources = result.get("sources") or []
        row.origin = "ai"
        row.status = "ready"
        row.claimed_at = None
    await db.commit()


_CLAIM_ROLE_SQL = text(
    f"""
    INSERT INTO role_profiles (slug, name, match_rules, typical_skills, origin, status, claimed_at)
    VALUES (:slug, :name, CAST(:rules AS jsonb), CAST(:skills AS jsonb), 'ai', 'researching', now())
    ON CONFLICT (slug) DO UPDATE
       SET status = 'researching', claimed_at = now()
     WHERE role_profiles.origin <> 'manual'
       AND (
            (role_profiles.status = 'failed'
             AND role_profiles.updated_at < now() - interval '{FAILED_RETRY_HOURS} hours')
         OR (role_profiles.status = 'researching'
             AND (role_profiles.claimed_at IS NULL
                  OR role_profiles.claimed_at < now() - interval '{STALE_CLAIM_MINUTES} minutes'))
       )
    RETURNING id
    """
)


async def claim_role(
    db: AsyncSession, slug: str, name: str, rules: dict[str, Any], skills: list[str]
) -> bool:
    import json

    got = (
        await db.execute(
            _CLAIM_ROLE_SQL,
            {
                "slug": slug,
                "name": name[:200],
                "rules": json.dumps(rules, ensure_ascii=False),
                "skills": json.dumps(skills[:12], ensure_ascii=False),
            },
        )
    ).first()
    await db.commit()
    return got is not None


async def finish_role(
    db: AsyncSession, slug: str, result: Optional[dict[str, Any]]
) -> None:
    row = (
        await db.execute(
            select(RoleProfile).where(RoleProfile.slug == slug).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.origin == "manual" or row.status != "researching":
        await db.commit()
        return
    if not result or not result.get("summary"):
        row.status = "failed"
    else:
        row.summary = result.get("summary")
        row.example = result.get("example")
        row.day_to_day = result.get("day_to_day") or []
        row.candidate_questions = result.get("candidate_questions") or []
        row.sources = result.get("sources") or []
        row.origin = "ai"
        row.status = "ready"
    row.claimed_at = None
    await db.commit()


def client_about_missing(playbook: Optional[ClientPlaybook]) -> bool:
    return playbook is None or not (playbook.about_for_candidate or "").strip()


async def fill_client_about(
    db: AsyncSession, client_id: int, client_name: str, *, user_id: Optional[int] = None
) -> bool:
    """Research opisu klienta dla kandydata — tylko gdy karta nie ma opisu.

    Opis wpisany ręcznie wygrywa zawsze (sprawdzane ponownie pod blokadą po
    researchu). Klient bez karty dostaje nową kartę z samym opisem.
    """
    from app.services.plain_knowledge.research import research

    if client_id in _inflight_clients:
        return False
    _inflight_clients.add(client_id)
    try:
        current = await db.scalar(
            select(ClientPlaybook).where(ClientPlaybook.client_id == client_id)
        )
        if not client_about_missing(current):
            return False
        result = await research(db, "client", client_name, user_id=user_id)
        about = (result or {}).get("about")
        if not about:
            return False
        row = (
            await db.execute(
                select(ClientPlaybook)
                .where(ClientPlaybook.client_id == client_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is not None and not client_about_missing(row):
            await db.commit()
            return False
        if row is None:
            from app.api.client_playbooks import _next_version

            version = await _next_version(db, client_id)
            row = ClientPlaybook(client_id=client_id, version=version)
            db.add(row)
        else:
            row.version = int(row.version or 1) + 1
            version = row.version
        row.about_for_candidate = about
        row.about_for_candidate_origin = "web"
        row.about_for_candidate_sources = result.get("sources") or []
        db.add(
            ClientPlaybookEvent(
                client_id=client_id,
                playbook_version=version,
                action="web_research",
                changes={"about_for_candidate": {"from": None, "to": about}},
                actor_user_id=None,
                actor_name="Research AI",
            )
        )
        await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — AI to dodatek
        await db.rollback()
        logger.warning("plain_knowledge client about failed: %s", type(exc).__name__)
        return False
    finally:
        _inflight_clients.discard(client_id)
