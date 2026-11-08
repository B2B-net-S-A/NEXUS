# Insights → Raporty → „Klienci: od CV do zatrudnienia” (audyt 08.11.2026, B3)
<!-- indeks: CV, rozmowy, zatrudnienia, CV na zatrudnienie, hit ratio per klient, „Do przejrzenia” poza mianownikiem, mediana pierwszego CV, `/api/insights/clients/funnel` -->

Decyzja Artura z 08.11.2026: tabela dla całej firmy, bez limitu CV i bez zmiany
kolejności Daily (punkty 2 i 3 tezy B3 czekają na decyzję handlową na tych
liczbach). Raport, a nie zakładka, bo pasek Insights przy 1280 px jest pełny.

## Definicje (`services/insights_client_funnel.py`)

- **CV, rozmowy, zatrudnieni**: pierwsze wejście pary (kandydat, rekrutacja)
  na etap w wybranym okresie, z widoku `analytics_first_milestones`.
  Wykluczone placementy się nie liczą.
- **CV na zatrudnienie**: przelicznik okresu, puste przy braku zatrudnień.
  Zatrudnienie z okresu może pochodzić z CV sprzed okresu, więc to nie kohorta.
- **Hit ratio**: wygrane / (wygrane + przegrane), z zamknięć od 12.10.2026
  (`competition_history.cutover_utc`) w ramach okresu. Grupy z
  `hit_ratio_closures.closure_group`: zatrudnienie = wygrana, `competitor` i
  `no_activity` bez zatrudnienia = przegrana, powody neutralne poza wynikiem.
- **Do przejrzenia** (brak powodu albo „Inny”): osobna kolumna, poza
  mianownikiem. To jedyna różnica wobec raportu „Zamknięcia i hit ratio”, gdzie
  takie zamknięcia liczą się jak przegrane do czasu przeglądu. Weryfikacja
  audytu pokazała, że dla klienta z dużą liczbą zamknięć bez powodu zaniżało to
  wynik (część miała zatrudnienie albo żadnej decyzji).
- **Pierwsze CV**: mediana dni od otwarcia do pierwszego CV, dla rekrutacji,
  których pierwsze CV wypadło w okresie.

Kwot tu nie ma, stąd bramka jak `/clients/hit-ratio` (`CurrentUser`, D7), a
domyślny okres to bieżący kwartał. Czerwony znacznik: hit ratio poniżej progu
`DL_HIT_RATIO_TARGET_PCT` (30%).
