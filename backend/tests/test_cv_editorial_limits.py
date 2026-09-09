import copy
import json
from unittest.mock import Mock

import pytest

from app.services.cv_generator_b2b import editorial_limits as editor
from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot


LONG = "Odpowiadał za testy migracji do AWS wyłącznie w środowisku szkoleniowym, bez wdrożeń produkcyjnych."
PATH = "/experience/0/responsibilities/0"
RULE = CvRuleSnapshot(None, False, None, False, False, max_bullet_chars=40)


def data():
    return {"experience": [{"responsibilities": [LONG, "Tworzył API."]}]}


def test_rewrites_whole_bullet_preserving_qualification(monkeypatch):
    call = Mock(
        return_value=json.dumps(
            {"items": [{"path": PATH, "text": "Testy migracji AWS tylko szkoleniowo."}]}
        )
    )
    monkeypatch.setattr(editor, "analyze_with_ai", call)
    candidate = data()
    editor.fit_responsibilities(candidate, RULE, language="pl", request_id="audit")
    assert candidate["experience"][0]["responsibilities"] == [
        "Testy migracji AWS tylko szkoleniowo.",
        "Tworzył API.",
    ]
    request = json.loads(call.call_args.args[0])
    assert request["items"] == [{"path": PATH, "text": LONG}]


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{"path": PATH, "text": ""}],
        [{"path": PATH, "text": LONG}],
        [{"path": PATH, "text": "Testy migracji AWS…"}],
        [{"path": "/experience/5", "text": "Testy"}],
        [{"path": PATH, "text": "Testy"}, {"path": PATH, "text": "Testy"}],
    ],
)
def test_failed_editorial_response_cannot_partially_mutate_document(monkeypatch, items):
    monkeypatch.setattr(
        editor, "analyze_with_ai", lambda *a, **k: json.dumps({"items": items})
    )
    candidate = data()
    before = copy.deepcopy(candidate)
    with pytest.raises(editor.EditorialLimitError):
        editor.fit_responsibilities(candidate, RULE, language="pl", request_id="audit")
    assert candidate == before


def test_already_fitting_document_does_not_call_model(monkeypatch):
    call = Mock(side_effect=AssertionError("unnecessary model call"))
    monkeypatch.setattr(editor, "analyze_with_ai", call)
    editor.fit_responsibilities(
        {"experience": [{"responsibilities": ["Testy API."]}]},
        RULE,
        language="pl",
        request_id="audit",
    )
    call.assert_not_called()
