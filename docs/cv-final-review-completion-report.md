# Niezależna kontrola AI wygenerowanego CV (GPT Luna, tryb doradczy)

Data: 18.09.2026 · Migracja: `0327_cv_factual_verification_quota`
Flagi: `CV_FINAL_REVIEW_ENABLED` (domyślnie **ON**), `CV_FINAL_REVIEW_TIMEOUT` (120 s),
`CV_FACTUAL_VERIFICATION_MODEL` (override modelu).

## Problem

Generator CV B2B miał gotowy, przetestowany weryfikator faktów
(`cv_generator_b2b/factual_verification.py`, 827 linii testów), który **nie
działał na produkcji** z dwóch niezależnych powodów:

1. **Przy generacji nie był wołany w ogóle.** Wywołanie siedziało wyłącznie
   w ścieżce v10 (`standalone_service.py:1787`), a produkcja stoi na
   `legacy_v7` (`CV_GENERATION_PIPELINE=legacy`, domyślne od awarii 10.09) —
   ta funkcja wraca ~250 linii wcześniej.
2. **Przy zatwierdzaniu był wyłączony flagą.** `CV_SOURCE_EVIDENCE_ENFORCED=false`
   → `cv_approval_review.py` zwracało `unverified / evidence_enforcement_off`.

Trzeci, najpoważniejszy merytorycznie problem: weryfikator jechał na
`AIFeatureKey.cv_generator`, czyli **tym samym modelem, który napisał CV**.
Badanie modeli z 16.09.2026 zmierzyło, że sędzia LLM faworyzuje własne wyjście
(~+30 pkt), więc kontrola własnej pracy jest systematycznie za łagodna.

## Decyzje (Artur, 18.09.2026)

| Pytanie | Decyzja |
|---|---|
| Model recenzenta | **GPT Luna** (`gpt-5.6-luna`), fallback Sonnet 5 przy 429/5xx |
| Niepotwierdzone twierdzenia | **Tylko ostrzeżenie** — CV zawsze powstaje, zatwierdzenie zawsze przechodzi |
| Włączanie | **Domyślnie ON**; `CV_SOURCE_EVIDENCE_ENFORCED` zostaje osobną, twardą bramką (domyślnie OFF) |
| Zakres | Generacja (legacy_v7 + v10) **oraz** zatwierdzanie edytowanego CV |
| UI | Ostrzeżenia w istniejącej liście + plakietka; w edytorze toast + trwały baner |
| Reużycie | `verified` z generacji zwalnia z drugiej recenzji niezmienionego CV |

## Co powstało

### Klucz AI `cv_factual_verification` (F18)
`models/ai_feature.py` (enum + etykieta + opis danych wysyłanych), migracja
`0327`, lustro w `entrypoint.sh` (`_ENUM_STATEMENTS` + `_DATA_STATEMENTS`),
wpis w `services/ai_models.py` (`default=GPT_LUNA`, `fallbacks=(SONNET_5,)`),
union w `frontend/src/lib/api.ts` (przy okazji dopisane brakujące
`experience_dates_on_demand`). Cena Luny i sonda `checks.openai` były już
gotowe — `providers_in_use()` wyprowadza dostawców z rejestru.

### Weryfikator: model, łańcuch, budżet, pełny raport
- `provider.analyze_with_ai` dostał `fallback_models`. **Bez tego Luna spadała
  na Opusa 4.8** — `fallbacks` były brane zawsze z klucza `cv_generator`,
  niezależnie od `model_override`. (Ten sam quirk mają dziś `uop_check`
  i `cv_rule_lint`; poza zakresem, ale wart osobnej poprawki.)
- `verify_final_cv(..., model, fallback_models, total_timeout)` — domyślnie
  model z rejestru; budżet monotoniczny dzielony między paczki po 40 twierdzeń.
- **Odrzucenia akumulowane po CAŁEJ pętli**, nie rzucane na pierwszej paczce:
  raport doradczy dla CV z trzech paczek milczałby o dwóch trzecich dokumentu.
  Błędy protokołu (niepoprawny JSON, brak pokrycia) nadal rzucają natychmiast.
- `FactualVerificationError.statuses` — mapa ścieżka → werdykt, żeby „brak
  dowodu" i „sprzeczne ze źródłem" czytały się różnie.

### `cv_generator_b2b/final_review.py` (nowy)
Jedyne miejsce z flagą, budżetem, rozliczeniem, etykietami pól i formatem
ostrzeżeń. Kontrakt: **`run_final_review` nigdy nie rzuca** — awaria recenzenta
daje `{"status": "unavailable"}` i jedno ostrzeżenie, nie brak dokumentu.
`legacy_v7/pipeline.py` dostał 6-liniowe, flagowane wywołanie (moduł zostaje
zamrożoną kopią), v10 używa tego samego helpera w trybie doradczym i zachowuje
starą gałąź blokującą przy włączonym egzekwowaniu.

Umiejscowienie w pipeline: **po** słowniku klienta, polityce prezentacji
i formacie dat, **przed** `deepcopy` do `render_payload` — raport opisuje
twierdzenia, które naprawdę trafią do dokumentu, i jedzie z nim do bazy.

### Rozliczenie osobnym kubełkiem
`_charge_final_review` + `_review_declaration_or_null` w czterech miejscach
(`_run_generate_new_job`, `_run_generate_upload_job` i ich bloki drugiej wersji
językowej). Deklaracja wchodzi w korutynie wołającej `run_in_threadpool` —
anyio kopiuje contextvary do wątku, więc tokeny recenzenta lądują na JEGO
operacji. `None` (flaga OFF / odmowa kwoty) nie wyłącza recenzji: liczy się
wtedy na kubełku generatora.

**Świadomie odrzucone:** naliczanie w handlerze i w snapshotcie joba —
dotykałoby `persist_job`, `execute_job`, `_run_declared`, `job_snapshot._TYPES`
i dwóch plików testów dla gwarancji bez wartości, odkąd `check_and_increment`
(17.09.2026) nigdy nie blokuje.

### Zatwierdzanie edytowanego CV
`prepare_approval_review`: skrót `evidence_enforcement_off` tylko przy OBU
flagach wyłączonych; braki źródeł w trybie doradczym **degradują**
(`advisory_source_unavailable`) zamiast odmawiać. `matches()` akceptuje
`verified` i `reviewed`. `execute_approval_review` płaci z nowego kubełka
i zwraca paragon z `findings` zamiast 422. `cv_approval_queue.state()` niesie
`findings_count`; obie ścieżki finalize zwracają `content_review_status`
i `content_review_findings`.

### Front
- `GeneratedCvItem.factual_review` (status + liczby; **bez ścieżek i cytatów**)
  → plakietka „Kontrola AI: OK / N uwag / niedostępna". `null` dla wierszy
  sprzed wdrożenia = nie rysujemy nic („niedostępna" znaczyłoby, że próbowała).
- `CvDraftSession.finalize()` zwraca werdykt; modal edycji pokazuje toast
  i **trwały bursztynowy baner** — znikający toast nie jest miejscem na listę
  rzeczy do sprawdzenia przed wysyłką CV do klienta.

## Weryfikacja

Backend w `nexus-deps-test:pytest-2026-09-16` (baza `nexus_cvreview`,
`alembic upgrade heads` z 0327):
- `test_cv_final_review_advisory.py` — **nowy**, 13 + 6 przypadków;
- pakiet dotkniętych modułów: 88 passed (legacy, approval, queue, worker);
- klucze/rejestr/lustro entrypointu: 56 passed.

**Mutacje (dowód, że testy mierzą):**
1. Podmiana recenzenta na model generatora → 3 testy czerwone
   (`test_the_reviewer_is_a_different_model_than_the_generator` i dwa dalsze).
2. Usunięcie baneru z modalu → 2 testy czerwone.

Front: `npm run lint` 0 błędów (172 ostrzeżenia, cap 300); vitest 30/30
(lista CV) i 13/13 (modal edycji). `type-check` w worktree pokazuje 9 błędów
z dryfu `node_modules` (brak `pdfjs-dist`, starszy tiptap) — wszystkie poza
diffem; baseline na `main` ma 12 błędów tej samej klasy. Czysty type-check
robi CI na własnym `npm ci`.

## Znane ograniczenia i dług

- **Koszt:** każda generacja to +1–3 wywołania Luny z pełnym CV i notatkami
  w każdej paczce. Po tygodniu sprawdzić Ustawienia → AI (kubełek
  `cv_factual_verification`) i rozkład `reason` w logach — szczególnie
  `invalid_schema`, bo OpenAI dostaje schemat z `strict:false` i autorytetem
  pozostaje lokalna walidacja `ReviewBatch`.
- **Provenance:** werdykt sędziego (nie egzekwowanie) poręcza teraz za
  niezmienione CV przy zatwierdzaniu.
- **`analyze_with_ai` i fallback:** `uop_check` oraz `cv_rule_lint` nadal
  dziedziczą fallback generatora (Opus 4.8) zamiast swojego z rejestru.
- **Nie powstało świadomie:** model „poprawiający" CV. Prompt weryfikatora
  wprost tego zabrania (`Never repair or rewrite claims`) — poprawiacz dopisuje
  własne fakty i wymagałby weryfikatora weryfikatora.

## Wdrożenie

Migracja 0327 + lustro w `entrypoint.sh` wchodzą z deployem; flagi nie są
wymagane (domyślne wartości są docelowe). `OPENAI_API_KEY` jest w Coolify od
16.09. Wyłączenie funkcji: `CV_FINAL_REVIEW_ENABLED=false` (workflow „Coolify
set env"). Po deployu sprawdzić: `/api/health` → `checks.openai`, jedna
generacja → `render_payload.factual_verification.model == "gpt-5.6-luna"`,
`GET /api/cv-generator/generated` → pole `factual_review`.
