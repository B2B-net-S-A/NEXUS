"""Unit tests for the CV Generator B2B pipeline helpers.

Covers the 2026-06-10 audit fixes:
  * champion keyword bolding — phrase-aware, word-boundary matching
    (multi-word MUST-HAVEs match, "Git" no longer bolds "digital", and a
    filler phrase like "Znajomość Java" still bolds the real term "Java"),
  * Claude response normalization (missing keys must not KeyError → 500),
  * the anti-fabrication seatbelt ("makijaż, nie inna osoba" — every
    technology/cert in the output must be traceable to CV or notes),
  * filename sanitization (ł → l, not dropped),
  * .doc upload rejection with a clear message.
"""

from __future__ import annotations

import pytest

from app.services.cv_generator_b2b.docx_renderer import (
    add_text_with_highlights,
    compile_keyword_patterns,
    highlight_spans,
)
from app.services.cv_generator_b2b.standalone_service import (
    StandaloneGenerationError,
    _fabrication_warnings,
    _normalize_candidate_data,
    _sanitize_for_filename,
    _validate_upload,
    ascii_filename_fallback,
    rerender_docx_from_payload,
)


# ── Keyword bolding ────────────────────────────────────────────────────────


def _matches(text: str, keywords: list[str]) -> list[str]:
    patterns = compile_keyword_patterns(keywords)
    return [text[s:e] for s, e in highlight_spans(text, patterns)]


def test_multiword_keyword_matches():
    assert _matches("Budowa pipeline'ów GitLab CI/CD od zera", ["GitLab CI/CD"]) == [
        "GitLab CI/CD"
    ]


def test_multiword_keyword_matches_with_spaced_slash():
    assert _matches("GitLab CI / CD w praktyce", ["GitLab CI/CD"]) == ["GitLab CI / CD"]


def test_substring_does_not_overbold():
    # Old token-based matching bolded "digital" for keyword "Git".
    assert _matches("digital transformation", ["Git"]) == []
    assert _matches("Praca z Git i GitLab", ["Git"]) == ["Git"]


def test_parenthesized_alias_matches_both_forms():
    found = _matches("klaster K8s, potem Kubernetes", ["Kubernetes (K8s)"])
    assert found == ["K8s", "Kubernetes"]


def test_special_char_keywords():
    assert _matches("programowanie w C++ oraz C", ["C++"]) == ["C++"]
    assert _matches("aplikacje .NET i C#", ["C#"]) == ["C#"]


def test_case_insensitive():
    assert _matches("doświadczenie z RABBITMQ", ["RabbitMQ"]) == ["RABBITMQ"]


def test_stopword_keywords_skipped():
    # Champion data sometimes contains noise like "i"/"w" — never bold those.
    assert _matches("praca w zespole i z klientem", ["w", "i"]) == []


def test_add_text_with_highlights_splits_runs():
    class FakeRun:
        def __init__(self) -> None:
            class Font:
                name = None
                color = type("C", (), {"rgb": None})()
                size = None
                bold = None

            self.font = Font()
            self.text = ""

    class FakePara:
        def __init__(self) -> None:
            self.runs: list[tuple[str, FakeRun]] = []

        def add_run(self, text: str) -> FakeRun:
            run = FakeRun()
            self.runs.append((text, run))
            return run

    para = FakePara()
    add_text_with_highlights(para, "Docker, Kubernetes i Bash", ["Kubernetes"])
    texts = [t for t, _ in para.runs]
    bolds = [r.font.bold for _, r in para.runs]
    assert texts == ["Docker, ", "Kubernetes", " i Bash"]
    assert bolds == [None, True, None]


def test_descriptive_parenthetical_bolds_only_base_term():
    # The screenshot bug: "Figma (zaawansowana znajomość)" used to split into a
    # bold keyword "zaawansowana znajomość" that then bolded those generic
    # words throughout the CV prose. Now only the real skill bolds.
    kw = ["Figma (zaawansowana znajomość)"]
    assert _matches("Projektowanie w Figma i Sketch", kw) == ["Figma"]
    # The qualifier must NEVER bold on its own.
    assert _matches("zaawansowana znajomość narzędzi UX", kw) == []


def test_acronym_parenthetical_still_splits():
    # Genuine aliases ("K8s", ".NET", "PL/SQL") must keep bolding both forms.
    assert _matches("klaster K8s, potem Kubernetes", ["Kubernetes (K8s)"]) == [
        "K8s",
        "Kubernetes",
    ]
    assert _matches("aplikacje .NET", ["Microsoft (.NET)"]) == [".NET"]


def test_generic_single_word_keyword_skipped():
    # Champion lists sometimes contain proficiency/filler entries on their own.
    assert _matches("zaawansowana znajomość Figma", ["znajomość"]) == []
    assert _matches("Docker mile widziane", ["mile widziane"]) == []
    assert _matches("bardzo dobra znajomość AWS", ["bardzo dobra znajomość"]) == []


def test_hyphen_space_spelling_drift_matches():
    # Champion list vs CV often disagree on hyphen vs space — match both ways
    # (multi-word tech "react native" ↔ "react-native").
    assert _matches("Aplikacje w react native", ["react-native"]) == ["react native"]
    assert _matches("Zaawansowany react-native", ["react native"]) == ["react-native"]


def test_filler_phrase_bolds_real_term():
    # "Bolds only part" bug: a champion entry written as natural language
    # ("Znajomość Java") never matched because the CV writes just "Java".
    # Now the filler is stripped and the real term still bolds.
    assert _matches("Programowanie w Java i Spring", ["Znajomość Java"]) == ["Java"]
    assert _matches("Backend w Spring Boot", ["Dobra znajomość Spring Boot"]) == [
        "Spring Boot"
    ]


def test_separate_skill_chips_each_bold():
    # Champion skills arrive as separate chips — each bolds where present.
    assert _matches("Stack: Java, Python i Go", ["Java", "Python"]) == [
        "Java",
        "Python",
    ]


def test_multiword_technology_stays_whole_concept_drops():
    # A genuine multi-word TECHNOLOGY bolds whole ("Spring Boot") — never its
    # bare common part ("boot"). A multi-word CONCEPT ("Design System") is not
    # a technology, so it must NOT bold at all (tech-only directive).
    assert _matches("Backend w Spring Boot dla klienta", ["Spring Boot"]) == [
        "Spring Boot"
    ]
    assert _matches("Tworzenie Design System dla klienta", ["Design System"]) == []
    assert _matches("migracja systemu do nowej wersji", ["Design System"]) == []


def test_verbose_requirement_never_bolds_generic_words():
    # The over-bolding recruiters reported: a wordy champion entry stays whole
    # and only matches verbatim, so its generic words never bold the CV prose.
    kw = ["Tworzenie i rozwój aplikacji webowych"]
    assert _matches("Tworzenie dokumentacji projektu", kw) == []
    assert _matches("dbam o rozwój zespołu i procesów", kw) == []


def test_requirement_prose_words_never_bold():
    # User-cited noise: these must never bold, even as single champion entries.
    assert (
        _matches("Posiada kluczowe technologie wymagane na stanowisku", ["Technologie"])
        == []
    )
    assert _matches("praca na stanowisku starszego developera", ["stanowisku"]) == []
    assert _matches("Tworzenie i utrzymanie usług", ["Tworzenie"]) == []
    # ...but a real skill wrapped in requirement prose still bolds.
    assert _matches("Posiada Java i Spring na stanowisku", ["Znajomość Java"]) == [
        "Java"
    ]


def test_verbose_requirement_bolds_only_buried_tech():
    # Recruiter directive: bold ONLY technologies. A wordy non-tech requirement
    # ("bazami danych SQL") never bolds the Polish prose — only the hard-tech
    # token buried inside it ("SQL") surfaces.
    kw = ["Doświadczenie z bazami danych SQL"]
    assert _matches("Pracował z bazami danych SQL i NoSQL", kw) == ["SQL"]
    # No tech token present → an unrelated prose line stays clean.
    assert _matches("migracja systemów do chmury", kw) == []


def test_strong_tech_tokens_pulled_from_requirement_prose():
    # Special-char / digit / acronym tokens are unmistakably tech, so they bold
    # even when the surrounding phrase is inflected differently in the CV.
    assert _matches("Aplikacje w C++ i Java", ["Programowanie w C++"]) == ["C++"]
    assert _matches("Backend w .NET", ["Tworzenie usług w .NET"]) == [".NET"]
    assert _matches("Praca z SQL Server", ["Microsoft SQL Server"]) == ["SQL"]


def test_non_tech_substantive_phrase_does_not_bold():
    # A substantive but non-technology requirement ("aplikacji webowych") must
    # NOT bold — it carries no tech token. Only technologies bold.
    kw = ["Tworzenie aplikacji webowych"]
    assert _matches("Projektowanie aplikacji webowych dla klienta", kw) == []
    assert _matches("Tworzenie dokumentacji technicznej", kw) == []


def test_champion_design_chips_only_hard_tech_bolds():
    # Real UI-Designer champion MUST-HAVE chips: "KONCEPT (pod-terminy)
    # (długie wyjaśnienie)". Recruiter directive — bold ONLY technologies:
    # platforms ("iOS/Android") and technical acronyms/standards ("RWD",
    # "WCAG"). Design methodologies / concepts ("User-Centered Design",
    # "Material Design", "Zasady Gestalt", "visual design", "design systemów")
    # must NOT bold.
    must = [
        "User-Centered Design (projektowanie w oparciu o potrzeby użytkownika, "
        "badania, feedback i dane, a nie wyłącznie wymagania biznesowe)",
        "Zasady projektowania (heurystyki, best practices UX) (np. spójność "
        "ekranów, przewidywalność zachowań aplikacji)",
        "Zasady Gestalt (hierarchia, percepcja, grupowanie) (umiejętność "
        "układania elementów na ekranie)",
        "Zaawansowany visual design (typografia, kolor, kompozycja, gridy) "
        "(projektowanie estetycznych interfejsów)",
        "Material Design oraz Human Interface Guidelines (znajomość standardów "
        "projektowania aplikacji dla Androida i iOS)",
        "Projektowanie aplikacji mobilnych (iOS/Android) (doświadczenie w "
        "projektowaniu ekranów)",
        "Responsywne projektowanie (RWD, multi-device) (tworzenie rozwiązań "
        "działających poprawnie)",
        "Zasady WCAG 2.1/2.2 (projektowanie zgodne z wymaganiami dostępności)",
        "Tworzenie i rozwój design systemów (komponenty, tokeny) "
        "(projektowanie i utrzymywanie bibliotek)",
    ]
    prose = (
        "Stosuje User-Centered Design, zasady projektowania oraz zasady Gestalt. "
        "Zaawansowany visual design; zna Material Design i Human Interface "
        "Guidelines. Projektowanie aplikacji mobilnych (iOS/Android), "
        "responsywne projektowanie (RWD). Zna zasady WCAG 2.1/2.2 oraz "
        "tworzenie i rozwój design systemów (komponenty, tokeny)."
    )
    found = [f.lower() for f in _matches(prose, must)]
    # Technologies / platforms / standards bold.
    assert "ios/android" in found, found
    assert "rwd" in found, found
    assert "wcag" in found, found
    # Methodologies / concepts / requirement prose must NEVER bold.
    for concept in [
        "user-centered",
        "user-centered design",
        "zasady projektowania",
        "gestalt",
        "visual design",
        "material design",
        "human interface",
        "design systemów",
        "komponenty",
        "tokeny",
        "tworzenie",
        "projektowanie",
    ]:
        assert all(concept not in f for f in found), (
            f"{concept!r} must not bold; found={found}"
        )


def test_only_listed_technologies_bold():
    # The headline requirement: in a mixed must-have/nice-to-have list, only
    # the concrete technologies bold; the design concepts alongside them do not.
    keywords = [
        "Figma (zaawansowana znajomość)",
        "React",
        "Doświadczenie w Python",
        "Docker oraz Kubernetes",
        "Znajomość SQL i PostgreSQL",
        "User-Centered Design",  # concept — must NOT bold
        "Zasady Gestalt",  # concept — must NOT bold
    ]
    prose = (
        "Projektant pracujący w Figma, buduje aplikacje w React i Python. "
        "Konteneryzacja: Docker, Kubernetes. Bazy: SQL, PostgreSQL. "
        "Stosuje User-Centered Design oraz zasady Gestalt."
    )
    found = [f.lower() for f in _matches(prose, keywords)]
    for tech in [
        "figma",
        "react",
        "python",
        "docker",
        "kubernetes",
        "sql",
        "postgresql",
    ]:
        assert tech in found, f"{tech!r} should bold; found={found}"
    joined = " ".join(found)
    assert "user-centered" not in joined
    assert "gestalt" not in joined


# ── Claude response normalization ──────────────────────────────────────────


def test_normalize_fills_missing_keys():
    data = _normalize_candidate_data(
        {
            "name": "Jan Kowalski",
            "experience": [{"company": "ACME"}],
            "education": [{"institution": "PW"}],
            "skills": [{"label": "DevOps:", "content": "Docker"}, "luźny string"],
        },
        fallback_name=None,
    )
    job = data["experience"][0]
    assert job["dates"] == ""
    assert job["responsibilities"] == []
    assert job["technologies"] == []
    edu = data["education"][0]
    assert edu["degree"] == ""
    assert data["skills"][1] == {"label": "", "content": "luźny string"}
    assert data["why_points"] == []
    assert data["languages"] == []


def test_normalize_uses_fallback_name():
    data = _normalize_candidate_data({}, fallback_name="Ada Nowak")
    assert data["name"] == "Ada Nowak"


def test_normalize_rejects_non_dict():
    with pytest.raises(StandaloneGenerationError) as exc:
        _normalize_candidate_data(["lista", "zamiast", "obiektu"], fallback_name=None)
    assert exc.value.code == "ai_failed"


def test_normalize_folds_typographic_dashes_to_hyphens():
    data = _normalize_candidate_data(
        {
            "name": "Jan Kowalski",
            "why_points": ["5 lat doświadczenia — w tym 3 w fintechu"],
            "languages": ["Polski – ojczysty", "Angielski – biegły"],
            "certifications": ["AWS SAA — Amazon (2022)"],
            "experience": [
                {
                    "company": "ACME",
                    "dates": "03.2020 – obecnie",
                    "responsibilities": ["Wdrożenie CI/CD — GitLab"],
                }
            ],
            "skills": [{"label": "DevOps:", "content": "Docker – zaawansowany"}],
        },
        fallback_name=None,
    )
    assert data["why_points"] == ["5 lat doświadczenia - w tym 3 w fintechu"]
    assert data["languages"] == ["Polski - ojczysty", "Angielski - biegły"]
    assert data["certifications"] == ["AWS SAA - Amazon (2022)"]
    job = data["experience"][0]
    assert job["dates"] == "03.2020 - obecnie"
    assert job["responsibilities"] == ["Wdrożenie CI/CD - GitLab"]
    assert data["skills"][0]["content"] == "Docker - zaawansowany"
    # No typographic dash survives anywhere in the output.
    blob = repr(data)
    for dash in ("–", "—", "‒", "―", "−"):
        assert dash not in blob


# ── Anti-fabrication guard ─────────────────────────────────────────────────

_SOURCE = """
Senior DevOps Engineer z doświadczeniem w Kubernetes, Docker oraz Terraform.
Certyfikat CKA (Certified Kubernetes Administrator) zdobyty w 2023.
Notatka rekrutera: kandydat potwierdził znajomość RabbitMQ na screeningu.
"""


def test_guard_passes_for_sourced_technologies():
    data = {
        "experience": [
            {
                "position": "DevOps",
                "technologies": ["Kubernetes", "Docker", "RabbitMQ"],
            }
        ],
        "certifications": ["CKA – Certified Kubernetes Administrator (2023)"],
    }
    assert _fabrication_warnings(data, _SOURCE, "pl") == []


def test_guard_flags_fabricated_technology():
    data = {
        "experience": [{"position": "DevOps", "technologies": ["Snowflake"]}],
        "certifications": [],
    }
    warnings = _fabrication_warnings(data, _SOURCE, "pl")
    assert len(warnings) == 1
    assert "Snowflake" in warnings[0]
    assert warnings[0].startswith("WERYFIKUJ")


def test_guard_flags_fabricated_certification():
    data = {
        "experience": [],
        "certifications": ["AWS Solutions Architect Professional"],
    }
    warnings = _fabrication_warnings(data, _SOURCE, "pl")
    assert len(warnings) == 1
    assert "AWS" in warnings[0]


def test_guard_handles_diacritics():
    data = {
        "experience": [
            {"position": "Dev", "technologies": ["zarządzanie łańcuchem CI"]}
        ],
        "certifications": [],
    }
    source = "Zarzadzanie lancuchem CI w GitLabie"
    assert _fabrication_warnings(data, source, "pl") == []


# ── Filename sanitization ──────────────────────────────────────────────────


def test_sanitize_preserves_polish_letters():
    # The on-disk filename keeps the candidate's real spelling — Polish letters
    # (ł, ą, ż, ó…) survive; only whitespace is normalized to underscores.
    assert _sanitize_for_filename("Łukasz Kamecki") == "Łukasz_Kamecki"
    assert _sanitize_for_filename("Michał Bogdan") == "Michał_Bogdan"
    assert _sanitize_for_filename("Kamil Szukajło") == "Kamil_Szukajło"


def test_sanitize_replaces_unsafe_characters():
    assert _sanitize_for_filename("Jan/Kowalski") == "Jan_Kowalski"
    assert _sanitize_for_filename("   ") == "kandydat"


def test_ascii_filename_fallback_transliterates_polish():
    # The Content-Disposition ASCII fallback still folds Polish → ASCII so the
    # legacy ``filename="…"`` parameter stays latin-1 encodable.
    assert (
        ascii_filename_fallback("CV_B2B_Łukasz_Kamecki.docx")
        == "CV_B2B_Lukasz_Kamecki.docx"
    )
    assert (
        ascii_filename_fallback("CV_B2B_Kamil_Szukajło.docx")
        == "CV_B2B_Kamil_Szukajlo.docx"
    )


# ── Upload validation ──────────────────────────────────────────────────────


def test_doc_upload_rejected_with_clear_message():
    with pytest.raises(StandaloneGenerationError) as exc:
        _validate_upload(
            b"\xd0\xcf\x11\xe0 fake doc",
            "cv_stare.doc",
            allowed_ext={".pdf", ".docx"},
            label="CV",
        )
    assert exc.value.code == "invalid_input"
    assert ".docx lub PDF" in exc.value.message


def test_pdf_upload_accepted():
    _validate_upload(
        b"%PDF-1.4 fake", "cv.pdf", allowed_ext={".pdf", ".docx"}, label="CV"
    )


# ── Per-role technology cap ────────────────────────────────────────────────


def test_cap_technologies_prioritizes_champion():
    from app.services.cv_generator_b2b.standalone_service import (
        _cap_role_technologies,
    )

    techs = [f"Tech{i}" for i in range(1, 12)] + ["Splunk", "QRadar", "Tech12"]
    data = {"experience": [{"position": "x", "technologies": list(techs)}]}
    _cap_role_technologies(data, ["Splunk", "QRadar"])
    kept = data["experience"][0]["technologies"]
    assert len(kept) == 12
    assert "Splunk" in kept and "QRadar" in kept
    # Original ordering preserved within the kept subset.
    assert kept.index("Tech1") < kept.index("Splunk")


def test_cap_technologies_noop_under_limit():
    from app.services.cv_generator_b2b.standalone_service import (
        _cap_role_technologies,
    )

    data = {"experience": [{"position": "x", "technologies": ["A", "B"]}]}
    _cap_role_technologies(data, ["A"])
    assert data["experience"][0]["technologies"] == ["A", "B"]


# ── Overlapping employment dates ───────────────────────────────────────────


def test_parse_date_range_variants():
    from app.services.cv_generator_b2b.standalone_service import _parse_date_range

    assert _parse_date_range("03.2020 – 11.2023") == (2020 * 12 + 2, 2023 * 12 + 10)
    assert _parse_date_range("2019") == (2019 * 12, 2019 * 12 + 11)
    ongoing = _parse_date_range("02.2024 – obecnie")
    assert ongoing is not None and ongoing[1] == 9999 * 12
    assert _parse_date_range("brak dat") is None
    assert _parse_date_range("") is None


def test_overlap_warning_flags_parallel_roles():
    from app.services.cv_generator_b2b.standalone_service import (
        _date_overlap_warnings,
    )

    data = {
        "experience": [
            {"company": "Contina", "dates": "02.2024 – obecnie"},
            {"company": "COI", "dates": "11.2023 – 02.2025"},
        ]
    }
    warnings = _date_overlap_warnings(data, "pl")
    assert len(warnings) == 1
    assert "Contina" in warnings[0] and "COI" in warnings[0]
    assert warnings[0].startswith("WERYFIKUJ")


def test_overlap_ignores_handover_month():
    from app.services.cv_generator_b2b.standalone_service import (
        _date_overlap_warnings,
    )

    data = {
        "experience": [
            {"company": "A", "dates": "01.2020 – 03.2022"},
            {"company": "B", "dates": "03.2022 – obecnie"},
        ]
    }
    assert _date_overlap_warnings(data, "pl") == []


def test_overlap_caps_warning_count():
    from app.services.cv_generator_b2b.standalone_service import (
        _date_overlap_warnings,
    )

    data = {
        "experience": [
            {"company": f"Firma{i}", "dates": "01.2020 – obecnie"} for i in range(5)
        ]
    }
    warnings = _date_overlap_warnings(data, "pl")
    assert len(warnings) == 4  # 3 pary + "… i N kolejnych"
    assert "kolejnych" in warnings[-1]


# ── Exact years of experience ──────────────────────────────────────────────


def test_total_experience_years_counts_full_tenure():
    from app.services.cv_generator_b2b.standalone_service import (
        _total_experience_years,
    )

    # 09.2018 – 09.2023 = 61 months ≈ 5.08 → 5 (the recruiter's "5 years").
    assert _total_experience_years([{"dates": "09.2018 – 09.2023"}]) == 5


def test_total_experience_years_merges_overlapping_roles():
    from app.services.cv_generator_b2b.standalone_service import (
        _total_experience_years,
    )

    # Parallel B2B contracts must be counted once, not summed to 10.
    years = _total_experience_years(
        [
            {"dates": "01.2019 – 12.2023"},
            {"dates": "01.2019 – 12.2023"},
        ]
    )
    assert years == 5


def test_total_experience_years_none_without_dates():
    from app.services.cv_generator_b2b.standalone_service import (
        _total_experience_years,
    )

    assert _total_experience_years([{"company": "X"}]) is None


def test_fix_experience_years_corrects_undercount():
    from app.services.cv_generator_b2b.standalone_service import (
        _fix_experience_years,
    )

    data = {
        "experience": [{"dates": "09.2018 – 09.2023"}],
        "why_points": [
            "Ponad 4 lata doświadczenia jako UX/UI Designer, w tym 3 lata w startupie",
            "Specjalizacja w technologiach: Figma, Sketch",
        ],
    }
    _fix_experience_years(data, "pl")
    # Headline total corrected to the exact figure; "w tym 3 lata" sub-figure
    # and the second point are left untouched.
    assert data["why_points"][0].startswith("5 lat doświadczenia jako UX/UI Designer")
    assert "w tym 3 lata w startupie" in data["why_points"][0]
    assert data["why_points"][1] == "Specjalizacja w technologiach: Figma, Sketch"


def test_fix_experience_years_polish_plural_unit():
    from app.services.cv_generator_b2b.standalone_service import (
        _fix_experience_years,
    )

    data = {
        "experience": [{"dates": "01.2022 – 12.2023"}],  # 24 months → 2 → "2 lata"
        "why_points": ["Ponad 1 rok doświadczenia jako Developer"],
    }
    _fix_experience_years(data, "pl")
    assert data["why_points"][0] == "2 lata doświadczenia jako Developer"


# ── Saved-CV re-render (panel list download/preview) ───────────────────────


def _sample_payload(blind: bool = False) -> dict:
    return {
        "name": "Jan Kowalski",
        "first_name": "Jan",
        "position": "Java Developer",
        "language": "pl",
        "blind_cv": blind,
        "why_points": ["8 lat doświadczenia jako Java Developer"],
        "skills": [{"label": "Backend:", "content": "Java, Spring Boot"}],
        "languages": ["Polski – ojczysty", "Angielski – biegły"],
        "experience": [
            {
                "dates": "01.2020 – obecnie",
                "company": "Acme",
                "industry": "IT",
                "position": "Java Developer",
                "responsibilities": ["Rozwój usług w Java"],
                "technologies": ["Java", "Spring Boot"],
            }
        ],
    }


def test_rerender_from_payload_produces_docx():
    # Saved-CV download/preview re-renders deterministically from the payload,
    # with no Claude call. DOCX is a zip → starts with the PK magic bytes.
    data = rerender_docx_from_payload(_sample_payload())
    assert data[:2] == b"PK"
    assert len(data) > 1000


def test_rerender_does_not_mutate_saved_payload():
    # render mutates candidate_data in place for blind anonymization; the helper
    # deep-copies so the STORED payload stays reusable for the next download.
    payload = _sample_payload(blind=True)
    rerender_docx_from_payload(payload)
    assert payload["name"] == "Jan Kowalski"
    assert payload["experience"][0]["company"] == "Acme"


def test_rodo_clause_is_separated_by_closing_divider():
    # The RODO consent clause must read as a distinct footer block, not as notes
    # tacked onto the last role. A red divider (the B2B HR, fillcolor #e14f4f)
    # closes the document body and the clause follows it — so in the XML the
    # clause text comes AFTER the last divider, which itself comes AFTER the
    # last experience content. No bottom-anchoring frame is used (it spilled the
    # clause onto a blank second page on content-heavy CVs).
    import io
    import zipfile

    data = rerender_docx_from_payload(_sample_payload())
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        body = z.read("word/document.xml").decode("utf-8")

    last_experience_text = body.rfind("Spring Boot")  # last role's last technology
    last_divider = body.rfind('fillcolor="#e14f4f"')
    rodo = body.find("Wyrażam zgodę na przetwarzanie")

    assert last_experience_text != -1
    assert rodo != -1, "RODO clause missing"
    assert last_divider > last_experience_text, "closing divider not after last role"
    assert rodo > last_divider, "RODO clause not after the closing divider"
    assert "<w:framePr" not in body, "frame anchoring reintroduced (causes blank page)"
