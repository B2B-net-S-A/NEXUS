"""Układ „Nowe CV” bez WeasyPrint: kontrakt wejścia, czyste funkcje, etykiety, HTML."""

from __future__ import annotations

import copy
import re

import pytest

from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS
from app.services.cv_generator_b2b.public_view import _mask_blind
from app.services.cv_new_layout import LayoutSettings, NewCvDocument, render_new_cv_html
from app.services.cv_new_layout.assets import (
    FONT_FILES,
    FONTS_DIR,
    LOGO_PATH,
    is_local_asset,
    text_width,
)
from app.services.cv_new_layout.axis import (
    MIN_SEGMENT,
    OLDER_FILL,
    W,
    career_axis,
    company_name,
    layout,
    main_career,
    stops,
)
from app.services.cv_new_layout.context import build_context
from app.services.cv_new_layout.education import highest_school, top_certs
from app.services.cv_new_layout.facts import (
    Cert,
    Span,
    cert_parts,
    certs_by_year,
    duration_text,
    lang_code,
    lang_level,
    lang_parts,
    parse_dates,
    split_degree,
    union_years,
    year_fraction,
    years_with,
)
from app.services.cv_new_layout.labels import LABELS, counted, more_at_end
from app.services.cv_new_layout.document import School
from app.services.cv_new_layout.render import sniff_image_mime
from app.services.cv_new_layout.roles import role_period
from app.services.cv_new_layout.text import (
    Keywords,
    md_bold,
    merge_fragments,
    split_items,
)
from tests._cv_new_layout_fixtures import (
    TODAY,
    blind,
    english,
    long_cv,
    short_cv,
    tiny_png,
)

NOW = 2026 + 10.6 / 12


def _html(data: dict, **kw) -> str:
    settings = kw.pop("settings", None)
    return render_new_cv_html(
        NewCvDocument.from_cv_json(data, **kw), settings=settings, today=TODAY
    )


def _text(html: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"<[^>]+>", " ", re.sub(r"<style>.*?</style>", "", html, flags=re.S)),
    )


# ---------- kontrakt wejścia ----------


def test_contract_maps_generator_keys():
    doc = NewCvDocument.from_cv_json(long_cv())
    assert doc.name == "Łucja Przykładowa"
    assert doc.position == "Starszy analityk danych"  # presentation_position wygrywa
    assert doc.language == "pl" and doc.blind is False
    assert len(doc.why) == 3 and doc.why[0].startswith("**Ponad 15 lat**")
    assert doc.experience[0].company == "Bank Przykładowy S.A."
    assert doc.experience[0].technologies == ("Python", "SQL", "Kafka", "Power BI")
    assert doc.skills[0].label == "Kategoria 1"  # bez dwukropka
    assert not doc.skills[0].content.endswith(".")
    assert len(doc.certifications) == 10
    assert doc.education[0].institution == "Politechnika Wzorcowa"


def test_contract_why_from_caller_wins_and_is_capped_at_three():
    doc = NewCvDocument.from_cv_json(
        long_cv(), why=["Jedno.", " ", "Dwa.", "Trzy.", "Cztery."]
    )
    assert doc.why == ("Jedno.", "Dwa.", "Trzy.")


def test_contract_tolerates_broken_shapes():
    data = {
        "name": None,
        "position": 7,
        "experience": ["x", {"dates": None}],
        "skills": [{"label": "A"}],
        "education": [{}],
        "languages": "Polski",
        "language": "de",
    }
    doc = NewCvDocument.from_cv_json(
        data, rodo_clause_html="<p>Zgoda</p>", consent_image=b""
    )
    assert doc.name == "" and doc.position == "7" and doc.language == "pl"
    assert (
        len(doc.experience) == 1
        and doc.skills == ()
        and doc.education == ()
        and doc.languages == ()
    )
    assert doc.consent_image is None and doc.rodo_clause_html == "<p>Zgoda</p>"


def test_blind_masks_name_and_companies_like_word_file():
    data = blind(long_cv())
    doc = NewCvDocument.from_cv_json(data)
    mirror = copy.deepcopy(data)
    _mask_blind(mirror)
    assert doc.name == mirror["name"] == "Kandydat"
    assert [r.company for r in doc.experience] == [
        j["company"] for j in mirror["experience"]
    ]
    assert doc.experience[0].company == "Firma z branży bankowość"
    en = NewCvDocument.from_cv_json(english(data))
    assert (
        en.name == "Candidate"
        and en.experience[0].company == "Company from bankowość industry"
    )


def test_blind_html_has_no_name_and_summary_heading():
    html = _html(blind(long_cv()))
    assert "Przykładowa" not in html and "Łucja" not in html
    assert "Bank Przykładowy" not in html
    assert "Podsumowanie" in html and "Dlaczego nasz kandydat" not in html
    assert "<h1 class='title'>Starszy analityk danych</h1>" in html


# ---------- czyste funkcje ----------


def test_split_items_respects_parentheses():
    assert split_items("Java (Spring, JPA), SQL, Kafka.") == [
        "Java (Spring, JPA)",
        "SQL",
        "Kafka",
    ]
    assert split_items("") == []


def test_merge_fragments_glues_declined_continuations():
    items = [
        "zarządzanie zakresem",
        "ryzykiem",
        "testy funkcjonalne",
        "regresyjne",
        "dane",
        "SQL",
    ]
    assert merge_fragments(items) == [
        "zarządzanie zakresem, ryzykiem",
        "testy funkcjonalne, regresyjne",
        "dane",
        "SQL",
    ]


def test_cert_parts_variants():
    assert cert_parts("PMP - PMI (2021)") == Cert("PMP", "PMI", "2021")
    assert cert_parts("ISTQB Foundation (2019)") == Cert("ISTQB Foundation", "", "2019")
    assert cert_parts("Scrum Master") == Cert("Scrum Master", "", "")
    # opis kursu z małej litery nie jest wystawcą
    assert cert_parts("PMP - kurs przygotowawczy w szkole online").issuer == ""


def test_certs_by_year_newest_first_undated_last():
    rows = certs_by_year(["A (2019)", "B", "C (2022)", "D"])
    assert [r.name for r in rows] == ["C", "A", "B", "D"]


def test_language_parts_levels_and_codes():
    assert lang_parts("Polski - ojczysty") == ("Polski", "ojczysty")
    assert lang_parts("polski – ojczysty") == ("polski", "ojczysty")
    assert lang_parts("Angielski: B2") == ("Angielski", "B2")
    assert lang_parts("Niemiecki") == ("Niemiecki", "")
    assert lang_level("ojczysty lub dwujęzyczny") == (6, "ojczysty")
    assert lang_level("native", "en") == (6, "native")
    assert lang_level("C1/C2") == (5, "C1/C2")
    assert lang_level("b2") == (4, "B2")
    assert lang_level("komunikatywny") == (None, "komunikatywny")
    assert (
        lang_code("Angielski") == "EN"
        and lang_code("German") == "DE"
        and lang_code("Esperanto") == "ES"
    )


def test_parse_dates_reads_each_side():
    span = parse_dates("2013 - 12.2017", NOW)
    assert (
        span.start == 2013
        and span.end == pytest.approx(2018.0)
        and not span.months_known
    )
    span = parse_dates("03.2020 – obecnie", NOW)
    assert (
        span.start == pytest.approx(2020 + 2 / 12)
        and span.end == NOW
        and span.months_known
    )
    assert parse_dates("obecnie", NOW) == Span(None, NOW, False)
    assert parse_dates("2019", NOW) == Span(2019, 2020, False)
    assert (
        parse_dates("2015 - 2015", NOW).end == 2016
    )  # sam rok: koniec co najmniej rok po początku
    assert parse_dates("", NOW) == Span(None, None, False)


def test_year_fraction():
    assert year_fraction(TODAY) == pytest.approx(2026 + (10 + 19 / 30) / 12)


def test_duration_text_rounds_down_without_months():
    assert duration_text(parse_dates("08.2024 – 12.2025", NOW)) == "1 rok 5 mies."
    assert duration_text(parse_dates("2016 - 2019", NOW)) == "ok. 3 lata"
    assert duration_text(parse_dates("01.2020 - 12.2024", NOW)) == "5 lat"
    assert duration_text(parse_dates("08.2024 – 12.2025", NOW), "en") == "1 year 5 mo."
    assert duration_text(Span(None, NOW, False)) == ""


def test_union_years_counts_overlaps_once():
    assert union_years([(2010, 2014), (2012, 2016), (2018, 2019)]) == pytest.approx(7)
    roles = [
        (Span(2010, 2014, True), "python sql"),
        (Span(2012, 2016, True), "java"),
        (Span(2015, 2017, True), "python"),
    ]
    assert years_with(roles, lambda t: "python" in t) == pytest.approx(6)


def test_highest_school_skips_unfinished_and_keeps_cv_order_on_tie():
    schools = [
        School("2010", "Informatyka - studia przerwane, magister", "Uczelnia A", ""),
        School("2008", "Ekonomia - licencjat", "Uczelnia B", ""),
        School("2006", "Zarządzanie - inżynier", "Uczelnia C", ""),
    ]
    assert highest_school(schools).institution == "Uczelnia B"
    assert highest_school([]) is None


def test_split_degree():
    assert split_degree("Informatyka - magister inżynier") == (
        "Informatyka",
        "Magister inżynier",
    )
    assert split_degree("Data Science, master") == ("Data Science", "Master")
    assert split_degree("Kurs analityczny") == ("Kurs analityczny", "")


def test_md_bold_escapes_html():
    assert md_bold("**<b>x</b>** & y") == "<b>&lt;b&gt;x&lt;/b&gt;</b> &amp; y"


def test_keywords_mark_whole_items_and_bold_like_word():
    keys = Keywords.build(["Python", "Power BI", "hurtownie danych w chmurze"])
    assert keys.is_key("python") and keys.is_key("Power BI")
    assert not keys.is_key("Python i SQL")
    assert "<b>Python</b>" in keys.bold("Potoki w Python & SQL")
    assert "&amp;" in keys.bold("Potoki w Python & SQL")


def test_text_width_uses_font_metrics():
    assert text_width("WWW", 3) > text_width("iii", 3) * 2


# ---------- oś kariery ----------


def test_company_name_strips_legal_form():
    assert company_name("Bank Przykładowy S.A.") == "Bank Przykładowy"
    assert company_name("Ubezpieczenia Beta sp. z o.o.") == "Ubezpieczenia Beta"
    assert company_name("FIRMA TESTOWA POLSKA") == "Firma Testowa"
    assert company_name("Bank Przykładowy S.A. · Bankowość") == "Bank Przykładowy"


def test_main_career_moves_contained_roles_to_parallel_and_trims_overlaps():
    ctx = build_context(NewCvDocument.from_cv_json(long_cv()), TODAY)
    dated = [r for r in ctx.roles if r.start is not None]
    main, parallel = main_career(dated)
    assert "Projekt Delta" in [
        r.role.company for r in parallel
    ]  # w całości w Logistyka Gamma
    alfa = next(r for r in main if r.role.company == "Softwarehouse Alfa")
    gamma = next(r for r in main if r.role.company == "Logistyka Gamma")
    assert alfa.end == pytest.approx(
        gamma.start
    )  # zakładka: poprzednie kończy się w dniu startu nowego


def _ctx(data: dict):
    return build_context(NewCvDocument.from_cv_json(data), TODAY)


def test_axis_is_in_order_not_in_time_scale():
    """Artur 25.11.2026 (S1): odcinek ma miejsce na pełną nazwę firmy, a nie szerokość
    z liczby lat; razem zawsze cała szerokość strony."""
    segs = layout(_ctx(long_cv()))
    assert sum(w for _, _, w in segs) == pytest.approx(W)
    assert all(w >= MIN_SEGMENT for _, _, w in segs)
    assert all(
        x2 == pytest.approx(x1 + w1) for (_, x1, w1), (_, x2, _) in zip(segs, segs[1:])
    )
    # najkrótsza praca nie jest kreską: najwyżej kilka razy węższa od najdłuższej
    widths = [w for _, _, w in segs]
    assert max(widths) / min(widths) < 4


def test_axis_collapses_oldest_and_never_truncates_names():
    data = long_cv()
    ctx = _ctx(data)
    segs = layout(ctx)
    assert segs[0][0].kind == "older" and segs[0][0].company.startswith("Wcześniej · ")
    assert segs[-1][0].current
    svg = career_axis(ctx)
    assert "…" not in svg and f'fill="{OLDER_FILL}"' in svg
    for s, _, _ in segs[1:]:
        for word in s.company.split():
            assert word in svg
    assert ">2023</text>" in svg and ">dziś</text>" in svg  # rok startu + koniec


def test_axis_groups_consecutive_short_jobs():
    data = short_cv()
    data["experience"] = [
        {
            "dates": d,
            "company": c,
            "position": "Tester",
            "industry": "",
            "technologies": [],
            "responsibilities": [],
        }
        for d, c in (
            ("05.2024 – obecnie", "Firma Kappa"),
            ("11.2023 – 04.2024", "Firma Lambda"),
            ("06.2023 – 10.2023", "Firma Mi"),
            ("01.2023 – 05.2023", "Firma Ni"),
            ("2019 - 2022", "Firma Ksi"),
        )
    ]
    st = stops(_ctx(data))
    short = [s for s in st if s.kind == "short"]
    assert len(short) == 1
    assert short[0].company == "Firma Ni · Firma Mi · Firma Lambda"
    assert short[0].role == "3 krótkie projekty"
    assert [s.company for s in st] == ["Firma Ksi", short[0].company, "Firma Kappa"]


def _roles(*dates: str) -> dict:
    data = long_cv()
    data["experience"] = [
        {
            "dates": d,
            "company": f"Firma {i}",
            "position": "Analityk",
            "industry": "",
            "technologies": [],
            "responsibilities": [],
        }
        for i, d in enumerate(dates)
    ]
    return data


@pytest.mark.parametrize(
    "dates",
    [
        (),  # CV bez stanowisk (absolwent)
        ("", ""),  # role bez dat
        ("obecnie",),  # jedyna rola bez początku
        (
            "01.2020 - obecnie",
            "01.2020 - obecnie",
            "01.2020 - obecnie",
        ),  # same równoległe kontrakty
    ],
)
def test_axis_without_segments_does_not_break_the_cv(dates):
    """Bez odcinków oś znika albo pokazuje to, co się da — CV się renderuje (przegląd 25.11.2026)."""
    data = _roles(*dates)
    career_axis(_ctx(data))
    assert "DLACZEGO NASZ KANDYDAT" in _html(data).upper()


def test_current_role_without_start_stays_on_the_axis():
    data = _roles("obecnie", "2015 - 2019")
    svg = career_axis(_ctx(data))
    assert "Firma 0" in svg and ">dziś</text>" in svg


def test_axis_english_and_blind():
    svg = career_axis(_ctx(blind(english(long_cv()))))
    assert "Earlier · " in svg and ">today</text>" in svg and "Wcześniej" not in svg


def test_role_period_follows_cv_language():
    en = build_context(NewCvDocument.from_cv_json(english(short_cv())), TODAY)
    assert role_period(en, en.roles[0]) == "05.2024 – present (2 years 7 mo.)"
    pl = build_context(NewCvDocument.from_cv_json(short_cv()), TODAY)
    assert role_period(pl, pl.roles[0]) == "05.2024 – obecnie (2 lata 7 mies.)"


def test_top_certs_prefers_role_domain():
    data = long_cv()
    data["certifications"] = [
        "Kurs Excel (2024)",
        "PMP - PMI (2015)",
        "Databricks Data Engineer (2019)",
        "Inny (2025)",
    ]
    ctx = build_context(NewCvDocument.from_cv_json(data), TODAY)
    top = top_certs(ctx, certs_by_year(ctx.doc.certifications), 3)
    assert top[0].name == "Databricks Data Engineer"


# ---------- etykiety ----------


def test_labels_pl_and_en_have_the_same_keys():
    assert LABELS["pl"].keys() == LABELS["en"].keys()


@pytest.mark.parametrize("lang", ["pl", "en"])
@pytest.mark.parametrize(
    ("ours", "word"),
    [
        ("why", "why"),
        ("education", "education"),
        ("skills", "skills"),
        ("experience", "experience"),
        ("company", "company_name"),
        ("position", "position"),
        ("tasks", "responsibilities"),
        ("technologies", "technologies"),
        ("certifications", "certifications"),
        ("dates", "dates"),
    ],
)
def test_labels_reuse_word_wording(lang, ours, word):
    expected = TRANSLATIONS[lang][word].rstrip(":?").strip()
    assert LABELS[lang][ours].casefold() == expected.casefold()


def test_plurals():
    assert counted("pl", "year", 1) == "1 rok"
    assert counted("pl", "year", 3) == "3 lata"
    assert counted("pl", "year", 12) == "12 lat"
    assert counted("pl", "year", 22) == "22 lata"
    assert counted("en", "year", 2) == "2 years"
    assert (
        more_at_end("pl", "certificate", 7)
        == "+ 7 certyfikatów — pełna lista na końcu CV"
    )
    assert (
        more_at_end("en", "school", 1) == "+ 1 school — full list at the end of the CV"
    )


# ---------- HTML ----------


def test_html_polish_headings_and_title():
    html = _html(long_cv())
    for heading in (
        "Dlaczego nasz kandydat",
        "Przebieg kariery",
        "Umiejętności",
        "Edukacja",
        "Doświadczenie",
        "Zakres zadań",
        "Technologie",
        "Nazwa firmy",
        "dziś",
        "Edukacja — pełna lista",
    ):
        assert heading in html, heading
    # stanowisko, a pod nim imię i nazwisko — bez myślnika (Artur 23.11.2026)
    assert (
        "<h1 class='title'>Starszy analityk danych</h1><div class='nm'>Łucja Przykładowa</div>"
        in html
    )
    assert "danych – " not in html
    assert "<b>PL</b> ojczysty" in html and "<b>EN</b> C1/C2" in html
    assert "<b>Ponad 15 lat</b>" in html and "Czwarty punkt" not in html


def test_html_english_headings():
    html = _html(english(long_cv()))
    for heading in (
        "Why our candidate",
        "Career path",
        "Skills",
        "Education",
        "Experience",
        "Tasks",
        "Technologies",
        "today",
        "<b>PL</b> native",
    ):
        assert heading in html, heading
    assert "Dlaczego" not in html and "Umiejętności" not in html


def test_html_page1_shows_three_certificates_and_moves_the_rest():
    text = _text(_html(long_cv()))
    assert "+ 7 certyfikatów — pełna lista na końcu CV" in text
    assert "+ 2 szkoły — pełna lista na końcu CV" in text
    assert text.count("Certyfikat danych 0") == 1  # tylko w pełnej liście (najstarszy)


def test_html_skill_cap_adds_overflow_and_full_list():
    html = _html(long_cv(), settings=LayoutSettings(font_pt=9, skill_cap=4))
    assert "<span class='more'> +10</span>" in html
    assert "Umiejętności — pełna lista" in html
    assert ".p1{font-family:'Source Sans 3',Poppins,sans-serif;font-size:9pt}" in html


def test_html_rodo_clause_is_last_and_defaults_to_word_text():
    body = _html(long_cv()).split("<body>", 1)[1]
    assert body.rfind("<div") == body.rfind("<div class='rodo'>")
    assert body.endswith(
        f"<div class='rodo'>{TRANSLATIONS['pl']['rodo']}</div></div></body></html>".replace(
            '"', "&quot;"
        )
    )
    custom = _html(long_cv(), rodo_clause_html="<p class='rodo-x'>Klauzula klienta</p>")
    assert (
        "Klauzula klienta" in custom and TRANSLATIONS["pl"]["rodo"][:40] not in custom
    )


def test_html_consent_image_before_clause_only_when_readable():
    html = _html(long_cv(), consent_image=tiny_png())
    assert "data:image/png;base64," in html
    assert html.index("class='consent'") < html.index("class='rodo'")
    assert TRANSLATIONS["pl"]["consent_heading"] in html
    assert "class='consent'" not in _html(long_cv(), consent_image=b"not an image")
    assert "class='consent'" not in _html(long_cv())


def test_sniff_image_mime():
    assert sniff_image_mime(tiny_png()) == "image/png"
    assert sniff_image_mime(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert sniff_image_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert sniff_image_mime(b"<svg") is None


def test_html_has_no_network_resources_and_assets_exist():
    html = _html(long_cv())
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in html
    for _, _, name in FONT_FILES:
        assert (FONTS_DIR / name).is_file()
    assert (FONTS_DIR / "Poppins-OFL.txt").read_text().startswith("Copyright")
    assert (FONTS_DIR / "SourceSans3-OFL.txt").read_text().startswith("Copyright")
    assert LOGO_PATH.is_file()
    assert is_local_asset(LOGO_PATH.as_uri())
    assert not is_local_asset("file:///etc/hosts")
    assert not is_local_asset("http://169.254.169.254/latest/meta-data")


def test_html_escapes_candidate_content():
    data = short_cv()
    data["experience"][0]["responsibilities"] = ["<script>alert(1)</script> testy"]
    data["name"] = "Jan <img src=x>"
    html = _html(data)
    assert "<script>" not in html and "<img src=x>" not in html
    assert "&lt;script&gt;" in html


def test_html_short_cv_skips_empty_sections():
    html = _html(short_cv())
    assert "class='pills'" not in html  # bez języków w danych — bez pastylek
    assert "Edukacja — pełna lista" not in html
    assert "Umiejętności — pełna lista" not in html


# ---------- strona 1 po warsztatach 23.11.2026 ----------


def test_languages_below_b1_and_basic_are_left_out():
    data = long_cv()
    data["languages"] = [
        "Polski - ojczysty",
        "Angielski - B1",
        "Niemiecki - A2",
        "Rosyjski - podstawowy",
        "Hiszpański - komunikatywny",
    ]
    html = _html(data)
    assert "<b>EN</b> B1" in html and "<b>ES</b> komunikatywny" in html
    assert "<b>DE</b>" not in html and "<b>RU</b>" not in html


def test_city_pill_next_to_languages_without_country_code():
    data = dict(long_cv(), candidate_location="Kraków, PL")
    html = _html(data)
    assert re.search(
        r"<span class='pill loc'><svg[^>]*>.*?</svg>Kraków</span>", html, re.S
    )
    assert "Kraków, PL" not in html
    foreign = _html(dict(long_cv(), candidate_location="Berlin, DE"))
    assert "</svg>Berlin, DE</span>" in foreign


def test_no_city_pill_without_location_or_in_blind_cv():
    assert "pill loc" not in _html(long_cv())
    assert "pill loc" not in _html(
        blind(dict(long_cv(), candidate_location="Kraków, PL"))
    )


def test_why_sentences_have_no_bullets_and_are_separated_by_rules():
    html = _html(long_cv())
    assert "<ul class='why'>" in html
    assert re.search(r"ul\.why li::before\{display:none\}", html)
    assert re.search(r"ul\.why li\{[^}]*border-top", html)


def _edu(data: dict, **kw) -> str:
    html = _html(data, **kw)
    return html[html.index("<span>Edukacja</span>") : html.index("class='rest'")]


def test_wreath_shows_degree_when_no_certificate_is_required():
    edu = _edu(long_cv())
    assert ">2008</text>" in edu  # rok dyplomu w wieńcu
    assert "Wykształcenie" in edu and "Certyfikaty i szkolenia · 10" in edu


def test_wreath_shows_certificate_required_by_client():
    data = dict(long_cv(), must_have=["Python", "PRINCE2 Practitioner"])
    data["certifications"] = data["certifications"] + [
        "PRINCE2 Practitioner - Axelos (2021)"
    ]
    edu = _edu(data)
    assert ">PRINCE2</text>" in edu and ">2021</text>" in edu
    assert "Certyfikat" in edu and "Inne certyfikaty i szkolenia · 10" in edu
    assert "<b>Informatyka</b>" in edu  # dyplom obok, bez wieńca


def test_recruiter_can_force_certificate_or_school_in_the_wreath():
    with_cert = dict(long_cv(), must_have=["PRINCE2 Practitioner"])
    with_cert["certifications"] = with_cert["certifications"] + [
        "PRINCE2 Practitioner - Axelos (2021)"
    ]
    assert ">2008</text>" in _edu(with_cert, wreath="school")
    forced = _edu(long_cv(), wreath="cert")
    assert "Inne certyfikaty i szkolenia" in forced and ">2008</text>" not in forced


def test_course_is_not_treated_as_required_certificate():
    data = dict(long_cv(), must_have=["Python"])
    data["certifications"] = ["Kurs Python dla analityków - Akademia (2023)"]
    assert ">2008</text>" in _edu(data)


def test_skill_requirement_does_not_pull_a_course_certificate_into_the_wreath():
    """Staging 23.11: MUST „UX Design” (umiejętność) dopasowało „Foundations of User
    Experience Design” — wieniec ma dostać certyfikat tylko za wymaganie-certyfikat."""
    data = dict(long_cv(), must_have=["UX Design", "Figma"])
    data["certifications"] = ["Foundations of User Experience Design - Google (2022)"]
    assert ">2008</text>" in _edu(data)
