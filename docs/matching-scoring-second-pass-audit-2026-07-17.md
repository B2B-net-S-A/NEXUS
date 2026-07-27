# Moduł 3 — Matching/scoring: drugi przebieg audytu (świeże ustalenia)

## Audyt niezależny, ukierunkowany na to, czego NIE znalazł pierwszy przegląd Codexa

> Data: 2026-07-17 (Europe/Warsaw)
>
> Stan kodu: `origin/main` = `bdf5a75` (po merge'ach #776/#778 z pierwszego planu
> oraz równoległych M4/M5/M6/M7 i #815)
>
> Metoda: 12 równoległych agentów-soczewek czytających realny kod, z jawnym
> wykluczeniem całego rejestru ustaleń Codexa (M3-SEC-01…M3-CI-01) — celem były
> **wyłącznie nowe** defekty. Weryfikacja adversarialna przerwana limitem sesji,
> więc **każde ustalenie poniżej zostało ręcznie potwierdzone przez odczyt kodu
> na `bdf5a75`** (plik:linia + cytat). Findingi, których nie dało się jednoznacznie
> potwierdzić, są wypisane osobno jako „do weryfikacji", nie w rejestrze.
>
> Status: rekomendacja i rejestr; implementacja nie została rozpoczęta.

## 1. Streszczenie

Pierwszy przegląd (Codex) mapował **klasy** problemów całego modułu. Ten przebieg
szuka **konkretnych, nowych instancji** — zwłaszcza w miejscach, których pierwsza
lista nie objęła (routery `jobs.py`, ścieżki zapisu kandydata, sync Traffit,
generator championów, retrieval historyczny) oraz w regresjach z merge'ów M4/M6.

Najważniejsze nowe ustalenia:

1. **Skan marketplace crashuje i po cichu gubi WSZYSTKIE alerty joba**, gdy do
   jednej oferty pasuje ≥2 kandydatów — kolizja z partial-unique
   `ix_notif_dedup_daily`, bo notyfikacja właściciela joba idzie z
   `dedupe_resurface=False` i poza `try`. To nowy mechanizm (crash), inny niż
   znany M3-MKT-01 (duplikat/forever-unique na logu alertów).
2. **`POST /candidates/from-linkedin` wstrzykuje kandydata na dowolny etap**
   (w tym terminalny: hired/rejected/offer) z ciała żądania, omijając eligibility
   i bramkę pending-verification (M4 P0.4).
3. **Historical boost od-zeruje karę** — kandydat z blacklistą/konfliktem/
   wykluczeniem, którego scoring hard-zeruje do 0, dostaje z powrotem do 15 pkt
   i wraca na listę rekomendacji z dodatnim wynikiem (widoczny, gdy rekruter
   zejdzie progiem — kontrolka z PR B).
4. **Reużycie `_EMBED_TRIGGER_FIELDS` do inwalidacji cache** pomija
   salary/location/remote/deadline/**client_id** — edycja stawki lub przepięcie
   joba na innego klienta zostawia świeży cache ze starym wynikiem (w tym starą
   eligibility).
5. **Trzy ścieżki zapisujące wejścia scoringu nie inwalidują cache**: sync
   Traffit (status/skills/location — nawet blacklist), generator championów
   (`champion_profile` zasila must+champion_fit), oraz wewnętrzny wyścig
   `_upsert_breakdown` vs `mark_stale_*`.

Rekomendacja: to jest **kolejny pakiet containment/correctness** przed jakąkolwiek
migracją silnika — punkty 1–4 są P0/P1 z realnym skutkiem (utrata alertów, obejście
gate'ów, blacklist wraca, stale eligibility po zmianie klienta).

## 2. Metoda i granice

- Kod czytany z izolowanego `bdf5a75`. Każde ustalenie w rejestrze §4 ma potwierdzenie
  plik:linia (odczyt ręczny), nie tylko wskazanie agenta.
- Świadomie **wykluczony** cały rejestr Codexa. Gdy nowe ustalenie jest konkretną
  instancją znanej klasy (np. eligibility na read-surface = M3-ELIG-01), jest to
  zaznaczone i raportowane tylko, gdy wnosi nowy, actionable szczegół.
- Nie uruchamiano recompute, re-embedu, płatnych operacji AI ani nie dotykano
  produkcji. Stan alembic prod (istotny dla §4.12) nie był weryfikowalny stąd —
  oparto się na znanym stanie „orphaned ~0170".

## 3. Rejestr nowych ustaleń

| ID | Prio | Ustalenie | Plik |
|---|---|---|---|
| N-01 | P0 | Skan marketplace crashuje i gubi wszystkie alerty joba przy ≥2 matchach (`ix_notif_dedup_daily` + `dedupe_resurface=False` + notyfikacja poza `try`) | `services/marketplace_service.py:469`, `api/notifications.py:230` |
| N-02 | P1 | `from-linkedin` wstrzykuje dowolny (terminalny) etap z ciała, omija eligibility + pending-verification | `api/candidates.py:2370` |
| N-03 | P1 | Historical boost od-zeruje karę — blacklist/konflikt/wykluczenie wraca z dodatnim wynikiem | `api/recommendations.py:278` |
| N-04 | P1 | Inwalidacja cache reużywa `_EMBED_TRIGGER_FIELDS` → salary/location/remote/deadline/client_id nie markują stale | `api/jobs.py:997` |
| N-05 | P1 | Sync Traffit aktualizuje status/skills/location bez `mark_stale` — nawet blacklist nie zeruje starego wyniku | `services/traffit/importer.py` |
| N-06 | P1 | Generator championów (`apply`/`accept-section`) zapisuje `champion_profile` bez `mark_stale` (zasila must + champion_fit) | `services/champion_draft_service.py` |
| N-07 | P1 | `_upsert_breakdown` bezwarunkowo czyści `stale`, ścigając się z `mark_stale_*` → przed-edycyjny wynik przypięty jako świeży | `services/match_score_cache.py:104` |
| N-08 | P1 | `seeking-contractors`: 1 request = do 200 seryjnych embedów Voyage + ~30k nieskeszowanych scoringów; brak limitera | `api/recommendations.py:1311` |
| N-09 | P2 | Warstwa skills: pusty `must` → 100% budżetu, pusty `nice` → 0%; żadne nie używa konwencji 0.65 (niespójność cross-job) | `services/scoring_service.py:675` |
| N-10 | P2 | Query embedowane z `input_type="document"` w retrievalu historycznym (asymetria, jak naprawiono gdzie indziej) | `services/historical_jobs_retrieval.py:120` |
| N-11 | P2 | Trzy różne zestawy progów band (80/65/45 vs 80/60/40 vs 50) na ten sam wynik 0-100 | `components/{ds/MatchScoreBadge,v2/pages/DopasowanieTab,sourcing/ContractorMatchCard}` |
| N-12 | P1* | `job_shortlist_entries` (migr 0172) bez mirrora w `entrypoint.sh` — feature 500s, jeśli prod alembic osierocony ~0170 | `alembic/versions/0172_*.py`, `entrypoint.sh` |
| N-13 | P1 | M3-CI-01 nadal żywe: 9 plików testów matching poza slice CI — w tym te, które łapałyby N-01/N-03 (`test_marketplace_service`, `test_similar_job_candidates`, `test_proposals`) | `.github/workflows/ci.yml:98` |

\* N-12: P1 warunkowo — pewny defekt „brak mirrora", skutek zależy od realnego head'a alembic na prod.

## 4. Szczegóły

### N-01 (P0) — skan marketplace gubi wszystkie alerty joba przy ≥2 matchach

`_create_marketplace_notifications` woła `create_notification(..., dedupe_resurface=False)`
dla właściciela joba (`recruiter_id`) przy **każdym** dopasowanym kandydacie
(`marketplace_service.py:469`, w pętli `for cand in candidates`). Partial-unique
`ix_notif_dedup_daily` (migracja 0029) obejmuje
`(user_id, notification_type, related_entity_id, date_trunc('day', created_at AT TIME ZONE 'Europe/Warsaw'))
WHERE related_entity_id IS NOT NULL` — a `marketplace_match` zawsze ustawia
`related_entity_id=job.id`. Przy `dedupe_resurface=False` `create_notification`
robi surowy `db.add(notif)` (`notifications.py:230`), pomijając gałąź „update in
place" — więc **drugi** kandydat tego samego joba wywołuje `IntegrityError`.

Wywołania `_create_marketplace_notifications` i `_try_insert_alert_log` są **poza**
`try/except`, który obejmuje tylko `score_candidate_job` (linie 452–462). Wyjątek
zatruwa sesję async i przerywa pętlę skanu joba; że cały skan to jedna transakcja,
**rollbackuje się też pierwszy, poprawnie utworzony alert**. Sweeper jest wpięty na
żywo (`main.py:524`, `MARKETPLACE_ENABLED` domyślnie true).

Skutek: dla każdej oferty, do której pasuje ≥2 kandydatów powyżej progu, feed
marketplace **po cichu nie dostarcza żadnego alertu** (użytkownik nie widzi błędu —
tylko log `exception`). To nowy mechanizm względem M3-MKT-01 (tam: duplikat/race na
`uq_marketplace_alert_pair`).

Fix: właściciel joba to jeden odbiorca dla N kandydatów — albo notyfikacja
per-job powinna iść **raz** (agregat „N nowych matchy") z `dedupe_resurface=True`,
albo INSERT notyfikacji musi być `ON CONFLICT DO NOTHING`/objęty `try` per-para.
Notyfikacje + log przenieść do bloku odpornego na `IntegrityError` bez zatruwania
skanu.

### N-02 (P1) — `from-linkedin` wstrzykuje dowolny etap, omija bramki

`create_candidate_from_linkedin` (`candidates.py:2341`, `RecruiterPlus`) bierze
`target_stage = data.stage or PipelineStage.new` (2370) wprost z ciała i przekazuje
do `_assign_candidate_to_job(..., stage=target_stage)`, który robi
`CandidateStage(stage=stage, ...)` bez żadnego sprawdzenia. Brak: eligibility
(blacklist/konflikt/NDA), bramki pending-verification (M4 P0.4 — przy stawce
powyżej `salary_max`), walidacji że etap należy do template'u joba i nie jest
terminalny. Rekruter może więc jednym żądaniem oznaczyć kandydata jako
`hired`/`contracted`/`rejected`/`offer`, omijając cały proces akceptacji. To
konkretna, wykonalna instancja klasy M3-ACT-01/M3-ELIG-01 (której Codex nie
przypisał do tej ścieżki). Fix: skierować przez wspólny command przypisania
(eligibility + dozwolone etapy początkowe + audit) i **odrzucić** etapy terminalne
z tego wejścia.

### N-03 (P1) — historical boost od-zeruje karę (blacklist/konflikt wraca)

`score_candidate_job` hard-zeruje `total = 0.0`, gdy `_check_penalties` zwróci
`blacklist`/`client_excluded`/`active_conflict` (`scoring_service.py:1006-1007`).
Ale w `recommendations.py:278-286` pętla dodaje boost: `b.total = round(b.total +
bonus, 2)` — **bez sprawdzenia `b.penalties`**. `boost_points_for_sources` daje do
`BOOST_MAX_SOURCES(3) × BOOST_POINTS_PER_SOURCE(5) = 15` pkt. Główna ścieżka
retrievalu (`candidate_ids` z `similarity_map` Qdranta) **nie filtruje statusu**
(tylko fallback DB filtruje `!= blacklisted`, linie 209-215), więc blacklistowany
kandydat z wektorem-widmem w Qdrant trafia do scoringu, zostaje wyzerowany karą,
po czym boost podnosi go do 15.

Przy domyślnym progu 40 nie przejdzie (15 < 40), ale rekruter ma teraz kontrolkę
`min_score` (PR B) — po zejściu ≤15 blacklistowany kandydat pojawia się z dodatnim
wynikiem, badge'em „Historia" i aktywnym „Przypisz". `sort(-r.total)` też miesza
ranking. To interakcja Phase-14 boost z systemem kar; jedyny bezpiecznik
(`total=0`) jest cicho pokonany. Fix: pomijać boost dla `b.penalties` (i docelowo
filtrować ineligible przed scoringiem — nieomijalna eligibility z M3-ELIG-01).

### N-04 (P1) — inwalidacja cache reużywa listy pól embeddingu

`jobs.py:997` woła `mark_stale_for_job` tylko gdy `_EMBED_TRIGGER_FIELDS & changed`.
Ten zbiór (68-80) = `{title, description, requirements, must_skills, nice_skills,
seniority, subcategory, industry, train_name}` — pola wpływające na **wektor**. Nie
zawiera `salary_min/max`, `location`, `remote_policy`, `deadline`, `client_id`,
które są wejściami **composite'u**: salary→warstwa salary, location/remote→location,
deadline→availability, `client_id`→**penalties** (client_excluded/active_conflict).

Edycja widełek płacowych albo przepięcie joba na innego klienta zostawia cache ze
starym wynikiem i **starą eligibility** — kanban `pipeline-scores` i
`/recommendations` serwują stary composite. To reużycie jednej listy do dwóch
różnych celów („co zmienia wektor" vs „co zmienia wynik"). Fix: osobny
`_SCORE_TRIGGER_FIELDS` (nadzbiór) dla `mark_stale_for_job`.

### N-05 / N-06 / N-07 (P1) — kolejne dziury inwalidacji cache

- **N-05 Traffit:** `services/traffit/importer.py` — zero `mark_stale`. Sync
  aktualizuje `status`, `skills`, `location`, `tags` (wszystkie wejścia scoringu),
  ale nie inwaliduje `candidate_job_match_scores`. Kandydat **zblacklistowany
  upstream w Traffit** zachowuje stary, nie-wyzerowany cache wynik do następnego
  triggera. (Wzorzec zgodny z regułą „każda zmiana wejść scoringu musi markować
  stale" — tu złamany na najczęstszej ścieżce zapisu w systemie.)
- **N-06 Champion:** `services/champion_draft_service.py` — zero `mark_stale`.
  `champion_profile` zasila must-skills i warstwę `champion_fit`
  (`scoring_service.py:441,658`), a apply-from-suggestion/accept-section zmienia je
  bez inwalidacji.
- **N-07 wyścig:** `match_score_cache._upsert_breakdown` (`:104`) bezwarunkowo
  ustawia `stale=False` przy zapisie. Gdy edycja joba markuje wiersze `stale=True`
  równolegle z trwającym recompute, zapis recompute (policzony na **starych**
  danych) nadpisuje flagę → przed-edycyjny wynik przypięty jako świeży. Brak TTL,
  więc nie samo-naprawia się w czasie.

### N-08 (P1) — koszt `seeking-contractors`

`recommendations.py:1311` — pętla `for cand in candidates:` woła
`search_jobs_semantic(query_text, ...)` per kandydat (embed Voyage + Qdrant search
na kandydata). Przy `page_size` do 200 i `horizon_days` do 180 jeden request to do
200 seryjnych, płatnych embedów + scoring każdej pary (kandydat × pula otwartych
jobów) w większości poza cache. Endpoint nie ma `@limiter.limit`. To nowa,
konkretna instancja klasy kosztowej — Codex M3-COST-01 dotyczył tylko bounds na
`/ai-matches`.

### N-09 (P2) — niespójne traktowanie braku danych w warstwie skills

`scoring_service.py:675-676`:
```python
must_pts = (len(must_match) / len(must) * must_max) if must else must_max   # pusty must → PEŁNY budżet
nice_pts = (len(nice_match) / len(nice) * nice_max) if nice else 0.0        # pusty nice → ZERO
```
Dwa przeciwne traktowania „brak kryterium" dla must vs nice, i żadne nie używa
konwencji `SCORE_UNKNOWN_NEUTRAL_FRACTION` (0.65) z pozostałych warstw. Job bez
must-skills (częsty po imporcie Traffit) daje **każdemu** kandydatowi pełne punkty
must → warstwa staje się szumem i zawyża wszystkich równo, psując porównanie
kandydat↔wiele-jobów. Odrębne od M3-SCORE-02 (tam: 0.65 daje punkty; tu: skills
konwencji w ogóle nie stosuje i jest wewnętrznie sprzeczne).

### N-10 (P2) — asymetryczny embedding w retrievalu historycznym

`historical_jobs_retrieval.py:120` — `generate_embedding(query_text)` bez
`input_type="query"`; domyślnie `"document"` (`embedding_service.py:191`). Voyage
3-large stosuje inne prompty instrukcyjne dla query vs document, więc zapytanie
embedowane w trybie document degraduje trafność retrievalu. Główne ścieżki
(`search_candidates_semantic`) używają `input_type="query"` poprawnie — ta została
pominięta.

### N-11 (P2) — rozjazd progów band w UI

Ten sam wynik 0-100 dostaje trzy różne bandy: `DopasowanieTab` (80/65/45),
`ContractorMatchCard` (80/60/40), `MatchScoreBadge` (≥50 = warning). Wynik 62 jest
„primary" na jednym ekranie, „amber/warning" na innym. Konkretna instancja FE
rozjazdu progów (Codex M3-UI-01 mówił o progach ogólnie). Fix: jedna centralna
polityka band/threshold (spójna z decyzją o skali po recalibracji).

### N-12 (P1 warunkowo) — migracja 0172 bez mirrora w entrypoint

`0172_job_shortlist_entries.py` tworzy tabelę `job_shortlist_entries`;
`grep job_shortlist_entries backend/entrypoint.sh` = 0. Zgodnie ze znanym stanem
(prod alembic osierocony ~0170), migracja może nigdy nie zaaplikować się na prod →
cały feature shortlist (`api/job_shortlist.py`) zwraca 500. Reguła
„każda tabela matching musi mieć idempotentny mirror w `entrypoint.sh`" jest tu
złamana. Akcja: potwierdzić realny head alembic na prod; jeśli < 0172 — dodać
mirror `CREATE TABLE IF NOT EXISTS` w `_COLUMN_STATEMENTS`.

### N-13 (P1) — testy poza bramką CI (wciąż)

9 plików testów matching istnieje, ale jest poza `pytest`-slice w `ci.yml`:
`test_marketplace_flow`, `test_marketplace_service`, `test_matching_location`,
`test_matching_skills`, `test_proposals`, `test_recommendation_competence_category_multi`,
`test_recommendation_filters`, `test_shortlist_and_proposal`, `test_similar_job_candidates`,
`test_similar_job_notify`. Kluczowe: `test_marketplace_service` łapałoby N-01,
`test_similar_job_candidates` — N-03, `test_proposals` — regresje snapshotów. Mimo
dodania `test_matching_containment` (PR A), obszary z dzisiejszymi nowymi bugami
nie są bramkowane. Fix: dopisać do slice (albo przejść na `pytest tests/` z
jawnym markerem live-server, zamiast białej listy).

## 5. Ustalenia „do weryfikacji" (nie potwierdzone jednoznacznie)

Zgłoszone przez agentów, ale nie zakwalifikowane do rejestru bez dowodu na `bdf5a75`:

- **`parse_cv` omija `ai_quota`** (`candidates.py:3635,3737`) — grep nie pokazał
  gate'u quota przed najdroższą ścieżką Claude, ale nie sprawdzono, czy `cv_parser`
  nie bramkuje wewnętrznie. Warte 10-min weryfikacji (jeśli prawda — kill-switch AI
  nie zatrzymuje parsowania CV).
- **`DopasowanieTab` `setQueryData(queryKey,…)` po `refresh`** (`:129`) — możliwy
  zapis uzasadnienia joba A pod klucz joba B przy przełączeniu w locie; semantyka
  callbacków React Query v5 niejednoznaczna bez testu — nie potwierdzam.
- **Ghost vector po hard-delete joba/kandydata** — brak ścieżki delete wektora;
  pokrywa się częściowo z M3-INDEX-01 (orphan vectors) i jest przyczyną N-03
  (blacklist w Qdrant). Zgłaszam jako kontekst N-03, nie osobno.
- Pozostałe P2 z surowej listy agentów (hardcoded `nexus_candidates` w 5 miejscach,
  centroid CC bez batchowania, `embed_candidate` nested commit, `/embed-diagnostics`
  dla viewera, `_canon_skill` zlepia C++/C#/C) — prawdopodobne, ale niższy priorytet;
  do przeglądu w osobnym przebiegu.

## 6. Rekomendowana kolejność

1. **N-01** (P0) — natychmiast: marketplace gubi alerty po cichu na żywym loopie.
2. **N-02, N-03** (P1 bezpieczeństwo/integralność) — obejście gate'ów i powrót
   blacklisty.
3. **N-04…N-07** (P1 poprawność cache) — jeden PR: rozdzielić score-triggery od
   embed-triggerów + `mark_stale` w Traffit/champion + naprawić wyścig
   `_upsert_breakdown`.
4. **N-13, N-12** (bramka jakości) — dopisać testy do CI i mirror migracji, żeby
   powyższe fixy były chronione i faktycznie działały na prod.
5. **N-08…N-11** (koszt + kalibracja + UI) — pakiet porządkowy.

Nic z tego nie wymaga nowego modelu, uczenia wag ani re-embedu — to dalszy
containment/correctness spójny z rekomendacją pierwszego przeglądu.
