# Modele AI per funkcja — decyzja z badania na danych produkcyjnych (16.09.2026)

Badanie siedmiu modeli na WSZYSTKICH funkcjach AI (raport poza repo:
`outputs/model-matrix-2026-09-15/RAPORT-KONCOWY.md`, identyfikatory F1–F17)
zakończyło się decyzją Artura wdrożoną w rejestrze `services/ai_models.py`:

| ID | funkcja | model | ID | funkcja | model |
|---|---|---|---|---|---|
| F1 | scoring | Sonnet 5 | F9 | cv_parser | Sonnet 5 |
| F2 | champion_profile_parse | Sonnet 5 (z Haiku) | F10 | cv_backfill, cv_name_backfill | **GPT-6 Luna** (z Sonnet 5, od 22.09) |
| F3 | cv_requirement_map | Sonnet 5 | F11 | notes_extraction | **GPT-6 Luna** (z Sonnet 5, od 25.09) |
| F4 | cv_generator | Sonnet 5 (z 4.6) | F12 | candidate_summary | **GPT-6 Luna** (z Sonnet 5, od 22.09) |
| F5 | cv_interactive_chat | GPT-6 Luna (z Sonnet 5) | F13 | champion_draft | **GPT-6 Luna** (z Sonnet 5, od 22.09) |
| F6 | job_description_generator | Sonnet 5 | F14 | cv_rule_lint | Sonnet 5 (z Haiku) |
| F7 | order_parser | **Sonnet 5** (od 25.09; 22–25.09 GPT-6 Luna) | F15 | mindy_chat | GPT-6 Luna |
| F8 | uop_check | GPT-6 Luna | F16/F17 | `VOYAGE_MODEL` / `RERANKER_ENABLED` | voyage-3 / wyłączony |
| F18 | cv_factual_verification | GPT-6 Luna (z Sonnet 5) | | | |

- **„Luna" to od 22.09.2026 GPT-6 Luna (`gpt-6-luna`)**, nie GPT-5.6 Luna,
  na której robiono badanie 16.09 — liczby F5/F8/F15/F18 pochodzą z wersji
  5.6. Kształt żądania bez zmian (sprawdzone żądaniem z produkcji), cena
  0,10/0,50 USD za 1M zamiast 0,20/1,20. Powrót bez deployu: env funkcji
  (np. `UOP_CHECK_MODEL=gpt-5.6-luna`). Przeniesienie na Lunę KOLEJNEJ funkcji
  wymaga pomiaru jak w badaniu — nie samej zmiany wersji.
- **Pomiar GPT-6 Luna 22.09.2026** (harness `/root/nexus-model-eval`, te same
  przypadki co 16.09, 14 zadań, 0,79 USD) przeniósł na Lunę 6 decyzją Artura:
  F7 zamówienia (błędy krytyczne 3,9% vs 4,7% Sonneta, 0 cichych — cofnięte
  25.09, patrz niżej), F12
  podsumowanie aktywności (96,7% poprawnych jak DeepSeek, bez wysyłki poza EOG),
  F13 szkic Championa (remis) i F10 masowe uzupełnianie pól/nazwisk z CV
  (0,07 vs 0,08 wymyślonej technologii na CV). **Parser CV (F9) zostaje na
  Sonnecie**: na tym samym prompcie v7 Luna 6 wymyśla 0,62 technologii na CV,
  Sonnet 0,17 (różnica istotna). Porównując modele po zmianie promptu,
  licz OBA na bieżącym prompcie — stare wyniki mieszają efekt modelu i promptu.
  F10 nie czyta już `CLAUDE_MODEL_CV`/`CLAUDE_MODEL_CV_BULK` (te zostają przy
  parserze, lincie i datach doświadczenia); zapas przy przeciążeniu OpenAI to
  model parsera CV (`_parse_with_claude`), zamówienia/Champion/podsumowanie
  przekazują `fallbacks_for(...)` jawnie. Harness przechwytuje od 22.09 także
  `llm_providers.chat_complete` — bez tego bieg modelu OpenAI szedł na model
  produkcji.
- **OpenAI od GPT-5.6 liczy ZAPIS do cache (1,25× wejścia)** i zgłasza go
  w `prompt_tokens_details.cache_write_tokens`; `parse_response` odejmuje go
  od wejścia, a `_PRICES` dla OpenAI to czwórka (wejście, wyjście, odczyt,
  zapis). Do 22.09 zapis był wyceniany jak zwykłe wejście.
- **F7 = Sonnet 5 od 25.09.2026 — Luna już DWA razy przegrała na fladze niepewności.**
  21.09 powrót z GPT-5.6 Luna, 22.09 przejście na GPT-6 Lunę po pomiarze, 25.09
  zespół zgłosił, że Luna 6 ciągle daje „odczyt niepewny”. Pomiar 22.09 liczył
  trafność pól, nie flagę `uncertain` — przy kolejnej próbie Luny licz też odsetek
  odczytów niepewnych na poprawnych zamówieniach. GPT-5.6 Luna czytała
  zamówienia poprawnie, ale oznaczała odczyt jako `uncertain` bez konkretnego
  powodu („oznaczony przez model jako niepewny", echo instrukcji promptu), a
  bramka poczty traktuje każdą niepewność jako powód do kolejki — Nordea po
  16.09: 2 z 6 poprawnych zamówień do ręcznego sprawdzenia. Badanie 16.09 i tak
  zalecało zostawić odczyt na Sonnecie. `order_pdf_parser._MODEL` liczy się przy
  imporcie, więc zmiana `ORDER_PARSER_MODEL` w Coolify wymaga restartu.
- **DeepSeek wycofany 25.09.2026 (decyzja Artura).** Konto zeszło do −0,01 USD
  i nocny odczyt notatek (F11) dostawał 402 dla każdego kandydata (~1000
  zdarzeń Sentry na noc). F11 przeszedł na GPT-6 Luna (pomiar 25.09 na prompcie
  v5: 0,22 nieugruntowanych wartości/kandydata, 1/60 w stawce — miesięczna,
  poprawna). Stawka PLN/h z notatek wchodzi do profilu tylko, gdy ta liczba
  stoi w notatce (`_drop_ungrounded_rate`). Bieg staje na pierwszym 401/402/403
  (`status=provider_unavailable`). Kod dostawcy DeepSeek zostaje, ale żadna
  funkcja go nie używa, więc sonda zdrowia o niego nie pyta.
- **Rejestr jest JEDYNYM miejscem „funkcja → model".** Dostawca wynika z NAZWY
  modelu (`llm_providers.provider_of`: `claude-*` → Anthropic, `gpt-*` →
  OpenAI, `deepseek*` → DeepSeek). Nie dokładaj literałów modeli ani osobnych
  klientów w serwisach — `test_ai_models_registry.py` przypina decyzję per ID.
- **Dostawcy spoza Anthropic idą przez TĘ SAMĄ granicę `claude_client.call_claude`**
  (`services/llm_providers.py`): ten sam kształt odpowiedzi (`ProviderMessage`
  = bloki tekstowe, `stop_reason`, `usage`), te same ponowienia, deadline,
  fallback i telemetria (`ai_metering` z własnym cennikiem i polem `provider`).
  Błędy są zgłaszane WYJĄTKAMI SDK Anthropic (`RateLimitError`, `APITimeoutError`,
  `AuthenticationError`…) z prawdziwym `httpx.Response` — na nich stoi
  klasyfikacja ponowień i mapowanie błędów kilkunastu wołających. Nie zamieniaj
  tego na osobną hierarchię wyjątków „bo czystsza": zepsuje `except anthropic.*`.
- **Nieobsługiwane u GPT/DeepSeek: streaming, `tools`, bloki inne niż tekst
  (obraz, dokument PDF)** — `ValueError` (nieponawialny), nie ciche pominięcie.
  OpenAI dostaje `reasoning_effort=none`, `store=false`, bez `temperature`
  (modele rozumujące odrzucają parametr); DeepSeek `thinking=disabled` — czyli
  konfiguracje, w których model wygrał badanie.
- **Funkcje na GPT/DeepSeek mają fallback na Sonneta 5** (429/5xx/przeciążenie).
  **Brak klucza dostawcy = 401 NIEPONAWIALNE, bez kaskady na Claude** — błąd
  konfiguracji ma być widoczny: `/api/health` → `checks.openai` /
  `checks.deepseek` (`unconfigured` | `configured` | `degraded` | `unhealthy`).
  Sondy „brak klucza" u wołających pytają `api_key_configured(model)`, nie o
  klucz Anthropic. Klucze `OPENAI_API_KEY` i `DEEPSEEK_API_KEY` są w Coolify
  od badania (16.09.2026).
- **`settings_attr` wygrywa z `default` rejestru**, więc domyślne wartości
  legacy pól w `config.py` (`CLAUDE_MODEL_CV`, `CLAUDE_MODEL_CV_BULK`,
  `ORDER_PARSER_MODEL`) MUSZĄ być tym samym modelem co w rejestrze — pilnuje
  `test_legacy_settings_defaults_agree_with_the_registry`. Tak Haiku siedziałby
  w backfillu mimo decyzji. MINDY nie honoruje już legacy `CLAUDE_MODEL_CV`.
- **F4: Sonnet 5 z `CV_B2B_THINKING=disabled`** (domyślne). Rewert #628 mierzył
  Sonneta 5 z wymuszonym thinking; badanie z thinking wyłączonym: wymyślone fakty
  0.20 vs 0.41 u 4.6. Nie przywracaj pinu 4.6 bez ponownego pomiaru.
- **F2: zmiana modelu parsera Championa zmienia WYNIKI parsowania** — przy
  kolejnej edycji promptu bump `PARSER_VERSION`; klucz cache nie zawiera nazwy
  modelu.
- **F16/F17:** `VOYAGE_MODEL` w kodzie = `voyage-3` (do 16.09 kod mówił
  `voyage-3-large`, prod `voyage-3` — rozjazd wysyłał eval na ścieżkę
  referencyjną); `RERANKER_ENABLED=False` — na ścieżce produkcyjnej był no-opem
  (pula = wynik, `canonical_fit` i tak sortuje), dosypka 500→rerank-3→200
  n.s. Kod rerankera zostaje; włączenie = env w Coolify.
- **Dokładając nowy model:** wpis w `ai_models._REGISTRY` z uzasadnieniem
  (ID + liczba z badania), cena w `ai_metering._PRICES` (dwójka = Anthropic,
  trójka = dostawca z własną stawką za odczyt cache), przy nowym dostawcy —
  gałąź w `llm_providers.build_request/parse_response` i etykieta w
  `HEALTH_LABEL`.
