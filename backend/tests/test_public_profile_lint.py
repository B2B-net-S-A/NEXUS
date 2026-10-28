"""Kontrola publicznego opisu rekrutacji i slugi strony kariery (czyste funkcje).

Bez bazy: reguły, które decydują, czy nazwa klienta albo stawka trafi na
publiczny LinkedIn, muszą być sprawdzalne wprost.
"""

from __future__ import annotations

import pytest

from app.services import career_slugs
from app.services.career_consent import (
    CONSENT_CURRENT_TEXT,
    CONSENT_FUTURE_TEXT,
    CONSENT_TEXT_VERSION,
)
from app.services.public_apply import parse_optional_fields
from app.services.public_profile_lint import lint_public_texts


def _codes(findings) -> list[str]:
    return [f.code for f in findings]


def test_client_name_is_found_case_and_diacritics_insensitive():
    findings = lint_public_texts(
        ["Projekt dla ŁÓDZKIEGO banku", "Praca w zespole pko bank polski nad CRM."],
        client_names=["PKO Bank Polski S.A."],
    )
    assert _codes(findings) == ["client_name"]
    assert "pko bank polski" in findings[0].excerpt.lower()


def test_client_alias_is_found():
    findings = lint_public_texts(
        ["Rozwój platformy mBanku dla klientów detalicznych."],
        client_names=["mBank S.A.", "mBanku"],
    )
    assert "client_name" in _codes(findings)


def test_client_name_needs_whole_words():
    # „ing" jako fragment słowa („marketing") nie jest nazwą ING.
    findings = lint_public_texts(
        ["Zespół marketingowy i testing automatyczny."], client_names=["ING"]
    )
    assert findings == []


@pytest.mark.parametrize(
    "text",
    [
        "Budżet do 180 zł/h",
        "Stawka 150 PLN netto",
        "25 000 PLN miesięcznie",
        "do 20k PLN",
        "180/h B2B",
        "1200 / MD",
        "stawka do negocjacji w okolicach 170",
        "PLN 140",
        "oferujemy 15 tys. zł",
    ],
)
def test_money_is_found(text: str):
    findings = lint_public_texts([text])
    assert _codes(findings) == ["money"], text
    assert findings[0].message.startswith("Wykryto kwotę")


@pytest.mark.parametrize(
    "text",
    [
        "Java 17+ i Spring Boot 3",
        "Start 10.2026, projekt na 12+ miesięcy",
        "2 dni w tygodniu w biurze w Warszawie",
        "Kubernetes, Kafka, PostgreSQL 16",
    ],
)
def test_ordinary_technical_text_is_clean(text: str):
    assert lint_public_texts([text]) == []


def test_contact_and_person_names_are_found():
    findings = lint_public_texts(
        [
            "Pisz na marta.nowak@b2bnetwork.pl albo dzwoń 600 111 222.",
            "Proces prowadzi Marta Nowak.",
        ],
        person_names=["Marta Nowak"],
    )
    assert "contact" in _codes(findings)
    assert "person_name" in _codes(findings)


# ── Luki domknięte 13.10.2026 (wcześniej tylko w ogłoszeniu na portale) ─────


@pytest.mark.parametrize(
    "text",
    [
        "200 złotych za godzinę",
        "20 tysięcy złotych",
        "150 dolarów dziennie",
        "3000 CZK",
        "budżet projektu 2 mln PLN",
        "do 30 tys. netto",
        "180 netto/h + VAT",
        "15 000 brutto",
        "180 ＰＬＮ",
        # Skrót „tys.” przed wielką literą nie kończy zdania — cięcie w tym
        # miejscu chowało najzwyklejszy zapis kwoty przed każdym wzorcem.
        "do 30 tys. PLN",
        "15 tys. EUR miesięcznie",
        "30 tys. Netto",
        "do 30 tys. Złotych miesięcznie",
        "WYNAGRODZENIE: 15 000 ZŁOTYCH",
        # Kropka po słowie nie jest częścią liczby.
        "stawka ok.180 zł",
        "5 000 brutto",
        "2 000 netto miesięcznie",
    ],
)
def test_amounts_in_words_and_net_gross_are_found(text: str):
    assert _codes(lint_public_texts([text])) == ["money"], text


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
        "tel22 555 12 34",
    ],
)
def test_links_other_phone_formats_and_spelled_out_addresses_are_found(text: str):
    """Kandydat aplikuje przez formularz na tej stronie — link albo numer
    w opisie wysłałby go gdzie indziej (często: na stronę klienta)."""
    assert _codes(lint_public_texts([f"Rola w zespole platformy. {text}"])) == [
        "contact"
    ], text


@pytest.mark.parametrize(
    "text,code",
    [
        ("Infrastruktura klienta Kwar\u00adcowy Bank.", "client_name"),
        ("Infrastruktura klienta Kwar\u200bcowy Bank.", "client_name"),
        ("stawka 180\u200b zł/h", "money"),
        ("tel. 600\u200b100\u200b200", "contact"),
        ("pisz: jan\u200b@example.com", "contact"),
        # Niewidoczne, a bez kategorii „format”: łącznik grafemów, selektor
        # wariantu, wypełniacz hangul.
        ("Infrastruktura klienta Kwar\u034fcowy Bank.", "client_name"),
        ("stawka 180\ufe0f zł/h", "money"),
        ("tel. 600\u3164100\u3164200", "contact"),
    ],
)
def test_invisible_characters_do_not_hide_a_finding(text: str, code: str):
    """Miękki łącznik i spacja zerowej szerokości przychodzą z Worda i PDF-a."""
    findings = lint_public_texts([text], client_names=["Kwarcowy Bank"])
    assert code in _codes(findings), text


@pytest.mark.parametrize(
    "text",
    [
        "Praca z ASP.NET, Node.js i socket.io",
        "Next.js/React, Vue.js, C++ 17 i CI/CD",
        "2 dni w biurze na miesiąc, zespół 8 osób",
        "System obsługuje 10 mln użytkowników",
        "Start: listopad 2026, kontrakt na 12 miesięcy",
        "Produkt opisuje strona produkt-demo.pl",
        "ISO 27001, RODO, 3 lata w bankowości",
        # Przegląd 13.10.2026 — fałszywe alarmy pierwszej wersji wzorców:
        "Komunikacja z zespołami w Niemczech, Austrii (AT) i Szwajcarii (CH).",
        "Aktualizacja algorytmu płac wg przepisów 2024 brutto/netto.",
        "Kalkulator w wersji 2 brutto/netto",
        "Biuro: Warszawa, 00-120 Złota 59",
        "Organizujemy 2 zloty firmowe rocznie.",
        "10k requestów/s, dostępność 24/7, 3/4 etatu",
    ],
)
def test_new_rules_leave_ordinary_text_alone(text: str):
    assert lint_public_texts([text]) == [], text


@pytest.mark.parametrize(
    "slug",
    [
        "senior-java-developer-warszawa-ab12",
        "tester-22-555-12-34-ab12",
        "analityk-2-mln-uzytkownikow-x9k2",
        "devops-180-netto-zespol-a1b2",
    ],
)
def test_job_link_slugs_do_not_trip_the_new_rules(slug: str):
    """Slug linku rekrutacji też przechodzi kontrolę, a nietrafiony adres jest
    przy zatwierdzeniu WYMIENIANY (stary daje 404) — nowe reguły nie mogą
    zacząć łapać rozesłanych już adresów."""
    assert lint_public_texts([slug]) == [], slug


@pytest.mark.parametrize(
    "slug",
    [
        # Końcówki, które trafiały we wzorce kwot: „zl” + cyfra (od początku
        # istnienia kontroli, raz na ok. 1800 linków) i cyfra + kod waluty.
        "senior-java-developer-zl1v",
        "senior-java-developer-41zl",
        "senior-java-developer-1czk",
        "rekrutacja-9uah",
    ],
)
def test_random_suffix_of_a_job_slug_is_not_content(slug: str):
    """Losową końcówkę dopisujemy sami. Kontrola czyta część z tytułu —
    inaczej zatwierdzenie opisu wymieniało rozesłany adres bez powodu."""
    assert lint_public_texts([slug]) != []
    assert lint_public_texts([career_slugs.job_slug_content(slug)]) == []


def test_job_slug_content_keeps_what_comes_from_the_title():
    assert career_slugs.job_slug_content("java-developer-nordea-ab12") == (
        "java-developer-nordea"
    )
    assert career_slugs.job_slug_content("rekrutacja-ab12") == "rekrutacja"
    assert career_slugs.job_slug_content("rekrutacja") == "rekrutacja"
    assert career_slugs.job_slug_content(None) == ""
    # Nazwa klienta w części z tytułu nadal jest znaleziskiem.
    content = career_slugs.job_slug_content("java-developer-nordea-ab12")
    assert _codes(lint_public_texts([content], client_names=["Nordea"])) == [
        "client_name"
    ]


def test_amount_start_guard_does_not_change_what_matches():
    """Liczba startuje tylko od pierwszej cyfry ciągu (ochrona przed
    kwadratowym czasem). To nie może zmienić wyniku żadnego wzorca kwoty."""
    import random
    import re

    from app.services.public_profile_lint import CERTAIN_MONEY_PATTERNS

    guard = r"(?<!\d)(?<!\d[\s.,])(?<!\d[\s.,][\s.,])"
    pairs = [
        (pattern, re.compile(pattern.pattern.replace(guard, ""), pattern.flags))
        for pattern in CERTAIN_MONEY_PATTERNS
        # Wzorzec „N netto” bez mnożnika ma własną regułę (nie rok, nie cyfra).
        if guard in pattern.pattern and "(?!(?:(?:19|20)" not in pattern.pattern
    ]
    assert len(pairs) == 5
    tokens = ["1", "20", "180", "5 000", " ", "  ", ".", ",", "zł", "PLN", "k", "tys.",
              "mln", "/h", "/ MD", "netto", "złotych", "CZK", "x", "ok.", "wersja", "-"]  # fmt: skip
    rng = random.Random(20261013)
    for _ in range(20000):
        text = "".join(rng.choice(tokens) for _ in range(rng.randint(1, 9)))
        for guarded, plain in pairs:
            assert bool(guarded.search(text)) == bool(plain.search(text)), (
                text,
                guarded.pattern,
            )


def test_money_patterns_stay_linear_on_long_whitespace():
    """Liczba, po której idzie długi ciąg spacji bez waluty, liczyła się
    sześciennie: 800 spacji = kilkanaście sekund na pętli zdarzeń, a opis
    publiczny przyjmuje 4000 znaków."""
    import time

    started = time.perf_counter()
    assert lint_public_texts(["1" + " " * 4000 + "x", "1 " * 2000 + "x"]) == []
    # Wzorce dopisane 13.10.2026: ciągi, które prawie pasują na całej długości.
    assert (
        lint_public_texts(
            [
                "ab.+-" * 800,  # adres bez „(at)”
                "+1" + "  1" * 1300 + "x",  # „+” i cyfry rozdzielone dwiema spacjami
                "12 345 67 8 " * 330,  # prawie numer stacjonarny
                "1 " * 1990 + "nett",  # liczby bez „netto”
                # NFKC wydłuża tekst: „⒛” to „20.”, U+1F101 to „0,” — 4000
                # takich znaków dawało ponad 2 s, zanim liczba dostała start
                # tylko od pierwszej cyfry ciągu.
                "\u249b" * 4000 + "x",
                "\U0001f101" * 4000 + "x",
            ]
        )
        == []
    )
    assert time.perf_counter() - started < 1.0


def test_money_message_matches_contract_shape():
    (finding,) = lint_public_texts(["Budżet do 180 zł/h"])
    assert finding.as_dict() == {
        "code": "money",
        "message": "Wykryto kwotę: „Budżet do 180 zł/h” — stawek nie publikujemy.",
        "excerpt": "Budżet do 180 zł/h",
    }


# ── Slugi ──────────────────────────────────────────────────────────────────


def test_slugify_transliterates_polish():
    assert career_slugs.slugify("Główny Księgowy — Łódź") == "glowny-ksiegowy-lodz"


def test_job_slug_base_falls_back_for_empty_title():
    assert career_slugs.job_slug_base("") == "rekrutacja"
    assert career_slugs.job_slug_base("Senior Java Developer") == (
        "senior-java-developer"
    )


def test_random_suffix_is_four_lowercase_alnum():
    suffix = career_slugs.random_suffix()
    assert len(suffix) == 4 and suffix.isalnum() and suffix == suffix.lower()


@pytest.mark.parametrize(
    "slug,ok",
    [
        ("marta-n", True),
        ("abc", True),
        ("ab", False),
        ("-marta", False),
        ("marta-", False),
        ("Marta", False),
        ("marta--n", False),
        ("marta_n", False),
        ("r", False),
        ("rodo", False),
        ("api", False),
        ("kariera", False),
        ("x" * 41, False),
    ],
)
def test_recruiter_slug_validation(slug: str, ok: bool):
    assert (career_slugs.recruiter_slug_problem(slug) is None) is ok


def test_suggested_slug_is_valid():
    slug = career_slugs.suggest_recruiter_slug("Marta Nowak")
    assert slug == "marta-n"
    assert career_slugs.recruiter_slug_problem(slug) is None


def test_career_url_falls_back_to_kariera_path_on_app_host(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "CAREER_PUBLIC_BASE_URL", "")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://nexus.example/")
    # Bez osobnej domeny strona żyje pod /kariera na hoście aplikacji —
    # tylko tam middleware ją przepuszcza.
    assert career_slugs.job_link_url("a-1b2c") == (
        "https://nexus.example/kariera/r/a-1b2c"
    )
    # Na hoście aplikacji strona rekrutera leży pod /kariera/p/<slug> —
    # /kariera/<slug> to 404 (błąd z testu na produkcji 22.09).
    assert career_slugs.recruiter_link_url("marta-n") == (
        "https://nexus.example/kariera/p/marta-n"
    )
    assert career_slugs.recruiter_base_url() == "https://nexus.example/kariera/p/"
    monkeypatch.setattr(
        settings, "CAREER_PUBLIC_BASE_URL", "https://kariera.dynaminds.pl"
    )
    assert career_slugs.recruiter_link_url("marta-n") == (
        "https://kariera.dynaminds.pl/marta-n"
    )
    assert career_slugs.recruiter_base_url() == "https://kariera.dynaminds.pl/"
    assert career_slugs.job_link_url("a-1b2c") == (
        "https://kariera.dynaminds.pl/r/a-1b2c"
    )


def test_career_url_ignores_stray_punctuation_after_domain(monkeypatch):
    # 23.10.2026: na produkcji zmienna miała średnik na końcu i wszystkie
    # linki wychodziły jako „https://kariera.b2bnetwork.pl;/artur-t" —
    # przeglądarka takiego adresu nie otwiera.
    from app.core.config import settings

    monkeypatch.setattr(
        settings, "CAREER_PUBLIC_BASE_URL", " https://kariera.b2bnetwork.pl; "
    )
    assert career_slugs.recruiter_link_url("artur-t") == (
        "https://kariera.b2bnetwork.pl/artur-t"
    )
    assert career_slugs.job_link_url("a-1b2c") == (
        "https://kariera.b2bnetwork.pl/r/a-1b2c"
    )
    assert career_slugs.career_base_url() == "https://kariera.b2bnetwork.pl"
    monkeypatch.setattr(
        settings, "CAREER_PUBLIC_BASE_URL", "https://kariera.b2bnetwork.pl/,"
    )
    assert career_slugs.recruiter_base_url() == "https://kariera.b2bnetwork.pl/"


# ── Zgoda i pola opcjonalne ────────────────────────────────────────────────


def test_consent_texts_name_the_controller_and_split_the_purposes():
    """Decyzja D (19.10.2026): obowiązkowa zgoda nie obejmuje już przyszłych
    rekrutacji — to osobna, dobrowolna zgoda."""
    for text in (CONSENT_CURRENT_TEXT, CONSENT_FUTURE_TEXT):
        assert "B2B.NET S.A." in text
    assert "przyszł" not in CONSENT_CURRENT_TEXT
    assert "przyszłych procesów rekrutacyjnych" in CONSENT_FUTURE_TEXT
    assert CONSENT_TEXT_VERSION == "2026-10-19"


def test_optional_fields_accept_blank_strings():
    out = parse_optional_fields(
        expected_rate_hourly="", availability_date="", city="  ", work_mode=""
    )
    assert out == {
        "expected_rate_hourly": None,
        "availability_date": None,
        "city": None,
        "work_mode": None,
    }


@pytest.mark.parametrize(
    "kwargs,field",
    [
        ({"expected_rate_hourly": "0"}, "expected_rate_hourly"),
        ({"expected_rate_hourly": "abc"}, "expected_rate_hourly"),
        ({"expected_rate_hourly": "10001"}, "expected_rate_hourly"),
        ({"availability_date": "01.10.2026"}, "availability_date"),
        ({"work_mode": "office"}, "work_mode"),
        ({"city": "x" * 121}, "city"),
    ],
)
def test_optional_fields_reject_with_field_loc(kwargs, field):
    from fastapi import HTTPException

    base = {
        "expected_rate_hourly": None,
        "availability_date": None,
        "city": None,
        "work_mode": None,
    }
    with pytest.raises(HTTPException) as exc:
        parse_optional_fields(**{**base, **kwargs})
    assert exc.value.status_code == 422
    assert exc.value.detail[0]["loc"] == ["body", field]


# ── Tytuł publiczny (0340) ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("title", "clients", "expected"),
    [
        (
            "Nordea: ESG Regulatory Reporting Pillar 3 (42835)",
            ["Nordea Bank Abp"],
            "ESG Regulatory Reporting Pillar 3",
        ),
        (
            "Nordea: ESG Regulatory Reporting Pillar 3 (42835)",
            ["Nordea Bank Abp", "Nordea"],
            "ESG Regulatory Reporting Pillar 3",
        ),
        ("Tester Manualny (ZOB-3003)", [], "Tester Manualny"),
        ("Test Automation Engineer RITM0857078", [], "Test Automation Engineer"),
        ("Java Developer - REQ12345", [], "Java Developer"),
        (
            "PL - CBP - Solution Architecture - SENIOR T24 ARCHITECT, Pep: 4979 (42827)",
            [],
            "PL - CBP - Solution Architecture - SENIOR T24 ARCHITECT",
        ),
        ("Senior Data Architect", ["Nordea Bank Abp"], "Senior Data Architect"),
        ("NORDEA BANK ABP – Java Dev", ["Nordea Bank Abp"], "Java Dev"),
        ("mBank | Analityk Biznesowy", ["mBank S.A.", "mBank"], "Analityk Biznesowy"),
        # Pierwsze słowo nazwy klienta krótsze niż 4 litery nie jest prefiksem.
        ("ING: Tester", ["ING Bank Śląski"], "ING: Tester"),
        ("ING: Tester", ["ING Bank Śląski", "ING"], "Tester"),
        ("Tester (m/k)", [], "Tester (m/k)"),
        ("  Java   17   Developer  ", [], "Java 17 Developer"),
        # 19.10.2026: numer BNP po podkreślniku szedł na stronę i do adresu.
        ("Software Developer_RITM0866775", [], "Software Developer"),
        ("Java Developer_REQ0012345", [], "Java Developer"),
        ("Power BI_PKN500023226", [], "Power BI"),
        # Nawias z cyfrą bywa częścią roli — zostaje (jak w nagłówku CV).
        ("DevOps Engineer (K8s)", [], "DevOps Engineer (K8s)"),
        ("Administrator (ISO 27001)", [], "Administrator (ISO 27001)"),
        ("Data Engineer (Python 3)", [], "Data Engineer (Python 3)"),
        # Kilka numerów zapytań i numer z dopiskiem też schodzą (przegląd 19.10).
        ("IT Analyst (42928, 42927)", [], "IT Analyst"),
        ("Java (nr 42835)", [], "Java"),
        ("Java Developer (ID 4521)", [], "Java Developer"),
    ],
)
def test_default_public_title(title, clients, expected):
    from app.services.job_public_profile import default_public_title

    assert default_public_title(title, clients) == expected


def test_default_public_title_never_empty():
    from app.services.job_public_profile import default_public_title

    assert default_public_title("(42835)", []) == "(42835)"
    assert default_public_title("Nordea:", ["Nordea Bank Abp"]) == "Nordea"
    assert default_public_title("RITM0857078", []) == "RITM0857078"
    assert default_public_title("", []) == ""
    assert default_public_title(None, []) == ""


def test_default_public_title_drops_the_client_reference_anywhere():
    from app.services.job_public_profile import default_public_title

    assert (
        default_public_title("Java Developer 42946 Warszawa", [], "42946")
        == "Java Developer Warszawa"
    )
    # Numer „4521” nie wycina kawałka dłuższej liczby.
    assert default_public_title("Tester 145210", [], "4521") == "Tester 145210"
    # Kilka numerów w nawiasie: bez resztek „(,)” po wycięciu.
    assert (
        default_public_title("IT Analyst (42928, 42927)", [], "42928, 42927")
        == "IT Analyst"
    )


def test_legacy_default_title_keeps_the_rules_from_before_19_10():
    from app.services.job_public_profile import legacy_default_public_title

    assert (
        legacy_default_public_title("Software Developer_RITM0866775", [])
        == "Software Developer_RITM0866775"
    )
    assert legacy_default_public_title("DevOps Engineer (K8s)", []) == (
        "DevOps Engineer"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Software Developer_RITM0866775",
        "Numer zgłoszenia RITM0866775 w opisie.",
        "Projekt ZOB-3003 trwa rok.",
        "Wsparcie zespołu (PKN500023226).",
        "SCTASK0123456",
        "Tester_PKN/5/000177/26",
    ],
)
def test_internal_codes_are_findings(text):
    from app.services.public_profile_lint import CODE_INTERNAL, lint_internal_codes

    findings = lint_internal_codes([text])
    assert [f.code for f in findings] == [CODE_INTERNAL]


@pytest.mark.parametrize(
    "text",
    [
        "Java 17, Spring Boot 3 i Kafka.",
        "Zespół 8 osób, 2 dni w biurze.",
        "Certyfikat ISO 27001 mile widziany.",
        "Wersja REQ bez numeru.",
    ],
)
def test_ordinary_text_has_no_internal_codes(text):
    from app.services.public_profile_lint import lint_internal_codes

    assert lint_internal_codes([text]) == []


def test_client_reference_in_text_is_an_internal_code():
    from app.services.public_profile_lint import lint_internal_codes

    findings = lint_internal_codes(
        ["Rekrutacja 42946 dla zespołu płatności."], client_reference="42946, 42947"
    )
    assert len(findings) == 1 and "42946" in findings[0].message
    # Krótkie numery (mniej niż 4 znaki) nie są szukane — za dużo trafień.
    assert lint_internal_codes(["Zespół 123 osób."], client_reference="123") == []


def test_internal_codes_do_not_touch_the_slug_check():
    """Kontrola adresu (``lint_public_texts``) nie zna kodów: znalezisko
    w adresie wymieniałoby rozesłany link na nowy, a stary dawałby 404."""
    from app.services.public_profile_lint import lint_public_texts

    assert lint_public_texts(["software-developer-ritm0866775-ab12"]) == []


def test_client_prefix_needs_a_separator_and_whole_words():
    from app.services.job_public_profile import default_public_title

    # Bez separatora to może być zwykłe słowo tytułu — zostaje.
    assert default_public_title("Nordea Java Developer", ["Nordea Bank Abp"]) == (
        "Nordea Java Developer"
    )
    assert default_public_title("Nordeax: Tester", ["Nordea Bank Abp"]) == (
        "Nordeax: Tester"
    )


def test_trim_subtitle_cuts_on_word_boundary_without_period():
    from app.services.job_public_profile import DRAFT_SUBTITLE_MAX, trim_subtitle

    long = (
        "rozwój platformy płatności w sektorze bankowym dla dużej organizacji "
        "z wieloma zespołami rozproszonymi po Europie i Azji."
    )
    out = trim_subtitle(long)
    assert len(out) <= DRAFT_SUBTITLE_MAX
    assert long.startswith(out)
    assert not out.endswith(" ") and not out.endswith(".")
    assert trim_subtitle("rozwój platformy płatności.") == "rozwój platformy płatności"


def test_content_hash_includes_the_title():
    from app.services.job_public_profile import content_hash

    a = content_hash("s", "a", None, "Tytuł A")
    assert a != content_hash("s", "a", None, "Tytuł B")
    assert a != content_hash("s", "a", None)


def test_job_is_open_means_published_regardless_of_handoff():
    from types import SimpleNamespace

    from app.models.job import JobStatus
    from app.services.job_public_profile import job_is_open

    assert job_is_open(SimpleNamespace(status=JobStatus.published, is_open=False))
    assert not job_is_open(SimpleNamespace(status=JobStatus.closed, is_open=True))
    assert not job_is_open(SimpleNamespace(status=JobStatus.draft, is_open=True))
    assert not job_is_open(None)


def test_draft_material_uses_given_title_and_falls_back_to_description():
    from types import SimpleNamespace

    from app.services.job_public_profile import draft_material

    job = SimpleNamespace(
        title="Nordea: Data Engineer (42835)",
        champion_profile={},
        description="Budowa hurtowni danych w chmurze.",
        requirements="3 lata z Pythonem.",
        must_skills=None,
        nice_skills=None,
        remote_policy=None,
        onsite_days_per_week=None,
        location=None,
        seniority=None,
        recruitment_type=None,
    )
    out = draft_material(job, "Data Engineer")
    assert out["title"] == "Data Engineer"
    assert out["description"] == "Budowa hurtowni danych w chmurze."
    assert out["requirements"] == "3 lata z Pythonem."
    job.champion_profile = {"project": {"about": "Hurtownia", "responsibilities": ""}}
    out = draft_material(job)
    assert out["description"] == "brak" and out["requirements"] == "brak"
    # Bez podanego tytułu: domyślny bez znajomości klienta (kody zdjęte).
    assert out["title"] == "Nordea: Data Engineer"


# ── Runda 8 (R8-N4-1): sekcje ukryte przełącznikiem też są publiczne ───────


def test_hidden_sections_are_still_linted():
    from app.services.job_public_profile import _payload_texts

    payload = {
        "title": "Java Developer",
        "subtitle": None,
        "about": None,
        "must": [{"name": "Znajomość systemów PKO BP", "note": None}],
        "nice": ["Praca w pko bp"],
        "params": {"city": "Centrala PKO BP", "start": None, "duration": None},
        "show": {"must": False, "nice": False, "params": False, "process": True},
    }
    findings = lint_public_texts(_payload_texts(payload), client_names=["PKO BP"])
    assert _codes(findings) == ["client_name"] * 3


# ── Runda 8 (decyzja Artura 27.09.2026): ukryta sekcja znika z danych ───────


def _hidden_job():
    from types import SimpleNamespace

    return SimpleNamespace(
        champion_profile={
            "basics": {"start_date": "10.2026", "contract_length": "12 mies."},
            "stack": {"must": [{"name": "Java 17"}], "nice": [{"name": "Kafka"}]},
        },
        must_skills=None,
        nice_skills=None,
        location="Warszawa",
        remote_policy=None,
        onsite_days_per_week=2,
        seniority=None,
    )


def _public(sections, **kwargs):
    from app.services.job_public_profile import public_job_payload

    return public_job_payload(
        _hidden_job(),
        title="Java Developer",
        link_slug="java-dev",
        subtitle="Rozwój platformy",
        about="Opis",
        sections=sections,
        **kwargs,
    )


_HIDDEN = {"must": False, "nice": False, "params": False, "process": True}


def test_hidden_sections_vanish_from_the_public_projection():
    payload = _public(_HIDDEN)
    assert payload["must"] == [] and payload["nice"] == []
    params = payload["params"]
    for key in ("city", "remote_policy", "onsite_days_per_week", "seniority"):
        assert params[key] is None, key
    assert params["start"] is None and params["duration"] is None
    # Stała firmy, nie dana rekrutacji — czyta ją sekcja „proces”.
    assert params["contract"] == "B2B"
    assert payload["show"] == _HIDDEN


def test_shown_sections_stay_in_the_public_projection():
    payload = _public(None)
    assert payload["must"] == [{"name": "Java 17", "note": None}]
    assert payload["nice"] == ["Kafka"]
    assert payload["params"]["city"] == "Warszawa"
    assert payload["params"]["start"] == "10.2026"


def test_hidden_sections_from_the_approval_snapshot_also_vanish():
    from app.services import job_public_profile as jpp

    full = _public(_HIDDEN, respect_show=False)
    assert full["must"] == [{"name": "Java 17", "note": None}]
    stored = jpp.sections_with_approved_content(_HIDDEN, jpp.approved_content(full))
    # Migawka niesie pełne pola (inaczej edytor widziałby fałszywą „zmianę”)…
    assert jpp.stored_approved_content(stored)["must"] == ["Java 17"]
    assert not jpp.approved_content_stale(_hidden_job(), stored)
    # …ale strona i portale dostają okrojoną projekcję.
    served = _public(stored)
    assert served["must"] == [] and served["params"]["city"] is None
    assert jpp.visible_params(_hidden_job(), stored)["city"] is None
    assert jpp.visible_params(_hidden_job(), None)["city"] == "Warszawa"


def test_portal_refuses_hidden_must_with_a_clear_reason():
    from app.services.job_portals import jjit_payload

    options = jjit_payload.normalize_options(
        {
            "category": "java",
            "experience_level": "senior",
            "working_time": "full_time",
            "workplace_type": "remote",
            "city": "Warszawa",
        }
    )
    payload = _public(_HIDDEN)
    assert jjit_payload.skill_split("rocketjobs", payload) == ([], [])
    problems = jjit_payload.validate("rocketjobs", payload, options)
    assert any("ukryta" in p for p in problems), problems
    assert "Szczegóły" not in jjit_payload.build_body(payload)
    assert jjit_payload.validate("rocketjobs", _public(None), options) == []


# ── Strona zostaje na zatwierdzonej wersji (19.10.2026) ────────────────────


def _approved_profile(**overrides):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from app.services import job_public_profile as jpp

    subtitle, about, title = "podtytuł", "Opis zatwierdzony.", "Software Developer"
    show = jpp.normalize_sections(None)
    payload = {
        "title": title,
        "subtitle": subtitle,
        "about": about,
        "must": [{"name": "Java 17", "note": None}],
        "nice": ["Kafka"],
        "params": {"city": "Warszawa", "start": None, "duration": None},
        "show": show,
    }
    profile = SimpleNamespace(
        subtitle=subtitle,
        about=about,
        public_title=None,
        approved_at=datetime.now(timezone.utc),
        approved_hash=jpp.content_hash(subtitle, about, show, title),
        sections=jpp.sections_with_approved_content(
            show, jpp.approved_content(payload, client_id=7)
        ),
    )
    for key, value in overrides.items():
        setattr(profile, key, value)
    return profile


def _job(client_id=7):
    from types import SimpleNamespace

    return SimpleNamespace(client_id=client_id, title="Software Developer")


def test_approved_profile_is_published_as_is():
    from app.services import job_public_profile as jpp

    profile = _approved_profile()
    version = jpp.published_from(
        _job(),
        profile,
        status=jpp.STATUS_APPROVED,
        effective_title="Software Developer",
    )
    assert version is not None and version.pending_changes is False
    assert version.about == "Opis zatwierdzony."


def test_edit_after_approval_keeps_the_approved_text_live():
    from app.services import job_public_profile as jpp

    profile = _approved_profile(about="Nowa treść, jeszcze bez kontroli.")
    version = jpp.published_from(
        _job(), profile, status=jpp.STATUS_DRAFT, effective_title="Software Developer"
    )
    assert version is not None and version.pending_changes is True
    assert version.about == "Opis zatwierdzony."
    assert version.title == "Software Developer"
    # Migawka must/nice jedzie razem z tekstem — strona dostaje pełne sekcje.
    payload = jpp.public_job_payload(
        _job_for_payload(),
        title=version.title,
        link_slug="x",
        subtitle=version.subtitle,
        about=version.about,
        sections=version.sections,
    )
    assert payload["must"] == [{"name": "Java 17", "note": None}]


def _job_for_payload():
    from types import SimpleNamespace

    return SimpleNamespace(
        client_id=7,
        title="Software Developer",
        champion_profile={},
        must_skills=[],
        nice_skills=[],
        location="Kraków",
        remote_policy=None,
        onsite_days_per_week=None,
        onsite_days_per_month=None,
        seniority=None,
    )


def test_tampered_snapshot_is_not_published():
    from app.services import job_public_profile as jpp

    profile = _approved_profile(about="Nowa treść.")
    snapshot = jpp.stored_approved_content(profile.sections)
    snapshot[jpp.APPROVED_TEXT_KEY]["about"] = "Tekst, którego nikt nie zatwierdził."
    version = jpp.published_from(
        _job(), profile, status=jpp.STATUS_DRAFT, effective_title="Software Developer"
    )
    assert version is None


def test_client_change_still_takes_the_page_down():
    from app.services import job_public_profile as jpp

    profile = _approved_profile(about="Nowa treść.")
    version = jpp.published_from(
        _job(client_id=8),
        profile,
        status=jpp.STATUS_DRAFT,
        effective_title="Software Developer",
    )
    assert version is None


def test_never_approved_profile_is_not_published():
    from app.services import job_public_profile as jpp

    profile = _approved_profile(approved_at=None, approved_hash=None)
    assert (
        jpp.published_from(
            _job(), profile, status=jpp.STATUS_DRAFT, effective_title="X"
        )
        is None
    )


def test_profile_approved_before_19_10_keeps_its_old_default_title():
    """Opis bez tekstu w migawce, którego tytuł domyślny zmieniły nowe reguły
    czyszczenia: strona zostaje z tytułem zatwierdzonym."""
    from app.services import job_public_profile as jpp

    old_title = "Software Developer_RITM0866775"
    profile = _approved_profile()
    profile.approved_hash = jpp.content_hash(
        profile.subtitle, profile.about, profile.sections, old_title
    )
    snapshot = jpp.stored_approved_content(profile.sections)
    snapshot.pop(jpp.APPROVED_TEXT_KEY)
    version = jpp.published_from(
        _job(),
        profile,
        status=jpp.STATUS_DRAFT,
        effective_title="Software Developer",
        legacy_title=old_title,
    )
    assert version is not None and version.title == old_title
    assert version.pending_changes is True
    # Pierwszy zapis zmian dopisuje tekst do migawki — kolejne zmiany już
    # nie zdejmują strony.
    sections = jpp.with_published_text(profile.sections, version)
    profile.sections = sections
    profile.about = "Poprawiony opis."
    again = jpp.published_from(
        _job(), profile, status=jpp.STATUS_DRAFT, effective_title="Software Developer"
    )
    assert again is not None and again.about == "Opis zatwierdzony."
    assert again.title == old_title


# ── Plakat z kodem QR (etap 3, 19.10.2026) ────────────────────────────────


def _poster_payload(**overrides):
    payload = {
        "title": "Senior <Java> Developer",
        "subtitle": "rozwój platformy płatności",
        "about": "Opis, którego plakat nie pokazuje.",
        "must": [
            {"name": n, "note": None} for n in ("Java 17", "Spring", "Kafka", "K8s")
        ],
        "nice": [],
        "params": {"city": "Warszawa", "remote_policy": "hybrid", "contract": "B2B"},
        "show": {},
    }
    payload.update(overrides)
    return payload


def test_poster_html_escapes_text_and_embeds_the_qr_as_data_uri():
    pytest.importorskip("segno")
    from app.services.career_poster import poster_html

    doc = poster_html(_poster_payload(), "https://kariera.example/r/java-ab12")
    assert "Senior &lt;Java&gt; Developer" in doc and "<Java>" not in doc
    assert 'src="data:image/svg+xml' in doc
    assert "[warszawa · hybryda · b2b]" in doc
    # Najwyżej trzy wymagania; opis projektu nie trafia na plakat.
    assert "Kafka" in doc and "K8s" not in doc
    assert "Opis, którego" not in doc
    assert "https://kariera.example/r/java-ab12" in doc
    # Żadnego zasobu spoza data: — renderer i tak by go zablokował.
    assert "http://" not in doc.replace("https://kariera.example", "")


def test_poster_uses_the_recruitment_theme_colors():
    """Plakat w kolorach szablonu; nieznany szablon (np. dawna scena) = Grafit."""
    pytest.importorskip("segno")
    from app.services.career_poster import poster_html

    url = "https://kariera.example/r/java-ab12"
    light = poster_html(_poster_payload(), url, "jasny")
    assert "background: #F5F4EC" in light and "color: #C42536" in light
    fallback = poster_html(_poster_payload(), url, "papier")
    assert "background: #141414" in fallback and "color: #F05A69" in fallback


def test_poster_without_optional_sections_has_no_empty_blocks():
    pytest.importorskip("segno")
    from app.services.career_poster import poster_html

    doc = poster_html(
        _poster_payload(subtitle=None, must=[], params={}), "https://k.example/r/x"
    )
    assert '<p class="sub">' not in doc and "<ul>" not in doc


def test_poster_pdf_renders_when_weasyprint_is_available():
    pytest.importorskip("segno")
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        pytest.skip("WeasyPrint bez bibliotek systemowych (pango)")
    from app.services.career_poster import render_poster_pdf

    pdf = render_poster_pdf(_poster_payload(), "https://kariera.example/r/java-ab12")
    assert pdf.startswith(b"%PDF")
