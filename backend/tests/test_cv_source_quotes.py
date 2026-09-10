import json

import pytest

from app.services.cv_generator_b2b.source_quotes import (
    source_quote_span,
    same_source_value,
    source_column_dates,
)
from app.services.cv_generator_b2b import source_facts as facts
from tests.test_cv_complete_source_facts import response, SOURCE


@pytest.fixture(autouse=True)
def _enforce_source_evidence(monkeypatch):
    # Asserts that invented facts are rejected; strict enforcement ships behind
    # a flag defaulting OFF (advisory) in production.
    monkeypatch.setenv("CV_SOURCE_EVIDENCE_ENFORCED", "true")


def test_gate_off_by_default_keeps_unverified_facts_instead_of_rejecting(monkeypatch):
    monkeypatch.delenv("CV_SOURCE_EVIDENCE_ENFORCED", raising=False)
    payload = response()
    # An invented tool with no source evidence would be an unbound_fact and
    # hard-reject when enforced. Advisory default: keep it, never block.
    payload["document"]["experience"][0]["technologies"].append("Kubernetes")
    result = facts.validate_extraction(
        json.dumps(payload), {"cv": SOURCE, "screening_notes": ""}
    )
    assert "Kubernetes" in result["document"]["experience"][0]["technologies"]


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


@pytest.mark.parametrize(
    "start,end,company_line",
    [
        ("02.02.2026", "now", " Firma B. Analityk."),
        ("01.12.2019", "31.10.2021", "\nFirma B. Analityk."),
        ("2010.04.15", "2010.11.30", " Firma B. Analityk."),
    ],
)
def test_source_dates_join_pdf_column_with_original_role_evidence(
    start, end, company_line
):
    payload = response()
    role = f"{start}-{company_line}\n{end} Przygotowywał zapytania SQL."
    source = SOURCE.replace(SOURCE.splitlines()[1], role)
    payload["document"]["experience"][0]["dates"] = f"{start} – {end}"
    payload["evidence"][2]["quote"] = role
    result = facts.validate_extraction(
        json.dumps(payload), {"cv": source, "screening_notes": ""}
    )
    evidence = result["evidence"][2]
    assert source[evidence["start"] : evidence["end"]] == role
    assert result["field_evidence"]["/experience/0/dates"] == [2]


@pytest.mark.parametrize(
    "value,quote",
    [
        ("01.2020 – 12.2021", "01.2020- Company\n11.2021 Duties"),
        ("01.01.2020 – 12.2021", "2020- Company\n12.2021 Duties"),
        ("2020 – 2021", "2020-01-01- Company\n2021-12-01 Duties"),
        (
            "01.2020 – 12.2021",
            "01.2020- Company\n01.2022- Next company\n12.2021 Duties",
        ),
        ("01.2020 – 12.2021", "01.2020- Company\nDescription\nMore duties\n12.2021"),
        ("01.2020 – now", "01.2020- Company\n12.2021 Duties"),
        ("01.2020 – present", "01.2020- Company\nnow Duties"),
        ("2020 – 2021", "Windows Server 2020-\n2021 Duties"),
        ("AWS Kubernetes", "AWS\nKubernetes"),
    ],
)
def test_column_dates_reject_changed_or_borrowed_endpoints(value, quote):
    assert not source_column_dates(value, quote)


def test_date_column_exception_does_not_apply_to_a_responsibility():
    payload = response()
    role = "01.2018- Firma B. Analityk.\n12.2020 Przygotowywał zapytania SQL."
    source = SOURCE.replace(SOURCE.splitlines()[1], role)
    payload["evidence"][2]["quote"] = role
    payload["document"]["experience"][0]["responsibilities"].append("01.2018 – 12.2020")
    with pytest.raises(facts.SourceFactsError):
        facts.validate_extraction(
            json.dumps(payload), {"cv": source, "screening_notes": ""}
        )


def test_joining_dates_inside_an_evidence_quote_is_still_rejected():
    payload = response()
    source = SOURCE.replace(
        SOURCE.splitlines()[1],
        "01.2018- Firma B. Analityk.\n12.2020 Przygotowywał zapytania SQL.",
    )
    with pytest.raises(facts.SourceFactsError):
        facts.validate_extraction(
            json.dumps(payload), {"cv": source, "screening_notes": ""}
        )
