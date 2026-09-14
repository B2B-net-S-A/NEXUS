"""The Champion section of the paid CV prompt is capped at 14 000 characters.

The 14 000-character limit was removed from `parse_champion_from_docx_bytes`
(it rejected long but readable Word forms), and nothing else bounded what the
generator copies into the prompt: an uploaded document's sections, or a
stored profile's project description and screening answers, went to the model
whole — paid per token, on every generation, in both pipelines. The section
is now cut at a line or word boundary and the recruiter gets a warning. The
Word v4 table read and the stored profile themselves stay uncapped.
"""

import time
from datetime import date

from app.services.champion_intake import MAX_TEXT
from app.services.cv_generator_b2b import standalone_service as svc
from app.services.cv_generator_b2b.champion_builder import (
    CHAMPION_PROMPT_CAP_WARNING,
    ChampionProfileForPrompt,
    build_champion_section,
    build_screening_notes_section,
    cap_champion_prompt_section,
)
from app.services.cv_generator_b2b.legacy_v7 import pipeline as legacy_pipeline
from app.services.cv_generator_b2b.legacy_v7.champion import (
    build_champion_section as build_legacy_champion_section,
)
from tests.test_cv_generator_content_mode import (
    captured_prompt,  # noqa: F401 — pytest fixture
)
from tests.test_cv_generator_legacy_v7 import (
    _CV_TEXT as LEGACY_CV_TEXT,
    _champion,
    _run as run_legacy,
    defaults,  # noqa: F401 — pytest fixture
)

NOTES = "Kandydat potwierdził znajomość Pythona."


def huge_champion() -> ChampionProfileForPrompt:
    """~60 000 characters: one long project description after the requirements."""
    return ChampionProfileForPrompt(
        must_have=["Kubernetes"],
        nice_to_have=["Terraform"],
        project_context="Rozwijamy platformę płatności dla banku. " * 1500,
        responsibilities="Utrzymanie klastrów produkcyjnych",
    )


def champion_block(user_content: str) -> str:
    start = user_content.index("<champion_profile>\n") + len("<champion_profile>\n")
    return user_content[start : user_content.index("\n</champion_profile>")]


def test_warning_is_polish_and_names_the_limit() -> None:
    assert MAX_TEXT == 14_000
    assert "14 000 znaków" in CHAMPION_PROMPT_CAP_WARNING
    assert "Profil Championa" in CHAMPION_PROMPT_CAP_WARNING


def test_a_section_within_the_cap_is_returned_untouched() -> None:
    section = build_champion_section(_champion(), "pl")

    capped, warnings = cap_champion_prompt_section(section)

    assert capped is section
    assert warnings == []


def test_the_cut_prefers_a_line_boundary() -> None:
    lines = [f"Pytanie {i}: jak projektujesz odporne API?" for i in range(600)]
    section = "PROFIL CHAMPIONA:\n" + "\n".join(lines)

    capped, warnings = cap_champion_prompt_section(section)

    assert len(capped) <= MAX_TEXT
    assert section.startswith(capped)
    assert section[len(capped)] == "\n", "a line was cut in half"
    assert warnings == [CHAMPION_PROMPT_CAP_WARNING]


def test_one_long_paragraph_is_cut_between_words() -> None:
    section = "PROFIL CHAMPIONA:\nKontekst projektu: " + "słowo " * 12_000

    capped, _ = cap_champion_prompt_section(section)

    assert len(capped) <= MAX_TEXT
    assert capped.endswith("słowo")
    assert section[len(capped)].isspace()


# ── Legacy v7 (production default) ───────────────────────────────────────────


def test_legacy_prompt_caps_a_huge_champion_and_warns(defaults) -> None:  # noqa: F811
    champion = huge_champion()
    assert len(build_legacy_champion_section(champion, "pl")) > 50_000

    result = run_legacy("tailored", champion=champion)

    block = champion_block(defaults["calls"][0]["user"])
    assert len(block) <= MAX_TEXT
    assert block.startswith("PROFIL CHAMPIONA:\n\nMUST-HAVE: Kubernetes")
    full = build_legacy_champion_section(champion, "pl").strip()
    assert full.startswith(block) and full[len(block)].isspace()
    assert CHAMPION_PROMPT_CAP_WARNING in result.warnings


def test_legacy_prompt_is_byte_identical_for_a_normal_champion(defaults) -> None:  # noqa: F811
    result = run_legacy("tailored", champion=_champion())

    section = build_legacy_champion_section(_champion(), "pl").strip()
    notes = build_screening_notes_section(NOTES, "pl").strip()
    assert defaults["calls"][0]["user"] == (
        f"<cv>\n{LEGACY_CV_TEXT.strip()}\n</cv>\n\n"
        f"<screening_notes>\n{notes}\n</screening_notes>\n\n"
        f"<champion_profile>\n{section}\n</champion_profile>\n\n"
        # M05-B01: dzisiejsza data dla liczenia „obecnie" (poza cache'owanym
        # promptem systemowym).
        + legacy_pipeline.build_generation_date_block("pl", date.today())
    )
    assert CHAMPION_PROMPT_CAP_WARNING not in result.warnings


# ── Rebuilt pipeline (CV_GENERATION_PIPELINE=v10) ────────────────────────────


def _run_v10(champion: ChampionProfileForPrompt):
    return svc._run_generation_pipeline(
        cv_bytes=b"x",
        cv_filename="cv.pdf",
        champion_dto=champion,
        screening_notes_text=NOTES,
        language="pl",
        blind_cv=False,
        request_id="champion-cap",
        fallback_name="Jan Kowalski",
        started_at=time.time(),
        job_id=1,
        job_title="Platform Engineer",
        content_mode="tailored",
    )


def test_v10_prompt_caps_a_huge_champion_and_warns(captured_prompt) -> None:  # noqa: F811
    champion = huge_champion()

    result = _run_v10(champion)

    block = champion_block(captured_prompt["user"])
    assert len(block) <= MAX_TEXT
    assert block.startswith("PROFIL CHAMPIONA:\n\nMUST-HAVE: Kubernetes")
    full = build_champion_section(champion, "pl").strip()
    assert full.startswith(block) and full[len(block)].isspace()
    assert CHAMPION_PROMPT_CAP_WARNING in result.warnings


def test_v10_champion_block_is_byte_identical_for_a_normal_champion(
    captured_prompt,  # noqa: F811
) -> None:
    result = _run_v10(_champion())

    expected = build_champion_section(_champion(), "pl").strip()
    assert champion_block(captured_prompt["user"]) == expected
    assert CHAMPION_PROMPT_CAP_WARNING not in result.warnings
