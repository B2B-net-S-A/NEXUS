"""Mapa wiedzy IT: powiązania haseł słownika (0660, decyzja Artura z 07.11.2026).

Słownik znał nazwy, ale nie związki między nimi: „Java” u osoby z samym
Spring Boot była brakiem, a QC blokowało CV z GitHubem przy wymaganiu „Git”.
Cztery rodzaje powiązań:

* ``implies`` „wynika z” (Spring Boot ⇒ Java) i ``part_of`` „część”
  (GitHub ⇒ Git) — spełniają wymaganie wszędzie: wyszukiwanie, bramka
  krytycznych, QC, przegląd DL, strażnik generatora (``skill_normalize.implied_forms``);
* ``alternative`` „zamiennik” (Flask ~ FastAPI) — nie spełnia, osoba zostaje
  widoczna z pytaniem do rozmowy;
* ``typical`` „typowe” (Java ⇒ Maven) — nie spełnia, daje pytanie do rozmowy.

Co noc: pary z umiejętności profili (kto ma A, ile procent wpisuje B),
podpowiedzi słowniczka „po ludzku” (``cv_hints``) i zamienniki w kategoriach;
rodzaj związku ocenia model, bezpieczniki w kodzie (``apply_guards``) i od
razu zatwierdza nocny bieg — decyzja Artura z 07.11.2026 „wszystko zatwierdź
sam”. HoR+ może powiązanie wycofać w zakładce „Powiązania”.
Reguła: ``docs/claude/kandydaci-wyszukiwanie/mapa-wiedzy-it-powiazania.md``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feature import AIFeatureKey
from app.models.skill import Skill
from app.models.skill_relation import SkillRelation
from app.services import skill_curation
from app.services.ai_models import fallbacks_for, model_for
from app.services.care.skills import SkillDictionary, load_dictionary

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.skill_dictionary_proposals
KINDS = ("implies", "part_of", "alternative", "typical")
HARD_KINDS = ("implies", "part_of")
MIN_PROFILES = 300
MIN_SHARE = 0.5
SURE_SHARE = 0.9
# Decyzja Artura z 07.11.2026: „wszystko zatwierdź sam, nie pytaj” — powiązanie,
# które przejdzie bezpieczniki, zatwierdza nocny bieg; HoR+ może je wycofać.
AUTO_CURATOR = "auto: model + dane"
# 600 ucinało słabsze, ale ważne pary (Java → Git 54,6%, pomiar 07.11.2026).
PAIRS_MAX = 1500
BATCH_SIZE = 60
BATCH_CONCURRENCY = 3
CATEGORY_MIN_SKILLS = 4
REASON_MAX = 200
# Ostrzeżenie „często nie stoi w CV” tylko przy narzędziach i praktykach (Git,
# Jira, Maven) — przy React czy Javie odciągałoby od słusznie krytycznego wiersza.
TYPICAL_WARNING_CATEGORIES = frozenset(
    {"tools", "practice", "methodology", "standards"}
)

_GLOSSARY = (
    Path(__file__).resolve().parent.parent / "data" / "plain_knowledge" / "terms.json"
)
_HINT_SPLIT = re.compile(r"\s*/\s*|\s+(?:lub|or|albo)\s+|\s*,\s*", re.IGNORECASE)
_VERSION_TAIL = re.compile(r"\s+\d[\d./x+]*$")


@dataclass(frozen=True)
class Pair:
    from_id: int
    to_id: int
    support: int = 0
    share: Optional[float] = None
    source: str = "data"


def is_role(category: Optional[str]) -> bool:
    return skill_curation.is_role(category)


# ── Źródła propozycji ───────────────────────────────────────────────────────

_PAIRS_SQL = text(
    """
    WITH named AS (
        SELECT c.id AS cid, lower(trim(e->>'name')) AS name
        FROM candidates c,
             jsonb_array_elements(
                 CASE WHEN jsonb_typeof(c.skills) = 'array' THEN c.skills
                      ELSE '[]'::jsonb END
             ) e
        WHERE e->>'name' IS NOT NULL
    ),
    keys AS (
        SELECT lower(canonical_name) AS name, id FROM skills
        UNION ALL
        SELECT lower(alias), skill_id FROM skill_aliases
    ),
    resolved AS (
        SELECT DISTINCT n.cid, k.id AS sid
        FROM named n JOIN keys k ON k.name = n.name
    ),
    counts AS (
        SELECT sid, count(*) AS n FROM resolved GROUP BY sid HAVING count(*) >= :min_n
    ),
    co AS (
        SELECT a.sid AS a, b.sid AS b, count(*) AS ab
        FROM resolved a
        JOIN resolved b ON b.cid = a.cid AND b.sid <> a.sid
        WHERE a.sid IN (SELECT sid FROM counts) AND b.sid IN (SELECT sid FROM counts)
        GROUP BY a.sid, b.sid
    )
    SELECT co.a, co.b, c.n, co.ab
    FROM co JOIN counts c ON c.sid = co.a
    WHERE co.ab::float / c.n >= :min_share
    ORDER BY co.ab::float / c.n DESC, c.n DESC
    LIMIT :limit
    """
)


async def mine_pairs(db: AsyncSession, dictionary: SkillDictionary) -> list[Pair]:
    """Pary „kto ma A, ten w ≥ 50% wpisuje też B” z umiejętności profili."""
    rows = (
        await db.execute(
            _PAIRS_SQL,
            {"min_n": MIN_PROFILES, "min_share": MIN_SHARE, "limit": PAIRS_MAX},
        )
    ).all()
    out: list[Pair] = []
    for a, b, n, ab in rows:
        if is_role(dictionary.categories.get(a)) or is_role(
            dictionary.categories.get(b)
        ):
            continue
        out.append(Pair(from_id=a, to_id=b, support=int(n), share=float(ab) / float(n)))
    return out


def hint_names(hint: str) -> list[str]:
    """„Spring / Spring Boot” → [„Spring”, „Spring Boot”], bez wersji."""
    names = []
    for part in _HINT_SPLIT.split(hint or ""):
        part = _VERSION_TAIL.sub("", part.strip())
        # „Java 8/11/17/21” dzieli się też na same numery wersji — te odpadają.
        if part and not part.replace(".", "").isdigit():
            names.append(part)
    return names


def glossary_pairs(dictionary: SkillDictionary, terms: list[dict]) -> list[Pair]:
    """Podpowiedzi słowniczka „po ludzku”: hasło z ``cv_hints`` ⇒ hasło terminu.
    Słowniczek miesza rodzaje (React ⇒ JavaScript, Maven przy Javie, Kotlin
    przy Javie), więc to tylko kandydaci — rodzaj ocenia model."""
    out: list[Pair] = []
    for term in terms:
        to_id = dictionary.resolve(str(term.get("term_key") or ""))
        if to_id is None or is_role(dictionary.categories.get(to_id)):
            continue
        for hint in term.get("cv_hints") or []:
            for name in hint_names(str(hint)):
                from_id = dictionary.resolve(name)
                if from_id is None or from_id == to_id:
                    continue
                if is_role(dictionary.categories.get(from_id)):
                    continue
                out.append(Pair(from_id=from_id, to_id=to_id, source="glossary"))
    return out


def load_glossary() -> list[dict]:
    try:
        data = json.loads(_GLOSSARY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("skill relations: słowniczek niedostępny")
        return []
    return list(data.get("terms") or []) if isinstance(data, dict) else []


def merge_pairs(*groups: list[Pair]) -> list[Pair]:
    """Jedna para na (od, do): liczby z danych, źródło „słowniczek”, gdy też tam jest."""
    merged: dict[tuple[int, int], Pair] = {}
    for group in groups:
        for pair in group:
            key = (pair.from_id, pair.to_id)
            old = merged.get(key)
            if old is None:
                merged[key] = pair
                continue
            merged[key] = Pair(
                from_id=pair.from_id,
                to_id=pair.to_id,
                support=max(old.support, pair.support),
                share=old.share if old.share is not None else pair.share,
                source="glossary"
                if "glossary" in (old.source, pair.source)
                else old.source,
            )
    return list(merged.values())


# ── Model ───────────────────────────────────────────────────────────────────

SYSTEM = """Jesteś ekspertem IT w agencji rekrutacyjnej. Oceniasz związek między dwiema umiejętnościami ze słownika: OD i DO.
Dla KAŻDEJ pary zwróć obiekt {"id": …, "kind": …, "reason": …}:
- "implies" — kto zna OD, ten na pewno zna DO, bo OD jest zbudowane na DO albo bez DO nie da się w OD pracować (Spring Boot → Java, Next.js → React, React → JavaScript, Django → Python),
- "part_of" — OD jest odmianą, usługą albo platformą DO (GitHub → Git, AWS Lambda → AWS, EKS → Kubernetes),
- "alternative" — OD i DO rozwiązują ten sam problem i jedno może zastąpić drugie w projekcie (Flask ↔ FastAPI, Jenkins ↔ GitLab CI, Kafka ↔ RabbitMQ),
- "typical" — przy OD zwykle używa się DO, ale da się znać OD bez DO (Java → Maven, Java → JUnit, React → Jest),
- "none" — tylko częste współwystępowanie bez związku w wiedzy (Jest → TypeScript, PowerPoint → Excel).
Uwaga:
- narzędzie, którego się UŻYWA, nie daje umiejętności BUDOWANIA: ChatGPT, Claude, GitHub Copilot → LLM / Generative AI to „none”;
- usługa albo produkt z rodziny nie daje całej platformy: Azure DevOps → Azure (chmura) to „none”, Power Query → Power BI to „none” (Power Query jest też w Excelu);
- dwie nazwy tej samej rzeczy (UAT i User Acceptance Testing) to „none” — to sprawa aliasów, nie powiązań;
- dystrybucja albo wersja systemu → system (Ubuntu → Linux) i protokół → format (SOAP → XML) to „typical”: użytkownik Ubuntu nie musi administrować Linuksem, a SOAP nie daje pracy z XML na poziomie, którego chce klient.
„reason”: po polsku, najwyżej 12 słów, dlaczego. Nie zgaduj: przy wątpliwości wybierz słabszy rodzaj („typical” zamiast „implies”) albo „none”.
Zwróć TYLKO JSON {"items": [...]}."""

ALT_SYSTEM = """Jesteś ekspertem IT w agencji rekrutacyjnej. Dostajesz listę umiejętności z jednej kategorii słownika.
Wskaż pary ZAMIENNIKÓW: dwie umiejętności, które rozwiązują ten sam problem, tak że osoba znająca jedną szybko wdroży się w drugą i klient często akceptuje jedną zamiast drugiej (Flask ↔ FastAPI, Jenkins ↔ GitLab CI, Kafka ↔ RabbitMQ, PostgreSQL ↔ MySQL).
Nie łącz rzeczy z różnych warstw (język z frameworkiem), o innym celu (JMeter do testów obciążenia ↔ Postman do API, Windows ↔ Linux) ani dwóch nazw tej samej rzeczy (UAT ↔ User Acceptance Testing). Używaj DOKŁADNIE nazw z listy. Najwyżej 25 par.
Zwróć TYLKO JSON {"items": [{"a": "…", "b": "…", "reason": "po polsku, najwyżej 12 słów"}]}."""


def _call_model(system: str, body: str) -> str:
    from app.services.claude_client import call_claude, text_of

    message = call_claude(
        model=model_for(FEATURE),
        fallback_models=list(fallbacks_for(FEATURE)),
        max_tokens=8000,
        temperature=0,
        timeout=180,
        max_retries=1,
        total_timeout=300,
        system=system,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": body}],
    )
    return text_of(message)


def _json_items(raw: str) -> list[dict]:
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        items = json.loads(raw[start:end]).get("items") or []
    except (ValueError, AttributeError):
        return []
    return [item for item in items if isinstance(item, dict)]


def pair_prompt(batch: list[tuple[int, Pair]], dictionary: SkillDictionary) -> str:
    rows = []
    for index, pair in batch:
        row: dict[str, Any] = {
            "id": index,
            "od": dictionary.names.get(pair.from_id),
            "od_kategoria": dictionary.categories.get(pair.from_id),
            "do": dictionary.names.get(pair.to_id),
            "do_kategoria": dictionary.categories.get(pair.to_id),
        }
        if pair.share is not None:
            row["profile_z_od"] = pair.support
            row["procent_wpisuje_do"] = round(pair.share * 100)
        rows.append(row)
    return json.dumps({"pary": rows}, ensure_ascii=False)


def parse_kinds(raw: str) -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    for item in _json_items(raw):
        try:
            index = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        kind = str(item.get("kind") or "").strip()
        if kind in (*KINDS, "none"):
            out[index] = (kind, str(item.get("reason") or "").strip()[:REASON_MAX])
    return out


def parse_alternatives(raw: str, dictionary: SkillDictionary) -> list[tuple[Pair, str]]:
    out = []
    for item in _json_items(raw):
        a = dictionary.resolve(str(item.get("a") or ""))
        b = dictionary.resolve(str(item.get("b") or ""))
        if a is None or b is None or a == b:
            continue
        low, high = sorted((a, b))
        reason = str(item.get("reason") or "").strip()[:REASON_MAX]
        out.append((Pair(from_id=low, to_id=high, source="model"), reason))
    return out


_PAREN_TAIL = re.compile(r"\s*\([^)]*\)\s*$")


def _same_thing(a: Optional[str], b: Optional[str]) -> bool:
    """„User Acceptance Testing” i „User Acceptance Testing (UAT)” to jedno hasło
    zapisane dwa razy — to sprawa aliasów, nie powiązania."""
    if not a or not b:
        return False
    left = _PAREN_TAIL.sub("", a).strip().casefold()
    right = _PAREN_TAIL.sub("", b).strip().casefold()
    return left == right


def apply_guards(pair: Pair, kind: str, dictionary: SkillDictionary) -> Optional[str]:
    """Rodzaj po bezpiecznikach albo ``None`` (para odpada).

    Role nie mają powiązań. „Wynika z” i „część” z danych wymagają, żeby
    co najmniej połowa profili z OD wpisywała DO — inaczej model mógłby
    ogłosić implikację tam, gdzie ludzie piszą coś innego; słowniczek jest
    wyjątkiem (React ⇒ JavaScript wpisuje tylko 68%, ale to wiedza, nie zwyczaj)."""
    if kind == "none" or kind not in KINDS:
        return None
    if is_role(dictionary.categories.get(pair.from_id)) or is_role(
        dictionary.categories.get(pair.to_id)
    ):
        return None
    if _same_thing(
        dictionary.names.get(pair.from_id), dictionary.names.get(pair.to_id)
    ):
        return None
    if kind in HARD_KINDS and pair.source == "model":
        return "typical"
    # „Typowe” to zwyczaj, nie wiedza: musi go potwierdzić co najmniej połowa
    # profili (słowniczek podaje pary w obie strony, np. „Python > Django”).
    if kind == "typical" and pair.source != "model" and (pair.share or 0) < MIN_SHARE:
        return None
    # Zatwierdzamy bez człowieka (decyzja Artura z 07.11.2026), więc twardy
    # rodzaj wymaga drugiego świadka: ≥ 90% profili albo słowniczka.
    if (
        kind in HARD_KINDS
        and pair.source != "glossary"
        and (pair.share or 0) < SURE_SHARE
    ):
        return "typical"
    return kind


def is_sure(row: SkillRelation) -> bool:
    """„Zatwierdź pewne”: twardy rodzaj, który potwierdzają też dane (≥ 90%)."""
    return bool(
        row.status == "proposed"
        and row.kind in HARD_KINDS
        and row.share is not None
        and float(row.share) >= SURE_SHARE
    )


async def classify_pairs(
    db: AsyncSession, pairs: list[Pair], dictionary: SkillDictionary
) -> dict[int, tuple[str, str]]:
    from app.services.ai_quota import ai_feature

    indexed = list(enumerate(pairs))
    batches = [indexed[i : i + BATCH_SIZE] for i in range(0, len(indexed), BATCH_SIZE)]
    if not batches:
        return {}
    limiter = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def run(batch: list[tuple[int, Pair]]) -> dict[int, tuple[str, str]]:
        async with limiter:
            try:
                raw = await run_in_threadpool(
                    _call_model, SYSTEM, pair_prompt(batch, dictionary)
                )
                return parse_kinds(raw)
            except Exception as exc:  # noqa: BLE001 — wynik modelu to dodatek
                logger.warning(
                    "skill relations: partia nieudana (%s)", type(exc).__name__
                )
                return {}

    async with ai_feature(db, FEATURE, units=len(batches)):
        await db.commit()
        results = await asyncio.gather(*[run(b) for b in batches])
    merged: dict[int, tuple[str, str]] = {}
    for result in results:
        merged.update(result)
    return merged


async def find_alternatives(
    db: AsyncSession, dictionary: SkillDictionary
) -> list[tuple[Pair, str]]:
    from app.services.ai_quota import ai_feature

    by_category: dict[str, list[str]] = {}
    for skill_id, category in dictionary.categories.items():
        if category and not is_role(category):
            by_category.setdefault(category, []).append(dictionary.names[skill_id])
    groups = [
        sorted(names)
        for names in by_category.values()
        if len(names) >= CATEGORY_MIN_SKILLS
    ]
    if not groups:
        return []
    limiter = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def run(names: list[str]) -> list[tuple[Pair, str]]:
        async with limiter:
            try:
                raw = await run_in_threadpool(
                    _call_model,
                    ALT_SYSTEM,
                    json.dumps({"umiejetnosci": names}, ensure_ascii=False),
                )
                return parse_alternatives(raw, dictionary)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "skill relations: zamienniki nieudane (%s)", type(exc).__name__
                )
                return []

    async with ai_feature(db, FEATURE, units=len(groups)):
        await db.commit()
        results = await asyncio.gather(*[run(g) for g in groups])
    return [item for result in results for item in result]


# ── Nocny bieg ──────────────────────────────────────────────────────────────


async def _existing(db: AsyncSession) -> dict[tuple[int, int, str], SkillRelation]:
    rows = (await db.execute(select(SkillRelation))).scalars().all()
    return {(r.from_skill_id, r.to_skill_id, r.kind): r for r in rows}


def _decided_pairs(
    existing: dict[tuple[int, int, str], SkillRelation],
) -> set[tuple[int, int]]:
    """Pary, o których człowiek już zdecydował (w dowolnym rodzaju) — nie wracają."""
    return {
        (r.from_skill_id, r.to_skill_id)
        for r in existing.values()
        if r.status in ("accepted", "rejected")
    }


async def run(db: AsyncSession, *, use_model: bool = True) -> dict:
    """Przelicz propozycje powiązań; ``use_model=False`` = same pary bez rodzaju."""
    dictionary = await load_dictionary(db)
    pairs = merge_pairs(
        await mine_pairs(db, dictionary), glossary_pairs(dictionary, load_glossary())
    )
    existing = await _existing(db)
    decided = _decided_pairs(existing)
    fresh = [p for p in pairs if (p.from_id, p.to_id) not in decided]
    model = model_for(FEATURE) if use_model else None
    kinds = await classify_pairs(db, fresh, dictionary) if use_model else {}
    alternatives = await find_alternatives(db, dictionary) if use_model else []

    proposed = 0
    # Tylko hasła zmienione tej nocy (audyt 2, W4): wszystkie dotąd zatwierdzone
    # powiązania unieważniały co noc ok. 60% zapamiętanych wyników.
    touched: set[int] = set()
    taken = set(decided)
    for index, pair in enumerate(fresh):
        kind, reason = kinds.get(index, (None, ""))
        guarded = apply_guards(pair, kind, dictionary) if kind else None
        if guarded is None:
            continue
        if _upsert(db, existing, pair, guarded, reason, model):
            proposed += 1
            touched.add(pair.to_id)
        taken.add((pair.from_id, pair.to_id))
    for pair, reason in alternatives:
        # Jedna para = jeden rodzaj: zamiennik nie dubluje „typowego” ani „wynika z”.
        if (pair.from_id, pair.to_id) in taken or (pair.to_id, pair.from_id) in taken:
            continue
        taken.add((pair.from_id, pair.to_id))
        if apply_guards(pair, "alternative", dictionary) is None:
            continue
        if _upsert(db, existing, pair, "alternative", reason, model):
            proposed += 1
            touched.add(pair.to_id)
    await db.commit()
    invalidated_jobs = 0
    if touched and model is not None:
        invalidated_jobs = await skill_curation.after_dictionary_change(db, touched)
    summary = {
        "pairs": len(pairs),
        "fresh": len(fresh),
        "accepted": proposed,
        "touched_skills": len(touched) if model is not None else 0,
        "invalidated_jobs": invalidated_jobs,
        "model": model,
    }
    logger.info("skill relations: %s", summary)
    return summary


def _upsert(
    db: AsyncSession,
    existing: dict[tuple[int, int, str], SkillRelation],
    pair: Pair,
    kind: str,
    reason: str,
    model: Optional[str],
) -> int:
    key = (pair.from_id, pair.to_id, kind)
    row = existing.get(key)
    if row is not None and row.status != "proposed":
        return 0
    if row is None:
        row = SkillRelation(
            from_skill_id=pair.from_id, to_skill_id=pair.to_id, kind=kind
        )
        db.add(row)
        existing[key] = row
    row.source = pair.source
    row.support = pair.support
    row.share = Decimal(str(round(pair.share, 4))) if pair.share is not None else None
    row.reason = reason or row.reason
    row.model = model
    if model is not None:
        row.status = "accepted"
        row.curated_by = AUTO_CURATOR
        row.curated_at = func.now()
    return 1


# ── Zakładka „Powiązania” ───────────────────────────────────────────────────


class RelationError(Exception):
    """Błąd domenowy powiązania (4xx w API)."""


async def list_relations(
    db: AsyncSession,
    *,
    status: str = "proposed",
    kind: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    query = select(SkillRelation).where(SkillRelation.status == status)
    if kind:
        query = query.where(SkillRelation.kind == kind)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        (
            await db.execute(
                query.order_by(
                    SkillRelation.share.desc().nulls_last(),
                    SkillRelation.support.desc(),
                    SkillRelation.id,
                )
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    names = await _names(
        db, {r.from_skill_id for r in rows} | {r.to_skill_id for r in rows}
    )
    counts = dict(
        (
            await db.execute(
                select(SkillRelation.status, func.count()).group_by(
                    SkillRelation.status
                )
            )
        ).all()
    )
    sure = await db.scalar(
        select(func.count())
        .select_from(SkillRelation)
        .where(
            SkillRelation.status == "proposed",
            SkillRelation.kind.in_(HARD_KINDS),
            SkillRelation.share >= SURE_SHARE,
        )
    )
    return {
        "items": [relation_payload(r, names) for r in rows],
        "total": int(total),
        "totals": {
            "proposed": int(counts.get("proposed", 0)),
            "accepted": int(counts.get("accepted", 0)),
            "rejected": int(counts.get("rejected", 0)),
            "sure": int(sure or 0),
        },
    }


async def _names(
    db: AsyncSession, ids: set[int]
) -> dict[int, tuple[str, Optional[str]]]:
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Skill.id, Skill.canonical_name, Skill.category).where(
                Skill.id.in_(ids)
            )
        )
    ).all()
    return {sid: (name, category) for sid, name, category in rows}


def relation_payload(
    row: SkillRelation, names: dict[int, tuple[str, Optional[str]]]
) -> dict:
    src = names.get(row.from_skill_id, ("?", None))
    dst = names.get(row.to_skill_id, ("?", None))
    return {
        "id": row.id,
        "from": {"id": row.from_skill_id, "name": src[0], "category": src[1]},
        "to": {"id": row.to_skill_id, "name": dst[0], "category": dst[1]},
        "kind": row.kind,
        "status": row.status,
        "source": row.source,
        "support": row.support,
        "share": float(row.share) if row.share is not None else None,
        "reason": row.reason,
        "sure": is_sure(row),
        "curated_by": row.curated_by,
    }


async def _proposed(db: AsyncSession, relation_id: int) -> SkillRelation:
    row = await db.get(SkillRelation, relation_id, with_for_update=True)
    if row is None:
        raise RelationError("Nie ma takiego powiązania.")
    if row.status != "proposed":
        raise RelationError("O tym powiązaniu już zdecydowano.")
    return row


async def accept(
    db: AsyncSession,
    relation_id: int,
    *,
    kind: Optional[str] = None,
    curated_by: Optional[str],
) -> dict:
    """Zatwierdź (opcjonalnie ze zmienionym rodzajem); działa od razu w całej aplikacji."""
    row = await _proposed(db, relation_id)
    if kind is not None:
        if kind not in KINDS:
            raise RelationError("Nieznany rodzaj powiązania.")
        clash = await db.scalar(
            select(SkillRelation.id).where(
                SkillRelation.from_skill_id == row.from_skill_id,
                SkillRelation.to_skill_id == row.to_skill_id,
                SkillRelation.kind == kind,
                SkillRelation.id != row.id,
            )
        )
        if clash is not None:
            raise RelationError("To powiązanie w tym rodzaju już istnieje.")
        row.kind = kind
    row.status = "accepted"
    row.curated_by = curated_by
    row.curated_at = func.now()
    await db.commit()
    await skill_curation.after_dictionary_change(db, [row.to_skill_id])
    return {"id": row.id, "status": "accepted", "kind": row.kind}


async def reject(
    db: AsyncSession, relation_id: int, *, curated_by: Optional[str]
) -> dict:
    row = await _proposed(db, relation_id)
    row.status = "rejected"
    row.curated_by = curated_by
    row.curated_at = func.now()
    await db.commit()
    return {"id": row.id, "status": "rejected"}


async def accept_sure(db: AsyncSession, *, curated_by: Optional[str]) -> dict:
    """Zatwierdź pewne: twarde powiązania, które potwierdza ≥ 90% profili."""
    rows = (
        (
            await db.execute(
                select(SkillRelation).where(
                    SkillRelation.status == "proposed",
                    SkillRelation.kind.in_(HARD_KINDS),
                    SkillRelation.share >= SURE_SHARE,
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.status = "accepted"
        row.curated_by = curated_by
        row.curated_at = func.now()
    await db.commit()
    if rows:
        await skill_curation.after_dictionary_change(db, {r.to_skill_id for r in rows})
    return {"accepted": len(rows)}


async def create_manual(
    db: AsyncSession,
    *,
    from_skill_id: int,
    to_skill_id: int,
    kind: str,
    curated_by: Optional[str],
) -> dict:
    """Powiązanie dodane ręcznie przez HoR+ — od razu zatwierdzone."""
    if kind not in KINDS:
        raise RelationError("Nieznany rodzaj powiązania.")
    if from_skill_id == to_skill_id:
        raise RelationError("Hasło nie może wynikać samo z siebie.")
    names = await _names(db, {from_skill_id, to_skill_id})
    if len(names) < 2:
        raise RelationError("Nie ma takiego hasła.")
    if any(is_role(category) for _name, category in names.values()):
        raise RelationError("Role nie mają powiązań.")
    row = await db.scalar(
        select(SkillRelation).where(
            SkillRelation.from_skill_id == from_skill_id,
            SkillRelation.to_skill_id == to_skill_id,
            SkillRelation.kind == kind,
        )
    )
    if row is None:
        row = SkillRelation(
            from_skill_id=from_skill_id,
            to_skill_id=to_skill_id,
            kind=kind,
            source="manual",
        )
        db.add(row)
    row.status = "accepted"
    row.curated_by = curated_by
    row.curated_at = func.now()
    await db.commit()
    await skill_curation.after_dictionary_change(db, [to_skill_id])
    return {"id": row.id, "status": "accepted", "kind": kind}


async def withdraw(
    db: AsyncSession, relation_id: int, *, curated_by: Optional[str]
) -> dict:
    """Wycofaj zatwierdzone powiązanie (zostaje jako odrzucone, nie wraca nocą)."""
    row = await db.get(SkillRelation, relation_id, with_for_update=True)
    if row is None:
        raise RelationError("Nie ma takiego powiązania.")
    row.status = "rejected"
    row.curated_by = curated_by
    row.curated_at = func.now()
    await db.commit()
    await skill_curation.after_dictionary_change(db, [row.to_skill_id])
    return {"id": row.id, "status": "rejected"}


# ── Podpowiedzi w edytorze wymagań (etap C, 07.11.2026) ─────────────────────


async def relation_hints(db: AsyncSession, words: list[str]) -> list[dict]:
    """Co mapa wiedzy mówi o słowach wierszy, które słownik ZNA.

    * ``implied`` — słowo wynika z innego słowa tych wymagań (JavaScript przy
      React): osoby z samym React już się liczą;
    * ``typical`` — słowo często nie stoi w CV, bo jest typowe przy innym
      (Git przy Javie) — jako krytyczne ukryje część dobrych osób;
    * ``alternative`` — zamienniki, z którymi osoba nie zniknie z listy.
    Edytor pokazuje dwa ostatnie tylko przy wierszu krytycznym."""
    from app.services.skill_normalize import (
        RELATION_ALTERNATIVES,
        RELATION_IMPLIED_BY,
        RELATION_TYPICAL_BY,
        canonical_of,
    )

    dictionary = await load_dictionary(db)
    canon_words: dict[str, str] = {}
    for raw in words:
        word = (raw or "").strip()
        skill_id = dictionary.resolve(word) if word else None
        if skill_id is not None:
            canon_words.setdefault(canonical_of(dictionary.names[skill_id]), word)
    if not canon_words:
        return []
    by_canon = {name.lower(): name for name in dictionary.names.values()}
    typical_share = await _typical_shares(db, canon_words, dictionary)

    def display(canons) -> list[str]:
        return sorted(by_canon[c] for c in canons if c in by_canon)

    out: list[dict] = []
    for canon, word in canon_words.items():
        sources = RELATION_IMPLIED_BY.get(canon, set()) & set(canon_words)
        if sources:
            out.append(
                {
                    "word": word,
                    "kind": "implied",
                    "names": display(sources),
                    "share": None,
                }
            )
        typical = RELATION_TYPICAL_BY.get(canon)
        skill_id = dictionary.resolve(canon)
        tool_like = (
            dictionary.categories.get(skill_id) or ""
        ) in TYPICAL_WARNING_CATEGORIES
        if typical and tool_like and canon in typical_share:
            source, share = typical_share[canon]
            out.append(
                {"word": word, "kind": "typical", "names": [source], "share": share}
            )
        alternatives = RELATION_ALTERNATIVES.get(canon)
        if alternatives:
            out.append(
                {
                    "word": word,
                    "kind": "alternative",
                    "names": display(alternatives)[:4],
                    "share": None,
                }
            )
    return out


async def _typical_shares(
    db: AsyncSession, canon_words: dict[str, str], dictionary: SkillDictionary
) -> dict[str, tuple[str, float]]:
    """Dla słowa „typowego”: hasło z największą liczbą profili, przy którym je
    wiąże, i odsetek tych, którzy je wpisują (Git przy Javie: 55%)."""
    ids = {
        sid: name.lower()
        for sid, name in dictionary.names.items()
        if name.lower() in canon_words
    }
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(
                SkillRelation.from_skill_id,
                SkillRelation.to_skill_id,
                SkillRelation.share,
            )
            .where(
                SkillRelation.status == "accepted",
                SkillRelation.kind == "typical",
                SkillRelation.to_skill_id.in_(ids),
                SkillRelation.share.is_not(None),
            )
            # Najliczniejsza grupa (Java przy Gicie), nie egzotyczne narzędzie.
            .order_by(SkillRelation.support.desc(), SkillRelation.share.asc())
        )
    ).all()
    out: dict[str, tuple[str, float]] = {}
    for from_id, to_id, share in rows:
        canon = ids[to_id]
        source = dictionary.names.get(from_id)
        if canon not in out and source:
            out[canon] = (source, float(share))
    return out
