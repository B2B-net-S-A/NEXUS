"""Jedno miejsce, w którym widać: funkcja generatywna → model → skąd.

Do PR-a C11 model był ustalany w CZTERECH mechanizmach rozrzuconych po 13
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
fallbacków i listą env-override'ów. Dostawca wynika z NAZWY modelu
(``llm_providers.provider_of``): ``claude-*`` idzie przez SDK Anthropic,
``gpt-*`` do OpenAI, ``deepseek*`` do DeepSeek — tą samą pętlą ponowień
i fallbacków w ``claude_client.call_claude``.

Decyzja Artura z 16.09.2026 (badanie modeli na danych produkcyjnych,
``outputs/model-matrix-2026-09-15/RAPORT-KONCOWY.md``, identyfikatory F1–F17):

| ID  | funkcja                          | model                    |
|-----|----------------------------------|--------------------------|
| F1  | scoring                          | claude-sonnet-5          |
| F2  | champion_profile_parse           | claude-sonnet-5 (z Haiku)|
| F3  | cv_requirement_map               | claude-sonnet-5          |
| F4  | cv_generator                     | claude-sonnet-5 (z 4.6)  |
| F5  | cv_interactive_chat              | gpt-5.6-luna (z Haiku)   |
| F6  | job_description_generator        | claude-sonnet-5          |
| F7  | order_parser                     | claude-sonnet-5 (21.09)  |
| F8  | uop_check                        | gpt-5.6-luna             |
| F9  | cv_parser                        | claude-sonnet-5          |
| F10 | cv_backfill + cv_name_backfill   | claude-sonnet-5 (z Haiku)|
| F11 | notes_extraction                 | deepseek-v4-pro (z Haiku)|
| F12 | candidate_summary                | deepseek-v4-pro          |
| F13 | champion_draft                   | claude-sonnet-5          |
| F14 | cv_rule_lint                     | claude-sonnet-5 (z Haiku)|
| F15 | mindy_chat                       | gpt-5.6-luna             |
| F18 | cv_factual_verification          | gpt-5.6-luna (z Sonnet 5)|
| F19 | jarvis                           | claude-sonnet-5 (z Haiku)|
| F20 | job_public_description           | claude-sonnet-5 (z Haiku)|
| F16 | embeddingi (``VOYAGE_MODEL``)    | voyage-3 — config.py     |
| F17 | reranker (``RERANKER_ENABLED``)  | wyłączony — config.py    |

Funkcje na GPT/DeepSeek mają fallback na Sonneta 5: przeciążenie albo 429
u dostawcy nie zdejmuje funkcji. Brak klucza dostawcy to 401 NIEPONAWIALNE
— nie kaskaduje na Claude, żeby błąd konfiguracji był widoczny (także
w ``/api/health``: ``checks.openai`` / ``checks.deepseek``).

Rozwiązanie różnicy pustego env-a: Coolify wstrzykuje puste stringi
(``CV_B2B_MAX_RETRIES=""`` — patrz ``claude_client.env_number``), więc pusty
override jest traktowany jak brak, a nie jak model o nazwie ``""``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.core.config import settings
from app.models.ai_feature import AIFeatureKey
from app.services.llm_providers import ANTHROPIC, api_key_for, provider_of

SONNET_5 = "claude-sonnet-5"
GPT_LUNA = "gpt-5.6-luna"
DEEPSEEK_PRO = "deepseek-v4-pro"


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


# Uwaga: literał champion_profile_parse NIE wchodzi do klucza cache promptu
# (`PARSER_VERSION` w champion_profile_ingest jest niezależny od modelu), ale
# zmiana modelu zmienia WYNIKI parsowania — bump wersji parsera przy zmianie.
_REGISTRY: dict[AIFeatureKey, ModelChoice] = {
    AIFeatureKey.scoring: ModelChoice(
        default=SONNET_5,
        env_vars=("MATCH_SCORING_MODEL",),
        rationale="F1. Uzasadnienie dopasowania (LLM); sam ranking jest deterministyczny. "
        "Badanie 16.09: pokrycie brakujących wymagań 0.53 vs 0.32 (Haiku), 0.19 (Luna).",
    ),
    AIFeatureKey.job_description_generator: ModelChoice(
        default=SONNET_5,
        env_vars=("JOB_WRITER_MODEL",),
        rationale="F6. Generator ogłoszeń; jedyny model z językiem OK w 100% (badanie 16.09).",
    ),
    AIFeatureKey.cv_parser: ModelChoice(
        default=SONNET_5,
        env_vars=("CV_PARSER_MODEL",),
        settings_attr="CLAUDE_MODEL_CV",
        rationale="F9. Parser CV; honoruje legacy CLAUDE_MODEL_CV, CV_PARSER_MODEL rozdziela "
        "go od reszty. Badanie 16.09: najmniej wymyślonych faktów (0.063).",
    ),
    AIFeatureKey.candidate_summary: ModelChoice(
        default=DEEPSEEK_PRO,
        env_vars=("CANDIDATE_SUMMARY_MODEL",),
        fallbacks=(SONNET_5,),
        rationale="F12. Podsumowanie aktywności: DeepSeek V4 Pro 3% błędów vs 20% u Sonneta 5 "
        "(badanie 16.09); dane produkcyjne do DeepSeek za zgodą Artura z 16.09.",
    ),
    AIFeatureKey.champion_draft: ModelChoice(
        default=SONNET_5,
        env_vars=("CHAMPION_AI_MODEL",),
        rationale="F13. Szkic Championa: najmniej nieugruntowanych pozycji (0.10).",
    ),
    AIFeatureKey.order_parser: ModelChoice(
        default=SONNET_5,
        env_vars=("ORDER_PARSER_MODEL",),
        # settings_attr obok tego samego env: wierne odtworzenie oryginału
        # `os.environ.get("ORDER_PARSER_MODEL","") or settings.ORDER_PARSER_MODEL`.
        # env_vars (os.environ) wygrywa i zwykle to wystarcza; settings_attr
        # łapie wariant z pliku .env, który pydantic czyta, a os.environ nie widzi.
        settings_attr="ORDER_PARSER_MODEL",
        rationale="F7. Odczyt PDF zamówień: Sonnet 5 (decyzja Artura 21.09.2026, powrót "
        "z GPT Luna). Luna czytała wartości poprawnie, ale oznaczała odczyt jako "
        "niepewny bez konkretnego powodu, więc zamówienia Nordei szły do kolejki "
        "zamiast zapisu automatycznego (2 z 6 po 16.09). Badanie 16.09 i tak "
        "zalecało zostawić tę funkcję na Sonnecie.",
    ),
    AIFeatureKey.cv_requirement_map: ModelChoice(
        default=SONNET_5,
        env_vars=("CV_REQUIREMENT_MAP_MODEL",),
        rationale="F3. Mapa wymagań: zgodność 0.944, najmniej zgubionych dowodów.",
    ),
    AIFeatureKey.cv_interactive_chat: ModelChoice(
        default=GPT_LUNA,
        env_vars=("CV_INTERACTIVE_CHAT_MODEL",),
        fallbacks=(SONNET_5,),
        rationale="F5. Czat publicznego CV: wszystkie modele 1.0 na odmowach — decyduje "
        "cena i umowa powierzenia (OpenAI).",
    ),
    AIFeatureKey.cv_backfill: ModelChoice(
        default=SONNET_5,
        env_vars=("CV_BACKFILL_MODEL",),
        settings_attr="CLAUDE_MODEL_CV_BULK",
        rationale="F10. Masowy backfill pól; honoruje CLAUDE_MODEL_CV_BULK (od 16.09 = Sonnet 5), "
        "CV_BACKFILL_MODEL rozdziela od lintu. Haiku wymyślał fakty w 31% CV vs 8%.",
    ),
    AIFeatureKey.experience_dates_on_demand: ModelChoice(
        default=SONNET_5,
        env_vars=("EXPERIENCE_DATES_MODEL",),
        settings_attr="CLAUDE_MODEL_CV_BULK",
        rationale="Ta sama robota co F10 (odczyt CV), więc ten sam model — "
        "osobny klucz jest po to, żeby dało się ją zgasić bez nocnego syncu.",
    ),
    AIFeatureKey.notes_extraction: ModelChoice(
        default=DEEPSEEK_PRO,
        env_vars=("NOTES_EXTRACTION_MODEL",),
        fallbacks=(SONNET_5,),
        rationale="F11. Fakty z notatek: DeepSeek V4 Pro 0.15 nieugruntowanych vs 0.56 "
        "u Haiku i 0.33 u Sonneta 5 (badanie 16.09).",
    ),
    AIFeatureKey.champion_profile_parse: ModelChoice(
        default=SONNET_5,
        env_vars=("CHAMPION_PROFILE_PARSE_MODEL",),
        rationale="F2. Odczyt profili Championa: Sonnet 5 recall 0.955 przy 0.05 wymyślonych; "
        "Haiku bez stacku wymyślał 82% pozycji (badanie 16.09).",
    ),
    AIFeatureKey.cv_generator: ModelChoice(
        default=SONNET_5,
        env_vars=("CV_B2B_MODEL",),
        fallbacks=("claude-opus-4-8",),
        rationale="F4. Generator CV: Sonnet 5 z thinking=disabled (jak w badaniu) wymyślał "
        "fakty w 20% CV vs 41% u Sonneta 4.6 (rewert #628 mierzył wymuszone thinking). "
        "Fallback nadpisywalny env CV_B2B_FALLBACK_MODELS w provider.py.",
    ),
    AIFeatureKey.mindy_chat: ModelChoice(
        default=GPT_LUNA,
        env_vars=("MINDY_MODEL",),
        # Bez legacy CLAUDE_MODEL_CV: od 16.09 MINDY ma własny model (GPT Luna),
        # a stara zmienna wiązała ją z parserem CV — dokładnie sprzężenie z C11.
        fallbacks=(SONNET_5,),
        rationale="F15. MINDY: wszystkie modele 1.0 — decyduje cena; MINDY_MODEL to jedyny override.",
    ),
    AIFeatureKey.cv_rule_lint: ModelChoice(
        default=SONNET_5,
        env_vars=("CV_RULE_LINT_MODEL",),
        settings_attr="CLAUDE_MODEL_CV_BULK",
        rationale="F14. Lint reguł CV; honoruje CLAUDE_MODEL_CV_BULK, CV_RULE_LINT_MODEL "
        "rozdziela od backfillu.",
    ),
    AIFeatureKey.uop_check: ModelChoice(
        default=GPT_LUNA,
        env_vars=("UOP_CHECK_MODEL",),
        fallbacks=(SONNET_5,),
        rationale="F8. Znamiona UoP: GPT Luna 100% nazewnictwa, recall 1.0 na podłożonych "
        "znamionach (badanie 16.09).",
    ),
    AIFeatureKey.cv_factual_verification: ModelChoice(
        default=GPT_LUNA,
        env_vars=("CV_FACTUAL_VERIFICATION_MODEL",),
        fallbacks=(SONNET_5,),
        rationale="F18 (decyzja 18.09.2026, POZA badaniem 16.09). Recenzent gotowego CV "
        "MUSI być innym modelem niż generator (F4 = Sonnet 5): badanie zmierzyło, że sędzia "
        "LLM faworyzuje własne wyjście (~+30 pkt), więc kontrola własnej pracy jest "
        "systematycznie za łagodna. Luna wygrała F7/F8 — zadania „znajdź i zacytuj”, czyli "
        "dokładnie to, co robi weryfikator.",
    ),
    AIFeatureKey.jarvis: ModelChoice(
        default=SONNET_5,
        env_vars=("JARVIS_MODEL",),
        # WYŁĄCZNIE Anthropic: pętla agenta wysyła `tools`, a
        # `llm_providers._UNSUPPORTED_KWARGS` odrzuca je dla GPT/DeepSeek
        # nieponawialnym ValueError — fallback na innego dostawcę zabiłby łańcuch.
        fallbacks=("claude-haiku-4-5",),
        rationale="F19 (decyzja 21.09.2026, POZA badaniem 16.09). Jarvis wymaga tool-use, "
        "który w NEXUSIE obsługuje tylko dostawca Anthropic; Sonnet 5 jak reszta funkcji "
        "rozumujących, Haiku jako tańszy fallback przy przeciążeniu.",
    ),
    AIFeatureKey.job_public_description: ModelChoice(
        default=SONNET_5,
        env_vars=("JOB_PUBLIC_DESCRIPTION_MODEL",),
        fallbacks=("claude-haiku-4-5",),
        rationale="F20 (decyzja 21.09.2026, POZA badaniem 16.09). Publiczny opis rekrutacji "
        "na stronę kariery to ta sama robota co F6 (generator ogłoszeń), a tam Sonnet 5 był "
        "jedynym modelem z językiem OK w 100%. Tekst i tak przechodzi deterministyczną "
        "kontrolę (klient, kwoty, kontakty) i zatwierdzenie człowieka.",
    ),
    AIFeatureKey.cv_name_backfill: ModelChoice(
        default=SONNET_5,
        env_vars=("CV_NAME_BACKFILL_MODEL",),
        settings_attr="CLAUDE_MODEL_CV",
        rationale="F10. Sync imion z Traffita; deleguje do parse_cv (model CV), własny override "
        "dla ~57k wierszy bez ruszania parsera na wgraniu CV.",
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


def providers_in_use() -> list[str]:
    """Dostawcy spoza Anthropic, do których prowadzi dziś rejestr (model
    podstawowy albo fallback) — dla sondy kluczy w ``/api/health``."""
    found = {provider_of(m) for feature in _REGISTRY for m in model_chain_for(feature)}
    found.discard(ANTHROPIC)
    return sorted(found)


def registry_snapshot() -> dict[str, dict[str, object]]:
    """Migawka dla sondy zdrowia i panelu Ustawienia → AI."""
    out: dict[str, dict[str, object]] = {}
    for feature, choice in _REGISTRY.items():
        model, source = choice.resolve()
        provider = provider_of(model)
        out[feature.value] = {
            "model": model,
            "source": source,
            "provider": provider,
            "key_configured": bool(api_key_for(provider)),
            "fallbacks": list(choice.fallbacks),
        }
    return out
