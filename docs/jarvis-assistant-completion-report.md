# Jarvis — asystent-agent NEXUSA (zastępuje MINDY) — raport z ukończenia

Data: 21.09.2026. Plan: Etapy A (fundament, maskotka, odczyt), B (akcje
z potwierdzeniem) i C (proaktywność, odblokowania) wdrożone w jednym PR-ze.

## Co powstało

**Dla użytkownika.** Maskotka w prawym dolnym rogu każdego ekranu. Otwiera
się kliknięciem, skrótem ⌘J albo z palety ⌘K („Zapytaj Jarvisa”). Jarvis
odpowiada na pytania o dane NEXUSA i przygotowuje zadania, które człowiek
zatwierdza kliknięciem „Zrób to”. Wygląd ustawia każdy sam: 8 postaci + 2
odblokowywane w Lidze Mistrzów, własne imię, kolor, mała ikona, poranny
skrót dnia, dźwięk. Strona MINDY kieruje do Jarvisa.

**Zasady bezpieczeństwa** (szczegóły w `CLAUDE.md`, sekcja „Jarvis”):

- narzędzia wołają ISTNIEJĄCE trasy in-process tokenem pytającego — zero
  własnych uprawnień;
- zapis to wyłącznie propozycja (`jarvis_actions`), wykonanie po kliknięciu,
  dokładnie z zapisanymi argumentami, idempotentnie, TTL 15 min;
- operacje krytyczne (usuwanie, wypowiedzenia, podpisy, stawki, maile,
  generatory, administracja) nigdy — tylko przycisk do ekranu;
- Markdown odpowiedzi bez obrazków i bez linków zewnętrznych (kanał wycieku
  przy wstrzyknięciu promptu z CV/notatek);
- tryb „podgląd jako” wyłącza asystenta.

## Pliki

Backend:
- `alembic/versions/0330_jarvis.py` (+ lustro w `entrypoint.sh`): wartość
  enuma i seed `ai_features.jarvis`, `users.jarvis_prefs`, tabele
  `jarvis_conversations`, `jarvis_messages`, `jarvis_actions`,
  `jarvis_conversation_entities`, procedura Pomocy `jarvis-asystent`.
- `app/models/jarvis.py`, `app/api/jarvis.py`,
  `app/services/jarvis/{tools,transport,agent,store,actions,prompt,prefs,via_tag,erasure}.py`,
  `app/tasks/jarvis_retention.py`, `app/data/procedures/jarvis-asystent.md`.
- Zmiany: `deps.py` (tag `via`), `users.py` (preferencje Jarvisa),
  `candidates.py` (kasowanie rozmów przy usunięciu kandydata),
  `claude_client.py` (koszt narzędzi klienckich), `ai_models.py` (F19),
  `proposals_bulk.py` + telemetria (`source="jarvis"`), `main.py`
  (router, pętla retencji, sondy `/api/health/deep`), `config.py`.

Frontend:
- `components/jarvis/*` (postaci, maskotka, panel, karty, formularz wyglądu,
  `JarvisRoot`, `useKidsChatter`), `lib/jarvis/*` (typy, SSE, strumień,
  kontekst, reduktor, API, zdarzenie otwarcia), harness `/preview/jarvis`.
- `AppShellV2` montuje `JarvisRoot` zamiast `KidsMascot` (usunięta),
  `KeyboardShortcuts` (⌘J → Jarvis, ⌘⇧J → nowa rekrutacja),
  `CommandPaletteV2`, strona `/dynareporter/mindy`, `store/theme.ts` v8.

## Nowe trasy

`GET /api/jarvis/status` · `POST /api/jarvis/chat` (SSE) ·
`GET /api/jarvis/conversations` · `GET|DELETE /api/jarvis/conversations/{id}` ·
`POST /api/jarvis/actions/{id}/confirm` · `POST /api/jarvis/actions/{id}/reject` ·
`GET|PATCH /api/users/me/preferences` rozszerzone o `jarvis`.

## Weryfikacja

- Backend: `test_jarvis_agent.py` (pętla przez prawdziwą aplikację,
  odmowy uprawnień, propozycja → zatwierdzenie → notatka, idempotencja,
  wygaśnięcie, impersonacja, flaga, blokada tury, awaria modelu, RODO,
  zakres właściciela), `test_jarvis_tool_registry_contract.py` (trasy
  istnieją, odczyt = trasa odczytu, lista zakazana, ekrany istnieją we
  froncie, klucze odświeżania istnieją), `test_jarvis_units.py`,
  `test_jarvis_migration_mirror.py` + kontrakty authz/sekcji/modeli AI.
- Frontend: vitest (`jarvis-lib`, `jarvis-components`, skróty, middleware,
  shell), `tsc`, `eslint`; harness `/preview/jarvis` obejrzany w przeglądarce
  (10 postaci × 6 nastrojów, panel, karty, historia, formularz wyglądu).

## Znane ograniczenia i kroki po wdrożeniu

- **`JARVIS_ENABLED=false` domyślnie.** Włączenie: workflow „Coolify set env”
  (`JARVIS_ENABLED=true`), potem test na produkcji z prawdziwym modelem —
  lokalnie pętla była testowana z podmienionym modelem, bez wywołań Claude.
- Tekst odpowiedzi przychodzi w całości per krok (bez strumieniowania tokenów).
- Endpointy MINDY w backendzie zostają jedno wydanie (strona już przekierowuje).
- Karta „mimo ostrzeżenia” (409 `ELIGIBILITY_WARNING`) jest pokryta logiką,
  ale bez testu integracyjnego z prawdziwą rekrutacją i konfliktem.
- Nazwisko kandydata, które padło wyłącznie w tekście odpowiedzi modelu (bez
  ID w wynikach narzędzi), znika najpóźniej z retencją 30 dni.
- Koszt: tura ≈ kilka wywołań Sonneta; pilnuje alarm wydatków i miękki
  licznik 50 pytań/dzień (informuje, nie blokuje). Zmierzyć po tygodniu.
