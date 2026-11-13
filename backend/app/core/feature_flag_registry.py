"""Rejestr flag wyłączonych domyślnie: każda nowa ma termin decyzji.

Audyt z 07.11.2026 (D3): w ``config.py`` 87 przełączników domyślnie stoi na
``False``, część od miesięcy, i nikt nie pamięta, kto ma zdecydować. Wpis mówi,
po co jest flaga i do kiedy trzeba ją włączyć na stałe albo usunąć razem
z kodem. Po terminie pada ``tests/test_feature_flag_registry.py``. Przedłużenie
to nowa data ``decided`` z ``expires`` najwyżej 60 dni dalej, czyli decyzja
w diffie PR-a, a nie milczenie.

Rejestr opisuje wartość domyślną z kodu. To, co jest ustawione na produkcji,
zmienia wyłącznie workflow „Coolify set env”.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

MAX_DAYS_WITHOUT_DECISION = 60


@dataclass(frozen=True)
class FeatureFlag:
    name: str
    purpose: str
    decided: date
    expires: date


REGISTERED_FLAGS: tuple[FeatureFlag, ...] = (
    FeatureFlag(
        name="TRAININGS_TEAMS_ENABLED",
        purpose="Spotkania szkoleń w Teams zakłada NEXUS w kalendarzu szkolenia@, nagranie wraca samo; włącza Artur po kroku admina M365.",
        decided=date(2026, 11, 13),
        expires=date(2027, 1, 12),
    ),
    FeatureFlag(
        name="SALES_REGISTRY_ENABLED",
        purpose="Dane firm Sprzedaży z białej listy VAT i KRS (noc i po zapisie NIP-u); włącza Artur po próbie na stagingu.",
        decided=date(2026, 11, 13),
        expires=date(2027, 1, 12),
    ),
    FeatureFlag(
        name="SALES_COGNISM_PEOPLE_ENABLED",
        purpose="Mapy decydentów z Cognism przez osobną rutynę Grok Bota.",
        decided=date(2026, 11, 12),
        expires=date(2027, 1, 11),
    ),
    FeatureFlag(
        name="SALES_BOT_TASKS_ENABLED",
        purpose="Nowe zadania Grok Bota w Sprzedaży (poza sygnałami i punktami); włącza Artur po próbie polecenia v2.",
        decided=date(2026, 11, 12),
        expires=date(2027, 1, 11),
    ),
    FeatureFlag(
        name="SALES_SIGNALS_ENABLED",
        purpose="Sygnały i punkty do rozmowy z Grok Bota w Sprzedaży; włącza Artur po próbie bota.",
        decided=date(2026, 11, 9),
        expires=date(2027, 1, 8),
    ),
    FeatureFlag(
        name="SINGLE_CANDIDATE_LIST_ENABLED",
        purpose="Jedna lista kandydatów zamiast zakładek, portale na skali „Dop.”; włącza tylko Artur.",
        decided=date(2026, 11, 8),
        expires=date(2027, 1, 7),
    ),
    FeatureFlag(
        name="NEW_COLUMN_TEMPO_TARGET_ENABLED",
        purpose="Cel kart w „Nowych” wg tempa rekrutacji i miejsce dla świeżych; włącza tylko Artur.",
        decided=date(2026, 11, 8),
        expires=date(2027, 1, 7),
    ),
    FeatureFlag(
        name="REVIEW_BATCH_ENABLED",
        purpose="Porcja dnia kart z przeglądu (#3153); włącza tylko Artur po pilocie HoR.",
        decided=date(2026, 11, 7),
        expires=date(2027, 1, 6),
    ),
    FeatureFlag(
        name="AUTO_FULL_REVIEW_DAYTIME_FIRST_ENABLED",
        purpose="Pierwszy przegląd nowej rekrutacji w dzień; włącza się razem z porcją dnia.",
        decided=date(2026, 11, 7),
        expires=date(2027, 1, 6),
    ),
)

# Stan z 08.11.2026. Lista bez terminów, bo 85 dat w jednym dniu zablokowałoby
# kolejkę merge'ów naraz. Nowa flaga domyślnie wyłączona idzie do rejestru wyżej,
# a nazwa stąd przechodzi tam, gdy ktoś podejmie o niej decyzję.
OFF_BEFORE_REGISTRY: frozenset[str] = frozenset(
    {
        "AAD_GROUP_RBAC_ENABLED",
        "ACCESS_USAGE_COUNTER_ENABLED",
        "ADMIN_CASES_MAIL_INGEST_ENABLED",
        "AI_INDEX_OUTBOX_ENABLED",
        "AI_INDEX_WORKER_ENABLED",
        "AI_MATCH_TELEMETRY_ENABLED",
        "AI_QUOTA_STRICT",
        "AI_SCORING_CONTRACT_V2",
        "AI_SCORING_SKILL_RECENCY",
        "AI_TEXT_SCHEMA_V2",
        "AI_TEXT_SCHEMA_V3",
        "ANALYTICS_CUTOVER_BREAKGLASS",
        "APPLICATION_SCREENING_ENABLED",
        "AUTENTI_ENABLED",
        "CANDIDATE_CONTACT_ASSIGNMENT_ENABLED",
        "CANDIDATE_CONTACT_ENABLED",
        "CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED",
        "CANDIDATE_MATCH_JOB_PREFERRED_GROUPS",
        "CHAMPION_AVAILABILITY_CONFLICT_ENABLED",
        "CHAMPION_AVAILABILITY_FALLBACK_ENABLED",
        "CHAMPION_MATCH_SIGNALS_ENABLED",
        "CHAMPION_SENIORITY_PENALTY_ENABLED",
        "COMPASS_AVAILABILITY_ENABLED",
        "COMPASS_LIFECYCLE_ENABLED",
        "COMPASS_WORKDAYS_ENABLED",
        "CONTRACT_DOCS_SP_SYNC_ENABLED",
        "CONVERSATION_FACTS_ENABLED",
        "CV_AUTO_GENERATE_WITHOUT_CONFIRMATION",
        "CV_CENTRAL_POLICIES_ENABLED",
        "CV_INTERACTIVE_ENABLED",
        "CV_JOB_INPUT_RETENTION_ENABLED",
        "CV_PASSAGES_ENABLED",
        "DEBUG",
        "HR_APPROVALS_MAIL_REPLY_ENABLED",
        "HR_PROGRAM_ENABLED",
        "HYBRID_POOL_ENABLED",
        "JARVIS_ENABLED",
        "JJIT_ENABLED",
        "KEYWORD_SEARCH_FOLDED_FTS",
        "KNOWN_PEOPLE_BOOST_ENABLED",
        "KPI_COACH_DEBUG_BREAKGLASS",
        "KPI_COACH_NUDGER_ENABLED",
        "KPI_COACH_V2_NUDGES_ENABLED",
        "M365_APP_MAIL_ENABLED",
        "M365_RECORDING_DISCOVERY_ENABLED",
        "M365_REMATCH_ENABLED",
        "M365_SYNC_LOOP_ENABLED",
        "M365_WEBHOOKS_ENABLED",
        "MATCH_DIGEST_ENABLED",
        "MULTI_QUERY_RETRIEVAL_ENABLED",
        "NEW_COLUMN_AUTOFILL_ENABLED",
        "NOTES_INSIGHTS_SYNC_ENABLED",
        "OAUTH_ROUTE_SCOPES_ENFORCE",
        "ORDER_MAIL_INGEST_ENABLED",
        "PORTAL_JJIT_ENABLED",
        "PORTAL_PRACUJ_ENABLED",
        "PORTAL_ROCKETJOBS_ENABLED",
        "PRIOR_SCREENING_LAYER_ENABLED",
        "QUERY_ADAPTER_ENABLED",
        "RECOMMENDATION_CARD_ASSIST_ENABLED",
        "RECOMMENDATION_CARD_IMPORT_ENABLED",
        "RECRUITMENT_ALLOCATION_ENABLED",
        "RERANKER_ENABLED",
        "SALES_TEAMS_TRANSCRIPTS_ENABLED",
        "SAVED_SEARCH_SEMANTICS_MIGRATION_AUTORUN",
        "SCORE_RENORMALIZE_UNSCORED_LAYERS",
        "SCREENING_NOTE_SYNC_ENABLED",
        "SCREENING_NOTE_SYNC_OTHER_NOTES_ENABLED",
        "SELF_REGISTRATION_ENABLED",
        "SKILL_ALIAS_EXTENDED_ENABLED",
        "SMTP_ENABLED",
        "STRUCTURED_POOL_ENABLED",
        "TALENT_RADAR_STRUCTURED_SKILLS_ENABLED",
        "TEAMS_NOTIFICATIONS_ENABLED",
        "TEAMS_PREP_APP_ONLY_ENABLED",
        "TEAMS_PREP_TRANSCRIPTS_ENABLED",
        "TRAFFIT_IMPORT_SIDE_EFFECTS_ENABLED",
        "TRAFFIT_INBOUND_APPLY_ENABLED",
        "TRAFFIT_INTEGRATION_ENABLED",
        "TRAFFIT_OUTBOUND_ENABLED",
        "TRAFFIT_POLL_ENABLED",
        "TRAFFIT_SYNC_ENABLED",
        "TRAFFIT_WEBHOOK_ACCEPT_ENABLED",
        "WEEKLY_EVAL_ENABLED",
    }
)
