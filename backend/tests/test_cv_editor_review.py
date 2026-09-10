import pytest

from app.services.cv_editor_review import editor_claims, EditorReviewInputError


def test_preserves_inline_negation_and_role_context_in_order():
    assert editor_claims(
        "<h2>Doświadczenie</h2><h3>Firma A — Junior</h3><p>Nie <strong>zarządzał</strong> zespołem.</p><p>3 lata w roli.</p>"
    ) == [
        "Firma A — Junior",
        "Nie zarządzał zespołem.",
        "3 lata w roli.",
    ]


def test_never_hides_excess_claims_or_unreviewed_image_content():
    for content in (
        "<p>fakt</p>" * 1001,
        '<img src="data:image/png;base64,AA=="><p>fakt</p>',
        "",
    ):
        with pytest.raises(EditorReviewInputError):
            editor_claims(content)


def test_table_cells_keep_a_boundary_and_do_not_join_numbers():
    assert editor_claims("<table><tr><td>3</td><td>lata</td></tr></table>") == [
        "3 | lata |"
    ]
