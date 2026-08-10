# Audyt gotowości: NEXUS jako wyszukiwarka talentów AI na profilu Championa

**Data:** 2026-08-07 · **HEAD:** `b4af6c58` · **Metoda:** mapowanie kodu (6 obszarów) + adwersaryjna weryfikacja + bezpośrednie pomiary na produkcyjnej bazie i w Qdrancie.

Istnieje też wersja wizualna raportu (opublikowana jako prywatny artefakt w sesji, link poza repo —
`.gitleaks.toml` traktuje każdy UUID jako potencjalny klucz Fireflies i celowo nie osłabiamy tej reguły
dla linku wygodowego). Ten dokument jest kompletny sam w sobie.

---

## Werdykt

**System nie jest zepsuty — jest nieuruchomiony i niezmierzony.** Pilotaż na 3 ofertach jednego
klienta jest wykonalny w ok. tydzień, ale jego celem ma być **pierwszy pomiar jakości po
rekalibracji**, a nie „wdrożenie wyszukiwarki".

Nic nie blokuje włączenia od strony konfiguracji: master toggle AI włączony, wszystkie 11 funkcji
`ai_features` `enabled=true`, `monthly_limit=0` (bez limitu), klucz Anthropic skonfigurowany,
Qdrant zdrowy. Przez cały czas życia systemu wykonano **23 wywołania AI** (`ai_usage_log`);
`champion_draft` — 3 razy, ostatnio 2026-06-11.

---

## Jak to działa

Profil Championa to JSONB przypięty do **jednej oferty** (`jobs.champion_profile`,
[job.py:147](../backend/app/models/job.py)), walidowany przez
[`ChampionProfile`](../backend/app/schemas/champion.py). Zawiera kontekst projektu, pytania
screeningowe z odpowiedziami wzorcowymi, insighty konsultanta, notatki sourcingowe i weryfikację
dwustronną. Zapis: `PUT /api/jobs/{id}/champion-profile` (DeliveryLeadPlus, pełny REPLACE z
zachowaniem 3 bloków stemplowanych serwerowo). AI nie pisze wprost — produkuje
`ChampionProfileSuggestion` (delta-patch per sekcja), którą DL akceptuje wybiórczo pod `FOR UPDATE`.

Generatory AI (wszystkie Sonnet 5, `CHAMPION_AI_MODEL`): z opisu oferty, z transkryptu Fireflies,
z rozmowy CloudTalk, z podobnych zamkniętych ofert. Plus piąty, osobny: `generate_recommended_searches`.

Po zmianie treściowej `refresh_job_matching`
([job_matching_refresh.py:55](../backend/app/services/job_matching_refresh.py)) re-embeduje ofertę,
unieważnia cache scoringu i oznacza ostatni snapshot jako stale.

### Dwa silniki — mocniejszy nie nazywa się „AI"

**A. Silnik semantyczny — `GET /api/jobs/{id}/recommendations`** (dojrzały)

```
narracja Championa → tekst embeddingu oferty (embedding_service.py:595-681)
  → Voyage voyage-3-large (1024 wym.)
  → Qdrant nexus_candidates
  → Voyage rerank-2.5 (RERANKER_ENABLED=true)
  → composite 0-100, 6 warstw (scoring_service.py)
  → próg RECOMMENDATION_MIN_SCORE=40, cap MATCH_MAX_RESULTS=200
```

Kalibrowany dwukrotnie: `SEMANTIC_CALIBRATION_GAMMA=0.6`, `SCORE_UNKNOWN_NEUTRAL_FRACTION=0.65`.
Twardy prefiltr uprawnień (blacklista/NDA/konkurent/weto HM), boost historyczny z guardem na
wyzerowane kary, łagodna degradacja przy awarii Qdranta (`meta.search_degraded`).

**B. Silnik leksykalny — „Rekomendowane wyszukiwania"** (słaby)

```
profil Championa → Claude (CHAMPION_RECOMMENDED_SEARCHES, llm_prompts.py:409)
  → RecommendedSearchParams (whitelista)
  → DL zatwierdza → SavedSearch
  → POST /api/candidates: ILIKE po search_doc/raw_cv_text + filtry SQL
```

**To jedyna funkcja zamieniająca profil Championa w wyszukiwanie ludzi — i jako jedyna nie dotyka
wektorów.** `RecommendedSearchParams` ([champion.py:174-201](../backend/app/schemas/champion.py))
nie ma pól `q` ani `search_mode`, a tryb hybrydowy włącza się wyłącznie przy
`search_mode=="hybrid" and bool(q_text)` ([search.py:290](../backend/app/api/search.py)).
Default to `"boolean"`. 47 921 wektorów leży na tej ścieżce odłogiem.

### Warstwa `champion_fit` nic nie różnicuje

`_score_champion_fit` ([scoring_service.py:955-996](../backend/app/services/scoring_service.py))
czyta `CandidateStage.screening_answers`. Kandydat, którego dopiero szukasz, żadnych nie ma → dostaje
neutralne `10 × 0.65 = 6.5` pkt. Pula wyszukiwania z definicji wyklucza osoby w pipelinie, więc
**każdy** wynik dostaje tyle samo. 10% budżetu to stała.

---

## Pomiary na produkcji (2026-08-07)

### Wypełnienie pól, po których wyszukiwarka filtruje i punktuje

| Pole | Wypełnione | % z 56 608 |
|---|---:|---:|
| `embedding_id` (Qdrant: 47 921 punktów) | 45 317 | 84,7%* |
| `raw_cv_text` | 39 178 | 69,2% |
| `competence_category_id` | 33 362 | 58,9% |
| `ai_summary` | 14 739 | 26,0% |
| `location` | 8 423 | 14,9% |
| `city` | 7 647 | 13,5% |
| `years_it_experience` | **670** | **1,2%** |
| `skills` (niepusta tablica) | **272** | **0,5%** |
| język ze znanym CEFR | **209** | **0,4%** |
| `expected_rate_hourly` | **0** | **0%** |
| `availability_status ≠ unknown` | **0** | **0%** |

\* wg Qdranta (47 921 punktów) — kolumna `embedding_id` ma 45 317, różnica ~2,6 tys. to dryf
(punkty bez odpowiadającego wpisu w bazie).

Kolekcje Qdranta: `nexus_candidates` 47 921 · `nexus_jobs` 3 862 · `nexus_cc_centroids` 5 ·
`nexus_pool_centroids` 84.

### Lejek jedynego prawdziwego wyszukiwania Championa

Zapisane wyszukiwanie #3 „Tester manualny/automatyczny — doświadczenie bankowe" (job 143770,
wygenerowane 2026-06-11):

| Krok | Zostaje |
|---|---:|
| baza | 56 608 |
| `raw_cv_text ILIKE '%bank%'` | 11 091 |
| `+ experience_years 2–6` | **45** |

`experience_years_min/max` to **twardy filtr nietolerujący NULL**
([structured_candidate_search.py:248-253](../backend/app/services/structured_candidate_search.py)) —
w odróżnieniu od `availability_date` (:295), `notice_period` (:309) i `rate` (:327) w tym samym
pliku, które NULL-e jawnie przepuszczają. Asymetria jest dowodem, że to przeoczenie, nie decyzja.
Prompt LLM wprost zachęca do emitowania tego pola ([llm_prompts.py:453](../backend/app/services/llm_prompts.py))
i model użył go we wszystkich trzech propozycjach.

Uwaga: `skills_must`/`skills_any` **są już miękkie** (tylko ranking, SEARCH-P0-03, :237-243) —
z komentarzem przyznającym, że kolumna jest pusta u ~99% importów. Doświadczenie zostało pominięte
przy tej naprawie.

### Świeżość indeksu wg kohorty

| Miesiąc | Nowych | Z embeddingiem |
|---|---:|---:|
| 2026-08 | 624 | 100% |
| 2026-07 | 4 270 | **20,0%** |
| 2026-06 | 4 644 | **0,02%** |
| 2026-05 | 13 181 | 75,5% |
| 2026-04 | 33 889 | 100% |

~7 900 kandydatów z czerwca–lipca nie istnieje dla żadnej ścieżki semantycznej.
`AI_INDEX_OUTBOX_ENABLED` i `AI_INDEX_WORKER_ENABLED` oba `False`
([config.py:76-77](../backend/app/core/config.py)) → embedding leci inline i może zostać po cichu
zgubiony; outbox miał być właśnie tą durability. Import Traffita kolejkuje reindeks tylko dla
**nowo wstawionych** — zaktualizowani i „adopted" nie trafiają do kolejki.

### Adopcja

| Obiekt | Sztuk |
|---|---:|
| `jobs.champion_profile IS NOT NULL` | **5** (wszystkie `closed`, ostatni 2026-06-16) |
| `champion_profile_suggestions` | 2 |
| `candidate_match_justifications` | 3 |
| `saved_searches` | 3 |
| `ai_usage_log` (łącznie) | 23 |
| oferty `published` / `draft` / `closed` | 14 / 283 / 3 815 |

---

## Blokery

| Waga | Rzecz | Typ |
|---|---|---|
| bloker | Dziura w indeksie semantycznym (~8,7 tys. bez wektora, rośnie codziennie) | dane |
| bloker | Twardy filtr lat doświadczenia: 11 091 → 45 | kod |
| bloker | Uprawnienia — TAC prowadzący ofertę nie może utworzyć jej Championa (`DeliveryLeadPlus` na 4 endpointach) | proces |
| bloker | Zero żywych Championów; handoff 409 dla `closed`, `generate-from-history` deterministycznie martwy (≥2 zamknięte oferty z profilem u tego samego klienta) | dane |
| wysoka | Wyciek zakresu: `/api/champion-suggestions/{id}` sprawdza tylko rolę → `apply` **zapisuje** do profilu cudzego klienta; to samo `notes/link-job` (+ LLM bez kwoty) | kod |
| wysoka | Brak sufitu kosztowego; `enrich_from_meeting`/`enrich_from_call`/`parse_cv` omijają bramkę kwot i master toggle | konfiguracja |
| wysoka | Brak pomiaru od 2 rekalibracji — ostatni: 2026-05-10, P@5 = 0,167, R@20 = 0,151, werdykt NO-GO, na starym 5-warstwowym profilu wag | proces |

---

## Plan

### Fala 0 — odblokowanie (dni)

1. **Zmierz pokrycie i zdrenuj kolejkę** (S) — `GET /api/admin/index-coverage`, potem w Coolify
   **najpierw** `AI_INDEX_WORKER_ENABLED=true`. **Nie ruszaj** `AI_INDEX_OUTBOX_ENABLED` — flip
   samego outboxu bez workera pogorszy stan (pojedyncze edycje przestaną embedować inline).
   Komentarz w `config.py` sugeruje odwrotną kolejność i jest mylący.
2. **Dopisz do kolejki historyczną lukę** (M) — scroll Qdranta po id → różnica zbiorów z tabelą →
   `record_bulk_reindex` batchami po 5 000. **Nie** używaj `reembed_collections.py` (brak trybu
   „tylko brakujące", ładuje całą tabelę do pamięci).
3. **Zdejmij twardość z filtru doświadczenia** (S) — tolerancja NULL jak w sąsiednich filtrach;
   równolegle usuń `experience_years_*` z whitelisty LLM.
4. **Otwórz tworzenie Championa dla TAC** (S) — systemowo dla roli, nie per-user.
5. **Domknij zakres oferty** (S) — `_ensure_delivery_lead_job_visible` w 4 handlerach sugestii +
   `link-job`; tam też `check_and_increment`.
6. **Ustaw limity miesięczne AI** (M) — sufity dla `scoring` i `champion_draft`; bramka kwot dla
   3 omijających ścieżek; ujednolić 429 vs 503.
7. **Załóż pierwszego Championa na otwartej ofercie** (S, praca DL) — 3 oferty jednego klienta,
   pełna ścieżka do snapshotu. Test end-to-end, którego nikt nigdy nie zrobił.

### Fala 1 — jakość wyników (1–2 tyg.)

- **Podnieś sufit retrievalu + prefiltr w Qdrancie** (L) — payload punktu ma dziś tylko
  `{candidate_id, name, competence_category}`, więc filtry tną po pobraniu. Dodaj `status`,
  kategorię, token miasta, dostępność; pula 1 000–2 000; runda dobierająca. Spinaj z poz. 0.2.
- **Odpal harness ewaluacyjny + CI** (M) — baseline po naprawie indeksu; dopisz `verified` do
  `STAGE_RELEVANCE`, dołóż `filter_eligible_candidates` i `exclude_in_pipeline`.
- **Doprowadź weryfikację Championa do matchingu** (S) — `verification.*.insights/key_corrections`
  (jedyne pole, którego backend **wymaga**) nie są czytane przez `_build_job_text_v1` ani
  `_extract_skills_from_champion`; endpoint weryfikacji nie woła `refresh_job_matching`.
  Najtańszy wzrost jakości w backlogu.
- **Napraw asymetrie budżetu** (M) — pusta lista `nice` daje twarde 0/10, pusta `must` daje pełne
  20/20; wszystkie 3 ścieżki `_score_salary` zwracają tę samą stałą 7,8. Razem 22 pkt szumu.
- **Przebuduj `champion_fit` albo go usuń** (L) — rozdziel `screening_fit` (pipeline) od realnego
  `champion_fit` z profilu.
- **Wepnij kalibrację w klucz cache** (S) — gamma i neutral fraction nie wchodzą do
  `SCORING_ALGORITHM_VERSION`, mimo obietnicy „rollback bez redeployu".
- **Rozstrzygnij los `/ai-matches`** (S/M) — `_build_job_query` **nie zna Championa w ogóle** i
  filtruje tylko blacklistę. Najuczciwiej: usuń z UI, zostaw jako diagnostykę.

### Fala 2 — zaufanie i UX (2–4 tyg.)

- Wyszukiwarka ad-hoc „opis roli → ludzie" + „znajdź podobnych do tego kandydata" (L) — **żadne
  z tych nie istnieje**; klocki są (`cv_match_preview` to wzorzec), brakuje kompozycji.
- Akcja „nie pasuje" + telemetria (M) — `reject` z `reason_code` jest w słowniku bez emitera;
  `record_impressions` ma jedynego wywołującego w martwym orkiestratorze → mianownik CTR nie istnieje.
- Uzasadnienie AI przed przypisaniem + batch (M) — ograniczenie jest wyłącznie we froncie.
- Zbatchuj N+1 w scoringu (M) — warunek wstępny podniesienia puli.
- Puste stany czytające się jak utrata danych (M) — 4 instancje; przy braku semantyki **nie
  pokazuj listy**.
- Optimistic locking na profilu (M) — jedyna ścieżka zapisu bez `FOR UPDATE`.

### Fala 3 — skala i automatyzacja (1–2 mies.)

- Reverse-match: nowy kandydat → aktywne Championy (L, migracja).
- „Rekomendowane wyszukiwania" na tryb hybrydowy (M) — dodaj `q` + `search_mode` do whitelisty,
  `max_length` lustrzane do `CandidateSearchRequest`, `filters` w formacie skanera alertów.
- Trwała kolejka zamiast `BackgroundTasks` + reaper snapshotów (L).
- TTL i sygnał dezaktualizacji profilu (M) — bez tego adopcja wygaśnie w miesiąc.
- Dashboard skuteczności (L) — oceny draftów i kciuki są zapisywane i nigdzie nieużywane.
- Martwy kod: orkiestrator / schemat tekstu v2 / blue-green backfill (L) — decyzja binarna per element.
- Sonda Voyage w `/api/health` (M) — dziś zero trafień `VOYAGE` w `main.py`.

---

## Czego nie robić

1. **Nie włączaj outboxu przed workerem** — pogorszy stan, który miałeś naprawić.
2. **Nie kopiuj `.env.example` do Coolify** — deklaruje `VOYAGE_MODEL=voyage-3` przy kodowym
   `voyage-3-large`; nazwa modelu jest w `SCORING_ALGORITHM_VERSION` → skasuje cały cache.
3. **Nie strój gammy/neutral fraction w trakcie pilotażu** — nie unieważniają cache, dostaniesz
   mieszankę starych i nowych liczb.
4. **Nie włączaj alertów przed kalibracją** — próg targu 80 to przy obecnych sufitach warstw
   zdarzenie brzegowe; alerty bez kalibracji uczą ignorowania powiadomień.
5. **Nie pokazuj surowego score klientowi** — realny sufit ~70, potrafi przekroczyć 100, w 1/3
   składa się ze stałych.
6. **Nie traktuj `/api/health` jako dowodu, że AI działa** — `anthropic: configured` to obecność
   klucza; Voyage nie ma sondy.
7. **Nie używaj `/proposals/regenerate` jako obejścia bramki Championa.**
8. **Nie rób „wielkiego włączenia"** — kilka niezależnych trybów cichej awarii jest po objawach
   nieodróżnialnych.
9. **Nie odkładaj RODO**, jeśli pilotaż dotknie realnych kandydatów: wektory zawierają imię,
   nazwisko i 3 000 znaków CV, brak bramki zgód, punktu zablokowanego kandydata nie da się usunąć
   żadną ścieżką operacyjną.

---

## Załącznik: helpery użyte do pomiarów

```bash
# Zapytanie read-only do produkcyjnej bazy
ssh -i ~/.ssh/nexus_prod_root_ed25519 root@91.99.199.112 \
  "docker exec \$(docker ps --filter name=postgres --format '{{.Names}}' | head -1) \
   psql -U nexus -d nexus -A -F '|' -c \"SELECT ...\""

# Inwentarz kolekcji Qdranta (przez kontener backendu — Qdrant nie ma curl/wget)
ssh -i ~/.ssh/nexus_prod_root_ed25519 root@91.99.199.112 \
  "docker exec \$(docker ps --filter name=backend --format '{{.Names}}' | head -1) \
   python -c 'import os,urllib.request,json; ...'"
```

Wbudowana diagnostyka, której warto użyć zamiast SSH:
- `GET /api/admin/index-coverage` — pokrycie DB↔Qdrant + stan outboxu
- `GET /api/ai-matching/audit` (admin) — alembic, schemat, budżety profili wag, coverage
- `POST /api/candidates/diagnostics` — waterfall wykluczeń przy zerowym wyniku
