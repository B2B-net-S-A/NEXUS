"""Przypomnienia o brakujących ogłoszeniach (27.10.2026) — czyste reguły.

Kto robi który kanał, kiedy rekrutacja idzie osobnym mailem, a kiedy
zbiorczym, i co niesie karta maila. Bez bazy.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.models.user import UserRole
from app.services.email import render_card_email
from app.services.job_ad import reminders as r

DL = 1
REC = 2
REC2 = 3
HOR = 9
WARSAW = ZoneInfo("Europe/Warsaw")
TODAY = date(2026, 10, 28)
CUTOFF = datetime(2026, 10, 27, 18, 0, tzinfo=timezone.utc)
NAMES = {DL: "Martyna Wiśniewska", REC: "Julia Sowa", REC2: "Ola Kowal"}


def _status(
    *,
    job_id: int = 789139,
    opened_at: datetime | None = datetime(2026, 10, 19, 9, tzinfo=timezone.utc),
    leads: tuple[int, ...] = (DL,),
    recruiters: tuple[int, ...] = (REC,),
    career_live: datetime | None = None,
    portals: dict | None = None,
    skips: dict | None = None,
    has_ad: bool = True,
) -> r.JobAdStatus:
    return r.JobAdStatus(
        job_id=job_id,
        title="Programista Integracji ZOB-3070",
        client="Bank",
        opened_at=opened_at,
        leads=leads,
        delivery_lead_id=leads[0] if leads == (DL,) else None,
        recruiter_ids=recruiters,
        has_ad=has_ad,
        channels=r.channel_states(
            career_live=career_live,
            portals_live=portals or {},
            skips=skips or {},
            recruiter_ids=recruiters,
            leads=leads,
        ),
        names=dict(NAMES),
    )


# ── Kto robi który kanał ─────────────────────────────────────────────────────


def test_career_belongs_to_recruiters_and_portals_to_the_lead() -> None:
    s = _status(recruiters=(REC, REC2))
    assert s.channel("kariera").owners == (REC, REC2)
    assert s.channel("pracuj").owners == (DL,)
    assert s.channel("jjit").owners == (DL,)


def test_without_recruiter_the_lead_publishes_the_career_page() -> None:
    s = _status(recruiters=())
    assert s.channel("kariera").owners == (DL,)


def test_live_and_skipped_channels_are_not_missing() -> None:
    at = datetime(2026, 10, 22, 8, tzinfo=timezone.utc)
    s = _status(
        portals={"pracuj": at},
        skips={"jjit": ("Klient nie chce JustJoin.IT", DL, at)},
    )
    assert [c.channel for c in s.missing] == ["kariera"]
    assert s.channel("pracuj").state == "live"
    assert s.channel("jjit").state == "skipped"
    assert s.channel("jjit").skip_reason == "Klient nie chce JustJoin.IT"


def test_recruiter_is_concerned_only_by_the_career_page() -> None:
    at = datetime(2026, 10, 22, 8, tzinfo=timezone.utc)
    done_career = _status(career_live=at)
    assert done_career.concerns(DL)
    assert not done_career.concerns(REC)
    all_done = _status(career_live=at, portals={"pracuj": at, "jjit": at})
    assert not all_done.concerns(DL)
    assert not all_done.concerns(REC)


# ── Kiedy ────────────────────────────────────────────────────────────────────


def test_due_now_only_on_business_days_from_eight_once_a_day() -> None:
    morning = datetime(2026, 10, 28, 8, 5, tzinfo=WARSAW)
    assert r.due_now(morning, None)
    assert not r.due_now(morning, "2026-10-28")
    assert r.due_now(morning, "2026-10-27")
    assert not r.due_now(datetime(2026, 10, 28, 7, 55, tzinfo=WARSAW), None)
    assert not r.due_now(datetime(2026, 10, 28, 17, 0, tzinfo=WARSAW), None)
    # Sobota i Wszystkich Świętych (niedziela 1.11 i tak) — bez wysyłki.
    assert not r.due_now(datetime(2026, 10, 31, 9, 0, tzinfo=WARSAW), None)


def test_first_reminder_comes_the_day_after_opening() -> None:
    opened = datetime(2026, 10, 28, 7, tzinfo=timezone.utc)  # 9:00 w Warszawie
    assert not r.due_today(opened, TODAY)
    assert r.due_today(opened, date(2026, 10, 29))


def test_jobs_opened_after_launch_are_new_older_go_to_backlog() -> None:
    assert r.is_new(datetime(2026, 10, 28, 6, tzinfo=timezone.utc), CUTOFF)
    assert not r.is_new(datetime(2026, 10, 19, 9, tzinfo=timezone.utc), CUTOFF)
    assert not r.is_new(None, CUTOFF)
    assert not r.is_new(datetime(2026, 10, 28, 6, tzinfo=timezone.utc), None)


def test_plan_day_splits_new_jobs_from_backlog() -> None:
    old = _status(job_id=1)
    new = _status(job_id=2, opened_at=datetime(2026, 10, 27, 19, tzinfo=timezone.utc))
    fresh = _status(job_id=3, opened_at=datetime(2026, 10, 28, 6, tzinfo=timezone.utc))
    done = _status(
        job_id=4,
        career_live=CUTOFF,
        portals={"pracuj": CUTOFF, "jjit": CUTOFF},
        opened_at=datetime(2026, 10, 27, 19, tzinfo=timezone.utc),
    )
    per_job, backlog = r.plan_day([old, new, fresh, done], cutoff=CUTOFF, today=TODAY)
    assert sorted((uid, s.job_id) for uid, s in per_job) == [(DL, 2), (REC, 2)]
    assert backlog == {DL: 1, REC: 1}


def test_recruiter_gets_no_per_job_reminder_when_only_portals_are_missing() -> None:
    new = _status(
        job_id=2,
        opened_at=datetime(2026, 10, 27, 19, tzinfo=timezone.utc),
        career_live=CUTOFF,
    )
    per_job, _ = r.plan_day([new], cutoff=CUTOFF, today=TODAY)
    assert [uid for uid, _ in per_job] == [DL]


def test_head_of_recruitment_leads_a_job_without_delivery_lead() -> None:
    new = _status(
        job_id=2,
        opened_at=datetime(2026, 10, 27, 19, tzinfo=timezone.utc),
        leads=(HOR,),
        recruiters=(),
    )
    per_job, _ = r.plan_day([new], cutoff=CUTOFF, today=TODAY)
    assert [uid for uid, _ in per_job] == [HOR]
    assert new.channel("kariera").owners == (HOR,)


# ── Karty maili ──────────────────────────────────────────────────────────────


def test_lead_card_lists_three_channels_and_opens_each_from_the_mail() -> None:
    card = r.lead_card(_status(), DL, TODAY)
    assert card is not None
    assert card.title == "Rekrutacja nie ma jeszcze żadnego ogłoszenia"
    assert card.subject == "[NEXUS] Wstaw ogłoszenia · Programista Integracji ZOB-3070"
    facts = dict(card.facts)
    assert facts["Strona kariery"] == "✗ brak · robi Julia S., 9 dni"
    assert facts["Pracuj.pl"] == "✗ brak · robisz Ty"
    assert facts["JustJoin.IT"] == "✗ brak · robisz Ty"
    assert [(b.label, b.path, b.style) for b in card.buttons] == [
        ("Wstaw na JustJoin.IT", "/jobs/789139?ogloszenie=jjit", "primary"),
        ("Wstaw na Pracuj.pl", "/jobs/789139?ogloszenie=pracuj", "secondary"),
        (
            "Przypomnij: Julia S.",
            "/jobs/789139?ogloszenie=kariera&przypomnij=rekruter",
            "secondary",
        ),
        ("Nie publikujemy tej rekrutacji", "/jobs/789139?ogloszenie=pomin", "neg"),
    ]
    assert card.required


def test_lead_card_when_only_the_recruiter_is_late() -> None:
    at = datetime(2026, 10, 22, 8, tzinfo=timezone.utc)
    card = r.lead_card(_status(portals={"pracuj": at, "jjit": at}), DL, TODAY)
    assert card is not None
    assert card.action == "Przypilnuj strony kariery"
    assert card.chip == "Czeka na rekrutera"
    assert not card.waiting
    assert card.buttons[0].label == "Przypomnij: Julia S."
    assert card.buttons[0].style == "primary"
    assert dict(card.facts)["Pracuj.pl"] == "✓ wisi od 22.10"


def test_lead_card_shows_skip_reason_and_nothing_when_all_done() -> None:
    at = datetime(2026, 10, 22, 8, tzinfo=timezone.utc)
    s = _status(
        career_live=at,
        portals={"pracuj": at},
        skips={"jjit": ("Klient nie chce JustJoin.IT", DL, at)},
    )
    assert r.lead_card(s, DL, TODAY) is None
    s2 = _status(portals={"pracuj": at}, skips={"jjit": ("Klient nie chce", DL, at)})
    card = r.lead_card(s2, DL, TODAY)
    assert card is not None
    assert dict(card.facts)["JustJoin.IT"] == "— nie publikujemy: Klient nie chce"


def test_recruiter_card_only_for_the_career_page_owner() -> None:
    s = _status()
    card = r.recruiter_card(s, REC, TODAY)
    assert card is not None
    assert card.subject.startswith("[NEXUS] Opublikuj na stronie kariery · ")
    assert [(b.label, b.path) for b in card.buttons] == [
        ("Opublikuj na stronie kariery", "/jobs/789139?ogloszenie=kariera")
    ]
    assert dict(card.facts)["Delivery Lead"] == "Martyna W."
    assert r.recruiter_card(s, REC2, TODAY) is None
    live = _status(career_live=datetime(2026, 10, 22, tzinfo=timezone.utc))
    assert r.recruiter_card(live, REC, TODAY) is None


def test_recruiter_card_without_content_says_how_to_prepare_it() -> None:
    card = r.recruiter_card(_status(has_ad=False), REC, TODAY)
    assert card is not None
    assert "ułożysz jednym kliknięciem" in card.text


def test_nudge_names_who_asked() -> None:
    message = r.nudge_message("Martyna Wiśniewska")
    assert message.startswith("Prosi: Martyna W.")
    card = r.recruiter_card(_status(), REC, TODAY, asked_by=r._asked_by(message))
    assert card is not None
    assert card.chip == "Prośba od DL-a"
    assert "Martyna W. prosi Cię o to dziś." in card.text


def test_backlog_card_lists_newest_first_and_counts_channels() -> None:
    at = datetime(2026, 10, 22, 8, tzinfo=timezone.utc)
    rows = [
        _status(
            job_id=100 + i,
            opened_at=datetime(2026, 9, 1 + i, tzinfo=timezone.utc),
            portals={"pracuj": at} if i % 2 else {},
        )
        for i in range(10)
    ]
    card = r.backlog_card(rows, DL)
    assert card is not None
    assert card.about == "10 rekrutacji sprzed startu przypomnień"
    assert card.buttons[0].path == r.BACKLOG_LINK
    assert len(card.facts) == r.BACKLOG_LISTED + 1
    assert card.facts[-1] == ("…", "i 2 starszych")
    assert "strona kariery w 10, Pracuj.pl w 5, JustJoin.IT w 10" in card.text
    # Najnowsza (wrzesień, dzień 10) ma Pracuj.pl, poprzednia — nic.
    assert card.facts[0][0] == "✗ kariera, JJIT"
    assert card.facts[1][0] == "✗ kariera, Pracuj, JJIT"


def test_backlog_card_for_recruiter_shows_only_the_career_page() -> None:
    at = datetime(2026, 10, 22, 8, tzinfo=timezone.utc)
    rows = [_status(job_id=1), _status(job_id=2, career_live=at)]
    card = r.backlog_card(rows, REC)
    assert card is not None
    assert card.about == "1 rekrutacja sprzed startu przypomnień"
    assert card.facts == (("✗ kariera", "Programista Integracji ZOB-3070"),)
    assert r.backlog_card([_status(career_live=at)], REC) is None


def test_mail_buttons_never_point_at_the_api_and_render_with_the_template() -> None:
    cards = [
        r.lead_card(_status(), DL, TODAY),
        r.recruiter_card(_status(), REC, TODAY),
        r.backlog_card([_status()], DL),
    ]
    for card in cards:
        assert card is not None
        for button in card.buttons:
            assert button.path.startswith("/") and not button.path.startswith("/api")
        subject, text, html = render_card_email(card)
        assert subject == card.subject
        assert "przychodzi zawsze" in text
        assert card.title in html


# ── Kto decyduje ─────────────────────────────────────────────────────────────


def _user(uid: int, *roles: UserRole) -> SimpleNamespace:
    return SimpleNamespace(
        id=uid, has_any_role=lambda *want: bool(set(want) & set(roles))
    )


def test_only_lead_hor_or_admin_manage_skips_and_nudges() -> None:
    s = _status()
    assert r.can_manage(_user(DL, UserRole.delivery_lead), s)
    assert r.can_manage(_user(HOR, UserRole.head_of_recruitment), s)
    assert r.can_manage(_user(50, UserRole.admin), s)
    assert not r.can_manage(_user(REC, UserRole.recruiter), s)
    # DL innej rekrutacji też nie.
    assert not r.can_manage(_user(77, UserRole.delivery_lead), s)


def test_panel_marks_what_the_viewer_does() -> None:
    view = r.panel(_status(), _user(REC, UserRole.recruiter))
    by_channel = {c["channel"]: c for c in view["channels"]}
    assert by_channel["kariera"]["mine"] is True
    assert by_channel["pracuj"]["mine"] is False
    assert by_channel["pracuj"]["owner_names"] == ["Martyna Wiśniewska"]
    assert view["can_manage"] is False
    assert view["recruiter_names"] == ["Julia Sowa"]


def test_short_name() -> None:
    assert r.short_name("Julia Sowa") == "Julia S."
    assert r.short_name("Anna Maria Nowak") == "Anna N."
    assert r.short_name("Admin") == "Admin"
    assert r.short_name(None) == "ktoś z zespołu"
