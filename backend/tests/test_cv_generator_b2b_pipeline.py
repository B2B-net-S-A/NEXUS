"""Unit tests for the CV Generator B2B pipeline helpers.

Covers the 2026-06-10 audit fixes:
  * champion keyword bolding — phrase-aware, word-boundary matching
    (multi-word MUST-HAVEs match, "Git" no longer bolds "digital"),
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


def test_sanitize_transliterates_polish_l():
    assert _sanitize_for_filename("Łukasz Kamecki") == "Lukasz_Kamecki"


def test_sanitize_strips_diacritics():
    assert _sanitize_for_filename("Michał Bogdan") == "Michal_Bogdan"


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
