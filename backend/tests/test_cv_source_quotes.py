import json

import pytest

from app.services.cv_generator_b2b.source_quotes import (
    source_quote_span,
    same_source_value,
)
from app.services.cv_generator_b2b import source_facts as facts
from tests.test_cv_complete_source_facts import response, SOURCE


def test_pdf_line_wrap_and_spacing_keep_original_evidence_offsets():
    source = "Heading\nModeling   business\nprocesses\twith UML.\nNext role"
    span = source_quote_span(source, "Modeling business processes with UML.")
    assert source[slice(*span)] == "Modeling   business\nprocesses\twith UML."
    assert same_source_value("business processes", source[slice(*span)])


@pytest.mark.parametrize(
    "quote", ["no Kubernetes", "3 years", "01.2020", "AWS", "", "A B"]
)
def test_whitespace_matching_does_not_invent_or_change_content(quote):
    assert source_quote_span("Kubernetes; 3 people; 2020; aws; AB", quote) is None


def test_source_ledger_accepts_pdf_spacing_but_still_rejects_an_invented_tool():
    payload = response()
    pdf_source = SOURCE.replace("Firma B", "Firma  B").replace(
        "zapytania SQL", "zapytania\nSQL"
    )
    result = facts.validate_extraction(
        json.dumps(payload), {"cv": pdf_source, "screening_notes": ""}
    )
    evidence = result["evidence"][2]
    assert "zapytania\nSQL" in pdf_source[evidence["start"] : evidence["end"]]
    payload["document"]["experience"][0]["technologies"].append("Kubernetes")
    with pytest.raises(facts.SourceFactsError, match="Complete source facts"):
        facts.validate_extraction(
            json.dumps(payload), {"cv": pdf_source, "screening_notes": ""}
        )
