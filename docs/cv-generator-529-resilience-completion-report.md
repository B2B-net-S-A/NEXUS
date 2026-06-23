# CV Generator — odporność na Claude 529 `overloaded_error`

> Fix produkcyjny, 2026-06-23. Generator CV (`/cv-generator`) zwracał użytkownikowi
> surowy błąd: `Claude wywołanie nieudane: Claude call failed: Error code: 529 -
> {'type':'error','error':{'type':'overloaded_error','message':'Overloaded'}}`.

## Diagnoza

Sam generator nie był zepsuty. Anthropic zwracał **HTTP 529 `overloaded_error`**
(pula modelu `claude-sonnet-4-6` przeciążona), a dotychczasowy retry (jeden model,
5 prób, ~30 s backoffu) nie był w stanie tego przeczekać. Surowy słownik błędu
wyciekał wprost do toasta w UI (`extractErrorDetail` → `toast.showError`).

Ścieżka: `ai_client.analyze_with_ai` → po wyczerpaniu retry `CVGeneratorAIError`
→ `standalone_service` opakowywał w `f"Claude wywołanie nieudane: {err}"`
(`ai_failed`, 502) → frontend pokazywał `detail`.

## Co zmieniono

### `backend/app/services/cv_generator_b2b/ai_client.py` (rdzeń)
- **Łańcuch modeli (fallback):** `_models()` = deduplikowane `[primary, *fallbacks]`.
  Primary z `CV_B2B_MODEL` (domyślnie `claude-sonnet-4-6`), fallbacki z
  `CV_B2B_FALLBACK_MODELS` (CSV, domyślnie `claude-opus-4-8`). 529 jest
  **per-pool**, więc próba na innej rodzinie modeli realnie ratuje generację.
- **Kaskada tylko dla błędów przejściowych:** retry per model (jitterowany,
  capowany backoff). Tylko `_is_retryable` (429/529/5xx/connection) kaskaduje do
  kolejnego modelu; twardy 4xx (zła konfiguracja/klucz) wychodzi natychmiast,
  bez maskowania cichym fallbackiem.
- **Czysty komunikat:** gdy *każdy* model pozostaje przeciążony →
  `CVGeneratorOverloadedError` z komunikatem PL „Usługa AI (Claude) jest chwilowo
  przeciążona. Spróbuj wygenerować CV ponownie za chwilę." (HTTP **503**), zamiast
  surowego `Error code: 529 - {...}`.
- **Timeout per request:** jawny `CV_B2B_REQUEST_TIMEOUT` (domyślnie 120 s) —
  SDK default to 600 s, co potrafiłoby zablokować slot threadpoola FastAPI.
- **Twardnienie konfiguracji:** bezpieczny parser numerycznych env-varów
  (pusty/„śmieciowy" `CV_B2B_MAX_RETRIES`/`CV_B2B_MAX_TOKENS` → default, nie
  `ValueError` → bare 500); guard na pusty łańcuch modeli; `any_retryable`
  (overload wygrywa nad 4xx z fallbacku); check truncacji przed logiem „success".

### `backend/app/services/cv_generator_b2b/standalone_service.py`
- Nowy `except CVGeneratorOverloadedError` → `StandaloneGenerationError(code="ai_overloaded")`
  (kolejność: Truncated → Overloaded → AIError; podklasy przed bazą).

### `backend/app/api/cv_generator_b2b.py`
- `_error_status`: `"ai_overloaded" → 503`.

### Testy + CI + docs
- `backend/tests/test_cv_generator_b2b_ai_client.py` — 11 testów (łańcuch, dedup,
  sukces-bez-fallbacku, fallback-na-overloadzie, czysty komunikat bez wycieku
  `529`/`overloaded_error`, 4xx-bez-fallbacku, truncacja, overload-then-4xx,
  pusty-łańcuch, śmieciowy-env, brak-klucza).
- `.github/workflows/ci.yml` — dopisane `test_cv_generator_b2b_ai_client.py`
  **oraz** `test_sentry_filtering.py` do (selektywnej) listy pytest — wcześniej
  obie były poza bramką CI.
- `.env.example` — udokumentowane `CV_B2B_FALLBACK_MODELS`, `CV_B2B_MAX_RETRIES`,
  `CV_B2B_REQUEST_TIMEOUT`.

## Frontend
Bez zmian — `CVGeneratorStandaloneV2.tsx` już pokazuje `detail` z odpowiedzi
(także dla 503) przez `extractErrorDetail` → toast. Po fixie użytkownik widzi
czysty komunikat zamiast surowego słownika; a w typowym przypadku (Sonnet
przeciążony, Opus wolny) generacja **po prostu się udaje** dzięki fallbackowi.

## Weryfikacja
- 12/12 scenariuszy logiki przechodzi lokalnie (standalone verifier, bo lokalny
  python nie ma pełnego stacku backendu — heavy deps weasyprint/pyhanko).
- `ruff` czysty, `py_compile` czysty, `ci.yml` waliduje się jako YAML.
- Committed test (`test_cv_generator_b2b_ai_client.py`) uruchamia pełny pytest w
  CI (z prawdziwym `anthropic`) — to brama, której nie da się odtworzyć lokalnie.
- Przegląd adwersaryjny (multi-agent) — 8 znalezisk (0 critical/high-funkcjonalnych);
  wszystkie zaadresowane w tej zmianie.

## Aktywacja / tuning (opcjonalne, Coolify env vault)
- `CV_B2B_FALLBACK_MODELS=` (pusty) → wyłącza fallback (kontrola kosztu).
- `CV_B2B_MAX_RETRIES` → steruje worst-case latency przed 503.
- `CV_B2B_REQUEST_TIMEOUT` → ceiling pojedynczego wywołania.

## Znane ograniczenia
- Worst-case latency przy globalnym przeciążeniu obu modeli: ~28–34 s backoffu
  przed czystym 503 (mieści się w komunikowanym UI oknie 60–90 s).
- Dedykowany semafor współbieżności CV-gen (odseparowany od globalnego threadpoola)
  — rozważany jako osobny follow-up; ten fix dokłada per-request timeout, który
  ogranicza czas trzymania slotu.
