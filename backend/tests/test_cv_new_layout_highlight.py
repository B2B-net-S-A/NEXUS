"""Wyróżnik kandydata na stronie 1 „Nowego CV” (Artur 25.11.2026) — bez bazy i WeasyPrint."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.cv_page1 import HighlightUpdate, Page1Update, _merged
from app.services.cv_new_layout import NewCvDocument, render_new_cv_html
from app.services.cv_new_layout.context import build_context
from app.services.cv_new_layout.document import HighlightChoice
from app.services.cv_new_layout.highlight import (
    choice_from_extras,
    matches_client,
    resolve,
)
from tests._cv_new_layout_fixtures import TODAY, blind, english, long_cv

PKO = ["PKO BP", "Powszechna Kasa Oszczędności Bank Polski S.A"]


@pytest.mark.parametrize(
    ("company", "names", "hit"),
    [
        ("PKO.BP", PKO, True),
        ("PKO Bank Polski S.A.", PKO, True),
        ("PKN Orlen S.A.", ["Orlen"], True),
        ("Credit Agricole", ["Credit Agricole Bank Polska S.A."], True),
        ("Ingenium sp. z o.o.", ["ING"], False),
        ("Bank Millennium", ["Bank"], False),
        ("Softwarehouse Alfa", PKO, False),
        ("", PKO, False),
    ],
)
def test_matches_client(company, names, hit):
    assert matches_client(company, names) is hit


def _doc(data: dict, **kw) -> NewCvDocument:
    return NewCvDocument.from_cv_json(data, **kw)


def _with_client(names) -> dict:
    data = long_cv()
    data["client_names"] = names
    return data


def test_auto_highlight_from_work_at_the_client():
    ctx = build_context(_doc(_with_client(["Bank Przykładowy"])), TODAY)
    hl = resolve(ctx)
    assert hl is not None
    assert hl.label == "Doświadczenie w Bank Przykładowy"
    assert hl.sub == "2023–dziś"
    assert (
        hl.text.startswith("**3 lata")
        and "jako Główny analityk danych** w Bank Przykładowy." in hl.text
    )
    assert hl.token == "3 lata"  # nazwa dłuższa niż 8 znaków: w wieńcu staż


def test_auto_highlight_short_client_name_goes_into_the_wreath():
    data = _with_client(["Beta"])
    hl = resolve(build_context(_doc(data), TODAY))
    assert hl is not None and hl.token == "Beta" and hl.sub == "2021–2023"


def test_no_highlight_without_client_work_blind_or_off():
    assert resolve(build_context(_doc(_with_client(PKO)), TODAY)) is None
    assert (
        resolve(build_context(_doc(blind(_with_client(["Bank Przykładowy"]))), TODAY))
        is None
    )
    off = _doc(_with_client(["Bank Przykładowy"]), highlight=HighlightChoice("off"))
    assert resolve(build_context(off, TODAY)) is None


def test_custom_highlight_needs_label_and_text():
    custom = HighlightChoice(
        "custom", "Wyróżnienie", "2015", "**Best IT Project Manager** 2015."
    )
    hl = resolve(build_context(_doc(long_cv(), highlight=custom), TODAY))
    assert hl is not None and (hl.label, hl.token) == ("Wyróżnienie", "2015")
    empty = HighlightChoice("custom", "Wyróżnienie", "", "")
    assert resolve(build_context(_doc(long_cv(), highlight=empty), TODAY)) is None


def test_english_auto_highlight():
    data = english(_with_client(["Bank Przykładowy"]))
    hl = resolve(build_context(_doc(data), TODAY))
    assert (
        hl is not None
        and hl.label == "Experience at Bank Przykładowy"
        and hl.sub.endswith("today")
    )
    assert " as Główny analityk danych** at Bank Przykładowy." in hl.text


def test_page1_has_one_wreath_only():
    """Wieniec raz na stronie: z wyróżnikiem Edukacja idzie bez wieńca (ikony)."""
    plain = render_new_cv_html(_doc(long_cv()), today=TODAY)
    assert (
        "class='hl'" not in plain
        and "class='wb'" not in plain  # Edukacja bez wieńca zawsze (Artur 25.11.2026)
        and plain.count('class="hlw"') == 0
    )
    html = render_new_cv_html(_doc(_with_client(["Bank Przykładowy"])), today=TODAY)
    p1 = html.split("<div class='rest'>")[0]
    assert "class='hl'" in p1 and "class='edp'" in p1 and "class='wb'" not in p1
    assert "Doświadczenie w Bank Przykładowy · 2023–dziś" in p1


def test_choice_from_extras_trims_and_defaults():
    assert choice_from_extras(None) == HighlightChoice()
    assert choice_from_extras({"highlight": {"mode": "x"}}) == HighlightChoice()
    got = choice_from_extras(
        {
            "highlight": {
                "mode": "custom",
                "label": " A  b ",
                "token": "123456789",
                "text": "t",
            }
        }
    )
    assert got == HighlightChoice("custom", "A b", "12345678", "t")


def test_patch_merge_highlight():
    extras = {"why": ["a"], "wreath": "cert"}
    custom = _merged(
        extras,
        Page1Update(
            highlight=HighlightUpdate(
                mode="custom",
                label=" Wyróżnienie ",
                token="2015",
                text="Zdanie\nz nową linią",
            )
        ),
    )
    assert custom["highlight"] == {
        "mode": "custom",
        "label": "Wyróżnienie",
        "token": "2015",
        "text": "Zdanie z nową linią",
    }
    assert custom["why"] == ["a"] and custom["wreath"] == "cert"
    assert _merged(custom, Page1Update(highlight=HighlightUpdate(mode="off")))[
        "highlight"
    ] == {"mode": "off"}
    assert "highlight" not in _merged(
        custom, Page1Update(highlight=HighlightUpdate(mode="auto"))
    )
    with pytest.raises(HTTPException) as err:
        _merged(
            extras,
            Page1Update(highlight=HighlightUpdate(mode="custom", label="Wyróżnienie")),
        )
    assert err.value.status_code == 422


def test_patch_highlight_limits():
    with pytest.raises(ValueError):
        HighlightUpdate(mode="custom", label="x", text="y", token="123456789")
    with pytest.raises(ValueError):
        HighlightUpdate(mode="inne")
