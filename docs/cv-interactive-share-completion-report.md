# Interaktywne CV — publiczny link, kafelki wymagań, chat (completion report)

> Data: 2026-08-07 · Branch: `claude/cv-classic-interactive-versions-b87092`
> Pomysł Artura: „jak robimy CV, to żeby była wersja classic i wersja
> interaktywna i klient może sobie przełączać (…) lista wymagań must have i
> nice to have, manager klika kafelek i widzi jakie ktoś ma doświadczenie
> (…) plus chatbox, gdzie manager wpisuje pytanie i dostaje odpowiedź
> dotyczącą tej osoby".

## Decyzje produktowe (zatwierdzone)

1. **Pełny zakres naraz** — link + widok classic + kafelki + chat.
2. **Interaktywna wersja tylko dla trybu „z procesu"** (`mode="new"`) — upload
   nie ma joba, więc nie ma wymagań; dostaje link z samym widokiem classic.
3. **Niezależnie od sufitu `cv_content_mode_cap`** + osobna flaga per klient
   (`Client.cv_interactive_enabled`, domyślnie ON).
4. **Eksport tylko przez druk/PDF przeglądarki** (window.print) — bez
   publicznego endpointu DOCX.

## Architektura

Jeden link `/cv/i/{token}`, dwa widoki przełączane przez hiring managera.
Źródłem WSZYSTKIEGO co widzi klient jest **client-safe payload**
(`build_public_payload` w `backend/app/services/cv_generator_b2b/public_view.py`):
deepcopy `cv_generated_documents.render_payload` bez `warnings`
(bezpiecznik fabrykacji = wewnętrzny), z maskowaniem blind (lustro renderera
DOCX: nazwisko → „Kandydat", firmy → „Firma z branży X"). Ten sam payload:

* renderuje widok classic (HTML 1:1 z sekcjami DOCX),
* jest WEJŚCIEM do generacji mapy wymagań — cytaty-dowody mogą fizycznie
  pochodzić tylko z tekstu, który klient i tak widzi,
* jest CAŁYM kontekstem chatu — model nie dostaje notatek/stawek/transkryptów,
  więc nie może ich wygadać.

### Kafelki (precompute, nie live-AI)

`backend/app/services/cv_generator_b2b/requirement_map.py` —
`ensure_requirement_map()` wołane na końcu background-joba generacji
(`_run_generate_new_job`). Jeden dodatkowy call Claude na generację
(`CV_REQUIREMENT_MAP` v1 w `llm_prompts.py`, model env
`CV_REQUIREMENT_MAP_MODEL`, default `claude-sonnet-5`). Wynik w
`cv_generated_documents.requirement_map` (+ `input_hash`/`model`/`generated_at`
— cache, ponowna finalizacja tego samego payloadu nie płaci drugi raz).

Wymagania: `Job.must_skills`/`nice_skills` (przez `iter_skill_names`),
fallback dla pustych must (~88% jobów) = regexowa ekstrakcja z Championa/JD
(`scoring_service._extract_skills_from_champion`). Cap 12 must + 8 nice.

**Kontrakt anty-fabrykacyjny** (`_sanitize_items`): każdy cytat musi być
substringiem publicznego payloadu (normalizacja whitespace+case) — parafrazy
odpadają; „met" bez ocalałego dowodu degraduje do „partial"; wymagania spoza
listy są ignorowane, brakujące dostają „no_data". Publiczny endpoint serwuje
wyłącznie zapisany cache — **zero AI na publicznej ścieżce kafelków**.

Fail-open: kwota AI (`AIFeatureKey.cv_requirement_map`) / błąd LLM / brak
klucza NIE psują generacji CV — link działa w samym widoku classic.

### Chat (`backend/app/services/cv_generator_b2b/interactive_chat.py`)

Warstwy obrony (od najtwardszej):
1. kontekst = wyłącznie public payload + mapa wymagań (patrz wyżej);
2. koszty: dzienny limit pytań per link (`CV_INTERACTIVE_CHAT_DAILY_LIMIT`,
   default 30 → 429) + globalna kwota `AIFeatureKey.cv_interactive_chat`
   (→ 503) + rate limit `5/minute; 60/hour` per IP;
3. DLP/injection: pytanie skanowane wzorcami injection (reuse regexów
   z `candidate_activity_summary_service` — jedno źródło prawdy); próba
   injection dostaje odmowę BEZ wywołania AI; odpowiedź skanowana na
   injection-echo i konkretne kwoty pieniężne → generyczna odmowa;
4. historia server-side per link (ostatnie 10 wiadomości z DB) — klient nie
   wstrzyknie spreparowanej „historii asystenta".

Model: env `CV_INTERACTIVE_CHAT_MODEL`, default `claude-haiku-4-5-20251001`
(publiczny, koszto-wrażliwy endpoint). `thinking: disabled` (trap truncacji).
Każda wymiana logowana w `cv_share_chat_messages` — także jako sygnał
sprzedażowy (co managerowie realnie sprawdzają).

### Tokeny linków

`cv_generated_share_tokens` — od pierwszego dnia WYŁĄCZNIE token v2
(hash-at-rest): sekret `token_urlsafe(36)` pokazany raz, w DB tylko SHA-256,
PK = nie-sekretny revoke-key `v2$<hex>`, **bez gałęzi legacy/dual-read**.
TTL 1–90 dni (default 14), opcjonalny `max_views` (atomowy UPDATE), rewokacja
idempotentna. Przy tworzeniu linku działa veto hiring managera (ten sam gate
co przy brandowanym CV — etap wyprowadzany z pary candidate_id+job_id).

## Endpointy

Authed (`/api/cv-generator`, `CandidateDocumentAccess`):
* `POST /generated/{id}/share-token?expires_in_days=&max_views=` → 201, raw
  token raz + `interactive_available`
* `GET /generated/{id}/share-tokens` — lista bez sekretów
* `DELETE /generated/share-token/{token_or_key}` — revoke

Public (`/api/public`, w `public_share.py`):
* `GET /cv-i/{token}` — `30/minute`, no-store/no-referrer, atomic view count,
  Activity audit; response `{cv, requirements|null, chat_enabled, expires_at}`
* `POST /cv-i/{token}/chat` — `5/minute; 60/hour`, body `{question≤500}`,
  429/503/502 wg warstwy limitu

`_PATH_TOKEN_RE` w `logging_config.py` rozszerzony o segment `share-token/`
(redakcja tokenów w logach; `public/cv-i/` łapał się już wzorcem
`public/[\w-]+/`).

## Frontend

* **Publiczna strona** `frontend/src/app/cv/i/[token]/page.tsx` — przełącznik
  Klasyczne/Interaktywne (default interaktywne gdy dostępne), dokument CV
  (sekcje jak DOCX, PL/EN wg języka CV), kafelki must/nice ze statusami
  (met=emerald / partial=amber / no_data=muted), klik w cytat-dowód scrolluje
  i podświetla pozycję doświadczenia, chat z sugestiami pytań, druk przez
  `window.print()` (elementy interaktywne `print:hidden`), stany 404/410.
  `PUBLIC_PATHS` i `AppShellV2` pokrywają `/cv/i/…` istniejącym prefiksem
  `/cv/` — zero zmian w middleware.
* **Modal udostępniania** `components/v2/modals/CvGeneratedShareModal.tsx` +
  przycisk `Link2` w wierszu listy „Wygenerowane CV"
  (`CVGeneratorStandaloneV2`). Sekret pokazany raz, lista linków, revoke.
* **Flaga klienta** — checkbox w `EditClientModal` (`AppShell.tsx`),
  `cv_interactive_enabled` w `ClientUpdate`/`ClientSafeResponse` (BE).
* `lib/api.ts`: `cvGeneratedShareApi` + naprawa unii `AIFeatureKey`
  (dodane `order_parser` — dług z 0214 — oraz dwa nowe klucze).

## Schemat / migracja / safety-net

* Migracja `0217_cv_interactive_share` (down: `0216`): 2 wartości enuma
  `aifeaturekey` + seedy `ai_features`, tabele `cv_generated_share_tokens`
  i `cv_share_chat_messages`, kolumny `requirement_map*` na
  `cv_generated_documents`, `clients.cv_interactive_enabled`.
* Lustro w `backend/entrypoint.sh`: `_ENUM_STATEMENTS` (2×ADD VALUE),
  `_COLUMN_STATEMENTS` (kolumny + CREATE TABLE IF NOT EXISTS + indeksy),
  `_DATA_STATEMENTS` (2×seed).

## Kwoty / sterowanie na prod

Ustawienia → AI: dwa nowe kafle („Interaktywne CV — kafelki wymagań",
„— chat klienta"), każdy z toggle + limitem miesięcznym. Wyłączenie chatu
chowa go na WSZYSTKICH linkach (`chat_enabled=false`); wyłączenie kafelków
zatrzymuje generację map dla nowych CV. Env: `CV_REQUIREMENT_MAP_MODEL`,
`CV_REQUIREMENT_MAP_MAX_TOKENS`, `CV_INTERACTIVE_CHAT_MODEL`,
`CV_INTERACTIVE_CHAT_MAX_TOKENS`, `CV_INTERACTIVE_CHAT_DAILY_LIMIT`.

## Testy

`backend/tests/test_cv_interactive_share.py` (10):
lifecycle tokenu v2 (hash-at-rest, revoke-key ≠ access-key, max_views,
revoke), 409 dla nie-ready, blind maskuje nazwisko+firmy, payload bez
warnings, upload=classic-only, flaga klienta wyłącza interaktywność+chat,
walidator mapy (parafraza odrzucona, met→partial, no_data dla brakujących,
zły experience_index→null), chat: injection→odmowa bez LLM, dzienny
limit→429. Zaktualizowany `test_ai_settings_schemas.py` (8 kluczy).
Uruchomione lokalnie w obrazie prod na czystym Postgresie (migracje 0001→0217
przechodzą): **10/10 + 206 testów generatora + kontrakt authz zielone**.

## Znane ograniczenia / świadome decyzje

* Mapa wymagań generuje się tylko dla NOWYCH generacji — historyczne CV mają
  link classic-only (regeneracja CV dobuduje mapę).
* `GET /generated` nadal listuje globalnie dla `CandidateDocumentAccess`
  (istniejący quirk #9 audytu — nie ruszany w tym PR).
* Chat odmawia przy KONKRETNYCH kwotach w odpowiedzi (defense-in-depth) —
  może to złapać legalne „budżet 2 mln EUR" z treści CV; rzadkie, świadome.
* Ocena statusu kafelka (met/partial) jest oceną AI — ale każdy dowód to
  zweryfikowany substring CV, a status bez dowodów nie może być „met".
