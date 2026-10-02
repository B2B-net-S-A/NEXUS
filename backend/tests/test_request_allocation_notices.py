"""Przypomnienie „Klient milczy” co 14 dni — od ostatniego wysłania (audyt 24.09.2026).

Stara reguła ``dni % 14 == 0`` gubiła przypomnienie na kolejne 14 dni, gdy
poranny przebieg nie wypadł dokładnie w 14. dniu (pętla stała, deploy).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.request_allocation_notices import (
    is_stale_check_day,
    silent_reminder_due,
)

NOW = datetime(2026, 9, 24, 8, 30, tzinfo=timezone.utc)


@pytest.mark.unit
def test_first_reminder_after_14_days_even_when_day_14_was_missed() -> None:
    since = NOW - timedelta(days=15)  # 14. dzień bez porannego przebiegu
    assert silent_reminder_due(NOW, since, None) is True
    assert silent_reminder_due(NOW, NOW - timedelta(days=13), None) is False


@pytest.mark.unit
def test_next_reminder_counts_from_the_last_one_sent() -> None:
    since = NOW - timedelta(days=40)
    assert (
        silent_reminder_due(NOW, since, (NOW - timedelta(days=13)).isoformat()) is False
    )
    assert (
        silent_reminder_due(NOW, since, (NOW - timedelta(days=15)).isoformat()) is True
    )


@pytest.mark.unit
def test_reminder_from_a_previous_silent_episode_does_not_count() -> None:
    since = NOW - timedelta(days=14)
    previous_episode = (since - timedelta(days=3)).isoformat()
    assert silent_reminder_due(NOW, since, previous_episode) is True


@pytest.mark.unit
def test_no_start_date_means_no_reminder() -> None:
    assert silent_reminder_due(NOW, None, None) is False


@pytest.mark.unit
def test_monday_stale_check_uses_the_business_calendar_not_utc() -> None:
    """R5-7: przegląd o 00:30 w Warszawie w poniedziałek to niedziela w UTC."""
    monday_0030_warsaw = datetime(2026, 9, 27, 22, 30, tzinfo=timezone.utc)
    assert monday_0030_warsaw.weekday() == 6  # niedziela w UTC
    assert is_stale_check_day(monday_0030_warsaw) is True
    tuesday_0030_warsaw = datetime(2026, 9, 28, 22, 30, tzinfo=timezone.utc)
    assert tuesday_0030_warsaw.weekday() == 0  # poniedziałek w UTC
    assert is_stale_check_day(tuesday_0030_warsaw) is False
    assert is_stale_check_day(datetime(2026, 9, 28, 8, 0, tzinfo=timezone.utc)) is True


# ── Adresat „Requestów do decyzji” (runda 6 audytu) ─────────────────────────


@pytest.mark.unit
def test_inactive_or_missing_delivery_lead_escalates_to_head_of_recruitment() -> None:
    from app.services.request_allocation_notices import route_to_recipients

    assert route_to_recipients(7, {7}, [90, 91]) == [7]
    # Nieaktywny DL = jak brak DL-a — lustro `_delivery_lead_targets`.
    assert route_to_recipients(7, set(), [90, 91]) == [90, 91]
    assert route_to_recipients(None, {7}, [90]) == [90]


class _Rows:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)


class _FakeDb:
    """Pierwsze ``execute`` = wiersze rekrutacji, ``scalars`` = aktywni DL-e,
    potem Head of Recruitment."""

    def __init__(self, rows, active_leads, hor):
        self._rows = rows
        self._scalars = [active_leads, hor]

    async def execute(self, _statement):
        return _Rows(self._rows)

    async def scalars(self, _statement):
        return _Rows(self._scalars.pop(0))


@pytest.mark.asyncio
async def test_silent_reminder_for_inactive_lead_goes_to_hor_and_is_remembered(
    monkeypatch,
) -> None:
    from app.services import notification_triggers
    from app.services.request_allocation_notices import _review_notices

    sent: list[int] = []

    async def emit(db, **kwargs):
        sent.append(kwargs["user_id"])
        return object()

    monkeypatch.setattr(notification_triggers, "emit", emit)
    tuesday = datetime(2026, 9, 29, 7, 0, tzinfo=timezone.utc)
    rows = [(42, 7, "client_silent", tuesday - timedelta(days=40), None)]
    count, reminded = await _review_notices(
        _FakeDb(rows, active_leads=[], hor=[90]), now=tuesday, reminded={}
    )
    assert sent == [90]
    assert count == 1
    # Zapamiętane — jutro nie wraca (dotąd przepadało codziennie).
    assert reminded == {"42": tuesday.isoformat()}


# ── Dzwonek „propozycje czekają” dla Head of Recruitment (02.10.2026) ───────


class _NoticeDb:
    """``scalar`` = dzisiejszy wpis odbiorcy (albo ``None``)."""

    def __init__(self, existing=None):
        self._existing = existing

    async def scalar(self, _statement):
        return self._existing


def _patch_proposal_notices(monkeypatch, *, pending: int, created: bool):
    from types import SimpleNamespace

    from app.services import (
        notification_triggers,
        request_allocation_notices,
        request_allocation_proposals,
    )

    calls: list[dict] = []

    async def load_pending(_db):
        return [object()] * pending

    async def emit(_db, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace() if created else None

    async def recipients(_db):
        return [90, 91]

    monkeypatch.setattr(request_allocation_proposals, "load_pending", load_pending)
    monkeypatch.setattr(notification_triggers, "emit", emit)
    monkeypatch.setattr(
        request_allocation_notices, "_head_of_recruitment_ids", recipients
    )
    return calls


@pytest.mark.asyncio
async def test_no_pending_proposals_means_no_notice(monkeypatch) -> None:
    from app.services.request_allocation_notices import send_proposal_notices

    calls = _patch_proposal_notices(monkeypatch, pending=0, created=True)
    assert await send_proposal_notices(_NoticeDb(), new_proposals=True) == 0
    assert calls == []


@pytest.mark.asyncio
async def test_first_proposal_of_the_day_notifies_every_head_of_recruitment(
    monkeypatch,
) -> None:
    from app.models.notification import NotificationType
    from app.services.request_allocation_notices import (
        PROPOSALS_LINK,
        send_proposal_notices,
    )

    calls = _patch_proposal_notices(monkeypatch, pending=3, created=True)
    assert await send_proposal_notices(_NoticeDb(), new_proposals=True) == 2
    assert [c["user_id"] for c in calls] == [90, 91]
    for call in calls:
        assert call["title"] == "Propozycje przydziału do akceptacji: 3"
        assert call["ntype"] is NotificationType.request_allocation_proposals
        # Jeden wpis dziennie na odbiorcę — klucz dedupu to sam odbiorca.
        assert call["related_entity_type"] == "user"
        assert call["related_entity_id"] == call["user_id"]
        assert call["link"] == PROPOSALS_LINK == "/dashboard#czeka-na-ciebie"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("old_title", "new_proposals", "bumped"),
    [
        # Liczba się zmieniła — ten sam wpis wraca jako nieprzeczytany.
        ("Propozycje przydziału do akceptacji: 2", False, True),
        # Poranne przypomnienie z tą samą liczbą nie dzwoni drugi raz.
        ("Propozycje przydziału do akceptacji: 3", False, False),
        # Jedna zaakceptowana, jedna nowa: liczba ta sama, sprawa nowa.
        ("Propozycje przydziału do akceptacji: 3", True, True),
    ],
)
async def test_same_day_notice_is_bumped_instead_of_duplicated(
    monkeypatch, old_title: str, new_proposals: bool, bumped: bool
) -> None:
    from types import SimpleNamespace

    from app.services import request_allocation_notices
    from app.services.request_allocation_notices import send_proposal_notices

    _patch_proposal_notices(monkeypatch, pending=3, created=False)
    pushed: list[dict] = []

    def queue(_db, *, user_id, event_payload, row):
        pushed.append({"user_id": user_id, "payload": event_payload, "row": row})
        return True

    monkeypatch.setattr(request_allocation_notices, "queue_ws_notification", queue)
    existing = SimpleNamespace(
        id=7,
        title=old_title,
        message="Automat zaproponował osoby do requestów.",
        link="/dashboard#czeka-na-ciebie",
        is_read=True,
    )
    sent = await send_proposal_notices(_NoticeDb(existing), new_proposals=new_proposals)
    # Dwóch odbiorców, atrapa oddaje im ten sam wpis — po pierwszym podbiciu
    # tytuł już się zgadza, więc drugi liczy się tylko przy nowej propozycji.
    assert (sent > 0) is bumped
    assert existing.is_read is (not bumped)
    assert existing.title == "Propozycje przydziału do akceptacji: 3"
    # Podbicie dzwoni też w otwartej karcie: po odrzuceniu propozycji automat
    # proponuje następną osobę tego samego dnia, a pulpit ma ją pokazać od
    # razu. Zdarzenie idzie po commicie, przypięte do podbitego wiersza.
    assert len(pushed) == sent
    for item in pushed:
        assert item["row"] is existing
        assert item["payload"]["type"] == "notification"
        data = item["payload"]["data"]
        assert data["id"] == 7
        assert data["notification_type"] == "request_allocation_proposals"
        assert data["title"] == "Propozycje przydziału do akceptacji: 3"
        assert data["link"] == "/dashboard#czeka-na-ciebie"


@pytest.mark.asyncio
async def test_recipient_without_access_gets_nothing(monkeypatch) -> None:
    from app.services.request_allocation_notices import send_proposal_notices

    # ``emit`` odmówił (brak dostępu), a dzisiejszego wpisu nie ma.
    _patch_proposal_notices(monkeypatch, pending=3, created=False)
    assert await send_proposal_notices(_NoticeDb(None), new_proposals=True) == 0


@pytest.mark.asyncio
async def test_withdrawn_proposal_is_not_announced_as_a_taken_away_request(
    monkeypatch,
) -> None:
    """Do akceptacji nikt nie jest przypisany — osoba, której propozycję
    odrzucono, nie może rano przeczytać „Zwolnione: …”."""
    from app.services import notification_triggers
    from app.services.request_allocation_notices import _assignment_notices

    sent: list[dict] = []

    async def emit(db, **kwargs):
        sent.append(kwargs)
        return object()

    monkeypatch.setattr(notification_triggers, "emit", emit)
    now = datetime(2026, 10, 2, 7, 0, tzinfo=timezone.utc)
    rows = [
        # (osoba, rekrutacja, stan, przypisano, zwolniono, powód, tytuł)
        (7, 1, "released", now, now, "proposal:rejected", "Java"),
        (7, 2, "released", now, now, "proposal:superseded", "Kotlin"),
        (8, 3, "released", now, now, "champion", "Tester"),
        (8, 4, "active", now, None, None, "DevOps"),
    ]
    count = await _assignment_notices(_SeqDb(rows, []), now=now)
    assert count == 1
    assert [call["user_id"] for call in sent] == [8]
    assert sent[0]["message"] == "Od dziś: DevOps. Zwolnione: Tester (Mamy championa)."


class _SeqDb:
    """Kolejne ``execute`` oddają kolejne zestawy wierszy."""

    def __init__(self, *results):
        self._results = list(results)

    async def execute(self, _statement):
        return _Rows(self._results.pop(0))


@pytest.mark.asyncio
async def test_morning_digest_skips_requests_already_announced_on_the_spot(
    monkeypatch,
) -> None:
    """Zaakceptowana propozycja dzwoni od razu („Nowy request do pracy”).

    W trybie ``auto`` poranny skrót czytał każde aktywne przypisanie z ostatniej
    doby, więc ta sama osoba dostawała rano drugą wzmiankę o tym samym
    requeście.
    """
    from app.services import notification_triggers
    from app.services.request_allocation_notices import _assignment_notices

    sent: list[dict] = []

    async def emit(db, **kwargs):
        sent.append(kwargs)
        return object()

    monkeypatch.setattr(notification_triggers, "emit", emit)
    now = datetime(2026, 10, 2, 7, 0, tzinfo=timezone.utc)
    rows = [
        (8, 4, "active", now, None, None, "DevOps"),
        (8, 5, "active", now, None, None, "Java"),
        (9, 4, "active", now, None, None, "DevOps"),
    ]
    # Osoba 8 dostała już dzwonek o rekrutacji 4; osoba 9 — o żadnej.
    count = await _assignment_notices(_SeqDb(rows, [(8, 4)]), now=now)
    assert count == 2
    assert {call["user_id"]: call["message"] for call in sent} == {
        8: "Od dziś: Java.",
        9: "Od dziś: DevOps.",
    }


@pytest.mark.asyncio
async def test_morning_digest_is_silent_when_everything_was_announced(
    monkeypatch,
) -> None:
    from app.services import notification_triggers
    from app.services.request_allocation_notices import _assignment_notices

    sent: list[dict] = []

    async def emit(db, **kwargs):
        sent.append(kwargs)
        return object()

    monkeypatch.setattr(notification_triggers, "emit", emit)
    now = datetime(2026, 10, 2, 7, 0, tzinfo=timezone.utc)
    rows = [(8, 4, "active", now, None, None, "DevOps")]
    assert await _assignment_notices(_SeqDb(rows, [(8, 4)]), now=now) == 0
    assert sent == []


# ── Pora porannego przeglądu (02.10.2026) ───────────────────────────────────


@pytest.mark.unit
def test_morning_review_is_not_sent_in_the_evening() -> None:
    """Automat włączony wieczorem (albo pierwszy przebieg po deployu o 20:54)
    wysyłał „poranny” skrót od razu. Po 17:00 czasu firmy skrót czeka do rana."""
    from app.services.request_allocation import _review_due
    from app.services.request_allocation_rules import AllocationRules

    rules = AllocationRules()  # przegląd o 08:30

    def at(hour: int, minute: int) -> datetime:
        # 02.10.2026: Warszawa = UTC+2.
        return datetime(2026, 10, 2, hour - 2, minute, tzinfo=timezone.utc)

    assert _review_due({}, rules, at(8, 0)) is False
    assert _review_due({}, rules, at(8, 30)) is True
    # Pętla stała rano (deploy) — nadrabia w ciągu dnia pracy.
    assert _review_due({}, rules, at(16, 59)) is True
    assert _review_due({}, rules, at(17, 0)) is False
    assert _review_due({}, rules, at(20, 54)) is False
    assert _review_due({"last_review_date": "2026-10-02"}, rules, at(10, 0)) is False
    # Wczorajszy przegląd nie liczy się za dzisiejszy.
    assert _review_due({"last_review_date": "2026-10-01"}, rules, at(10, 0)) is True


@pytest.mark.unit
def test_review_time_set_after_working_hours_still_fires() -> None:
    """Godzinę przeglądu ustawia admin — późna pora nie może wyłączyć skrótu."""
    from app.services.request_allocation import _review_due
    from app.services.request_allocation_rules import AllocationRules

    rules = AllocationRules(review_time="18:00")
    assert (
        _review_due({}, rules, datetime(2026, 10, 2, 15, 59, tzinfo=timezone.utc))
        is False
    )
    assert (
        _review_due({}, rules, datetime(2026, 10, 2, 16, 30, tzinfo=timezone.utc))
        is True
    )


# ── Dzwonek od razu po przydziale (02.10.2026) ──────────────────────────────


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _PairsDb(_FakeDb):
    def begin_nested(self):
        return _Savepoint()


@pytest.mark.asyncio
async def test_assigned_pairs_get_one_bell_each_and_a_failed_bell_stops_nothing(
    monkeypatch,
) -> None:
    from app.models.notification import NotificationType
    from app.services import notification_triggers
    from app.services.request_allocation_notices import notify_assigned_pairs

    sent: list[dict] = []

    async def emit(db, **kwargs):
        if kwargs["user_id"] == 7:
            raise RuntimeError("baza odmówiła")
        sent.append(kwargs)
        return object()

    monkeypatch.setattr(notification_triggers, "emit", emit)
    # (request, tytuł, klient)
    rows = [(10, "Java Developer", "Bank"), (11, "Tester", None)]
    db = _PairsDb(rows, active_leads=[], hor=[])
    # Para powtórzona w przebiegu i request, którego już nie ma, nie dzwonią.
    await notify_assigned_pairs(db, [(10, 7), (10, 8), (11, 8), (10, 8), (99, 8)])
    assert [(call["user_id"], call["related_entity_id"]) for call in sent] == [
        (8, 10),
        (8, 11),
    ]
    assert sent[0]["title"] == "Nowy request do pracy"
    assert sent[0]["message"] == "Java Developer · Bank"
    assert sent[1]["message"] == "Tester"
    for call in sent:
        assert call["ntype"] is NotificationType.request_assignment_changed
        assert call["related_entity_type"] == "job"
        assert call["link"] == f"/jobs/{call['related_entity_id']}"
