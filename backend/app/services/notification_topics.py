"""Tematy powiadomień — ikony górnego paska zamiast dzwonka (16.10.2026).

Pomiar 16.10.2026: dzwonek miał „99+” u 21 z 41 kont, ~18 wpisów na osobę
dziennie, a 99,5% oznaczeń „przeczytane” w 30 dni to gaszenie hurtem. Decyzja
Artura: dzwonka nie ma; każda ikona paska ma JEDEN temat — „Wiadomości”
(czaty + wzmianki z notatek), „Kalendarz” (rozmowy u klienta), „Moi ludzie”,
„CV” (licznik ze stanu, `api/board_tasks` → `/cv`) i „Rekrutacje” (rekrutacje
z nowościami). Typ bez ikony („inne”) daje tylko dymek i mail tam, gdzie mail
już jest.

Temat liczy się z TYPU, nie z treści: filtry SQL to zwykłe `type IN (…)`,
a mapa jest wyczerpująca (`test_notification_topics.py` — nowy typ bez tematu
wywraca CI). Reguła: `docs/claude/powiadomienia/pasek-tematy-bez-dzwonka.md`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from sqlalchemy import Integer, case, cast, func, literal_column

from app.models.notification import NotificationType
from app.services.notification_categories import NotificationCategory, types_in


class NotificationTopic(StrEnum):
    messages = "messages"
    interviews = "interviews"
    cv = "cv"
    my_people = "my_people"
    jobs = "jobs"
    contracts = "contracts"
    other = "other"


_T = NotificationType
_P = NotificationTopic

# Wzmianki i odpowiedzi w notatkach idą do okienka „Wiadomości” obok czatów.
# Osobna krotka, nie `mention_dispatch.CHAT_NOTIFICATION_TYPES` — tamta steruje
# `exclude_chat` i kasowaniem wierszy przy usunięciu wiadomości czatu.
NOTE_NOTIFICATION_TYPES: tuple[NotificationType, ...] = (
    _T.note_mention,
    _T.note_reply,
)

_MESSAGES = (_T.job_chat_message, _T.job_chat_mention, *NOTE_NOTIFICATION_TYPES)

_CV = (_T.board_task_waiting, _T.cv_ready, _T.cpro_send_assigned)

_JOBS = (
    # Ruchy kandydatów i przypomnienia o parze
    _T.stage_rule,
    _T.stage_changed,
    _T.client_accepted,
    _T.hire_missing_contract,
    _T.stage_stuck_7d,
    _T.dl_stage_stale_6h,
    _T.client_feedback_eobd,
    _T.candidate_feedback_1h,
    _T.suggest_next_step,
    _T.pending_verification,
    _T.candidate_rate_change,
    _T.candidate_rate_change_task,
    _T.candidate_claim_taken,
    _T.candidate_followup_signal,
    # 0506: umowa przedwstępna osoby (prośba, podpisy, terminy).
    _T.pre_contract,
    # Rekrutacja: Champion, termin, przydział
    _T.champion_profile_updated,
    _T.champions_changed,
    _T.champion_search_resumed,
    _T.job_deadline_7d,
    _T.job_deadline_3d,
    _T.job_deadline_1d,
    _T.request_assignment_changed,
    _T.recruiter_parked,
    _T.recruiter_restored,
    _T.recruitment_allocation_alert,
    _T.request_review_needed,
    _T.client_job_opened,
    _T.job_p0_set,
    _T.job_p0_requested,
    _T.job_closed_people_waiting,
    _T.request_allocation_proposals,
    # 0526: brakujące ogłoszenia (codzienne, bez dymka).
    _T.job_ad_missing,
    _T.job_ad_backlog,
    _T.job_ad_nudge,
    # Osoby od automatu do tej rekrutacji
    _T.auto_match,
    _T.auto_match_proposals,
    _T.similar_job_candidates,
    _T.also_fits_added,
    _T.autofill_decisions_due,
    _T.autofill_quality_report,
    _T.match_digest,
    # Konsultant od opieki do obsadzenia w rekrutacji („Przekaż do front office”).
    _T.care_front_office_handoff,
)

_INTERVIEWS = tuple(types_in(NotificationCategory.interviews))

# 26.10.2026: umowy w podpisie mają własną ikonę „Umowy” (dotąd „inne”, sam
# dymek — reprezentant firmy nie zauważył umowy czekającej na jego podpis).
_CONTRACTS = (
    _T.signature_sent,
    _T.signature_signed,
    _T.signature_rejected,
    _T.signature_failed,
    _T.signature_renewal_requested,
    # Prośba do DL o „Oznacz jako podpisaną” (droga mailowa).
    _T.b2b_signature_requested,
    # Umowę Twojej osoby wygenerował ktoś inny — wyślij ją i pilnuj podpisu.
    _T.b2b_agreement_ready,
)


def _build() -> dict[NotificationType, NotificationTopic]:
    mapping: dict[NotificationType, NotificationTopic] = {}
    for topic, types in (
        (_P.messages, _MESSAGES),
        (_P.interviews, _INTERVIEWS),
        (_P.cv, _CV),
        (_P.my_people, (_T.my_people_match,)),
        (_P.jobs, _JOBS),
        (_P.contracts, _CONTRACTS),
    ):
        for t in types:
            assert t not in mapping, f"{t} ma dwa tematy"
            mapping[t] = topic
    # Reszta nie ma ikony: zamówienia, system, KPI, zapisane
    # wyszukiwania, Targ, wynik przeglądu bazy… (decyzja D6: dymek i mail).
    for t in NotificationType:
        mapping.setdefault(t, _P.other)
    return mapping


TOPIC_BY_TYPE: dict[NotificationType, NotificationTopic] = _build()


def topic_for(notification_type: NotificationType) -> NotificationTopic:
    return TOPIC_BY_TYPE[notification_type]


def types_in_topic(topic: NotificationTopic) -> frozenset[NotificationType]:
    return frozenset(t for t, p in TOPIC_BY_TYPE.items() if p == topic)


# Dymek tylko tam, gdzie ktoś czeka na ruch tej osoby albo nie ma innego
# miejsca. Ruchy etapów, automat i terminy zmieniają tylko licznik ikony;
# czat ma własny dymek z `chat:notify`, „Kalendarz” — z `INTERVIEW_NOTIFY_EVENT`,
# coach KPI — z `KpiNudgeToaster`.
_JOBS_TOAST = (
    # Akceptacja klienta (0451) — dobra wiadomość dla całego zespołu pary.
    _T.client_accepted,
    # 0452: Delivery Lead ma wpisać umowę zatrudnionej osoby.
    _T.hire_missing_contract,
    # 0506: ktoś czeka na przedwstępną — wystawienie, podpis, termin B2B.
    _T.pre_contract,
    _T.request_assignment_changed,
    _T.recruiter_parked,
    _T.recruiter_restored,
    _T.candidate_rate_change_task,
    _T.candidate_claim_taken,
    _T.request_review_needed,
    _T.client_job_opened,
    _T.job_p0_set,
    _T.job_p0_requested,
    _T.job_closed_people_waiting,
    _T.request_allocation_proposals,
    _T.care_front_office_handoff,
)
_OTHER_WITHOUT_TOAST = (_T.kpi_coach, _T.powercalling_kpi)

TOAST_TYPES: frozenset[NotificationType] = frozenset(
    (
        *_CV,
        *NOTE_NOTIFICATION_TYPES,
        *_JOBS_TOAST,
        # Każde zdarzenie umowy w podpisie czeka na czyjś ruch.
        *_CONTRACTS,
        *(t for t in types_in_topic(_P.other) if t not in _OTHER_WITHOUT_TOAST),
    )
)


def enrich_realtime_event(event: Mapping[str, Any]) -> Mapping[str, Any]:
    """Ramka `notification` z gniazda dostaje `topic` i `toast` — kopia, nie mutacja.

    Siedmiu producentów wysyła ramki `type: "notification"`; temat dokładamy
    w jednym miejscu (`api/ws.py` `ConnectionManager.notify_user`). Typ
    nieznany tej wersji backendu (rozjazd przy wdrożeniu) to „inne” z dymkiem —
    lepiej pokazać niż zgubić.
    """
    if event.get("type") != "notification":
        return event
    data = event.get("data")
    if not isinstance(data, Mapping):
        return event
    try:
        ntype = NotificationType(data.get("notification_type"))
    except ValueError:
        topic, toast = _P.other, True
    else:
        topic, toast = topic_for(ntype), ntype in TOAST_TYPES
    return {**event, "data": {**data, "topic": topic.value, "toast": toast}}


# Rekrutacja, do której należy wiersz: ścieżka `/jobs/{id}`, parametr `?job=`
# (auto-match prowadzi na profil kandydata) albo encja „job”. Literały regexów
# zostają w SQL jako stałe — jako parametry wiązane w SELECT i GROUP BY
# dostałyby różne numery i Postgres odrzuciłby zapytanie (pułapka z czatów).
_JOB_PATH = "^/jobs/([0-9]{1,9})(?:[/?#]|$)"
_JOB_PARAM = "[?&]job=([0-9]{1,9})(?:&|#|$)"


def job_key_expression(model: Any) -> Any:
    return func.coalesce(
        cast(func.substring(model.link, literal_column(f"'{_JOB_PATH}'")), Integer),
        cast(func.substring(model.link, literal_column(f"'{_JOB_PARAM}'")), Integer),
        case(
            (model.related_entity_type == "job", model.related_entity_id),
            else_=None,
        ),
    )


__all__ = [
    "NOTE_NOTIFICATION_TYPES",
    "TOAST_TYPES",
    "TOPIC_BY_TYPE",
    "NotificationTopic",
    "enrich_realtime_event",
    "job_key_expression",
    "topic_for",
    "types_in_topic",
]
