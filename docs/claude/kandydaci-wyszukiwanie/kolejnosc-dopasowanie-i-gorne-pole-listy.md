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
