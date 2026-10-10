# Indeks wektorowy: dryf, degradacja i pula ofert (18.09.2026)

- **Adapter wektora zapytania (`services/query_adapter.py`, flaga
  `QUERY_ADAPTER_ENABLED`, domyślnie OFF; badanie 06.10.2026).** Macierz
  `app/data/query_adapter.npz` uczona `scripts/train_query_adapter.py` (prawda
  verified+, zamrożone zbiory eval A i B wykluczone) daje `q + a·q·W` WYŁĄCZNIE
  dla zapytania rekrutacji szukającego kandydatów: `canonical_fit`,
  `pipeline_base_fit`, `candidate_search_worker`, `candidate_match_order`
  (`kind="job"`). Nie dla podobnych rekrutacji, kandydat→oferta, wyszukiwania
  tekstem ani starszych pul (`search_candidates_semantic`). Pamięci zapytań
  trzymają surowe wektory; wersja macierzy wchodzi do `scoring_algorithm_version`
  tylko przy włączonym adapterze. Macierz innego `VOYAGE_MODEL` jest ignorowana
  — zmiana modelu = ponowne uczenie. Włączenie wyłącznie po A/B
  (`coolify-ops` `eval-ab-query-adapter`).
- **Hasz indeksu zależy od TREŚCI i MODELU** (`index_outbox_service._desired_hash`).
  Był samym `sha256(text)`, więc zmiana `VOYAGE_MODEL` nie tworzyła dryfu i nic
  się nie przeindeksowywało — indeks cicho mieszałby wektory z dwóch przestrzeni,
  a podobieństwo między nimi nie znaczy nic. **Porównuj przez `hashes_match`,
  nigdy `!=`**: hasz sprzed tej daty nie niesie modelu i porównany dosłownie
  wyglądałby jak dryf na CAŁEJ bazie — reconciler zakolejkowałby ~60 tys.
  przeliczeń Voyage'a przy pierwszym tiku, płacąc za import jeszcze raz.
  `LEGACY_EMBEDDING_MODEL` to zapis historii, nie konfiguracja — nie zmieniaj
  go razem z `VOYAGE_MODEL`.
- **Reconciler dryfu jest WŁĄCZONY domyślnie i objęty heartbeatem.** Powód
  wyłączenia („przy `AI_INDEX_MAX_ATTEMPTS=5` awaria Voyage'a plus reconciler
  karmiący workera wypala backlog w wiersze `dead` za zielonym healthem") był
  słuszny i nie zniknął sam — zamyka go bramka `embedding_provider_down()`:
  przy `checks.voyage = unhealthy` tik nic nie zapisuje. `unknown` NIE jest
  awarią (inaczej po każdym deployu reconciler stałby do pierwszego
  niezwiązanego wywołania modelu). Zdjęty z `EXEMPT` w `loop_heartbeat`:
  pętla wykrywająca BRAK zapisu nie może sama milczeć niezauważona.
- **Import Traffita zapisuje intencję przeindeksowania OFERT** (`index_intents`
  w statystykach fazy `jobs`). `_UPSERT_JOB` nadpisuje `title`, a tytuł wchodzi
  do tekstu embeddingu, więc każda nocna zmiana zostawiała wektor nieaktualny
  na stałe: 128 z 307 opublikowanych rekrutacji (41,7%) bez wektora.
- **`degraded` znaczy AWARIA SILNIKA, nie „ktoś nie ma wektora".** Pula niesie
  dwie różne flagi: `semantic_unknown` (ten kandydat) i `semantic_engine_down`
  (dostawca). Do 18.09.2026 baner „tryb awaryjny" zapalał się na pierwszej
  z nich, więc wystarczył jeden kandydat dociągnięty przez BM25 i zaraz
  odfiltrowany: 20 z 21 losowych rekrutacji w „trybie awaryjnym" przy zdrowym
  Qdrancie i Voyage'u. Jedyny sygnał ostrzegający przed nieufnym rankingiem
  świecił non stop, więc realna awaria byłaby od normalnej pracy
  nieodróżnialna. `/ai-matches` liczy `degraded` **po przycięciu do
  `max_results`** (wiersz, którego rekruter nie zobaczy, nie zapala banera nad
  tym, co widzi) i dodatkowo, gdy NIC z widocznych nie zostało zmierzone.
- **Odznaka dopasowania na liście kandydatów nie zmyśla liczby.** Ta ścieżka
  nie ma `similarity_map` z Qdranta, więc świeżo policzony wynik ma warstwę
  wartą 60/100 punktów NIEZMIERZONĄ — stąd stałe 26,2 i „0 pasujących ofert"
  o każdym kandydacie w bazie przy progu 50, którego przy takim suficie nie da
  się przekroczyć. Teraz wiersze są oznaczane (`semantic_unavailable_ids`),
  a `summarize_match_stats` liczy WYŁĄCZNIE wyniki ze zmierzoną semantyką
  (`semantic_was_measured`) i oddaje `top_score = None`, gdy nie ma czego
  pokazać. `None` to „nie wiemy", nie „zero" — UI renderuje „Nie policzono".
  Cache czytamy dalej, więc para policzona wcześniej z prawdziwym kosinusem
  ma prawdziwą odznakę. Zapytanie o oferty dostało `ORDER BY` (bez niego
  `LIMIT` oddaje DOWOLNY wycinek), a `total_open` liczy wszystkie opublikowane,
  nie wielkość wycinka.
- **Pula ofert filtruje się PO STRONIE QDRANTA** (`search_jobs_semantic(statuses=…)`,
  `status` w payloadzie punktu). 95,4% wektorów ofert to rekrutacje ZAMKNIĘTE,
  a filtr nakładał się dopiero w SQL na pobraną pulę, więc `top_k=50` dawało
  ~9 rekomendacji. **Filtr jest `should` (OR) z `IsEmptyCondition`, nigdy
  twardym `must`**: punkty sprzed tej zmiany nie mają `status`, więc `must`
  odciąłby całą dzisiejszą kolekcję i zamienił ~9 rekomendacji w ZERO. Filtr
  staje się w pełni skuteczny w miarę przeindeksowywania ofert.
