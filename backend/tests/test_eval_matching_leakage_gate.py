"""AI-P0-01 — the matching eval closes label leakage and can gate CI.

Two defects made the eval untrustworthy as a quality gate:

1. Label leakage — the headline ran the default profile with champion_fit=10,
   and ``_score_champion_fit`` reads ``screening_answers`` that only exist for
   ground-truth positives. The model was peeking at the label. Now champion_fit
   is zeroed by default (``--include-champion`` to opt back in).
2. No gate — ``_run`` always exit-0'd, so a matching regression went green.
   Now ``--fail-under-precision`` / ``--fail-under-recall`` make it exit non-zero.

These unit-test the wiring (mask + arg surface); the full metric run needs a
live DB + Voyage and is out of scope here.
"""

from __future__ import annotations

from scripts.eval_matching import (
    DEFAULT_PROFILE,
    _parse_args,
    _without_champion,
)


def test_without_champion_zeros_only_that_layer() -> None:
    masked = _without_champion(DEFAULT_PROFILE)
    assert masked.champion_fit == 0.0
    # Every other layer is untouched (only the leaky signal is removed).
    for layer in ("semantic", "skills", "salary", "location", "availability"):
        assert getattr(masked, layer) == getattr(DEFAULT_PROFILE, layer)
    # And the original is unmutated (frozen-dataclass replace, not in-place).
    assert DEFAULT_PROFILE.champion_fit == 10.0


def test_champion_off_by_default_on_by_flag() -> None:
    assert _parse_args([]).include_champion is False
    assert _parse_args(["--include-champion"]).include_champion is True


def test_fail_under_thresholds_parse() -> None:
    default = _parse_args([])
    assert default.fail_under_precision is None
    assert default.fail_under_recall is None

    args = _parse_args(["--fail-under-precision", "0.15", "--fail-under-recall", "0.4"])
    assert args.fail_under_precision == 0.15
    assert args.fail_under_recall == 0.4
