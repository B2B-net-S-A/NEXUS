"""Słownik rośnie z danych: nocne propozycje haseł i wariantów (06.11.2026).

Audyt słownika z 06.11.2026: słownik znał 46% must-have w rekrutacjach, a 89%
rekrutacji miało choć jedno wymaganie spoza słownika. Decyzja Artura „Etap 1:
A + B”: co noc zbieramy nazwy, których słownik nie zna, z trzech miejsc
(umiejętności profili, CV z generatora, wymagania rekrutacji), grupujemy je
w rodziny zapisów („excel”, „ms excel”, „microsoft excel”), a model
proponuje decyzję. Do słownika wchodzi tylko to, co zatwierdzi Head of
Recruitment albo admin (D7: jeden słownik, nic nie mapuje się samo).

Reguła dla ludzi: ``docs/claude/kandydaci-wyszukiwanie/slownik-rosnie-z-danych-propozycje.md``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Text, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feature import AIFeatureKey
from app.models.app_setting import AppSetting
from app.models.skill_proposal import SkillProposal
from app.services import skill_curation
from app.services.ai_models import fallbacks_for, model_for
from app.services.care.skills import (
    SkillDictionary,
    load_dictionary,
    loose_key,
    name_key,
    suggester,
)

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.skill_dictionary_proposals
TOP_FAMILIES = 400
BATCH_SIZE = 50
BATCH_CONCURRENCY = 3
JOB_WEIGHT = 20
USAGE_KEY = "skill_dictionary_usage"
DECISIONS = ("new", "alias", "generic", "soft", "noise")
ACCEPTABLE = ("new", "alias")
NAME_MAX = 100
WORDS_MAX = 6

_SPACES = re.compile(r"\s+")
_PARENS = re.compile(r"\s*\([^)]*\)")
_PREFIX = re.compile(r"^(?:ms|microsoft|apache)\s+")
_JOB_VARIANTS = re.compile(r"\s+(?:lub|or)\s+|\s+/\s+", re.IGNORECASE)


class ProposalError(Exception):
    """Błąd domenowy propozycji; ``status_code`` mapuje API."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


# ── Zbieranie nazw ──────────────────────────────────────────────────────────


@dataclass
class NameStat:
    raw: str
    cand: int = 0
    cv: int = 0
    jobs: int = 0

    @property
    def count(self) -> int:
        return self.cand + self.cv + self.jobs


def clean_name(raw: Any) -> Optional[str]:
    """Nazwa nadająca się na hasło albo ``None`` (zdanie, pusty, za długi)."""
    if not isinstance(raw, str):
        return None
    cleaned = _SPACES.sub(" ", raw).strip().strip(".;:").strip()
    if len(cleaned) < 2 or len(cleaned) > NAME_MAX:
        return None
    if len(cleaned.split(" ")) > WORDS_MAX:
        return None
    return cleaned


def split_cv_content(content: Any) -> list[str]:
    """„Java 17+, SQL, Spring (Boot, Data)” → trzy nazwy: przecinek w nawiasie nie dzieli."""
    if not isinstance(content, str):
        return []
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in content:
        if ch in "([":
            depth += 1
        elif ch in ")]" and depth:
            depth -= 1
        if ch in ",;" and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return [p for p in parts if p.strip()]


def split_job_name(raw: Any) -> list[str]:
    """Wiersz wymagań „C# lub .NET” to dwa zapisy, każdy szukany osobno."""
    if not isinstance(raw, str):
        return []
    return [p for p in _JOB_VARIANTS.split(raw) if p.strip()]


def _add(stats: dict[str, NameStat], raw: str, source: str, amount: int) -> None:
    name = clean_name(raw)
    if name is None:
        return
    key = name_key(name)
    stat = stats.get(key)
    if stat is None:
        stat = stats[key] = NameStat(raw=name)
    setattr(stat, source, getattr(stat, source) + amount)


_CAND_SQL = text(
    """
    SELECT btrim(s->>'name') AS name, count(DISTINCT c.id) AS n
    FROM candidates c
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(c.skills) = 'array' THEN c.skills ELSE '[]'::jsonb END
    ) s
    WHERE jsonb_typeof(s) = 'object' AND coalesce(btrim(s->>'name'), '') <> ''
    GROUP BY 1
    """
)

_CV_SQL = text(
    """
    SELECT d.id, s->>'content'
    FROM cv_generated_documents d
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(d.render_payload->'skills') = 'array'
             THEN d.render_payload->'skills' ELSE '[]'::jsonb END
    ) s
    WHERE d.status = 'ready' AND (d.render_payload->>'discarded_at') IS NULL
      AND jsonb_typeof(s) = 'object'
    """
)

_JOBS_SQL = text(
    """
    SELECT j.id, s->>'name'
    FROM jobs j
    CROSS JOIN LATERAL jsonb_array_elements(
        (CASE WHEN jsonb_typeof(j.must_skills) = 'array' THEN j.must_skills ELSE '[]'::jsonb END)
        || (CASE WHEN jsonb_typeof(j.nice_skills) = 'array' THEN j.nice_skills ELSE '[]'::jsonb END)
    ) s
    WHERE jsonb_typeof(s) = 'object'
    """
)


async def collect_names(db: AsyncSession) -> dict[str, NameStat]:
    """Nazwy z profili, CV i wymagań z liczbą profili / CV / rekrutacji."""
    stats: dict[str, NameStat] = {}
    for name, n in (await db.execute(_CAND_SQL)).all():
        _add(stats, name, "cand", int(n))
    for source, sql, splitter in (
        ("cv", _CV_SQL, split_cv_content),
        ("jobs", _JOBS_SQL, split_job_name),
    ):
        seen: dict[str, set[int]] = defaultdict(set)
        raw_of: dict[str, str] = {}
        for owner_id, value in (await db.execute(sql)).all():
            for part in splitter(value):
                name = clean_name(part)
                if name is None:
                    continue
                key = name_key(name)
                seen[key].add(owner_id)
                raw_of.setdefault(key, name)
        for key, owners in seen.items():
            _add(stats, raw_of[key], source, len(owners))
    return stats


# ── Rodziny ─────────────────────────────────────────────────────────────────


def family_key(raw: str) -> str:
    """Klucz rodziny: ``loose_key`` bez nawiasów i przedrostków ms/microsoft/apache."""
    base = _PARENS.sub(" ", raw or "").strip().lower()
    base = _PREFIX.sub("", base).strip()
    return (loose_key(base) or loose_key(raw))[:200]


def loose_index(dictionary: SkillDictionary) -> dict[str, int]:
    """``loose_key`` hasła/aliasu → id, tylko gdy klucz wskazuje jedno hasło."""
    found: dict[str, set[int]] = defaultdict(set)
    for key, skill_id in dictionary.by_key.items():
        lk = loose_key(key)
        if lk:
            found[lk].add(skill_id)
    return {lk: next(iter(ids)) for lk, ids in found.items() if len(ids) == 1}


def allowed_categories(dictionary: SkillDictionary) -> set[str]:
    return skill_curation.allowed_categories(dictionary.categories.values())


@dataclass
class Group:
    key: str
    names: set[str] = field(default_factory=set)
    row: Optional[SkillProposal] = None


def group_unknown(
    stats: dict[str, NameStat],
    dictionary: SkillDictionary,
    rows: list[SkillProposal],
) -> tuple[list[Group], dict[int, int]]:
    """Nazwy spoza słownika w rodzinach + liczba profili per hasło słownika.

    Rodzina, której nazwę zna już wiersz z poprzednich nocy (także po scaleniu
    rodzin z tym samym hasłem), dołącza do tego wiersza: wynik modelu zostaje,
    a nazwy ze zatwierdzonych i odrzuconych nie wracają."""
    usage: dict[int, int] = defaultdict(int)
    by_family: dict[str, set[str]] = defaultdict(set)
    for key, stat in stats.items():
        skill_id = dictionary.resolve(key)
        if skill_id is not None:
            usage[skill_id] += stat.cand
            continue
        fk = family_key(stat.raw)
        if fk:
            by_family[fk].add(key)

    row_by_name: dict[str, SkillProposal] = {}
    row_by_family: dict[str, SkillProposal] = {}
    for row in rows:
        row_by_family[row.family_key] = row
        for item in row.names or []:
            row_by_name[name_key(str(item.get("name", "")))] = row

    groups: dict[str, Group] = {}
    for fk, names in by_family.items():
        row = row_by_family.get(fk) or next(
            (row_by_name[n] for n in sorted(names) if n in row_by_name), None
        )
        gkey = row.family_key if row is not None else fk
        group = groups.setdefault(gkey, Group(key=gkey, row=row))
        group.names |= names
    return list(groups.values()), dict(usage)


def _names_payload(names: set[str], stats: dict[str, NameStat]) -> list[dict]:
    ordered = sorted(names, key=lambda n: (-stats[n].count, n))
    return [
        {"name": n, "count": stats[n].count, "cand": stats[n].cand} for n in ordered
    ]


def _fill_counts(
    row: SkillProposal, names: set[str], stats: dict[str, NameStat]
) -> None:
    row.names = _names_payload(names, stats)
    row.cand_count = sum(stats[n].cand for n in names)
    row.cv_count = sum(stats[n].cv for n in names)
    row.job_count = sum(stats[n].jobs for n in names)
    row.weight = row.cand_count + row.cv_count + JOB_WEIGHT * row.job_count
    heaviest = row.names[0]["name"] if row.names else row.family_key
    row.display_name = stats[heaviest].raw[:200] if heaviest in stats else heaviest


# ── Bezpieczniki wyniku modelu ──────────────────────────────────────────────


def _skill_for(
    name: str, dictionary: SkillDictionary, index: dict[str, int]
) -> Optional[int]:
    if not name:
        return None
    return dictionary.resolve(name) or index.get(loose_key(name))


def apply_guards(
    item: dict, dictionary: SkillDictionary, index: dict[str, int]
) -> dict:
    """Wynik modelu → pola wiersza; to, czego nie da się sprawdzić, idzie na „low”."""
    decision = item.get("decision") if item.get("decision") in DECISIONS else "noise"
    confidence = "high" if item.get("confidence") == "high" else "low"
    canonical = str(item.get("canonical") or "").strip()[:200]
    category = str(item.get("category") or "").strip() or None
    notes: list[str] = []
    target: Optional[int] = None
    replacements: list[str] = []

    if decision == "new" and canonical:
        existing = _skill_for(canonical, dictionary, index)
        if existing is not None:
            decision, target = "alias", existing
    if decision == "alias":
        target = target or _skill_for(canonical, dictionary, index)
        if target is None:
            confidence = "low"
            notes.append(f"Hasła „{canonical}” nie ma w słowniku: tylko ręcznie")
        else:
            canonical = dictionary.names.get(target, canonical)
            category = dictionary.categories.get(target)
            if (category or "").startswith("role_"):
                confidence = "low"
                notes.append(
                    f"Wskazuje rolę „{canonical}”, nie umiejętność: tylko ręcznie"
                )
    elif decision == "new":
        if not canonical:
            confidence = "low"
        if category not in allowed_categories(dictionary):
            category = None
            confidence = "low"
    else:
        canonical, category = "", None
        if decision == "generic":
            for name in item.get("replacements") or []:
                skill_id = _skill_for(str(name), dictionary, index)
                if skill_id is not None:
                    label = dictionary.names[skill_id]
                    if label not in replacements:
                        replacements.append(label)
    return {
        "decision": decision,
        "canonical": canonical or None,
        "target_skill_id": target,
        "category": category,
        "replacements": replacements[:8],
        "confidence": confidence,
        "review_note": "; ".join(notes) or None,
    }


def rule_alias(names: set[str], index: dict[str, int]) -> Optional[int]:
    """Każdy zapis rodziny trafia ``loose_key`` w to samo hasło → alias bez modelu."""
    targets = {index.get(loose_key(n)) for n in names}
    if len(targets) == 1 and None not in targets:
        return next(iter(targets))
    return None


# ── Model ───────────────────────────────────────────────────────────────────

SYSTEM = """Jesteś kuratorem słownika umiejętności IT agencji rekrutacyjnej. Dostajesz rodziny zapisów umiejętności z profili kandydatów, CV i wymagań klientów, których słownik nie zna, listę haseł, które słownik już zna, i listę dozwolonych kategorii.
Dla KAŻDEJ rodziny zwróć obiekt:
- "id": id rodziny bez zmian,
- "decision": "alias" (inny zapis hasła, które słownik już zna: literówka, skrót, odmiana, tłumaczenie, wersja), "new" (prawdziwa, konkretna umiejętność warta osobnego hasła), "generic" (ogólnik albo obszar zbyt szeroki na hasło, np. „IT analysis”, „relacyjne bazy danych”), "soft" (cecha osobista, język obcy, tryb pracy), "noise" (śmieć, fragment zdania),
- "canonical": dla "alias" DOKŁADNA nazwa hasła z listy słownika, dla "new" poprawna oficjalna pisownia (np. „Azure DevOps”, „ServiceNow”), inaczej "",
- "category": dla "new" jedna z dozwolonych kategorii, inaczej "",
- "replacements": dla "generic" do 6 konkretnych haseł z listy słownika, którymi rekruter może zastąpić ogólnik (np. dla „relacyjne bazy danych”: PostgreSQL, MySQL, Oracle DB), inaczej [],
- "confidence": "high" albo "low".
Nie zgaduj: gdy nie wiesz, co to jest, albo hasło słownika pasuje tylko w przybliżeniu, daj "low". Rola zawodowa (np. „team lead”) to nie umiejętność. Zwróć TYLKO JSON {"items":[...]}."""


def build_prompt(batch: list[dict], dictionary: SkillDictionary) -> str:
    return json.dumps(
        {
            "slownik": sorted(dictionary.names.values()),
            "kategorie": sorted(allowed_categories(dictionary)),
            "rodziny": batch,
        },
        ensure_ascii=False,
    )


def parse_reply(raw: str) -> dict[int, dict]:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("odpowiedź bez JSON")
    items = json.loads(raw[start : end + 1]).get("items") or []
    out: dict[int, dict] = {}
    for item in items:
        if isinstance(item, dict):
            try:
                out[int(item.get("id"))] = item
            except (TypeError, ValueError):
                continue
    return out


def _call_model(body: str) -> str:
    from app.services.claude_client import call_claude, text_of

    message = call_claude(
        model=model_for(FEATURE),
        fallback_models=list(fallbacks_for(FEATURE)),
        max_tokens=8000,
        temperature=0,
        timeout=180,
        max_retries=1,
        total_timeout=300,
        system=SYSTEM,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": body}],
    )
    return text_of(message)


async def classify(
    db: AsyncSession, families: list[dict], dictionary: SkillDictionary
) -> tuple[dict[int, dict], int]:
    """Klasyfikacja w partiach; zwraca wyniki po id i liczbę nieudanych partii."""
    from app.services.ai_quota import ai_feature

    batches = [
        families[i : i + BATCH_SIZE] for i in range(0, len(families), BATCH_SIZE)
    ]
    if not batches:
        return {}, 0
    limiter = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def run(batch: list[dict]) -> Optional[dict[int, dict]]:
        async with limiter:
            try:
                raw = await run_in_threadpool(
                    _call_model, build_prompt(batch, dictionary)
                )
                return parse_reply(raw)
            except Exception as exc:  # noqa: BLE001 — wynik modelu to dodatek
                logger.warning(
                    "skill proposals: partia nieudana (%s)", type(exc).__name__
                )
                return None

    async with ai_feature(db, FEATURE, units=len(batches)):
        await db.commit()  # zwolnij połączenie na czas modelu
        results = await asyncio.gather(*[run(b) for b in batches])
    merged: dict[int, dict] = {}
    failed = 0
    for result in results:
        if result is None:
            failed += 1
        else:
            merged.update(result)
    return merged, failed


# ── Nocny bieg ──────────────────────────────────────────────────────────────


def _merge_key(row: SkillProposal) -> Optional[str]:
    if row.decision == "alias" and row.target_skill_id:
        return f"#{row.target_skill_id}"
    if row.decision == "new" and row.canonical:
        return name_key(row.canonical)
    return None


async def run(db: AsyncSession, *, use_model: bool = True) -> dict:
    """Przelicz propozycje; ``use_model=False`` = same liczby i reguły bez modelu."""
    dictionary = await load_dictionary(db)
    index = loose_index(dictionary)
    stats = await collect_names(db)
    rows = list((await db.scalars(select(SkillProposal))).all())
    groups, usage = group_unknown(stats, dictionary, rows)

    open_groups = [g for g in groups if g.row is None or g.row.status == "open"]
    top = select_top(open_groups, stats)
    kept = {id(g.row) for g in top if g.row is not None}
    for row in rows:
        if row.status == "open" and id(row) not in kept:
            await db.delete(row)
    for group in top:
        if group.row is None:
            group.row = SkillProposal(
                family_key=group.key, display_name=group.key, status="open"
            )
            db.add(group.row)
        _fill_counts(group.row, group.names, stats)
        group.row.computed_at = func.now()

    pending: list[tuple[int, Group]] = []
    for group in top:
        row = group.row
        if row.classified_at is not None:
            continue
        target = rule_alias(group.names, index)
        if target is not None:
            fields = apply_guards(
                {
                    "decision": "alias",
                    "canonical": dictionary.names[target],
                    "confidence": "high",
                },
                dictionary,
                index,
            )
            _set_fields(row, fields, model=None)
        else:
            pending.append((len(pending), group))

    failed = 0
    model_error = False
    model = model_for(FEATURE)
    if use_model and pending:
        families = [
            {"id": i, "nazwy": [n["name"] for n in g.row.names][:12]}
            for i, g in pending
        ]
        try:
            results, failed = await classify(db, families, dictionary)
        except Exception as exc:  # noqa: BLE001 — wyłączona funkcja = same liczby
            logger.warning(
                "skill proposals: model niedostępny (%s)", type(exc).__name__
            )
            results, model_error = {}, True
        for i, group in pending:
            if i in results:
                _set_fields(
                    group.row, apply_guards(results[i], dictionary, index), model=model
                )

    merged = _merge_same_canonical([g.row for g in top])
    for row in merged:
        if row.id is None:
            db.expunge(row)
        else:
            await db.delete(row)

    await db.execute(
        insert(AppSetting)
        .values(key=USAGE_KEY, value={"counts": {str(k): v for k, v in usage.items()}})
        .on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": {"counts": {str(k): v for k, v in usage.items()}}},
        )
    )
    await db.commit()
    summary = {
        "unknown_names": sum(len(g.names) for g in groups),
        "families": len(groups),
        "open": len(top) - len(merged),
        "classified": len(pending) if use_model else 0,
        "failed_batches": failed,
        "model_error": model_error,
        "merged": len(merged),
        "model": model if use_model else None,
    }
    logger.info("skill proposals: %s", summary)
    return summary


def group_weight(names: set[str], stats: dict[str, NameStat]) -> int:
    return sum(stats[n].cand + stats[n].cv + JOB_WEIGHT * stats[n].jobs for n in names)


def select_top(groups: list[Group], stats: dict[str, NameStat]) -> list[Group]:
    """Najcięższe rodziny (``TOP_FAMILIES``); wiersze powstają tylko dla nich."""
    ranked = sorted(groups, key=lambda g: (-group_weight(g.names, stats), g.key))
    return ranked[:TOP_FAMILIES]


def _set_fields(row: SkillProposal, fields: dict, *, model: Optional[str]) -> None:
    for key, value in fields.items():
        setattr(row, key, value)
    row.model = model
    row.classified_at = func.now()


def _merge_same_canonical(rows: list[SkillProposal]) -> list[SkillProposal]:
    """Rodziny z tym samym hasłem w jeden wiersz (najcięższy zostaje); zwraca zbędne."""
    by_key: dict[str, list[SkillProposal]] = defaultdict(list)
    for row in rows:
        key = _merge_key(row)
        if key is not None:
            by_key[key].append(row)
    dropped: list[SkillProposal] = []
    for same in by_key.values():
        if len(same) < 2:
            continue
        same.sort(key=lambda r: -r.weight)
        keep, others = same[0], same[1:]
        names = {n["name"]: n for n in keep.names}
        notes = [keep.review_note] if keep.review_note else []
        for other in others:
            for n in other.names:
                names.setdefault(n["name"], n)
            keep.cand_count += other.cand_count
            keep.cv_count += other.cv_count
            keep.job_count += other.job_count
            if other.confidence == "low":
                keep.confidence = "low"
            if other.review_note and other.review_note not in notes:
                notes.append(other.review_note)
            dropped.append(other)
        keep.names = sorted(
            names.values(), key=lambda n: (-int(n.get("count", 0)), n["name"])
        )
        keep.weight = keep.cand_count + keep.cv_count + JOB_WEIGHT * keep.job_count
        keep.review_note = "; ".join(notes) or None
    return dropped


# ── Decyzje HoR+ ────────────────────────────────────────────────────────────


def is_sure(row: SkillProposal) -> bool:
    """Do „Zatwierdź pewne”: high, nowe hasło albo wariant, bez uwagi, z kategorią."""
    return (
        row.status == "open"
        and row.decision in ACCEPTABLE
        and row.confidence == "high"
        and not row.review_note
        and bool(row.category)
        and (
            bool(row.canonical) if row.decision == "new" else bool(row.target_skill_id)
        )
    )


async def _open_row(db: AsyncSession, proposal_id: int) -> SkillProposal:
    row = await db.get(SkillProposal, proposal_id, with_for_update=True)
    if row is None:
        raise ProposalError("Nie ma takiej propozycji.", 404)
    if row.status != "open":
        raise ProposalError("Tę propozycję ktoś już rozstrzygnął.", 409)
    return row


def alias_names(row: SkillProposal) -> list[str]:
    """Zapisy, które wchodzą do słownika jako aliasy.

    Zapis z dopiskiem w nawiasie („excel (advanced)”, „excel (vba)”) liczy się
    do wagi rodziny, ale aliasem nie zostaje: rodzina „Microsoft Excel” miała
    ich na stagingu kilkadziesiąt (06.11.2026), a mapa aliasów porównuje
    zapis dosłownie, więc każdy byłby osobnym śmieciem w słowniku."""
    return [
        str(n.get("name"))
        for n in row.names or []
        if n.get("name") and "(" not in str(n.get("name"))
    ]


async def _apply(
    db: AsyncSession, row: SkillProposal, *, curated_by: Optional[str]
) -> None:
    names = alias_names(row)
    if row.decision == "new":
        canonical = (row.canonical or "").strip()
        aliases = [n for n in names if name_key(n) != name_key(canonical)]
        skill_id, _ = await skill_curation.create_skill_rows(
            db, canonical_name=canonical, category=row.category, aliases=aliases
        )
        row.target_skill_id = skill_id
    elif row.decision == "alias" and row.target_skill_id:
        await skill_curation.add_alias_rows(db, row.target_skill_id, names)
    else:
        raise ProposalError(
            "Do słownika wchodzi tylko nowe hasło albo wariant znanego hasła — "
            "ogólnik, cechę i śmieć odrzuć."
        )
    row.status = "accepted"
    row.curated_by = curated_by
    row.curated_at = func.now()


async def accept(
    db: AsyncSession,
    proposal_id: int,
    *,
    curated_by: Optional[str],
    decision: Optional[str] = None,
    canonical: Optional[str] = None,
    category: Optional[str] = None,
    target_skill_id: Optional[int] = None,
) -> dict:
    """Zatwierdź jedną propozycję, z poprawkami HoR+ (decyzja, nazwa, kategoria, hasło)."""
    row = await _open_row(db, proposal_id)
    dictionary = await load_dictionary(db)
    if decision is not None:
        if decision not in ACCEPTABLE:
            raise ProposalError("Decyzja musi być „new” albo „alias”.")
        row.decision = decision
    if canonical is not None:
        row.canonical = canonical.strip()[:200] or None
    if category is not None:
        if category and category not in allowed_categories(dictionary):
            raise ProposalError(f"Nieznana kategoria „{category}”.")
        row.category = category or None
    if target_skill_id is not None:
        if target_skill_id not in dictionary.names:
            raise ProposalError("Nie ma takiego hasła w słowniku.")
        row.target_skill_id = target_skill_id
    if row.decision == "new" and not row.canonical:
        raise ProposalError("Nowe hasło potrzebuje nazwy.")
    if row.decision == "alias" and not row.target_skill_id:
        raise ProposalError("Wskaż hasło słownika, do którego dopisać warianty.")
    try:
        await _apply(db, row, curated_by=curated_by)
    except skill_curation.CurationConflict as exc:
        await db.rollback()
        raise ProposalError(str(exc), 409) from exc
    except skill_curation.CurationError as exc:
        await db.rollback()
        raise ProposalError(str(exc)) from exc
    await db.commit()
    skill_id = row.target_skill_id
    await skill_curation.after_dictionary_change(db, [skill_id] if skill_id else [])
    return {"id": row.id, "status": row.status, "skill_id": skill_id}


async def reject(
    db: AsyncSession, proposal_id: int, *, curated_by: Optional[str]
) -> dict:
    row = await _open_row(db, proposal_id)
    row.status = "rejected"
    row.curated_by = curated_by
    row.curated_at = func.now()
    await db.commit()
    return {"id": row.id, "status": row.status}


async def accept_sure(db: AsyncSession, *, curated_by: Optional[str]) -> dict:
    """„Zatwierdź pewne”: każda we własnym savepoincie, mapa odświeżona raz."""
    rows = (
        await db.scalars(
            select(SkillProposal)
            .where(SkillProposal.status == "open")
            .order_by(SkillProposal.weight.desc(), SkillProposal.id)
            .with_for_update()
        )
    ).all()
    accepted: list[int] = []
    skipped: list[dict] = []
    for row in rows:
        if not is_sure(row):
            continue
        try:
            async with db.begin_nested():
                await _apply(db, row, curated_by=curated_by)
            accepted.append(row.target_skill_id)
        except (skill_curation.CurationError, ProposalError) as exc:
            skipped.append({"id": row.id, "name": row.display_name, "reason": str(exc)})
    await db.commit()
    if accepted:
        await skill_curation.after_dictionary_change(db, [i for i in accepted if i])
    return {"accepted": len(accepted), "skipped": skipped}


# ── Odczyt ──────────────────────────────────────────────────────────────────


async def load_usage(db: AsyncSession) -> dict[int, int]:
    value = await db.scalar(select(AppSetting.value).where(AppSetting.key == USAGE_KEY))
    counts = (value or {}).get("counts") or {}
    out: dict[int, int] = {}
    for key, count in counts.items():
        try:
            out[int(key)] = int(count)
        except (TypeError, ValueError):
            continue
    return out


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def row_payload(row: SkillProposal, dictionary: SkillDictionary) -> dict:
    return {
        "id": row.id,
        "family_key": row.family_key,
        "display_name": row.display_name,
        "names": row.names or [],
        "cand_count": row.cand_count,
        "cv_count": row.cv_count,
        "job_count": row.job_count,
        "weight": row.weight,
        "decision": row.decision,
        "canonical": row.canonical,
        "target_skill_id": row.target_skill_id,
        "target_name": dictionary.names.get(row.target_skill_id)
        if row.target_skill_id
        else None,
        "category": row.category,
        "replacements": row.replacements or [],
        "confidence": row.confidence,
        "review_note": row.review_note,
        "status": row.status,
        "sure": is_sure(row),
        "model": row.model,
        "computed_at": row.computed_at.isoformat() if row.computed_at else None,
        "curated_by": row.curated_by,
        "curated_at": row.curated_at.isoformat() if row.curated_at else None,
    }


async def list_proposals(
    db: AsyncSession,
    *,
    status: str = "open",
    decision: Optional[str] = None,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    dictionary = await load_dictionary(db)
    query = select(SkillProposal).where(SkillProposal.status == status)
    if decision:
        query = query.where(SkillProposal.decision == decision)
    needle = q.strip().lower()
    if needle:
        query = query.where(
            func.lower(SkillProposal.display_name).contains(needle)
            | func.lower(func.coalesce(SkillProposal.canonical, "")).contains(needle)
            | func.lower(SkillProposal.names.cast(Text)).contains(needle)
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await db.scalars(
            query.order_by(SkillProposal.weight.desc(), SkillProposal.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    open_rows = (
        await db.scalars(select(SkillProposal).where(SkillProposal.status == "open"))
    ).all()
    by_decision: dict[str, int] = defaultdict(int)
    for row in open_rows:
        by_decision[row.decision or "unclassified"] += 1
    return {
        "items": [row_payload(r, dictionary) for r in rows],
        "total": int(total),
        "totals": {
            "open": len(open_rows),
            "names": sum(len(r.names or []) for r in open_rows),
            "sure": sum(1 for r in open_rows if is_sure(r)),
            "by_decision": dict(by_decision),
        },
        "computed_at": _iso(
            max((r.computed_at for r in open_rows if r.computed_at), default=None)
        ),
        "categories": sorted(allowed_categories(dictionary)),
    }


# ── Podpowiedź w edytorze wymagań ───────────────────────────────────────────


def hint_worthy(row: SkillProposal) -> bool:
    """Propozycja, którą wolno podpowiedzieć przy wierszu.

    Wariant i nowe hasło tylko pewne i bez uwagi: wariant roli („team
    management” → „Engineering Management”) czeka w zakładce na decyzję
    człowieka, więc podpowiedź nie może go podsuwać jednym kliknięciem."""
    if row.decision == "generic":
        return True
    return (
        row.decision in ACCEPTABLE and row.confidence == "high" and not row.review_note
    )


async def dictionary_hints(db: AsyncSession, words: list[str]) -> list[dict]:
    """Podpowiedź przy słowie wiersza, którego słownik nie zna.

    Delivery Lead zmienia nią tylko swój wiersz (dopisuje warianty); słownik
    zmienia wyłącznie HoR+ przez propozycję (``proposal_id``)."""
    dictionary = await load_dictionary(db)
    usage = await load_usage(db)
    rows = (
        await db.scalars(select(SkillProposal).where(SkillProposal.status == "open"))
    ).all()
    by_name: dict[str, SkillProposal] = {}
    by_family: dict[str, SkillProposal] = {}
    for row in rows:
        by_family[row.family_key] = row
        for item in row.names or []:
            by_name[name_key(str(item.get("name", "")))] = row
    suggest = suggester(dictionary)

    def counted(skill_id: int) -> dict:
        return {"name": dictionary.names[skill_id], "count": usage.get(skill_id)}

    hints: list[dict] = []
    seen: set[str] = set()
    for raw in words:
        word = clean_name(raw)
        if word is None:
            continue
        key = name_key(word)
        if key in seen or dictionary.resolve(key) is not None:
            continue
        seen.add(key)
        row = by_name.get(key) or by_family.get(family_key(word))
        hint: Optional[dict] = None
        if row is not None and hint_worthy(row):
            names = {str(n.get("name")): n for n in row.names or []}
            own = names.get(key, {})
            hint = {
                "word": word,
                "kind": row.decision,
                "proposal_id": row.id,
                "word_count": own.get("cand"),
                "target": None,
                "add_words": [],
                "canonical": row.canonical,
                "category": row.category,
            }
            if row.decision == "alias" and row.target_skill_id in dictionary.names:
                hint["target"] = counted(row.target_skill_id)
                hint["add_words"] = [hint["target"]]
            elif row.decision == "generic":
                ids = [dictionary.resolve(n) for n in row.replacements or []]
                hint["add_words"] = [counted(i) for i in ids if i is not None]
            elif row.decision == "new":
                hint["add_words"] = [
                    {"name": n, "count": names.get(n, {}).get("cand")}
                    for n in alias_names(row)
                    if n != key
                ][:4]
            if not hint["add_words"] and row.decision != "new":
                hint = None
        if hint is None:
            ids = suggest(word)
            if ids:
                hint = {
                    "word": word,
                    "kind": "suggest",
                    "proposal_id": None,
                    "word_count": None,
                    "target": counted(ids[0]),
                    "add_words": [counted(i) for i in ids],
                    "canonical": None,
                    "category": None,
                }
        if hint is not None:
            hints.append(hint)
    return hints
