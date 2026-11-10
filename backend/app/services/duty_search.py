"""„Kto już to robił” — wyszukiwanie po celu projektu i obowiązkach.

Decyzja Artura 09.11.2026, reguła
``docs/claude/kandydaci-wyszukiwanie/kto-juz-to-robil-wyszukiwanie-po-celu.md``.

Przebieg (w tle, ``app/tasks/duty_search_worker.py``):

1. rozbicie celu (F47): zdolności z wagą, sygnały pośrednie, wzorce do tekstu CV,
   trzy przykładowe akapity CV osoby, która to zrobiła;
2. szeroka sieć: wektor celu, wektory akapitów, wzorce w ``raw_cv_text`` (RRF)
   oraz kanoniczny ranking „Z requestu” (top 50) — ta sama bramka
   dopuszczalności (blacklista, NDA, weto) co ``canonical_search``;
3. ocena CV (F48) z dosłownym cytatem; cytat sprawdza kod;
4. kolejność widoku: najpierw „Robił to” / „Bardzo blisko” z cytatem, w grupie
   RRF z obu list. Ocena celu NIE wchodzi do kanonicznego fitu.

Wynik modelu jest dodatkiem: bez rozbicia szukamy samym wektorem celu; awaria
oceny wszystkich osób kończy przebieg jako ``failed`` (komunikat, nie pusta lista).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import anyio
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feature import AIFeatureKey
from app.models.duty_search_run import DutySearchResult, DutySearchRun
from app.services.ai_models import fallbacks_for, model_for
from app.services.llm_prompts import DUTY_SEARCH_JUDGE, DUTY_SEARCH_PLAN
from app.services.prompt_fencing import fence

logger = logging.getLogger(__name__)

PLAN_FEATURE = AIFeatureKey.duty_search_plan
JUDGE_FEATURE = AIFeatureKey.duty_search_judge

DAILY_LIMIT = int(os.environ.get("DUTY_SEARCH_DAILY_LIMIT", "10"))
MAX_ACTIVE_PER_USER = 2
GOAL_MIN_CHARS = 30
GOAL_MAX_CHARS = 6000

POOL_SIZE = 150
GOAL_POOL_JUDGED = 60
CANONICAL_TOP = 50
CV_CHAR_LIMIT = 14_000
MODEL_THREADS = 8
PLAN_TIMEOUT_SECONDS = 90.0
JUDGE_TIMEOUT_SECONDS = 60.0
REGEX_STATEMENT_TIMEOUT_MS = 20_000
RRF_K = 60

TIERS = ("zrobil_to", "bardzo_blisko", "ma_klocki", "brak")
STRONG_TIERS = frozenset({"zrobil_to", "bardzo_blisko"})
CAP_STATES = frozenset({"tak", "czesciowo", "brak"})

# Cytat: dosłownie (po normalizacji) albo ≥ 80% trójek słów z CV przy cytacie
# z co najmniej 6 słów. Odczyt PDF wstawia daty w środek zdania
# („optimize/ 01-2021 – Present improve JIRA…”), a model skleja zdanie —
# ścisłe porównanie odrzucało 12% prawdziwych cytatów (pomiar 09.11.2026).
QUOTE_MIN_WORDS = 3
FUZZY_MIN_WORDS = 6
FUZZY_SHARE = 0.8


# --- funkcje czyste -----------------------------------------------------------


def normalize_words(value: Optional[str]) -> list[str]:
    folded = unicodedata.normalize("NFKD", value or "")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch)).casefold()
    folded = folded.replace("ł", "l")
    return re.sub(r"[^0-9a-z]+", " ", folded).split()


class CvText:
    """Znormalizowany tekst CV do sprawdzania cytatów (liczony raz na osobę)."""

    def __init__(self, raw: Optional[str]):
        words = normalize_words(raw)
        self.joined = " " + " ".join(words) + " "
        self.trigrams = {" ".join(words[i : i + 3]) for i in range(len(words) - 2)}

    def contains(self, quote: Optional[str]) -> bool:
        words = normalize_words(quote)
        if len(words) < QUOTE_MIN_WORDS:
            return False
        if f" {' '.join(words)} " in self.joined:
            return True
        if len(words) < FUZZY_MIN_WORDS:
            return False
        grams = [" ".join(words[i : i + 3]) for i in range(len(words) - 2)]
        hits = sum(1 for g in grams if g in self.trigrams)
        return hits / len(grams) >= FUZZY_SHARE


def _clip(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


@dataclass(frozen=True)
class Capability:
    name: str
    weight: int
    hint: str


@dataclass(frozen=True)
class GoalPlan:
    summary: str
    capabilities: tuple[Capability, ...] = ()
    signals: tuple[tuple[str, str], ...] = ()
    patterns: tuple[str, ...] = ()
    anti: tuple[str, ...] = ()
    fragments: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "summary": self.summary,
            "capabilities": [
                {"name": c.name, "weight": c.weight, "hint": c.hint}
                for c in self.capabilities
            ],
            "signals": [{"signal": s, "why": w} for s, w in self.signals],
            "anti": list(self.anti),
            "patterns": list(self.patterns),
            "fragments": list(self.fragments),
        }


# Postgres ARE: lookahead i odwołania wsteczne to jedyne konstrukcje, które
# potrafią zjeść czas; resztę pilnuje statement_timeout.
_UNSAFE_PATTERN = re.compile(r"\(\?|\\[1-9]")


def parse_plan(raw: Mapping[str, Any], *, fallback_summary: str) -> GoalPlan:
    caps: list[Capability] = []
    seen: set[str] = set()
    for item in _as_list(raw.get("zdolnosci")):
        if len(caps) >= 6:
            break
        if not isinstance(item, Mapping):
            continue
        name = _clip(item.get("nazwa"), 80)
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        try:
            weight = int(item.get("waga") or 1)
        except (TypeError, ValueError):
            weight = 1
        caps.append(
            Capability(
                name, min(3, max(1, weight)), _clip(item.get("po_czym_poznac"), 200)
            )
        )
    signals = tuple(
        (_clip(s.get("sygnal"), 160), _clip(s.get("dlaczego"), 200))
        for s in _as_list(raw.get("sygnaly_posrednie"))[:8]
        if isinstance(s, Mapping) and _clip(s.get("sygnal"), 160)
    )
    patterns = tuple(
        p
        for p in (
            str(x).strip()
            for x in _as_list(raw.get("wzorce_regex"))[:14]
            if isinstance(x, str)
        )
        if 3 <= len(p) <= 200 and not _UNSAFE_PATTERN.search(p)
    )
    anti = tuple(
        _clip(a, 160) for a in _as_list(raw.get("anty_sygnaly"))[:3] if _clip(a, 160)
    )
    fragments = tuple(
        _clip(f, 1200)
        for f in _as_list(raw.get("fragmenty_cv"))[:3]
        if len(_clip(f, 1200)) >= 40
    )
    summary = _clip(raw.get("cel_jednym_zdaniem"), 400) or _clip(fallback_summary, 400)
    return GoalPlan(summary, tuple(caps), signals, patterns, anti, fragments)


@dataclass(frozen=True)
class Assessment:
    tier: str
    confidence: Optional[int]
    capabilities: dict[str, str] = field(default_factory=dict)
    evidence: tuple[dict, ...] = ()
    gap: str = ""
    question: str = ""
    rejected_quotes: int = 0
    error: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "capabilities": dict(self.capabilities),
            "evidence": list(self.evidence),
            "gap": self.gap,
            "question": self.question,
            "rejected_quotes": self.rejected_quotes,
            "error": self.error,
        }


def parse_assessment(
    raw: Mapping[str, Any], cv: CvText, capability_names: Iterable[str]
) -> Assessment:
    """Odpowiedź sędziego → ocena. Bez sprawdzonego cytatu nie ma poziomu."""
    names = {n.casefold(): n for n in capability_names}
    tier = raw.get("poziom") if raw.get("poziom") in TIERS else "brak"
    try:
        confidence: Optional[int] = max(0, min(100, int(raw.get("pewnosc"))))
    except (TypeError, ValueError):
        confidence = None
    caps: dict[str, str] = {}
    raw_caps = raw.get("zdolnosci") if isinstance(raw.get("zdolnosci"), Mapping) else {}
    for key, value in raw_caps.items():
        name = names.get(str(key).strip().casefold())
        if name and value in CAP_STATES:
            caps[name] = value
    kept: list[dict] = []
    rejected = 0
    for item in _as_list(raw.get("dowody"))[:3]:
        if not isinstance(item, Mapping):
            continue
        quote = _clip(item.get("cytat"), 400)
        if cv.contains(quote):
            kept.append(
                {
                    "quote": quote,
                    "where": _clip(item.get("gdzie"), 160),
                    "meaning": _clip(item.get("wniosek"), 300),
                }
            )
        else:
            rejected += 1
    if not kept:
        tier = "brak"
    return Assessment(
        tier=tier,
        confidence=confidence,
        capabilities=caps,
        evidence=tuple(kept),
        gap=_clip(raw.get("luka"), 400),
        question=_clip(raw.get("pytanie"), 400),
        rejected_quotes=rejected,
    )


def rrf_scores(lists: Iterable[Sequence[int]], *, k: int = RRF_K) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ids in lists:
        for rank, cid in enumerate(ids):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return scores


def fused_order(
    canonical_ids: Sequence[int],
    goal_ids: Sequence[int],
    tiers: Mapping[int, str],
) -> list[int]:
    """Najpierw „Robił to” i „Bardzo blisko”, w grupie RRF z obu list.

    Ocena celu NIE przestawia osób w obrębie grupy — pomiar 09.11 pokazał,
    że kolejność po samej ocenie gubi osoby, które klient przyjmował.
    """
    scores = rrf_scores([canonical_ids, goal_ids])
    union = list(dict.fromkeys([*canonical_ids, *goal_ids]))
    return sorted(
        union, key=lambda c: (tiers.get(c) not in STRONG_TIERS, -scores.get(c, 0.0))
    )


def capabilities_block(plan: GoalPlan) -> str:
    if not plan.capabilities:
        return "- (brak rozbicia — oceniaj względem celu)"
    return "\n".join(
        f"- {c.name} (waga {c.weight}): {c.hint}" for c in plan.capabilities
    )


def signals_block(plan: GoalPlan) -> str:
    if not plan.signals:
        return "- (brak)"
    return "\n".join(f"- {s}" for s, _ in plan.signals)


# --- wywołania modeli (w wątku; testy je podmieniają) -------------------------


def _call_plan_model(prompt: str) -> str:
    from app.services.claude_client import call_claude_text  # noqa: PLC0415

    return call_claude_text(
        total_timeout=PLAN_TIMEOUT_SECONDS,
        model=model_for(PLAN_FEATURE),
        fallback_models=fallbacks_for(PLAN_FEATURE),
        max_tokens=7000,
        thinking={"type": "disabled"},
        system=DUTY_SEARCH_PLAN.system_prompt or "",
        messages=[{"role": "user", "content": prompt}],
    )


def _call_judge_model(prompt: str) -> str:
    from app.services.claude_client import call_claude_text  # noqa: PLC0415

    return call_claude_text(
        total_timeout=JUDGE_TIMEOUT_SECONDS,
        model=model_for(JUDGE_FEATURE),
        fallback_models=fallbacks_for(JUDGE_FEATURE),
        max_tokens=1200,
        thinking={"type": "disabled"},
        system=DUTY_SEARCH_JUDGE.system_prompt or "",
        messages=[{"role": "user", "content": prompt}],
    )


_LIMITER: Optional[anyio.CapacityLimiter] = None


def _model_limiter() -> anyio.CapacityLimiter:
    # Własne wątki zamiast wspólnej puli: ok. 100 wywołań po kilkanaście sekund
    # zajęłoby pulę ``run_in_threadpool`` i zatrzymało inne trasy.
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = anyio.CapacityLimiter(MODEL_THREADS)
    return _LIMITER


def goal_prompt_text(title: Optional[str], goal: str) -> str:
    return fence("cel", f"{title or ''}\n{goal}".strip())


# --- przebieg -----------------------------------------------------------------


@dataclass
class _Person:
    candidate_id: int
    cv_text: str


async def _plan(db: AsyncSession, run: DutySearchRun) -> tuple[GoalPlan, bool]:
    from app.services.ai_quota import ai_feature
    from app.services.cv_quoted_evidence import model_json

    fallback = run.goal_title or run.goal_text[:200]
    try:
        async with ai_feature(db, PLAN_FEATURE, user_id=run.created_by, units=1):
            await db.commit()
            raw = await anyio.to_thread.run_sync(
                _call_plan_model,
                DUTY_SEARCH_PLAN.render(
                    goal=goal_prompt_text(run.goal_title, run.goal_text)
                ),
                limiter=_model_limiter(),
            )
        return parse_plan(model_json(raw), fallback_summary=fallback), True
    except Exception as exc:  # noqa: BLE001 — dodatek: idziemy samym wektorem celu
        logger.warning("[duty-search] rozbicie celu nieudane (%s): %s", run.id, exc)
        return GoalPlan(summary=_clip(fallback, 400)), False


def _radar_query(run: DutySearchRun):
    from app.services.talent_radar_search import RadarQuery

    return RadarQuery(
        client_id=run.client_id,
        text=f"{run.goal_title or ''}\n\nObowiązki:\n{run.goal_text}".strip(),
        title=run.goal_title,
        top_k=CANONICAL_TOP,
    )


async def _canonical(
    db: AsyncSession, run: DutySearchRun
) -> tuple[list[int], dict[int, float], bool]:
    from app.services.talent_radar_search import canonical_search

    result = await canonical_search(db, _radar_query(run), user_id=run.created_by)
    ids: list[int] = []
    fits: dict[int, float] = {}
    for fit in result.breakdowns:
        cid = fit.breakdown.candidate_id
        ids.append(cid)
        if fit.fit_score is not None:
            fits[cid] = float(fit.fit_score)
    return ids, fits, bool(result.degraded)


async def _vector_hits(vector: list[float], limit: int) -> list[int]:
    from app.core.config import settings
    from app.services.embedding_service import _get_qdrant_client

    def _query() -> list[int]:
        client = _get_qdrant_client()
        if client is None:
            return []
        res = client.query_points(
            settings.QDRANT_COLLECTION, query=vector, limit=limit, with_payload=False
        )
        return [int(p.id) for p in res.points]

    return await anyio.to_thread.run_sync(_query)


async def _pattern_hits(db: AsyncSession, patterns: Sequence[str]) -> list[int]:
    """Osoby z co najmniej dwoma różnymi wzorcami w tekście CV."""
    good: list[str] = []
    for pattern in patterns:
        try:
            async with db.begin_nested():
                await db.execute(text("SELECT 'x' ~* :p"), {"p": pattern})
            good.append(pattern)
        except Exception:  # noqa: BLE001 — zły wzorzec od modelu po prostu odpada
            continue
    if len(good) < 2:
        return []
    expr = " + ".join(f"(raw_cv_text ~* :p{i})::int" for i in range(len(good)))
    params = {f"p{i}": p for i, p in enumerate(good)}
    try:
        async with db.begin_nested():
            await db.execute(
                text(f"SET LOCAL statement_timeout = {REGEX_STATEMENT_TIMEOUT_MS}")
            )
            rows = (
                await db.execute(
                    text(
                        f"SELECT id, {expr} AS hits FROM candidates "
                        "WHERE raw_cv_text IS NOT NULL "
                        f"ORDER BY hits DESC, id DESC LIMIT {POOL_SIZE}"
                    ),
                    params,
                )
            ).all()
    except Exception as exc:  # noqa: BLE001 — limit czasu: zostają wektory
        logger.warning("[duty-search] wzorce w CV przerwane: %s", exc)
        return []
    return [int(r[0]) for r in rows if int(r[1]) >= 2]


async def _goal_pool(
    db: AsyncSession, run: DutySearchRun, plan: GoalPlan
) -> tuple[list[int], dict]:
    from app.services.embedding_service import generate_embedding

    lists: dict[str, list[int]] = {}
    goal_vec = await generate_embedding(
        f"{run.goal_title or ''}\n{run.goal_text}", input_type="query"
    )
    if goal_vec:
        lists["goal"] = await _vector_hits(goal_vec, POOL_SIZE)
    for i, fragment in enumerate(plan.fragments):
        vec = await generate_embedding(fragment, input_type="document", use_cache=False)
        if vec:
            lists[f"fragment{i + 1}"] = await _vector_hits(vec, POOL_SIZE)
    if plan.patterns:
        lists["patterns"] = await _pattern_hits(db, plan.patterns)
    scores = rrf_scores(lists.values())
    pool = sorted(scores, key=lambda c: -scores[c])[:POOL_SIZE]
    return pool, {name: len(ids) for name, ids in lists.items()}


async def _eligible(
    db: AsyncSession, run: DutySearchRun, ids: Sequence[int]
) -> list[int]:
    """Ta sama bramka co ``canonical_search`` (blacklista, NDA, weto, dealbreakery)."""
    from app.api.matching import _gate_and_dealbreakers
    from app.services.champion_intake import enforce_operation
    from app.services.request_matching_context import build_request_context
    from app.services.requirement_contract import search_dealbreaker_inputs
    from app.services.scoring_service import resolve_active_profile
    from app.services.talent_radar_search import _load_candidates, build_ephemeral_job

    if not ids:
        return []
    job = build_ephemeral_job(_radar_query(run))
    enforce_operation(job, "search", force=True)
    profile = await resolve_active_profile(
        db, user_id=run.created_by, client_id=run.client_id
    )
    target = build_request_context(job, profile).as_job()
    candidates = await _load_candidates(db, list(ids))
    kept, _annotations, _hidden, _, _ = await _gate_and_dealbreakers(
        db,
        job=target,
        ordered=candidates,
        now=datetime.now(timezone.utc),
        inputs=search_dealbreaker_inputs(target),
    )
    return [c.id for c in kept]


async def _already_in_job(db: AsyncSession, job_id: Optional[int]) -> set[int]:
    if job_id is None:
        return set()
    from app.models.recruitment_pipeline import CandidateStage

    rows = await db.scalars(
        select(CandidateStage.candidate_id).where(CandidateStage.job_id == job_id)
    )
    return set(rows.all())


async def _load_cvs(db: AsyncSession, ids: Sequence[int]) -> dict[int, str]:
    rows = (
        await db.execute(
            text("SELECT id, raw_cv_text FROM candidates WHERE id = ANY(:ids)"),
            {"ids": list(ids)},
        )
    ).all()
    return {int(r[0]): r[1] or "" for r in rows}


async def _judge(
    db: AsyncSession, run: DutySearchRun, plan: GoalPlan, people: Sequence[_Person]
) -> dict[int, Assessment]:
    from app.services.ai_quota import ai_feature
    from app.services.cv_quoted_evidence import model_json

    names = [c.name for c in plan.capabilities]
    to_call = [p for p in people if len(p.cv_text.strip()) >= 200]
    out: dict[int, Assessment] = {
        p.candidate_id: Assessment(tier="brak", confidence=None, error="no_cv")
        for p in people
        if p not in to_call
    }
    if not to_call:
        return out
    goal = plan.summary or run.goal_title or run.goal_text[:400]
    prompts = [
        DUTY_SEARCH_JUDGE.render(
            goal=goal,
            capabilities=capabilities_block(plan),
            signals=signals_block(plan),
            cv=fence("cv", p.cv_text[:CV_CHAR_LIMIT]),
        )
        for p in to_call
    ]
    async with ai_feature(
        db, JUDGE_FEATURE, user_id=run.created_by, units=len(to_call)
    ):
        await db.commit()  # zwolnij połączenie na czas modelu
        answers = await asyncio.gather(
            *(
                anyio.to_thread.run_sync(
                    _call_judge_model, prompt, limiter=_model_limiter()
                )
                for prompt in prompts
            ),
            return_exceptions=True,
        )
    for person, answer in zip(to_call, answers):
        if isinstance(answer, BaseException):
            out[person.candidate_id] = Assessment(
                tier="brak", confidence=None, error="model"
            )
            continue
        try:
            out[person.candidate_id] = parse_assessment(
                model_json(answer), CvText(person.cv_text), names
            )
        except Exception:  # noqa: BLE001 — zła odpowiedź jednej osoby
            out[person.candidate_id] = Assessment(
                tier="brak", confidence=None, error="parse"
            )
    return out


async def execute_run(db: AsyncSession, run: DutySearchRun) -> None:
    """Cały przebieg jednego wyszukiwania. Wyjątek zostawia stan workerowi."""
    started = time.monotonic()
    plan, plan_ok = await _plan(db, run)
    t_plan = time.monotonic() - started

    canonical: list[int] = []
    fits: dict[int, float] = {}
    canonical_degraded = False
    try:
        # Punkt zapisu: błąd bazy w rankingu nie może zostawić przerwanej
        # transakcji, bo dalej idzie pula celu na tej samej sesji.
        async with db.begin_nested():
            canonical, fits, canonical_degraded = await _canonical(db, run)
    except Exception as exc:  # noqa: BLE001 — zostaje pula celu
        logger.warning(
            "[duty-search] kanoniczny ranking nieudany (%s): %s", run.id, exc
        )
        canonical_degraded = True
    goal_pool, list_sizes = await _goal_pool(db, run, plan)
    if not canonical and not goal_pool:
        raise DutySearchFailed("retrieval_unavailable")

    excluded = await _already_in_job(db, run.job_id)
    eligible = set(await _eligible(db, run, goal_pool[:POOL_SIZE]))
    canonical = [c for c in canonical if c not in excluded][:CANONICAL_TOP]
    goal_ids = [c for c in goal_pool if c in eligible and c not in excluded]
    judged_ids = list(dict.fromkeys([*canonical, *goal_ids[:GOAL_POOL_JUDGED]]))
    t_pool = time.monotonic() - started

    cvs = await _load_cvs(db, judged_ids)
    people = [_Person(cid, cvs.get(cid, "")) for cid in judged_ids]
    assessments = await _judge(db, run, plan, people)
    called = [a for a in assessments.values() if a.error != "no_cv"]
    if called and all(a.error in ("model", "parse") for a in called):
        raise DutySearchFailed("judge_unavailable")

    tiers = {cid: a.tier for cid, a in assessments.items()}
    order = fused_order(canonical, goal_ids[:GOAL_POOL_JUDGED], tiers)
    canonical_set = set(canonical)
    await db.execute(delete(DutySearchResult).where(DutySearchResult.run_id == run.id))
    for position, cid in enumerate(order):
        a = assessments.get(cid) or Assessment(
            tier="brak", confidence=None, error="missing"
        )
        db.add(
            DutySearchResult(
                run_id=run.id,
                candidate_id=cid,
                position=position,
                tier=a.tier,
                confidence=a.confidence,
                fit_score=fits.get(cid),
                from_goal_only=cid not in canonical_set,
                assessment=a.as_dict(),
            )
        )
    counts = {tier: sum(1 for c in order if tiers.get(c) == tier) for tier in TIERS}
    run.plan = plan.as_dict()
    run.metrics = {
        **(run.metrics or {}),
        "plan_ok": plan_ok,
        "canonical": len(canonical),
        "canonical_degraded": canonical_degraded,
        "goal_pool": len(goal_pool),
        "lists": list_sizes,
        "excluded_in_job": len(excluded),
        "judged": len(called),
        "judge_errors": sum(1 for a in called if a.error),
        "rejected_quotes": sum(a.rejected_quotes for a in called),
        "tiers": counts,
        "plan_seconds": round(t_plan, 1),
        "pool_seconds": round(t_pool, 1),
        "seconds": round(time.monotonic() - started, 1),
        "models": {"plan": model_for(PLAN_FEATURE), "judge": model_for(JUDGE_FEATURE)},
    }
    run.state = "complete"
    run.error_code = None
    run.completed_at = datetime.now(timezone.utc)
    run.lease_expires_at = None


class DutySearchFailed(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# --- kolejka ------------------------------------------------------------------

LEASE = timedelta(minutes=10)
MAX_CLAIMS = 3
RETENTION = timedelta(days=30)

_CLAIM_SQL = text(
    """
    UPDATE duty_search_runs
       SET state = 'running',
           lease_expires_at = now() + make_interval(secs => :lease),
           started_at = COALESCE(started_at, now()),
           metrics = jsonb_set(COALESCE(metrics, '{}'::jsonb), '{claims}',
                               to_jsonb(COALESCE((metrics->>'claims')::int, 0) + 1)),
           updated_at = now()
     WHERE id = (
            SELECT id FROM duty_search_runs
             WHERE state = 'queued'
                OR (state = 'running' AND lease_expires_at < now())
             ORDER BY created_at
             LIMIT 1
             FOR UPDATE SKIP LOCKED)
    RETURNING id, COALESCE((metrics->>'claims')::int, 1) AS claims
    """
)


async def claim_next(db: AsyncSession) -> Optional[tuple[str, int]]:
    row = (await db.execute(_CLAIM_SQL, {"lease": LEASE.total_seconds()})).first()
    await db.commit()
    return (row[0], int(row[1])) if row else None


async def fail_run(db: AsyncSession, run_id: str, code: str) -> None:
    run = await db.get(DutySearchRun, run_id)
    if run is None:
        return
    run.state = "failed"
    run.error_code = code[:60]
    run.completed_at = datetime.now(timezone.utc)
    run.lease_expires_at = None
    await db.commit()


async def purge_old(db: AsyncSession) -> int:
    cutoff = datetime.now(timezone.utc) - RETENTION
    result = await db.execute(
        delete(DutySearchRun).where(DutySearchRun.created_at < cutoff)
    )
    await db.commit()
    return int(result.rowcount or 0)


async def used_today(db: AsyncSession, user_id: int) -> int:
    from sqlalchemy import func

    from app.core.scheduling import business_today, local_day_start_utc

    start = local_day_start_utc(business_today())
    return int(
        await db.scalar(
            select(func.count(DutySearchRun.id)).where(
                DutySearchRun.created_by == user_id, DutySearchRun.created_at >= start
            )
        )
        or 0
    )


async def active_count(db: AsyncSession, user_id: int) -> int:
    from sqlalchemy import func

    return int(
        await db.scalar(
            select(func.count(DutySearchRun.id)).where(
                DutySearchRun.created_by == user_id,
                DutySearchRun.state.in_(("queued", "running")),
            )
        )
        or 0
    )
