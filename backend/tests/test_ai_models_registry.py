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


def test_cv_generator_is_sonnet_5_with_opus_fallback():
    """F4 (decyzja 16.09.2026): Sonnet 5 z thinking=disabled — w badaniu na
    danych produkcyjnych wymyślał fakty w 20% CV vs 41% u Sonneta 4.6 (rewert
    #628 mierzył Sonneta 5 z WYMUSZONYM thinking). Fallback Opus zostaje."""
    assert ai_models.model_for(AIFeatureKey.cv_generator) == "claude-sonnet-5"
    assert ai_models.model_chain_for(AIFeatureKey.cv_generator) == [
        "claude-sonnet-5",
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
    assert ai_models.model_for(AIFeatureKey.uop_check) == "gpt-5.6-luna"


def test_narrow_override_splits_cv_parser_from_mindy(monkeypatch):
    """Sedno C11: MINDY_MODEL zmienia MINDY, ale NIE parser CV."""
    from app.core.config import settings

    monkeypatch.setenv("MINDY_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.delenv("CV_PARSER_MODEL", raising=False)
    # cv_parser bierze legacy z settings.CLAUDE_MODEL_CV — ustaw na domyślny
    monkeypatch.setattr(settings, "CLAUDE_MODEL_CV", "claude-sonnet-5")
    assert ai_models.model_for(AIFeatureKey.mindy_chat) == "claude-haiku-4-5-20251001"
    assert ai_models.model_for(AIFeatureKey.cv_parser) == "claude-sonnet-5"


def test_legacy_claude_model_cv_drives_the_cv_parser_but_no_longer_mindy(monkeypatch):
    """Kompat: stara zmienna nadal steruje parserem CV (i syncem imion), gdy
    wąskich brak. MINDY od 16.09.2026 ma własny model (GPT Luna) — legacy
    `CLAUDE_MODEL_CV` NIE może jej cofać na Claude; to było sprzężenie z C11.

    Patchujemy `settings.CLAUDE_MODEL_CV` wprost (resolve() czyta je przez
    getattr przy wywołaniu). NIE reloadujemy config — reload podmienia globalny
    singleton settings, a inne moduły trzymają starą referencję (to zatruwało
    test_ungated_call_is_only_logged_by_default w tym samym biegu)."""
    from app.core.config import settings

    monkeypatch.delenv("CV_PARSER_MODEL", raising=False)
    monkeypatch.delenv("CV_NAME_BACKFILL_MODEL", raising=False)
    monkeypatch.delenv("MINDY_MODEL", raising=False)
    monkeypatch.setattr(settings, "CLAUDE_MODEL_CV", "claude-opus-4-8")
    assert ai_models.model_for(AIFeatureKey.cv_parser) == "claude-opus-4-8"
    assert ai_models.model_for(AIFeatureKey.cv_name_backfill) == "claude-opus-4-8"
    assert ai_models.model_for(AIFeatureKey.mindy_chat) == "gpt-5.6-luna"


# Decyzja Artura z 16.09.2026 po badaniu modeli na danych produkcyjnych
# (outputs/model-matrix-2026-09-15/RAPORT-KONCOWY.md, identyfikatory F1–F15).
# Test czyta model przez resolve(), więc env-override w środowisku testowym
# (np. UOP_CHECK_MODEL z .env) zmieniłby wynik — dlatego zdejmujemy każdy.
DECISION_2026_09_16 = {
    AIFeatureKey.scoring: ("F1", "claude-sonnet-5"),
    AIFeatureKey.champion_profile_parse: ("F2", "claude-sonnet-5"),
    AIFeatureKey.cv_requirement_map: ("F3", "claude-sonnet-5"),
    AIFeatureKey.cv_generator: ("F4", "claude-sonnet-5"),
    AIFeatureKey.cv_interactive_chat: ("F5", "gpt-5.6-luna"),
    AIFeatureKey.job_description_generator: ("F6", "claude-sonnet-5"),
    # F7 — powrót na Sonneta 5 decyzją 21.09.2026 (GPT Luna flagowała
    # poprawne odczyty jako niepewne).
    AIFeatureKey.order_parser: ("F7", "claude-sonnet-5"),
    AIFeatureKey.uop_check: ("F8", "gpt-5.6-luna"),
    AIFeatureKey.cv_parser: ("F9", "claude-sonnet-5"),
    AIFeatureKey.cv_backfill: ("F10", "claude-sonnet-5"),
    AIFeatureKey.cv_name_backfill: ("F10", "claude-sonnet-5"),
    # Ta sama robota co F10 (odczyt CV), więc ten sam model. Osobny klucz jest
    # po to, żeby dało się zgasić ścieżkę użytkownika bez nocnego syncu.
    AIFeatureKey.experience_dates_on_demand: ("F10", "claude-sonnet-5"),
    AIFeatureKey.notes_extraction: ("F11", "deepseek-v4-pro"),
    AIFeatureKey.candidate_summary: ("F12", "deepseek-v4-pro"),
    AIFeatureKey.champion_draft: ("F13", "claude-sonnet-5"),
    AIFeatureKey.cv_rule_lint: ("F14", "claude-sonnet-5"),
    AIFeatureKey.mindy_chat: ("F15", "gpt-5.6-luna"),
    # F18 — decyzja 18.09.2026, POZA badaniem 16.09: recenzent gotowego CV
    # musi być INNYM modelem niż generator (F4), bo sędzia LLM faworyzuje
    # własne wyjście. Zmiana tego wpisu na model generatora cofa sens funkcji.
    AIFeatureKey.cv_factual_verification: ("F18", "gpt-5.6-luna"),
    # F19 — decyzja 21.09.2026: Jarvis woła `tools`, więc tylko Anthropic.
    AIFeatureKey.jarvis: ("F19", "claude-sonnet-5"),
}


def _clear_model_overrides(monkeypatch):
    from app.core.config import settings

    for choice in ai_models._REGISTRY.values():
        for name in choice.env_vars:
            monkeypatch.delenv(name, raising=False)
    # Legacy pola settings: domyślne z config.py (Sonnet 5 od 16.09.2026).
    monkeypatch.setattr(settings, "CLAUDE_MODEL_CV", "claude-sonnet-5")
    monkeypatch.setattr(settings, "CLAUDE_MODEL_CV_BULK", "claude-sonnet-5")
    monkeypatch.setattr(settings, "ORDER_PARSER_MODEL", "claude-sonnet-5")


def test_decision_table_covers_every_feature():
    assert set(DECISION_2026_09_16) == set(AIFeatureKey)


@pytest.mark.parametrize(
    "feature,function_id,expected",
    [(k, v[0], v[1]) for k, v in DECISION_2026_09_16.items()],
    ids=[f"{v[0]}-{k.value}" for k, v in DECISION_2026_09_16.items()],
)
def test_defaults_match_the_2026_09_16_decision(monkeypatch, feature, function_id, expected):
    """Każda funkcja dostaje model z decyzji Artura (ID F1–F15 z raportu)."""
    _clear_model_overrides(monkeypatch)
    assert ai_models.model_for(feature) == expected, function_id


def test_legacy_settings_defaults_agree_with_the_registry():
    """`settings_attr` wygrywa z `default`, więc domyślna wartość pola w config.py
    MUSI być tym samym modelem — inaczej decyzja z rejestru nigdy nie działa
    (tak Haiku siedziałby w backfillu przez CLAUDE_MODEL_CV_BULK)."""
    from app.core.config import Settings

    fields = Settings.model_fields
    for feature, choice in ai_models._REGISTRY.items():
        if choice.settings_attr:
            assert fields[choice.settings_attr].default == choice.default, (
                feature.value,
                choice.settings_attr,
            )


@pytest.mark.parametrize(
    "feature",
    [
        AIFeatureKey.cv_interactive_chat,
        AIFeatureKey.uop_check,
        AIFeatureKey.mindy_chat,
        AIFeatureKey.notes_extraction,
        AIFeatureKey.candidate_summary,
        AIFeatureKey.cv_factual_verification,
    ],
)
def test_non_anthropic_functions_fall_back_to_sonnet_5(monkeypatch, feature):
    """Przeciążenie/429 u OpenAI albo DeepSeek nie zdejmuje funkcji — łańcuch
    schodzi na Sonneta 5 (obaj dostawcy dopuszczeni do danych produkcyjnych)."""
    _clear_model_overrides(monkeypatch)
    chain = ai_models.model_chain_for(feature)
    assert len(chain) == 2
    assert chain[1] == "claude-sonnet-5"


def test_jarvis_chain_stays_on_anthropic(monkeypatch):
    """Jarvis wysyła `tools` — GPT/DeepSeek je odrzucają nieponawialnym
    ValueError, więc KAŻDY model w łańcuchu (także fallback) musi być Claude."""
    from app.services.llm_providers import ANTHROPIC, provider_of

    _clear_model_overrides(monkeypatch)
    chain = ai_models.model_chain_for(AIFeatureKey.jarvis)
    assert chain[0] == "claude-sonnet-5"
    assert all(provider_of(model) == ANTHROPIC for model in chain)


def test_providers_in_use_lists_openai_and_deepseek(monkeypatch):
    _clear_model_overrides(monkeypatch)
    assert ai_models.providers_in_use() == ["deepseek", "openai"]


def test_registry_snapshot_reports_provider_and_key(monkeypatch):
    """Panel AI i sonda zdrowia widzą, KTÓRY dostawca i czy ma klucz."""
    _clear_model_overrides(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "")
    snap = ai_models.registry_snapshot()
    assert snap["mindy_chat"]["provider"] == "openai"
    assert snap["mindy_chat"]["key_configured"] is True
    assert snap["notes_extraction"]["provider"] == "deepseek"
    assert snap["notes_extraction"]["key_configured"] is False
    assert snap["scoring"]["provider"] == "anthropic"


def test_retrieval_defaults_f16_voyage_3_and_f17_reranker_off():
    """F16/F17 (16.09.2026): embeddingi zostają na voyage-3 (model produkcyjnych
    kolekcji; inne Voyage n.s., OpenAI gorszy), reranker WYŁĄCZONY (no-op w
    produkcyjnej ścieżce, dosypka n.s.). Asercja na DOMYŚLNYCH polach klasy,
    nie na singletonie — env testowe nie może tego przysłonić."""
    from app.core.config import Settings

    assert Settings.model_fields["VOYAGE_MODEL"].default == "voyage-3"
    assert Settings.model_fields["RERANKER_ENABLED"].default is False
