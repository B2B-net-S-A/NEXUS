"""Formaty portali dla ogłoszenia do wklejenia — czyste funkcje, bez bazy."""

from __future__ import annotations

from app.services.job_ad import render
from app.services.job_ad.fixed_blocks import (
    DEFAULTS,
    SUFFIX_KM,
    SUFFIX_KMX,
    SUFFIX_NONE,
)
from app.services.job_ad.material import AdMaterial


def _material(**overrides) -> AdMaterial:
    base = dict(
        title="Senior Java Developer",
        seniority="senior",
        about="Platforma płatności natychmiastowych.",
        responsibilities="",
        description="",
        requirements_text="",
        critical=("Java",),
        must=("Java", "Kafka"),
        nice=("Kubernetes",),
        domains="",
        certifications="",
        pitch="",
        city="Warszawa",
        remote_policy="hybrid",
        onsite_days_per_week=2,
        onsite_days_per_month=None,
        contract="B2B",
        start="listopad 2026",
        duration="12 miesięcy",
        language="polski, angielski B2",
        working_time="fulltime",
    )
    base.update(overrides)
    return AdMaterial(**base)


def _content(**overrides) -> dict:
    base = {
        "title": "Senior Java Developer",
        "lead": "Szukamy osoby do zespołu płatności.",
        "about": "Zespół buduje mikroserwisy.\n\nWdrożenia co dwa tygodnie.",
        "start": "listopad 2026",
        "duration": "12 miesięcy",
        "language": "polski, angielski B2",
        "responsibilities": ["rozwój mikroserwisów", "przeglądy kodu"],
        "requirements": ["min. 5 lat doświadczenia w Javie", "praktyka z Apache Kafka"],
        "nice_to_have": ["Kubernetes i OpenShift"],
        "offer": ["długoterminowy projekt"],
    }
    base.update(overrides)
    return base


def _render(content=None, material=None, *, lang="pl", suffix=SUFFIX_KMX, tech=None):
    material = material or _material()
    return render.render_ad(
        content or _content(),
        tech if tech is not None else render.tech_from_material(material),
        material,
        DEFAULTS.for_lang(lang),
        lang=lang,
        title_suffix=suffix,
    )


def _field(view: dict, key: str) -> dict:
    return next(f for f in view["pracuj"]["fields"] if f["key"] == key)


def _section(view: dict, key: str) -> dict:
    return next(s for s in view["jjit"]["sections"] if s["key"] == key)


# ── Tytuł: jedna konwencja zamiast sześciu ──────────────────────────────────


def test_title_suffix_follows_the_setting_and_the_language():
    assert render.titled("Java Developer", "pl", SUFFIX_KMX) == "Java Developer (k/m/x)"
    assert render.titled("Java Developer", "en", SUFFIX_KMX) == "Java Developer (f/m/x)"
    assert render.titled("Java Developer", "pl", SUFFIX_KM) == "Java Developer (k/m)"
    assert render.titled("Java Developer", "en", SUFFIX_KM) == "Java Developer (f/m)"
    assert render.titled("Java Developer", "pl", SUFFIX_NONE) == "Java Developer"


def test_title_with_a_marker_is_left_alone():
    for title in (
        "Tester (K/M/X)",
        "IT Analyst (f/m/x)",
        "Programista .NET (k/m)",
        "Data Platform Developer (m/k/n)",
    ):
        assert render.titled(title, "pl", SUFFIX_KMX) == title


# ── Warunki: z pól rekrutacji, bez modelu ───────────────────────────────────


def test_terms_describe_hybrid_work_in_polish_and_english():
    terms = render.terms_from(_material(), _content())
    assert render.term_lines(terms, "pl") == [
        "kontrakt B2B",
        "praca hybrydowa: 2 dni w tygodniu w biurze (Warszawa)",
        "start: listopad 2026",
        "czas trwania: 12 miesięcy",
        "język pracy: polski, angielski B2",
    ]
    assert render.term_lines(terms, "en")[:2] == [
        "B2B contract",
        "hybrid work: 2 days per week in the office (Warszawa)",
    ]


def test_terms_skip_what_the_recruitment_does_not_have():
    material = _material(
        remote_policy=None, onsite_days_per_week=None, city=None, language=None
    )
    terms = render.terms_from(material, _content(start="", duration="", language=""))
    assert render.term_lines(terms, "pl") == ["kontrakt B2B"]


def test_one_office_day_and_monthly_days_are_worded_correctly():
    one = render.terms_from(_material(onsite_days_per_week=1), _content())
    assert "1 dzień w tygodniu w biurze" in render.term_lines(one, "pl")[1]
    monthly = render.terms_from(
        _material(onsite_days_per_week=None, onsite_days_per_month=8), _content()
    )
    assert "8 dni w miesiącu w biurze" in render.term_lines(monthly, "pl")[1]
    remote = render.terms_from(_material(remote_policy="remote"), _content())
    assert render.term_lines(remote, "pl")[1] == "praca zdalna"
    onsite = render.terms_from(_material(remote_policy="onsite"), _content())
    assert render.term_lines(onsite, "pl")[1] == "praca stacjonarna (Warszawa)"


def test_start_duration_and_language_come_from_the_ad_not_the_recruitment():
    """Rekruter poprawia je w oknie, a wersji angielskiej tłumaczy je model."""
    terms = render.terms_from(
        _material(),
        _content(start="styczeń 2027", duration="", language="angielski C1"),
    )
    lines = render.term_lines(terms, "pl")
    assert "start: styczeń 2027" in lines
    assert "język pracy: angielski C1" in lines
    assert not any(line.startswith("czas trwania") for line in lines)


# ── Technologie ─────────────────────────────────────────────────────────────


def test_tech_levels_come_from_the_requirement_level():
    stack = render.jjit_tech_stack(render.tech_from_material(_material()))
    assert [(t["name"], t["level"], t["label"]) for t in stack] == [
        ("Java", 4, "Advanced"),
        ("Kafka", 3, "Regular"),
        ("Kubernetes", 1, "Nice to have"),
    ]


def test_jjit_stack_is_capped_and_keeps_required_first():
    tech = [{"name": f"Nice{i}", "level": "nice"} for i in range(8)]
    tech += [{"name": f"Must{i}", "level": "must"} for i in range(6)]
    stack = render.jjit_tech_stack(render.clean_tech(tech))
    assert len(stack) == render.JJIT_TECH_LIMIT
    assert [t["name"] for t in stack[:6]] == [f"Must{i}" for i in range(6)]


def test_tech_takes_short_names_and_splits_alternatives():
    """Etykieta wymagania bywa zdaniem klienta albo wierszem „X lub Y” —
    lista technologii portalu bierze tylko krótkie nazwy."""
    material = _material(
        critical=("Kafka lub RabbitMQ",),
        must=(
            "Kafka lub RabbitMQ",
            "min. 5 lat doświadczenia w systemach płatniczych w bankowości",
            "Java",
        ),
        nice=("znajomość standardu ISO 20022 i praktyka w projektach SEPA",),
    )
    assert render.tech_from_material(material) == [
        {"name": "Kafka", "level": "critical"},
        {"name": "RabbitMQ", "level": "critical"},
        {"name": "Java", "level": "must"},
    ]


def test_jjit_says_how_many_technologies_did_not_fit():
    tech = render.clean_tech([{"name": f"T{i}", "level": "must"} for i in range(13)])
    view = _render(tech=tech)
    assert len(view["jjit"]["tech_stack"]) == render.JJIT_TECH_LIMIT
    assert view["jjit"]["tech_overflow"] == 3
    assert _render()["jjit"]["tech_overflow"] == 0


def test_clean_tech_drops_duplicates_blanks_and_unknown_levels():
    cleaned = render.clean_tech(
        [
            {"name": " Java ", "level": "critical"},
            {"name": "java", "level": "must"},
            {"name": "", "level": "must"},
            {"name": "Kafka", "level": "expert"},
            "śmieć",
        ]
    )
    assert cleaned == [
        {"name": "Java", "level": "critical"},
        {"name": "Kafka", "level": "must"},
    ]


# ── Pracuj.pl: pola w kolejności formularza ─────────────────────────────────


def test_pracuj_fields_follow_the_portal_form_order():
    view = _render()
    assert [f["key"] for f in view["pracuj"]["fields"]] == [
        "title",
        "about",
        "responsibilities",
        "requirements",
        "nice_to_have",
        "offer",
        "tech_required",
        "tech_optional",
        "process",
    ]
    assert _field(view, "title")["text"] == "Senior Java Developer (k/m/x)"
    assert _field(view, "tech_required")["items"] == ["Java", "Kafka"]
    assert _field(view, "tech_optional")["items"] == ["Kubernetes"]


def test_pracuj_offer_joins_terms_project_points_and_the_fixed_block():
    offer = _field(_render(), "offer")
    assert offer["items"][0] == "kontrakt B2B"
    assert "długoterminowy projekt" in offer["items"]
    assert offer["items"][-len(DEFAULTS.pl.offer) :] == list(DEFAULTS.pl.offer)
    assert offer["auto_count"] == 5
    assert offer["fixed_count"] == len(DEFAULTS.pl.offer)
    assert offer["text"].split("\n") == offer["items"]
    assert offer["hidden_auto"] == [] and offer["hidden_fixed"] == []


def test_hidden_offer_points_leave_both_portals_but_stay_restorable():
    # Zgłoszenie 28.10: rekruterka chciała zdjąć punkt stałego bloku w jednej
    # rekrutacji. Ukryty punkt znika z Pracuj.pl i JustJoin.IT, a okno dostaje
    # go osobno, żeby dało się go przywrócić.
    medical = DEFAULTS.pl.offer[0]
    view = _render(_content(offer_hidden=[medical.upper(), "kontrakt  B2B"]))
    offer = _field(view, "offer")
    assert medical not in offer["items"] and "kontrakt B2B" not in offer["items"]
    assert offer["hidden_fixed"] == [medical]
    assert offer["hidden_auto"] == ["kontrakt B2B"]
    assert offer["auto_count"] == 4
    assert offer["fixed_count"] == len(DEFAULTS.pl.offer) - 1
    assert medical not in _section(view, "offer")["items"]
    assert "kontrakt B2B" not in _section(view, "terms")["items"]
    assert medical not in render.rendered_texts(view)


def test_own_offer_point_repeating_a_term_or_the_fixed_block_is_shown_once():
    # Wklejona cała lista z karty: punkty z rekrutacji i stałego bloku
    # dokładają się same, więc ich kopie we własnych punktach nie wychodzą.
    pasted = ["Kontrakt B2B", DEFAULTS.pl.offer[1], "długoterminowy projekt"]
    view = _render(_content(offer=pasted))
    offer = _field(view, "offer")
    assert offer["items"].count("kontrakt B2B") == 1
    assert offer["items"].count(DEFAULTS.pl.offer[1]) == 1
    assert "Kontrakt B2B" not in offer["items"]
    assert "długoterminowy projekt" in offer["items"]
    assert _section(view, "offer")["items"].count(DEFAULTS.pl.offer[1]) == 1


def test_own_offer_drops_what_the_terms_and_fixed_block_already_say():
    material = _material()
    content = _content(offer=["kontrakt B2B", "długoterminowy projekt"])
    own = render.own_offer(
        content, render.terms_from(material, content), DEFAULTS.pl, lang="pl"
    )
    assert own == ["długoterminowy projekt"]


def test_pracuj_about_falls_back_to_the_lead_when_the_project_is_empty():
    view = _render(_content(about=""))
    assert _field(view, "about")["text"] == "Szukamy osoby do zespołu płatności."


def test_pracuj_params_are_form_choices_not_text():
    assert _render()["pracuj"]["params"] == [
        "starszy specjalista / starsza specjalistka (senior)",
        "kontrakt B2B",
        "pełny etat",
        "praca hybrydowa",
        "Warszawa",
    ]


# ── JustJoin.IT: jeden opis + pola formularza ───────────────────────────────


def test_jjit_body_has_the_house_structure():
    view = _render()
    assert [s["key"] for s in view["jjit"]["sections"]] == [
        "lead",
        "about",
        "terms",
        "responsibilities",
        "requirements",
        "nice_to_have",
        "offer",
        "process",
        "company",
    ]
    assert _section(view, "about")["heading"] == "O projekcie"
    assert _section(view, "process")["kind"] == "ordered"
    assert _section(view, "offer")["fixed_count"] == len(DEFAULTS.pl.offer)
    html_body = view["jjit"]["body_html"]
    assert html_body.startswith("<p>Szukamy osoby do zespołu płatności.</p>")
    assert (
        "<h3>Twój zakres obowiązków</h3><ul><li>rozwój mikroserwisów</li>" in html_body
    )
    assert "<ol><li>Rozmowa z rekruterem</li>" in html_body
    text_body = view["jjit"]["body_text"]
    assert "Wymagania\n• min. 5 lat doświadczenia w Javie" in text_body
    assert "1. Rozmowa z rekruterem" in text_body


def test_jjit_english_ad_uses_english_headings_and_blocks():
    view = _render(lang="en")
    assert _section(view, "requirements")["heading"] == "Requirements"
    assert _section(view, "terms")["items"][0] == "B2B contract"
    assert _section(view, "process")["items"] == list(DEFAULTS.en.process)
    assert view["title"] == "Senior Java Developer (f/m/x)"


def test_empty_sections_disappear_instead_of_leaving_a_heading():
    view = _render(_content(lead="", nice_to_have=[], responsibilities=[]))
    keys = [s["key"] for s in view["jjit"]["sections"]]
    assert "lead" not in keys and "nice_to_have" not in keys
    assert "responsibilities" not in keys
    assert "Mile widziane" not in view["jjit"]["body_html"]
    assert "Mile widziane" not in view["jjit"]["body_text"]
    assert _field(view, "nice_to_have")["html"] == ""


def test_jjit_form_fields_come_from_the_recruitment():
    fields = {f["key"]: f["value"] for f in _render()["jjit"]["form_fields"]}
    assert fields == {
        "title": "Senior Java Developer (k/m/x)",
        "experience": "Senior",
        "employment": "B2B · Full-time",
        "workplace": "Hybrid",
        "office_days": "2",
        "city": "Warszawa",
    }


def test_every_text_is_escaped_in_html():
    view = _render(
        _content(
            lead="<script>alert(1)</script>",
            requirements=["Java & <b>Spring</b>"],
        ),
        tech=[{"name": "<img src=x>", "level": "must"}],
    )
    body = view["jjit"]["body_html"]
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "<li>Java &amp; &lt;b&gt;Spring&lt;/b&gt;</li>" in body
    assert (
        _field(view, "tech_required")["html"] == "<ul><li>&lt;img src=x&gt;</li></ul>"
    )


def test_no_amounts_come_from_the_renderer():
    """Widełki wpisuje człowiek w formularzu portalu — renderer ich nie zna."""
    view = _render()
    blob = view["jjit"]["body_text"] + " ".join(
        f["text"] for f in view["pracuj"]["fields"]
    )
    assert "zł" not in blob and "PLN" not in blob


def test_rendered_texts_cover_everything_that_can_be_copied():
    """Wejście kontroli: tytuł, pola Pracuj, pola formularza, technologie
    i każda sekcja opisu — także warunki i stałe bloki."""
    view = _render()
    texts = render.rendered_texts(view)
    for expected in (
        "Senior Java Developer (k/m/x)",
        "Szukamy osoby do zespołu płatności.",
        "praca hybrydowa: 2 dni w tygodniu w biurze (Warszawa)",
        "język pracy: polski, angielski B2",
        "długoterminowy projekt",
        "Kubernetes",
        "Warszawa",
        DEFAULTS.pl.offer[0],
        DEFAULTS.pl.process[0],
        DEFAULTS.pl.about,
    ):
        assert expected in texts, expected
    assert all(texts)
