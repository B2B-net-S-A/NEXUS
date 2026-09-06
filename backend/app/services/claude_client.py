"""Shared, resilient Claude (Anthropic) call helper.

Centralises the timeout + transient-retry policy that previously lived only in
``cv_generator_b2b/ai_client.py`` (the CV-B2B generator). The other request-path
Claude callers — ``match_justification_service``, ``champion_draft_service`` and
``dynareporter_mindy`` — used to construct ``anthropic.Anthropic(api_key)`` with
the SDK's **600 s default timeout** and **no retry**, so a hung provider pinned a
threadpool slot for ten minutes and a single transient 429/529 turned into a hard
502 with no degraded mode.

Design — deliberately ADDITIVE and behaviour-preserving:

* ``call_claude()`` returns the *same* ``anthropic.types.Message`` that
  ``client.messages.create()`` returns, so each caller's existing response
  parsing (concatenating text blocks, ``stop_reason`` checks, ``usage`` logging)
  is unchanged.
* On the success path it does exactly one ``messages.create`` — identical to the
  old code, only with an explicit per-request timeout.
* It re-raises the underlying error once the retry budget is exhausted, so each
  caller's existing ``except`` / fallback / error-status mapping still fires.

The function is synchronous (it uses ``time.sleep`` for backoff) and MUST be run
off the event loop — callers invoke it via ``starlette.concurrency.run_in_threadpool``,
so the blocking sleep occupies a worker thread, never the single-worker loop.
"""

from __future__ import annotations

import logging
import random
import time
import traceback
from collections.abc import Sequence
from typing import Any

import anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)

# Backoff schedule for transient failures: min(cap, base * 2**attempt) + jitter.
# Mirrors the proven cv_generator_b2b/ai_client.py policy.
_BACKOFF_BASE = 1.0
_BACKOFF_CAP = 8.0
_BACKOFF_JITTER = 0.5


def is_retryable_anthropic_error(err: BaseException) -> bool:
    """Return True for overloaded / rate-limited / 5xx / connection / timeout errors.

    A 4xx request/config error (bad key, malformed request) is NOT retryable —
    every attempt would fail identically — so it surfaces immediately.
    """
    status = getattr(err, "status_code", None)
    if status is None:
        response = getattr(err, "response", None)
        if response is not None:
            status = getattr(response, "status_code", None)

    err_type = ""
    body = getattr(err, "body", None)
    if isinstance(body, dict):
        err_obj = body.get("error") or {}
        if isinstance(err_obj, dict):
            err_type = err_obj.get("type", "")
    if not err_type:
        err_type = getattr(err, "type", "") or ""

    if status in (429, 529):
        return True
    if err_type in ("overloaded_error", "rate_limit_error"):
        return True
    if (
        isinstance(err, anthropic.APIStatusError)
        and status
        and 500 <= int(status) < 600
    ):
        return True
    if isinstance(err, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return True
    return False


class ClaudeError(RuntimeError):
    """Wywołanie modelu nie dało użytecznego wyniku.

    Wspólny przodek, żeby wołający mógł złapać całą rodzinę jednym `except`.
    Nie zastępuje surowych wyjątków SDK: pojedynczy model dalej re-raise'uje
    to, co przyszło od dostawcy (patrz `call_claude`), bo dziesięć istniejących
    miejsc wywołania mapuje te typy na własne kody błędów.
    """


class ClaudeTruncated(ClaudeError):
    """Odpowiedź ucięta limitem `max_tokens` (`stop_reason=max_tokens`).

    Problem DŁUGOŚCI TREŚCI, nie kondycji dostawcy — identyczny na każdym
    modelu, więc nigdy nie uruchamia fallbacku ani ponowienia.
    """


class ClaudeOverloaded(ClaudeError):
    """Każdy model w łańcuchu pozostał przeciążony/niedostępny.

    Rzucane WYŁĄCZNIE gdy łańcuch miał więcej niż jeden model — przy
    pojedynczym modelu (dzisiejsze zachowanie wszystkich wołających)
    re-raise'ujemy surowy wyjątek SDK, bo na nim stoi ich obsługa błędów
    i dwa testy w `test_claude_client.py`.
    """


def env_number(name: str, default: float, cast):
    """Liczba ze zmiennej środowiskowej, odporna na pustą wartość i śmieci.

    `os.environ.get(name, str(default))` zwraca `""`, gdy klucz JEST ustawiony,
    ale pusty — a `int("")` rzuca. Literówka operatora w Coolify (np.
    `CV_B2B_MAX_RETRIES=`) nie może kończyć się gołym 500 w generacji CV.
    Przeniesione z `cv_generator_b2b/ai_client.py` razem z resztą jego polityki.
    """
    import os

    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return cast(default)
    try:
        return cast(raw)
    except (TypeError, ValueError):
        logger.warning(
            "[claude_client] nieprawidłowe %s=%r — biorę domyślne %s",
            name,
            raw,
            default,
        )
        return cast(default)


def text_of(message: Any) -> str:
    """Skleja WSZYSTKIE bloki tekstowe odpowiedzi.

    Modele Claude 5 potrafią zacząć od bloku innego niż tekstowy (thinking),
    więc `content[0].text` bywa pusty — objawiało się to niżej jako mylące
    „nieprawidłowy JSON (znak 0)". Ten sam idiom był skopiowany w siedmiu
    miejscach; tutaj jest raz.
    """
    return "".join(
        getattr(block, "text", "") or ""
        for block in (getattr(message, "content", None) or [])
        if hasattr(block, "text")
    )


def _model_chain(model: str, fallback_models: Sequence[str] | None) -> list[str]:
    """[model, *fallbacki] bez duplikatów, z zachowaniem kolejności."""
    ordered = [model, *(fallback_models or ())]
    seen: set[str] = set()
    chain: list[str] = []
    for name in ordered:
        if name and name not in seen:
            seen.add(name)
            chain.append(name)
    return chain


def _apply_thinking_default(kwargs: dict[str, Any]) -> None:
    """Domyślnie wyłącz extended thinking; `thinking=None` znaczy „nie pinuj".

    Tokeny thinking liczą się do `max_tokens` i wypychają właściwą odpowiedź,
    co objawia się jako `stop_reason=max_tokens` na treści, która sama w sobie
    by się zmieściła. Dwunastu wołających pinowało to u siebie, a MINDY —
    jedyny, który tego nie robił — miała przez to 400/800 tokenów bez rezerwy.
    Domyślna wartość TUTAJ likwiduje dwanaście kopii i zamyka tę lukę.
    """
    if "thinking" not in kwargs:
        kwargs["thinking"] = {"type": "disabled"}
    elif kwargs["thinking"] is None:
        # Jawne „oddaj decyzję modelowi" — parametr pomijamy w wywołaniu.
        kwargs.pop("thinking")


def _apply_system_cache(kwargs: dict[str, Any]) -> None:
    """Oznacz prompt systemowy do cache'owania (`cache_control: ephemeral`).

    Statyczne instrukcje bywają dłuższe niż dane, a płaci się za nie przy
    każdym wywołaniu. Do tej pory robił to wyłącznie generator CV.
    """
    system = kwargs.get("system")
    if isinstance(system, str) and system.strip():
        kwargs["system"] = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]


def _record_health(started: float, *, failed: bool) -> None:
    """Feed the call outcome into the Claude circuit breaker (never raises)."""
    try:
        from app.services.ai_health import record_provider_call

        record_provider_call("claude", int((time.monotonic() - started) * 1000), failed)
    except Exception:  # noqa: BLE001 — health telemetry must not break a call
        pass


def _record_tokens(message: Any) -> None:
    """Dolicz tokeny udanego wywołania do zadeklarowanej operacji (nigdy nie rzuca).

    Granica dostawcy jest jedynym miejscem, które WIDZI `message.usage` dla
    każdego wołającego naraz — instrumentowanie ich pojedynczo zostawiłoby
    dziury dokładnie tam, gdzie nikt nie pamiętał (dziś usage idzie do logu
    w czterech serwisach i do nikąd w pozostałych).
    """
    try:
        from app.services.ai_quota import record_token_usage

        usage = getattr(message, "usage", None)
        if usage is None:
            return
        record_token_usage(
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
    except Exception:  # noqa: BLE001 — telemetria nie może wywrócić wywołania
        pass


def _assert_declared(model: str) -> None:
    """Refuse (or at least log) an LLM call nobody charged a quota for.

    The gate cannot live on the route: `fireflies_sync` is a background loop,
    CV enrichment is a BackgroundTask and `enrich_from_call` is a webhook —
    none of them is a request handler, and all three reached Claude without a
    quota check while every *handler* looked correctly wrapped. Standing here,
    at the provider boundary, is the only position that sees all of them.
    """
    try:
        from app.core.config import settings
        from app.services.ai_quota import AIQuotaUngated, current_ai_call

        if current_ai_call() is not None:
            return
        if getattr(settings, "AI_QUOTA_STRICT", False):
            raise AIQuotaUngated(
                f"LLM call (model={model}) outside `async with ai_feature(...)` — "
                "it would spend money the quota system cannot see"
            )
        # `warning`, not `error`, on purpose. This branch only runs while
        # AI_QUOTA_STRICT is off — the deliberate log-only observation cycle. With
        # LoggingIntegration every `error` becomes a Sentry event, so a single
        # forgotten call site would emit one per invocation and bury real errors
        # for the whole window. Under STRICT the call raises instead of logging.
        logger.warning(
            "[ai-quota] UNGATED LLM call model=%s — not wrapped in "
            "`async with ai_feature(...)`; invisible to the master toggle, the "
            "monthly limit and ai_usage_log. Stack: %s",
            model,
            "".join(traceback.format_stack(limit=8)),
        )
    except ImportError:  # pragma: no cover — keeps the client importable alone
        return


class _ModelExhausted(Exception):
    """Wewnętrzne: jeden model wyczerpał swój budżet ponowień.

    `retryable` niesie charakter OSTATNIEGO błędu, bo to on rozstrzyga, czy
    warto schodzić na kolejny model: przeciążenie jest per-pula modelu, a błąd
    4xx (zły klucz, zła nazwa modelu) każdy model odrzuci tak samo.
    """

    def __init__(self, cause: BaseException | None, retryable: bool) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.retryable = retryable


def _call_one_model(
    client: anthropic.Anthropic,
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    retries: int,
    raise_on_truncation: bool,
    started: float,
    kwargs: dict[str, Any],
) -> anthropic.types.Message:
    """Jeden model z pełnym budżetem ponowień. Rzuca `_ModelExhausted`."""
    last_err: BaseException | None = None
    last_retryable = False

    for attempt in range(retries + 1):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                **kwargs,
            )
            # Ucięcie to NIE awaria dostawcy: wywołanie WRÓCIŁO i zostało
            # opłacone. Zaliczenie go jako porażki otwierałoby circuit breaker
            # na zdrowym Claude, a pominięcie tokenów zaniżałoby rachunek
            # dokładnie tam, gdzie zużyto ich najwięcej.
            _record_health(started, failed=False)
            _record_tokens(message)

            if getattr(message, "stop_reason", None) == "max_tokens":
                # Logujemy ZAWSZE, rzucamy tylko na życzenie. Trzy ścieżki
                # (`notes_insights_extractor`, parser profili Championa,
                # generator CV) mają własną naprawę uciętego JSON-a i działa
                # ona dziś — bezwarunkowy wyjątek zamieniłby tę naprawę
                # w martwy kod, a odzyskiwalny wynik w błąd.
                logger.warning(
                    "[claude_client] odpowiedź ucięta limitem %s tokenów "
                    "(model=%s, stop_reason=max_tokens)",
                    max_tokens,
                    model,
                )
                if raise_on_truncation:
                    raise ClaudeTruncated(
                        f"Odpowiedź modelu została ucięta limitem {max_tokens} "
                        f"tokenów (model={model})."
                    )
            return message
        except ClaudeTruncated:
            raise  # długość treści — identyczna na każdym modelu, bez fallbacku
        except BaseException as err:  # noqa: BLE001 — klasyfikuj, potem re-raise
            last_err = err
            last_retryable = is_retryable_anthropic_error(err)
            logger.warning(
                "[claude_client] próba %d/%d model=%s nieudana: %s (ponawialny=%s)",
                attempt + 1,
                retries + 1,
                model,
                err,
                last_retryable,
            )
            if attempt >= retries or not last_retryable:
                break
            delay = min(_BACKOFF_CAP, _BACKOFF_BASE * (2**attempt)) + random.uniform(
                0, _BACKOFF_JITTER
            )
            time.sleep(delay)

    raise _ModelExhausted(last_err, last_retryable)


def call_claude(
    *,
    messages: list[dict[str, Any]],
    model: str,
    max_tokens: int,
    api_key: str | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
    fallback_models: Sequence[str] | None = None,
    cache_system: bool = False,
    raise_on_truncation: bool = False,
    **kwargs: Any,
) -> anthropic.types.Message:
    """Wywołaj model z jawnym timeoutem, ponowieniami i (opcjonalnie) fallbackiem.

    Zwraca surowy ``Message`` — tak jak ``client.messages.create`` — więc
    dziesięć istniejących miejsc wywołania parsuje odpowiedź bez zmian.

    Args:
        messages: lista wiadomości (przekazywana bez zmian).
        model: podstawowy model.
        max_tokens: limit tokenów odpowiedzi.
        api_key: nadpisuje ``settings.ANTHROPIC_API_KEY``, gdy wołający sam
            rozwiązuje klucz (np. honorując też starsze ``CLAUDE_API_KEY``).
        timeout: sufit per żądanie; domyślnie ``ANTHROPIC_TIMEOUT_SECONDS``.
        max_retries: dodatkowe próby po pierwszej; domyślnie
            ``ANTHROPIC_MAX_RETRIES``.
        fallback_models: modele próbowane po ``model``, gdy ten pozostaje
            PRZECIĄŻONY. Przeciążenie (529) jest per-pula modelu, więc zejście
            na inną rodzinę ratuje generację, zamiast wywalać ją w całości.
            Błąd 4xx nie kaskaduje — każdy model odrzuciłby go tak samo.
        cache_system: oznacz prompt systemowy do cache'owania.
        raise_on_truncation: zamień ``stop_reason=max_tokens`` w
            ``ClaudeTruncated``. Domyślnie ``False``, bo trzy ścieżki mają
            własną naprawę uciętego JSON-a — patrz `_call_one_model`.
        **kwargs: przekazywane wprost do ``messages.create`` (``system``,
            ``temperature``, ``thinking``…). ``thinking`` domyślnie
            ``{"type": "disabled"}``; ``thinking=None`` pomija parametr.
    """
    _assert_declared(model)

    key = api_key if api_key is not None else settings.ANTHROPIC_API_KEY
    request_timeout = (
        timeout if timeout is not None else settings.ANTHROPIC_TIMEOUT_SECONDS
    )
    retries = max_retries if max_retries is not None else settings.ANTHROPIC_MAX_RETRIES

    _apply_thinking_default(kwargs)
    if cache_system:
        _apply_system_cache(kwargs)

    # max_retries=0 — własna polityka SDK jest wyłączona, żeby nie nakładała
    # się na backoff niżej; jawny timeout ucina zawieszoną próbę.
    client = anthropic.Anthropic(api_key=key, max_retries=0, timeout=request_timeout)

    chain = _model_chain(model, fallback_models)
    started = time.monotonic()
    last_err: BaseException | None = None
    any_retryable = False

    for index, current in enumerate(chain):
        try:
            return _call_one_model(
                client,
                model=current,
                messages=messages,
                max_tokens=max_tokens,
                retries=retries,
                raise_on_truncation=raise_on_truncation,
                started=started,
                kwargs=kwargs,
            )
        except _ModelExhausted as exhausted:
            last_err = exhausted.cause
            any_retryable = any_retryable or exhausted.retryable
            if not exhausted.retryable:
                break  # 4xx — każdy kolejny model odrzuci to tak samo
            if index + 1 < len(chain):
                logger.warning(
                    "[claude_client] model %s wyczerpany (przeciążenie) — "
                    "schodzę na %s",
                    current,
                    chain[index + 1],
                )

    _record_health(started, failed=True)

    # Łańcuch jednomodelowy zachowuje DOTYCHCZASOWY kontrakt: surowy wyjątek
    # SDK leci do wołającego. Na tym stoi obsługa błędów dziesięciu miejsc
    # wywołania (i dwa testy w `test_claude_client.py`), więc podmiana go na
    # własny typ byłaby zmianą zrywającą przebraną za sprzątanie.
    if len(chain) > 1 and any_retryable:
        raise ClaudeOverloaded(
            "Usługa AI jest chwilowo przeciążona — spróbuj ponownie za chwilę."
        ) from last_err
    if last_err is not None:
        raise last_err
    raise ClaudeError("call_claude nie zwrócił odpowiedzi")  # pragma: no cover


def call_claude_text(**kwargs: Any) -> str:
    """`call_claude`, ale zwraca sklejony tekst zamiast ``Message``.

    Istnieje dla trzech konsumentów przeniesionych z ``analyze_with_ai``, które
    parsują `str`. Dziesięciu pozostałych trzyma się ``Message``, więc to oni
    dyktują kształt `call_claude` — ta owijka jest tańsza niż przepisywanie
    ich parsowania.

    Pusta odpowiedź jest błędem, nie pustym stringiem: dalej i tak skończyłaby
    się myląco jako „nieprawidłowy JSON (znak 0)".
    """
    message = call_claude(**kwargs)
    text = text_of(message)
    if not text.strip():
        raise ClaudeError("Model zwrócił odpowiedź bez treści tekstowej.")
    return text
