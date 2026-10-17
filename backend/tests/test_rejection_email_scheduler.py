"""Unit tests for `app.services.rejection_email_scheduler`.

Pure-function tests (no DB, no Graph). Focus:
- trigger_previous_stages correctness (the business rule)
- `_apply()` renderer — simple placeholders, conditional block
- renderer doesn't leak client/company names (only job.title is exposed)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.recruitment_pipeline import PipelineStage
from app.models.user import User, UserRole
from app.services import rejection_email_text as rejection_text
from app.services.email_template_variables import plain_text_to_html
from app.services.rejection_email_scheduler import (
    ACTIVE_OTHER_STAGES_EXCLUDE,
    DELAY_MINUTES,
    MAX_ATTEMPTS,
    TRIGGER_PREVIOUS_STAGES,
    _apply,
    _can_send_rejection_email,
    _render,
    _resolve_template,
    mail_text_kind,
)
from app.services.section_permissions import ProductSection


def default_text(*, candidate, job, recruiter=None, kind=rejection_text.TEXT_AFTER_CLIENT):
    """Pełna treść domyślna (część do poprawy + zakończenie) jak w oknie."""
    del recruiter
    text = rejection_text.default_text(
        candidate_name=candidate.name, job_title=job.title, kind=kind
    )
    return text.subject, text.full()


# ── Constants ──────────────────────────────────────────────────────────────


def test_trigger_previous_stages_contains_all_client_visible() -> None:
    """The trigger set must include every stage after which the client has
    seen the candidate — including `cv_sent`, even though STAGE_CATEGORY
    labels it `internal`. This is the core business rule."""
    assert PipelineStage.cv_sent in TRIGGER_PREVIOUS_STAGES
    assert PipelineStage.client_interview in TRIGGER_PREVIOUS_STAGES
    assert PipelineStage.acceptance in TRIGGER_PREVIOUS_STAGES
    assert PipelineStage.negotiation in TRIGGER_PREVIOUS_STAGES
    assert PipelineStage.onboarding in TRIGGER_PREVIOUS_STAGES


def test_trigger_previous_stages_excludes_early_internal() -> None:
    """Etapy przed klientem nie dają treści „po kliencie” — od 17.10.2026 mail
    z „Zweryfikowany” i „QC CV” ma treść „przed klientem” (``mail_text_kind``)."""
    for stage in (
        PipelineStage.new,
        PipelineStage.prep_call,
        PipelineStage.screening,
        PipelineStage.interview,
    ):
        assert stage not in TRIGGER_PREVIOUS_STAGES, (
            f"{stage} must not count as seen by the client"
        )


@pytest.mark.parametrize(
    ("legacy", "name", "expected"),
    [
        # D1 (17.10.2026): przed weryfikacją bez maila.
        ("new", "Nowi / Analiza CV", None),
        ("screening", "Screening", None),
        ("prep_call", None, None),
        # Po rozmowie z nami, przed klientem — treść „przed klientem”.
        ("verified", "Kandydat Zweryfikowany", rejection_text.TEXT_BEFORE_CLIENT),
        ("interview", "QC CV", rejection_text.TEXT_BEFORE_CLIENT),
        ("new", "Wysłać do Cpro", rejection_text.TEXT_BEFORE_CLIENT),
        # U klienta — treść z 13.10.2026.
        ("cv_sent", "Wysłany do Klienta", rejection_text.TEXT_AFTER_CLIENT),
        ("interview", "Po Interview", rejection_text.TEXT_AFTER_CLIENT),
        ("client_interview", "Interview u klienta", rejection_text.TEXT_AFTER_CLIENT),
        ("acceptance", None, rejection_text.TEXT_AFTER_CLIENT),
        # Zamknięta karta to nie etap, po którym ktoś odrzuca.
        ("rejected", "Odrzucony", None),
    ],
)
def test_mail_text_kind_follows_the_board_column(legacy, name, expected) -> None:
    category = "terminal" if legacy == "rejected" else "internal"
    assert mail_text_kind(legacy, name=name, category=category) == expected


def test_active_other_stages_exclude_terminals() -> None:
    """All terminal stages must be in the exclude-set so they never appear
    as an 'other active process' in the rendered body."""
    assert PipelineStage.rejected in ACTIVE_OTHER_STAGES_EXCLUDE
    assert PipelineStage.withdrawn in ACTIVE_OTHER_STAGES_EXCLUDE
    assert PipelineStage.hired in ACTIVE_OTHER_STAGES_EXCLUDE


def test_delay_is_fifteen_minutes() -> None:
    assert DELAY_MINUTES == 15


def test_max_attempts_is_three() -> None:
    assert MAX_ATTEMPTS == 3


def test_rejection_email_requires_pipeline_write_not_only_sourcing() -> None:
    recruiter = User(
        id=91,
        email="recruiter@example.com",
        name="Recruiter",
        role=UserRole.recruiter,
        roles=[UserRole.recruiter.value],
        is_active=True,
    )
    recruiter.effective_section_access = {
        section.value: "none" for section in ProductSection
    }
    recruiter.effective_section_access[ProductSection.sourcing.value] = "write"

    assert not _can_send_rejection_email(recruiter)

    recruiter.effective_section_access[ProductSection.pipeline.value] = "read"
    assert not _can_send_rejection_email(recruiter)

    recruiter.effective_section_access[ProductSection.pipeline.value] = "write"
    assert _can_send_rejection_email(recruiter)


# ── Renderer: _apply() ─────────────────────────────────────────────────────


@pytest.fixture
def ctx() -> dict[str, str]:
    return {
        "candidate_name": "Jan",
        "candidate_lastname": "Kowalski",
        "candidate_full_name": "Jan Kowalski",
        "job_title": "Senior Python Developer",
        "recruiter_name": "Ania",
        "other_processes_count": "2",
        "other_processes_list": "DevOps Lead, Backend Architect",
    }


def test_apply_simple_placeholder_replacement(ctx: dict[str, str]) -> None:
    template = "Hi {{candidate_name}}, role: {{job_title}}"
    rendered = _apply(template, ctx, has_others=False)
    assert rendered == "Hi Jan, role: Senior Python Developer"


def test_apply_strips_if_block_when_no_others(ctx: dict[str, str]) -> None:
    template = (
        "Hello {{candidate_name}}. "
        "{{#if other_processes}}You have {{other_processes_count}} others.{{/if}}"
        " Bye."
    )
    rendered = _apply(template, ctx, has_others=False)
    assert rendered == "Hello Jan.  Bye."
    assert "{{#if" not in rendered
    assert "{{/if}}" not in rendered
    assert "others" not in rendered


def test_apply_keeps_if_block_when_has_others(ctx: dict[str, str]) -> None:
    template = (
        "Hello {{candidate_name}}. "
        "{{#if other_processes}}You have {{other_processes_count}} others: "
        "{{other_processes_list}}.{{/if}} Bye."
    )
    rendered = _apply(template, ctx, has_others=True)
    assert "You have 2 others: DevOps Lead, Backend Architect." in rendered
    assert "{{#if" not in rendered
    assert "{{/if}}" not in rendered


def test_apply_handles_multiline_if_block(ctx: dict[str, str]) -> None:
    template = """Line 1
{{#if other_processes}}
Line 2 — {{other_processes_count}}
Line 3 — {{other_processes_list}}
{{/if}}
Line 4"""
    stripped = _apply(template, ctx, has_others=False)
    assert "Line 2" not in stripped
    assert "Line 3" not in stripped
    assert "Line 1" in stripped and "Line 4" in stripped

    rendered = _apply(template, ctx, has_others=True)
    assert "Line 2 — 2" in rendered
    assert "Line 3 — DevOps Lead, Backend Architect" in rendered


def test_apply_unknown_placeholder_left_intact(ctx: dict[str, str]) -> None:
    """Unknown placeholders stay as-is; easier to spot template bugs than to
    silently drop content."""
    rendered = _apply("{{candidate_name}} + {{unknown_thing}}", ctx, has_others=False)
    assert rendered == "Jan + {{unknown_thing}}"


# ── Renderer: _render() integration ────────────────────────────────────────


def _mk_candidate(name: str = "Jan", lastname: str = "Kowalski") -> SimpleNamespace:
    return SimpleNamespace(name=name, lastname=lastname)


def _mk_job(title: str = "Senior Python Developer") -> SimpleNamespace:
    return SimpleNamespace(title=title)


def _mk_recruiter(
    name: str = "Anna Nowak", email: str = "anna@co.pl"
) -> SimpleNamespace:
    return SimpleNamespace(name=name, email=email)


# Szablon z blokiem „inne procesy” i podpisem rekrutera — od 13.10.2026 treść
# domyślna nie ma ani jednego, ani drugiego (D4, podpis dokleja Outlook), ale
# renderer nadal obsługuje je w szablonie wskazanym jawnie.
_TEMPLATE_WITH_OTHERS = SimpleNamespace(
    subject="Informacja zwrotna — {{job_title}}",
    body=(
        "<p>Cześć {{candidate_name}},</p>"
        "{{#if other_processes}}<p>Nadal rozważamy Cię w {{other_processes_count}} "
        "innych otwartych procesach: {{other_processes_list}}.</p>{{/if}}"
        "<p>Pozdrawiam,<br>{{recruiter_name}}</p>"
    ),
)


def test_render_uses_default_template_when_none_given() -> None:
    """Renderer falls back to the hard-coded Polish template if no row exists."""
    subject, body = _render(
        template=None,
        candidate=_mk_candidate(),
        job=_mk_job(),
        recruiter=_mk_recruiter(),
        other_processes=[],
    )
    assert "Senior Python Developer" in subject
    assert "Cześć Jan," in body
    # When others=[], the if-block is gone
    assert "innych otwartych procesach" not in body


def test_render_with_others_shows_titles_only() -> None:
    others = [
        {"job_id": 10, "title": "DevOps Lead"},
        {"job_id": 11, "title": "Backend Architect"},
    ]
    _, body = _render(
        template=_TEMPLATE_WITH_OTHERS,
        candidate=_mk_candidate(),
        job=_mk_job(),
        recruiter=_mk_recruiter(),
        other_processes=others,
    )
    assert "DevOps Lead" in body
    assert "Backend Architect" in body
    assert "2" in body  # other_processes_count
    # Make sure no job_id leaks into the body.
    assert '"job_id"' not in body
    assert "10" not in body  # job_id=10 — hopefully no false-positive
    assert "11" not in body  # job_id=11


def test_render_does_not_expose_client_fields() -> None:
    """Defense-in-depth: even if someone passes client-shaped data, the
    renderer only references job_id and title from each entry. Client names
    must never appear in the body."""
    others = [
        {
            "job_id": 7,
            "title": "Staff Engineer",
            # Even if these keys are present, they must not render.
            "client_name": "Acme Corp SECRET",
            "company": "TopSecret Industries",
        },
    ]
    _, body = _render(
        template=_TEMPLATE_WITH_OTHERS,
        candidate=_mk_candidate(),
        job=_mk_job(),
        recruiter=_mk_recruiter(),
        other_processes=others,
    )
    assert "Staff Engineer" in body
    assert "Acme Corp SECRET" not in body
    assert "TopSecret Industries" not in body


def test_render_recruiter_fallback_to_email() -> None:
    """If a recruiter row is missing `name`, the renderer uses their email —
    at least the message isn't signed 'None'."""
    _, body = _render(
        template=_TEMPLATE_WITH_OTHERS,
        candidate=_mk_candidate(),
        job=_mk_job(),
        recruiter=SimpleNamespace(name=None, email="rec@co.pl"),
        other_processes=[],
    )
    assert "rec@co.pl" in body
    assert "None" not in body


# ── Treść domyślna i okno odrzucenia (13.10.2026, D1–D6) ──────────────────


def test_default_text_is_the_approved_text() -> None:
    subject, body = default_text(
        candidate=_mk_candidate(), job=_mk_job(), recruiter=_mk_recruiter()
    )
    assert subject == "Informacja zwrotna — Senior Python Developer"
    assert body == (
        "Cześć Jan,\n\n"
        "dziękujemy za udział w rekrutacji na stanowisko Senior Python Developer. "
        "Niestety został wybrany inny kandydat.\n\n"
        "Życzymy powodzenia i zachęcamy do udziału w przyszłych procesach "
        "rekrutacyjnych!"
    )


def test_before_client_text_does_not_say_another_candidate_won() -> None:
    """D4 (17.10.2026): CV nie trafiło do klienta — treść „przed klientem”."""
    text = rejection_text.default_text(
        candidate_name="Jan",
        job_title="Senior Python Developer",
        kind=rejection_text.TEXT_BEFORE_CLIENT,
    )
    assert text.subject == "Informacja zwrotna — Senior Python Developer"
    assert text.body == (
        "Cześć Jan,\n\n"
        "dziękujemy za rozmowę i czas poświęcony na rekrutację na stanowisko "
        "Senior Python Developer. Po przeanalizowaniu wymagań projektu "
        "zdecydowaliśmy, że w tym procesie nie przedstawimy Twojej kandydatury."
    )
    assert "inny kandydat" not in text.full()
    assert text.closing == rejection_text.CLOSING


def test_renderer_fallback_matches_the_window_text() -> None:
    """Zapas renderera (szablon nie istnieje) = treść „po kliencie” z okna."""
    _, html = _render(
        template=None,
        candidate=_mk_candidate(),
        job=_mk_job(),
        recruiter=_mk_recruiter(),
        other_processes=[],
    )
    _, text = default_text(candidate=_mk_candidate(), job=_mk_job())
    assert html == plain_text_to_html(text)


def test_default_mail_has_no_own_signoff_or_other_processes() -> None:
    """Podpis dokleja Outlook — własne „Pozdrawiam” dawało dwa pożegnania."""
    others = [{"job_id": 10, "title": "DevOps Lead"}]
    _, body = _render(
        template=None,
        candidate=_mk_candidate(),
        job=_mk_job(),
        recruiter=_mk_recruiter(),
        other_processes=others,
    )
    assert body == (
        "<p>Cześć Jan,</p>\n"
        "<p>dziękujemy za udział w rekrutacji na stanowisko Senior Python Developer. "
        "Niestety został wybrany inny kandydat.</p>\n"
        "<p>Życzymy powodzenia i zachęcamy do udziału w przyszłych procesach "
        "rekrutacyjnych!</p>"
    )
    assert "Pozdrawiam" not in body
    assert "Anna Nowak" not in body
    assert "DevOps Lead" not in body


def test_default_text_for_the_field_is_not_escaped_but_the_mail_is() -> None:
    job = _mk_job(title="R&D <Lead>")
    _, text = default_text(
        candidate=_mk_candidate(), job=job, recruiter=_mk_recruiter()
    )
    assert "stanowisko R&D <Lead>." in text
    assert "R&amp;D &lt;Lead&gt;" in plain_text_to_html(text)


def test_text_from_the_window_is_always_escaped() -> None:
    from app.services.email_template_variables import body_to_html, plain_text_to_html

    text = "Cześć Jan,\n\n<b>Uwaga</b> & <script>x</script>\nDo zobaczenia"
    assert plain_text_to_html(text) == (
        "<p>Cześć Jan,</p>\n"
        "<p>&lt;b&gt;Uwaga&lt;/b&gt; &amp; &lt;script&gt;x&lt;/script&gt;<br>\n"
        "Do zobaczenia</p>"
    )
    # Dla porównania: szablon z HTML-em przechodzi przez body_to_html bez zmian,
    # dlatego tekst z okna idzie wyłącznie przez plain_text_to_html.
    assert body_to_html("<b>Uwaga</b>") == "<b>Uwaga</b>"


async def test_without_override_settings_templates_are_not_read() -> None:
    """D6: bez jawnego szablonu wysyłka nie zagląda do bazy — treść z kodu."""

    class _NoDb:
        def __getattr__(self, name: str):  # pragma: no cover - wywołanie = błąd
            raise AssertionError(f"_resolve_template sięgnął do bazy: {name}")

    assert await _resolve_template(_NoDb(), None) is None


def test_edited_subject_becomes_one_line_and_blank_text_is_refused() -> None:
    from pydantic import ValidationError

    from app.schemas.pipeline import StageMove

    move = StageMove(
        candidate_id=1,
        job_id=2,
        stage=PipelineStage.rejected,
        rejection_email_subject="  Rekrutacja\r\n Senior   Dev ",
        rejection_email_body="Cześć,\n\nDziękujemy.",
    )
    assert move.rejection_email_subject == "Rekrutacja Senior Dev"
    assert move.rejection_email_body == "Cześć,\n\nDziękujemy."

    for field, value in (
        ("rejection_email_subject", " \n "),
        ("rejection_email_body", "  \n\n "),
        ("rejection_email_subject", "x" * 999),
        ("rejection_email_body", "x" * 5001),
    ):
        with pytest.raises(ValidationError):
            StageMove(
                candidate_id=1, job_id=2, stage=PipelineStage.rejected, **{field: value}
            )


def test_default_subject_of_a_long_recruitment_title_can_be_sent_back() -> None:
    """Przegląd PR #2185: tytuł rekrutacji ma do 255 znaków, więc domyślny temat
    do ~276. Okno odsyła go razem z poprawioną treścią — limit 200 dawał 422
    i odrzucenie nie przechodziło."""
    from app.schemas.pipeline import StageMove

    subject, body = default_text(
        candidate=_mk_candidate(),
        job=_mk_job(title="T" * 255),
        recruiter=_mk_recruiter(),
    )
    move = StageMove(
        candidate_id=1,
        job_id=2,
        stage=PipelineStage.rejected,
        rejection_email_subject=subject,
        rejection_email_body=body + "\n\nDopisek rekrutera.",
    )
    assert move.rejection_email_subject == subject


# ── Dopisek o pozostałych rekrutacjach i nazwy dla kandydata (17.10.2026) ──


def test_other_processes_text_lists_named_and_counts_unnamed() -> None:
    assert rejection_text.other_processes_text([]) is None
    assert rejection_text.other_processes_text(["Java Tech Lead"]) == (
        "To dotyczy tylko tej rekrutacji — nadal bierzesz udział w naszym "
        "pozostałym procesie:\n"
        "• Java Tech Lead\n\n"
        "Odezwiemy się, gdy będziemy mieć w nim nowe informacje."
    )
    assert rejection_text.other_processes_text(
        ["Java Tech Lead", None, "Backend Developer (Kotlin)", None, None]
    ) == (
        "To dotyczy tylko tej rekrutacji — nadal bierzesz udział w naszych "
        "pozostałych procesach:\n"
        "• Java Tech Lead\n"
        "• Backend Developer (Kotlin)\n"
        "• i jeszcze 3 inne rekrutacje\n\n"
        "Odezwiemy się, gdy będziemy mieć w nich nowe informacje."
    )


def test_other_processes_text_without_any_name_gives_only_a_count() -> None:
    assert rejection_text.other_processes_text([None]) == (
        "To dotyczy tylko tej rekrutacji — nadal bierzesz udział w jeszcze "
        "jednej naszej rekrutacji.\n\n"
        "Odezwiemy się, gdy będziemy mieć w nim nowe informacje."
    )
    assert "w jeszcze 2 naszych rekrutacjach." in rejection_text.other_processes_text(
        [None, None]
    )


@pytest.mark.parametrize(
    ("title", "safe"),
    [
        ("Senior Java Developer", True),
        ("C# Developer", True),
        ("Java 17 Developer", True),
        ("SAP Consultant REQ1234567", False),
        ("Developer - Payments - DE#12345", False),
        ("Nordea Analityk danych", False),
        ("", False),
    ],
)
def test_title_safe_for_mail_hides_codes_and_client(title: str, safe: bool) -> None:
    assert rejection_text.title_safe_for_mail(title, ["Nordea Bank Abp"]) is safe


def test_marker_is_filled_with_the_list_or_the_closing() -> None:
    body = plain_text_to_html("Cześć Jan,\n\nW tym procesie nie przechodzisz dalej.")
    stored = f"{body}\n{rejection_text.OTHER_PROCESSES_MARKER}"

    filled = rejection_text.fill_other_processes(stored, ["R&D <Lead>"])
    assert rejection_text.OTHER_PROCESSES_MARKER not in filled
    assert "• R&amp;D &lt;Lead&gt;</p>" in filled
    assert filled.startswith(body)

    # Osoba odpadła w międzyczasie ze wszystkich — zwykłe zakończenie.
    alone = rejection_text.fill_other_processes(stored, [])
    assert alone == f"{body}\n<p>{rejection_text.CLOSING}</p>"

    # Treść bez znacznika (szablon, odznaczony dopisek) zostaje bez zmian.
    assert rejection_text.fill_other_processes(body, ["Java"]) == body


def test_marker_typed_in_the_window_is_escaped_not_filled() -> None:
    """Rekruter nie podrobi znacznika — `plain_text_to_html` robi z „<” encję."""
    typed = plain_text_to_html(f"Cześć {rejection_text.OTHER_PROCESSES_MARKER}")
    assert rejection_text.OTHER_PROCESSES_MARKER not in typed
    assert rejection_text.fill_other_processes(typed, ["Java"]) == typed


# ── Wspólny mail o kilku rekrutacjach (17.10.2026, D3) ─────────────────────


def test_merged_text_names_every_recruitment() -> None:
    text = rejection_text.merged_text(
        candidate_name="Anna", job_titles=["Senior Java Developer", "Java Tech Lead"]
    )
    assert text.subject == "Informacja zwrotna — Senior Java Developer, Java Tech Lead"
    assert text.body == (
        "Cześć Anna,\n\n"
        "dziękujemy za udział w rekrutacjach na stanowiska Senior Java Developer "
        "i Java Tech Lead. W tych dwóch procesach nie przechodzisz dalej."
    )
    three = rejection_text.merged_text(candidate_name="Anna", job_titles=["A", "B", "C"])
    assert "na stanowiska A, B i C. W tych trzech procesach" in three.body


def test_other_processes_text_after_a_merged_mail_speaks_of_these_recruitments() -> None:
    text = rejection_text.other_processes_text(["Backend Developer"], merged=True)
    assert text.startswith("To dotyczy tylko tych rekrutacji — nadal bierzesz udział")
    stored = f"<p>x</p>\n{rejection_text.OTHER_PROCESSES_MARKER}"
    assert "tylko tych rekrutacji" in rejection_text.fill_other_processes(
        stored, ["Backend Developer"], merged=True
    )
