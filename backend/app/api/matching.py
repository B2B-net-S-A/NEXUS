"""
AI Candidate Matching — dla danej oferty pracy, znajduje najlepiej pasujących kandydatów
używając semantycznego wyszukiwania Qdrant (Voyage AI) + fallback tag-based.

GET /api/jobs/{id}/ai-matches
"""

# UWAGA: bez `from __future__ import annotations` — PEP 563 zamienia
# adnotacje FastAPI w ForwardRef i wywala app.openapi() na Annotated
# guardach (CandidateSearchAccess); ten sam trap co slowapi #579.

import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateSearchAccess
from app.api.deps import get_db
from app.core.config import settings
from app.models.candidate import Candidate
from app.models.job import Job
from app.services.candidate_job_eligibility import Visibility
from app.services.dealbreaker_filters import (
    DealbreakerInputs,
    DealbreakerResult,
    apply_dealbreakers,
    dealbreaker_inputs_for_job,
    missing_must_skills,
    office_fit_status,
    rate_fit_status,
    resolve_job_budget_hourly,
)
from app.services.pipeline_eligibility import evaluate_candidates_for_job
from app.services.location_utils import (
    location_matches as _location_matches,
    location_tokens as _location_tokens,
)
from app.services.reranker_service import rerank_or_passthrough
from app.services.scoring_service import (
    _extract_skills_from_champion,
    candidate_skill_names,
    canonical_skill_names,
    job_explicit_must_skills,
    skill_present as _candidate_has_skill,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# UWAGA: `_normalize_skill` / `_extract_skills` / `_extract_tags` NIE są już
# źródłem chipów ✓/✗ — te czyta `candidate_skill_names` z silnika scoringu
# (patrz `_build_match_info`). Zostają, bo pokrywa je osobny test jednostkowy
# kształtów `skills` z Traffita; nie podłączaj ich z powrotem pod chipy.
def _normalize_skill(s) -> str:
    """Normalize a skill to lowercase string."""
    if isinstance(s, dict):
        return (s.get("name") or "").lower().strip()
    return str(s).lower().strip()


def _extract_skills(raw) -> list[str]:
    """Extract skill list from JSONB field (list of dicts or list of strings).

    Traffit-imported candidates often store ``skills`` as a JSON-encoded string
    (e.g. ``'["Java", "Spring Boot"]'``) rather than a real JSON array. Without
    decoding that first, a naive comma-split produces broken tokens like
    ``["java`` that never match required skills — so a candidate who clearly
    lists the skill would still show every requirement as a red ✗ gap. Decode
    the JSON string before falling back to comma splitting.
    """
    if not raw:
        return []
    if isinstance(raw, list):
        return [_normalize_skill(s) for s in raw if _normalize_skill(s)]
    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, list):
                return [_normalize_skill(s) for s in parsed if _normalize_skill(s)]
        return [s.strip().lower() for s in raw.split(",") if s.strip()]
    return []


def _extract_tags(raw) -> list[str]:
    """Extract tags list."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(t).lower().strip() for t in raw if t]
    if isinstance(raw, str):
        return [t.strip().lower() for t in raw.split(",") if t.strip()]
    return []


def _build_match_info(
    candidate: Candidate,
    required_skills: list[str],
    nice_skills: list[str] | None = None,
    score: float | None = None,
    *,
    inputs: DealbreakerInputs | None = None,
) -> dict:
    """Build the match result dict for a candidate.

    Chipy ✓/✗ czyta REGUŁA SILNIKA (`candidate_skill_names`), nie kolumna
    `candidate.skills`. Ta kolumna jest pusta dla 49 440 z 49 802 kandydatów na
    prodzie — technologie siedzą w `cv_extracted_data.traffit_technologie` albo
    w `raw_cv_text` — więc wiersz wyrankowany przez Qdranta na 0.94 renderował
    się CAŁY na czerwono: ranking czytał CV, a chipy pustą kolumnę. Ta sama
    funkcja rozwija też RODZINY aliasów z bazy (`MSSQL` = `SQL Server`,
    `K8s` = `Kubernetes`), których lokalna tabelka dwóch par nie znała.

    Wymagania porównujemy w przestrzeni kanonicznej, ale wyświetlamy ETYKIETĘ
    z treści rekrutacji — obok chipów stoi lista „Wymagane" zbudowana z tych
    samych surowych stringów i rozjazd nazw czytałby się jak inny wymóg.

    `inputs` (0278, opcjonalne — `None` gdy wołający nie ma jeszcze rubryk,
    np. stare testy jednostkowe) dokłada etykiety rubryk PO STRONIE WIERSZA:
    `rate_fit`/`office_fit`/`missing_must`. Świadomie OSOBNE od `gaps`:
    `gaps` liczy się względem WYŚWIETLANEGO `required_skills` (może pochodzić
    z regexa po prozie), `missing_must` — wyłącznie względem `inputs.must_skills`
    (kolumna/Tier 0 Championa, TA SAMA lista, którą egzekwuje twarda bramka).
    Gdy bramka nie ma czego wymagać (`inputs.must_skills` puste), `missing_must`
    jest zawsze `[]`, nawet jeśli `gaps` (z prozy) coś pokazuje.
    """
    all_candidate_skills = candidate_skill_names(candidate)

    req_labels: list[str] = []
    seen: set[str] = set()
    for raw in required_skills:
        if not raw:
            continue
        label = str(raw).lower().strip()
        if not label or label in seen:
            continue
        seen.add(label)
        req_labels.append(label)

    matching: list[str] = []
    gaps: list[str] = []
    for label in sorted(req_labels):
        canon = canonical_skill_names([label])
        # `_candidate_has_skill` zostaje jako druga warstwa tolerancji: gdy
        # taksonomia nie jest wczytana (`ALIAS_MAP` pusty), kanonizacja jest
        # tożsamością i tylko ona łapie `postgresql`/`postgres`.
        if _candidate_has_skill(canon[0] if canon else label, all_candidate_skills):
            matching.append(label)
        else:
            gaps.append(label)

    # Compute score if not provided by Qdrant
    if score is None:
        if req_labels:
            score = len(matching) / len(req_labels)
        else:
            # Fallback score based on profile completeness
            filled = sum(
                [
                    bool(candidate.skills),
                    bool(candidate.ai_summary),
                    bool(candidate.competence_category),
                    bool(candidate.email),
                ]
            )
            score = filled / 4

    # Nice-to-have coverage — TYLKO do wyświetlenia (dok „Dopasowanie",
    # kolumna „Mile widziane"). Świadomie NIE wchodzi do `score`: silnik liczy
    # wynik z wymagań must (i semantyki), a mile widziane to bonus, nie próg.
    # Etykiety już będące must są pomijane (`seen`), żeby ten sam skill nie
    # wyszedł raz jako must i raz jako nice.
    nice_labels: list[str] = []
    seen_nice: set[str] = set()
    for raw in nice_skills or []:
        if not raw:
            continue
        label = str(raw).lower().strip()
        if not label or label in seen_nice or label in seen:
            continue
        seen_nice.add(label)
        nice_labels.append(label)

    nice_matching: list[str] = []
    nice_gaps: list[str] = []
    for label in sorted(nice_labels):
        canon = canonical_skill_names([label])
        if _candidate_has_skill(canon[0] if canon else label, all_candidate_skills):
            nice_matching.append(label)
        else:
            nice_gaps.append(label)

    return {
        "candidate": {
            "id": candidate.id,
            "name": candidate.name,
            "lastname": candidate.lastname,
            "email": candidate.email,
            "phone": candidate.phone,
            "location": candidate.location,
            "status": candidate.status.value if candidate.status else None,
            "competence_category": candidate.competence_category,
            "tags": candidate.tags,
            "skills": candidate.skills,
            "ai_summary": candidate.ai_summary,
            "avatar_url": candidate.avatar_url,
            # Warsztat C2: stawka godzinowa (zderzana z budżetem oferty w doku),
            # aktualne stanowisko i firma (podtytuł wiersza „rola · firma ·
            # miasto"). Wszystkie z wczytanego wiersza — zero dodatkowych zapytań.
            # `getattr` z domyślną: realny ORM ma te pola, ale atrapy testowe
            # (SimpleNamespace) nie muszą — brak pola nie może wywalić rankingu.
            "expected_rate_hourly": (
                float(rate_hourly)
                if (rate_hourly := getattr(candidate, "expected_rate_hourly", None))
                is not None
                else None
            ),
            "current_title": getattr(candidate, "linkedin_current_title", None),
            "current_company": getattr(candidate, "linkedin_current_company", None),
        },
        "match_score": round(min(score, 1.0), 3),
        "matching_skills": matching,
        "gaps": gaps,
        "nice_matching": nice_matching,
        "nice_gaps": nice_gaps,
        # Rubryki 0278 — status dealbreakerów NA WIERSZU, żeby rekruter widział
        # „dlaczego" bez otwierania profilu. `rate_fit`/`office_fit` czytają
        # `expected_rate_hourly` (już w `candidate` wyżej) i deklarację dni w
        # biurze; sam status wystarcza w tej fali — liczba dni jest follow-upem.
        "rate_fit": rate_fit_status(candidate, inputs) if inputs else "unknown",
        "office_fit": office_fit_status(candidate, inputs) if inputs else "unknown",
        "missing_must": (
            missing_must_skills(candidate, inputs.must_skills) if inputs else []
        ),
    }


def _eligibility_annotation(decision) -> dict | None:
    """UI annotation for a candidate whose eligibility is not plainly clean.

    Returns ``None`` for a fully-eligible candidate with no secondary signal.
    Otherwise a dict the ranking row renders as a badge and uses to disable the
    assign/promote action when ``assignment_allowed`` is ``False``. ``reason``
    is the ready Polish label from ``_REASON_LABELS_PL``.
    """
    if decision is None:
        return None
    if decision.eligible and not decision.secondary_reasons:
        return None
    return {
        "reason_code": decision.reason_code.value,
        "reason": decision.reason,
        "assignment_allowed": decision.assignment_allowed,
        "visibility": decision.visibility.value,
        "severity": decision.severity.value,
        "secondary": [r.value for r in decision.secondary_reasons],
    }


async def _gate_and_dealbreakers(
    db: AsyncSession,
    *,
    job: Job,
    ordered: list[Candidate],
    now: datetime,
) -> tuple[list[Candidate], dict[int, dict], dict, int, DealbreakerInputs]:
    """Apply the eligibility gate and dealbreakers, preserving input order.

    Returns ``(kept, annotations_by_id, hidden_meta, eligibility_filtered, inputs)``.
    ``inputs`` (0278) is the SAME ``DealbreakerInputs`` used to filter this
    pool — returned so the row builder can compute ``rate_fit``/``office_fit``/
    ``missing_must`` against the identical rubric values the gate just applied,
    instead of re-resolving them (and risking a rare Champion-flag race where
    the two reads disagree).
      * ``hidden``-visibility candidates (global blacklist, already-in-job) are
        DROPPED — they must never surface in a job-scoped search.
      * ``warn``-visibility candidates (active client blacklist / NDA /
        competitor conflict, standing hiring-manager veto) are KEPT and
        annotated with the Polish reason and ``assignment_allowed=False`` so
        the row shows the block and the action is disabled.
      * soft ``visible`` warnings (current employment, candidate-excluded
        client) are kept and annotated too.
      * dealbreakers then hide over-budget and (for office/hybrid jobs)
        remote-only candidates; their counts come back in ``hidden_meta``.
        ``warn`` candidates are EXEMPT from dealbreakers — a compliance block
        must always surface with its reason, never be swallowed into a budget
        count, so they stay in the list even when over budget.
      * ``eligibility_filtered`` is the count of ``hidden``-visibility
        candidates dropped by the gate — the ONLY people the gate removes now
        that ``warn`` are surfaced. Published in ``meta`` for parity with Talent
        Radar (bliźniaczy ekran). Because ``warn`` (client blacklist / NDA /
        competitor / HM veto) are shown as rows, they are NOT counted here.

    PRODUKTOWY OVERRIDE (decyzja Artura, 2026-09). Do 2026-08-20 ta ścieżka
    wołała ``filter_eligible_candidates``, które WYCINAŁO wszystkich
    z ``assignment_allowed=False`` (w tym ``warn``), a licznik ukrytych szedł
    wyłącznie do logu — świadomie, jako ochrona przed „wyrocznią na NDA".
    Właściciel produktu zdecydował pokazywać zablokowanych z powodem wprost
    w rankingu; realizujemy to przez trójstanowe ``Visibility`` (``warn``
    widoczny z plakietką, ``hidden`` nadal ukryty), więc globalna blacklista
    i duplikaty pozostają niewidoczne. Dealbreaker ``hidden_meta`` (budżet /
    zdalnie) nie jest poufny per klient i moduł sam zwraca liczniki.
    """
    empty_meta = DealbreakerResult().hidden_meta()
    if not ordered:
        return [], {}, empty_meta, 0, dealbreaker_inputs_for_job(job)

    decisions = await evaluate_candidates_for_job(
        db, job=job, candidate_ids=[c.id for c in ordered], now=now
    )
    visible = [
        c
        for c in ordered
        if not (
            (d := decisions.get(c.id)) is not None and d.visibility == Visibility.hidden
        )
    ]
    eligibility_filtered = len(ordered) - len(visible)

    # Dealbreakery (budżet / zdalnie) NIE mogą wchłonąć kandydatów `warn`
    # (assignment_allowed=False: aktywny konflikt klienta / NDA / konkurent /
    # weto HM). Inaczej `warn` nad budżetem znika do `hidden_meta.over_budget`
    # BEZ plakietki compliance — rekruter widzi „ukryto N (budżet)" i nie wie,
    # że część z nich to blokada prawna. Celem decyzji było „pokaż zablokowanych
    # z powodem", więc `warn` zawsze wychodzi z anotacją; sufit budżetu ścina
    # wyłącznie kandydatów przypisywalnych (eligible + miękkie ostrzeżenia).
    warn_ids = {
        c.id
        for c in visible
        if (d := decisions.get(c.id)) is not None and not d.assignment_allowed
    }
    dealbreakable = [c for c in visible if c.id not in warn_ids]

    # Rubryki (0278): jedno rozwiązanie budżetu/must-have/dni/miasta biura dla
    # tej oferty, dzielone przez WSZYSTKIE pięć powierzchni rubryk. `wants_office`
    # wchodzi tu SZERZEJ niż dawny odczyt samej kolumny `remote_policy` — uwzględnia
    # też fallback do Championa (za CHAMPION_MATCH_SIGNALS_ENABLED) i dni w biurze
    # > 0, więc oferta z pustym `remote_policy`, ale wypełnionym Championem, też
    # poprawnie uzbraja auto-wykluczanie „tylko zdalnie".
    inputs = dealbreaker_inputs_for_job(job)
    db_res = apply_dealbreakers(
        dealbreakable,
        inputs=inputs,
        exclude_over_budget=True,
        exclude_remote_only=bool(inputs.wants_office),
    )
    kept_dealbreakable_ids = {c.id for c in db_res.kept}
    # Zachowaj oryginalną kolejność rankingu: `warn` zostają na swoich pozycjach,
    # nie-`warn` tylko jeśli przeszły dealbreakery.
    kept = [c for c in visible if c.id in warn_ids or c.id in kept_dealbreakable_ids]
    annotations: dict[int, dict] = {}
    for c in kept:
        ann = _eligibility_annotation(decisions.get(c.id))
        if ann is not None:
            annotations[c.id] = ann
    return kept, annotations, db_res.hidden_meta(), eligibility_filtered, inputs


def _build_job_query(job: Job) -> str:
    """Build a semantic query string from job fields."""
    parts: list[str] = []

    if job.title:
        parts.append(job.title)

    # Extract required skills from requirements text and JSONB
    if job.requirements:
        parts.append(job.requirements[:500])

    if job.description:
        parts.append(job.description[:300])

    # Add seniority hint
    title_lower = (job.title or "").lower()
    if "senior" in title_lower:
        parts.append("senior experienced engineer")
    elif "junior" in title_lower:
        parts.append("junior developer entry level")
    elif "lead" in title_lower or "architect" in title_lower:
        parts.append("lead architect technical leadership")
    elif "mid" in title_lower:
        parts.append("mid level developer")

    return " ".join(p for p in parts if p.strip())


def _parse_required_skills(job: Job) -> list[str]:
    """Extract required skills from job requirements text.

    Requirements are often a single comma-separated line
    (``"java, spring boot, hibernate, postgresql, oracle, kafka"``). Splitting
    only on newlines turned that whole line into one giant "skill" that no
    candidate could ever match — so every requirement rendered as one red ✗
    gap chip. Split on commas/semicolons too so each skill is matched
    individually. (``/`` is intentionally NOT a separator — it would break
    skills like ``CI/CD`` or ``TCP/IP``.)
    """
    skills: list[str] = []
    if not job.requirements:
        return skills
    seen: set[str] = set()
    for line in job.requirements.splitlines():
        line = line.strip().lstrip("•-–*·").strip()
        for raw in re.split(r"[,;]", line):
            skill = raw.strip().lower()
            if skill and 2 <= len(skill) <= 60 and skill not in seen:
                seen.add(skill)
                skills.append(skill)
    return skills[:20]


def _parse_nice_skills(job: Job) -> list[str]:
    """Nice-to-have skill labels from the job's ``nice_skills`` JSON.

    Unlike must-have skills (parsed from the free-text ``requirements`` line),
    nice-to-haves live in the structured ``nice_skills`` column written by the
    Champion sync / AI-criteria step. Shape is a list of ``{"name": str}`` dicts
    (with an optional ``level``); we defensively accept bare strings too. Labels
    are lowercased, deduped and capped — they drive the "Mile widziane" column
    and the dock's nice-coverage list, never the score.
    """
    raw = job.nice_skills
    if not raw or not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, dict):
            name = item.get("name")
        else:
            name = item
        if not name:
            continue
        label = str(name).lower().strip()
        if label and 2 <= len(label) <= 60 and label not in seen:
            seen.add(label)
            out.append(label)
    return out[:20]


def _required_skills_with_source(job: Job) -> tuple[list[str], str]:
    """Wymagania must dla wiersza + skąd faktycznie pochodzą (0278).

    `nice_skills` czyta `job.nice_skills` — kolumnę STRUKTURALNĄ — od dawna
    (`_parse_nice_skills`); `required_skills` do tej fali czytał wyłącznie
    regexem po `job.requirements`, czyli asymetrycznie WOLNIEJSZE i mniej
    pewne źródło niż to, co dealbreaker must-have już egzekwuje. Cztery źródła
    w kolejności pierwszeństwa, każde z WŁASNĄ etykietą (w odróżnieniu od
    `_score_skills`, gdzie warstwa PUNKTOWA zlewa Tier 0-3 Championa w jeden
    `must_source`):

      1. kolumna `job.must_skills` (jawna, wpisana wprost) → "must_skills"
      2. sekcja 3 Championa „Stack technologiczny" (Tier 0, też jawna, tylko
         inne miejsce zapisu) → "champion_stack"
      3. narracja/JD/tytuł Championa, WYWIEDZIONE regexem
         (`_extract_skills_from_champion` Tier 1-3) → "champion_narrative"
      4. regex po treści wymagań oferty (ostatni fallback sprzed Championa)
         → "requirements_text"
    """
    explicit = job_explicit_must_skills(job)
    if explicit:
        has_column = bool(canonical_skill_names(getattr(job, "must_skills", None)))
        return explicit, ("must_skills" if has_column else "champion_stack")
    narrative = [d["name"] for d in _extract_skills_from_champion(job)]
    if narrative:
        return narrative, "champion_narrative"
    return _parse_required_skills(job), "requirements_text"


async def _shared_engine_matches(
    db: AsyncSession,
    *,
    job: Job,
    ordered: list[Candidate],
    similarity_map: dict[int, float],
    semantic_unknown_ids: set[int],
    current_user,
    required_skills: list[str],
    nice_skills: list[str],
    rubric_inputs,
    elig_annotations: dict[int, dict],
    query_text: str,
) -> tuple[list[dict], bool]:
    """Policz wiersze `/ai-matches` KOMPOZYTEM 0–100, nie surowym kosinusem.

    Zwraca ``(matches, reranked)`` — wiersze posortowane malejąco po kompozycie,
    z ``match_score`` przeliczonym na skalę 0–1 (``total / 100``).

    DLACZEGO to w ogóle istnieje: zakładka rekrutacji renderuje dwie listy
    („Ranking" z `/recommendations` i „Shortlista" z `/ai-matches`) opisane tym
    samym słowem „dopasowanie", a liczone dwoma różnymi silnikami — jedna
    kompozytem ważonym profilem (60 pkt semantyki + umiejętności + lokalizacja
    + dostępność + sygnały Championa), druga surowym kosinusem z Qdranta.
    Kolejność potrafiła się różnić na tych samych danych, bez żadnego sygnału
    dla rekrutera, że ogląda dwie różne miary.

    Ta funkcja NIE zmienia kontraktu odpowiedzi: `match_score` zostaje na skali
    0–1, bo czytają go `MatchScoreBar` (×100), parametr `min_score` (ge=0, le=1)
    i zamrożony `JobShortlist.score_snapshot`. Zmienia się to, CO ta liczba
    znaczy — i dlatego siedzi za flagą do czasu A/B.

    Zapisu do cache'u nie ma, gdy któremuś kandydatowi nie zmierzono kosinusu
    (M3-CACHE-01): kompozyt z neutralną warstwą semantyczną nie może przeżyć
    awarii dostawcy jako wynik „świeży".
    """

    from app.api.recommendations import (
        _apply_historical_boost,
        _score_breakdown_payload,
    )
    from app.analytics.capabilities import AnalyticsCapability, user_has_capability
    from app.services.match_score_cache import bulk_get_or_compute
    from app.services.scoring_service import resolve_active_profile
    from app.services.similar_job_candidates import fetch_historical_boost_map

    profile = await resolve_active_profile(
        db, user_id=current_user.id, client_id=job.client_id
    )
    breakdowns = await bulk_get_or_compute(
        job,
        ordered,
        db,
        similarity_map=similarity_map,
        profile=profile,
        allow_cache_write=not semantic_unknown_ids,
        semantic_unavailable_ids=semantic_unknown_ids,
    )

    # Boost historyczny liczony świeżo per request — jak w `/recommendations`;
    # stan pipeline'u zmienia się za często, żeby dało się go unieważniać
    # w cache'u score'ów.
    try:
        boost_map = await fetch_historical_boost_map(db, job.id)
    except Exception as e:  # pragma: no cover — best-effort
        logger.warning("[AIMatch] historical_boost job=%s: %s", job.id, e)
        boost_map = {}
    _apply_historical_boost(breakdowns, boost_map)

    by_id = {c.id: c for c in ordered}
    scored = [(b, by_id[b.candidate_id]) for b in breakdowns if b.candidate_id in by_id]

    reranked = False
    top_n = int(getattr(settings, "AI_MATCHES_RERANK_TOP_N", 0) or 0)
    if top_n > 0 and len(scored) > 1:
        from app.services.embedding_service import _build_candidate_text

        head, tail = scored[:top_n], scored[top_n:]
        docs = [_build_candidate_text(c)[:4000] for _, c in head]
        pairs = await rerank_or_passthrough(query_text, docs, top_k=len(docs))
        if pairs and any(score != 1.0 for _, score in pairs):
            # Rerank przestawia KOLEJNOŚĆ czołówki; `match_score` zostaje
            # kompozytem, bo wynik rerankera żyje na innej skali niż próg.
            head = [head[idx] for idx, _ in pairs]
            scored = head + tail
            reranked = True

    include_finance = user_has_capability(
        current_user, AnalyticsCapability.VIEW_FINANCE
    )
    matches: list[dict] = []
    for b, c in scored:
        m = _build_match_info(
            c,
            required_skills,
            nice_skills=nice_skills,
            score=round(b.total / 100.0, 4),
            inputs=rubric_inputs,
        )
        m["eligibility"] = elig_annotations.get(c.id)
        m["total_score"] = round(b.total, 1)
        m["breakdown"] = _score_breakdown_payload(b, include_finance=include_finance)
        matches.append(m)
    return matches, reranked


@router.get("/jobs/{job_id}/ai-matches")
async def get_ai_matches(
    job_id: int,
    current_user: CandidateSearchAccess,
    # M3-COST-01: bounds są twarde — bez nich `limit` rozszerza effective_pool
    # (Qdrant fetch + liczba dokumentów rerankowanych przez Voyage) bez granic,
    # a odpowiedź zawiera PII kandydatów. 422 zanim jakikolwiek provider zostanie
    # dotknięty.
    min_score: float | None = Query(None, ge=0.0, le=1.0),
    limit: int | None = Query(None, ge=1, le=500),
    location: str | None = Query(None, max_length=120),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /api/jobs/{job_id}/ai-matches

    Returns **all** candidates that match the job (score >= ``min_score``),
    ranked best-first, using Qdrant semantic search + optional Voyage rerank.
    Falls back to tag-based matching if Qdrant is unavailable.

    Replaces the old hard top-10 behaviour: the result set is now bounded only
    by the match threshold and a safety cap (``MATCH_MAX_RESULTS``), so a job
    with 60 genuine fits shows all 60 instead of an arbitrary first 10.

    Query params (all optional; default to runtime-tunable settings):
        min_score: minimum match score (0-1) a candidate must reach to be shown.
        limit:     hard cap on the number of results (payload safety bound).
        location:  restrict results to candidates whose location matches this
                   place (city/region, substring-tolerant). Falls back to the
                   job's own ``location`` when omitted. Empty when neither is
                   set → no location filter (legacy behaviour preserved).
    """
    shared_engine = bool(getattr(settings, "AI_MATCHES_SHARED_ENGINE", False))
    max_results = limit if limit is not None else settings.MATCH_MAX_RESULTS
    # Próg mieszka na skali WYNIKU, a wynik zmienia znaczenie razem z silnikiem.
    # Pod wspólnym silnikiem `match_score` to kompozyt/100, więc domyślną
    # podłogą jest ta sama `RECOMMENDATION_MIN_SCORE`, którą stosuje bliźniacza
    # lista na tej samej zakładce; jawny `min_score` (0–1) nadal obowiązuje
    # i jest po prostu przeliczany. Bez tego domyślne 0.5 odsiałoby kompozyty
    # poniżej 50/100 — czyli WIĘKSZOŚĆ realnych dopasowań.
    if shared_engine:
        threshold = (
            min_score
            if min_score is not None
            else settings.RECOMMENDATION_MIN_SCORE / 100.0
        )
    else:
        threshold = min_score if min_score is not None else settings.AI_MATCH_MIN_SCORE
    # Retrieval/rerank pool is independent of the result cap: it bounds how many
    # candidates the (cost-bearing) reranker scores, while max_results bounds the
    # payload. Results are therefore effectively capped at the smaller of the two.
    pool_size = (
        settings.MATCH_POOL_SIZE if shared_engine else settings.AI_MATCH_POOL_SIZE
    )

    # Fetch job
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje")

    query_text = _build_job_query(job)
    required_skills, required_skills_source = _required_skills_with_source(job)
    nice_skills = _parse_nice_skills(job)
    # Rubryki 0278 strony oferty — jedna definicja dla obu gałęzi odpowiedzi
    # (semantycznej i tag-fallback), do klucza top-level `rubrics`.
    _rubric_inputs_preview = dealbreaker_inputs_for_job(job)
    job_rubrics = {
        "budget_hourly": resolve_job_budget_hourly(job),
        "onsite_days_per_week": getattr(job, "onsite_days_per_week", None),
        "office_location": getattr(job, "location", None),
        "must_skills": required_skills,
        # Które wymagania REALNIE bramkują, a które są punktem wymagań i zostają
        # wyłącznie sygnałem scoringowym. Bez tego bramka, która po cichu nie
        # działa, wygląda identycznie jak bramka, która nikogo nie odsiała —
        # a to dwie różne informacje dla Delivery Leada.
        "must_skills_gating": list(_rubric_inputs_preview.must_skills),
        "must_skills_ignored": list(_rubric_inputs_preview.must_skills_ignored),
    }

    # ── Location filter ──────────────────────────────────────────────────────
    # Explicit query param wins; otherwise fall back to the job's own location
    # (which is empty for ~99% of Traffit-imported jobs, hence the param).
    requested_location = (location or "").strip() or (job.location or "").strip()
    requested_tokens = _location_tokens(requested_location)
    location_active = bool(requested_tokens)
    # When filtering by location, widen the retrieval pool so the located subset
    # isn't starved by the default top-100 semantic cut (only ~17% of candidates
    # have any location at all). Plain (no-location) requests keep the cheaper
    # default pool.
    effective_pool = max(pool_size, max_results) if location_active else pool_size

    # Import lokalny (cykl importów), ale POZA `try`: nieudany import to błąd
    # kodu, nie degradacja providera — 500 jest tu poprawną odpowiedzią, a
    # trzymanie go pod `try` zostawiało `_build_candidate_text` „possibly
    # unbound" dla każdego, kto puści tu mypy.
    from app.services.canonical_text import build_job_query_variants
    from app.services.embedding_service import (
        _build_candidate_text,
        SemanticSearchUnavailable,
    )
    from app.services.hybrid_search import build_job_bm25_query, build_job_must_groups
    from app.services.retrieval_pool import retrieve_candidate_pool

    if shared_engine:
        # Ten sam dokument zapytania, którym pulę pobiera pozostałych pięć
        # powierzchni. Inny tekst = inna pula = „wspólny silnik", który i tak
        # ogląda innych ludzi niż lista obok.
        from app.services.embedding_service import _build_job_text

        query_text = _build_job_text(job)

    # Pull a wide pool so "show all who match" isn't artificially capped by
    # retrieval. The threshold filter below — not a fixed top-K — decides
    # who is shown. Rerank cost scales ~linearly with pool size, hence the
    # tunable AI_MATCH_POOL_SIZE.
    rerank_enabled = bool(getattr(settings, "RERANKER_ENABLED", False))

    # ── Attempt Qdrant semantic search (+ optional Voyage rerank) ────────────
    # `try` obejmuje WYŁĄCZNIE wywołanie sieciowe. Do 2026-08-20 obejmował całą
    # gałąź semantyczną RAZEM z bramką dopuszczalności — więc wyjątek z samej
    # bramki (padnięty DB na `candidate_conflicts`, timeout, `AttributeError`
    # na niekompletnym `job`) był łapany tutaj i spychał request do gałęzi
    # tag-fallback, która bramki nie miała. Bramka bezpieczeństwa, której własna
    # awaria omijała bramkę bezpieczeństwa.
    #
    # Po zwężeniu awaria bramki kończy się 500 — to jest CEL, nie efekt uboczny:
    # fail-closed w regule zawierania. Strona oferty ma gałąź `isError`
    # (`app/jobs/[id]/page.tsx`), więc wyrenderuje się jako awaria, nie jako zero.
    #
    # `raise_on_error=True` jest tu warunkiem koniecznym, nie ozdobą: domyślny
    # kontrakt `search_candidates_semantic` POŁYKA awarię providera i zwraca
    # `[]`, więc padnięty Voyage/Qdrant był nieodróżnialny od zdrowego zapytania,
    # które po prostu nic nie znalazło. Bez tego rozróżnienia `meta.degraded`
    # niżej byłoby zgadywaniem.
    hits: list = []
    semantic_unavailable = False
    try:
        # Pula przez FASADĘ, nie przez `search_candidates_semantic` wprost.
        # Do 09.2026 ta powierzchnia — jedyna, którą rekruter naprawdę oglada
        # na stronie rekrutacji — była JEDYNĄ z sześciu poza fasadą, więc każda
        # dźwignia retrievalu (hybryda, multi-query, pula SQL-first po must-have)
        # działała wszędzie indziej, tylko nie tutaj. Objaw byłby cichy: A/B na
        # zamrożonym zbiorze ofert pokazywałby wpływ strategii, a ekran
        # produktu i tak jechałby na starej puli.
        #
        # Przy flagach OFF fasada deleguje do `search_candidates_semantic`
        # wywołanie za wywołanie (`retrieval_pool.py`), więc ten commit sam
        # w sobie nie zmienia odpowiedzi.
        hits = await retrieve_candidate_pool(
            db,
            query_text,
            top_k=effective_pool,
            raise_on_error=True,
            query_variants=build_job_query_variants(job, query_text),
            bm25_query=build_job_bm25_query(job),
            must_groups=build_job_must_groups(job),
        )
    except SemanticSearchUnavailable as e:
        semantic_unavailable = True
        logger.warning(
            f"[AIMatch] semantic retrieval unavailable for job {job_id}: {e} — falling back to tag-based"
        )
    except Exception as e:
        semantic_unavailable = True
        logger.warning(
            f"[AIMatch] Qdrant search failed for job {job_id}: {e} — falling back to tag-based"
        )

    # Wiersze, dla których kosinusu NIE zmierzono (`semantic_unknown` — padła
    # dosypka po udanym BM25 albo kandydat nie ma wektora), niosą `score` 0.0.
    # To jest „nie wiem", nie „zmierzono zero", a ta gałąź porównuje
    # `match_score` WPROST z progiem — zostawione, weszłyby do odpowiedzi jako
    # najsłabsze dopasowania puli, czyli awaria dostawcy podszyłaby się pod
    # zmierzony brak dopasowania. Odrzucamy je i mówimy to w logu.
    semantic_unknown_ids = {
        h["candidate_id"] for h in hits if h.get("semantic_unknown")
    }
    if semantic_unknown_ids:
        logger.warning(
            "[AIMatch] job %s: %s wierszy bez zmierzonego kosinusu",
            job_id,
            len(semantic_unknown_ids),
        )
        if not shared_engine:
            # Stara ścieżka porównuje kosinus WPROST z progiem, więc 0.0 jako
            # „nie wiem" udawałoby zmierzony brak dopasowania. Wspólny silnik
            # takich wierszy nie odrzuca: `bulk_get_or_compute` zna stan „brak
            # pomiaru" (`semantic_unavailable_ids`) i liczy warstwę semantyczną
            # neutralnie zamiast obwiniać profil kandydata.
            hits = [h for h in hits if h["candidate_id"] not in semantic_unknown_ids]

    if hits:
        candidate_ids = [h["candidate_id"] for h in hits]
        qdrant_scores = {h["candidate_id"]: h["score"] for h in hits}

        cand_result = await db.execute(
            select(Candidate).where(Candidate.id.in_(candidate_ids))
        )
        candidates_by_id = {c.id: c for c in cand_result.scalars().all()}

        # Preserve Qdrant ranking order while dropping anyone the recruiter
        # could not actually assign.
        #
        # This used to check the GLOBAL blacklist only, while the sibling
        # `/recommendations` ran the full eligibility filter. The difference
        # is not cosmetic: an active client blacklist, an NDA, a competitor
        # conflict and a standing hiring-manager veto all passed straight
        # through to a list the job page renders with an "add to pipeline"
        # button next to every row. Same engine, same page, two different
        # containment rules — and the weaker one was the default view.
        ordered: list[Candidate] = [
            c for cid in candidate_ids if (c := candidates_by_id.get(cid))
        ]
        (
            ordered,
            elig_annotations,
            hidden_meta,
            eligibility_filtered,
            rubric_inputs,
        ) = await _gate_and_dealbreakers(
            db, job=job, ordered=ordered, now=datetime.now(timezone.utc)
        )

        search_type = "semantic"

        if shared_engine:
            # `search_type` MUSI zaczynać się od "semantic" — front uznaje
            # odpowiedź za zdegradowaną, gdy tak nie jest (`page.tsx`).
            matches, reranked = await _shared_engine_matches(
                db,
                job=job,
                ordered=ordered,
                similarity_map={
                    cid: sc
                    for cid, sc in qdrant_scores.items()
                    if cid not in semantic_unknown_ids
                },
                semantic_unknown_ids=semantic_unknown_ids,
                current_user=current_user,
                required_skills=required_skills,
                nice_skills=nice_skills,
                rubric_inputs=rubric_inputs,
                elig_annotations=elig_annotations,
                query_text=query_text,
            )
            search_type = "semantic+composite" + ("+rerank" if reranked else "")
            if location_active:
                matches = [
                    m
                    for m in matches
                    if _location_matches(requested_tokens, m["candidate"]["location"])
                ]
            matches = [m for m in matches if m["match_score"] >= threshold][
                :max_results
            ]
            degraded = bool(semantic_unknown_ids)
            return {
                "job_id": job_id,
                "job_title": job.title,
                "required_skills": required_skills,
                "required_skills_source": required_skills_source,
                "nice_skills": nice_skills,
                "search_type": search_type,
                "min_score": round(threshold, 3),
                "location_filter": requested_location if location_active else None,
                "matches": matches,
                "rubrics": job_rubrics,
                "meta": {
                    "mode": search_type,
                    "degraded": degraded,
                    "reason": "semantic_unavailable" if degraded else None,
                    "hidden": hidden_meta,
                    "eligibility_filtered": eligibility_filtered,
                    "budget_hourly": resolve_job_budget_hourly(job),
                },
            }

        scores_by_idx: dict[int, float] = {
            i: qdrant_scores.get(c.id, 0.0) for i, c in enumerate(ordered)
        }

        if rerank_enabled and ordered:
            docs = [_build_candidate_text(c)[:4000] for c in ordered]
            # Rerank the whole pool (top_k=len(docs)) so threshold filtering
            # below sees a fully-ranked list, not a pre-trimmed one.
            pairs = await rerank_or_passthrough(query_text, docs, top_k=len(docs))
            if pairs and any(score != 1.0 for _, score in pairs):
                # Real rerank result (passthrough returns score=1.0 for all).
                # Reorder per rerank, scores aligned to new positions.
                search_type = "semantic+rerank"
                ordered = [ordered[idx] for idx, _ in pairs]
                scores_by_idx = {i: score for i, (_, score) in enumerate(pairs)}
            # Passthrough / failure → keep Qdrant order + scores as-is.

        matches = []
        for i, c in enumerate(ordered):
            m = _build_match_info(
                c,
                required_skills,
                nice_skills=nice_skills,
                score=scores_by_idx.get(i, 0.0),
                inputs=rubric_inputs,
            )
            m["eligibility"] = elig_annotations.get(c.id)
            matches.append(m)
        # Location filter (when active): keep only candidates whose location
        # matches the request, preserving the semantic ranking order.
        if location_active:
            matches = [
                m
                for m in matches
                if _location_matches(requested_tokens, m["candidate"]["location"])
            ]
        # Threshold filter: show everyone who fits, capped for payload safety.
        matches = [m for m in matches if m["match_score"] >= threshold][:max_results]

        return {
            "job_id": job_id,
            "job_title": job.title,
            "required_skills": required_skills,
            "required_skills_source": required_skills_source,
            "nice_skills": nice_skills,
            "search_type": search_type,
            "min_score": round(threshold, 3),
            "location_filter": requested_location if location_active else None,
            "matches": matches,
            "rubrics": job_rubrics,
            "meta": {
                "mode": search_type,
                "degraded": False,
                "reason": None,
                "hidden": hidden_meta,
                "eligibility_filtered": eligibility_filtered,
                # Operational (candidate) budget the gate enforces — the C2
                # context bar shows it and the dock compares each rate to it,
                # so "stawka vs budżet" reads the SAME ceiling as "ukryto:
                # over_budget". Null when the job has no hourly budget.
                "budget_hourly": resolve_job_budget_hourly(job),
            },
        }

    # ── Fallback: tag-based matching ─────────────────────────────────────────
    logger.info(f"[AIMatch] Using tag-based fallback for job {job_id}")

    # Grab all active candidates (bounded by the retrieval pool for performance)
    all_result = await db.execute(
        select(Candidate).where(Candidate.status != "blacklisted").limit(effective_pool)
    )
    all_candidates = list(all_result.scalars().all())

    # Ta sama reguła zawierania co w gałęzi semantycznej (`_gate_and_dealbreakers`):
    # `hidden` (globalna blacklista, duplikat) wypada, `warn` (blacklista klienta /
    # NDA / konkurent / weto HM) wraca z powodem i zablokowaną akcją, a dealbreakery
    # (budżet / zdalnie) liczą się do `hidden_meta`. Wchodzi się tu TRZEMA drogami:
    # wyjątek z retrievalu, wyjątek z gałęzi semantycznej — i CICHO, gdy Qdrant
    # zwróci pustą listę. `status != "blacklisted"` w SQL zostaje jako tani
    # prefiltr (globalna blacklista i tak jest `hidden`).
    (
        all_candidates,
        elig_annotations,
        hidden_meta,
        eligibility_filtered,
        rubric_inputs,
    ) = await _gate_and_dealbreakers(
        db, job=job, ordered=all_candidates, now=datetime.now(timezone.utc)
    )
    # Log zostaje (P-B): rozstrzyga „lista jest podejrzanie krótka" bez zgadywania,
    # także gdy front licznika nie pokaże. Liczy WYŁĄCZNIE warstwę `hidden`
    # (globalna blacklista / duplikat) — `warn` są teraz widoczni jako wiersze.
    if eligibility_filtered:
        logger.info(
            "[AIMatch] tag-fallback job=%s: bramka ukryła %s (globalna blacklista / duplikat)",
            job_id,
            eligibility_filtered,
        )

    matches = []
    for c in all_candidates:
        # Location filter (when active): skip non-matching candidates up front.
        if location_active and not _location_matches(requested_tokens, c.location):
            continue
        match = _build_match_info(
            c,
            required_skills,
            nice_skills=nice_skills,
            score=None,
            inputs=rubric_inputs,
        )
        match["eligibility"] = elig_annotations.get(c.id)
        # No required_skills → score is a profile-completeness proxy; keep the
        # threshold floor so junk profiles don't surface as "matches".
        if match["match_score"] >= threshold:
            matches.append(match)

    # Sort by score desc, show all who clear the threshold (capped).
    matches.sort(key=lambda x: x["match_score"], reverse=True)
    matches = matches[:max_results]

    # `meta.degraded` — strona rekrutacji ma gotowy baner „wyszukiwanie
    # semantyczne niedostępne" wpięty dokładnie w ten klucz, tylko backend go
    # nigdy nie wypełniał: awaria Qdranta/Voyage renderowała się albo jako
    # nieoznaczona lista dopasowań (rekruter dodawał z niej ludzi do pipeline'u
    # i wysyłał CV do klienta), albo jako „Brak pasujących kandydatów w bazie".
    # Ta gałąź jest zdegradowana ZAWSZE — także gdy Qdrant odpowiedział zdrowo,
    # ale pusto: ranking po pokryciu tagów to nie jest ranking semantyczny,
    # a jedyne, co odróżnia te dwa przypadki, to `reason`.
    return {
        "job_id": job_id,
        "job_title": job.title,
        "required_skills": required_skills,
        "required_skills_source": required_skills_source,
        "nice_skills": nice_skills,
        "search_type": "tag_fallback",
        "min_score": round(threshold, 3),
        "location_filter": requested_location if location_active else None,
        "matches": matches,
        "rubrics": job_rubrics,
        "meta": {
            "mode": "tag_fallback",
            "degraded": True,
            "reason": (
                "semantic_unavailable" if semantic_unavailable else "no_semantic_hits"
            ),
            "hidden": hidden_meta,
            "eligibility_filtered": eligibility_filtered,
            "budget_hourly": resolve_job_budget_hourly(job),
        },
    }
