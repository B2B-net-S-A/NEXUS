"""Unit tests for legacy Traffit `$$user_NN$$` mention resolution.

Pure-function coverage (no DB):
    1. collect_traffit_user_ids — extracts ids, dedups, ignores noise
    2. render_traffit_mentions — token → @Name, unknown → fallback, @email untouched
"""

from __future__ import annotations

from app.services.note_mention_render import (
    collect_traffit_user_ids,
    render_traffit_mentions,
)


def test_collect_extracts_distinct_ids_across_notes() -> None:
    ids = collect_traffit_user_ids(
        [
            "<div><p>$$user_40$$ hello</p></div>",
            '{"content":"<p>$$user_205$$ and $$user_40$$</p>"}',
            None,
            "no tokens here",
        ]
    )
    assert ids == {"40", "205"}


def test_collect_empty_when_no_tokens() -> None:
    assert collect_traffit_user_ids(["plain note", "", None]) == set()


def test_render_replaces_known_token_with_name() -> None:
    out = render_traffit_mentions(
        "<div><p>$$user_40$$&nbsp;</p></div>", {"40": "Klaudia Uliasz"}
    )
    assert out == "<div><p>@Klaudia Uliasz&nbsp;</p></div>"
    assert "$$user_40$$" not in out


def test_render_handles_multiple_tokens_in_json_wrapper() -> None:
    raw = '{"content":"<p>$$user_205$$ napisał do $$user_40$$</p>","state":{"id":1}}'
    out = render_traffit_mentions(
        raw, {"205": "Ignacy Kotecki", "40": "Klaudia Uliasz"}
    )
    assert out == (
        '{"content":"<p>@Ignacy Kotecki napisał do @Klaudia Uliasz</p>","state":{"id":1}}'
    )


def test_render_unknown_id_falls_back_to_generic_label() -> None:
    # The raw token must never reach the UI, even for pruned Traffit accounts.
    out = render_traffit_mentions("ping $$user_999$$", {})
    assert out == "ping @użytkownik"
    assert "$$user_999$$" not in out


def test_render_leaves_native_email_mentions_untouched() -> None:
    raw = "rozmowa z @jan.kowalski@b2bnetwork.pl o $$user_40$$"
    out = render_traffit_mentions(raw, {"40": "Klaudia Uliasz"})
    assert out == "rozmowa z @jan.kowalski@b2bnetwork.pl o @Klaudia Uliasz"


def test_render_passthrough_for_empty_and_none() -> None:
    assert render_traffit_mentions("", {"40": "X"}) == ""
    assert render_traffit_mentions(None, {"40": "X"}) is None
    assert render_traffit_mentions("note without tokens", {}) == "note without tokens"
