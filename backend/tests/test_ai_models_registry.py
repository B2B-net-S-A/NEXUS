"""Rejestr modeli AI — jedno miejsce prawdy dla każdej funkcji generatywnej.

Strażnik przed regresją, którą naprawił C11: model ustalany literałem rozsianym
po 13 plikach, gdzie ``CLAUDE_MODEL_CV`` sterował po cichu DWIEMA funkcjami.
"""

import pytest

from app.models.ai_feature import AIFeatureKey
from app.services import ai_models


def test_every_feature_key_has_a_registry_entry():
    """Nowa funkcja AI nie może wrócić do literału — musi mieć wpis w rejestrze."""
    missing = [k.value for k in AIFeatureKey if k not in ai_models._REGISTRY]
    assert not missing, f"Brak wpisu w ai_models._REGISTRY dla: {missing}"


def test_registry_snapshot_covers_all_keys():
    snap = ai_models.registry_snapshot()
    assert set(snap) == {k.value for k in AIFeatureKey}
    for value, info in snap.items():
        assert info["model"], f"{value} bez modelu"
        assert info["source"] in ("default",) or info["source"].startswith(
            ("env:", "settings:")
        )


def test_cv_generator_keeps_the_sonnet_46_pin_and_opus_fallback():
    """Rewert #628: pin Sonnet 4.6 + fallback opus — decyzja jakościowa, nie przypadek."""
    assert ai_models.model_for(AIFeatureKey.cv_generator) == "claude-sonnet-4-6"
    assert ai_models.model_chain_for(AIFeatureKey.cv_generator) == [
        "claude-sonnet-4-6",
        "claude-opus-4-8",
    ]


def test_model_chain_dedupes_primary_in_fallbacks():
    choice = ai_models.ModelChoice(
        default="claude-sonnet-5", fallbacks=("claude-sonnet-5", "claude-opus-4-8")
    )
    # podmień tymczasowo wpis, żeby sprawdzić dedup na realnej ścieżce
    original = ai_models._REGISTRY[AIFeatureKey.uop_check]
    ai_models._REGISTRY[AIFeatureKey.uop_check] = choice
    try:
        assert ai_models.model_chain_for(AIFeatureKey.uop_check) == [
            "claude-sonnet-5",
            "claude-opus-4-8",
        ]
    finally:
        ai_models._REGISTRY[AIFeatureKey.uop_check] = original


def test_empty_env_override_is_ignored(monkeypatch):
    """Coolify wstrzykuje puste stringi — pusty override to brak, nie model ''."""
    monkeypatch.setenv("UOP_CHECK_MODEL", "   ")
    # resolve() czyta env przy KAŻDYM wywołaniu — bez reloadu (reload config/rejestru
    # podmieniłby globalny singleton settings i zatruł kolejne testy w tym biegu).
    assert ai_models.model_for(AIFeatureKey.uop_check) == "claude-sonnet-5"


def test_narrow_override_splits_cv_parser_from_mindy(monkeypatch):
    """Sedno C11: MINDY_MODEL zmienia MINDY, ale NIE parser CV."""
    from app.core.config import settings

    monkeypatch.setenv("MINDY_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.delenv("CV_PARSER_MODEL", raising=False)
    # cv_parser bierze legacy z settings.CLAUDE_MODEL_CV — ustaw na domyślny
    monkeypatch.setattr(settings, "CLAUDE_MODEL_CV", "claude-sonnet-5")
    assert ai_models.model_for(AIFeatureKey.mindy_chat) == "claude-haiku-4-5-20251001"
    assert ai_models.model_for(AIFeatureKey.cv_parser) == "claude-sonnet-5"


def test_legacy_claude_model_cv_still_drives_both_until_split(monkeypatch):
    """Kompat: stara zmienna nadal steruje parserem CV i MINDY, gdy wąskich brak.

    Patchujemy `settings.CLAUDE_MODEL_CV` wprost (resolve() czyta je przez
    getattr przy wywołaniu). NIE reloadujemy config — reload podmienia globalny
    singleton settings, a inne moduły trzymają starą referencję (to zatruwało
    test_ungated_call_is_only_logged_by_default w tym samym biegu)."""
    from app.core.config import settings

    monkeypatch.delenv("CV_PARSER_MODEL", raising=False)
    monkeypatch.delenv("MINDY_MODEL", raising=False)
    monkeypatch.setattr(settings, "CLAUDE_MODEL_CV", "claude-opus-4-8")
    assert ai_models.model_for(AIFeatureKey.cv_parser) == "claude-opus-4-8"
    assert ai_models.model_for(AIFeatureKey.mindy_chat) == "claude-opus-4-8"


@pytest.mark.parametrize(
    "feature,expected",
    [
        (AIFeatureKey.scoring, "claude-sonnet-5"),
        (AIFeatureKey.cv_interactive_chat, "claude-haiku-4-5-20251001"),
        (AIFeatureKey.champion_profile_parse, "claude-haiku-4-5-20251001"),
        (AIFeatureKey.order_parser, "claude-sonnet-5"),
    ],
)
def test_defaults_match_pre_registry_values(feature, expected):
    """Zachowanie bit w bit: te same domyślki co przed rejestrem."""
    assert ai_models.model_for(feature) == expected
