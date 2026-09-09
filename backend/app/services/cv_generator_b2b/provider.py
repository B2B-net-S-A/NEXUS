"""Polityka wywołań modelu dla generatora CV B2B — na wspólnym kliencie.

Następca ``ai_client.py``. Tamten budował ``anthropic.Anthropic(...)`` wprost,
przez co omijał NARAZ cztery rzeczy: jawny timeout wspólnego klienta, jego
backoff, telemetrię zdrowia dostawcy i bramkę kwot. Był jedynym wpisem na
``_RAW_CLIENT_BASELINE`` i to on trzymał tę listę przy życiu.

Co zostaje tutaj, a nie idzie do `claude_client`: **strojenie konkretnego
produktu**. Generator CV ma własny model, własny łańcuch fallbacku, własny
limit tokenów i własne typy błędów, na które mapuje go warstwa wyżej. Wspólny
klient dostał MECHANIZMY (łańcuch, cache promptu, wykrywanie ucięcia); wartości
są decyzją tego produktu i mieszkają razem z nim.

Typy wyjątków zachowane co do nazwy CELOWO: trzej konsumenci mapują je na
własne kody błędów (`standalone_service` na trzy różne `StandaloneGenerationError`),
więc przemianowanie ich zamieniłoby migrację stosu w zmianę zachowania trzech
powierzchni użytkownika naraz.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import fallbacks_for, model_for
from app.services.claude_client import (
    ClaudeError,
    ClaudeOverloaded,
    ClaudeTruncated,
    call_claude_text,
    env_number,
)

logger = logging.getLogger(__name__)


# Rewert #628 (sonnet-5): fala feedbacku od rekruterów — jakość CV wyraźnie
# spadła. Sonnet 5 z wymuszonym thinking=disabled (konieczne, bo jego adaptive
# thinking zjadał budżet max_tokens — #630/#632) generuje słabsze CV niż
# Sonnet 4.6 w swoim naturalnym trybie. Ewentualny powrót na Sonnet 5 wymaga
# CV_B2B_THINKING=adaptive + CV_B2B_MAX_TOKENS>=24576 i porównania jakości.
#
# TO NIE JEST DOMYŚLNA WARTOŚĆ Z PRZYPADKU — to zmierzona decyzja jakościowa.
# Model i fallback żyją w rejestrze (ai_models.AIFeatureKey.cv_generator) — jedno
# miejsce prawdy dla wszystkich 16 funkcji; tu zostaje env-owe warstwowanie
# (CV_B2B_MODEL / CV_B2B_FALLBACK_MODELS) specyficzne dla tej ścieżki.
# 8192 → 16384: gęste CV (długi staż, wiele ról, rozbudowane obowiązki)
# przekraczały 8192 tokeny outputu i ucinały JSON. 16384 daje 2× zapasu, a przy
# ekstrakcji strukturalnej płaci się za realnie wygenerowane tokeny, więc
# normalne CV nie drożeją. Mieści się pod capem outputu modelu fallbackowego.
_DEFAULT_MAX_TOKENS = 16384
_DEFAULT_MAX_RETRIES = 3
# Sufit per żądanie. Domyślka SDK to 600 s — o wiele za dużo dla wywołania
# biegnącego synchronicznie w slocie threadpoola FastAPI.
_DEFAULT_REQUEST_TIMEOUT = 120.0

PROMPT_NAME = "cv_b2b_extraction"
# v3 (2026-06-11): poufność notatek (stawki/red flagi), kwantyfikacja, zwięzłość
# starszych ról, tytuł pod ofertę, kanoniczna pisownia tech, kontekst projektu,
# higiena dat edukacji/luk.
# v4 (2026-06-11): limit 12 technologii per rola (priorytet must/nice klienta).
# v5 (2026-07-01): wierność obowiązków — zakaz rozdmuchiwania zakresu (klienci/
# domeny/usługi/integracje), Profil Championa i notatki tylko jako pozycjonowanie.
# v6 (2026-07-13): Profil Championa (MUST/NICE) rozróżnia technologie od
# metodyk/kompetencji/ról/języków.
# v7 (2026-07-29): trzy tryby obróbki treści (basic/polished/tailored) jako
# addendum do promptu bazowego; kwoty wymuszające wypełniacz zamienione na
# górne limity — przy ubogim CV model zwraca tyle, ile jest w źródle.
PROMPT_VERSION = 7


class CVGeneratorAIError(RuntimeError):
    """Wywołanie modelu nie powiodło się po wyczerpaniu prób."""


class CVGeneratorTruncatedError(CVGeneratorAIError):
    """Odpowiedź ucięta limitem max_tokens."""


class CVGeneratorOverloadedError(CVGeneratorAIError):
    """Każdy model w łańcuchu pozostał przeciążony — awaria PRZEJŚCIOWA.

    Osobny typ, bo niesie komunikat, który operator ma zobaczyć: „spróbuj za
    chwilę", nie surowy słownik błędu API.
    """


def _model() -> str:
    return model_for(AIFeatureKey.cv_generator)


def _fallback_models() -> list[str]:
    raw = os.environ.get("CV_B2B_FALLBACK_MODELS")
    if raw is None:
        return list(fallbacks_for(AIFeatureKey.cv_generator))
    return [m.strip() for m in raw.split(",") if m.strip()]


def _thinking_param() -> dict[str, str] | None:
    """Konfiguracja extended thinking dla ekstrakcji.

    Dla ``claude-sonnet-4-6`` ``disabled`` jest no-opem — thinking i tak jest
    tam domyślnie wyłączony. Pin ma znaczenie, gdy przez ``CV_B2B_MODEL``
    wybrany zostanie model Claude 5: tam adaptive thinking działa domyślnie,
    a jego tokeny liczą się do ``max_tokens`` i wypychają JSON CV.

    ``None`` znaczy „oddaj decyzję modelowi" i wspólny klient pomija wtedy
    parametr — ta sama semantyka co dotąd.
    """
    mode = os.environ.get("CV_B2B_THINKING", "disabled").strip().lower()
    if mode in ("adaptive", "on", "true", "1", "enabled", "default"):
        return None
    return {"type": "disabled"}


def _api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        from app.core.config import settings

        return settings.ANTHROPIC_API_KEY or None
    except Exception:  # noqa: BLE001 — config nie może wywrócić klienta
        return None


def analyze_with_ai(
    content: str,
    request_id: str,
    system: str | None = None,
    *,
    model_override: str | None = None,
    response_schema: dict[str, Any] | None = None,
) -> str:
    """Zawołaj model i zwróć tekst odpowiedzi. Sygnatura bez zmian.

    Args:
        content: wiadomość użytkownika (dane kandydata w ogranicznikach).
        request_id: korelacja w logach.
        system: prompt instrukcyjny; leci przez ``system`` z oznaczeniem do
            cache'owania, żeby statyczne instrukcje nie były opłacane przy
            każdej generacji.
        model_override: inny model podstawowy dla wołającego spoza generatora
            CV (analiza UoP, lint reguł). Łańcuch fallbacku zostaje wspólny,
            ale wołający nie dziedziczy modelu przypiętego pod jakość CV.

    Raises:
        CVGeneratorTruncatedError: odpowiedź ucięta limitem tokenów.
        CVGeneratorOverloadedError: każdy model w łańcuchu przeciążony.
        CVGeneratorAIError: brak klucza albo błąd 4xx (żądanie/konfiguracja).
    """
    api_key = _api_key()
    if not api_key:
        raise CVGeneratorAIError("ANTHROPIC_API_KEY env var is not set")

    primary = model_override or _model()
    fallbacks = _fallback_models()
    if not primary:
        raise CVGeneratorAIError(
            "Brak skonfigurowanego modelu Claude (CV_B2B_MODEL jest pusty)."
        )

    max_tokens = env_number("CV_B2B_MAX_TOKENS", _DEFAULT_MAX_TOKENS, int)
    start = time.time()
    logger.info(
        "[cv_b2b][%s] start model=%s fallbacki=%s prompt=%s/v%d",
        request_id,
        primary,
        fallbacks,
        PROMPT_NAME,
        PROMPT_VERSION,
    )

    kwargs: dict[str, Any] = {}
    if system:
        kwargs["system"] = system
        kwargs["cache_system"] = True
    if response_schema is not None:
        kwargs["output_config"] = {
            "format": {"type": "json_schema", "schema": response_schema}
        }

    try:
        text = call_claude_text(
            messages=[{"role": "user", "content": content}],
            model=primary,
            fallback_models=fallbacks,
            max_tokens=max_tokens,
            api_key=api_key,
            timeout=env_number(
                "CV_B2B_REQUEST_TIMEOUT", _DEFAULT_REQUEST_TIMEOUT, float
            ),
            max_retries=env_number("CV_B2B_MAX_RETRIES", _DEFAULT_MAX_RETRIES, int),
            thinking=_thinking_param(),
            # Ucięcie MA tu rzucać: `standalone_service` mapuje je na własny
            # kod błędu, a cicha, ucięta odpowiedź trafiłaby dalej jako
            # „nieprawidłowy JSON" i wysłała diagnozę w złą stronę.
            raise_on_truncation=True,
            **kwargs,
        )
    except ClaudeTruncated as exc:
        raise CVGeneratorTruncatedError(str(exc)) from exc
    except ClaudeOverloaded as exc:
        raise CVGeneratorOverloadedError(
            "Usługa AI (Claude) jest chwilowo przeciążona. "
            "Spróbuj wygenerować CV ponownie za chwilę."
        ) from exc
    except ClaudeError as exc:
        raise CVGeneratorAIError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surowy błąd SDK (4xx, brak sieci)
        raise CVGeneratorAIError(f"Claude call failed: {exc}") from exc

    logger.info(
        "[cv_b2b][%s] sukces w %dms (model=%s)",
        request_id,
        int((time.time() - start) * 1000),
        primary,
    )
    return text
