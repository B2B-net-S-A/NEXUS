# Wyszukiwanie ręczne: podpowiedzi, przycisk „Szukaj”, pamięć (25.09.2026)

Makiety: https://claude.ai/artifact/6JCbPSp86E7uzAxcyNmqW4. Dotyczy listy
`/candidates`, „Szukaj ręcznie” rekrutacji (ta sama lista w trybie `embed`,
#1815) i starej wyszukiwarki `CandidateSearchView` (`?mode=search&job=`).

- **Zmiany filtrów czekają na „Szukaj”** (albo Enter w pustym polu słów / w polu
  tekstu). Lista trzyma szkic (`filtersSnapshot`) i zastosowane (`applied`);
  zapytanie, adres, eksport, zapis wyszukiwania i linki do profilu czytają
  `applied`. Od razu działa tylko sortowanie i strona przy tych samych
  kryteriach (`lib/candidate-list-staging.ts`, `carryImmediate`). Akcje „całe
  wyszukiwanie naraz” (zapisane, „Wstecz”, tryb tekstu, „Ostatnie
  wyszukiwania”) wołają `requestApply()`. W `CandidateSearchView` `draft` vs
  `request`, licznik `searchRequestChangeCount`.
- **Podpowiedzi** `GET /api/candidates/keywords/suggest` (`services/keyword_suggest.py`):
  słownik `skills` + aliasy w pamięci procesu (przebudowa w
  `refresh_alias_map`), stanowiska (zapytanie `/titles/suggest` zawężone do
  słowa od początku, jak `tekst*` — „git” nie podpowiada „digital …”),
  liczba osób z `keyword_fts` — osobne zapytanie na słowo (savepoint, limit
  czasu, pamięć 1 h), WYŁĄCZNIE dla pojedynczych słów i `jav*`: zbiorcze
  `count(*) FILTER (WHERE keyword_fts @@ …)` trwało na produkcji 3 s, a fraza
  (`java <-> developer`) 1,8–3,6 s, bo sprawdza pozycje w każdym wierszu —
  `null` = nie policzono, nigdy błąd. Stanowiska z pamięcią 10 min. Wstawiana jest nazwa kanoniczna; słowa
  kluczowe NIE rozwijają aliasów, więc alias to tylko wyjaśnienie. Wyjątek
  (decyzja Artura 25.09.2026, `keyword_suggest._label_word`): gdy podpowiedź
  trafia przez alias będący osobnym słowem nazwy („kafka” w „Apache Kafka”),
  wstawiane jest to słowo, a nazwa zostaje wyjaśnieniem — na produkcji
  „kafka” 4569 osób, fraza „Apache Kafka” 1704. Front:
  `ChipField`/`SkillBucketsField` z propem `suggest` (bez niego zachowanie jak
  dawniej), pobieranie bez react-query (`useKeywordSuggestions`, pole żyje też
  bez `QueryClientProvider`). W rekrutacji na górze must/nice Championa.
- **Pamięć** (`lib/search-memory.ts`, czyści ją wylogowanie): goły adres
  `/candidates` odtwarza ostatnie zastosowane wyszukiwanie tej karty
  (sessionStorage: filtry, przewinięcie, ostatnio otwarta osoba) z banerem
  „Nowe wyszukiwanie”; „Wstecz” do gołego wpisu to cofnięcie filtra, nie
  przywrócenie. Okno „Szukaj ręcznie” (`embed`) NIE czyta pamięci listy —
  pamięta własne wyszukiwanie per (osoba, rekrutacja) 30 dni, zapisuje je
  dopiero po działaniu osoby („Szukaj”, strona, sortowanie; samo otwarcie nie
  może przykryć nowych wymagań Championa), a „Wróć do filtrów z rekrutacji” je
  kasuje. „Ostatnie wyszukiwania” = 10 wpisów per osoba w localStorage (lista:
  `kind=list`, okno rekrutacji: `kind=job` + `jobId`, oba w formacie filtrów
  listy). Testy listy MUSZĄ czyścić pamięć w `beforeEach` — inaczej goły adres
  testu przywraca filtry poprzedniego.

### Słowa kluczowe = lista wymagań (decyzje Artura 25.09.2026)

Makiety: https://claude.ai/artifact/R56h63e1JEbSptnsaxrjk3. Zamiast trzech
woreczków („wszystkie / którekolwiek / żadne”, kolejne grupy były ukryte
w „Więcej filtrów”) jeden edytor wierszy (`RequirementRowsField`, logika
`lib/keyword-requirements.ts`): wiersz = wymaganie, słowa w wierszu = warianty
(LUB), wiersze łączy I, osobno „Wyklucz”; pod polami zdanie
`describeKeywordSearch`, które mówi, jak serwer przeczyta wyszukiwanie.

- **Na drucie każdy wiersz to grupa** `q_any` (adres) / `q_any_group` (API) —
  także jednowyrazowy (znaczy to samo co `q_all`), więc kolejność wierszy
  przeżywa odświeżenie. Stare `q_all` z zakładek i zapisów `decodeFilters`
  zamienia na wiersze na początku; `qAll` zostaje w typie wyłącznie dla źródeł
  spoza adresu. `CandidatesListV2` czyta adres tym samym `decodeFilters` (druga
  kopia parsowania usunięta). `|` w słowie = spacja (rozdziela słowa grupy).
- **Limity:** edytor 10 wierszy (`MAX_REQUIREMENT_ROWS`), serwer
  `_MAX_ANY_GROUPS` = 20 (zapas na stare linki — GET ucina nadmiar po cichu).
- **Podpowiedzi przy pomyłkach** (nic nie zmienia się samo, każda ma „Zostaw”):
  miasto (spis `pl_places` przez `/places/suggest`, ≥ 20 tys. mieszkańców —
  „Kotlin” to wieś) → „Ustaw lokalizację”; „senior/junior/mid/stażysta” →
  filtr stażu; „React / Vue”, „a lub b”, „a or b” → „Rozdziel” (ukośnik tylko
  ze spacjami — „CI/CD” to jedno słowo). W edytorze Championa tylko „Rozdziel”.
- **Warianty pisowni = przycisk, nigdy automat.** `keyword_suggest.skill_variants`
  dokłada do umiejętności `variants` (aliasy bez 1–2-znakowych, bez
  `scoring_service.POLISH_WORD_ALIASES`, bez aliasów zawierających pełną nazwę
  jako słowo — „java 11” znajdzie samo „java”; max 5); lista podpowiedzi ma
  osobną pozycję „Z wariantami” (wybieralną klawiaturą, bez przycisku w opcji).
- **Wymagania do wyszukiwania w Championie** (`ChampionSearch.requirements`,
  `exclude`; sekcja 2, osobna karta w edytorze POZA grupą „proza” — pierwszy
  wiersz przełączał tę grupę i pole gubiło fokus). `keywords` to odtąd „Frazy
  do LinkedIna” (szukanie poza NEXUSEM). Luna proponuje 2–4 wiersze na
  `/jobs/new` (`JOB_REQUEST_INTAKE` v6); każde słowo musi stać w mailu jako
  CAŁE słowo (`_word_in_text` — `_in_text` to podłańcuch), a słowo, które się
  odmienia, jako rdzeń z gwiazdką (`_grounded_search_word`: początek słowa
  z maila, ≥ 4 litery, bez spacji; gwiazdka przy technologii ze słownika
  znika, bo „Java*” łapie JavaScript). Test na produkcji 25.09: v5 dała
  wiersz „bankowości” — 55 osób, „bankow*” — 323, „bankow* lub banking” —
  903. Dlatego wiersz może nieść JEDEN angielski odpowiednik spoza maila
  (decyzja Artura 25.09.2026, `_translated_search_word`): tylko obok słowa
  z maila, nigdy technologia ze słownika ani słowo z polskimi literami;
  wtedy blok ma plakietkę „propozycja AI”, nie „z maila”. Obok liczba osób
  w bazie (lista, aktywni i pasywni). Handoff wymaga co najmniej jednego
  wiersza (`job_readiness.MSG_SEARCH_REQUIREMENTS`, tylko handoff — alokacja
  czyta bramkę briefu). Automaty ich NIE czytają: `champion_view.requirement_source`
  wycina `search.requirements`/`exclude`, więc edycja nie kasuje kontraktu
  wymagań ani odcisku pełnego przeglądu. Zapis SAMYCH wierszy omija
  `prepare_profile` jak notatki (`user_edit` — inaczej nowy stempel `intake`
  zmieniał odcisk i odczyt przeglądu dawał 409), a handler nie woła wtedy
  `refresh_job_matching` ani `enqueue_job_safe` (`search_rows_only`). Licznik
  osób idzie `fetchCandidateListPage` — `candidatesApi.list` wysyła `status[]=`
  i serwer liczył całą bazę.
- **„Szukaj ręcznie”** startuje od tych wierszy (`jobListFilters`, profil
  z zapytania `["champion-profile", jobId]` — świeży po zapisie DL-a); wtedy
  tytuł NIE idzie jako tekst po znaczeniu (pula semantyczna zawężała), must-have
  zostają rankingiem w „Umiejętnościach”. Bez wierszy — start jak dotąd, bez
  odniesienia do Championa. Pamięć okna niesie odcisk filtrów startowych
  (`request.seed`): inny odcisk = zostaje wyszukiwanie osoby, a baner mówi
  „Wymagania rekrutacji zmieniły się od tego czasu”.
- Rekomendowane wyszukiwania (AI) usunięte (panel, trasy, prompt,
  `candidate_column_coverage`) — użyte raz w historii, a od #1815 zatwierdzona
  strategia nie trafiała do „Szukaj ręcznie”.
