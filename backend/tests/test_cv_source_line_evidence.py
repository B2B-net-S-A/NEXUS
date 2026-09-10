import json

import pytest

from app.services.cv_generator_b2b import factual_verification as gate
from app.services.cv_generator_b2b import source_facts as facts
from app.services.cv_generator_b2b.source_lines import (
    SourceReference,
    numbered_sources,
    reference_span,
)
from app.services.cv_generator_b2b.source_quotes import (
    same_source_value,
    source_column_dates,
    source_role_text,
)
from tests.test_cv_complete_source_facts import SOURCE, response


def line_response():
    result = response()
    for item, line in zip(result["evidence"], (1, 1, 2, 3, 4), strict=True):
        item.pop("quote")
        item.update(start_line=line, end_line=line)
    return result


@pytest.mark.parametrize(
    "value,quote,accepted",
    [
        ("2006–2008", "2006 - 2008 University", True),
        ("2002 - 2006", "2002– 2006 University", True),
        ("01.2020–12.2021", "Role: 01.2020 - 12.2021", True),
        ("2020–2021", "01.2020-12.2021 Role", False),
        ("2020–2021", "2020-2021.12 Role", False),
        ("2020–2021", "12020-2021 Role", False),
        ("01.2020–12.2021", "2020-2021 Role", False),
    ],
)
def test_inline_date_separators_preserve_both_endpoints_and_precision(
    value, quote, accepted
):
    assert source_column_dates(value, quote) is accepted


def test_original_offsets_survive_pdf_page_breaks_crlf_and_blank_lines():
    original = "Name\r\n\r\n01.2020- Company\r\n12.2021 Tasks\fNext page\n"
    numbered = numbered_sources({"cv": original})["cv"]
    assert "".join(row["text"] for row in numbered) == original
    reference = SourceReference(start_line=3, end_line=4)
    span = reference_span(original, reference)
    assert original[slice(*span)] == "01.2020- Company\r\n12.2021 Tasks\f"


@pytest.mark.parametrize("start,end", [(1, 8), (4, 2), (None, 2), (1, None), (2, 2)])
def test_missing_reversed_out_of_bounds_and_empty_ranges_are_rejected(start, end):
    assert (
        reference_span("Name\n\nRole", SourceReference(start_line=start, end_line=end))
        is None
    )


def test_retyped_quote_cannot_override_a_line_reference():
    assert (
        reference_span("Name", SourceReference(start_line=1, end_line=1, quote="Name"))
        is None
    )


def test_numbered_evidence_covers_all_facts_and_still_rejects_invented_tool():
    payload = line_response()
    sources = {"cv": SOURCE, "screening_notes": ""}
    result = facts.validate_extraction(json.dumps(payload), sources)
    assert result["document"] == payload["document"]
    assert all(result["field_evidence"].values())
    payload["document"]["experience"][0]["technologies"].append("Kubernetes")
    with pytest.raises(facts.SourceFactsError) as error:
        facts.validate_extraction(json.dumps(payload), sources)
    assert error.value.reason == "unbound_fact"
    assert error.value.paths == ["/experience/0/technologies/1"]


def test_response_wrapper_paths_resolve_to_the_same_document_fields():
    payload = line_response()
    for citation in payload["evidence"]:
        citation["path"] = "/document" + citation["path"]
    result = facts.validate_extraction(
        json.dumps(payload), {"cv": SOURCE, "screening_notes": ""}
    )
    assert result["document"] == payload["document"]
    assert all(result["field_evidence"].values())
    assert [item["path"] for item in result["evidence"]] == [
        item["path"] for item in line_response()["evidence"]
    ]


def test_surplus_empty_field_and_structural_label_citations_make_no_claims():
    payload = line_response()
    payload["document"]["skills"] = [{"label": "Technical", "content": ""}]
    for path in (
        "/position",
        "/certifications",
        "/experience/0/industry",
        "/document/skills/0/label",
        "/skills/0/content",
    ):
        # There is no text to cite for an empty field, including empty notes.
        payload["evidence"].append(
            {"path": path, "source": "screening_notes", "start_line": 1, "end_line": 1}
        )
    result = facts.validate_extraction(
        json.dumps(payload), {"cv": SOURCE, "screening_notes": ""}
    )
    assert result["document"] == payload["document"]
    assert all(result["field_evidence"].values())
    assert len(result["evidence"]) == len(line_response()["evidence"])
    # Surplus citations never support a real populated claim.
    payload["document"]["skills"][0]["content"] = "Invented skill"
    with pytest.raises(facts.SourceFactsError):
        facts.validate_extraction(
            json.dumps(payload), {"cv": SOURCE, "screening_notes": ""}
        )


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/",
        "/document",
        "/documentary/name",
        "/experience/99",
        "/skills/0",
        "/unknown",
    ],
)
def test_unknown_or_root_citations_still_fail_with_repair_path(path):
    payload = line_response()
    payload["evidence"].append(
        {"path": path, "source": "cv", "start_line": 1, "end_line": 1}
    )
    with pytest.raises(facts.SourceFactsError) as error:
        facts.validate_extraction(
            json.dumps(payload), {"cv": SOURCE, "screening_notes": ""}
        )
    assert error.value.reason == "invalid_evidence_path"
    assert error.value.paths == [path]


def test_invalid_pointer_gets_one_repair_without_losing_any_source_history(monkeypatch):
    bad = line_response()
    bad["evidence"][2]["path"] = "/experience/99"
    calls = []

    def model(content, *args, **kwargs):
        calls.append(json.loads(content))
        return json.dumps(bad if len(calls) == 1 else line_response())

    monkeypatch.setattr(facts, "analyze_with_ai", model)
    result = facts.extract_source_facts(
        cv_text=SOURCE, screening_notes="", request_id="pointer-repair"
    )
    assert result["document"] == line_response()["document"]
    assert result["extraction_attempts"] == 2
    assert calls[1]["validation"] == {
        "reason": "invalid_evidence_path",
        "paths": ["/experience/99"],
    }


@pytest.mark.parametrize(
    "path,suffix",
    [
        ("/experience/12/responsibilities/3", "_responsibilities"),
        ("/education/0/dates", "_dates"),
        ("/skills/0/content", "_content"),
        ("/name", "_name"),
        ("/certifications/1", "_certifications"),
        ("/experience/0/private candidate value", ""),
        ("/name/private", ""),
    ],
)
def test_failure_metadata_contains_only_fixed_field_categories(path, suffix):
    error = facts.SourceFactsError("unbound_fact", [path])
    assert error.diagnostic_code == "source_unbound_fact" + suffix
    assert len(error.diagnostic_code) <= 64


def test_pdf_date_column_and_split_words_do_not_require_retyped_role_quotes():
    role = "16.01.2015- Firma B. Analityk. Admin-\n31.03.2015 istration of Active Direc-\ntory only in training.\n"
    original = SOURCE.replace(SOURCE.splitlines(keepends=True)[1], role)
    payload = line_response()
    payload["document"]["experience"][0].update(
        dates="16.01.2015-31.03.2015",
        responsibilities=["Administration of Active Directory only in training."],
        technologies=["Active Directory"],
    )
    payload["evidence"][2]["end_line"] = 4
    for item in payload["evidence"][3:]:
        item["start_line"] += 2
        item["end_line"] += 2
    result = facts.validate_extraction(
        json.dumps(payload), {"cv": original, "screening_notes": ""}
    )
    span = result["evidence"][2]
    assert original[span["start"] : span["end"]] == role
    payload["document"]["experience"][0]["responsibilities"] = [
        "Administration of production Active Directory."
    ]
    with pytest.raises(facts.SourceFactsError):
        facts.validate_extraction(
            json.dumps(payload), {"cv": original, "screening_notes": ""}
        )


def test_layout_matching_does_not_concatenate_dates_or_remove_inline_hyphens():
    assert not same_source_value("20202021", "2020-\n2021")
    assert not same_source_value("readonly", "read-only")
    assert not same_source_value("AWS", "aws")
    assert (
        source_role_text("01.2020-12.2021 Role\n2022 was a training course")
        == "01.2020-12.2021 Role\n2022 was a training course"
    )


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_one_repair_uses_same_gate_preserves_history_and_shares_deadline(
    monkeypatch, repair_succeeds
):
    bad = line_response()
    bad["document"]["experience"][0]["technologies"] = ["Invented"]
    calls = []
    times = iter([100, 110, 160])
    monkeypatch.setattr(facts.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(facts, "total_timeout_seconds", lambda: 300)

    def model(content, request_id, **kwargs):
        calls.append((json.loads(content), kwargs))
        return json.dumps(
            line_response() if len(calls) == 2 and repair_succeeds else bad
        )

    monkeypatch.setattr(facts, "analyze_with_ai", model)
    if repair_succeeds:
        result = facts.extract_source_facts(
            cv_text=SOURCE, screening_notes="", request_id="repair"
        )
        assert result["document"] == response()["document"]
        assert result["extraction_attempts"] == 2
    else:
        with pytest.raises(facts.SourceFactsError):
            facts.extract_source_facts(
                cv_text=SOURCE, screening_notes="", request_id="repair"
            )
    assert len(calls) == 2
    assert [kwargs["total_timeout"] for _, kwargs in calls] == [290, 240]
    assert calls[1][0]["validation"]["paths"] == ["/experience/0/technologies/0"]
    assert (
        calls[1][0]["previous_extraction"]["document"]["experience"]
        == bad["document"]["experience"]
    )


def test_final_review_uses_original_line_context_and_rejects_semantic_invention(
    monkeypatch,
):
    document = {"name": "Jan Testowy", "why_points": ["Przygotowywał zapytania SQL."]}
    calls = []

    def model(content, *args, **kwargs):
        incoming = json.loads(content)
        calls.append(incoming)
        return json.dumps(
            {
                "claims": [
                    {
                        "path": path,
                        "status": "supported",
                        "evidence": [{"source": "cv", "start_line": 1, "end_line": 2}],
                    }
                    for path in incoming["claims"]
                ]
            }
        )

    monkeypatch.setattr(gate, "analyze_with_ai", model)
    result = gate.verify_final_cv(
        document, cv_text=SOURCE, screening_notes="", identity="", request_id="review"
    )
    assert result["status"] == "verified"
    assert calls[0]["sources"] == numbered_sources(
        {"cv": SOURCE, "screening_notes": "", "identity": ""}
    )
    assert result["claims"][0]["evidence"][0]["quote"] == "".join(
        SOURCE.splitlines(keepends=True)[:2]
    )

    def reject(content, *args, **kwargs):
        output = json.loads(model(content))
        output["claims"][-1]["status"] = "unsupported"
        return json.dumps(output)

    monkeypatch.setattr(gate, "analyze_with_ai", reject)
    with pytest.raises(gate.FactualVerificationError, match="did not pass"):
        gate.verify_final_cv(
            document,
            cv_text=SOURCE,
            screening_notes="",
            identity="",
            request_id="review",
        )


@pytest.mark.parametrize(
    "schema", [facts.EXTRACTION_RESPONSE_SCHEMA, gate.REVIEW_RESPONSE_SCHEMA]
)
def test_live_schema_requires_range_integers_without_generating_quotes(schema):
    evidence = schema["$defs"]["Evidence"]
    assert "quote" not in evidence["properties"]
    assert evidence["properties"]["start_line"] == {"type": "integer"}
    assert {"start_line", "end_line", "source"} <= set(evidence["required"])
