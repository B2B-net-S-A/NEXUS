"""Kategorie powiadomień i wyciszenia per użytkownik (0349, 22.09.2026).

Powiadomień jest ~60 typów, więc każdy użytkownik wybiera w „Moje konto →
Powiadomienia" jedną z ~11 kategorii, nie typ techniczny. Mapa typ →
kategoria jest wyczerpująca (pilnuje ``test_notification_categories.py``):
nowy typ bez kategorii wywraca test, zamiast po cichu omijać wyciszenia.

Wyciszenia żyją w ``users.muted_notification_categories`` jako
``{kategoria: znacznik czasu wyciszenia}``. Znacznik służy jednemu: po
ponownym włączeniu kategorii powiadomienia utworzone w czasie wyciszenia
są oznaczane jako przeczytane, a wcześniejsze nieprzeczytane zostają.
„Cofnij" tuż po wyciszeniu nie gasi więc cudzej, starszej sprawy.

Wyciszenie działa w ``notification_access`` — tym samym miejscu, przez które
przechodzi każdy odczyt dzwonka, każde wypchnięcie przez WebSocket i każda
decyzja „czy wysłać" (``emit`` i pozostali producenci). Kategorie
obowiązkowe nie dają się wyciszyć ani przez API, ani przez stary zapis.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from app.models.notification import NotificationType


class NotificationCategory(StrEnum):
    mentions = "mentions"
    chat = "chat"
    pipeline = "pipeline"
    reminders = "reminders"
    deadlines = "deadlines"
    interviews = "interviews"
    candidates = "candidates"
    rejections = "rejections"
    contracts = "contracts"
    kpi = "kpi"
    system = "system"


@dataclass(frozen=True)
class CategoryInfo:
    label: str
    description: str
    mandatory: bool = False


# Kolejność = kolejność na stronie ustawień.
CATEGORY_INFO: dict[NotificationCategory, CategoryInfo] = {
    NotificationCategory.mentions: CategoryInfo(
        "Wzmianki (@)",
        "Ktoś oznaczył Cię w notatce lub na czacie albo wytypował Cię do zadania.",
        mandatory=True,
    ),
    NotificationCategory.interviews: CategoryInfo(
        "Rozmowy",
        "Umówione rozmowy, terminy od klienta, telefon do kandydata po rozmowie, debrief.",
        mandatory=True,
    ),
    NotificationCategory.chat: CategoryInfo(
        "Czat rekrutacji i kandydata",
        "Nowe wiadomości na czatach, w których bierzesz udział.",
    ),
    NotificationCategory.pipeline: CategoryInfo(
        "Ruchy w rekrutacjach",
        "Kandydat przesunięty na inny etap, dodany do rekrutacji, zmiana profilu Championa.",
    ),
    NotificationCategory.reminders: CategoryInfo(
        "Zaległości i przypomnienia",
        "Kandydat stoi na etapie od kilku dni, brak feedbacku, podpowiedź następnego kroku.",
    ),
    NotificationCategory.deadlines: CategoryInfo(
        "Terminy rekrutacji",
        "Do końca rekrutacji zostało 7, 3 albo 1 dzień.",
    ),
    NotificationCategory.candidates: CategoryInfo(
        "Nowi i pasujący kandydaci",
        "Propozycje z automatu, „Moi ludzie”, zapisane wyszukiwania, zgłoszenia z formularza.",
    ),
    NotificationCategory.rejections: CategoryInfo(
        "Maile z odmową",
        "Mail z odmową zaplanowany, wysłany, anulowany albo nieudany.",
    ),
    NotificationCategory.contracts: CategoryInfo(
        "Kontrakty, zamówienia i podpisy",
        "Koniec umowy lub zamówienia, brak kolejnego zamówienia, podpisy, zwrot sprzętu.",
    ),
    NotificationCategory.kpi: CategoryInfo(
        "KPI i coaching",
        "Power Calling i podpowiedzi coacha KPI.",
    ),
    NotificationCategory.system: CategoryInfo(
        "Konto i system",
        "Zmiana hasła, alarmy kosztów AI i awarie automatów.",
        mandatory=True,
    ),
}


_T = NotificationType
_C = NotificationCategory

CATEGORY_BY_TYPE: dict[NotificationType, NotificationCategory] = {
    # Wzmianki
    _T.job_chat_mention: _C.mentions,
    _T.note_mention: _C.mentions,
    # Ktoś wytypował Cię do wysłania osoby do Cpro — imienne zadanie, jak wzmianka.
    _T.cpro_send_assigned: _C.mentions,
    # Ktoś przekazał Ci kartę do przeglądu DL albo do kolejki Cpro — imienne
    # zadanie, na które czeka kandydat; nie da się go wyciszyć.
    _T.board_task_waiting: _C.mentions,
    # Rekruter czeka, aż potwierdzisz podpis jego umowy — imienne zadanie (0417).
    _T.b2b_signature_requested: _C.mentions,
    # 0418: zadanie DL po wzroście stawki — na DL czeka klient, nie do wyciszenia.
    _T.candidate_rate_change_task: _C.mentions,
    # Ktoś przejął Twoją osobę w „Nowych" — imienne, jak wzmianka.
    _T.candidate_claim_taken: _C.mentions,
    # Odpowiedź na Twoją notatkę — imienne, jak wzmianka (0399).
    _T.note_reply: _C.mentions,
    # Ktoś przydzielił Ci request (akceptacja propozycji automatu, poranne
    # „Od dziś: …”) — imienne zadanie, więc nie da się go wyciszyć.
    _T.request_assignment_changed: _C.mentions,
    # Czat
    _T.job_chat_message: _C.chat,
    # Ruchy w rekrutacjach
    _T.stage_changed: _C.pipeline,
    _T.stage_rule: _C.pipeline,
    _T.candidate_rate_change: _C.pipeline,
    _T.candidate_added: _C.pipeline,
    _T.champion_profile_updated: _C.pipeline,
    _T.pending_verification: _C.pipeline,
    # Zaległości i przypomnienia
    _T.stage_stuck_7d: _C.reminders,
    _T.dl_stage_stale_6h: _C.reminders,
    _T.client_feedback_eobd: _C.reminders,
    _T.candidate_feedback_1h: _C.reminders,
    _T.suggest_next_step: _C.reminders,
    _T.recruitment_allocation_alert: _C.reminders,
    _T.board_tasks_digest: _C.reminders,
    _T.request_review_needed: _C.reminders,
    # 0409: propozycje automatu przydziału czekają na akceptację.
    _T.request_allocation_proposals: _C.reminders,
    # Terminy rekrutacji
    _T.job_deadline_7d: _C.deadlines,
    _T.job_deadline_3d: _C.deadlines,
    _T.job_deadline_1d: _C.deadlines,
    # Rozmowy
    _T.interview_scheduled: _C.interviews,
    _T.post_interview_t15: _C.interviews,
    _T.post_interview_t45: _C.interviews,
    _T.post_interview_t2h_escalation: _C.interviews,
    _T.interview_slots_requested: _C.interviews,
    _T.interview_slot_chosen: _C.interviews,
    _T.interview_slot_confirmed: _C.interviews,
    _T.interview_debrief_saved: _C.interviews,
    _T.prep_attention: _C.interviews,
    # 0374: koniec programu praktykanta — decyzja Head of Recruitment.
    _T.trainee_program_decision: _C.kpi,
    # Nowi i pasujący kandydaci
    _T.new_application: _C.candidates,
    _T.application_screening_digest: _C.candidates,
    _T.candidate_followup_signal: _C.candidates,
    _T.match_digest: _C.candidates,
    _T.marketplace_match: _C.candidates,
    _T.similar_job_candidates: _C.candidates,
    _T.saved_search_match: _C.candidates,
    _T.saved_search_reapproval: _C.candidates,
    _T.auto_match: _C.candidates,
    _T.auto_match_proposals: _C.candidates,
    _T.my_people_match: _C.candidates,
    _T.candidate_search_completed: _C.candidates,
    # Maile z odmową
    _T.rejection_email_scheduled: _C.rejections,
    _T.rejection_email_sent: _C.rejections,
    _T.rejection_email_cancelled: _C.rejections,
    _T.rejection_email_skipped: _C.rejections,
    _T.rejection_email_failed: _C.rejections,
    # Kontrakty, zamówienia i podpisy
    _T.contract_ending: _C.contracts,
    _T.contract_ending_90d: _C.contracts,
    _T.contract_activated: _C.contracts,
    _T.equipment_return_due_14d: _C.contracts,
    _T.client_order_ending_30d: _C.contracts,
    _T.client_order_ending_14d: _C.contracts,
    _T.client_order_ending_7d: _C.contracts,
    _T.order_missing_successor: _C.contracts,
    _T.hired_order_missing: _C.contracts,
    _T.framework_contract_expiring_30d: _C.contracts,
    _T.framework_contract_expiring_14d: _C.contracts,
    _T.framework_contract_expiring_7d: _C.contracts,
    _T.framework_contract_signed: _C.contracts,
    _T.signature_sent: _C.contracts,
    _T.signature_signed: _C.contracts,
    _T.signature_rejected: _C.contracts,
    _T.signature_failed: _C.contracts,
    # KPI
    _T.powercalling_kpi: _C.kpi,
    _T.kpi_coach: _C.kpi,
    # Konto i system
    _T.password_reset_requested: _C.system,
    _T.password_changed_by_admin: _C.system,
    _T.ai_spend_alert: _C.system,
    _T.automation_failing: _C.system,
}


def category_for(notification_type: NotificationType) -> NotificationCategory:
    return CATEGORY_BY_TYPE[notification_type]


# ── Grupy: wiersze tabeli „Kto co dostaje” (rola × grupa, 09.10.2026) ────────
#
# Administrator wyłącza powiadomienia całej roli. Kategoria bywa na to za
# gruba: „Kontrakty…” niosą naraz koniec zamówień (1 111 wpisów w 30 dni do
# adminów) i podpisy umów, a „Zaległości…” — „kandydat stoi 6 h” i poranny
# skrót. Grupa jest więc kategorią albo jej nazwanym kawałkiem. Wyciszenia
# OSOBY zostają na poziomie kategorii.


@dataclass(frozen=True)
class GroupInfo:
    label: str
    category: NotificationCategory


# Kategorie dzielone na kawałki: klucz grupy → (etykieta, kategoria, typy).
# Typ kategorii nieobecny w żadnym kawałku wywraca test wyczerpujący.
_SPLIT_GROUPS: dict[
    str, tuple[str, NotificationCategory, tuple[NotificationType, ...]]
] = {
    "reminders_stage_6h": (
        "Kandydat stoi na etapie 6 h",
        _C.reminders,
        (_T.dl_stage_stale_6h,),
    ),
    "reminders_stage_7d": (
        "Kandydat stoi na etapie 7 dni",
        _C.reminders,
        (_T.stage_stuck_7d,),
    ),
    "reminders_board_digest": (
        "Skrót „Czeka na Ciebie” w dzwonku",
        _C.reminders,
        (_T.board_tasks_digest,),
    ),
    "reminders_next_step": (
        "Podpowiedź następnego kroku, brak feedbacku",
        _C.reminders,
        (_T.suggest_next_step, _T.client_feedback_eobd, _T.candidate_feedback_1h),
    ),
    "reminders_requests": (
        "Przydział requestów",
        _C.reminders,
        (
            _T.recruitment_allocation_alert,
            _T.request_review_needed,
            _T.request_allocation_proposals,
        ),
    ),
    "contracts_order_ending": (
        "Koniec zamówienia za 30 / 14 / 7 dni",
        _C.contracts,
        (
            _T.client_order_ending_30d,
            _T.client_order_ending_14d,
            _T.client_order_ending_7d,
        ),
    ),
    "contracts_contract_ending": (
        "Koniec umowy",
        _C.contracts,
        (_T.contract_ending, _T.contract_ending_90d),
    ),
    "contracts_activated": (
        "Umowa aktywowana, nowy szkic kontraktu",
        _C.contracts,
        (_T.contract_activated,),
    ),
    "contracts_framework": (
        "Umowa ramowa",
        _C.contracts,
        (
            _T.framework_contract_expiring_30d,
            _T.framework_contract_expiring_14d,
            _T.framework_contract_expiring_7d,
            _T.framework_contract_signed,
        ),
    ),
    "contracts_missing_order": (
        "Brak zamówienia",
        _C.contracts,
        (_T.order_missing_successor, _T.hired_order_missing),
    ),
    "contracts_signatures": (
        "Podpisy i zwrot sprzętu",
        _C.contracts,
        (
            _T.signature_sent,
            _T.signature_signed,
            _T.signature_rejected,
            _T.signature_failed,
            _T.equipment_return_due_14d,
        ),
    ),
}

_SPLIT_CATEGORIES = frozenset(category for _, category, _ in _SPLIT_GROUPS.values())


def _build_groups() -> tuple[dict[str, GroupInfo], dict[NotificationType, str]]:
    info: dict[str, GroupInfo] = {}
    by_type: dict[NotificationType, str] = {}
    for category, category_info in CATEGORY_INFO.items():
        if category not in _SPLIT_CATEGORIES:
            info[category.value] = GroupInfo(category_info.label, category)
            continue
        for key, (label, split_category, types) in _SPLIT_GROUPS.items():
            if split_category != category:
                continue
            info[key] = GroupInfo(label, category)
            for notification_type in types:
                by_type[notification_type] = key
    for notification_type, category in CATEGORY_BY_TYPE.items():
        if category not in _SPLIT_CATEGORIES:
            by_type[notification_type] = category.value
    return info, by_type


# Kolejność = kolejność wierszy tabeli (kategorie jak na stronie ustawień).
GROUP_INFO, GROUP_BY_TYPE = _build_groups()


def types_in_group(group: str) -> frozenset[NotificationType]:
    return frozenset(t for t, g in GROUP_BY_TYPE.items() if g == group)


def group_is_mutable(group: str) -> bool:
    info = GROUP_INFO.get(group)
    return info is not None and is_mutable(info.category)


def types_in(category: NotificationCategory) -> frozenset[NotificationType]:
    return frozenset(t for t, c in CATEGORY_BY_TYPE.items() if c == category)


def is_mutable(category: NotificationCategory) -> bool:
    return not CATEGORY_INFO[category].mandatory


def muted_categories(raw: Mapping[str, Any] | None) -> frozenset[NotificationCategory]:
    """Kategorie faktycznie wyciszone — bez obowiązkowych i nieznanych kluczy.

    Zapis bywa starszy niż kod (kategorię przemianowano, zrobiono ją
    obowiązkową), więc czytamy go łagodnie i nigdy nie wyciszamy kategorii,
    której dziś wyciszyć nie wolno.
    """
    if not isinstance(raw, Mapping):
        return frozenset()
    result: set[NotificationCategory] = set()
    for key in raw:
        try:
            category = NotificationCategory(key)
        except ValueError:
            continue
        if is_mutable(category):
            result.add(category)
    return frozenset(result)


def muted_types_for(raw: Mapping[str, Any] | None) -> frozenset[NotificationType]:
    return frozenset(
        t for t, c in CATEGORY_BY_TYPE.items() if c in muted_categories(raw)
    )


def user_muted_types(user: Any) -> frozenset[NotificationType]:
    """Typy wyciszone przez użytkownika (pusty zbiór dla obiektów bez pola)."""
    return muted_types_for(getattr(user, "muted_notification_categories", None))
