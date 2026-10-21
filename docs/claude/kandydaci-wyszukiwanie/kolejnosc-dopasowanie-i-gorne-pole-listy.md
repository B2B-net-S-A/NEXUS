# Kolejność „Dopasowanie” i górne pole listy (25.09.2026)

Test na 120 rekrutacjach (`python -m scripts.eval_manual_search_order`, tylko
odczyt): przy „najnowsi” pierwsza strona „Szukaj ręcznie” zawierała osobę,
którą zespół potem zweryfikował, w 33% rekrutacji; przy dopasowaniu wektorowym
— 83% (wektor kolumny „Dop.”), cała baza bez wymagań — 80%. Proste sortowania
w bazie (ts_rank, słowa w profilu, świeżość CV) NIE pomagały — nie wracaj do nich.

- **`sort=match`** (`services/candidate_match_order.py`, przełącznik
  `CANDIDATE_MATCH_SORT`): w „Szukaj ręcznie” (jedna `recruitment_id` +
  `not_assigned`) wektor = `request_vector(build_request_context(job, profile))`
  — TEN SAM co `/scores`, więc kolejność zgadza się z kolumną „Dop.”; na liście
  — wektor słów z wierszy wymagań. Kolejność: „Mile widziane” → osoby z danymi
  przed brakami → osoby z wektorem wg podobieństwa → najnowsi (decyzje Artura).
  Zbiór > 30 tys. = 3 000 najbliższych z indeksu, reszta od najnowszych.
  Gotowa kolejność 5 min we WŁASNEJ, ograniczonej pamięci modułu (32 wpisy,
  LRU; klucz: filtry, wektor, osoba, odcisk kontekstu) — NIE
  w `app/core/cache.py`, który nie ma limitu ani sprzątania, a lista bywa
  długa na ~60 tys. id. Brak wektora/awaria = „najnowsi” i
  `sort_applied="newest"` w odpowiedzi — front mówi to zdaniem.
- **Osoby z rekrutacji odpadają przy ODCZYCIE strony, nie w kolejności**
  (K11/K5, audyt 06.10.2026): kolejność „Szukaj ręcznie” liczy się z filtrów
  bez `not_assigned` (`candidate_match_order.order_base_filters`), a
  `ordered_result` zdejmuje osoby z wierszem etapu w tej rekrutacji
  (`ids_in_job`). Do tej daty klucz pamięci miał sól z `max(stage.id)` —
  każde „Dodaj” liczyło kolejność od nowa, a strona 2 pomijała tylu ludzi,
  ilu dodano. Eksport (`ordered_ids`) i lista używają tej samej pamięci —
  obie budują zapytanie z `order_base_filters`.
- **Za ułożonym początkiem (top `CANDIDATE_MATCH_RERANK_TOP`) strona też
  dostaje pełną ocenę** (`rerank_page`, K10): osoby strony spoza początku są
  ułożone „Dop.” w obrębie strony i grup, niezmierzeni (także z nieaktualnym
  wektorem) na końcu grupy. Do 06.10.2026 od pozycji 201 była sama kolejność
  wektorowa i „Dop.” przestawało maleć.
- **„Trafność” bez tekstu = „Dopasowanie”** (K6,
  `_relevance_without_text_means_match`, lista i eksport): przy samych słowach
  kluczowych trafność liczyła podobieństwo trigramowe imienia do słów, czyli
  kolejność losową. „Mile widziane” (`q_preferred_group`) liczą się w tym samym
  zakresie pola co słowa kluczowe (`q_scope`).
- **Front** (`lib/url-filters.ts` `effectiveSort`/`matchSortAvailable`): bez
  tekstu i bez jawnego wyboru, przy wierszach wymagań albo w „Szukaj ręcznie”
  → `match`; jawne „Najnowsi” wygrywa. `ManualSearchPanel` bez wymagań
  w Championie NIE wpisuje już tytułu jako tekstu po znaczeniu (limit 200) —
  cała baza według dopasowania.
- **Górne pole**: przy „Szukaj” w trybie auto `GET /api/candidates/keywords/classify`
  (`keyword_suggest.classify_skills` — dokładna nazwa/alias ze słownika, każde
  słowo) zamienia same nazwy technologii na wiersze wymagań; słowo będące
  imieniem/nazwiskiem w bazie albo miastem ≥ 20 tys. zostawia tekst.
  Imiona/nazwiska sprawdzamy WYŁĄCZNIE przy `context=top` (górne pole;
  `classifyKeywords(text, "top")`) — K8, 06.10.2026: wiersz „SAP”, „Ada”,
  „Julia” nie był technologią, bo ktoś w bazie tak się nazywa.
  „Szukaj „…” po znaczeniu” cofa zamianę (tryb `semantic`). Wywołanie bez
  ponowień i z limitem 1,5 s — podpowiedź, nie bramka.

## W rekrutacji „Dopasowanie” bez grup „Mile widziane” (D1, 19.10.2026)

Zgłoszenie rekrutera: „AI search ma pokazywać najpierw najbardziej dopasowanych”.
W „Szukaj w bazie” i „Szukaj ręcznie” osoba z 61% stała nad osobą z 88%, bo
`order_rows` sortował najpierw po liczbie trafionych „Mile widziane” (must spoza
krytycznych, miasto rekrutacji, kategoria), a `rerank_within_groups` układał
„Dop.” tylko w obrębie tych grup.

- **Pomiar** (`python -m scripts.eval_manual_search_order --jobs 120 --rerank-top 200
  --groups`, produkcja tylko do odczytu, 19.10.2026; dwa pierwsze must wycinają jak
  krytyczne, reszta must to wiersze „Mile widziane”):

  | kolejność | ≥1 właściwa osoba na 1. stronie | właściwe w top 50 | MRR |
  |---|---:|---:|---:|
  | grupy must+miasto+kategoria → top 200 wg „Dop.” (do 19.10) | 68,3% | 33,3% | 0,255 |
  | grupy tylko po must → top 200 wg „Dop.” | 75,0% | 37,4% | 0,302 |
  | **top 200 wg „Dop.” bez grup (od 19.10)** | **85,8%** | **49,6%** | **0,416** |

- **Reguła:** `candidate_match_order.effective_prefix` — przy kontekście rekrutacji
  (jest „Dop.”) bez grupy „Mile widziane”; grupa braków danych zostaje (osoby, które
  przeszły filtr stawki/miasta tylko na brak danych, idą na koniec). Must spoza
  krytycznych, miasto i kategoria liczą się w samej ocenie (warstwy umiejętności
  i lokalizacji). Lista bez rekrutacji (brak „Dop.”) — grupy jak dotąd.
- **Wyłącznik** `CANDIDATE_MATCH_JOB_PREFERRED_GROUPS=true` przywraca kolejność
  sprzed 19.10 (zmiana przez workflow „Coolify set env”). Nie wracaj do grup bez
  nowego pomiaru tym samym skryptem.

## Panel „Ranking kandydatów” — wagi „Dop.” zmienia Head of Recruitment (21.10.2026)

Makiety: kanwa `LttSvWiuw2CLPPHU1jL7kN` (Jak to działa · Wagi z podglądem na
żywo · Pomiar na historii i historia zmian). Decyzje Artura 21.10.2026:

- **D1 — HoR publikuje sam, ale dopiero po pomiarze na historii.** Dostęp jak
  Cele KPI: zapis = admin albo Head of Recruitment z zapisem Insights
  (`HeadOfRecruitmentPlus` + bramka sekcji routera); odczyt panelu ma też
  Delivery Lead (`WeightsReader` w `api/scoring_weights.py`, lustro
  w `middleware.ts` i `settings-registry.ts`). Stare trasy CRUD profili
  (`POST/PATCH/DELETE /api/scoring-weights…`) zostają tylko dla admina —
  HoR nie może ominąć pomiaru.
- **D2 — edytowalne tylko trzy ważności** (podobieństwo CV, umiejętności,
  lokalizacja) i próg nocnych propozycji. Stawka (plakietka od 30.09)
  i dostępność (0 od 17.08) są zablokowane; bramki (krytyczne, „tylko
  zdalnie”) bez zmian.
- **D3 — tylko wagi ogólne.** Profile klienta i osoby zostają przy trasach
  admina; panel tylko ostrzega, że istnieją (`scoped_profiles`), bo wygrywają
  z wagami ogólnymi w `resolve_active_profile`.

### Jak to jest zapisane (`services/ranking_weights.py`)

- **Ważności nie sumują się do 100.** Udział warstwy = ważność / (suma trzech
  ważności + 15 za stawkę) — to samo, co liczy `base_fit_profile`. Do bazy
  idzie profil ogólny (`user_id`/`client_id` puste) z wagami rozpisanymi na
  90 pkt + 10 pkt screeningu, którego `base_fit_profile` nie czyta.
  Wbudowane 60/10/15/5/0/10 = ważności 60/10/5 bez zmiany żadnego wyniku.
  Odwrotnie (`panel_from_profile`) kotwicą jest waga stawki.
- **Szkic** (`app_settings['ranking_weights_draft']`) nic nie zmienia dla
  zespołu. Szkic równy opublikowanym = brak szkicu.
- **Próg nocnych propozycji** (`app_settings['auto_full_review_min_score']`)
  czyta `auto_full_review.publish_run_proposals` przez `nightly_min_score`;
  bez zapisu działa env `AUTO_FULL_REVIEW_MIN_SCORE`.
- **Historia** (`scoring_weight_changes`, 0501): publikacja z panelu i każda
  edycja profilu starymi trasami admina (`admin_edit`) — kto, kiedy, przed/po,
  powód, wynik pomiaru. `PATCH` profilu ustawia `updated_at` (kolumna nie ma
  `onupdate`).

### Pomiar i podgląd (`services/ranking_lab.py`, `ranking_publish.py`)

- **Składniki oceny liczone raz, wagi przeliczane bez AI.** Profil sondy
  (`PROBE`, 20 pkt na każdą z pięciu warstw) daje dla każdej osoby ułamek
  punktów warstwy, stosunek maksimum warstwy do wagi, flagę „oceniona”,
  warstwę wcześniejszych rozmów i mnożnik kar. `score()` składa z nich „Dop.”
  dla dowolnych wag dokładnie jak `score_candidate_job` (suma albo
  renormalizacja). Zgodność z silnikiem: `tests/test_ranking_lab.py` —
  zmiana składania wyniku w `scoring_service` = ten test na czerwono, popraw
  `_composite` razem z silnikiem.
- **Pomiar** = kolejność produkcji od 19.10 (wektor „Dop.” → 200 pierwszych
  wg „Dop.”) na 120 zamkniętych rekrutacjach z ostatnich 24 miesięcy (≥ 2
  „musi mieć”, ≥ 2 osoby zweryfikowane albo wysłane, które były w bazie przed
  otwarciem); dwa pierwsze „musi mieć” jako wiersze wymagań, baza cofnięta do
  dnia otwarcia, zweryfikowane wymagania zamaskowane
  (`score_candidates(reviewed_evidence=False)`). Miary: rekrutacje z właściwą
  osobą na 1. stronie, mediana miejsca pierwszej właściwej, właściwe w top 50,
  MRR, osoby ≥ progu z trafionym must w 200 pierwszych. Każda rekrutacja
  w osobnej sesji tylko do odczytu. Ten sam kod uruchamia
  `python -m scripts.eval_manual_search_order --weights skills=30`.
- **Zadanie w tle w procesie web, jedno naraz** (`ranking_publish.run`,
  `scoring_weight_measurements`). Wiersz bez znaku życia od 5 min czyta się
  jako przerwany (zwykle wdrożenie) — można od razu uruchomić nowy.
- **Publikacja** wymaga ukończonego pomiaru z odciskiem = opublikowane wagi
  + próg + szkic + `scoring_algorithm_version()` (inaczej 409). Spadek
  którejś miary w punktach procentowych (1. strona, top 50) o więcej niż
  2 pkt wymaga powodu (≥ 10 znaków, inaczej 422). Publikacja: profil ogólny
  w miejscu albo nowy „Wagi ogólne (panel)”, `mark_stale_for_profile`, próg,
  wiersz historii, usunięcie szkicu — w jednej transakcji. Otwarte pełne
  przeglądy dostają 409 przy odczycie (zmiana odcisku) i trzeba je przeliczyć.
- **„Przywróć”** = nowy szkic z wagami, które wprowadziła tamta zmiana; też
  przechodzi pomiar.
- **Podgląd na żywo**: `GET /api/scoring-weights/panel/preview/{job_id}` oddaje
  składniki 200 pierwszych osób zamkniętej rekrutacji (pamięć 15 min, klucz
  z wersją silnika), front przelicza kolejność sam. Lista rekrutacji do
  podglądu: `…/preview/jobs`.
