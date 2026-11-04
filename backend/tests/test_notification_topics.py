"""Tematy powiadomień — ikony górnego paska zamiast dzwonka (16.10.2026).

Kontrakty statyczne, bez bazy: każdy typ ma temat, temat „Rozmowy” to
dokładnie kategoria „Rozmowy”, wzmianki z notatek idą do „Wiadomości”, ale
nie do krotki czatu (ta steruje kasowaniem wierszy przy usunięciu
wiadomości), a ramka gniazda dostaje temat i decyzję o dymku bez mutowania
oryginału.
"""

from sqlalchemy.dialects import postgresql

from app.models.notification import Notification, NotificationType
from app.services.mention_dispatch import CHAT_NOTIFICATION_TYPES
from app.services.notification_categories import NotificationCategory, types_in
from app.services.notification_topics import (
    NOTE_NOTIFICATION_TYPES,
    TOAST_TYPES,
    TOPIC_BY_TYPE,
    NotificationTopic,
    enrich_realtime_event,
    job_key_expression,
    topic_for,
    types_in_topic,
)

_T = NotificationType


def test_every_notification_type_has_a_topic():
    missing = set(NotificationType) - set(TOPIC_BY_TYPE)
    assert not missing, (
        "Nowy typ powiadomienia bez tematu nie trafiłby do żadnej ikony paska — "
        f"dopisz go do TOPIC_BY_TYPE: {sorted(t.value for t in missing)}"
    )


def test_every_topic_has_at_least_one_type():
    assert set(TOPIC_BY_TYPE.values()) == set(NotificationTopic)


def test_interviews_topic_is_exactly_the_interviews_category():
    # Okienko „Kalendarz” (dawniej „Rozmowy”) czyta kategorię — temat nie może
    # się z nią rozjechać.
    assert types_in_topic(NotificationTopic.interviews) == types_in(
        NotificationCategory.interviews
    )


def test_messages_are_chats_and_notes():
    messages = types_in_topic(NotificationTopic.messages)
    assert set(CHAT_NOTIFICATION_TYPES) | set(NOTE_NOTIFICATION_TYPES) == messages
    assert set(NOTE_NOTIFICATION_TYPES) == {_T.note_mention, _T.note_reply}


def test_note_types_stay_out_of_the_chat_tuple():
    # CHAT_NOTIFICATION_TYPES steruje `exclude_chat` i kasowaniem wierszy
    # (`retract_chat_message_notifications`) — notatka tam nie należy.
    assert not set(NOTE_NOTIFICATION_TYPES) & set(CHAT_NOTIFICATION_TYPES)


def test_cv_topic_is_the_agreed_set():
    assert types_in_topic(NotificationTopic.cv) == {
        _T.board_task_waiting,
        _T.cv_ready,
        _T.cpro_send_assigned,
    }


def test_my_people_topic_is_the_match_only():
    assert types_in_topic(NotificationTopic.my_people) == {_T.my_people_match}


def test_recruitment_moves_belong_to_jobs():
    for t in (
        _T.stage_rule,
        _T.request_assignment_changed,
        _T.job_deadline_1d,
        _T.champion_profile_updated,
        _T.auto_match_proposals,
        _T.recruiter_parked,
    ):
        assert topic_for(t) is NotificationTopic.jobs, t


def test_types_without_an_icon_are_other():
    for t in (
        _T.ai_spend_alert,
        _T.client_order_ending_7d,
        _T.candidate_search_completed,
        _T.marketplace_match,
        _T.board_tasks_digest,
    ):
        assert topic_for(t) is NotificationTopic.other, t


def test_contract_signing_events_have_the_contracts_icon():
    # 26.10.2026: podpis za firmę „nie przyszedł” — typ bez ikony dawał tylko
    # dymek. Umowy w podpisie mają własną ikonę „Umowy” i zostają z dymkiem.
    for t in (
        _T.signature_sent,
        _T.signature_signed,
        _T.signature_rejected,
        _T.signature_failed,
        _T.b2b_signature_requested,
        _T.b2b_agreement_ready,
    ):
        assert topic_for(t) is NotificationTopic.contracts, t
        assert t in TOAST_TYPES, t
    # Przedwstępna i „brak umowy przy zatrudnieniu” zostają w „Rekrutacjach”.
    assert topic_for(_T.pre_contract) is NotificationTopic.jobs
    assert topic_for(_T.hire_missing_contract) is NotificationTopic.jobs


def test_toast_policy():
    # Dymek tylko tam, gdzie ktoś czeka na ruch tej osoby albo nie ma innego
    # miejsca. Ruchy etapów, automat i terminy zmieniają tylko licznik ikony.
    for t in (
        _T.cv_ready,
        _T.board_task_waiting,
        _T.cpro_send_assigned,
        _T.request_assignment_changed,
        _T.recruiter_parked,
        _T.candidate_rate_change_task,
        _T.note_mention,
        _T.note_reply,
        _T.ai_spend_alert,
        _T.b2b_signature_requested,
        _T.candidate_search_completed,
    ):
        assert t in TOAST_TYPES, t
    for t in (
        _T.stage_rule,
        _T.auto_match_proposals,
        _T.job_deadline_1d,
        _T.champion_profile_updated,
        _T.my_people_match,
        _T.job_chat_message,  # czat ma własny dymek z `chat:notify`
        _T.interview_scheduled,  # okienko „Kalendarz” robi własne dymki
        _T.kpi_coach,  # `KpiNudgeToaster`
        _T.powercalling_kpi,
    ):
        assert t not in TOAST_TYPES, t


def test_client_accepted_is_a_recruitment_event_with_toast():
    # 0451 (16.10.2026): akceptacja klienta to wydarzenie rekrutacji — trafia
    # do ikony „Rekrutacje” (dzwonka już nie ma) i daje dymek całemu zespołowi.
    assert topic_for(_T.client_accepted) is NotificationTopic.jobs
    assert _T.client_accepted in TOAST_TYPES


def test_hire_without_contract_is_a_named_task_with_toast():
    # 0452 (17.10.2026): Delivery Lead ma wpisać umowę zatrudnionej osoby —
    # sprawa imienna w rekrutacji, więc ikona „Rekrutacje” i dymek.
    assert topic_for(_T.hire_missing_contract) is NotificationTopic.jobs
    assert _T.hire_missing_contract in TOAST_TYPES


def test_enrich_adds_topic_and_toast_without_mutating():
    frame = {
        "type": "notification",
        "data": {"id": 7, "notification_type": "cv_ready", "link": "/jobs/3"},
    }
    enriched = enrich_realtime_event(frame)
    assert enriched["data"]["topic"] == "cv"
    assert enriched["data"]["toast"] is True
    assert "topic" not in frame["data"]
    assert enriched is not frame


def test_enrich_unknown_type_falls_back_to_other_with_toast():
    frame = {"type": "notification", "data": {"notification_type": "z_przyszlosci"}}
    enriched = enrich_realtime_event(frame)
    assert enriched["data"]["topic"] == "other"
    assert enriched["data"]["toast"] is True


def test_enrich_leaves_other_events_untouched():
    frame = {"type": "pipeline_changed", "data": {"job_id": 1}}
    assert enrich_realtime_event(frame) is frame
    assert enrich_realtime_event({"type": "notification"}) == {"type": "notification"}


def test_job_key_reads_jobs_path_query_param_and_job_entity():
    sql = str(job_key_expression(Notification).compile(dialect=postgresql.dialect()))
    # Ścieżka /jobs/{id}, parametr ?job= (auto-match) i encja „job”.
    assert "^/jobs/([0-9]{1,9})" in sql
    assert "[?&]job=([0-9]{1,9})" in sql
    assert "related_entity_type" in sql


async def test_connection_manager_sends_frame_with_topic(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from app.api import ws

    manager = ws.ConnectionManager()
    socket = MagicMock()
    socket.send_json = AsyncMock()
    manager._connections[963852] = [socket]
    manager._auth_tokens[socket] = "valid-token"
    monkeypatch.setattr(ws, "_authenticate_ws_token", AsyncMock(return_value=object()))
    monkeypatch.setattr(ws, "user_can_receive_realtime_event", lambda _u, _e: True)

    frame = {
        "type": "notification",
        "data": {"notification_type": "stage_rule", "link": "/jobs/5?candidate=9"},
    }
    await manager.notify_user(963852, frame)

    sent = socket.send_json.await_args.args[0]
    assert sent["data"]["topic"] == "jobs"
    assert sent["data"]["toast"] is False
    assert "topic" not in frame["data"]


def test_topic_read_request_bounds_and_default_scope():
    import pytest
    from pydantic import ValidationError

    from app.api.notifications import TopicReadRequest

    # Kolumny to int4 — większa liczba to 422, nie 500 z bazy.
    with pytest.raises(ValidationError):
        TopicReadRequest(topic="jobs", job_id=10**12)
    with pytest.raises(ValidationError):
        TopicReadRequest(topic="jobs", ids=[10**12])
    # Domyślnie klik gasi też przypomnienia w zastępstwie (jak klik w dzwonku).
    assert TopicReadRequest(topic="jobs").include_covered is True
