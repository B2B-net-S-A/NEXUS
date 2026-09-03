"""Jedno miejsce, w którym widać: funkcja generatywna → model → skąd.

Do tego PR-a model był ustalany w CZTERECH mechanizmach rozrzuconych po 13
plikach: typed settings (``settings.CLAUDE_MODEL_CV``), ``os.environ`` z
literałem-fallbackiem, literał modułowy i literał w domyślnym argumencie.
Skutki, których nie widać z pojedynczego pliku:

* ``CLAUDE_MODEL_CV`` sterował DWIEMA funkcjami — parserem CV i MINDY — więc
  zmiana modelu dla jednej po cichu zmieniała drugą. Tak samo
  ``CLAUDE_MODEL_CV_BULK`` wiązał masowy backfill z lintem reguł CV.
* Cztery funkcje (generator ogłoszeń, fakty z notatek, odczyt profili
  Championa, generator CV do #628) miały model wyłącznie w literale — bez
  żadnego env-override.

Rejestr wiąże KAŻDY ``AIFeatureKey`` z jego modelem, opcjonalnym łańcuchem
fallbacków i listą env-override'ów. Zachowanie każdego z 16 punktów jest
odtworzone bit w bit (ten sam efektywny model przy braku nowych zmiennych),
a rozdzielone funkcje dostają WŁASNE, węższe zmienne, honorując przy tym
stare (``CLAUDE_MODEL_CV`` / ``CLAUDE_MODEL_CV_BULK``) dla kompatybilności.

Rozwiązanie różnicy pustego env-a: Coolify wstrzykuje puste stringi
(``CV_B2B_MAX_RETRIES=""`` — patrz ``claude_client.env_number``), więc pusty
override jest traktowany jak brak, a nie jak model o nazwie ``""``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.core.config import settings
from app.models.ai_feature import AIFeatureKey


@dataclass(frozen=True)
class ModelChoice:
    """Deklaratywny opis: skąd bierze się model danej funkcji.

    Precedencja przy rozwiązywaniu: kolejne ``env_vars`` (pierwszy niepusty
    wygrywa) → ``settings_attr`` (pole pydantic, dla ścieżek migrujących ze
    starej zmiennej) → ``default``. Pusty/whitespace env jest pomijany.
    """

    default: str
    env_vars: tuple[str, ...] = ()
    settings_attr: str | None = None
    fallbacks: tuple[str, ...] = ()
    rationale: str = ""

    def resolve(self) -> tuple[str, str]:
        """Zwraca ``(model, źródło)`` — źródło do sondy zdrowia i panelu AI."""
        for name in self.env_vars:
            raw = os.environ.get(name)
            if raw and raw.strip():
                return raw.strip(), f"env:{name}"
        if self.settings_attr:
            val = getattr(settings, self.settings_attr, None)
            if val and str(val).strip():
                return str(val).strip(), f"settings:{self.settings_attr}"
        return self.default, "default"


# Uwaga: model literałów NIE jest tu zmieniany — te same wartości, co przed
# rejestrem. Zmiana literału champion_profile_parse unieważnia klucz cache
# promptu ('champion_parse:v4:haiku-4.5' to OSOBNY string) — nie ruszać bez
# bumpa wersji promptu.
_REGISTRY: dict[AIFeatureKey, ModelChoice] = {
    AIFeatureKey.scoring: ModelChoice(
        default="claude-sonnet-5",
        env_vars=("MATCH_SCORING_MODEL",),
        rationale="Uzasadnienie dopasowania (LLM); sam ranking jest deterministyczny.",
    ),
    AIFeatureKey.job_description_generator: ModelChoice(
        default="claude-sonnet-5",
        env_vars=("JOB_WRITER_MODEL",),
        rationale="Generator ogłoszeń; override dołożony w rejestrze (był goły literał).",
    ),
    AIFeatureKey.cv_parser: ModelChoice(
        default="claude-sonnet-5",
        env_vars=("CV_PARSER_MODEL",),
        settings_attr="CLAUDE_MODEL_CV",
        rationale="Parser CV; honoruje legacy CLAUDE_MODEL_CV, CV_PARSER_MODEL rozdziela go od MINDY.",
    ),
    AIFeatureKey.candidate_summary: ModelChoice(
        default="claude-sonnet-5",
        env_vars=("CANDIDATE_SUMMARY_MODEL",),
    ),
    AIFeatureKey.champion_draft: ModelChoice(
        default="claude-sonnet-5",
        env_vars=("CHAMPION_AI_MODEL",),
    ),
    AIFeatureKey.order_parser: ModelChoice(
        default="claude-sonnet-5",
        env_vars=("ORDER_PARSER_MODEL",),
        # settings_attr obok tego samego env: wierne odtworzenie oryginału
        # `os.environ.get("ORDER_PARSER_MODEL","") or settings.ORDER_PARSER_MODEL`.
        # env_vars (os.environ) wygrywa i zwykle to wystarcza; settings_attr
        # łapie wariant z pliku .env, który pydantic czyta, a os.environ nie widzi.
        settings_attr="ORDER_PARSER_MODEL",
    ),
    AIFeatureKey.cv_requirement_map: ModelChoice(
        default="claude-sonnet-5",
        env_vars=("CV_REQUIREMENT_MAP_MODEL",),
    ),
    AIFeatureKey.cv_interactive_chat: ModelChoice(
        default="claude-haiku-4-5-20251001",
        env_vars=("CV_INTERACTIVE_CHAT_MODEL",),
    ),
    AIFeatureKey.cv_backfill: ModelChoice(
        default="claude-haiku-4-5-20251001",
        env_vars=("CV_BACKFILL_MODEL",),
        settings_attr="CLAUDE_MODEL_CV_BULK",
        rationale="Masowy backfill pól; honoruje CLAUDE_MODEL_CV_BULK, CV_BACKFILL_MODEL rozdziela od lintu.",
    ),
    AIFeatureKey.notes_extraction: ModelChoice(
        default="claude-haiku-4-5-20251001",
        env_vars=("NOTES_EXTRACTION_MODEL",),
    ),
    AIFeatureKey.champion_profile_parse: ModelChoice(
        default="claude-haiku-4-5-20251001",
        env_vars=("CHAMPION_PROFILE_PARSE_MODEL",),
        rationale="Odczyt profili Championa; literał wiąże klucz cache promptu — patrz uwaga wyżej.",
    ),
    AIFeatureKey.cv_generator: ModelChoice(
        default="claude-sonnet-4-6",
        env_vars=("CV_B2B_MODEL",),
        fallbacks=("claude-opus-4-8",),
        rationale="Pin Sonnet 4.6 (rewert #628: Sonnet 5 z wymuszonym thinking daje słabsze CV). "
        "Fallback nadpisywalny env CV_B2B_FALLBACK_MODELS w provider.py.",
    ),
    AIFeatureKey.mindy_chat: ModelChoice(
        default="claude-sonnet-5",
        env_vars=("MINDY_MODEL",),
        settings_attr="CLAUDE_MODEL_CV",
        rationale="MINDY; honoruje legacy CLAUDE_MODEL_CV, MINDY_MODEL rozdziela od parsera CV.",
    ),
    AIFeatureKey.cv_rule_lint: ModelChoice(
        default="claude-haiku-4-5-20251001",
        env_vars=("CV_RULE_LINT_MODEL",),
        settings_attr="CLAUDE_MODEL_CV_BULK",
        rationale="Lint reguł CV; honoruje CLAUDE_MODEL_CV_BULK, CV_RULE_LINT_MODEL rozdziela od backfillu.",
    ),
    AIFeatureKey.uop_check: ModelChoice(
        default="claude-sonnet-5",
        env_vars=("UOP_CHECK_MODEL",),
    ),
    AIFeatureKey.cv_name_backfill: ModelChoice(
        default="claude-sonnet-5",
        env_vars=("CV_NAME_BACKFILL_MODEL",),
        settings_attr="CLAUDE_MODEL_CV",
        rationale="Sync imion z Traffita; deleguje do parse_cv (model CV), własny override na tańszy "
        "model dla ~57k wierszy bez ruszania parsera na wgraniu CV.",
    ),
}


def choice_for(feature: AIFeatureKey) -> ModelChoice:
    try:
        return _REGISTRY[feature]
    except KeyError as exc:  # pragma: no cover - strażnik przed cichym literałem
        raise KeyError(
            f"AIFeatureKey.{feature.value} nie ma wpisu w ai_models._REGISTRY — "
            "dodaj go zamiast wpisywać model literałem w miejscu wywołania."
        ) from exc


def model_for(feature: AIFeatureKey) -> str:
    """Efektywny model danej funkcji (env → settings → default)."""
    return choice_for(feature).resolve()[0]


def fallbacks_for(feature: AIFeatureKey) -> tuple[str, ...]:
    return choice_for(feature).fallbacks


def model_chain_for(feature: AIFeatureKey) -> list[str]:
    """[model, *fallbacki] z dedupem — gotowe pod ``call_claude(fallback_models=…)``."""
    primary = model_for(feature)
    chain = [primary]
    for m in fallbacks_for(feature):
        if m and m not in chain:
            chain.append(m)
    return chain


def registry_snapshot() -> dict[str, dict[str, object]]:
    """Migawka dla sondy zdrowia i panelu Ustawienia → AI."""
    out: dict[str, dict[str, object]] = {}
    for feature, choice in _REGISTRY.items():
        model, source = choice.resolve()
        out[feature.value] = {
            "model": model,
            "source": source,
            "fallbacks": list(choice.fallbacks),
        }
    return out
