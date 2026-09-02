"""Pydantic schemas for the Champion Profile.

Mirrors the Delivery Lead's "Profil Championa" Word template, restructured
in 09.2026 to seven sections: podstawowe informacje, co wpisać (search),
stack technologiczny, o projekcie, pytania screeningowe, o kliencie,
dokumenty. Verification, briefing and recommended searches sit OUTSIDE those
seven — they are server-stamped machinery, not fields a Delivery Lead fills.

Stored as JSONB inside `jobs.champion_profile` so we avoid a dedicated table
for a document-shaped payload that only the Delivery Lead owns. Because it is
schemaless storage, the pre-09.2026 shape is migrated ON READ rather than by a
one-shot data migration: 949 rows carry the old keys, and a JSONB rewrite is
reversible only from a backup we do not have off-site.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ── Building blocks: the seven sections ──────────────────────────────────────
#
# The template is deliberately SHORT. Everything here earns its place by being
# read by something downstream — scoring, retrieval, the CV generator or the
# recruiter's screening call. Prose that no consumer reads was the bulk of the
# old profile and is why Delivery Leads described 80% of it as noise.


class ChampionBasics(BaseModel):
    """1. Podstawowe informacje — the hard facts of the engagement.

    Everything the Word parser already extracts lives here. Before this shape
    existed these keys sat at the TOP LEVEL of the JSONB while ``ChampionProfile``
    knew nothing about them, so Pydantic's default ``extra="ignore"`` silently
    dropped all of them the first time a Delivery Lead pressed Save on an
    ingested profile — including ``rate_value`` (the hard rate ceiling in
    ``dealbreaker_filters``) and ``seniority_min_years`` (the measured seniority
    penalty). Giving them a home in the schema is what stops that.
    """

    role_name: Optional[str] = Field(default=None, max_length=255)
    seniority_min_years: Optional[int] = Field(default=None, ge=0, le=60)
    # PLN/h FOR THE CANDIDATE, by definition of the source document. Read by
    # `scoring_service.get_champion_hourly_rate` → `dealbreaker_filters`.
    rate_value: Optional[float] = Field(default=None, ge=0)
    rate_raw: Optional[str] = Field(default=None, max_length=255)
    work_mode: Optional[str] = Field(default=None, max_length=50)
    onsite_days_per_week: Optional[int] = Field(default=None, ge=0, le=7)
    # LOKALIZACJA BIURA — czyli gdzie jest praca, nie gdzie mieszka kandydat.
    #
    # Nazwa klucza kłamie i zostaje taka celowo: `scoring_service` porównuje tę
    # wartość z miastem KANDYDATA (`_score_location`), więc od zawsze znaczyła
    # „dokąd trzeba dojechać". Przemianowanie klucza to migracja 949 profili
    # i ośmiu konsumentów po to, żeby użytkownik zobaczył dokładnie to samo —
    # poprawione są więc ETYKIETY (wzór Word, edytor), nie kształt danych.
    candidate_location_pref: Optional[str] = Field(default=None, max_length=255)
    # JĘZYK PRACY wymagany od kandydata (np. „PL, EN B2+"). NIE jest to język,
    # w którym ma być napisane CV — ten stoi w `ClientCvRule.cv_language`, jest
    # per klient i to jego słucha generator. Dwa różne fakty, dwa różne pola;
    # zlanie ich dałoby drugie źródło prawdy obok tego, które naprawdę działa.
    language: Optional[str] = Field(default=None, max_length=50)
    start_date: Optional[str] = Field(default=None, max_length=100)
    # Termin na dostarczenie kandydatów DO TEJ oferty. Osobno od KPI klienta
    # („mamy 5 dni roboczych"), bo tamto opisuje tempo, a to konkretną datę.
    deadline: Optional[str] = Field(default=None, max_length=100)
    contract_length: Optional[str] = Field(default=None, max_length=255)


class ChampionSearch(BaseModel):
    """2. Co wpisać (search) — literally what the recruiter pastes into search.

    Not "sourcing strategy" any more. The old block asked for a plan (channels,
    a narrative, a to-do); this one asks for the query. That is the form the
    downstream machinery already consumes: `recommended_searches` turns exactly
    these strings into a `CandidateSearchRequest`.

    ``sources`` (the old channel checkboxes) survives for data safety — legacy
    profiles carry it — but has no editor UI. A recruiter knows which channels
    exist; recording it per job was pure ceremony.
    """

    keywords: str = ""
    target_companies: str = ""
    # Hard exclusions. Kept on the SEARCH side rather than with screening
    # because they decide who never shows up, not who fails a conversation.
    disqualifiers: List[str] = Field(default_factory=list)
    notes: str = ""
    sources: List[Literal["internal_base", "linkedin", "ad", "referrals", "other"]] = (
        Field(default_factory=list)
    )


class StackItem(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ChampionStack(BaseModel):
    """3. Stack technologiczny — STRUCTURED, and this is the whole point.

    Until now the only machine-readable requirement signal for a champion job
    came from `_extract_skills_from_champion`, which regex-scans the narrative
    prose for known aliases. That is why cutting "O projekcie" down to two
    sentences would have been a retrieval regression on its own: less prose
    meant fewer skills found.

    A structured list removes the guessing entirely, and `PUT .../champion-profile`
    syncs it into ``Job.must_skills`` / ``Job.nice_skills`` — the columns that
    are empty on ~88% of production jobs and that scoring, `requirement_map`
    (the interactive-CV tiles) and the search filters all prefer when present.
    """

    must: List[StackItem] = Field(default_factory=list)
    nice: List[StackItem] = Field(default_factory=list)
    # For the nuance a list cannot carry: "Java 17+, Java 8 nie interesuje".
    notes: str = ""

    def names(self) -> List[str]:
        return [item.name for item in (*self.must, *self.nice)]


class ChampionProject(BaseModel):
    """4. O projekcie — two sentences, merged with the duties.

    ``about`` is capped by INSTRUCTION, not by a validator: a hard length limit
    would reject an ingested legacy profile whose ``about`` is four sentences
    long, and rejecting stored data on read turns an over-long paragraph into a
    500. The cap lives in the parser prompt and the editor hint instead.
    """

    about: str = ""
    responsibilities: str = ""


class ScreeningQuestion(BaseModel):
    """One DL-authored screening question with grading hints."""

    id: str = Field(min_length=1, max_length=40)
    question: str = Field(min_length=1)
    ideal_answer: str = ""
    deal_breaker: str = ""


class ChampionClient(BaseModel):
    """6. O kliencie — everything role-independent about who we are staffing.

    Absorbs three blocks that used to float at the top level of the profile
    (``internal_consultant_insight``, ``historical_client_questions``,
    ``client_standards``) plus ``project_context.selling_points``. They are all
    answers to the same question — "what do I need to know about this client
    before I talk to a candidate?" — and splitting them across four places is
    what made the profile feel long without being informative.
    """

    about: str = ""
    selling_points: str = ""
    # From `client_standards` in the parsed document.
    priority_rules: str = ""
    offlimit: Optional[bool] = None
    contract_type: Optional[str] = Field(default=None, max_length=120)
    cv_language: Optional[str] = Field(default=None, max_length=50)
    # Ex-`internal_consultant_insight`: what our person already at the client says.
    consultant_insight: str = ""
    # Ex-`historical_client_questions`: what this client has asked before.
    historical_questions: str = ""
    sectors: List[str] = Field(default_factory=list)


class ChampionDocument(BaseModel):
    """7. Dokumenty — name + link, nothing uploaded.

    Deliberately a pointer, not storage: these documents already live on
    SharePoint, and copying them into NEXUS would create a second copy to keep
    in sync plus a personal-data retention path for files we do not own.
    """

    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2000)


# ── Legacy shapes (read-only compatibility) ──────────────────────────────────
#
# 949 production jobs carry a champion profile written in the pre-agenda shape
# by the August import (1095 files, parser v3). These classes are what that
# shape looked like; they exist so the migration in `ChampionProfile` has names
# to refer to and so older imports keep resolving. Nothing writes them.


class ChampionProjectContext(BaseModel):
    """LEGACY — superseded by `ChampionProject` + `ChampionClient.selling_points`."""

    about: str = ""
    responsibilities: str = ""
    selling_points: str = ""


class SourcingStrategy(BaseModel):
    """LEGACY — superseded by `ChampionSearch`."""

    sources: List[Literal["internal_base", "linkedin", "ad", "referrals", "other"]] = (
        Field(default_factory=list)
    )
    keywords: str = ""
    target_companies: str = ""
    notes: str = ""


# ── Two-sided verification ───────────────────────────────────────────────────
#
# The Champion Profile must not be a transcription of the client's request.
# The Delivery Lead verifies it from two sides: a conversation with the client
# (what do they REALLY need vs. what they wrote) and a conversation with one of
# our consultants already working at that client (what the day-to-day actually
# looks like). Soft signal only — publishing a job is never blocked on it.
#
# These blocks are server-stamped via POST /jobs/{id}/champion-profile/
# verification; a regular profile PUT preserves whatever is stored so the
# client cannot forge or wipe them.

VerificationMethod = Literal["call", "meeting", "email", "other"]


class ClientVerification(BaseModel):
    """Outcome of the DL ↔ client conversation about the request."""

    status: Literal["pending", "verified"] = "pending"
    verified_by_id: Optional[int] = None
    verified_by_name: Optional[str] = None
    verified_at: Optional[datetime] = None
    method: Optional[VerificationMethod] = None
    # Either the DL articulates what changed vs. the original request…
    key_corrections: str = ""
    # …or explicitly confirms the request was accurate as written.
    confirmed_as_is: bool = False


class ConsultantVerification(BaseModel):
    """Outcome of the DL ↔ our-consultant-at-the-client conversation."""

    status: Literal["pending", "verified", "skipped"] = "pending"
    verified_by_id: Optional[int] = None
    verified_by_name: Optional[str] = None
    verified_at: Optional[datetime] = None
    consultant_candidate_id: Optional[int] = None
    consultant_name: Optional[str] = None
    insights: str = ""
    # `skipped` escape hatch — no consultant placed at this client yet.
    skip_reason: str = ""


class ChampionVerification(BaseModel):
    client: ClientVerification = ClientVerification()
    consultant: ConsultantVerification = ConsultantVerification()

    def summary(self) -> Literal["none", "partial", "full"]:
        done = [
            self.client.status == "verified",
            self.consultant.status in ("verified", "skipped"),
        ]
        if all(done):
            return "full"
        if any(done):
            return "partial"
        return "none"


class ClientVerificationIn(BaseModel):
    """Payload the DL submits after talking to the client."""

    method: VerificationMethod = "call"
    key_corrections: str = ""
    confirmed_as_is: bool = False


class ConsultantVerificationIn(BaseModel):
    """Payload the DL submits after talking to our consultant (or skipping)."""

    consultant_candidate_id: Optional[int] = None
    consultant_name: str = ""
    insights: str = ""
    skipped: bool = False
    skip_reason: str = ""


class ChampionVerificationRequest(BaseModel):
    side: Literal["client", "consultant"]
    reset: bool = False
    client: Optional[ClientVerificationIn] = None
    consultant: Optional[ConsultantVerificationIn] = None


# ── DL briefing (breakout session) ───────────────────────────────────────────
#
# After the profile is verified, the DL records a short breakout session
# (Fireflies) explaining the role in their own words. The meeting Note is
# attached here so recruiters entering the job can listen to the audio and
# read the transcript instead of decoding a dry written profile. Server-
# stamped like `verification` — a profile PUT preserves the stored block.


class ChampionBriefing(BaseModel):
    status: Literal["pending", "attached"] = "pending"
    note_id: Optional[int] = None
    title: Optional[str] = None
    audio_storage_key: Optional[str] = None
    attached_by_id: Optional[int] = None
    attached_by_name: Optional[str] = None
    attached_at: Optional[datetime] = None


class ChampionBriefingRequest(BaseModel):
    note_id: int
    # Run LLM enrichment (cross-check briefing vs. profile) after attaching.
    enrich: bool = True


# ── Recommended searches (AI-proposed, DL-approved) ──────────────────────────
#
# The LLM turns the Champion Profile into 1-3 concrete candidate searches in
# the exact shape of `CandidateSearchRequest` (the job's "Wyszukaj manualnie"
# tab). The DL reviews each proposal (live result count, preview), approves or
# rejects; approval materialises a `SavedSearch` pinned to the job and shared
# with the team, so any recruiter entering the job activates it in one click.
# Strict whitelisted params — the LLM cannot invent filters we don't have.


class RecommendedSearchParams(BaseModel):
    """Whitelisted subset of CandidateSearchRequest the LLM may emit.

    Tolerant on purpose (Pydantic's default ``extra="ignore"``): this shape is
    also what gets read back out of ``jobs.champion_profile`` JSONB, where
    proposals written by older prompt versions still carry fields that have
    since been dropped. Validation of *fresh* LLM output goes through
    :class:`RecommendedSearchParamsIn`, which forbids extras so a hallucinated
    filter fails loudly instead of being silently discarded.

    List caps mirror ``CandidateSearchRequest`` exactly. Without them the model
    could emit 25 keywords, the proposal would store fine, and the recruiter
    would get a 422 the moment they clicked it — an error surfacing three steps
    away from its cause.
    """

    # Free-text query. Together with `search_mode="hybrid"` this is what lets a
    # recommended search reach the semantic index at all: `/api/search/candidates`
    # only takes the BM25+dense+rerank path when BOTH are set, and the default
    # is "boolean". Without these two fields the one feature that turns a
    # Champion into a candidate search was, by construction, the only surface
    # that never touched the 47 921 vectors we maintain for exactly this.
    q: Optional[str] = Field(default=None, max_length=500)
    search_mode: Literal["boolean", "hybrid"] = "hybrid"

    q_all: List[str] = Field(default_factory=list, max_length=20)
    # OR-groups that AND together: [["React","TS"],["Java"]] = (React OR TS) AND Java
    q_any_groups: List[List[str]] = Field(default_factory=list, max_length=10)
    q_none: List[str] = Field(default_factory=list, max_length=20)
    skills_must: List[str] = Field(default_factory=list, max_length=20)
    skills_any: List[str] = Field(default_factory=list, max_length=20)
    skills_none: List[str] = Field(default_factory=list, max_length=20)
    location_cities: List[str] = Field(default_factory=list, max_length=20)

    def is_empty(self) -> bool:
        return not any(
            [
                (self.q or "").strip(),
                self.q_all,
                self.q_any_groups,
                self.q_none,
                self.skills_must,
                self.skills_any,
                self.skills_none,
                self.location_cities,
            ]
        )


class RecommendedSearchParamsIn(RecommendedSearchParams):
    """Same shape, but for validating what the LLM just produced.

    ``extra="forbid"`` so an invented filter is a loud parse failure instead of
    a field quietly dropped on the floor. The generator previously swallowed
    every validation error and skipped the proposal, so a prompt that started
    hallucinating parameters looked exactly like a prompt that returned fewer
    strategies — indistinguishable from outside, and silent for as long as it
    took someone to notice the count.
    """

    model_config = ConfigDict(extra="forbid")


class RecommendedSearch(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=100)
    rationale: str = ""
    params: RecommendedSearchParams = RecommendedSearchParams()
    status: Literal["proposed", "approved", "rejected"] = "proposed"
    saved_search_id: Optional[int] = None
    # How many candidates this strategy actually matched at generation time.
    # The module docstring above already promised the DL a "live result count";
    # counting it BEFORE the proposal is stored is what makes a strategy that
    # returns nobody visible as such, instead of as an empty list the recruiter
    # discovers three clicks later and reads as "we have no such people".
    # ``None`` = the count could not be taken (never "zero").
    estimated_results: Optional[int] = None
    generated_at: Optional[datetime] = None
    decided_by_id: Optional[int] = None
    decided_by_name: Optional[str] = None
    decided_at: Optional[datetime] = None


class RecommendedSearchDecision(BaseModel):
    search_id: str
    action: Literal["approve", "reject", "reset"]


# ── Full profile ─────────────────────────────────────────────────────────────


class ChampionProfile(BaseModel):
    """The seven-section Champion Profile.

    Section order matches the Word template and the editor so a Delivery Lead
    reading one is reading the other:

        1. basics             — podstawowe informacje
        2. search             — co wpisać (search)
        3. stack              — stack technologiczny
        4. project            — o projekcie (2 zdania + obowiązki)
        5. screening_questions— pytania screeningowe
        6. client             — o kliencie
        7. documents          — dokumenty

    ``verification``, ``briefing`` and ``recommended_searches`` are NOT sections.
    They are server-stamped through dedicated endpoints and a plain profile PUT
    must never be able to forge or wipe them.
    """

    # ── the seven ──
    basics: ChampionBasics = ChampionBasics()
    search: ChampionSearch = ChampionSearch()
    stack: ChampionStack = ChampionStack()
    project: ChampionProject = ChampionProject()
    screening_questions: List[ScreeningQuestion] = Field(default_factory=list)
    client: ChampionClient = ChampionClient()
    documents: List[ChampionDocument] = Field(default_factory=list)

    # ── machinery, not fields ──
    verification: ChampionVerification = ChampionVerification()
    briefing: ChampionBriefing = ChampionBriefing()
    recommended_searches: List[RecommendedSearch] = Field(default_factory=list)

    # Ingest provenance (`_source` / `_parsed_at` / `_parser`). Carried opaquely:
    # nothing reads these by name, but they identify which parser version
    # produced a stored profile, which is the only way to tell a hand-written
    # profile from one of the 1095 parsed in August.
    provenance: dict = Field(default_factory=dict, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _absorb_legacy_shape(cls, data: Any) -> Any:
        """Migrate the pre-09.2026 shape into the seven sections, on read.

        Idempotent and non-destructive in one direction only: a legacy value is
        copied into its new home ONLY when that home is still empty. Re-validating
        an already-migrated profile is therefore a no-op, and a payload that
        carries both shapes (an editor that has been open across a deploy) keeps
        the new one.
        """
        if not isinstance(data, dict):
            return data
        out = dict(data)

        def _blank(value: Any) -> bool:
            if value is None:
                return True
            if isinstance(value, str):
                return not value.strip()
            if isinstance(value, (list, dict)):
                return not value
            return False

        def _fill(target: dict, key: str, value: Any) -> None:
            if not _blank(value) and _blank(target.get(key)):
                target[key] = value

        # 1. Flat top-level engagement facts → basics. These are the keys the old
        #    ChampionProfile did not declare, so `extra="ignore"` deleted them on
        #    every save; that is the data loss this move closes.
        basics = dict(out.get("basics") or {})
        for key in (
            "role_name",
            "seniority_min_years",
            "rate_value",
            "rate_raw",
            "work_mode",
            "start_date",
            "deadline",
            "contract_length",
        ):
            _fill(basics, key, out.pop(key, None))
        out["basics"] = basics

        legacy_ctx = out.pop("project_context", None) or {}
        legacy_ctx = legacy_ctx if isinstance(legacy_ctx, dict) else {}
        legacy_sourcing = out.pop("sourcing", None) or {}
        legacy_sourcing = legacy_sourcing if isinstance(legacy_sourcing, dict) else {}
        legacy_standards = out.pop("client_standards", None) or {}
        legacy_standards = (
            legacy_standards if isinstance(legacy_standards, dict) else {}
        )

        # 2. sourcing → search (a plan becomes a query).
        search = dict(out.get("search") or {})
        for key in ("keywords", "target_companies", "notes", "sources"):
            _fill(search, key, legacy_sourcing.get(key))
        _fill(search, "disqualifiers", out.pop("disqualifiers", None))
        out["search"] = search

        # 4. project_context.{about,responsibilities} → project.
        project = dict(out.get("project") or {})
        _fill(project, "about", legacy_ctx.get("about"))
        _fill(project, "responsibilities", legacy_ctx.get("responsibilities"))
        out["project"] = project

        # 6. selling_points + the three floating blocks + client_standards → client.
        client = dict(out.get("client") or {})
        _fill(client, "selling_points", legacy_ctx.get("selling_points"))
        _fill(
            client, "consultant_insight", out.pop("internal_consultant_insight", None)
        )
        _fill(
            client, "historical_questions", out.pop("historical_client_questions", None)
        )
        _fill(client, "sectors", out.pop("sectors", None))
        for key in ("priority_rules", "offlimit", "contract_type", "cv_language"):
            _fill(client, key, legacy_standards.get(key))
        out["client"] = client

        provenance = dict(out.get("provenance") or {})
        for key in ("_source", "_parsed_at", "_parser"):
            value = out.pop(key, None)
            if value is not None and key not in provenance:
                provenance[key] = value
        out["provenance"] = provenance

        return out

    def model_dump(self, *args: Any, **kwargs: Any) -> dict:
        """Dump the seven sections plus the underscore provenance keys.

        ``provenance`` itself is ``exclude=True``: re-emitting it both nested and
        flat would leave two copies in the JSONB that could drift apart.
        """
        data = super().model_dump(*args, **kwargs)
        for key, value in (self.provenance or {}).items():
            data.setdefault(key, value)
        return data

    def is_screening_ready(self) -> bool:
        """True if there is at least one question — i.e. recruiter can be asked to screen."""
        return bool(self.screening_questions)


# ── Screening answers (CandidateStage.screening_answers) ────────────────────


class ScreeningAnswerItem(BaseModel):
    question_id: str
    response: str = ""
    deal_breaker_hit: bool = False


class ScreeningAnswers(BaseModel):
    """Full payload a recruiter submits when moving a candidate past screening."""

    answers: List[ScreeningAnswerItem] = Field(default_factory=list)
    overall_fit: Literal["fit", "uncertain", "miss"] = "uncertain"
    notes: str = ""
    answered_at: Optional[datetime] = None
    answered_by: Optional[int] = None

    def match_percent(self) -> float:
        """Return 0-100 approximation of how well the candidate aligns with the Champion.

        - 100 when overall_fit=fit and no deal_breaker_hit
        -   0 when any deal_breaker_hit is True
        - otherwise proportional to (answered questions / total) with
          `uncertain` → 0.6 and `fit` → 1.0 multiplier.
        """
        if any(a.deal_breaker_hit for a in self.answers):
            return 0.0
        if not self.answers:
            return 0.0
        answered = sum(1 for a in self.answers if a.response.strip())
        ratio = answered / max(len(self.answers), 1)
        fit_weight = {"fit": 1.0, "uncertain": 0.6, "miss": 0.2}[self.overall_fit]
        return round(ratio * fit_weight * 100.0, 1)
