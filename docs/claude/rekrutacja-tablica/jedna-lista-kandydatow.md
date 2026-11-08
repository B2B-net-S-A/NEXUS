# Jedna lista kandydatów zamiast zakładek
<!-- indeks: `SINGLE_CANDIDATE_LIST_ENABLED`, `services/single_candidate_list.py`, `merged_rows`, `job_autofill_pool` w panelu, `?list=`, `label_counts`, `labels`, `single-list-filters`, `dop_scale`, `dop_scores`, `fill_portal_scores`, `keep_all`, „Z portali”, „Zgłosili się” -->

Decyzja Artura z 08.11.2026, raport i makieta 3:
https://claude.ai/artifact/HgCGsxN7Nk7ENGpb6iNg2B. Kod siedzi za flagą
`SINGLE_CANDIDATE_LIST_ENABLED` (domyślnie `false`, włącza Artur przez „Coolify set env”).
`false` to panel z pięcioma zakładkami i zapisy sprzed zmiany.

Dlaczego: wyniki leżały w trzech miejscach (`job_autofill_pool` 34 025 wierszy,
`job_proposals` 54 698 otwartych z 3 224 duplikatami par, `proposal_snapshots` 348),
każda zakładka miała własną kolejność, a scraper portali liczył na innej skali niż „Dop.”
(ta sama para średnio 69 i 73, korelacja 0,5).

## Model: scalanie przy odczycie, bez migracji

`single_candidate_list.merged_rows(job_id)` to jedyna definicja wierszy. Czytają ją lista
(`page`, `split_counts`) i silnik kart (`ranked_picks` przez `engine_rows`). Puli nie
kopiujemy do `job_proposals`, bo 34 tys. wierszy wymieniałoby się co noc, a dzwonek,
liczniki i `expire_full_base` musiałyby ich unikać. Potrzebna byłaby też migracja CHECK-a źródeł.

- **Wiersz puli zachowuje się jak `full_base`:** ten sam próg i status pary. Pokazany wynik
  to najwyższy ze źródeł na skali „Dop.”, dowody z propozycji, a z puli tylko przy osobie bez propozycji.
- **Pula nie wskrzesza osób, których system nie doda** (`system_exclusions`: usunięci z rekrutacji,
  zatrudnieni, odmowa na cały klient, „Nie szuka pracy”), a para pominięta albo w rekrutacji
  nie stoi na liście jak dotąd.
- **Wygasła propozycja (`expired`) z wierszem puli wraca:** pula to najnowszy przegląd.
- **„Najlepsze 40” przestaje być górną granicą listy:** osoby z puli spod progu stoją pod
  separatorem „Poniżej N%”, do 150. Liczby na filtrach, kafle i zakładka liczą tylko od progu.
- **Poza listą bez zmian:** dzwonek „Do przejrzenia”, licznik listy rekrutacji i skrót DL-a
  czytają `job_proposals`, więc osoby tylko z puli się w nich nie liczą.
- Migawka rekomendacji i żywy przegląd scalają się na froncie jak dotąd (`mergeProposals`),
  jeden wiersz na osobę, za osobami ze skrzynki. Pod filtrem odpadają, bo plakietek nie znają.

## Kolejność

Jedna, liczona na serwerze (`_ordered`, `review_batch_order.order_cards`), bo stron nie da się
układać w przeglądarce: przepięcia, przekazania od praktykantów, potem osoby od progu (nowi w bazie,
bez uwag z co 5. miejscem dla osoby bez procesu, z uwagami, z brakiem krytycznej), na końcu
osoby spod progu. Pełne reguły dla 500 osób (`ORDER_WINDOW`), ale okno zawsze obejmuje przepięcia,
przekazania i nowych w bazie, a reszta stoi wg wyniku. Filtr „Znamy” liczy z całej listy.

- Uwagi liczy `_by_rules(keep_all=True)`: nikt nie odpada, powód staje się uwagą. Lista pokazuje
  ludzi, których system sam by nie dodał, i to człowiek decyduje.
- Pozycja na końcu należy się za brak **krytycznej** (`effective_critical`), nie za pusty
  `missing_must`: 293 z 381 osób z pierwszeństwem miało tam zwykłe „musi mieć” (`nowi-w-bazie-najpierw.md`).
- Front nie sortuje listy (`keepInboxOrder`), jawny wybór „Najpierw byli u tego klienta” zostaje.

## Plakietki i filtry

| Filtr (`?list=`) | Kto | Plakietka w wierszu |
|---|---|---|
| `applied`, „Zgłosili się” | dowód zgłoszenia do tej rekrutacji (`candidates_with_application_evidence`) | „Zgłosił(a) się” |
| `new_in_base`, „Nowi w bazie” | `new_in_base_picks`, te same osoby co silnik | „Nowy · N dni” |
| `portal`, „Z portali” | `POSTING_SOURCES` z ostatnich 7 dni, ten sam podział co kafel „Nowi z ogłoszeń” | „Z portalu” albo „Nowe CV” |
| `similar`, „Podobne” | źródła `reassign`, `similar_projects` | „↻ Przepięcie”, „Podobna” |
| `known`, „Znamy” | `known_queue_points`, punkty większe od zera | „Znamy” |

Osoba bez plakietki to „Z bazy”. Stare adresy działają: `?wintab=postings` to filtr „Z portali”,
`similar` to „Podobne”, `base` to pozostałe. Liczby przychodzą z `label_counts` i nie zależą od filtra.

**Nic nie znika.** „Szukaj w bazie” i „Szukaj ręcznie” zostają zakładkami. Sekcja „Nowi w bazie” i
„Ukryci przez »musi mieć«” stoją pod „Wszyscy”. Narzędzie przepięć (sugestie, własna rekrutacja,
pozostali) stoi pod filtrem „Podobne”, ze swoją stopką, gdy nikt nie jest zaznaczony na liście.
Zgłoszenia odłożone przez AI są pod „Zgłosili się” i „Z portali”. Awaria `…/proposal-counts` = stare zakładki.

## Portale na skali „Dop.”

`propose_candidates_for_job` (także `proposals/bulk`) przy włączonej fladze liczy `canonical_fit`:

- wektor aktualny: `score` = „Dop.”, a `evidence.dop_scale = true`;
- wektor nieaktualny albo awaria: `score` pusty, wiersz czeka na ocenę z kolejki CV
  (`fill_portal_scores` po `_write_pool` wypełnia tylko puste wiersze `job_board`). Do tego czasu panel liczy
  „Dop.” przez `/scores`, jak przy starych wierszach;
- liczba scrapera zostaje w `evidence.auto_match.score` i wraca jako `board_score`.

**`job_board` zostaje w `NON_CANONICAL_SCORE_SOURCES`:** 2 022 otwarte pary mają w `score` liczbę scrapera
i zdjęcie źródła pokazałoby ją jako „Dop.”. Skalę nowego wiersza rozstrzyga `dop_scale`. Próg `JJIT_MATCH_MIN_SCORE`
i kod scrapera bez zmian. `job_board` nadal nie dostaje karty bez człowieka.

„Pomiń zaznaczone” zakłada wiersz także osobie tylko z puli (`dismiss_pool_only`), a „Cofnij” dodania
oddaje jej propozycję `full_base` (`reopen_pool_only`), bo usunięcie z rekrutacji odcina wiersz puli.

Testy: `backend/tests/test_single_candidate_list.py`,
`frontend/src/lib/__tests__/single-candidate-list.test.ts`, `AddCandidatesPanel.test.tsx` (`jedna lista`).
