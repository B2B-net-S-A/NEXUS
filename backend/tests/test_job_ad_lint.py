"""Kontrola ogłoszenia przed skopiowaniem na portal — bez bazy.

Przykłady pochodzą z pomiaru naszych publicznych ogłoszeń (12.10.2026):
wklejony formularz requestu, lista systemów z liczbą MD, wymagania w trzech
słowach.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.services.job_ad import lint, render
from app.services.job_ad.fixed_blocks import DEFAULTS, LangBlocks
from app.services.job_ad.material import AdMaterial


def _content(**overrides) -> dict:
    base = {
        "title": "DevOps Engineer",
        "lead": "Szukamy osoby do zespołu utrzymania platformy kredytowej.",
        "about": "Rola łączy CI/CD, monitoring i integrację systemów.",
        "start": "listopad 2026",
        "duration": "12 miesięcy",
        "language": "polski",
        "responsibilities": ["budowa i utrzymanie pipeline'ów CI/CD w Jenkinsie"],
        "requirements": ["min. 4 lata pracy z Kubernetesem i Dockerem"],
        "nice_to_have": [],
        "offer": [],
    }
    base.update(overrides)
    return base


def _lint(content, tech=(), **kwargs):
    kwargs.setdefault("client_names", ["Kwarcowy Bank"])
    kwargs.setdefault("person_names", ["Marta Przykładowa"])
    return lint.lint_ad(content, list(tech), **kwargs)


def _codes(findings, severity=None):
    return [f.code for f in findings if severity is None or f.severity == severity]


def test_clean_ad_has_no_findings():
    findings = _lint(_content())
    assert findings == []
    assert not lint.has_blocking(findings)


def test_street_address_only_advises_and_names_where_it_is():
    # Decyzja 28.10.2026: adres biura pozwala wygooglować klienta, ale nazwy
    # ulic w opisie projektu bywają niewinne — uwaga, nie blokada.
    findings = _lint(
        _content(about="Zespół pracuje w biurze przy ul. Chmielnej 89."),
        terms=["praca hybrydowa (Warszawa, Świętokrzyska 36)"],
    )
    address = [f for f in findings if f.code == lint.CODE_ADDRESS]
    assert [(f.severity, f.field) for f in address] == [
        ("advise", "about"),
        ("advise", lint.FIELD_TERMS),
    ]
    assert "Chmielnej 89" in address[0].message
    assert not lint.has_blocking(findings)


def test_city_typed_in_the_ad_is_checked_like_any_other_field():
    findings = _lint(_content(city="Warszawa, ul. Chmielna 89"))
    assert [(f.code, f.field) for f in findings] == [(lint.CODE_ADDRESS, "city")]


# ── Blokują: reguły strony kariery ──────────────────────────────────────────


def test_client_name_blocks_and_names_the_field():
    # Dopasowanie po całych słowach, jak na stronie kariery — odmienioną
    # nazwę („w Kwarcowym Banku”) łapie dopiero alias klienta.
    findings = _lint(
        _content(about="Infrastruktura systemu kredytów klienta Kwarcowy Bank.")
    )
    blocking = [f for f in findings if f.severity == lint.SEVERITY_BLOCK]
    assert [(f.code, f.field) for f in blocking] == [("client_name", "about")]
    assert "Klienta opisujemy branżą" in blocking[0].message
    assert lint.has_blocking(findings)


@pytest.mark.parametrize(
    "text",
    [
        "kontrakt B2B, stawka do 110 zł/h netto",
        "wynagrodzenie 25 000 PLN miesięcznie",
        "do 20k PLN",
        "180/h B2B",
        "1200 / MD",
        "PLN 140 za godzinę",
        # Przegląd 12.10.2026: węższa kopia wzorców przepuszczała te zapisy
        # jako uwagę, choć strona kariery je blokuje.
        "oferujemy 15 tysięcy zł miesięcznie",
        "do 180/godzinę",
        "do 25k/miesiąc",
        "do 25 000 / miesiąc",
        "1200/dni",
        # Kwoty, których wzorce strony kariery nie znają.
        "200 złotych za godzinę",
        "20 tysięcy złotych",
        "150 dolarów dziennie",
        "3000 CZK",
        "budżet projektu 2 mln PLN",
        "do 30 tys. netto",
        "180 netto/h + VAT",
        "180 ＰＬＮ",
    ],
)
def test_amount_with_a_currency_or_a_rate_unit_blocks(text):
    findings = _lint(_content(offer=[text]))
    assert [(f.code, f.severity, f.field) for f in findings] == [
        ("money", lint.SEVERITY_BLOCK, "offer")
    ]
    assert "polu wynagrodzenia portalu" in findings[0].message


def test_a_certain_amount_far_from_the_pay_word_still_blocks():
    """Wycinek znaleziska jest przycinany do 120 znaków — kwota z walutą
    na końcu długiego zdania nie może zniknąć za słowem „budżet”."""
    text = (
        "Budżet to 15 tysięcy zł w pierwszym etapie projektu, który potrwa "
        "dłużej niż planowano i w kolejnych miesiącach rośnie do 200 PLN "
        "za godzinę pracy"
    )
    assert len(text) > 120
    findings = _lint(_content(about=text))
    assert lint.has_blocking(findings)
    assert lint.CODE_POSSIBLE_MONEY not in _codes(findings)


@pytest.mark.parametrize(
    "text",
    [
        "rate limiting i throttling w Java 17",
    ],
)
def test_a_number_near_a_pay_word_without_a_currency_only_advises(text):
    """Wzorzec strony kariery jest świadomie nadgorliwy; w technicznym
    ogłoszeniu blokowałby kopiowanie zwykłych wymagań."""
    findings = _lint(_content(responsibilities=[text]))
    assert _codes(findings) == [lint.CODE_POSSIBLE_MONEY]
    assert not lint.has_blocking(findings)


def test_contact_and_surname_block():
    findings = _lint(
        _content(
            lead="Pytania kieruj na rekrutacja@example.com.",
            about="Zespół prowadzi Marta Przykładowa.",
        )
    )
    assert _codes(findings, lint.SEVERITY_BLOCK) == ["contact", "person_name"]


@pytest.mark.parametrize(
    "text",
    [
        "zadzwoń: 22 555 12 34",
        "tel. (22) 555-12-34",
        "+48 22 555 12 34",
        "+49 170 1234567",
        "jan [at] produkt-demo",
        "jan(at)firma(dot)example",
        "aplikuj: https://przyklad.example/apply",
        "www.kariera.przyklad.example/oferta/17",
        "jan＠example.com",
    ],
)
def test_links_and_contact_written_around_the_rules_block(text):
    """Treść requestu bywa z maila klienta: link „aplikuj tutaj” albo numer
    z podpisu wysłałby kandydatów poza portal."""
    findings = _lint(_content(about=f"Rola w zespole platformy. {text}"))
    assert ("contact", lint.SEVERITY_BLOCK, "about") in [
        (f.code, f.severity, f.field) for f in findings
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Praca z ASP.NET, Node.js i socket.io",
        "Next.js/React, Vue.js, C++ 17 i CI/CD",
        "2 dni w biurze na miesiąc, zespół 8 osób",
        "System obsługuje 10 mln użytkowników",
        "Start: listopad 2026, kontrakt na 12 miesięcy",
    ],
)
def test_ordinary_technical_sentences_raise_no_alarm(text):
    assert _lint(_content(about=text)) == []


def test_a_bare_site_address_is_advice():
    findings = _lint(_content(about="Produkt opisuje strona produkt-demo.pl."))
    assert [(f.code, f.severity) for f in findings] == [
        (lint.CODE_LINK, lint.SEVERITY_ADVISE)
    ]


@pytest.mark.parametrize(
    "text,code",
    [
        ("Infrastruktura klienta Kwar\u00adcowy Bank.", "client_name"),
        ("Infrastruktura klienta Kwar\u200bcowy Bank.", "client_name"),
        ("stawka 180\u200b zł/h", "money"),
        ("tel. 600\u200b100\u200b200", "contact"),
        ("pisz: jan\u200b@example.com", "contact"),
    ],
)
def test_invisible_characters_do_not_hide_a_finding(text, code):
    """Miękki łącznik i spacja zerowej szerokości przychodzą z Worda i PDF-a."""
    findings = _lint(_content(about=text))
    assert code in _codes(findings, lint.SEVERITY_BLOCK)


def test_blocking_findings_come_first():
    findings = _lint(
        _content(
            about="Stawka kandydata ustalana indywidualnie.",
            requirements=["Kwarcowy Bank — znajomość procesów bankowych"],
        )
    )
    severities = [f.severity for f in findings]
    assert severities[0] == lint.SEVERITY_BLOCK
    assert severities == sorted(severities, key=lambda s: s != lint.SEVERITY_BLOCK)


def test_technology_names_are_checked_too():
    findings = _lint(
        _content(), tech=[{"name": "System Kwarcowy Bank", "level": "must"}]
    )
    assert [(f.code, f.field) for f in findings] == [("client_name", "tech")]


# ── Kontrola widzi wszystko, co idzie do schowka ────────────────────────────


def test_city_from_the_recruitment_is_checked_and_points_at_the_champion():
    findings = _lint(_content(), terms=["Warszawa, biuro Kwarcowy Bank"])
    assert [(f.code, f.field) for f in findings] == [("client_name", "terms")]
    assert "Profilu Championa" in findings[0].message


def test_fixed_blocks_are_checked_and_point_at_the_settings():
    findings = _lint(_content(), fixed=["premia 500 zł za polecenie"])
    assert [(f.code, f.field) for f in findings] == [("money", "fixed")]
    assert "Ustawienia" in findings[0].message


def test_a_finding_is_reported_once_for_a_field_and_its_rendered_line():
    findings = _lint(
        _content(start="po akceptacji Kwarcowy Bank"),
        rendered=["start: po akceptacji Kwarcowy Bank"],
    )
    assert [(f.code, f.field) for f in findings] == [("client_name", "start")]


_SENTINEL = "tel. 600 100 200"


def _material(**overrides) -> AdMaterial:
    base = dict(
        title="DevOps Engineer",
        seniority="senior",
        about="",
        responsibilities="",
        description="",
        requirements_text="",
        critical=(),
        must=("Kubernetes",),
        nice=(),
        domains="",
        certifications="",
        pitch="",
        city="Gdańsk",
        remote_policy="hybrid",
        onsite_days_per_week=3,
        onsite_days_per_month=None,
        contract="B2B",
        start=None,
        duration=None,
        language=None,
        working_time="fulltime",
    )
    base.update(overrides)
    return AdMaterial(**base)


def _lint_rendered(content, material, blocks, tech=None):
    """Tak woła kontrolę trasa: z wynikiem renderu."""
    tech = tech if tech is not None else render.tech_from_material(material)
    rendered = render.render_ad(
        content, tech, material, blocks, lang="pl", title_suffix="kmx"
    )
    return lint.lint_ad(
        content,
        tech,
        terms=[material.city or ""],
        fixed=[*blocks.offer, *blocks.process, blocks.about],
        rendered=render.rendered_texts(rendered),
        client_names=["Kwarcowy Bank"],
        person_names=[],
    )


_CONTENT_INPUTS = [
    {"title": f"DevOps {_SENTINEL}"},
    {"lead": _SENTINEL},
    {"about": _SENTINEL},
    {"start": _SENTINEL},
    {"duration": _SENTINEL},
    {"language": _SENTINEL},
    {"responsibilities": [_SENTINEL]},
    {"requirements": [f"Kubernetes, pytania: {_SENTINEL}"]},
    {"nice_to_have": [_SENTINEL]},
    {"offer": [_SENTINEL]},
]


@pytest.mark.parametrize("patch", _CONTENT_INPUTS, ids=lambda p: next(iter(p)))
def test_sentinel_in_any_content_field_blocks(patch):
    findings = _lint_rendered(_content(**patch), _material(), DEFAULTS.pl)
    assert "contact" in _codes(findings, lint.SEVERITY_BLOCK)


def test_sentinel_in_the_city_blocks():
    findings = _lint_rendered(
        _content(), _material(city=f"Gdańsk {_SENTINEL}"), DEFAULTS.pl
    )
    assert ("contact", "terms") in [(f.code, f.field) for f in findings]


@pytest.mark.parametrize("part", ["offer", "process", "about"])
def test_sentinel_in_any_fixed_block_blocks(part):
    value = _SENTINEL if part == "about" else (_SENTINEL,)
    blocks = dataclasses.replace(DEFAULTS.pl, **{part: value})
    findings = _lint_rendered(_content(), _material(), blocks)
    assert ("contact", "fixed") in [(f.code, f.field) for f in findings]


def test_sentinel_in_a_technology_name_blocks():
    findings = _lint_rendered(
        _content(),
        _material(),
        DEFAULTS.pl,
        tech=[{"name": _SENTINEL, "level": "must"}],
    )
    assert "contact" in _codes(findings, lint.SEVERITY_BLOCK)


def test_default_blocks_and_the_title_suffix_raise_no_alarm():
    """„(k/m/x)” wygląda jak stawka „k/…”, a nią nie jest."""
    for blocks in (DEFAULTS.pl, DEFAULTS.en, LangBlocks((), (), "")):
        assert _lint_rendered(_content(), _material(), blocks) == []


# ── Stałe bloki przy zapisie w Ustawieniach ─────────────────────────────────


def test_fixed_blocks_refuse_amounts_and_contact_details():
    assert lint.lint_fixed_blocks(DEFAULTS.pl.offer) == []
    assert _codes(lint.lint_fixed_blocks(["premia 500 zł"])) == ["money"]
    assert _codes(lint.lint_fixed_blocks(["pisz: hr@example.com"])) == ["contact"]
    assert _codes(lint.lint_fixed_blocks(["więcej: www.example.com"])) == ["contact"]
    assert _codes(lint.lint_fixed_blocks(["premia 500 złotych"])) == ["money"]
    # Liczba bez waluty to nie powód, żeby odmówić zapisu.
    assert lint.lint_fixed_blocks(["stawka ustalana po 2 rozmowach z 10 osób"]) == []


# ── Doradzają ───────────────────────────────────────────────────────────────


def test_internal_request_headings_are_advice_not_a_block():
    findings = _lint(
        _content(
            about="Nazwa roli: Administrator rozwiązań chmurowych",
            offer=["Co może zachęcić kandydata? Długoterminowy projekt"],
            requirements=["MUST-HAVE Azure, Terraform, IAM, RBAC"],
        )
    )
    assert _codes(findings, lint.SEVERITY_BLOCK) == []
    assert _codes(findings).count(lint.CODE_INTERNAL_HEADING) == 3


def test_lowercase_must_have_in_a_sentence_is_fine():
    findings = _lint(
        _content(requirements=["Kubernetes jest dla nas must-have w tej roli"])
    )
    assert lint.CODE_INTERNAL_HEADING not in _codes(findings)


def test_man_days_and_request_numbers_are_advice():
    findings = _lint(
        _content(
            responsibilities=["Bankowość elektroniczna — aplikacja webowa 14 MD"],
            about="Zlecenie RITM0012345 dotyczy testów bezpieczeństwa aplikacji.",
        )
    )
    assert lint.CODE_MAN_DAYS in _codes(findings)
    assert lint.CODE_REQUEST_REF in _codes(findings)
    assert not lint.has_blocking(findings)


def test_short_requirements_are_reported_once():
    findings = _lint(
        _content(requirements=["C++", "C", "ang - B2", "praktyka z Apache Kafka"])
    )
    short = [f for f in findings if f.code == lint.CODE_SHORT_REQUIREMENT]
    assert len(short) == 1
    assert "„C++”" in short[0].message and "„ang - B2”" in short[0].message
    assert "Kafka" not in short[0].message
    assert short[0].field == "requirements"


def test_missing_terms_and_sections_are_advice():
    findings = _lint(
        _content(start="", duration="", responsibilities=[], requirements=[])
    )
    assert _codes(findings) == [
        lint.CODE_MISSING_START,
        lint.CODE_MISSING_DURATION,
        lint.CODE_EMPTY_SECTION,
        lint.CODE_EMPTY_SECTION,
    ]
    assert {f.field for f in findings} == {
        "start",
        "duration",
        "responsibilities",
        "requirements",
    }
    assert not lint.has_blocking(findings)
