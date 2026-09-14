"""M05-B02: etykieta pustego pola wzoru Championa nie jest wymaganiem NICE."""

from __future__ import annotations

import io
import sys
from pathlib import Path

from app.services.cv_generator_b2b.champion_builder import (
    _is_prose_entry,
    parse_champion_from_docx_bytes,
)


def _template_bytes(*, nuances: str = "") -> bytes:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import generate_champion_template  # noqa: PLC0415

    doc = generate_champion_template.build()
    for table in doc.tables:
        for row in table.rows:
            cell = row.cells[0]
            if cell.text.startswith("MUST-HAVE"):
                cell.paragraphs[-1].text = "Python, PostgreSQL, Docker"
            elif cell.text.startswith("NICE-TO-HAVE"):
                cell.paragraphs[-1].text = "Kubernetes"
            elif cell.text.startswith("Niuanse wersji") and nuances:
                cell.paragraphs[-1].text = nuances
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_empty_nuance_field_label_is_not_a_nice_to_have_requirement():
    champ = parse_champion_from_docx_bytes(_template_bytes(), "champion.docx")
    assert champ.must_have == ["Python", "PostgreSQL", "Docker"]
    assert champ.nice_to_have == ["Kubernetes"]


def test_filled_nuance_field_is_context_not_requirements():
    champ = parse_champion_from_docx_bytes(
        _template_bytes(nuances="Python 3.11+, bez Pythona 2"), "champion.docx"
    )
    assert champ.nice_to_have == ["Kubernetes"]
    assert "Python 3.11+" in champ.additional_context


def test_upload_tiles_come_only_from_real_requirements():
    from app.services.cv_generator_b2b.standalone_service import (
        UploadGenerationInput,
    )
    from app.services.cv_generator_b2b.upload_requirements import (
        upload_requirements,
    )

    payload = UploadGenerationInput(
        cv_bytes=b"cv",
        cv_filename="cv.pdf",
        champion_bytes=_template_bytes(),
        champion_filename="champion.docx",
    )
    names = [(r["name"], r["kind"]) for r in upload_requirements(payload)]
    assert names == [
        ("Python", "must"),
        ("PostgreSQL", "must"),
        ("Docker", "must"),
        ("Kubernetes", "nice"),
    ]


def test_colon_terminated_label_is_never_a_skill_chip():
    assert _is_prose_entry("Mile widziane:")
    assert not _is_prose_entry("Java (Spring, Hibernate)")
