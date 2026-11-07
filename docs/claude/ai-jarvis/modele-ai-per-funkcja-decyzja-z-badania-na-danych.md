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

## Audyt Sonnet 5.5 i Haiku 5.5 (02.11.2026)

Bieg na danych produkcyjnych w `/root/nexus-model-eval`, wyniki w `results-nov/`,
decyzja Artura z 02.11.2026. Najważniejsze dla kolejnych zmian:

- **Sonnet 5.5 od 03.11.2026 w F3 kafelki CV, F9 parser CV i F10 `cv_backfill`**, z Sonnetem 5
  jako zapasem; tabela na górze pliku pokazuje stan z 16.09. Parser przeszedł tylko dlatego,
  że `cv_technology_grounding` odcina przed zapisem technologie bez śladu w CV (zmyślenia
  0,34 wobec 0,20 na CV). Nie cofaj filtra bez cofnięcia modelu. Powrót bez deployu:
  `CV_PARSER_MODEL`, `CV_REQUIREMENT_MAP_MODEL`, `CV_BACKFILL_MODEL`. `cv_name_backfill`
  zostaje na Lunie, bo imiona nie zyskują na lepszym odczycie technologii.
- **Generator CV od 03.11.2026 na GPT-6.1 Sol, recenzent na Haiku 5.5.** Jurorzy na ślepo, 36 CV:
  Sol lepszy od Sonneta 5 w 24 parach, gorszy w 2 (Sonnet 5.5: 22 i 7), poważne zdania bez pokrycia
  0,31 wobec 1,36 na CV. Recenzent musi być od innego dostawcy niż generator, stąd Haiku,
  a nie Luna. **Wyższy reasoning nie pomaga:** medium i high wobec low dają remis (11/9/16 i 9/8/18),
  poważne zdania 0,28 i 0,29 wobec 0,39, a mediana czasu rośnie z 41 do 60 i 137 s przy limicie 300 s.
  Nie podnoś go bez nowego pomiaru. Powrót bez deployu: `CV_B2B_MODEL`, `CV_FACTUAL_VERIFICATION_MODEL`.
- **Generator ogłoszeń (F6) od 04.11.2026 na GPT-6.1 Sol, zapas Sonnet 5.5** (decyzja Artura mimo rekomendacji
  Sonneta 5.5). 40 rekrutacji z pełnym `AdMaterial`, tylko po polsku; wersji angielskiej nie mierzono. Wobec Sonneta 5
  Sol 29/6/3, Sonnet 5.5 27/6/5, Haiku 5.5 8/26/4. Sol wobec Sonneta 5.5 22/14/4, różnica ogólna nieistotna, ale wierność
  +0,29, język +0,24, ustawienia +0,33 (istotne) i obaj jurorzy po jego stronie. **Koszt świadomy:** technologie krytyczne
  i wymagane obecne w ogłoszeniu 70% wobec 81% (dopasowanie dosłowne), prompt nie każe użyć każdej. Przy skargach na braki
  w ogłoszeniach zacznij od tego punktu promptu. Pomiar na samym tytule i kilku umiejętnościach (pierwszy bieg, 03.11) jest
  niemiarodajny, bo prompt wymusza 4–7 obowiązków i każe modelom zmyślać. Powrót bez deployu: `JOB_WRITER_MODEL`.
- **Opus 5.5 nie wchodzi do generatora CV** (pomiar 03.11, 36 CV): wobec Sola 7/19/10, wierność −0,44 (istotne),
  kompletność +0,29, 0,33 USD wobec 0,085 USD na CV, mediana 98 s wobec 37 s. Jurorzy skłaniają się ku swojemu dostawcy
  (Sonnet 5.5 40/29 dla Opusa, Terra 56/16 dla Sola), więc porównuj też same oceny, nie tylko zwycięstwa.
- **Jurorom nie dawaj `highlight_keywords`.** To lista wymagań do pogrubienia, nie treść CV, a jurorzy
  brali ją za dopisane technologie: 68 z 117 zarzutów u Sonneta 5, 52 z 63 u Sola. `judges.py` na serwerze
  już to pomija, a wyniki wyżej są policzone bez tego pola.
- **Funkcje QC od 03.11.2026 (decyzja Artura, małe próby, ocena po 2 tygodniach na produkcji):**
  F22 propozycje zdań i F24 ocena prepu na Sonnecie 5.5, F28 screening z notatki na Solu, wszędzie
  Sonnet 5 jako zapas. F24 nie na Solu mimo 0% złych cytatów, bo podnosił ocenę o 8 punktów bez wzorca.
- **GPT-6.1 Sol od 03.11.2026 w F8 znamiona UoP**, z Sonnetem 5 jako zapasem: fałszywe alarmy
  4,5% wobec 34% Luny, brak propozycji zapisu 2% wobec 60%, ok. +0,26 USD miesięcznie.
  Prawdziwych przypadków ryzyka w próbie było tylko 8. Sol nie ma `reasoning_effort: none`,
  więc `llm_providers` wysyła `low`, a rozumowanie liczy się do limitu tokenów; przy funkcji
  z małym limitem trzeba go podnieść. W innych funkcjach Sol przegrał albo kosztował za dużo:
  parser dodaje ogólne pojęcia (40 pozycji na CV, 88 bez śladu), zamówienia mają 71% odczytów
  niepewnych, profile Championa recall MUST 65%, recenzent to ok. +86 USD miesięcznie.
- **Sonnet 5.5 odrzuca `thinking: disabled` kodem 400.** Wołający zostają przy
  `disabled`, a `claude_client._sdk_request_kwargs` tłumaczy to na `between_tools`
  dla każdego modelu w łańcuchu osobno, bo `between_tools` przyjmuje tylko Sonnet 5.5.
  Pomiar objął tylko ten tryb; adaptive nie był mierzony.
- **Nowszy nie znaczy lepszy per funkcja.** Sonnet 5.5 przegrywa z Sonnetem 5 przy
  profilach Championa (recall MUST 72% wobec 97%) i uzasadnieniach (wskazane braki
  18% wobec 51%), więc tam modelem zapasowym jest Haiku 5.5 (89% i 43%).
- **Model zapasowy działa tylko, gdy wołający go przekaże.** Wpis w rejestrze nic nie
  zmieni bez `fallback_models=` w wywołaniu; do 02.11 nie przekazywały go parser CV,
  uzasadnienia, kafelki CV i lint reguł. Daty doświadczenia idą przez parser, więc
  mają jego łańcuch i nie mają osobnego wpisu.
- **Cache:** w parserze 81% kosztu to wyjście, więc cache instrukcji daje ok. 26 USD
  miesięcznie, a JSON bez wcięć (prompt v8) ok. 50 USD. Znacznik stoi przed CV
  (`cv_parser._user_content`), a próba na 5 CV potwierdziła odczyt 1941 tokenów z cache.
  Generator ma TTL 1 godzina, bo 96% wywołań dzieli mniej niż godzina, a 5 minut
  tylko 44%. Jarvis zostaje przy 5 minutach: narzędzia z 5-minutowym znacznikiem
  stoją przed systemem, a dłuższy TTL musi poprzedzać krótszy, inaczej API zwraca 400.

## F10 `cv_backfill` na Haiku 5.5 od 07.11.2026 (odczyt masowy pełnym promptem)

Decyzja Artura z 07.11.2026 przed ponownym odczytem ok. 55 tys. CV starej bazy
(`scripts/reparse_cv_batch.py`, Batch API) i dla fazy nocnej `candidates_cv_fields`,
która od tej zmiany czyta pełnym promptem `CV_ENRICHMENT`, a nie `CV_ENRICHMENT_BULK`.

- Pomiar na stagingu, 50 losowych CV osób bez osi technologii, wzorzec = oś z odczytu
  Sonnetem 5.5: Haiku 5.5 oś u 47 z 50 osób, 77–83% technologii osi Sonneta (drugi
  odczyt Sonnetem 91%), miesiące w ±12 w 90% (Sonnet 97%), ta sama odpowiedź na
  „3+ lata” w 96% (Sonnet 99%), 0,0017 USD za CV wobec 0,034. Luna 6 na tym samym
  pomiarze: 64% jej technologii nie ma u Sonneta, 1 błąd na 50 — odrzucona.
- Haiku daje ok. 2% odpowiedzi z niepoprawnym JSON-em (1 na 50); bieg masowy liczy je
  jako nieudane i ponawia raz.
- Wgranie CV, „Odśwież z CV”, `from-cv` i scraper zostają na F9 (`cv_parser`, Sonnet 5.5):
  tam rekruter patrzy od razu.
- Powrót bez deployu: `CV_BACKFILL_MODEL=claude-sonnet-5-5`.
