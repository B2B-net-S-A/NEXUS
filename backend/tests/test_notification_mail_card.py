"""Mail z przyciskami akcji (26.10.2026): temat, znaczek, fakty, przyciski, stopka.

Czyste funkcje `notification_mail_card.build_card` i `email.render_card_email`
— bez bazy. Decyzja Artura: same przyciski, które otwierają ekran z decyzją
do potwierdzenia; nic nie wykonuje się z samego kliknięcia w mail.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from app.models.notification import NotificationType
from app.services.email import (
    OPTIONAL_FOOTER,
    REQUIRED_FOOTER,
    render_card_email,
    render_notification_email,
)
from app.services.notification_delivery import (
    BELL_MAIL_TYPES,
    HR_MAIL_KIND,
    IMMEDIATE_KINDS,
    REQUIRED_KINDS,
    notification_kind,
)
from app.services.notification_mail_card import (
    SPECS,
    MailFacts,
    build_card,
    link_refs,
    with_params,
)

SLOTS = (
    datetime(2026, 10, 29, 8, 30, tzinfo=timezone.utc),
    datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc),
)
INTERVIEW = MailFacts(
    candidate="Jan Testowy",
    job="Java Developer (TEST-1)",
    client="Bank Testowy",
    delivery_lead="Ewa Fikcyjna",
    slots=SLOTS,
    duration_minutes=60,
)


def _query(path: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(path).query)


def test_slot_request_subject_facts_and_one_button_per_slot():
    card = build_card(
        notification_type="interview_slots_requested",
        kind="client_interview",
        title="Terminy rozmowy od klienta",
        message="2 terminy rozmowy u klienta do ustalenia z kandydatem.",
        link="/calendar?cycle=11-22",
        required=True,
        facts=INTERVIEW,
        entity_ref="27",
    )
    assert card.subject == (
        "[NEXUS] Ustal termin z kandydatem · Jan Testowy · Bank Testowy"
    )
    assert card.chip == "Czeka na Ciebie" and card.waiting
    assert card.facts == (
        ("Rekrutacja", "Java Developer (TEST-1)"),
        ("Klient", "Bank Testowy"),
        ("Długość", "60 min"),
        ("Delivery Lead", "Ewa Fikcyjna"),
    )
    labels = [b.label for b in card.buttons]
    # Godziny w strefie firmy (8:30 UTC = 9:30 w Warszawie w październiku).
    assert labels == [
        "Kandydat wybrał 1 · czw 29.10, 9:30",
        "Kandydat wybrał 2 · pt 30.10, 9:00",
        "Otwórz rozmowę",
    ]
    first = _query(card.buttons[0].path)
    # Numer wniosku (`req`): termin zaznacza się tylko na tym samym wniosku —
    # para mogła dostać od klienta nowe terminy po wysłaniu maila.
    assert first == {
        "cycle": ["11-22"],
        "do": ["pick"],
        "choose": ["1"],
        "req": ["27"],
    }
    assert _query(card.buttons[1].path)["choose"] == ["2"]
    assert card.buttons[2].path == "/calendar?cycle=11-22"


def test_confirmed_interview_shows_chosen_slot_and_plans_prep():
    card = build_card(
        notification_type="interview_slot_confirmed",
        kind="client_interview",
        title="Rozmowa potwierdzona",
        message="Klient potwierdził termin.",
        link="/calendar?cycle=1-2",
        required=True,
        facts=MailFacts(**{**INTERVIEW.__dict__, "chosen_index": 1}),
    )
    assert card.facts[0] == ("Termin", "pt 30.10, 9:00")
    assert [b.label for b in card.buttons] == ["Zaplanuj prep", "Otwórz rozmowę"]
    assert _query(card.buttons[0].path)["do"] == ["plan_prep"]
    assert not card.waiting


def test_dl_review_keeps_review_link_and_lists_case_facts():
    card = build_card(
        notification_type="board_task_waiting",
        kind="dl_review",
        title="CV do przeglądu: Anna Przykładowa",
        message="Rekruterka przekazała CV do QC.",
        link="/jobs/22?candidate=11&review=1",
        required=True,
        facts=MailFacts(
            candidate="Anna Przykładowa",
            job="Analityk danych (TEST-2)",
            client="Klient Testowy",
        ),
    )
    assert card.subject == "[NEXUS] Przejrzyj CV · Anna Przykładowa · Klient Testowy"
    assert [(b.label, b.path, b.style) for b in card.buttons] == [
        ("Przejrzyj CV", "/jobs/22?candidate=11&review=1", "primary")
    ]
    assert dict(card.facts)["Kandydat"] == "Anna Przykładowa"


@pytest.mark.parametrize(
    ("title", "kind", "action"),
    [
        ("CV do przeglądu: Jan", "dl_review", "Przejrzyj CV"),
        ("Do wrzucenia do Cpro: Jan", "dl_review", "Wrzuć do Cpro"),
        ("Wciąż czeka na wysyłkę: Jan", "dl_review", "Wyślij CV do klienta"),
        ("QC CV do poprawy: Jan", "cv_returned", "Popraw CV"),
        ("Wrócił z kolejki Cpro: Jan", "cv_returned", "Popraw CV"),
        ("Kolejka Cpro: 3 osoby czekają", "dl_review", "Sprawdź zadanie"),
    ],
)
def test_board_task_action_follows_the_title(title, kind, action):
    """Jeden typ dzwonka, kilka zadań — „Przejrzyj CV” tylko dla przeglądu DL."""
    card = build_card(
        notification_type="board_task_waiting",
        kind=kind,
        title=title,
        message="…",
        link="/jobs/1?candidate=2",
        required=True,
    )
    assert card.action == action


def test_cv_returned_is_its_own_action():
    card = build_card(
        notification_type="board_task_waiting",
        kind="cv_returned",
        title="CV wróciło do poprawy: Jan",
        message="Popraw CV.",
        link="/jobs/1?candidate=2",
        required=True,
    )
    assert card.subject == "[NEXUS] Popraw CV"
    assert card.buttons[0].label == "Popraw CV"


def test_request_assigned_subject_is_job_and_client_with_deadline():
    card = build_card(
        notification_type="request_assignment_changed",
        kind="request_assigned",
        title="Nowy request do pracy",
        message="Przypisano Cię do rekrutacji.",
        link="/jobs/33",
        required=True,
        facts=MailFacts(
            job="Scrum Master (TEST-3)",
            client="Klient Testowy",
            delivery_lead="Ewa Fikcyjna",
            deadline=date(2026, 11, 6),
        ),
    )
    assert card.subject == (
        "[NEXUS] Nowa rekrutacja dla Ciebie · Scrum Master (TEST-3) · Klient Testowy"
    )
    assert dict(card.facts)["Termin"] == "06.11.2026"


def test_hired_order_missing_opens_contractor_panel():
    card = build_card(
        notification_type="hired_order_missing",
        kind="hire_documents",
        title="Nowy kontraktor bez zamówienia",
        message="Uzupełnij zamówienie.",
        link="/clients/26?tab=zamowienia",
        required=True,
        facts=MailFacts(
            candidate="Piotr Próbny",
            client="Klient Testowy",
            start_date=date(2026, 10, 22),
        ),
        entity_ref="9001",
    )
    assert _query(card.buttons[0].path) == {
        "tab": ["zamowienia"],
        "contract": ["9001"],
    }
    assert dict(card.facts) == {
        "Kontraktor": "Piotr Próbny",
        "Klient": "Klient Testowy",
        "Start": "22.10.2026",
    }


# Numer wniosku budowany w teście: literał UUID gitleaks bierze za klucz API.
LEAVE_LINK = f"/people/approvals?leave={uuid.UUID(int=1)}"


def test_leave_request_offers_approve_and_reject_to_confirm_on_screen():
    card = build_card(
        notification_type="hr_leave_requested",
        kind=HR_MAIL_KIND,
        title="Wniosek o nieobecność do akceptacji",
        message="Ola: 28.12–31.12.2026 (4 dni).",
        link=LEAVE_LINK,
        required=True,
        facts=MailFacts(
            person="Ola Przykładowa",
            period=(date(2026, 12, 28), date(2026, 12, 31)),
            # Fakty rekrutacji w mailu kadrowym nie idą nigdy.
            job="Nie powinno wyjść",
            client="Też nie",
        ),
    )
    assert card.subject == "[NEXUS] Zatwierdź nieobecność · Ola Przykładowa"
    assert card.facts == (
        ("Kto", "Ola Przykładowa"),
        ("Kiedy", "28.12–31.12.2026"),
    )
    decisions = [(b.label, _query(b.path).get("decide"), b.style) for b in card.buttons]
    assert decisions == [
        ("Zatwierdź", ["approve"], "primary"),
        ("Odrzuć", ["reject"], "neg"),
        ("Otwórz wniosek", None, "secondary"),
    ]


@pytest.mark.parametrize(
    ("title", "link"),
    [
        # Zastępca przy L4 nie decyduje — bez przycisków decyzji.
        ("Wniosek o nieobecność do wiadomości", LEAVE_LINK),
        # Stary wpis bez numeru wniosku w linku.
        ("Wniosek o nieobecność do akceptacji", "/people/approvals"),
    ],
)
def test_leave_without_decision_only_opens_approvals(title, link):
    card = build_card(
        notification_type="hr_leave_requested",
        kind=HR_MAIL_KIND,
        title=title,
        message="…",
        link=link,
        required=True,
    )
    assert [b.label for b in card.buttons] == ["Otwórz akceptacje"]
    assert all("decide" not in _query(b.path) for b in card.buttons)


def test_footer_says_required_only_for_required_kinds():
    _, text, html = render_card_email(
        build_card(
            notification_type="interview_slot_chosen",
            kind="client_interview",
            title="Kandydat wybrał termin",
            message="Potwierdź.",
            link="/calendar?cycle=1-2",
            required=True,
        )
    )
    assert REQUIRED_FOOTER in text and REQUIRED_FOOTER in html
    assert OPTIONAL_FOOTER not in text
    subject, text, html = render_notification_email(
        title="Nowa wiadomość na czacie", message="Jan: hej", deep_link_path="/jobs/1"
    )
    assert subject == "[NEXUS] Nowa wiadomość na czacie"
    assert OPTIONAL_FOOTER in text and REQUIRED_FOOTER not in html
    assert "/settings?item=my-notifications" in text


def test_html_escapes_everything_from_the_bell_and_facts():
    _, text, html = render_card_email(
        build_card(
            notification_type="client_accepted",
            kind="client_accepted",
            title="<script>alert(1)</script>",
            message='Klient "<b>X</b>"',
            link='/jobs/1?candidate=2&x="><img src=x>',
            required=True,
            facts=MailFacts(candidate="<i>Jan</i>", client="A&B"),
        )
    )
    assert "<script>" not in html and "<i>Jan</i>" not in html
    assert "&lt;script&gt;" in html and "A&amp;B" in html
    assert '"><img' not in html


def test_buttons_never_point_at_the_api():
    """Przycisk otwiera ekran — nigdy trasę `/api`, którą Safe Links by wywołał."""
    for ntype in SPECS:
        card = build_card(
            notification_type=ntype,
            kind=notification_kind(ntype),
            title="Wniosek o nieobecność do akceptacji",
            message="…",
            link="/calendar?cycle=1-2" if "interview" in ntype else LEAVE_LINK,
            required=True,
            facts=INTERVIEW,
            entity_ref="5",
        )
        assert card.buttons, ntype
        for button in card.buttons:
            assert button.path.startswith("/") and not button.path.startswith("/api")


def test_every_bell_mail_type_has_an_action():
    """Nowy typ w mailu „od razu” = wpis w `SPECS` (co zrobić i przycisk)."""
    bell = {t for types in BELL_MAIL_TYPES.values() for t in types}
    immediate = {
        t.value
        for t in NotificationType
        if notification_kind(t) in IMMEDIATE_KINDS
        and notification_kind(t) != HR_MAIL_KIND
    }
    assert bell | immediate <= set(SPECS)


def test_facts_skip_empty_and_cap_at_five():
    card = build_card(
        notification_type="client_accepted",
        kind="client_accepted",
        title="Klient zaakceptował",
        message="…",
        link="/jobs/1",
        required="client_accepted" in REQUIRED_KINDS,
        facts=MailFacts(candidate="Jan", client=None, job="Analityk"),
    )
    assert card.facts == (("Kandydat", "Jan"), ("Rekrutacja", "Analityk"))
    assert card.subject == "[NEXUS] Klient zaakceptował · Jan"


def test_request_number_goes_before_job_and_ends_the_subject():
    # Zgłoszenie DL z 23.11.2026: numer zapytania klienta (`client_reference`)
    # w mailu, żeby odpisać klientowi i znaleźć mail po tym numerze.
    card = build_card(
        notification_type="interview_slot_chosen",
        kind="client_interview",
        title="Odpisz klientowi — termin wybrany",
        message="Potwierdź termin klientowi.",
        link="/calendar?cycle=11-22",
        required=True,
        facts=MailFacts(
            **{**INTERVIEW.__dict__, "chosen_index": 0, "request_number": "ZOB-0001"}
        ),
    )
    assert card.subject == (
        "[NEXUS] Potwierdź termin u klienta · Jan Testowy · Bank Testowy · ZOB-0001"
    )
    assert card.facts == (
        ("Termin", "czw 29.10, 9:30"),
        ("Nr zapytania", "ZOB-0001"),
        ("Rekrutacja", "Java Developer (TEST-1)"),
        ("Klient", "Bank Testowy"),
        ("Delivery Lead", "Ewa Fikcyjna"),
    )
    subject, text, html_body = render_card_email(card)
    assert "Nr zapytania: ZOB-0001" in text and "ZOB-0001" in html_body


def test_request_number_fits_with_four_other_facts():
    card = build_card(
        notification_type="interview_slots_requested",
        kind="client_interview",
        title="Terminy rozmowy od klienta",
        message="…",
        link="/calendar?cycle=11-22",
        required=True,
        facts=MailFacts(**{**INTERVIEW.__dict__, "request_number": "43114"}),
    )
    assert [k for k, _ in card.facts] == [
        "Nr zapytania",
        "Rekrutacja",
        "Klient",
        "Długość",
        "Delivery Lead",
    ]


def test_no_request_number_no_row_and_no_subject_suffix():
    card = build_card(
        notification_type="interview_slot_chosen",
        kind="client_interview",
        title="t",
        message="m",
        link="/calendar?cycle=11-22",
        required=True,
        facts=MailFacts(**{**INTERVIEW.__dict__, "chosen_index": 0}),
    )
    assert "Nr zapytania" not in dict(card.facts)
    assert card.subject.endswith("· Bank Testowy")


def test_request_number_needs_the_job_row_and_skips_hr_mail():
    # Sam numer bez rekrutacji nic nie mówi; mail kadrowy nie niesie
    # faktów rekrutacji nigdy.
    alone = build_card(
        notification_type="client_accepted",
        kind="client_accepted",
        title="t",
        message="m",
        link="/jobs/1",
        required=False,
        facts=MailFacts(candidate="Jan", request_number="ZOB-0002"),
    )
    assert "Nr zapytania" not in dict(alone.facts)
    hr = build_card(
        notification_type="hr_leave_requested",
        kind=HR_MAIL_KIND,
        title="Wniosek o urlop",
        message="m",
        link="/people/approvals",
        required=True,
        facts=MailFacts(person="Ewa Fikcyjna", request_number="ZOB-0003"),
    )
    assert "ZOB-0003" not in hr.subject
    assert "Nr zapytania" not in dict(hr.facts)


def test_subject_parts_are_shortened():
    card = build_card(
        notification_type="request_assignment_changed",
        kind="request_assigned",
        title="t",
        message="m",
        link="/jobs/1",
        required=True,
        facts=MailFacts(job="X" * 200, client="Klient Testowy"),
    )
    assert len(card.subject) < 170 and card.subject.endswith("… · Klient Testowy")


@pytest.mark.parametrize(
    ("link", "refs"),
    [
        ("/jobs/12?candidate=34&review=1", {"job": 12, "candidate": 34}),
        ("/calendar?cycle=56-78&debrief=9", {"candidate": 56, "job": 78}),
        ("/clients/26?tab=zamowienia", {"client": 26}),
        ("/people/approvals", {}),
        (None, {}),
        ("/calendar?cycle=bad", {}),
    ],
)
def test_link_refs(link, refs):
    assert link_refs(link) == refs


def test_with_params_merges_and_removes():
    assert with_params("/a?x=1&y=2", y=None, z="3") == "/a?x=1&z=3"


async def test_load_facts_reads_client_reference_from_job():
    from types import SimpleNamespace

    from app.models.client import Client
    from app.models.job import Job
    from app.services.notification_mail_card import load_facts

    rows = {
        Job: SimpleNamespace(
            title="Analityk",
            working_title=None,
            deadline=None,
            client_id=5,
            delivery_lead_id=None,
            client_reference="  ZOB-0004 ",
        ),
        Client: SimpleNamespace(name="Bank Testowy", display_name=None),
    }

    class _Db:
        async def get(self, model, _id):
            return rows.get(model)

    notif = SimpleNamespace(
        link="/jobs/7", related_entity_type=None, related_entity_id=None
    )
    facts = await load_facts(_Db(), notif)
    assert facts.request_number == "ZOB-0004"
    rows[Job].client_reference = "   "
    assert (await load_facts(_Db(), notif)).request_number is None


def test_client_accepted_shows_recruiter_under_delivery_lead():
    # Prośba Olafa z 24.11.2026: w mailu „Klient zaakceptował” pole
    # „Rekruter” pod Delivery Leadem — także przy numerze zapytania (6 faktów).
    card = build_card(
        notification_type="client_accepted",
        kind="client_accepted",
        title="Klient zaakceptował: Jan Testowy",
        message="…",
        link="/jobs/1?candidate=2",
        required=True,
        facts=MailFacts(
            candidate="Jan Testowy",
            request_number="ZOB-0004",
            job="Analityk",
            client="Bank Testowy",
            delivery_lead="Dana Lead",
            recruiter="Rena Rekruter",
        ),
    )
    assert card.facts == (
        ("Kandydat", "Jan Testowy"),
        ("Nr zapytania", "ZOB-0004"),
        ("Rekrutacja", "Analityk"),
        ("Klient", "Bank Testowy"),
        ("Delivery Lead", "Dana Lead"),
        ("Rekruter", "Rena Rekruter"),
    )


async def test_load_facts_reads_pair_recruiter_only_for_client_accepted(monkeypatch):
    from types import SimpleNamespace

    from app.models.job import Job
    from app.models.notification import NotificationType
    from app.models.user import User
    from app.services import stage_handoff_recipients
    from app.services.notification_mail_card import load_facts

    asked: list[tuple[int, int]] = []

    async def _recruiter(_db, *, candidate_id, job_id):
        asked.append((candidate_id, job_id))
        return 42

    monkeypatch.setattr(stage_handoff_recipients, "pair_recruiter_id", _recruiter)
    rows = {
        Job: SimpleNamespace(
            title="Analityk",
            working_title=None,
            deadline=None,
            client_id=None,
            delivery_lead_id=None,
            client_reference=None,
        ),
        User: SimpleNamespace(name="Rena Rekruter"),
    }

    class _Db:
        async def get(self, model, _id):
            return rows.get(model)

    def _notif(ntype):
        return SimpleNamespace(
            notification_type=ntype,
            link="/jobs/7?candidate=3",
            related_entity_type="candidate_stage",
            related_entity_id=None,
        )

    facts = await load_facts(_Db(), _notif(NotificationType.client_accepted))
    assert facts.recruiter == "Rena Rekruter"
    assert asked == [(3, 7)]
    facts = await load_facts(_Db(), _notif(NotificationType.pre_contract))
    assert facts.recruiter is None
    assert asked == [(3, 7)]
