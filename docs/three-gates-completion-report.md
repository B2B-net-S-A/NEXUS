# Trzy rubryki rekrutacji — raport wdrożenia (09.2026)

> Program „AI ma czytać, nie wybierać". Decyzja właściciela (Artur, 07.09.2026).
> Plan źródłowy: `~/.claude/plans/zaplanuj-wszytsko-sobie-jak-async-emerson.md`.

## Dlaczego

Rekrutacja w body-leasingu stoi na trzech rubrykach: **technologie must-have**,
**stawka PLN/h**, **obecność w biurze** (dni/tydz. + miasto). Klient nie weźmie
na rozmowę kogoś bez must-have; ponad budżet nie ma marży; „tylko zdalnie" na
ofertę biurową odpada. To są bramki, nie preferencje.

Stan przed zmianą:

| Rubryka | Po stronie kandydata | Po stronie oferty | Czy była bramką |
|---|---|---|---|
| must-have | wypełnione (Fala 3 CV) | 87% kolumny `must_skills` | **nie** — 6,67 pkt ze 100 |
| stawka PLN/h | 8 853 z 55 217 | `rate_budget_hourly`, rzadko | tak (od 19.08), ale bez danych |
| dni w biurze | **pola nie było** | domyślna `hybrid` z importera | **nie** |

Trzy defekty, każdy cichy:

1. **`on_site` vs `onsite`.** Formularz kandydata zapisywał tryb jako `on_site`,
   backend porównuje z `onsite` i nie walidował. Kandydat zaznaczony
   „Stacjonarnie" był w scoringu liczony jako **odmawiający biura** i był
   niewidoczny w filtrze „Stacjonarnie".
2. **Stempel Traffita.** Importer wbijał `remote_policy='hybrid'` na INSERT
   każdej importowanej oferty (~99% korpusu). To fabrykuje sygnał: warstwa
   lokalizacji czyta „znana hybryda", a `/ai-matches` z automatu ukrywa na
   takiej ofercie kandydatów „tylko zdalnie".
3. **Champion wiedział, kod nie.** Profil Championa niósł stawkę, dni w biurze,
   tryb i miasto biura — czytał je wyłącznie generator uzasadnień. Scoring,
   dealbreakery i bramka handoffu patrzą na KOLUMNY oferty.

Własny pomiar z 15.08 pokazał skalę dźwigni: dołożenie dwóch rubryk z Championa
do scoringu dało **P@5 +67%, R@20n +87%**. Nie nowy model — rubryki.

## Co weszło

### Migracja `0278_office_presence_rubric` + lustro w `entrypoint.sh`

Numer **0278**, nie 0277 — ten zajął `0277_recruitment_allocation` zmergowany
w trakcie prac. Lustro w `entrypoint.sh` jest obowiązkowe: prod alembic bywa
osierocony, więc to safety-net jest realnym mechanizmem wdrożenia schematu.

**Schemat:** `candidates.max_onsite_days_per_week`, `jobs.onsite_days_per_week`;
`jobs.remote_policy` traci `NOT NULL` i domyślną `hybrid`. ORM traci też
**pythonowy `default=`** — bez tego SQLAlchemy przestemplowałby `None` z powrotem
na `hybrid` przy każdym INSERT, czyli „nieznane" nie dałoby się zapisać.

**Cztery jednorazowe naprawy danych** (S1 idempotentna po predykacie, S2–S4
z markerem w `app_settings`; S2 **przed** S3, bo S3 uzupełnia tylko puste):

- **S1** — `preferences.remote_modes`: `on_site` → `onsite`.
- **S2** — zdejmuje stempel `hybrid` z ofert Traffita, **z wyjątkiem tych,
  którym tryb ustawił człowiek** (wykrywane po `activities.details ? 'remote_policy'`;
  `details` jest JSONB, więc operator `?` istnieje — gdyby był zwykły JSON, całe
  S2 wywalałoby się po cichu w `try/except` entrypointu, a deploy byłby zielony).
- **S3** — Champion → kolumny oferty (`rate_value`→`rate_budget_hourly`,
  `onsite_days_per_week`, `work_mode`→`remote_policy`, `candidate_location_pref`→
  `location`), FILL_EMPTY, oba kształty JSONB (nowy `basics.*` i legacy płaski).
- **S4** — kandydaci z notatkowym `remote_only=true` → `max_onsite_days_per_week = 0`.

### Kontrakty i formularze

- Walidator `preferences` na wejściu API: `remote_modes` tylko z enuma (422),
  normalizacja `office_cities`, `max_onsite_days_per_week` odrzucane **wewnątrz**
  `preferences` (jest kolumną — jeden dom, nie dwa).
- **PATCH kandydata scala `preferences` płytko** zamiast nadpisywać: klucz
  z payloadu wygrywa, nieobecny zostaje, jawny `null` kasuje. Dotąd formularz
  modelujący cztery klucze kasował każdy inny przy zapisie telefonu.
- Modal kandydata: naprawiony `onsite`, dwa nowe pola (maks. dni w biurze,
  lokalizacje biura). Formularz oferty: dni w biurze, tryb bez domyślnej
  („— nie ustawiono —"), etykieta „Miasto biura", czyszczalny budżet.
- `champion_job_sync.fill_job_columns_from_champion` wołane przy **każdym**
  zapisie profilu i przy ingest z pliku. Mapowanie trybu pracy jest
  **prefiksowe** (`zdaln`/`hybryd`/`stacjonar`), bo `work_mode` Championa to
  wolny tekst, nie enum. Liczby akceptowane też jako tekst — tym samym wzorcem
  co SQL backfillu, żeby obie ścieżki kwalifikowały ten sam zbiór wartości.

### Ekstrakcja z notatek (`v4-onsite-days`)

Prompt dostał `preferences.max_onsite_days_per_week` (tylko wprost podana
liczba; „tylko zdalnie" = 0). `apply_insights` wypełnia kolumnę FILL_EMPTY —
nigdy nie nadpisuje wartości człowieka. Bump `PROMPT_VERSION` jest **darmowy**:
selekcja do przeliczenia idzie po dacie notatki vs stempel ekstrakcji, nie po
fingerprincie, więc korpus się nie przelicza.

### Bramki rankingu

`apply_dealbreakers` dostało trzy nowe powody — must-have, dni w biurze, miasto
biura — obok istniejących (budżet, tylko-zdalni). Wpięte w **pięć** powierzchni:
`/recommendations`, `/ai-matches`, Talent Radar, snapshot propozycji i digest.

Zasady, które trzymają to uczciwym:

- **Nieznane przechodzi.** Kandydat bez sygnału umiejętności, bez deklaracji dni
  albo bez tokenów lokalizacji NIGDY nie jest ukrywany.
- **Ukrywanie nigdy ciche.** `hidden_meta()` ma pięć liczników, a każdy renderuje
  się jako osobny chip we wszystkich czterech powierzchniach front-endu.
- **`warn` (konflikt klienta / NDA / konkurent / weto HM) są ZWOLNIENI**
  z dealbreakerów i widoczni z powodem — reguła C2, nietknięta.
- Kill-switch `RUBRIC_DEALBREAKERS_ENABLED` (domyślnie `true`) przywraca
  poprzednie zachowanie bez redeployu.

### Bramka handoffu — i dlaczego są DWIE funkcje

`job_handoff_blockers` = brief + trzy rubryki; używa jej „Przekaż do searchu"
i ekran gotowości. `job_readiness_blockers` = **sam brief**; używa jej
automatyczna alokacja rekrutacji (`recruitment_allocation`).

**Rozdzielenie jest celowe.** Rubryki dorzucone do wspólnej funkcji zatrzymałyby
automatyczną alokację dla każdej rekrutacji, która ich nie ma — czyli po cichu
wyłączyłyby świeżo wdrożoną, cudzą funkcję, której ta zmiana wcale nie dotyczy.
Objaw byłby niewidoczny: żądania parkowałyby się z powodem `brief_not_ready`.
Złapały to dopiero testy alokacji, nie testy handoffu. Granica jest zamrożona
testem kontraktowym — nie zwijaj tych funkcji z powrotem w jedną.

### Etykiety rubryk na wierszu `/ai-matches`

`required_skills` bierze się teraz z **kolumny** `must_skills` → stack Championa
→ narracja → dopiero na końcu regex po treści wymagań (`required_skills_source`
mówi, z którego źródła). Wiersz niesie `rate_fit`, `office_fit` i `missing_must`,
liczone tymi samymi predykatami, które ukrywają — więc etykieta i bramka nie
mogą się rozjechać.

### Za flagami (domyślnie OFF — merge nie zmienia produkcji)

- **`STRUCTURED_POOL_ENABLED`** — pula wybierana SQL-em po must-have zamiast
  wektorem. Sedno: `websearch_to_tsquery` nie ma nawiasów, więc AND-of-OR składa
  się operatorem tsquery `&&`, po jednym bindzie na rodzinę must; rodzina
  zwijająca się do pustego stringa jest **pomijana**, nigdy AND-owana (pusty
  tsquery nie pasuje do nikogo i wyzerowałby pulę). Członkostwo z SQL,
  podobieństwo nadal z `similarity_for_candidate_ids` — skala semantyczna, cache
  i kalibracja nietknięte. Flagi celowo POZA `_SCORING_CACHE_INPUTS`.
  Do A/B: `--structured-pool` w `scripts/eval_matching.py`.

### `/ai-matches` przez fasadę puli i na wspólnym silniku (uzupełnienie)

Do 09.2026 `/ai-matches` — jedyna powierzchnia, którą rekruter naprawdę ogląda
na stronie rekrutacji — pobierała pulę **z pominięciem fasady**, wołając
`search_candidates_semantic` wprost. Skutek: żadna dźwignia retrievalu jej nie
dotyczyła, w tym świeżo dodana pula SQL-first po must-have. Objaw byłby cichy —
A/B na zamrożonym zbiorze ofert pokazywałby wpływ strategii, a ekran produktu
i tak jechałby na starej puli. Teraz woła `retrieve_candidate_pool` z kompletem
argumentów (`query_variants`, `bm25_query`, `must_groups`), a strażnik AST
`test_all_pool_sites_go_through_the_facade` obejmuje **sześć** callsite'ów
zamiast pięciu (zweryfikowane mutacją: przywrócenie bezpośredniego wywołania
wywala strażnika).

Przy flagach retrievalu OFF fasada deleguje do `search_candidates_semantic`
wywołanie za wywołanie, więc samo przekierowanie nie zmienia odpowiedzi. Jedna
różnica jest zamierzona: wiersze bez ZMIERZONEGO kosinusu (`semantic_unknown`)
są odrzucane, bo stara ścieżka porównuje kosinus wprost z progiem — zostawione,
weszłyby jako najsłabsze dopasowania puli, czyli awaria dosypki podszyłaby się
pod zmierzony brak dopasowania.

**`AI_MATCHES_SHARED_ENGINE`** (domyślnie OFF) przełącza tę listę na kompozyt
0–100 liczony przez `bulk_get_or_compute` — ten sam silnik, którym liczy
`/recommendations`, snapshot handoffu i digest. Powód: zakładka rekrutacji
renderuje dwie listy opisane tym samym słowem „dopasowanie", a liczone dwoma
różnymi miarami (kompozyt ważony profilem vs surowy kosinus Qdranta z puli 100),
więc te same dane potrafiły dać dwie różne kolejności bez żadnego sygnału dla
rekrutera.

Co się przy tym NIE zmienia i dlaczego: `match_score` zostaje na skali **0–1**
(`total / 100`), bo czyta go `MatchScoreBar` (×100), parametr `min_score`
(ge=0, le=1) i zamrożony `JobShortlist.score_snapshot`. `search_type` to
`semantic+composite` — musi zaczynać się od `semantic`, inaczej front uzna
odpowiedź za zdegradowaną. Domyślna podłoga pod flagą to
`RECOMMENDATION_MIN_SCORE/100`, nie 0.5: kompozyt hybrydowy ma niski zakres
bezwzględny, więc stare 0.5 odsiałoby większość realnych dopasowań. Awaria
dostawcy nadal schodzi na ranking po tagach — flaga nie odbiera ścieżki
ratunkowej. `AI_MATCHES_RERANK_TOP_N` (0 = off) zmienia wyłącznie KOLEJNOŚĆ
czołówki, nigdy `match_score`.

Obie flagi są widoczne w `/api/admin/ai-matching/diagnostics` — dźwignia, której
nie da się zaobserwować, przestawia się na ślepo.

## Weryfikacja

- `ruff check app/` + `ruff format --check app/` — exit 0.
- `alembic heads` — dokładnie jedna: `0278_office_presence_rubric`.
- Migracje na czystej bazie + celowany pytest per commit — exit 0.
- **Test regresji metodą porównania LIST NAZW** (nie liczb): identyczny szeroki
  przebieg (~149 plików, ~2450 testów) na naszym stosie i na czystym `main`.
  Zbiór awarii **identyczny** — 27 failed + 1 error, te same nazwy, wszystkie
  zastane (`test_proposals.py`, `test_shortlist_and_proposal.py`,
  `test_marketplace_flow.py`). **Zero regresji.**
- Front: `tsc --noEmit`, `next lint`, vitest — exit 0.

## Co operator musi zrobić po wdrożeniu

1. **`/api/health/deep` musi zwrócić 200.** Dryf kolumn daje 503 i czerwony
   deploy — to działa jako bramka. Baseline sprzed wdrożenia: `healthy`, deep 200.
2. **Włączyć pętlę czytania notatek**, jeśli nie chodzi: `GET /api/admin/traffit/sync/status`
   (faza `notes_insights`); jeśli wyłączona — workflow „Coolify set env" z
   `key=NOTES_INSIGHTS_SYNC_ENABLED`, `value=true`, **`redeploy=false`**
   (redeploy przy zmiennej runtime = awaria), potem jeden zwykły deploy.
   Pierwszy bieg ręcznie: `POST /api/admin/notes-insights/sync`.
3. **Pomiar przed flipem flag rankingowych.** Na serwerze, na zamrożonym
   zbiorze 50 ofert z Championami (`/root/champ-eval-ids.txt`):
   `python -m scripts.eval_matching --job-ids $(tr '\n' ',' < /root/champ-eval-ids.txt) --jobs 50 --pool 1000`,
   potem to samo z `--structured-pool`. Porównać P@5 / R@20n / MRR i udział
   ground-truth w puli. Flip `STRUCTURED_POOL_ENABLED` dopiero po tym.

## Zmiana zachowania, którą zauważysz od razu

S3 wypełnia `rate_budget_hourly` na ofertach z Championem, więc istniejący od
19.08 twardy sufit budżetu zacznie na nich działać: rekruter zobaczy **mniej**
kandydatów, z chipem „Ukryto N powyżej budżetu oferty". Nieznana stawka nadal
przechodzi. To jest zamierzone — stawka jest rubryką, nie podpowiedzią.

## Znane ograniczenia

- **`onsite_days_per_week == 0` przy hybrydzie/stacjonarnie** jest traktowane
  jako wartość ZNANA (np. „hybrydowo, bez ustalonej liczby dni"), więc nie
  blokuje handoffu, a bramki dni/miasta są wtedy no-opem.
- **FILL_EMPTY jest jednokierunkowe.** Późniejsza zmiana stawki w Championie nie
  podąża do `rate_budget_hourly`, gdy kolumna jest już ustawiona.
  `resolve_job_budget_hourly` i tak preferuje kolumnę, więc rozjazd nie ma
  efektu na scoring — widać go tylko w formularzu oferty.
- **Same regiony w lokalizacji** (`Mazowieckie` bez miasta) nie dają tokenu
  miejsca, więc bramka miasta ich nie oceni — kandydat przechodzi jako „nieznany".
- **Filtr `min_onsite_days` istnieje tylko po stronie API** — bez kontrolki
  w panelu filtrów listy kandydatów. Świadomie: dodać, gdy kolumna się zapełni.
- **Trzy zbiory testów padają niezależnie od tej zmiany** i tak samo na `main`:
  `test_proposals.py` (fixture wysyła `level: 4` zamiast wartości enuma),
  `test_shortlist_and_proposal.py` (nieunikalny e-mail kandydata koliduje sam ze
  sobą), `test_marketplace_flow.py` (błąd zbierania). Nie naprawiane tutaj —
  poza zakresem, ale warte osobnego zgłoszenia.
