# Talent Radar i funkcje AI — audyt procesu i rozbieżności (2026-09-02)

> Zakres: jak działa Talent Radar (kod + przeklik na produkcji), jak działają
> pozostałe funkcje AI (Claude, Voyage/Qdrant, Ollama), gdzie się rozjeżdżają
> i co z tym zrobić. Audyt jest READ-ONLY — żadna poprawka nie została wdrożona.
> Każdy wniosek oznaczony „(prod)" został potwierdzony na żywym NEXUSIE
> 2026-09-02 (konto admin, klient Alior Bank S.A. / ALLCLOUDS, wersja `704bf46`).

## TL;DR

| | |
|---|---|
| Rozbieżności | **30** (2 × P1, 13 × P2, 15 × P3) |
| Talent Radar — czas wyszukiwania (prod) | 2,2 s · 3,0 s · 6,8 s · 11,0 s (pula 1996 → 20 wyników); `/api/health` w trakcie: 94–137 ms, pętla zdarzeń nie blokuje się |
| Parse profilu Championa (prod) | ~20 s (Haiku 4.5, prompt v5) |
| Ścieżki LLM poza bramką kwot | **4** ścieżki Claude (UoP check — potwierdzone na prodzie: licznik nie drgnął) + **wszystkie** powierzchnie Voyage/Qdrant (radar, rekomendacje, ai-matches, wyszukiwarka) |
| Funkcje AI bez sufitu (prod) | 14 / 14 — zgodne z decyzją 24.08, ale health ostrzega o tym na stałe |

**Dwa P1:**

1. **Radar czyta tylko początek wklejonego tekstu.** UI przyjmuje 20 000 znaków, silnik embeduje pierwsze **1200** i szuka umiejętności w pierwszych **4000** (`_build_job_text_v1`, `_extract_skills_from_champion` Tier 2). Potwierdzone (prod): 4726 znaków wstępu + wymagania na końcu → `skills: must 1/2 (z opisu)`, `matching_must: ["java"]` (z samego tytułu), sim 0,65 zamiast 0,73. Mail od klienta z wymaganiami na końcu jest rankowany po grzecznościach.
2. **Nazwa roli z profilu Championa ginie.** `talent_radar.py` czyta `parsed["role_name"]` (kształt promptu v3), a parser v5 zwraca `basics.role_name`. Skutek (prod): chip pokazuje „Profil wczytany" zamiast „Senior Java Developer (bankowość)", a request wyszukiwania **nie niesie `title`** — nazwa roli nigdy nie trafia do tekstu embeddingu.

## 1. Jak działa Talent Radar (stan faktyczny)

```
[UI] klient (wymagany) + tekst (≤20k) ALBO profil Championa (docx/pdf)
        + budżet PLN/h (prefill ze stawki profilu) + „ukryj wyłącznie zdalnie"
   │
   ├─ profil: POST /talent-radar/parse-champion → Haiku 4.5 (prompt v5, kwota champion_profile_parse)
   │          → champion_profile (7 sekcji) + must/nice + summary
   │
   ▼
POST /talent-radar/search  (20/min, każda rola, bez LLM, nic nie jest zapisywane)
   1. build_ephemeral_job → SimpleNamespace(id=None, client_id, title, description=text, champion_profile, must/nice=None*)
   2. _build_job_text → tytuł + description[:1200] + narracja Championa (+ must/nice gdy flaga*)
   3. retrieve_candidate_pool → Voyage query-embedding → Qdrant top MATCH_POOL_SIZE (prod: 2000)
      (HYBRID_POOL / MULTI_QUERY / CV_PASSAGES — OFF)
   4. _load_candidates (pełne wiersze, ~2000) → filter_eligible_candidates (blacklista, NDA, konkurencja, weto HM — per klient)
   5. apply_dealbreakers (twardy sufit budżetu, remote-only) → liczniki meta.hidden
   6. rank_candidates_for_job (bez cache): semantic 60 · skills 10 · salary 15 · location 5 · availability 0 · champion_fit 10
      must: job.must_skills → champion_profile.stack.must (Tier 0) → regex po narracji/JD (Tier 1-2) → tytuł (Tier 3)
   7. próg RECOMMENDATION_MIN_SCORE=40 → top_k=20 → _shape_result (salary bez liczb: redacted / not_applicable)
   ▼
[UI] MatchCard × 20 (max 8 chipów), „Przejrzeliśmy N, z czego M wolno zaproponować", „Ukryto K poza budżetem"
     snapshot w sessionStorage (powrót z profilu odtwarza formularz i wyniki)
```

`*` `TALENT_RADAR_STRUCTURED_SKILLS_ENABLED` jest na prodzie **OFF** (potwierdzone: `must_skills` w requeście nie zmienia `skills.reason`).

Czego radar świadomie NIE robi: nie woła LLM przy wyszukiwaniu, nie zakłada
rekrutacji, nie cache'uje wyników, nie stosuje boostu historycznego
(najsilniejszy sygnał rankingowy w `/recommendations`, 6× P@5 wg raportu
programu z 14.08) — bo nie ma `job.id`.

## 2. Rozbieżności — Talent Radar

| ID | P | Rozbieżność | Dowód | Kierunek naprawy |
|---|---|---|---|---|
| TR-1 | **P1** | Silnik czyta 1200 znaków (embedding) / 4000 (skills), UI obiecuje 20 000. | (prod) wstęp 4726 zn. + wymagania → `must 1/2 (z opisu)`, `matching_must=["java"]`, sim 0,65 vs 0,73 | Oferta efemeryczna ma nieść cały tekst (Voyage `truncation: true`, kontekst 32k tokenów) — sufit per obiekt zamiast stałej 1200/4000; do czasu naprawy licznik w UI ma mówić, ile silnik czyta. |
| TR-2 | **P1** | `summary.role_name` z klucza v3; parser v5 kładzie go w `basics`. Chip „Profil wczytany", request bez `title`. | (prod) `basics.role_name="Senior Java Developer (bankowość)"`, `summary.role_name=null`, body requestu bez `title` | `_summary_basics.get("role_name")` (jedna linia) + test na kształt v5. |
| TR-3 | P2 | Nice-to-have z profilu nigdy nie punktuje: Tier 0 zwraca tylko must, `job.nice_skills=None` przy fladze OFF. Chip mówi „5 nice". | (prod) `matching_nice=[]`, `gap_nice=[]` u wszystkich wyników | Tier 0 także dla `stack.nice` albo flip flagi (patrz TR-4). |
| TR-4 | P2 | Pola `must_skills`/`nice_skills` requestu to no-op (flaga OFF); docstring `parse-champion` twierdzi, że ranking „wywodzi wymagania z prozy" — od Tier 0 (09.2026) to nieprawda dla ścieżki profilu. | (prod) `must_skills=[Java, Kafka]` → nadal `must 11/12 (z opisu)`; profil → `must 6/7 (z Championa)` | Stan OFF flagi przestał znaczyć „jak przed zmianą" (Tier 0 już zmienia ranking). Zmierzyć flagę A/B metodą programu (P@5/R@20n) i podjąć decyzję; do tego czasu nie wysyłać pól z UI albo oznaczyć je jako nieaktywne. |
| TR-5 | P2 | API ma `location`, UI nie ma pola. Tryb tekstowy zawsze „lokalizacja nieznana" (3,2/5 dla każdego). | (prod) `location:"Warszawa"` → „lokalizacja OK" 4,1/5, pierwszy wynik zmienia się na osobę z Warszawy | Pole „Lokalizacja" w trybie tekstowym; w trybie profilu prefill z `candidate_location_pref`. |
| TR-6 | P2 | Warstwy strukturalnie nieoceniane w radarze wchodzą do budżetu: `champion_fit` zawsze 6,5/10 („brak screeningu" — radar nie ma pipeline'u), `availability` max 0. Wyniki skupiają się na 74–79, `fit_confidence` identyczne (0,571). | (prod) oba tryby | Profil wag dla radaru bez `champion_fit`, wynik prezentowany względem realnego maksimum (renormalizacja). Nie stroić wag — patrz raport programu 14.08. |
| TR-7 | P2 | Snapshot sesji nie niesie `championSkills`: po „Otwórz profil" → powrót → „Szukaj" request traci `must_skills`/`nice_skills`. Dziś bez skutku (flaga OFF + Tier 0), po flipie flagi łańcuch urwie się cicho. | (prod) body #3 = `{client_id, champion_profile, top_k, budget_hourly_max}` | Dopisać `championSkills` do `TalentRadarSessionState` + restore + test. |
| TR-8 | P2 | Tier 3 (tytuł) wstrzykuje „software developer" jako must; nikt tego nie ma → każdy kandydat dostaje gap i czerwony chip. | (prod) `gap_must=["software developer"]` we wszystkich sondach tekstowych | Lista słów-ról wykluczonych z derywacji must (developer, engineer, specialist…), a nie z taksonomii. |
| TR-9 | P3 | Chipy przycinane do 8, dopasowania przed brakami — przy ≥8 trafionych must braki znikają z karty. | (prod) tryb tekstowy: 8 zielonych, 0 czerwonych mimo gapu | Braki na początku albo gwarantowany slot na braki. |
| TR-10 | P3 | `salary.status="redacted"` (warstwa weszła do wyniku, liczby ukryte) nie ma żadnej reprezentacji w UI; komentarz w `TalentRadarResults` twierdzi, że warstwa jest zawsze `not_applicable`. Kandydat obniżony za stawkę nie widzi powodu. | (prod) tryb profilu: `status:"redacted"` | Krótki chip „stawka ponad budżet Championa" bez liczb + aktualizacja komentarza. |
| TR-11 | P3 | `seniority_note` (powód kary 16–32 %) nie jest serializowany w `ScoreBreakdown.as_dict()` — niewidoczny w radarze, rekomendacjach i zakładce Dopasowanie. Komentarz w dataclass obiecuje diagnozowalność. | kod: `as_dict` bez pola; grep FE: 0 użyć | Dodać do `as_dict` i wyrenderować (chip/tooltip). |
| TR-12 | P3 | Radar drukuje „z czego M wolno zaproponować" = licznik odsianych przez NDA/blacklistę/weto; `/ai-matches` świadomie NIE publikuje tej liczby („wyrocznia na NDA"). Ta sama reguła, dwie polityki. | kod: `talent_radar_search.as_meta` vs `matching.py` | Decyzja produktowa: albo obie powierzchnie pokazują, albo żadna (rekomendacja: nie pokazywać liczby, zostawić komunikat jakościowy). |
| TR-13 | P3 | Degradacja: radar zgłasza `semantic_unavailable` także przy zdrowym, pustym wyniku (`raise_on_error=False`); `/ai-matches` rozróżnia `no_semantic_hits`. | kod | `raise_on_error=True` + `SemanticSearchUnavailable`, jak w `/ai-matches` i `cv-upload-preview`. |
| TR-14 | P3 | Brak cache: każde wyszukanie (także identyczne) to pełny scoring ~2000 osób (2–11 s); `/recommendations` cache'uje per (kandydat, oferta, profil). | (prod) pomiary | Cache po (klient, hash tekstu/profilu, wersja scoringu) z krótkim TTL; opcjonalnie historia wyszukiwań. |
| TR-15 | P3 | Duplikaty osób w top-20 (ta sama osoba dwa razy, identyczny wynik). | (prod) tryb tekstowy | Zwijanie po fingerprincie tożsamości w `_load_candidates` + wsad do dedupu Cortexa. |
| TR-16 | P3 | Radaru nie ma w Ustawieniach → AI: koszt Voyage per wyszukanie nigdzie nie jest liczony, główny wyłącznik go nie zatrzymuje. Upload profilu liczy się pod etykietą „Odczyt profili Championa (Traffit)". | (prod) `champion_profile_parse` +1 po uploadzie | Patrz C-1 / C-10. |
| TR-17 | P3 | Dokumentacja: docstring `parse-champion` mówi „prompt v3" (jest v5); gałąź „forbidden" w `TalentRadarResults` jest martwa (backend nie zwraca 403 dla klienta). | kod | Sprzątanie przy najbliższym PR-ze w module. |

## 3. Inwentarz funkcji AI (jak działają dziś)

| Funkcja | Trasa / wejście | Model | Klient SDK | Kwota | `thinking` | Timeout FE |
|---|---|---|---|---|---|---|
| Uzasadnienie dopasowania („Dopasowanie") | `GET /candidates/{id}/scoring/{job}` | Sonnet 5 (`MATCH_SCORING_MODEL`) | `call_claude` | `ai_feature(scoring)` | disabled | 120 s |
| Podsumowanie aktywności | `POST …/activity-summary/refresh` | Sonnet 5 (`CANDIDATE_SUMMARY_MODEL`) | `call_claude` | `ai_feature` | disabled | 120 s |
| Generator ogłoszeń | `POST /ai/generate-job` | Sonnet 5 (literał `_JOB_WRITER_MODEL`) | `call_claude` | `ai_feature` | disabled | 120 s |
| Tworzenie kandydata z CV | `parse_cv` (candidates, cv-match-preview) | Sonnet 5 (`CLAUDE_MODEL_CV`) | `call_claude` | `ai_feature` gdy podano `db` | disabled | 120 s |
| — to samo z M365 (załączniki), Traffit (enrich-names), Cortex (cv_llm) | pętle w tle | Sonnet 5 | `call_claude` | **BRAK** (log „UNGATED") | disabled | — |
| Profil Championa AI (z JD / historii / spotkania / rozmowy, rekomendowane wyszukiwania) | `POST /jobs/{id}/champion-profile/*` | Sonnet 5 (`CHAMPION_AI_MODEL`; chunki: literał) | `call_claude` | serwis `ai_feature`; w `jobs.py` gołe `check_and_increment` | disabled | 120 s |
| Odczyt PDF zamówienia | `POST /clients/{id}/orders/extract` | Sonnet 5 (`ORDER_PARSER_MODEL`) | `call_claude` | gołe `check_and_increment` | disabled | nie zweryfikowano |
| Interaktywne CV — kafelki | tło po generacji | Sonnet 5 (`CV_REQUIREMENT_MAP_MODEL`) | `call_claude` | gołe, fail-open | disabled | — |
| Interaktywne CV — chat | `POST /public/cv-i/{token}/chat` | Haiku 4.5 | `call_claude` | gołe + limit 30/dzień | disabled | — |
| Masowe uzupełnianie pól z CV | admin, tło | Haiku 4.5 (`CLAUDE_MODEL_CV_BULK`) | `call_claude` | `ai_feature` | disabled | — |
| Fakty z notatek | pętla nocna | Haiku 4.5 (literał) | `call_claude` | `ai_feature` | disabled | — |
| Odczyt profili Championa (ingest + radar) | `POST /admin/champion-ingest`, `/talent-radar/parse-champion` | Haiku 4.5 (literał, prompt v5) | `call_claude` | `ai_feature` | disabled | 120 s |
| Generator CV B2B (+ CV próbne reguł) | tło po `POST /cv-generator/generate*` | **Sonnet 4.6 → Opus 4.8** (`CV_B2B_MODEL`, 16k tokenów, cache promptu) | **własny `ai_client`** | gołe w handlerze | env `CV_B2B_THINKING` | job async |
| Reguły CV — lint instrukcji | `POST /clients/{id}/cv-rule/lint` | Haiku 4.5 (`CLAUDE_MODEL_CV_BULK`) | **`ai_client`** | gołe, per pole | disabled | **60 s** |
| Sprawdzenie UoP (Generator Umów B2B) | `POST /b2b-generator/check-uop` | Sonnet 5 (literał) | **`ai_client`** | **BRAK** (prod: 15,4 s, licznik bez zmian) | disabled | **30 s (domyślny)** |
| MINDY (DynaReporter) | `POST /dynareporter/mindy/*` | Sonnet 5 przez `CLAUDE_MODEL_CV` | `call_claude` | `ai_feature` | **brak pinu** (prod: działa, 842 zn.) | — |
| Voyage/Qdrant: radar, `/recommendations`, `/ai-matches` (+rerank), wyszukiwarka semantyczna/hybrydowa, indeksowanie | — | voyage-3-large, rerank-2.5 | httpx | **BRAK klucza** | — | 120 s (część) |
| Ollama (fallback cv_parser, kryteria oferty, embeddingi) | — | llama3.2 / mxbai | httpx | — | — | — |

Stan prod (2026-09-02): master ON, 14 funkcji ON, wszystkie `monthly_limit=0`;
zużycie od 1.09: cv_generator 94, cv_requirement_map 89, notes_extraction 210,
order_parser 25, cv_backfill 19, scoring 0, candidate_summary 0, mindy 1 (test).
Flagi z diagnostyki: `AI_TEXT_SCHEMA_V2=false`, telemetria i outbox ON.
Ollama nie jest usługą w compose — fallbacki są martwe na prodzie.

## 4. Rozbieżności przekrojowe

| ID | P | Rozbieżność | Dowód | Kierunek naprawy |
|---|---|---|---|---|
| C-1 | **P1** | Kill-switch i kwoty nie obejmują: UoP check (surowy klient SDK, bez klucza), parsowania CV z załączników M365, backfillu imion z Traffita (`cv_backfill.parse_cv` bez `db`), ekstrakcji Cortex `cv_llm` — oraz wszystkich powierzchni Voyage. UI mówi „Wszystkie funkcje AI są wyłączone globalnie". | (prod) UoP: 200 po 15,4 s, `usage_diff={}`; kod: `test_ai_quota_provider_gate` pilnuje tylko gołych obciążeń i surowych klientów, nie ścieżek bez obciążenia | `AIFeatureKey.uop_check`; `db`/`ai_feature` w M365, Traffit, Cortex; klucz `matching` dla Voyage (osierocone wiersze `embeddings`/`matching` istniały w `ai_features`) albo uczciwy tekst wyłącznika. Test: każde `call_claude`/`analyze_with_ai` w kontekście deklaracji (uruchomić `AI_QUOTA_STRICT` w CI). |
| C-2 | P2 | Dwa stosy dostawcy: `call_claude` (90 s, 2 retry, health, bramka) vs `cv_generator_b2b/ai_client` (120 s, 3 retry, łańcuch modeli, cache promptu, bez deklaracji). Trzy funkcje na drugim stosie. | kod, baseline w teście | Dołożyć do `call_claude` łańcuch fallback + `cache_control`, zmigrować generator/lint/UoP, skasować baseline. |
| C-3 | P2 | Model konfigurowany trzema mechanizmami (typed Settings, `os.environ`, literały) i mylące nazwy: `CLAUDE_MODEL_CV` steruje MINDY i parserem CV; generator CV ma własny `CV_B2B_MODEL` przypięty do Sonnet 4.6 (rewert jakościowy #628) — decyzja żyje w komentarzu. Nigdzie nie widać, który model obsługuje którą funkcję. | kod | Rejestr modeli per `AIFeatureKey` (jedno miejsce, typed) + kolumna „model" w Ustawieniach → AI. |
| C-4 | P2 | Ucięcie odpowiedzi (`stop_reason=max_tokens`) obsługiwane per wołający: naprawa JSON (notatki, profil Championa), typowany błąd (generator CV), błąd parsowania → 502/503 (uzasadnienie, ogłoszenia), cichy skip (kafelki). `call_claude` nie sprawdza `stop_reason`. | kod | Centralne sprawdzenie w `call_claude` + typowany `ClaudeTruncated`. |
| C-5 | P2 | Pin `thinking: disabled` powtórzony w 12 miejscach, brakuje w MINDY (dziś działa, 400/800 tokenów bez rezerwy). | kod, (prod) | Domyślny pin w `call_claude`, opt-in dla wołających, którzy chcą thinking. |
| C-6 | P2 | Cache promptu tylko w generatorze CV; długie statyczne prompty systemowe (podsumowanie v2, uzasadnienie, kafelki, odczyt zamówień v4, Champion) idą bez `cache_control` przy każdym wywołaniu. | kod | `cache_control` na `system` w `call_claude` (próg 1024/2048 tokenów wg modelu). |
| C-7 | P2 | Timeouty FE: UoP 30 s (domyślny; wejście do 6000 zn., zmierzone 15 s na jednej linii), lint reguł 60 s (N sekwencyjnych wywołań). Lekcja #1210/#1211: każdy endpoint LLM na `SLOW_ENDPOINT_TIMEOUT_MS`. | kod, (prod) | Ujednolicić na 120 s; lint liczyć równolegle albo jako job w tle. |
| C-8 | P3 | Mapowanie HTTP: kwota → 503 wszędzie poza `recommended-searches/generate` (429); awaria dostawcy → 502 (podsumowanie, MINDY, uzasadnienie, Champion, chat) albo 503 (ogłoszenia, parse-champion, UoP); błąd parsowania odpowiedzi w ogłoszeniach raportowany jako „dostawca niedostępny". | kod | Jeden kontrakt: kwota → 503 + ten sam `detail`; dostawca → 503 + `Retry-After`; zła odpowiedź → 502. |
| C-9 | P3 | Health `ai_features: uncapped: <14>` ostrzega na stałe, choć decyzja 24.08 mówi „bez sufitów, alarm skoku" — lampka zawsze zapalona. Alarm liczy WYWOŁANIA, nie tokeny (generacja CV 16k tokenów = jedna linia MINDY). | (prod) health | Sonda ma sprawdzać, czy webhook alertu jest skonfigurowany; do `ai_usage_log` dopisać sumy tokenów (usage jest w każdej odpowiedzi `call_claude`). |
| C-10 | P3 | Etykiety Ustawień → AI: „Scoring kandydatów" gasi wyłącznie uzasadnienie LLM (ranking jest deterministyczny); „Odczyt profili Championa (Traffit)" liczy też radar; brak Voyage; brak modelu i kosztu. | (prod) panel | Przemianować, dodać model/tokeny, dopisać sekcję retrievalu. |
| C-11 | P3 | Polityka cache przy wyłączonej funkcji: podsumowanie aktywności → 503 nawet dla zapisanej notatki; uzasadnienie dopasowania → serwuje cache bez bramki. | kod | Jedna reguła (rekomendacja: cache czytelny, generacja zablokowana). |
| C-12 | P3 | Martwy łańcuch Ollama na prodzie: każda awaria Claude'a próbuje jeszcze HTTP na `localhost:11434` (szybki błąd, ale log „Ollama call failed" myli diagnozę). | compose bez usługi | Fallback Ollama tylko gdy `OLLAMA_BASE_URL` jawnie ustawione (bez domyślnego localhost). |
| C-13 | P3 | Wielokrotnie kopiowane sklejanie bloków tekstu / zdejmowanie ```` ``` ```` (7 kopii) — kolejny wołający znów to napisze. | kod | Helper `text_of(message)` w `claude_client`. |

## 5. Rekomendacje — kolejność

**Teraz (małe zmiany, duży skutek):**
1. TR-2 — nazwa roli z `basics` (1 linia + test). 
2. TR-1 — pełny tekst w ofercie efemerycznej (sufit per obiekt) + prawdziwy licznik w UI.
3. C-1 — cztery ścieżki Claude pod `ai_feature` (`uop_check` + `db` w M365/Traffit/Cortex), `AI_QUOTA_STRICT=true` w CI; klucz dla Voyage albo poprawny tekst wyłącznika.
4. C-7 — timeouty UoP i lintu na 120 s.

**Następny sprint (radar):** TR-5 lokalizacja, TR-6 profil wag radaru, TR-7 snapshot, TR-8 filtr słów-ról, TR-3/TR-4 decyzja o fladze po A/B (baseline OFF już nie równa się „przed zmianą"), TR-13 kontrakt degradacji.

**Następny sprint (platforma AI):** `call_claude` jako jedyny stos (C-2) z pinem thinking (C-5), `stop_reason` (C-4), `cache_control` (C-6), tokenami w `ai_usage_log` (C-9) i rejestrem modeli (C-3); panel Ustawienia → AI z modelem i kosztem (C-10).

**Backlog:** TR-9…TR-17, C-8, C-11…C-13.

**Czego nie robić:** nie stroić wag scoringu (ablacja 14.08: miksy w szumie; dźwignią jest retrieval i strona ofertowa) i nie przywracać marginesu budżetu (decyzja 19.08).

## 6. Metoda

Kod: `app/api/talent_radar.py`, `app/services/talent_radar_search.py`,
`scoring_service.py`, `retrieval_pool.py`, `embedding_service.py`,
`dealbreaker_filters.py`, `pipeline_eligibility.py`, `ai_quota.py`,
`claude_client.py`, `cv_generator_b2b/ai_client.py`, wszystkie moduły
z `AIFeatureKey` / `call_claude` / `analyze_with_ai`, FE `talent-radar-*`,
`api.ts`, `settings/ai`. Prod: 6 wyszukiwań radaru (3 tekstowe sondy API,
1 UI tekst, 2 UI profil), 1 parse profilu (docx), 1 UoP check, 1 MINDY,
`/api/health`, `/api/settings/ai`, `/api/admin/ai-matching/diagnostics`.
Sondy `/api/health` w trakcie wyszukiwania mierzyły blokowanie pętli zdarzeń.
