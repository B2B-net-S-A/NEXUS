"""Diagnostic contracts; mocked judgements do not measure actual model quality."""

import json
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.cv_generator_b2b import factual_verification as gate
from scripts import eval_cv_factual_gate as runner


SOURCE = "Jan Testowy. Tworzył API w Pythonie. Nie pracował z Kubernetes."
DOCUMENT = {"name": "Jan Testowy", "why_points": ["Tworzył API w Pythonie."]}


def review(content):
    return {
        "claims": [
            {
                "path": path,
                "status": "supported",
                "evidence": [{"source": "cv", "quote": SOURCE}],
            }
            for path in json.loads(content)["claims"]
        ]
    }


def verify():
    return gate.verify_final_cv(
        DOCUMENT,
        cv_text=SOURCE,
        screening_notes="",
        identity="Jan Testowy",
        request_id="synthetic-test",
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "extra",
        "invented_quote",
        "empty_evidence",
        "identity_skill",
        "non_json",
        "private",
    ],
)
def test_incomplete_or_fabricated_review_cannot_approve(monkeypatch, mutation):
    def response(content, *args, **kwargs):
        data = review(content)
        if mutation == "missing":
            data["claims"].pop()
        elif mutation == "duplicate":
            data["claims"].append(data["claims"][0])
        elif mutation == "extra":
            data["claims"].append({**data["claims"][0], "path": "/unknown"})
        elif mutation == "invented_quote":
            data["claims"][1]["evidence"][0]["quote"] = "Invented source"
        elif mutation == "empty_evidence":
            data["claims"][1]["evidence"] = []
        elif mutation == "identity_skill":
            data["claims"][1]["evidence"] = [
                {"source": "identity", "quote": "Jan Testowy"}
            ]
        elif mutation == "private":
            data["claims"][1]["status"] = "private"
        elif mutation == "non_json":
            return "not JSON"
        return json.dumps(data)

    monkeypatch.setattr(gate, "analyze_with_ai", response)
    with pytest.raises(gate.FactualVerificationError):
        verify()


def test_report_binds_exact_evidence_offsets_and_document(monkeypatch):
    monkeypatch.setattr(
        gate, "analyze_with_ai", lambda content, *a, **k: json.dumps(review(content))
    )
    report = verify()
    assert report["status"] == "verified"
    assert {item["path"] for item in report["claims"]} == set(
        gate.claim_inventory(DOCUMENT)
    )
    for item in report["claims"]:
        evidence = item["evidence"][0]
        assert SOURCE[evidence["start"] : evidence["end"]] == evidence["quote"]


def test_corpus_and_scoring_do_not_count_protocol_errors_as_rejection():
    cases, fingerprint = runner.load_cases()
    assert len(cases) == 40
    assert (
        fingerprint
        == "8010bddfc453b78d2427823dd9e1c09efc6211a512c5766d8730d04404395a5d"
    )
    assert runner.score(True, "accepted")
    assert runner.score(False, "semantic_rejection")
    for failure in (
        "invalid_review",
        "invalid_evidence",
        "provider_error",
        "invalid_json",
        "invalid_schema",
        "invalid_coverage",
    ):
        assert not runner.score(False, failure)
        assert not runner.score(True, failure)


async def test_existing_receipt_never_restarts_provider_calls(monkeypatch, tmp_path):
    async def previous(key, report):
        return {"complete": False, "results": [{"outcome": "accepted"}]}

    def forbidden(*args, **kwargs):
        raise AssertionError("Duplicate run must not call provider or checkpoint")

    monkeypatch.setattr(runner, "claim_run", previous)
    monkeypatch.setattr(runner, "checkpoint", forbidden)
    monkeypatch.setattr(runner, "verify_final_cv", forbidden)
    path = tmp_path / "receipt.json"
    assert await runner.evaluate(path, "primary", 1, "123-1") == 2
    assert json.loads(path.read_text())["replayed_receipt"] is True


async def test_runtime_revision_mismatch_stops_before_receipt_and_provider(
    monkeypatch, tmp_path
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Wrong deployment must never start")

    monkeypatch.setenv("GIT_SHA", "a" * 40)
    monkeypatch.setattr(runner, "claim_run", forbidden)
    path = tmp_path / "report.json"
    assert await runner.evaluate(path, "primary", 1, "123-1", "b" * 40) == 2
    assert json.loads(path.read_text())["stop_reason"] == "runtime_revision_mismatch"


@pytest.mark.parametrize(
    "identity", ["", "1;true", "0-1", "1-0", "1-1\n", "../x", "1-1000"]
)
def test_run_identity_rejects_arbitrary_receipt_access(identity):
    with pytest.raises(ValueError):
        runner.run_key(identity)


@pytest.mark.parametrize("actual_model", ["synthetic-primary", "wrong-model"])
async def test_real_run_path_preserves_metering_and_restores_environment(
    monkeypatch, tmp_path, actual_model
):
    class Session:
        async def scalars(self, query):
            assert "operation_id" in str(query)
            return SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        model=actual_model,
                        estimated_cost_usd=Decimal("0.01"),
                        input_tokens=100,
                        output_tokens=50,
                    )
                ]
            )

    @asynccontextmanager
    async def session():
        yield Session()

    @asynccontextmanager
    async def feature(db, key):
        assert key == runner.AIFeatureKey.cv_generator
        yield SimpleNamespace(operation_id="synthetic-operation")

    calls = []

    def verify(*args, **kwargs):
        calls.append(runner.os.environ["CV_B2B_MODEL"])
        assert runner.os.environ["CV_B2B_FALLBACK_MODELS"] == ""

    monkeypatch.setenv("CV_B2B_MODEL", "synthetic-primary")
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", "synthetic-fallback")
    monkeypatch.setattr(runner, "AsyncSessionLocal", session)
    monkeypatch.setattr(runner, "ai_feature", feature)
    monkeypatch.setattr(runner, "verify_final_cv", verify)
    path = tmp_path / "result.json"
    result = await runner.evaluate(path, "primary", 1)
    assert result == (0 if actual_model == "synthetic-primary" else 1)
    report = json.loads(path.read_text())
    assert calls == ["synthetic-primary"]
    assert report["complete"] is True and report["evaluated"] == 1
    assert report["results"][0]["estimated_cost_usd"] == "0.01"
    assert report["results"][0]["actual_models"] == [actual_model]
    assert runner.os.environ["CV_B2B_MODEL"] == "synthetic-primary"
    assert runner.os.environ["CV_B2B_FALLBACK_MODELS"] == "synthetic-fallback"
