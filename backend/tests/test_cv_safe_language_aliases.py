import copy

import pytest
from pydantic import ValidationError

from app.api.client_cv_rules import ClientCvRulePayload, ClientCvRuleRead
from app.services.cv_generator_b2b.client_rules import (
    CvRuleSnapshot,
    apply_presentation_policy,
    build_client_presentation_rules_block,
)
from app.services.cv_generator_b2b.language_aliases import alias_catalog


def rule(pairs):
    return CvRuleSnapshot(None, False, None, False, False, glossary=tuple(pairs))


@pytest.mark.parametrize(
    "source,target",
    [
        ("Python", "Rust"),
        ("AWS SAA", "AWS SAP"),
        ("Junior Developer", "Senior Developer"),
        ("BA", "Analityk Biznesowy"),
        ("2 lata", "10 lat"),
        ("SQL", "SQL, Kubernetes"),
    ],
)
def test_unsafe_legacy_pair_cannot_reach_model_or_document(source, target):
    recipe = rule([(source, target)])
    payload = {
        "position": source,
        "why_points": [source],
        "certifications": [source],
        "skills": [{"content": source}],
        "experience": [
            {"position": source, "responsibilities": [source], "technologies": [source]}
        ],
    }
    before = copy.deepcopy(payload)
    assert "niedozwolonych" in " ".join(apply_presentation_policy(payload, recipe))
    assert payload == before
    assert target not in build_client_presentation_rules_block(recipe, "pl")
    # Old drafts can still be opened/saved for correction, never published.
    pair = {"from": source, "to": target}
    ClientCvRulePayload(glossary=[pair], confirm=False)
    with pytest.raises(ValidationError, match="niedozwoloną"):
        ClientCvRulePayload(glossary=[pair], confirm=True)


@pytest.mark.parametrize("option", alias_catalog())
def test_catalog_is_publishable_and_applies_only_to_exact_titles(option):
    pair = {key: option[key] for key in ("kind", "from", "to")}
    ClientCvRulePayload(glossary=[pair], confirm=True)
    source, target = option["from"], option["to"]
    payload = {
        "language": option["target_language"],
        "position": source,
        "why_points": [source],
        "skills": [{"content": source}],
        "certifications": [source],
        "experience": [
            {
                "position": source,
                "responsibilities": [source],
                "technologies": [source],
            },
            {"position": "Senior " + source},
        ],
    }
    before = copy.deepcopy(payload)
    apply_presentation_policy(payload, rule([(source, target)]))
    assert payload["position"] == target
    assert payload["experience"][0]["position"] == target
    payload["position"] = source
    payload["experience"][0]["position"] = source
    assert payload == before
    payload["language"] = option["source_language"]
    apply_presentation_policy(payload, rule([(source, target)]))
    assert payload["position"] == source


def test_catalog_is_returned_even_when_client_has_no_rule():
    assert ClientCvRuleRead(client_id=1).glossary_options == alias_catalog()


def test_unrecognized_alias_kind_rejected():
    with pytest.raises(ValidationError):
        ClientCvRulePayload(
            glossary=[{"kind": "technology", "from": "Python", "to": "Rust"}]
        )
