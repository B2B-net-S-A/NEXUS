"""`scripts/staging/compare_flags.py`: różnica flagi z diffu blokuje, reszta idzie do paragonu."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "compare_flags", Path(__file__).resolve().parents[2] / "scripts/staging/compare_flags.py"
)
cf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cf)


def test_flags_in_diff_finds_names():
    diff = "+    if settings.CV_NEW_LAYOUT_ENABLED:\n-  x = MATCH_POOL_SIZE\n+ foo_enabled = 1"
    assert cf.flags_in_diff(diff) == {"CV_NEW_LAYOUT_ENABLED", "MATCH_POOL_SIZE"}


def test_difference_in_touched_flag_blocks():
    rows, blocking = cf.compare(
        {"CV_NEW_LAYOUT_ENABLED": False, "LAW_RADAR_ENABLED": False},
        {"CV_NEW_LAYOUT_ENABLED": True, "LAW_RADAR_ENABLED": True},
        {"CV_NEW_LAYOUT_ENABLED"},
    )
    assert blocking
    assert ("CV_NEW_LAYOUT_ENABLED", False, True, "tak → blokada") in rows
    assert ("LAW_RADAR_ENABLED", False, True, "nie") in rows


def test_difference_outside_diff_does_not_block():
    rows, blocking = cf.compare({"A_ENABLED": False}, {"A_ENABLED": True}, set())
    assert not blocking and rows == [("A_ENABLED", False, True, "nie")]


def test_equal_touched_flag_listed_without_block():
    rows, blocking = cf.compare({"A_ENABLED": True}, {"A_ENABLED": True}, {"A_ENABLED"})
    assert not blocking and rows == [("A_ENABLED", True, True, "tak")]


def test_render_table_has_header_and_lowercase_bools():
    text = cf.render([("A_ENABLED", False, True, "tak → blokada")])
    assert text.splitlines()[0] == "| flaga | staging | prod | w diffie? |"
    assert "| A_ENABLED | false | true | tak → blokada |" in text
    assert "(brak różnic)" in cf.render([])
