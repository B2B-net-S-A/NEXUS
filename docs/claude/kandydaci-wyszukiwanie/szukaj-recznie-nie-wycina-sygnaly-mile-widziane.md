# „Szukaj ręcznie” nie wycina — sygnały „Mile widziane” (26.09.2026)

Audyt `docs/audits/2026-09-26/wyszukiwanie-reczne.md` (pary osoba × rekrutacja
z 12 miesięcy, zweryfikowani albo wysłani klientowi): miasto i kategoria
wstawiane przez „Szukaj ręcznie” jako FILTRY wycinały 55,6% wybranych, a wiersze
must-have łączone przez I znajdowały 39%. Reguły, które łatwo cofnąć:

- **Lista ma trzy sygnały tylko do kolejności** (`GET /api/candidates`,
  `api/candidates.py` `_preferred_rank`): `location_preferred` (którekolwiek
  miasto = +1), `competence_category_preferred` (główna lub poboczna = +1),
  `q_preferred_group` (wiersz `a|b`, całe słowa = +1 za wiersz), obok
  `skills_preferred`. Nigdy nie tną i nie wchodzą do braków danych
  (`unknown_count_rank`). To samo `preferred_rank` prowadzi każde sortowanie
  i `sort=match`.
- **„Szukaj ręcznie”** (`lib/job-search-filters.ts` `jobListFilters`): WSZYSTKIE
  miasta rekrutacji i jej kategoria idą do „Mile widziane”, twarde `location`/
  `competenceCategoryIds` puste. Chip „Mile widziane” ma „Wymagaj” (zamiana
  w filtr). Pamięć okna rekrutacji ma klucz `job2`, bo stary niósł twarde filtry.
- **Obowiązkowe są WYŁĄCZNIE umiejętności krytyczne z serwera** (audyt
  06.10.2026, D1/W1–W6; `splitByCritical`): wiersze z
  `critical_resolution.search_rows` (`GET …/champion-profile`, po jednym na
  krytyczną, z wariantami z `keyword_suggest.requirement_search_words` —
  „PostgreSQL lub postgres”), czyli te same, którymi propozycje AI ukrywają
  kandydatów: wybór Delivery Leada, a bez niego podpowiedź z historii.
  Wiersz Championa z tą technologią dostaje warianty; krytyczna bez wiersza
  (profil bez `stack.rows`) dochodzi jako nowy wiersz — także dla rekrutacji
  bez wymagań do wyszukiwania. Reszta wierszy i wiersze „mile widziane” ze
  `stack.rows` (W6) idą do `qPreferred`. Klasyfikacja „technologia / nie”
  NIE decyduje już o obowiązkowości (do 06.10.2026 ekran opisywał jako „Musi
  mieć” wszystkie wiersze-technologie, a filtr wymagał tylko krytycznych).
  Jedna funkcja zasila okno „Szukaj ręcznie”, zakładkę „Szukaj w bazie”
  i kafel; zdanie o źródle (`mandatorySourceNote`: „wybrane przez Delivery
  Leada” / „podpowiedź z historii” / „brak — nic nie jest obowiązkowe”) stoi
  na każdym z nich. Błąd odczytu Championa = nic nie jest obowiązkowe.
  Opcje krytycznej serwer czyta TAK JAK BRAMKA AI
  (`keyword_suggest.requirement_options` → `must_gate_terms.gate_requirement`):
  „Java 11+” → „Java”, „Docker/Kubernetes” → dwie opcje, „Bazy danych
  (Oracle, PostgreSQL)” → Oracle i PostgreSQL. Front łączy krytyczną
  z wierszem Championa po nazwie bez wersji (`withoutVersion`), więc „Java 17”
  w Championie dostaje wariant „Java” zamiast osobnego wiersza. Krytyczna
  z opcją jednoliterową („C”, „R”) nie daje wiersza słów kluczowych
  (`search_rows_skipped`, zdanie na ekranie) — bramka AI czyta ją z profilu.
  „Są wiersze do szukania” liczy JEDNA funkcja `jobSearchPlan` (wiersze
  Championa, krytyczne albo „mile widziane”) dla okna, zakładki i kafla.
  Licznik w edytorze Championa (`SearchRequirementsEditor`) nadal liczy
  klasyfikacją — do wyrównania razem z edytorem (osobny PR).
- **Słowo kluczowe ma co najmniej 2 znaki — także „C” i „R”** (przegląd
  PR #2056): jako słowo kluczowe znajdowały prawie całą bazę (token `r`
  z „2019 r.”, `c` z „C++”/„C#”). Front mówi to przy polu („Pojedynczą literę
  wyszukaj w polu „Umiejętności””), v2 listy i wyszukiwarki odpowiada 422
  tym samym zdaniem (`KeywordTooShort`); v1 (alerty starych zapisów) pomija
  je po cichu jak dotąd.
- **Przy wierszach wymagań must-have NIE idą do „Umiejętności → Mile
  widziane”** (D2): ta sama technologia liczyła się dwa razy, a „Mile
  widziane” (stopnie leksykograficzne) wygrywało z „Dop.”. Bez wierszy
  must-have zostają w rankingu jak dotąd.
- **Kraj i adres to nie miasto** (`parseJobLocationCities`): „Polska
  (lokalizacja obowiązkowa)” jako filtr miasta wycinała 91% wybranych.
- **Początek „Szukaj ręcznie” układa pełny „Dop.”** (`candidate_match_order`,
  `CANDIDATE_MATCH_RERANK_TOP` = 200, 0 = wyłączone): `score_candidates` jak
  `/scores`, przestawienie WYŁĄCZNIE w obrębie grup („Mile widziane”, braki),
  niezmierzeni na końcu grupy, awaria = kolejność wektorowa. Zmierzone: zgodność
  z kolumną 10/19 → 19/19 par, MRR 0,283 → 0,472 (eval 120 rekrutacji); pierwsze
  zimne zapytanie ~2–4 s, kolejne strony z pamięci.
- **Odpowiedniki PL↔EN** (`app/data/keyword_equivalents.json`, prowadzi
  człowiek): trafiają do „Z wariantami” (`skill_variants`, przed aliasami)
  i jako pozycja `kind="term"` dla słów spoza słownika technologii
  („bankowość” → „bankow*”, „banking”). Słowa wieloznaczne (r, go, it, net…)
  dostają ostrzeżenie w `keywordHints`, nigdy automatyczną zmianę.
- **Zakres CV/Stanowisko/Umiejętności na nowej ścieżce** porównuje też pole
  złożone bez polskich znaków (`_folded_whole_word_match`) — „lodz” = „łódź”.
- Badanie do powtórki: `scripts/search_quality_study.py` (10 części) i
  `scripts/eval_manual_search_order.py --rerank-top 100 --ai-top 500`.
- **Tekst embeddingu v3 (pełne CV + notatki) PRZEGRAŁ z v1 — zostajemy na v1**
  (A/B 26.09.2026, `docs/embedding-v3-ab-runbook.md`, kolekcje-cienie
  `nexus_candidates_v3`, `…_v3_nonotes`): zbiór A MRR 0,440 → 0,390, P@5 0,200
  → 0,192; zbiór B R@20n 0,104 → 0,098; „Szukaj ręcznie” (wektor „Dop.”) 84,2%
  → 78,3% rekrutacji z trafieniem na 1. stronie. Bez [NOTES] jeszcze gorzej
  (73,3%) — notatki pomagają, słabszy jest sam układ tekstu v3. Nie włączaj
  `AI_TEXT_SCHEMA_V3` bez nowego pomiaru tym samym runbookiem.
