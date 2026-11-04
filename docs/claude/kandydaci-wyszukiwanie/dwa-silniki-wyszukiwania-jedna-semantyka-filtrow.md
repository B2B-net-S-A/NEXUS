# Dwa silniki wyszukiwania — jedna semantyka filtrów (09.2026)

NEXUS ma DWA silniki wyszukiwania kandydatów, które UI połączy w jeden ekran
„Kandydaci": **L** = `GET /api/candidates` (lista, ⌘K, eksport, alerty
zapisanych wyszukiwań) i **S** = `POST /api/search/candidates` (+ `/diagnostics`;
`/candidates/search` i ręczne szukanie w rekrutacji). Do 09.2026 rozjeżdżały się
w 11 miejscach (`docs/sesja-2026-07-28-completion-report.md`). Filtry wspólne
buduje WYŁĄCZNIE `app/services/candidate_search_predicates.py` — oba endpointy
czytają je stamtąd (także warianty legacy), prywatne kopie są zakazane
(`test_candidate_search_predicates.py` czyta źródła). Sortowanie, stronicowanie,
retrieval hybrydowy i diagnostyka zostają przy endpointach.

- **`semantics_version` rozstrzyga WSZYSTKO. Brak pola = v1 = DOKŁADNIE
  dotychczasowe wyniki każdego endpointu, łącznie z rozjazdami** (lista wycina
  osoby bez stawki/lokalizacji/stażu i czyta samą kolumnę `location`;
  wyszukiwarka dopasowuje tag podłańcuchem, liczy tylko kategorię główną, łączy
  „Otwarty na" koniunkcją, nie czyta koszyka Traffita i nie przełącza `q`
  wyglądającego na osobę). Całe nowe zachowanie jest opt-in: `semantics_version: 2`
  (pole w S, parametr w L) — wtedy oba silniki odpowiadają identycznie.
  Dowody: `test_saved_search_legacy_replay.py` (31 ładunków legacy; ten sam plik
  przechodzi na `origin/main` sprzed zmiany i po niej) oraz
  `test_search_engines_contract.py` (każda decyzja w v2: ten sam zbiór id z L i S).
  **Nie zmieniaj zachowania v1 „przy okazji" — na nim stoją alerty.**

Semantyka v2 (decyzje właściciela produktu, wiążące dla OBU endpointów):

| Filtr | Reguła v2 |
|---|---|
| Umiejętności | trzy kubełki: „Musi mieć" = TWARDO · „Mile widziane" = tylko ranking (także na liście — prowadzi każde sortowanie) · „Wyklucz" = TWARDO; bez kubełka → „Musi mieć". Jawne pola: `skills_required[]`, `skills_required_any_groups` (S: lista list; L: powtarzany parametr `a\|b`), `skills_preferred[]`, `skills_excluded[]`. `a\|b` = grupa LUB w KAŻDYM polu. Tag „java" nadal spełnia umiejętność „Java" (tagi są częścią zrzutu). |
| Tekst `q` | `text_mode: auto\|literal\|semantic`. Auto: e-mail, telefon, 2–3 wyrazy wyglądające na osobę → dopasowanie DOSŁOWNE (to samo w L i S: `literal_text_clause`); JEDNO słowo dosłownie TYLKO, gdy istnieje kandydat o takim imieniu, nazwisku albo członie nazwiska dwuczłonowego („Kowalska" → „Nowak-Kowalska") (`person_token_exists`: jedno `LIMIT 1` po indeksie trigramowym `search_doc_unaccented`, pamięć 60 s); reszta → tryb wybrany przez rekrutera. **v2 + `text_mode=auto` (`person_text_match`, #1904 i poprawka 29.09.2026):** osoba o dokładnie takim imieniu/nazwisku istnieje (bez polskich znaków; człon nazwiska z myślnikiem się liczy; 2–3 wyrazy = imię i nazwisko w dowolnej kolejności) → WYŁĄCZNIE takie osoby (`exact_person_filter`: jedno `IN (SELECT … trigram ILIKE po słowach AND równość)`, nigdy `OR` z gałęziami frazy — to wyłącza semi-join; bez prefiksu „Nowak” → „Nowakowski”, bez e-maila, firmy i notatek), `text_match: "exact"`; nikogo takiego nie ma → 2–3 wyrazy albo jedno słowo z końcówką nazwiska (`looks_like_surname`, bez przymiotników języków i regionów) dosłownie Z literówkami, `text_match: "similar"` („Nie ma nikogo o tym nazwisku — pokazujemy podobne.”). `interpretation.rule` mówi, która reguła zadziałała. W v1 auto działa tylko przy jawnym `text_mode`; bez `text_mode` (alerty) — bez zmian. |
| Brak danych | osoba BEZ lokalizacji / stażu / stawki ZOSTAJE i jest oznaczona w `unknown_fields: ["location","experience","rate"]` (tylko dla AKTYWNYCH filtrów); `hide_unknown: true` ją ukrywa. Stawka w walucie innej niż PLN = nieznana. |
| „Otwarty na" | LUB; `open_to_*: false` zostaje osobnym, twardym warunkiem |
| Kategoria kompetencji | główna LUB poboczna (M2M) LUB legacy FK |
| Lata doświadczenia | jedna reguła przedziału: dokładna liczba, a gdy jej brak — koszyk Traffita |
| Tagi | cały tag (token JSON, bez wielkości liter), nie podłańcuch |
| Lokalizacja | `city` LUB `location`, `%`/`_` dosłownie, bez polskich znaków; kilka miast (`location_cities`) i kraj w obu |
| `q_all`/`q_any`/`q_none` | jeden parser (`parse_q_groups`; grupa jako lista albo `a\|b`); CAŁE słowa, gwiazdka `java*`/`*script` (`keyword_terms`) — v1 podłańcuch |
| status / dostępność | zgodne w obu wersjach — przypięte testem |

- **Pola legacy umiejętności znaczą w L i S co innego — w OBU wersjach.** L:
  `skills` (+`skill_combine`), `skills_any`, `skills_none` są TWARDE. S:
  `skills_must` + `skills_any` to „Mile widziane" (SEARCH-P0-03), twarde jest
  tylko `skills_none`. Zgodne są dopiero pola jawne.
- **Krótki tekst dosłowny (≤ 2 znaki) w v2 = całe słowo przez indeks**
  (07.10.2026, `advanced_candidate_search.short_literal_match`, wpięte
  w `literal_text_clause(short_whole_word=sem.unified)` w L i S): indeks
  trigramowy nie działa poniżej 3 znaków, więc „c#” dosłownie czytało całe CV
  i notatki (10–30 s na produkcji). Teraz korpus złożony (`keyword_fold_fts`,
  notatki `content_fold_fts`) + dokładne imię/nazwisko. v1 i wyłączony korpus
  złożony = podłańcuch jak dotąd.
- **Lista nie ma retrievalu wektorowego** (do połączenia ekranów): przyjmuje
  `text_mode`, ale zawsze dopasowuje dosłownie i mówi to w `text_mode_applied`.
- **Diagnostyka zna twarde kubełki**: grupa `skills_required` („Musi mieć") obok
  `skills` („Wyklucz"); nowa grupa filtrów = wpis w `NULL_POLICY`.
- **Parser wyrażenia umiejętności ma port w Pythonie** (`parse_skill_expression`)
  i WSPÓLNY plik przypadków `frontend/src/lib/__fixtures__/skill-expression-cases.json`.
- **Nowy wspólny filtr:** builder w `candidate_search_predicates` (z wariantem
  v1, jeśli filtr już istniał), wpięcie w OBU endpointach, przypadek w obu
  plikach testów. Kanoniczny fit (`canonical_fit`, `scoring_service`) NIE jest
  tą zmianą dotykany.

### Brak danych per filtr i kilka miast z promieniem (D5, D6 — 19.10.2026)

Zgłoszenie: „Stawka do 55 zł/h” + „Warszawa” → „25 kandydatów”, a w wierszach
„brak stawki” / „brak lokalizacji”. Filtr działał według v2 (osoba bez danych
zostaje, na końcu listy) — brakowało rozdzielenia na ekranie.

- **`hide_unknown_rate` / `hide_unknown_location`** (L i S, pola obok
  `hide_unknown`; `Semantics.rate_unknown` / `location_unknown`): `true`
  ukrywa braki TYLKO swojego filtru (miasto obejmuje też kraj). Brak / `false`
  = jak bez przełącznika, więc nigdy nie poszerzają wyniku — v1 i stare
  `hide_unknown` odpowiadają dokładnie jak dotąd (test parametryczny
  w `test_location_places_and_unknown_flags.py`). Globalne `hide_unknown`
  (`hu=1`, „Więcej filtrów”) dalej ukrywa wszystko, także staż. Front:
  wybór „pokaż na końcu listy / ukryj” w okienku Stawki i Lokalizacji,
  adres `hur=1` / `hul=1`, dopisek „· bez stawki: ukryte” na przycisku i chipie.
- **`known_match_count`** w odpowiedzi listy = ile z `total` spełnia aktywne
  filtry stawki / lokalizacji / stażu Z DANYMI (`_unknown_rank_expr == 0`).
  Tylko v2, bez globalnego `hide_unknown` i gdy któryś z tych filtrów może
  zostawić braki; inaczej `null`. Ścieżka „najpierw id” i dawna liczą go
  w TYM SAMYM oknie co `total` (`count(*) FILTER (WHERE …) OVER ()`, zero
  zapytań więcej); kolejność „Dopasowanie” trzyma w pamięci same id, więc tam
  to jedno `count` po tych samych filtrach (tylko przy aktywnym filtrze
  z brakami — kosztu na produkcji nie mierzyłem). Front: „2 spełniają filtr ·
  23 bez danych” zamiast „25 kandydatów”.
- **Kreska nad osobami bez danych** (`lib/unknown-divider.ts`): stoi nad
  pierwszym wierszem z `unknown_fields` TYLKO przy układzie „z danymi, potem
  bez”. Braki idą na koniec przy każdym sortowaniu (także `match` i
  `newest`), ale „Mile widziane” (`_preferred_rank`) prowadzi przed nimi —
  wtedy braki bywają w środku i kreski nie ma (kolejności nie zmieniamy).
  „Ukryj” na kresce włącza oba wąskie przełączniki (+ globalne, gdy pod kreską
  są braki stażu). Wiersz listy ma plakietki `UnknownFieldBadges` jak
  wyszukiwarka.
- **`location_places`** (powtarzany: `Warszawa:30`, `Łódź`; do 10, promień
  1–300, nieznana miejscowość z promieniem = 422 jak `UnknownPlace`; zły
  kształt = 422 `InvalidLocationPlaces` przed zbudowaniem filtrów, w eksporcie
  z walidacji ciała) = **SUMA**: miasto bez promienia (dopasowanie jak
  `location_cities`), promień KTÓREGOKOLWIEK środka (suma `keys_within`) albo
  województwo (`location_places_clause`). Pojedyncze `location`(+`radius`)
  i `location_cities` z tego samego żądania dokładają się do sumy.
  **Bez `location_places` nic się nie zmienia:** `location` i `voivodeship`
  łączą się dalej przez I (promień + województwo = część wspólna), na tym
  stoją stare adresy i alerty. Front: adres `locs=Warszawa:30|Łódź`; stare
  `loc`/`radius` czytane jak dotąd, okienko pokazuje je jako listę z jednym
  miastem, a zapis (`locationPlacesPatch`) zostawia jedno miasto bez
  województw w starym kształcie (to samo znaczenie). Nowe pola w zapisanych
  wyszukiwaniach jadą w `qs` i `api`, w formacie v3 w `list_only` (w obie
  strony, alert je odtwarza).
- **`location_distance`** w wierszu („Pruszków · 16 km (Warszawa)”):
  najbliższy środek promienia, w którym leży miejscowość osoby, liczony
  w Pythonie ze współrzędnych `pl_places` dla wierszy strony (zero zapytań).
  Nazwa środka w nawiasie, bo „od Warszawy” wymaga odmiany nazw miejscowości.
- **„Szukaj ręcznie”**: miasta rekrutacji zostają „Mile widziane”; w okienku
  Lokalizacji jest „Wstaw miasta rekrutacji”, które przenosi je do twardej
  listy (do limitu 10).

### Zapisane wyszukiwania: format v3 i migracja na wspólną semantykę

- **Jeden format zapisu** (`version: 3`, `semantics_version: 2`, `origin`,
  `request`, `qs` z `sv=2`, `legacy`, `migration`) i adapter czytający OBA
  formaty legacy: `app/services/saved_search_payload.py` ↔
  `frontend/src/lib/saved-search-unified.ts`, wspólny plik przypadków
  `__fixtures__/saved-search-unified-cases.json`. `request` ma kształt wspólny
  + `list_only` / `search_only` dla filtrów jednego silnika. Najstarszy format
  listy `{qs}` bez `api` jest nieczytelny po stronie Pythona — zostaje nietknięty.
- **Migracja (`services/saved_search_migration.py`)** porównuje wynik v1 i v2
  przez PRAWDZIWE endpointy (token właściciela, do 500 id + `total`).
  **Zapis z LISTY migruje z flagami neutralizującymi** (`neutralise_list_request`:
  `hide_unknown: true` + `location_scope: "location_only"`), więc zwraca
  DOKŁADNIE to, co dotąd, i alerty się nie poszerzają; zapis z WYSZUKIWARKI
  zostawia osoby bez danych widoczne (tak działał zawsze). Nowo tworzone zapisy
  biorą zwykłe domyślne v2. Identyczny wynik → po cichu; inny (to, czego flaga
  nie wyrazi: `%`/`_` w lokalizacji, cały tag, kategoria poboczna, „Otwarty na"
  = LUB, koszyk Traffita, `q`-osoba) → `requires_reapproval=true`, alert
  WSTRZYMANY (`filters.migration.alert_was_on`), `diff` z samych LICZB + kody
  reguł `diff.rules` (`saved_search_payload.RULE_*`; statyczne „reguły, które
  dotyczą tego zapisu", nie atrybucja per osoba) i JEDNO powiadomienie
  `saved_search_reapproval` (migracja `0336_saved_search_reapproval_notif` +
  lustro w `entrypoint.sh`). Idempotentna (v3 i zapisy przypięte do v1 są
  pomijane). Tryb hybrydowy z `q` nie jest odtwarzany (embeddingi). Nieaktywny
  właściciel → do akceptacji bez powiadomienia. Najstarsze `{qs}` bez `api` są
  tylko liczone (`unreadable_ids`).
- **Decyzja właściciela zapisu = istniejące `confirm_reapproval`**
  (`PATCH /api/saved-searches/{id}`) + `reapproval_choice`: `accept`
  („Zatwierdź nowe wyniki") wznawia alert i ZERUJE linię bazową
  (`last_scanned_at`) — pierwszy przebieg skanera zasiewa dziennik nowym zbiorem
  bez alertu, zero burzy `saved_search_match`; `keep_legacy` („Zostaw po
  staremu") przywraca ORYGINALNY ładunek z `filters.legacy` ze znacznikiem
  `keep_legacy_semantics` — zapis zostaje przy v1 (jedyny sposób na te same
  wyniki, gdy różnicy nie wyraża żadna flaga), linia bazowa zostaje, a kolejne
  przebiegi migracji go omijają (`pinned`). UI: panel w `SavedSearchesMenu`
  („Zmieniły się zasady wyszukiwania", liczby przed/po, kody przetłumaczone
  w `lib/saved-search-reapproval.ts`) — osobny od plakietki po wycofaniu
  stawek miesięcznych (tamten zapis nie ma `filters.migration`).
- **Uruchomienie:** `POST /api/saved-searches/migrate-semantics[?dry_run=true]`
  (admin; odpowiedź = liczniki + id) albo przy starcie skanera alertów, gdy
  `SAVED_SEARCH_SEMANTICS_MIGRATION_AUTORUN=true` (domyślnie OFF — migracja
  wstrzymuje alerty i powiadamia ludzi, moment wybiera człowiek). Paragon:
  `app_settings['saved_search_semantics_migration_v3']`.
- **Skaner alertów** (`alert_list_params`): v3 → ścieżka wspólna
  (`unified_to_list_params`, `semantics_version=2`), legacy → `filters.api` bez
  zmian. Zapis v3 z filtrami, których lista nie zna (`list_engine_gaps`: języki,
  źródła…), NIE jest odtwarzany — alert byłby szerszy niż zapis.
- **UI (od #1665, 22.09.2026) wysyła v2 domyślnie na OBU ekranach**: lista
  (brak `sv` = v2; do adresu trafia tylko `sv=1` zapisu „Zostaw po staremu”)
  i wyszukiwarka (`semantics_version: 2`, koszyki `skills_required` /
  `skills_preferred` / `skills_excluded`, `text_mode`, `hide_unknown`). Nowe
  zapisy idą w formacie v3. Stary stan (`?s=`, zapisy legacy) otwiera się
  przez adapter: `skills_must`/`skills_any` → „Mile widziane” (zawsze były
  tylko rankingiem), `skills_none` → „Wyklucz” (`lib/candidate-search-semantics.ts`).
  Migracja nie oznacza zapisów v3 z listy jako zmienionych
  (`list_payload_is_unified`).
- **Zapis z dawnej wyszukiwarki ręcznej otwiera się na liście** (surowe
  żądanie bez `qs` albo v3 z `origin: search_request`): `listQsFromSavedSearch`
  przekłada go `searchRequestToListFilters` — tym samym adapterem co stare
  adresy `?s=`. Do 25.09.2026 lista pokazywała natywny `alert()` z odesłaniem
  do „Wyszukaj manualnie” rekrutacji, a tego ekranu od #1815 nie ma. Dzwonek
  na takim zapisie nie przebudowuje filtrów (skaner i tak ich nie odtworzy),
  tylko prosi o zapisanie go ponownie z listy. Menu nie używa `alert()` —
  zamrażał kartę i automatyzację przeglądarki.
