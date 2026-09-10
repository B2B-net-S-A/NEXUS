import hashlib
import json
from types import SimpleNamespace

import pytest

from app.services.cv_version_map_input import encode_map_input, decode_map_input


def version():
    html = "<p>AWS wyłącznie szkoleniowo.</p><p>Bez wdrożeń produkcyjnych.</p>"
    return SimpleNamespace(
        id=71,
        language="pl",
        content_html=html,
        content_sha256=hashlib.sha256(html.encode()).hexdigest(),
    )


def test_snapshot_keeps_exact_approved_text_and_requirements():
    approved = version()
    requirements = [{"name": "AWS", "kind": "must"}]
    raw, digest = encode_map_input(approved, requirements)
    requirements[0]["name"] = "Changed vacancy"
    decoded = decode_map_input(raw, digest, approved)
    assert decoded.requirements[0].name == "AWS"
    assert decoded.public_payload()["why_points"] == [
        "AWS wyłącznie szkoleniowo.",
        "Bez wdrożeń produkcyjnych.",
    ]


@pytest.mark.parametrize("change", ["digest", "version", "html", "paragraphs", "extra"])
def test_snapshot_rejects_wrong_version_and_changed_text(change):
    approved = version()
    raw, digest = encode_map_input(approved, [{"name": "AWS", "kind": "must"}])
    if change == "digest":
        digest = "0" * 64
    elif change == "version":
        approved.id = 72
    elif change == "html":
        approved.content_html = "<p>Changed</p>"
    else:
        content = json.loads(raw)
        if change == "paragraphs":
            content["paragraphs"] = ["Production AWS ownership"]
        else:
            content["private_notes"] = "Must not enter model"
        raw = json.dumps(content).encode()
        digest = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        decode_map_input(raw, digest, approved)
