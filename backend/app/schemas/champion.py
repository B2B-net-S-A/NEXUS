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

from pydantic import BaseModel, Field, field_validator, model_validator


class _NullTolerantSection(BaseModel):
    """Treat ``null`` in an optional text/list field as "not filled in".

    The AI parser is told to return ``null`` for information missing from the
    document, while these fields are typed ``str = ""`` / ``list = []``. A
    blank "Deal breaker" cell in the Word template therefore failed the whole
    import with a raw Pydantic error — after the paid parse (UAT M04-B01).
    Only fields WITH an empty default are coerced; required fields keep
    failing, because a missing screening question is a real defect.
    """

    @model_validator(mode="before")
    @classmethod
    def _null_to_empty(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cleaned = dict(data)
        for name, field in cls.model_fields.items():
            key = field.alias or name
            if key not in cleaned or cleaned[key] is not None:
                continue
            if field.default == "":
                cleaned[key] = ""
            elif field.default_factory is list:
                cleaned[key] = []
        return cleaned


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
    #
    # BEZ `max_length` — jak `client.cv_language` niżej. `prepare_profile`
    # przycina to pole (`text_limits`), ale WYŁĄCZNIE gdy jest w zbiorze
    # `dirty`, więc profil z importu, którego nikt nie edytował, nosi wartość
    # dłuższą niż 50 znaków w nieskończoność (najdłuższa na produkcji: 83).
    # Limit wywracał wtedy sam odczyt profilu. Audyt 18.09.2026.
    language: Optional[str] = None
    start_date: Optional[str] = Field(default=None, max_length=100)
    # Termin na dostarczenie kandydatów DO TEJ oferty. Osobno od KPI klienta
    # („mamy 5 dni roboczych"), bo tamto opisuje tempo, a to konkretną datę.
    deadline: Optional[str] = Field(default=None, max_length=100)
    contract_length: Optional[str] = Field(default=None, max_length=255)


# Wymagania do wyszukiwania w bazie (25.09.2026) — te same limity co edytor
# wierszy (`lib/keyword-requirements.ts`) i lista kandydatów.
SEARCH_REQUIREMENT_MAX_ROWS = 10
SEARCH_REQUIREMENT_MAX_WORDS = 20
SEARCH_WORD_MIN_CHARS = 2
SEARCH_WORD_MAX_CHARS = 100


def _search_words(values: Any) -> list[str]:
    """Słowa jednego wiersza: bez `|` (rozdziela słowa w adresie), pustych,
    za krótkich i powtórek (bez wielkości liter), najwyżej 20."""
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            continue
        word = " ".join(raw.replace("|", " ").split())[:SEARCH_WORD_MAX_CHARS].strip()
        if len(word) < SEARCH_WORD_MIN_CHARS or word.casefold() in seen:
            continue
        seen.add(word.casefold())
        out.append(word)
        if len(out) >= SEARCH_REQUIREMENT_MAX_WORDS:
            break
    return out


class ChampionSearch(_NullTolerantSection):
    """2. Co wpisać (search) — literally what the recruiter pastes into search.

    Not "sourcing strategy" any more. The old block asked for a plan (channels,
    a narrative, a to-do); this one asks for the query.

    ``keywords`` are LinkedIn-style phrases for searching OUTSIDE NEXUS
    („Frazy do LinkedIna”). ``requirements`` / ``exclude`` are the search in
    NEXUS's own base (decyzje Artura 25.09.2026): a row is one requirement,
    the words in a row are variants (OR), rows combine with AND — exactly the
    list's `q_any_group` / `q_none`. „Szukaj ręcznie” starts from them; the
    automatic matching does NOT read them (`champion_view.requirement_source`
    strips them), and the hand-off needs at least one row.

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
    requirements: List[List[str]] = Field(default_factory=list)
    exclude: List[str] = Field(default_factory=list)

    # Normalizacja zamiast odmowy: `prepare_profile` waliduje model w środku
    # handlera, więc wyjątek walidacji skończyłby się 500. Edytor i tak nie
    # pozwala przekroczyć limitów — tu łapiemy wyłącznie nietypowe wejście.
    @field_validator("requirements", mode="before")
    @classmethod
    def _clean_requirements(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        rows = [_search_words(row) for row in value]
        return [row for row in rows if row][:SEARCH_REQUIREMENT_MAX_ROWS]

    @field_validator("exclude", mode="before")
    @classmethod
    def _clean_exclude(cls, value: Any) -> Any:
        return _search_words(value) if isinstance(value, list) else value


# Storage bound for ONE stack entry. It was 120 until 09.2026, and the intake
# normaliser dropped everything longer (and everything over 12 words) into
# `intake.unresolved` — so a Delivery Lead's requirement written as a sentence
# silently vanished from `jobs.must_skills`. Long entries are now kept and only
# flagged; this bound exists solely against a whole pasted paragraph being
# stored as "one requirement" (entries are split on newlines, commas and
# semicolons first, so a real requirement never gets near it).
STACK_ITEM_MAX_CHARS = 500


class StackItem(BaseModel):
    name: str = Field(min_length=1, max_length=STACK_ITEM_MAX_CHARS)


class ChampionStack(_NullTolerantSection):
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


class ChampionProject(_NullTolerantSection):
    """4. O projekcie — two sentences, merged with the duties.

    ``about`` is capped by INSTRUCTION, not by a validator: a hard length limit
    would reject an ingested legacy profile whose ``about`` is four sentences
    long, and rejecting stored data on read turns an over-long paragraph into a
    500. The cap lives in the parser prompt and the editor hint instead.
    """

    about: str = ""
    responsibilities: str = ""


class ScreeningQuestion(_NullTolerantSection):
    """One DL-authored screening question with grading hints."""

    id: str = Field(min_length=1, max_length=40)
    question: str = Field(min_length=1)
    ideal_answer: str = ""
    deal_breaker: str = ""


class ChampionClient(_NullTolerantSection):
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
    # BEZ `max_length` — celowo, ta sama zasada co przy `ChampionProject.about`.
    #
    # Oba pola są hoistowane z `client_standards` przez
    # `migrate_legacy_champion_shape`, czyli POWSTAJĄ dopiero przy odczycie,
    # już po sanityzacji w `champion_intake.prepare_profile`. Żaden guard ich
    # więc nie przycina, a parser AI z 08.2026 wpisywał tam prozę („CV po polsku
    # oraz po angielsku…", 102 znaki). Limit oznaczał, że 83 rekrutacje
    # (19 opublikowanych, 2 665 kandydatów w pipeline'ach) zwracały 500 na
    # KAŻDYM odczycie i na KAŻDYM zapisie — a `prepare_profile` normalizuje
    # tylko pola ZMIENIONE, więc nietknięta wartość nie naprawiała się nigdy
    # i rekrutacji nie dało się zapisać ani sklonować. Audyt 18.09.2026.
    contract_type: Optional[str] = None
    cv_language: Optional[str] = None
    # Ex-`internal_consultant_insight`: what our person already at the client says.
    consultant_insight: str = ""
    # Ex-`historical_client_questions`: what this client has asked before.
    historical_questions: str = ""
    sectors: List[str] = Field(default_factory=list)


# ── 4. Doświadczenie poza stackiem (09.2026) ────────────────────────────────
#
# Dziedzina („payments, min. 2 lata"), certyfikaty i regulacje nie są
# technologiami, a do 09.2026 lądowały w stacku, gdzie scoring i filtry czytały
# je jak skille. Osobna sekcja mówi, CZYM są. Świadomie NIE jest bramką:
# branża w CV bywa pusta, więc brak śladu to „nie wiemy", nie „nie ma".


EXPERIENCE_ITEM_MAX_CHARS = 160
EXPERIENCE_ITEMS_MAX = 20


class ExperienceItem(_NullTolerantSection):
    name: str = Field(min_length=1, max_length=EXPERIENCE_ITEM_MAX_CHARS)
    level: Literal["must", "nice"] = "must"
    # Tylko dla dziedzin; w certyfikatach i regulacjach ignorowane.
    min_years: Optional[int] = Field(default=None, ge=0, le=40)
    # Niuans jednej pozycji: „karty debetowe, nie kredytowe".
    note: str = ""


class ChampionExperience(_NullTolerantSection):
    domains: List[ExperienceItem] = Field(default_factory=list)
    certifications: List[ExperienceItem] = Field(default_factory=list)
    regulations: List[ExperienceItem] = Field(default_factory=list)
    notes: str = ""

    def is_empty(self) -> bool:
        return not (
            self.domains
            or self.certifications
            or self.regulations
            or self.notes.strip()
        )


# ── 8. Wiedza z rozmów (09.2026) ─────────────────────────────────────────────
#
# Smaczki od klienta i od naszego konsultanta. Do 09.2026 leżały w pięciu
# wolnych polach, a dwa z nich (teksty weryfikacji) nie były nigdzie
# wyświetlane po zapisie. W bazie leżą WYŁĄCZNIE notatki pisane w tej sekcji
# (`manual`, `ai_intake`, `document`); wpisy ze starych pól i z weryfikacji
# składa `champion_view.insights` przy odczycie, o stałych identyfikatorach
# (`legacy:…`, `verification:…`) — bez przepisywania 949 profili.
#
# `audience` rozstrzyga, czy wolno to powiedzieć kandydatowi. „team" jest
# domyślne i NIGDY nie wychodzi poza zespół: publiczna karta Championa i szkic
# opisu na stronę kariery czytają wyłącznie „candidate".

INSIGHT_TEXT_MAX_CHARS = 2000
INSIGHTS_MAX = 60

InsightSource = Literal["client", "consultant"]
InsightAudience = Literal["team", "candidate"]
InsightTopic = Literal[
    "needs",
    "rejections",
    "decision",
    "process",
    "team",
    "project",
    "pitch",
    "ask_client",
    "other",
]
InsightOrigin = Literal["manual", "ai_intake", "document", "legacy", "verification"]
STORED_INSIGHT_ORIGINS = ("manual", "ai_intake", "document")


class InsightNote(_NullTolerantSection):
    id: str = Field(min_length=1, max_length=80)
    source: InsightSource = "client"
    topic: InsightTopic = "other"
    audience: InsightAudience = "team"
    text: str = Field(min_length=1, max_length=INSIGHT_TEXT_MAX_CHARS)
    # „Do dopytania" z /jobs/new: pytanie do klienta, które DL odhacza.
    done: bool = False
    origin: InsightOrigin = "manual"
    author_id: Optional[int] = None
    author_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Tylko w odpowiedzi API: wpisy z weryfikacji zmienia się ponowną weryfikacją.
    editable: bool = True


class ClientHistoryItem(BaseModel):
    topic: str = Field(default="other", max_length=40)
    text: str = Field(min_length=1, max_length=600)
    basis_count: Optional[int] = Field(default=None, ge=0)


class ClientHistorySummary(BaseModel):
    """Podsumowanie historii klienta — blok maszynowy, jak `briefing`.

    Liczy go `champion_client_history` (AI + bank pytań z debriefów); zwykły PUT
    profilu nie może go podrobić ani skasować.
    """

    status: Literal["none", "ready", "failed"] = "none"
    items: List[ClientHistoryItem] = Field(default_factory=list)
    debrief_questions: List[str] = Field(default_factory=list)
    event_count: int = 0
    generated_at: Optional[datetime] = None
    inputs_hash: Optional[str] = None
    model: Optional[str] = None
    message: Optional[str] = None


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


# ── Recommended searches — usunięte 25.09.2026 ──────────────────────────────
#
# Panel „Rekomendowane wyszukiwania (AI)” zastąpiły wymagania do wyszukiwania
# w sekcji 2 (`ChampionSearch.requirements`, decyzja Artura). Stare profile
# nadal niosą klucz `recommended_searches` — zostaje w modelu jako surowe dane
# (bez schematu i bez konsumenta), żeby zapis profilu go nie kasował.


# ── Full profile ─────────────────────────────────────────────────────────────


class ChampionIntake(BaseModel):
    policy_version: Literal[1] = 1
    template_version: Optional[str] = None
    # Input that could NOT become a canonical value (the field stays empty and
    # validation reports an error until someone resolves it).
    unresolved: dict[str, str] = Field(default_factory=dict)
    # Input that WAS kept, but deserves a second look: a document rate written
    # as a range next to a kept number, a requirement written as a sentence.
    # Always a warning — never a reason to empty a field or block anything.
    advisory: dict[str, str] = Field(default_factory=dict)
    document_context: dict[str, str] = Field(default_factory=dict)
    applied_by: Optional[int] = None
    applied_at: Optional[str] = None


def migrate_legacy_champion_shape(data: Any) -> Any:
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

    # 1b. Liczby całkowite zapisane jako ułamek — ucinamy zamiast odrzucać.
    #
    # Parser zapisywał „2,5 roku doświadczenia" jako `2.5`, a pół dnia w biurze
    # jako `0.5`. Pydantic odrzuca `float` na polu `int` (`int_from_float`),
    # więc pięć rekrutacji na produkcji wywracało cały odczyt profilu.
    #
    # UCINAMY W DÓŁ, nie zaokrąglamy do najbliższej — bo oba pola są wejściem
    # do bramek, które UKRYWAJĄ kandydatów, a repo trzyma zasadę „nieznane
    # przechodzi": `onsite_days_per_week` steruje `requires_office_days`
    # (`days > 0`) i `office_days_exceeded`, a `seniority_min_years` karą za
    # seniority. Zaokrąglenie `0.5 → 1` zaostrzyłoby bramkę na podstawie
    # wartości, której nikt świadomie nie wpisał; `0.5 → 0` najwyżej jej nie
    # zaostrza. Przy okazji `round()` w Pythonie jest bankierskie
    # (`round(0.5) == 0`, ale `round(2.5) == 2`) — niespójne w obie strony.
    # `ge`/`le` na polach nadal obowiązują. Audyt 18.09.2026.
    for key in ("seniority_min_years", "onsite_days_per_week"):
        value = basics.get(key)
        if isinstance(value, float) and not isinstance(value, bool):
            basics[key] = int(value)

    out["basics"] = basics

    legacy_ctx = out.pop("project_context", None) or {}
    legacy_ctx = legacy_ctx if isinstance(legacy_ctx, dict) else {}
    legacy_sourcing = out.pop("sourcing", None) or {}
    legacy_sourcing = legacy_sourcing if isinstance(legacy_sourcing, dict) else {}
    legacy_standards = out.pop("client_standards", None) or {}
    legacy_standards = legacy_standards if isinstance(legacy_standards, dict) else {}

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
    _fill(client, "consultant_insight", out.pop("internal_consultant_insight", None))
    _fill(client, "historical_questions", out.pop("historical_client_questions", None))
    _fill(client, "sectors", out.pop("sectors", None))
    for key in ("priority_rules", "offlimit", "contract_type", "cv_language"):
        _fill(client, key, legacy_standards.get(key))
    out["client"] = client

    provenance = dict(out.get("provenance") or {})
    for key in ("_source", "_parsed_at", "_parser", "_enriched"):
        value = out.pop(key, None)
        if value is not None and key not in provenance:
            provenance[key] = value
    out["provenance"] = provenance

    return out


class ChampionProfile(BaseModel):
    """The Champion Profile.

    Section order matches the Word template and the editor so a Delivery Lead
    reading one is reading the other:

        1. basics             — podstawowe informacje
        2. search             — co wpisać (search)
        3. stack              — stack technologiczny
        4. experience         — doświadczenie poza stackiem (09.2026)
        5. project            — o projekcie (2 zdania + obowiązki)
        6. screening_questions— pytania screeningowe
        7. client             — o kliencie
        8. insights           — wiedza z rozmów (09.2026)
           documents          — dokumenty (karta klienta, bez UI w edytorze)

    ``verification``, ``briefing``, ``recommended_searches`` and
    ``client_history`` are NOT sections. They are server-stamped through
    dedicated endpoints and a plain profile PUT must never be able to forge or
    wipe them.
    """

    # ── the sections ──
    basics: ChampionBasics = ChampionBasics()
    search: ChampionSearch = ChampionSearch()
    stack: ChampionStack = ChampionStack()
    experience: ChampionExperience = ChampionExperience()
    project: ChampionProject = ChampionProject()
    screening_questions: List[ScreeningQuestion] = Field(default_factory=list)
    client: ChampionClient = ChampionClient()
    insights: List[InsightNote] = Field(default_factory=list)
    documents: List[ChampionDocument] = Field(default_factory=list)
    intake: Optional[ChampionIntake] = None

    # ── machinery, not fields ──
    verification: ChampionVerification = ChampionVerification()
    briefing: ChampionBriefing = ChampionBriefing()
    # Dane historyczne panelu usuniętego 25.09.2026 — patrz komentarz wyżej.
    recommended_searches: List[dict[str, Any]] = Field(default_factory=list)
    client_history: ClientHistorySummary = ClientHistorySummary()

    # Ingest provenance (`_source` / `_parsed_at` / `_parser`). Carried opaquely:
    # nothing reads these by name, but they identify which parser version
    # produced a stored profile, which is the only way to tell a hand-written
    # profile from one of the 1095 parsed in August.
    provenance: dict = Field(default_factory=dict, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _absorb_legacy_shape(cls, data: Any) -> Any:
        return migrate_legacy_champion_shape(data)

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
    # Skąd odpowiedź (Pipeline v4, 23.09.2026): `reassign_suggested` = rekruter
    # przyjął podpowiedź Luny z poprzedniej rekrutacji (przepięcie).
    origin: Literal["manual", "reassign_suggested"] = "manual"
    # Pytanie świadomie pominięte przy przepięciu — odpowiedź bywa pusta.
    # Pominięte odpowiedzi nie liczą się do dopasowania i NIGDY nie wychodzą
    # do klienta (`client_safe_screening`).
    skipped: bool = False


class ExperienceCheck(BaseModel):
    """„Sprawdź w rozmowie” — pozycja sekcji 4 potwierdzona (albo nie) przez rekrutera.

    Tylko zapis rozmowy: nie zmienia `match_percent`, scoringu ani plakietek
    (te mówią o śladzie w CV, a to o tym, co kandydat powiedział).
    """

    kind: Literal["domains", "certifications", "regulations"] = "domains"
    name: str = Field(min_length=1, max_length=EXPERIENCE_ITEM_MAX_CHARS)
    status: Literal["confirmed", "not_confirmed", "unknown"] = "unknown"
    note: str = Field(default="", max_length=500)


class ScreeningAnswers(BaseModel):
    """Full payload a recruiter submits when moving a candidate past screening."""

    answers: List[ScreeningAnswerItem] = Field(default_factory=list)
    experience_checks: List[ExperienceCheck] = Field(
        default_factory=list, max_length=EXPERIENCE_ITEMS_MAX * 3
    )
    overall_fit: Literal["fit", "uncertain", "miss"] = "uncertain"
    notes: str = ""
    # Notatka WEWNĘTRZNA „pominięte — przepięcie": dlaczego część pytań nie ma
    # odpowiedzi. W odróżnieniu od `notes` (widoczne w share portalu) nie
    # trafia do klienta ani do generatora CV.
    internal_note: Optional[str] = Field(default=None, max_length=2000)
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
        # Pytania pominięte przy przepięciu nie są ani „za", ani „przeciw".
        counted = [a for a in self.answers if not a.skipped]
        if not counted:
            return 0.0
        answered = sum(1 for a in counted if a.response.strip())
        ratio = answered / max(len(counted), 1)
        fit_weight = {"fit": 1.0, "uncertain": 0.6, "miss": 0.2}[self.overall_fit]
        return round(ratio * fit_weight * 100.0, 1)


def client_safe_screening(screening_answers: Any) -> Optional[dict]:
    """Odpowiedzi screeningu w wersji dla KLIENTA (share portal, generator CV).

    Zdejmuje odpowiedzi pominięte przy przepięciu (`skipped`) i notatkę
    wewnętrzną (`internal_note`). Oba pola opisują NASZ proces, nie kandydata —
    pusta odpowiedź z dopiskiem „pominięte" czytałaby się u klienta jak brak
    kompetencji. Wejście to surowy JSONB z `CandidateStage.screening_answers`
    (także sprzed 23.09.2026); brak danych = ``None``.
    """
    if not isinstance(screening_answers, dict) or not screening_answers:
        return None
    safe = {k: v for k, v in screening_answers.items() if k != "internal_note"}
    answers = screening_answers.get("answers")
    if isinstance(answers, list):
        safe["answers"] = [
            a for a in answers if isinstance(a, dict) and not a.get("skipped")
        ]
    return safe
