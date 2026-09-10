import hashlib
import json
import pytest
from app.services.cv_approval_provenance import capture_editor_origin
from app.services.cv_generator_b2b.public_view import build_public_payload


@pytest.mark.parametrize("case", ["rule", "no_rule", "missing", "changed"])
def test_editor_keeps_only_verified_frozen_rule_provenance(case):
    snapshot = (
        {"max_roles": 2, "custom_instructions": "Private client instruction"}
        if case != "no_rule"
        else None
    )
    payload = {
        "name": "Person",
        "client_rule_snapshot": snapshot,
        "editorial_provenance": {
            "rule_sha256": hashlib.sha256(
                json.dumps(
                    snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
        },
    }
    if case == "missing":
        del payload["client_rule_snapshot"]
    elif case == "changed":
        snapshot["max_roles"] = 3
    metadata = capture_editor_origin("<p>CV</p>", payload)
    assert metadata["client_rule_snapshot_status"] == (
        "verified" if case in ("rule", "no_rule") else "unavailable"
    )
    if case == "rule":
        snapshot["max_roles"] = 9
        assert metadata["client_rule_snapshot"]["max_roles"] == 2
    public = build_public_payload(payload)
    assert "client_rule_snapshot" not in public
    assert "Private client instruction" not in str(public)
