"""Korpus prawa: zasilenie z wersjami, wyszukiwanie przepisów, zdarzenia zmian.

Kontrakt fundamentu (``docs/asystent-prawny-plan.md``) dla części B–H:

* ``search_provisions(db, query, *, acts=None, on_date=None, limit=8)``,
* ``get_provision(db, act_key, ref, *, on_date=None)``,
* ``SourcePassage`` (z ``citations``) i ``as_passage(hit)``,
* ``verify_text(db, text, passages, *, on_date=None)`` — weryfikator cytatów
  z przepisami dobranymi z korpusu,
* ``changes_since(db, since)`` — nowe wersje tekstu aktów (część H).

Wersja „obowiązuje w dniu D”, gdy ``valid_from <= D`` i (``valid_to`` puste
albo ``>= D``). Bez daty — wersja bieżąca (``valid_to`` puste). Dla dnia
sprzed najstarszej wersji w korpusie ``get_provision`` oddaje najstarszą
z ``exact_date=False`` (ekran mówi wtedy, z którego dnia jest tekst).

Sieć nigdy nie biegnie w otwartej transakcji: ``refresh_act`` czyta stan,
zamyka sesję, pobiera tekst i dopiero wtedy zapisuje wersję w nowej sesji.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Sequence

import httpx
from sqlalchemy import and_, case, delete, desc, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.legal_corpus import LegalAct, LegalActVersion, LegalProvision
from app.services.framework_contract_text import query_stems
from app.services.hybrid_search import reciprocal_rank_fusion
from app.services.legal import citations, fetch, index
from app.services.legal.acts import ACTS, ActSpec, spec_for
from app.services.legal.citations import CitationCheck, SourcePassage

logger = logging.getLogger(__name__)

__all__ = [
    "ProvisionHit",
    "SourcePassage",
    "as_passage",
    "changes_since",
    "get_provision",
    "law_passages",
    "refresh_act",
    "refresh_all",
    "search_provisions",
    "sources_status",
    "verify_text",
]

KEYWORD_HITS = 60
#: Jednostka dłuższa niż tyle znaków (art. 21 ustawy o PIT: 120 tys.) pasuje do
#: każdego pytania po słowach i wypycha trafne przepisy; jej ustępy i punkty są
#: w korpusie osobno, więc ranking po słowach ją pomija (pomiar 25.11.2026: 14
#: z 27 191 jednostek).
KEYWORD_MAX_CHARS = 20_000
INSERT_BATCH = 500
CHANGES_LIST_MAX = 300
RETRIEVAL_HYBRID = "hybrid"
RETRIEVAL_KEYWORDS = "keywords"
RETRIEVAL_NONE = "none"


@dataclass(frozen=True)
class ProvisionHit:
    id: int
    act_key: str
    act_short_name: str
    ref: str
    ref_key: str
    kind: str
    heading: Optional[str]
    text: str
    repealed: bool
    version_id: int
    version_ident: str
    valid_from: date
    valid_to: Optional[date]
    url: str
    exact_date: bool = True


@dataclass(frozen=True)
class SearchResult:
    hits: list[ProvisionHit]
    retrieval: str


def as_passage(hit: ProvisionHit) -> SourcePassage:
    return SourcePassage(
        kind=citations.KIND_LAW,
        ref=hit.ref,
        text=hit.text,
        url=hit.url,
        label=f"{hit.act_short_name}, tekst od {hit.valid_from.isoformat()}",
        act_key=hit.act_key,
    )


# ── odczyt ──────────────────────────────────────────────────────────────────


def _version_clause(on_date: Optional[date]) -> Any:
    if on_date is None:
        return LegalActVersion.valid_to.is_(None)
    return and_(
        LegalActVersion.valid_from <= on_date,
        or_(LegalActVersion.valid_to.is_(None), LegalActVersion.valid_to >= on_date),
    )


def _hit_columns() -> tuple[Any, ...]:
    return (
        LegalProvision.id,
        LegalAct.key,
        LegalAct.short_name,
        LegalProvision.ref,
        LegalProvision.ref_key,
        LegalProvision.kind,
        LegalProvision.heading,
        LegalProvision.text,
        LegalProvision.repealed,
        LegalActVersion.id,
        LegalActVersion.version_ident,
        LegalActVersion.valid_from,
        LegalActVersion.valid_to,
        LegalActVersion.url,
    )


def _hit(row: Any, *, exact_date: bool = True) -> ProvisionHit:
    return ProvisionHit(*row, exact_date=exact_date)


def _joined(stmt: Any) -> Any:
    return stmt.join(
        LegalActVersion, LegalActVersion.id == LegalProvision.version_id
    ).join(LegalAct, LegalAct.id == LegalProvision.act_id)


def _key_variants(key: str) -> list[str]:
    """Klucz i jego warianty: „ust.” ↔ „§” (KC ma paragrafy, ustawy ustępy)."""
    variants = [key]
    if " ust." in key:
        variants.append(key.replace(" ust.", " §", 1))
    elif " §" in key:
        variants.append(key.replace(" §", " ust.", 1))
    return variants


def _ancestors(key: str) -> list[str]:
    parts = key.split(" ")
    return [" ".join(parts[:n]) for n in range(len(parts) - 1, 0, -1)]


async def _by_keys(
    db: AsyncSession, act_key: str, keys: Sequence[str], on_date: Optional[date]
) -> tuple[Optional[ProvisionHit], bool]:
    rows = (
        await db.execute(
            _joined(select(*_hit_columns())).where(
                LegalAct.key == act_key,
                LegalProvision.ref_key.in_(list(keys)),
                _version_clause(on_date),
            )
        )
    ).all()
    if rows:
        by_key = {row[4]: row for row in rows}
        for key in keys:
            if key in by_key:
                return _hit(by_key[key]), True
    if on_date is None:
        return None, True
    # Dzień sprzed najstarszej wersji w korpusie: najstarsza wersja z flagą.
    earliest = await db.scalar(
        select(func.min(LegalActVersion.valid_from))
        .join(LegalAct, LegalAct.id == LegalActVersion.act_id)
        .where(LegalAct.key == act_key)
    )
    if earliest is None or earliest <= on_date:
        return None, True
    rows = (
        await db.execute(
            _joined(select(*_hit_columns())).where(
                LegalAct.key == act_key,
                LegalProvision.ref_key.in_(list(keys)),
                LegalActVersion.valid_from == earliest,
            )
        )
    ).all()
    by_key = {row[4]: row for row in rows}
    for key in keys:
        if key in by_key:
            return _hit(by_key[key], exact_date=False), False
    return None, False


def ref_to_key(ref: str) -> Optional[str]:
    """„art. 61 § 1” / „art. 6 ust. 1 lit. b” → klucz jednostki."""
    found = citations.extract(
        ref if ref.strip().lower().startswith("art") else f"art. {ref}"
    )
    law = next((c for c in found if c.kind == citations.KIND_LAW), None)
    return law.key if law else None


async def get_provision(
    db: AsyncSession,
    act_key: str,
    ref: str,
    *,
    on_date: Optional[date] = None,
    nearest_parent: bool = False,
) -> Optional[ProvisionHit]:
    """Jednostka ``ref`` aktu ``act_key`` (wersja z ``on_date`` albo bieżąca).

    ``nearest_parent=True``: gdy jednostki nie ma (np. „pkt 3” w artykule,
    który ma tylko tekst), oddaje najbliższą nadrzędną — weryfikator cytatów
    porównuje wtedy cytat z jej tekstem.
    """
    key = ref_to_key(ref)
    if key is None:
        return None
    hit, _exact = await _by_keys(db, act_key, _key_variants(key), on_date)
    if hit is not None or not nearest_parent:
        return hit
    for parent in _ancestors(key):
        hit, _exact = await _by_keys(db, act_key, _key_variants(parent), on_date)
        if hit is not None:
            return hit
    return None


async def law_passages(
    db: AsyncSession,
    found: Sequence[citations.Citation],
    *,
    on_date: Optional[date] = None,
) -> list[SourcePassage]:
    """Fragmenty przepisów dla odwołań z tekstu (także koniec zakresu „art. 111–116”)."""
    passages: list[SourcePassage] = []
    seen: set[tuple[str, str]] = set()
    for citation in found:
        if citation.kind != citations.KIND_LAW or citation.act_key is None:
            continue
        refs = [citation.ref]
        if citation.range_to:
            refs.append(f"art. {citation.range_to}")
        for ref in refs:
            hit = await get_provision(
                db, citation.act_key, ref, on_date=on_date, nearest_parent=True
            )
            if hit is None or (hit.act_key, hit.ref_key) in seen:
                continue
            seen.add((hit.act_key, hit.ref_key))
            passages.append(as_passage(hit))
    return passages


async def verify_text(
    db: AsyncSession,
    text: str,
    passages: Sequence[SourcePassage] = (),
    *,
    on_date: Optional[date] = None,
) -> list[CitationCheck]:
    """Weryfikator cytatów: przepisy z korpusu + podane fragmenty umów i wzorów."""
    found = citations.extract(text)
    law = await law_passages(db, found, on_date=on_date)
    return citations.verify(text, [*passages, *law])


def _tsquery(stems: Sequence[str], joiner: str) -> str:
    return f" {joiner} ".join(f"{stem}:*" for stem in stems)


async def _current_version_ids(
    db: AsyncSession, acts: Optional[Sequence[str]], on_date: Optional[date]
) -> list[int]:
    stmt = (
        select(LegalActVersion.id)
        .join(LegalAct, LegalAct.id == LegalActVersion.act_id)
        .where(_version_clause(on_date))
    )
    if acts:
        stmt = stmt.where(LegalAct.key.in_(list(acts)))
    return [int(v) for v in (await db.scalars(stmt)).all()]


async def search(
    db: AsyncSession,
    query: str,
    *,
    acts: Optional[Sequence[str]] = None,
    on_date: Optional[date] = None,
    limit: int = 8,
) -> SearchResult:
    """Przepisy pasujące do pytania: po słowach (FTS) i po znaczeniu (RRF)."""
    query = (query or "").strip()
    if not query:
        return SearchResult([], RETRIEVAL_NONE)
    limit = max(1, min(int(limit), 50))
    pinned: list[ProvisionHit] = []
    for citation in citations.extract(query):
        if (
            citation.kind == citations.KIND_LAW
            and citation.act_key
            and (not acts or citation.act_key in acts)
        ):
            hit = await get_provision(
                db, citation.act_key, citation.ref, on_date=on_date
            )
            if hit is not None:
                pinned.append(hit)
    version_ids = await _current_version_ids(db, acts, on_date)
    if not version_ids:
        return SearchResult(
            pinned[:limit], RETRIEVAL_NONE if not pinned else RETRIEVAL_KEYWORDS
        )
    stems = query_stems(query)
    keyword_ids: list[int] = []
    if stems:
        tsq_any = func.to_tsquery("simple", _tsquery(stems, "|"))
        tsq_all = func.to_tsquery("simple", _tsquery(stems, "&"))
        rank = func.ts_rank_cd(LegalProvision.search_vector, tsq_any, 1) + case(
            (LegalProvision.search_vector.op("@@")(tsq_all), 1.0), else_=0.0
        )
        stmt = (
            select(LegalProvision.id)
            .where(
                LegalProvision.version_id.in_(version_ids),
                LegalProvision.search_vector.op("@@")(tsq_any),
                LegalProvision.repealed.is_(False),
                func.length(LegalProvision.text) <= KEYWORD_MAX_CHARS,
            )
            .order_by(desc(rank), LegalProvision.id)
            .limit(KEYWORD_HITS)
        )
        keyword_ids = [int(i) for i in (await db.scalars(stmt)).all()]
    vector_ids = await index.vector_ranking(query, version_ids)
    if vector_ids is None:
        ranked = keyword_ids
        retrieval = RETRIEVAL_KEYWORDS
    else:
        ranked = [
            pid
            for pid, _score in reciprocal_rank_fusion(
                [vector_ids, keyword_ids[: index.VECTOR_HITS]]
            )
        ]
        retrieval = RETRIEVAL_HYBRID
    pinned_ids = {hit.id for hit in pinned}
    wanted = [pid for pid in ranked if pid not in pinned_ids][
        : max(0, limit - len(pinned))
    ]
    hits: list[ProvisionHit] = list(pinned)
    if wanted:
        rows = (
            await db.execute(
                _joined(select(*_hit_columns())).where(
                    LegalProvision.id.in_(wanted), LegalProvision.repealed.is_(False)
                )
            )
        ).all()
        by_id = {row[0]: _hit(row) for row in rows}
        hits.extend(by_id[pid] for pid in wanted if pid in by_id)
    if not hits:
        return SearchResult([], RETRIEVAL_NONE)
    return SearchResult(hits[:limit], retrieval)


async def search_provisions(
    db: AsyncSession,
    query: str,
    *,
    acts: Optional[Sequence[str]] = None,
    on_date: Optional[date] = None,
    limit: int = 8,
) -> list[ProvisionHit]:
    """Kontrakt fundamentu: same trafienia (``search`` niesie też sposób rankingu)."""
    return (await search(db, query, acts=acts, on_date=on_date, limit=limit)).hits


# ── stan korpusu i zdarzenia ────────────────────────────────────────────────


async def sources_status(db: AsyncSession) -> dict[str, Any]:
    acts = (await db.scalars(select(LegalAct).order_by(LegalAct.id))).all()
    versions = (
        await db.scalars(
            select(LegalActVersion).where(LegalActVersion.valid_to.is_(None))
        )
    ).all()
    current = {v.act_id: v for v in versions}
    counts = dict(
        (
            await db.execute(
                select(LegalActVersion.act_id, func.count()).group_by(
                    LegalActVersion.act_id
                )
            )
        ).all()
    )
    registry = {spec.key for spec in ACTS}
    items = []
    for act in acts:
        version = current.get(act.id)
        items.append(
            {
                "key": act.key,
                "short_name": act.short_name,
                "title": act.title,
                "source": act.source,
                "ident": act.ident,
                "in_registry": act.key in registry,
                "fetch_status": act.fetch_status,
                "fetch_error": act.fetch_error,
                "checked_at": act.checked_at.isoformat() if act.checked_at else None,
                "versions": int(counts.get(act.id, 0)),
                "current": (
                    {
                        "ident": version.version_ident,
                        "valid_from": version.valid_from.isoformat(),
                        "published_on": version.published_on.isoformat()
                        if version.published_on
                        else None,
                        "url": version.url,
                        "format": version.format,
                        "provisions": version.provisions_count,
                        "vectors": int((version.meta or {}).get("vectors") or 0),
                        "amendments_after": list(
                            (version.meta or {}).get("amendments_after") or []
                        )[:20],
                    }
                    if version
                    else None
                ),
            }
        )
    return {
        "acts": items,
        "acts_total": len(items),
        "acts_ready": sum(1 for item in items if item["current"]),
        "provisions_total": sum(
            (item["current"] or {}).get("provisions", 0) for item in items
        ),
        "embeddings_enabled": index.embeddings_enabled(),
    }


@dataclass(frozen=True)
class VersionChange:
    act_key: str
    version_id: int
    version_ident: str
    previous_ident: Optional[str]
    valid_from: date
    created_at: datetime
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)


async def changes_since(db: AsyncSession, since: datetime) -> list[VersionChange]:
    """Nowe wersje tekstu (z poprzednią w korpusie) zapisane po ``since``."""
    previous = LegalActVersion.__table__.alias("previous_version")
    rows = (
        await db.execute(
            select(LegalActVersion, LegalAct.key, previous.c.version_ident)
            .join(LegalAct, LegalAct.id == LegalActVersion.act_id)
            .join(previous, previous.c.id == LegalActVersion.previous_version_id)
            .where(LegalActVersion.created_at > since)
            .order_by(LegalActVersion.created_at)
        )
    ).all()
    out = []
    for version, act_key, previous_ident in rows:
        changes = version.changes or {}
        out.append(
            VersionChange(
                act_key=act_key,
                version_id=version.id,
                version_ident=version.version_ident,
                previous_ident=previous_ident,
                valid_from=version.valid_from,
                created_at=version.created_at,
                added=list(changes.get("added") or []),
                removed=list(changes.get("removed") or []),
                changed=list(changes.get("changed") or []),
            )
        )
    return out


# ── zasilenie ───────────────────────────────────────────────────────────────


async def ensure_acts(db: AsyncSession) -> None:
    """Wiersze aktów z rejestru (bez kasowania aktów spoza rejestru)."""
    for spec in ACTS:
        stmt = pg_insert(LegalAct).values(
            key=spec.key,
            source=spec.source,
            ident=spec.ident,
            short_name=spec.short_name,
            title=spec.title,
        )
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=[LegalAct.key],
                set_={
                    "source": stmt.excluded.source,
                    "ident": stmt.excluded.ident,
                    "short_name": stmt.excluded.short_name,
                },
            )
        )


def diff_versions(before: dict[str, str], after: dict[str, str]) -> dict[str, Any]:
    """Zmiany wobec poprzedniej wersji: oznaczenia dodane, usunięte, zmienione."""
    added = [key for key in after if key not in before]
    removed = [key for key in before if key not in after]
    changed = [key for key in after if key in before and before[key] != after[key]]
    return {
        "added": added[:CHANGES_LIST_MAX],
        "removed": removed[:CHANGES_LIST_MAX],
        "changed": changed[:CHANGES_LIST_MAX],
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
        },
    }


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()


@dataclass(frozen=True)
class RefreshResult:
    act_key: str
    status: str  # unchanged | new_version | failed
    version_ident: Optional[str] = None
    provisions: int = 0
    vectors: int = 0
    error: Optional[str] = None


async def _mark(
    act_id: int, *, status: str, error: Optional[str] = None, **values: Any
) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(LegalAct)
            .where(LegalAct.id == act_id)
            .values(
                fetch_status=status,
                fetch_error=(error or None) and error[:255],
                checked_at=datetime.now(timezone.utc),
                updated_at=func.now(),
                **values,
            )
        )
        await db.commit()


async def refresh_act(
    spec: ActSpec, *, http: httpx.AsyncClient, force: bool = False
) -> RefreshResult:
    """Sprawdza źródło aktu i zapisuje nową wersję, gdy się pojawiła."""
    async with AsyncSessionLocal() as db:
        await ensure_acts(db)
        await db.commit()
        act = await db.scalar(select(LegalAct).where(LegalAct.key == spec.key))
        assert act is not None
        act_id = act.id
        current = await db.scalar(
            select(LegalActVersion)
            .where(LegalActVersion.act_id == act_id, LegalActVersion.valid_to.is_(None))
            .order_by(desc(LegalActVersion.valid_from))
            .limit(1)
        )
        current_ident = current.version_ident if current else None
        current_id = current.id if current else None
        await db.commit()
    try:
        plan = await fetch.plan_for(http, spec)
        if current_ident == plan.ident and not force:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(LegalActVersion)
                    .where(LegalActVersion.id == current_id)
                    .values(meta=_merge_meta_expr(plan.meta))
                )
                await db.commit()
            await _mark(act_id, status="ok")
            return RefreshResult(spec.key, "unchanged", plan.ident)
        fetched = await fetch.fetch_text(http, plan)
    except fetch.FetchError as exc:
        logger.warning("[legal] akt %s: %s", spec.key, exc)
        await _mark(act_id, status="failed", error=str(exc))
        return RefreshResult(spec.key, "failed", error=str(exc))
    except httpx.HTTPError as exc:
        logger.warning("[legal] akt %s: %s", spec.key, type(exc).__name__)
        await _mark(act_id, status="failed", error=type(exc).__name__)
        return RefreshResult(spec.key, "failed", error=type(exc).__name__)
    version_id, previous_id, rows = await _store_version(act_id, spec, fetched)
    vectors = await index.index_version(act_id, version_id, rows, previous_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(LegalActVersion)
            .where(LegalActVersion.id == version_id)
            .values(meta=_merge_meta_expr({"vectors": vectors}))
        )
        await db.commit()
    await _mark(
        act_id, status="ok", url=fetched.plan.url, **_title_update(fetched.plan)
    )
    logger.info(
        "[legal] akt %s: wersja %s, %s jednostek, %s wektorów",
        spec.key,
        fetched.plan.ident,
        len(fetched.units),
        vectors,
    )
    return RefreshResult(
        spec.key, "new_version", fetched.plan.ident, len(fetched.units), vectors
    )


def _title_update(plan: fetch.VersionPlan) -> dict[str, Any]:
    if plan.title:
        return {"title": re.sub(r"\s+", " ", plan.title).strip()[:400]}
    return {}


def _merge_meta_expr(values: dict[str, Any]) -> Any:
    from sqlalchemy import literal
    from sqlalchemy.dialects.postgresql import JSONB

    return LegalActVersion.meta.op("||")(literal(values, JSONB))


async def _store_version(
    act_id: int, spec: ActSpec, fetched: fetch.FetchedText
) -> tuple[int, Optional[int], list[tuple[int, str]]]:
    plan = fetched.plan
    async with AsyncSessionLocal() as db:
        same = await db.scalar(
            select(LegalActVersion).where(
                LegalActVersion.act_id == act_id,
                LegalActVersion.version_ident == plan.ident,
            )
        )
        previous_link: Optional[int] = None
        if same is not None:
            # Ponowne zasilenie tej samej wersji (``force``): stara znika razem
            # z przepisami, łańcuch wersji zostaje.
            previous_link = same.previous_version_id
            await db.execute(
                delete(LegalActVersion).where(LegalActVersion.id == same.id)
            )
            await db.flush()
        previous = await db.scalar(
            select(LegalActVersion)
            .where(LegalActVersion.act_id == act_id, LegalActVersion.valid_to.is_(None))
            .order_by(desc(LegalActVersion.valid_from))
            .limit(1)
        )
        if previous is None and previous_link is not None:
            previous = await db.get(LegalActVersion, previous_link)
        before: dict[str, str] = {}
        if previous is not None:
            before = dict(
                (
                    await db.execute(
                        select(
                            LegalProvision.ref_key, func.md5(LegalProvision.text)
                        ).where(LegalProvision.version_id == previous.id)
                    )
                ).all()
            )
            close_on = max(previous.valid_from, plan.valid_from - timedelta(days=1))
            await db.execute(
                update(LegalActVersion)
                .where(LegalActVersion.id == previous.id)
                .values(valid_to=close_on)
            )
        after = {unit.key: _md5(unit.text) for unit in fetched.units}
        version_id = await db.scalar(
            insert(LegalActVersion)
            .values(
                act_id=act_id,
                version_ident=plan.ident,
                valid_from=plan.valid_from,
                published_on=plan.published_on,
                url=plan.url[:500],
                format=plan.format,
                content_hash=fetched.content_hash,
                provisions_count=len(fetched.units),
                previous_version_id=previous.id if previous is not None else None,
                changes=diff_versions(before, after) if previous is not None else {},
                meta=plan.meta,
            )
            .returning(LegalActVersion.id)
        )
        assert version_id is not None
        ids_by_key: dict[str, int] = {}
        units = fetched.units
        for start in range(0, len(units), INSERT_BATCH):
            batch = units[start : start + INSERT_BATCH]
            result = await db.execute(
                insert(LegalProvision).returning(
                    LegalProvision.id, LegalProvision.ref_key
                ),
                [
                    {
                        "version_id": version_id,
                        "act_id": act_id,
                        "ref": unit.ref[:120],
                        "ref_key": unit.key[:120],
                        "article": unit.article[:24],
                        "kind": unit.kind,
                        "depth": unit.depth,
                        "parent_key": unit.parent_key[:120]
                        if unit.parent_key
                        else None,
                        "position": unit.position,
                        "heading": unit.heading[:300] if unit.heading else None,
                        "text": unit.text,
                        "repealed": unit.repealed,
                    }
                    for unit in batch
                ],
            )
            ids_by_key.update({key: int(pid) for pid, key in result.all()})
        await db.commit()
    rows = [
        (
            ids_by_key[unit.key],
            index.embed_text(spec.short_name, unit.ref, unit.heading, unit.text),
        )
        for unit in units
        if unit.key in ids_by_key
        and index.should_embed(unit.depth, unit.text, unit.repealed)
    ]
    return int(version_id), (previous.id if previous is not None else None), rows


async def refresh_all(
    *, keys: Optional[Sequence[str]] = None, force: bool = False
) -> list[RefreshResult]:
    """Wszystkie akty z rejestru (albo ``keys``), po kolei, jeden klient HTTP."""
    specs = [spec for spec in ACTS if not keys or spec.key in keys]
    unknown = [key for key in keys or () if spec_for(key) is None]
    if unknown:
        raise ValueError(f"Nieznane akty: {', '.join(unknown)}")
    results = []
    async with fetch.client() as http:
        for spec in specs:
            results.append(await refresh_act(spec, http=http, force=force))
    return results


def act_keys() -> tuple[str, ...]:
    return tuple(spec.key for spec in ACTS)


def ensure_known_acts(keys: Sequence[str]) -> list[str]:
    known = set(act_keys())
    return [key for key in keys if key not in known]
