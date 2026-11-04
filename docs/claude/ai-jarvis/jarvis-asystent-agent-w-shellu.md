# Jarvis — asystent-agent w shellu (0330, zastępuje MINDY)

Maskotka w prawym dolnym rogu każdego ekranu (⌘J, paleta ⌘K „Zapytaj Jarvisa”)
dla KAŻDEJ zalogowanej roli (decyzja Artura 21.09.2026). Odpowiada na pytania
o dane NEXUSA i przygotowuje zadania. Raport: `docs/jarvis-assistant-completion-report.md`.
Backend: `app/api/jarvis.py` + `app/services/jarvis/`; front: `components/jarvis/`,
`lib/jarvis/`; harness `/preview/jarvis`.

- **Jarvis nie ma własnych uprawnień.** Narzędzie = wywołanie ISTNIEJĄCEJ trasy
  in-process (`httpx.ASGITransport`) z tokenem z żądania (`transport.py`).
  Bramki sekcji, członkostwa, portfela DL i redakcja kwot działają same. Nie
  dokładaj narzędzia z własnym SQL-em ani wołaniem handlera wprost — snapshot
  sekcji dokleja tylko `get_authenticated_user`.
- **Trzy poziomy (`tools.py`):** `read` wykonywany od razu; `write` model tylko
  PROPONUJE (`jarvis_actions.status=proposed`, karta w UI), wykonanie dopiero
  po `POST /api/jarvis/actions/{id}/confirm` klikniętym przez człowieka — i to
  DOKŁADNIE z zapisanymi `args`, idempotentnie (`proposed → confirmed` warunkowym
  UPDATE, TTL 15 min); `link` (`open_screen`) — operacje krytyczne (usuwanie,
  wypowiedzenie, podpis, stawki, maile, generatory, admin) NIGDY nie są
  wykonywane, Jarvis daje przycisk do ekranu. Listę zakazaną i „read ⇒ trasa
  odczytu” pilnuje `test_jarvis_tool_registry_contract.py`.
- **`acknowledge_eligibility` nie jest w schemacie narzędzia** — ustawia go
  wyłącznie serwer po prawdziwym 409 `ELIGIBILITY_WARNING` (druga karta „mimo
  ostrzeżenia”). Kalendarz bez `attendees`/`teams_link` — Jarvis nie zaprasza ludzi.
- **Karta akcji jest budowana przez SERWER** z args + nazw doczytanych przez API
  (`_display_names`); `sanitize_args` wycina klucze spoza schematu (model nie
  wstrzyknie `_display`). Etap przy przesunięciu idzie z tablicy, nie ze słów modelu.
- **Tylko Anthropic** (`AIFeatureKey.jarvis` → Sonnet 5, fallback Haiku) —
  `llm_providers` odrzuca `tools` dla GPT/DeepSeek. Cała tura = jedna operacja
  `ai_feature(jarvis)`. `claude_client` liczy koszt narzędzi KLIENCKICH zwykłym
  cennikiem (`_has_server_tools`); do 0330 każde `tools` = „unpriced”.
- **Prompt systemowy stały bajt w bajt** (cache); data, rola, ekran, imię
  nadane przez użytkownika idą blokiem `[Kontekst…]` w wiadomości użytkownika.
  Po tym znaczniku liczy się też miękki licznik dzienny (`JARVIS_DAILY_SOFT_LIMIT`,
  informuje, nie blokuje).
- **Pętla nie trzyma połączenia DB** podczas modelu i narzędzi (`store.py` —
  krótkie sesje). Jedna tura na osobę (`busy_until`, 409). Historia jest
  naprawiana przed wysłaniem (`repair_history`): `tool_use` bez wyniku (deploy
  uciął turę) dostaje syntetyczne „przerwane”. SSE z heartbeatem 10 s; rozłączenie
  klienta nie przerywa tury.
- **Tag `via: jarvis`** w `activities.details` bez dotykania 241 miejsc
  `Activity(`: nagłówek `X-Jarvis-Internal` z sekretem PROCESU → `stamp_via`
  w `deps.get_authenticated_user` → listener `before_flush` (`via_tag.py`).
  Nagłówek z przeglądarki nic nie daje.
- **RODO:** rozmowy wiążą kandydatów w `jarvis_conversation_entities` (args,
  `candidate_id` w wynikach, `/candidates/{id}`, wiersze narzędzi kandydackich,
  ekran). `DELETE /api/candidates/{id}` kasuje całe powiązane rozmowy
  (`jarvis/erasure.py`, licznik w audycie). Retencja 30 dni (`jarvis_retention`,
  biegnie niezależnie od `JARVIS_ENABLED`).
- **Tryb „podgląd jako” = Jarvis niedostępny** (403 na trasach, front chowa).
- **Kill-switch `JARVIS_ENABLED` domyślnie `false`**; włączenie przez workflow
  „Coolify set env”. Wyłączony: brak maskotki (poza trybem kids), trasy 503.
- **Jedna maskotka:** `KidsMascot` usunięta, jej zachowania (slogany, konami,
  `celebrate`) żyją w `useKidsChatter`; `kidsBuddy` zdjęty ze store'u motywu (v8).
  Postaci to gotowe ilustracje SVG na klasach `j-*` (`globals.css`), lista =
  `prefs.py` `JarvisCharacter` (test w `jarvis-lib.test.ts`); `robot_gold`/`trophy`
  odblokowuje `competition_winners` (rank 1 / ≤3), PATCH odrzuca zablokowaną 403.
- **⌘J = Jarvis, ⌘⇧J = nowa rekrutacja** (goły `j` bez zmian).
- **Endpointy MINDY (`/api/dynareporter/mindy/*`) usunięte** (21.09.2026),
  a 23.09.2026 cały DynaReporter (20 routerów, `DYNAREPORTER_MODE`, archiwum
  admina). Wartość enuma `mindy_chat` ZOSTAJE (Postgres nie ma `DROP VALUE`,
  historia kosztów ją niesie), razem z wpisem w rejestrze modeli.
  `/dynareporter/mindy` przekierowuje trwale na Insights (`next.config.ts`).
  Powrót routera łapie `test_mindy_endpoints_are_gone`.
- **Internet = przełącznik 🌐 na JEDNĄ wiadomość** (`web: true`, 21.09.2026,
  `services/jarvis/web.py`). Zasada: internet ALBO baza, nigdy oba. Tura z
  internetem dostaje wyszukiwarkę Anthropic (`web_search_20250305`,
  `JARVIS_WEB_MAX_SEARCHES_PER_TURN`) i WYŁĄCZNIE narzędzia z `WEB_SAFE_TOOLS`
  (Pomoc + link); nie dostaje historii rozmowy ani ID rekordu z ekranu — dane
  z NEXUSA nie mają jak trafić do zapytania na zewnątrz (RODO, wstrzyknięcie
  z CV). Twardy limit `JARVIS_WEB_DAILY_LIMIT` (429), wyłącznik
  `JARVIS_WEB_ENABLED`, domeny `JARVIS_WEB_ALLOWED_DOMAINS`/`_BLOCKED_DOMAINS`.
  Źródła (tylko http(s), z wyników wyszukiwarki, nie z tekstu modelu) idą
  zdarzeniem `sources` i blokiem `x_sources`, który `repair_history` odfiltrowuje
  przed wysłaniem do API. `pause_turn` jest kontynuowany surowymi blokami.
  Koszt: `ai_metering` dolicza 0,01 USD za wyszukiwanie
  (`usage.server_tool_use.web_search_requests`); `web_search_*` NIE jest już
  „unpriced”. Dokładając narzędzie do `WEB_SAFE_TOOLS` — tylko takie, które nie
  czyta danych osobowych ani biznesowych.
- **Dodając narzędzie:** wpis w `tools.py` (opis PL, `label`, `section`, `shape`
  przycinający wynik; zapis: `preview` + `done` + `invalidates`), test kontraktowy
  przechodzi sam, jeśli trasa istnieje i poziom się zgadza. Dokładając trasę
  pod `/api/jarvis/*` — wpis w `_BARE_BASELINE` i `_SECTIONLESS_ALLOWLIST`.
