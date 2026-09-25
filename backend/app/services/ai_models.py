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
| F5  | cv_interactive_chat              | gpt-6-luna (z Sonnet 5)  |
| F6  | job_description_generator        | claude-sonnet-5          |
| F7  | order_parser                     | gpt-6-luna (z Sonnet 5)  |
| F8  | uop_check                        | gpt-6-luna (z Sonnet 5)  |
| F9  | cv_parser                        | claude-sonnet-5          |
| F10 | cv_backfill + cv_name_backfill   | gpt-6-luna (z Sonnet 5)  |
| F11 | notes_extraction                 | gpt-6-luna (z Sonnet 5)  |
| F12 | candidate_summary                | gpt-6-luna (z Sonnet 5)  |
| F13 | champion_draft                   | gpt-6-luna (z Sonnet 5)  |
| F14 | cv_rule_lint                     | claude-sonnet-5 (z Haiku)|
| F15 | mindy_chat                       | gpt-6-luna (z Sonnet 5)  |
| F18 | cv_factual_verification          | gpt-6-luna (z Sonnet 5)  |
| F19 | jarvis                           | claude-sonnet-5 (z Haiku)|
| F20 | job_public_description           | claude-sonnet-5 (z Haiku)|
| F21 | screening_reassign_suggest       | gpt-6-luna (z Sonnet 5)  |
| F22 | dz_review                        | gpt-6-luna (z Sonnet 5)  |
| F23 | academy_screening                | gpt-6-luna (z Sonnet 5)  |
| F24 | prep_review                      | gpt-6-luna (z Sonnet 5)  |
| F16 | embeddingi (``VOYAGE_MODEL``)    | voyage-3 — config.py     |
| F17 | reranker (``RERANKER_ENABLED``)  | wyłączony — config.py    |

Luna to od 22.09.2026 GPT-6 Luna (``gpt-6-luna``, wydana tego dnia) zamiast
GPT-5.6 Luna, z której pochodzą liczby badania 16.09 — ta sama rodzina
i ten sam kształt żądania (``reasoning_effort=none``, JSON schema, ``store``),
dwa razy tańsze wejście i 2,4× tańsze wyjście. Powrót bez deployu: env
funkcji (np. ``CV_FACTUAL_VERIFICATION_MODEL=gpt-5.6-luna``).

Pomiar gpt-6-luna na przypadkach badania 16.09 (22.09.2026, harness
``/root/nexus-model-eval``, decyzja Artura tego dnia) przeniósł na Lunę 6 trzy
kolejne funkcje, w których wyszła na remis z dotychczasowym modelem: F7 odczyt
zamówień (błędy krytyczne 3,9% vs 4,7% Sonneta, 0 cichych), F12 podsumowanie
aktywności (96,7% poprawnych jak DeepSeek, dane zostają u dostawcy z DPA)
i F13 szkic Championa (recall 0,62 vs 0,60, precyzja 0,88 vs 0,90). Po nich
F10 masowe uzupełnianie pól i nazwisk z CV (wymyślone technologie 0,07 vs 0,08
Sonneta na CV, zła osoba 3,1% vs 6,3%).

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
GPT_LUNA = "gpt-6-luna"
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
        default=GPT_LUNA,
        env_vars=("CANDIDATE_SUMMARY_MODEL",),
        fallbacks=(SONNET_5,),
        rationale="F12. Podsumowanie aktywności: GPT-6 Luna 96,7% poprawnych, 0 wymyśleń — jak "
        "DeepSeek V4 Pro (pomiar 22.09), 8× taniej i bez wysyłki poza EOG. Sonnet 5 w badaniu "
        "16.09 nie oddał użytecznego podsumowania w 20% przypadków.",
    ),
    AIFeatureKey.champion_draft: ModelChoice(
        default=GPT_LUNA,
        env_vars=("CHAMPION_AI_MODEL",),
        fallbacks=(SONNET_5,),
        rationale="F13. Szkic Championa: GPT-6 Luna recall MUST 0,62 / precyzja 0,88 wobec "
        "0,60 / 0,90 Sonneta 5, 0 dopisanych pozycji u obu (pomiar 22.09), 28× taniej.",
    ),
    AIFeatureKey.order_parser: ModelChoice(
        default=GPT_LUNA,
        env_vars=("ORDER_PARSER_MODEL",),
        # settings_attr obok tego samego env: wierne odtworzenie oryginału
        # `os.environ.get("ORDER_PARSER_MODEL","") or settings.ORDER_PARSER_MODEL`.
        # env_vars (os.environ) wygrywa i zwykle to wystarcza; settings_attr
        # łapie wariant z pliku .env, który pydantic czyta, a os.environ nie widzi.
        settings_attr="ORDER_PARSER_MODEL",
        fallbacks=(SONNET_5,),
        rationale="F7. Odczyt PDF zamówień: GPT-6 Luna (decyzja Artura 22.09.2026). Na 127 "
        "zamówieniach badania: błędy krytyczne 3,9% vs 4,7% Sonneta 5, 0 cichych, trafność "
        "pól 0,960 vs 0,963, 34× taniej. 21.09 wróciliśmy z GPT-5.6 Luna na Sonneta, bo "
        "Luna 5.6 oznaczała poprawne odczyty Nordei jako niepewne bez powodu (2 z 6 do "
        "kolejki) — przy Lunie 6 obserwuj kolejkę Nordei.",
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
        default=GPT_LUNA,
        env_vars=("CV_BACKFILL_MODEL",),
        # Bez legacy CLAUDE_MODEL_CV_BULK od 22.09.2026: ta zmienna nadal steruje
        # lintem reguł i datami doświadczenia (Sonnet 5), a `settings_attr`
        # wygrywa z `default` — zostawiona zabrałaby tej funkcji Lunę.
        fallbacks=(SONNET_5,),
        rationale="F10. Masowy backfill pól: GPT-6 Luna (decyzja 22.09.2026 po pomiarze na 96 "
        "CV) — wymyślone technologie 0,07/CV vs 0,08 Sonneta 5, zła osoba 3,1% vs 6,3%, "
        "31× taniej. Przeciążenie OpenAI → model parsera CV (cv_parser._parse_with_claude).",
    ),
    AIFeatureKey.experience_dates_on_demand: ModelChoice(
        default=SONNET_5,
        env_vars=("EXPERIENCE_DATES_MODEL",),
        settings_attr="CLAUDE_MODEL_CV_BULK",
        rationale="Ta sama robota co F10 (odczyt CV), ale 22.09.2026 na Lunę 6 przeniesiono "
        "tylko cv_backfill i cv_name_backfill — ta ścieżka zostaje na Sonnecie 5 do decyzji. "
        "Osobny klucz jest po to, żeby dało się ją zgasić bez nocnego syncu.",
    ),
    AIFeatureKey.notes_extraction: ModelChoice(
        default=GPT_LUNA,
        env_vars=("NOTES_EXTRACTION_MODEL",),
        fallbacks=(SONNET_5,),
        rationale="F11. Od 25.09.2026 (decyzja Artura: bez DeepSeek, konto bez środków) "
        "GPT-6 Luna: 0.22 nieugruntowanych wartości na kandydata na prompcie v5 "
        "(60 przypadków, 0 błędów, 0.00055 USD) vs DeepSeek V4 Pro 0.15 i Sonnet 5 "
        "0.33 (22.09). Stawka PLN/h spoza notatek nie wchodzi do profilu "
        "(_drop_ungrounded_rate).",
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
    AIFeatureKey.screening_reassign_suggest: ModelChoice(
        default=GPT_LUNA,
        env_vars=("SCREENING_REASSIGN_MODEL",),
        fallbacks=(SONNET_5,),
        rationale="F21 (decyzja Artura 23.09.2026, POZA badaniem 16.09). Przepięcie: "
        "dopasowanie odpowiedzi z poprzedniego screeningu do pytań nowej rekrutacji to "
        "zadanie „znajdź i zacytuj” (jak F7/F8, które Luna wygrała). Wynik jest wyłącznie "
        "podpowiedzią — rekruter przyjmuje albo poprawia każdą odpowiedź.",
    ),
    AIFeatureKey.dz_review: ModelChoice(
        default=GPT_LUNA,
        env_vars=("DZ_REVIEW_MODEL",),
        fallbacks=(SONNET_5,),
        rationale="F22 (decyzja 23.09.2026, POZA badaniem 16.09). Podpowiedzi dla "
        "zatwierdzającego DZ to zadanie „znajdź i zacytuj” (must-have w CV, pogrubienia, "
        "pokrycie w rolach) — to samo, w czym Luna wygrała F7/F18; recenzent ma być innym "
        "modelem niż generator CV (F4 = Sonnet 5). Wynik doradczy, nigdy bramka.",
    ),
    AIFeatureKey.academy_screening: ModelChoice(
        default=GPT_LUNA,
        env_vars=("ACADEMY_SCREENING_MODEL",),
        fallbacks=(SONNET_5,),
        rationale="F23 (decyzja Artura 24.09.2026, POZA badaniem 16.09). Sortowanie "
        "zgłoszeń do akademii to odczyt dat edukacji i pracy oraz poziomu polskiego z CV "
        "z cytatem — to samo co F10 (Luna wybrana pomiarem 22.09). Liczbę lat i werdykt "
        "liczy kod; decyzję „nie” klika człowiek.",
    ),
    AIFeatureKey.prep_review: ModelChoice(
        default=GPT_LUNA,
        env_vars=("PREP_REVIEW_MODEL",),
        fallbacks=(SONNET_5,),
        rationale="F24 (decyzja Artura 23.09.2026, POZA badaniem 16.09). Ocena prepu "
        "z transkryptu Teams to „znajdź i zacytuj” (must-have i pytania klienta w "
        "rozmowie); cytat spoza transkryptu jest odrzucany, a poziom oceny liczy kod. "
        "Pomiar Luna vs Sonnet na pierwszych prawdziwych prepach: "
        "scripts/eval_prep_review.py. Wynik doradczy, nigdy bramka.",
    ),
    AIFeatureKey.cv_name_backfill: ModelChoice(
        default=GPT_LUNA,
        env_vars=("CV_NAME_BACKFILL_MODEL",),
        # Bez legacy CLAUDE_MODEL_CV od 22.09.2026 — ta zmienna steruje parserem CV
        # (Sonnet 5); patrz cv_backfill.
        fallbacks=(SONNET_5,),
        rationale="F10. Sync imion z Traffita; deleguje do parse_cv z własnym modelem. GPT-6 Luna "
        "jak cv_backfill (ten sam odczyt CV, pomiar 22.09.2026).",
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
