"""Runda 7 (R7-V1-3): odpowiedź z NEXUSA zachowuje cytat wątku z createReply."""

from app.services.m365.sender import _with_quoted_history


def test_reply_goes_right_after_body_tag() -> None:
    draft = {
        "body": {
            "contentType": "html",
            "content": "<html><body class='x'><hr><div>Cytat</div></body></html>",
        }
    }
    out = _with_quoted_history("<p>Odpowiedź</p>", draft)
    assert out == (
        "<html><body class='x'><p>Odpowiedź</p><hr><div>Cytat</div></body></html>"
    )


def test_fragment_without_body_tag_is_appended() -> None:
    draft = {"body": {"contentType": "HTML", "content": "<div>Cytat</div>"}}
    assert _with_quoted_history("<p>A</p>", draft) == "<p>A</p><div>Cytat</div>"


def test_text_quote_is_escaped() -> None:
    draft = {"body": {"contentType": "text", "content": "<b>x</b> & y"}}
    out = _with_quoted_history("<p>A</p>", draft)
    assert out == "<p>A</p><pre>&lt;b&gt;x&lt;/b&gt; &amp; y</pre>"


def test_draft_without_body_keeps_reply_only() -> None:
    assert _with_quoted_history("<p>A</p>", {"id": "d"}) == "<p>A</p>"
    assert _with_quoted_history("<p>A</p>", None) == "<p>A</p>"
    assert (
        _with_quoted_history("<p>A</p>", {"body": {"contentType": "html"}})
        == "<p>A</p>"
    )
