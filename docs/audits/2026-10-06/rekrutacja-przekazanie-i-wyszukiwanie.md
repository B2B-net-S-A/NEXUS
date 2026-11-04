# Audyt 06.10.2026 — przekazanie rekrutacji DL → rekruter i wyszukiwanie kandydatów

Stan: rundy 1 i 2 zakończone 06.10.2026 (10 agentów + weryfikacja każdego „wysokiego” znaleziska kodem albo danymi).
Zakres: kod NEXUSA (origin/main `c495e4067`), scrapery w `~/pracuj scrapper` (Mac), dane produkcji
(tylko odczyt, `default_transaction_read_only = on`). Nic nie zostało zmienione w kodzie ani na produkcji.

## Najważniejsze w 5 zdaniach

1. Przekazanie działa technicznie (rekruter przypisany i dzwonek < 1 min), ale praca rusza w 9 z 37 rekrutacji z NEXUSA — dzwonek ma 0% odczytów, a „Czeka na Ciebie” nie pokazuje nowej rekrutacji.
2. Rekruter zaczyna od 1 164 kart scrapera w „Ogłoszeniach” i 60–80 nigdy niewygasających propozycji (0 pominięć w całej historii, 1% dodanych).
3. Scraper Pracuj.pl zapisał 1 901 kandydatom stawkę „B2B” liczoną z oczekiwań miesięcznych (mediana 48 zł/h) jako ręczną — psuje „Stawkę od”, filtry i plakietki budżetu.
4. Wyszukiwanie z rekrutacji jest spójne co do zasad (miasto/kategoria nie tną, obowiązkowe tylko krytyczne), ale: ekran opisuje inne wymagania niż faktycznie stosuje (W1), DL prawie nie ustawia krytycznych (D1), bramka AI gubi „Spring (Boot …)” (K7), a z okna wyszukiwania nikt jeszcze nikogo nie dodał — rekruterzy szukają na liście `/candidates`, gdzie „Przypisz” wrzuca do „Ogłoszeń” (U1).
5. Edytor Championa traci niezapisane zmiany przy każdym odświeżeniu danych (N1) i nadpisuje cudze zmiany (N2).

## Naprawy (06–07.10.2026)

Decyzje Artura z 06.10 wykonane: PR [#2055](https://github.com/B2B-net-S-A/NEXUS/pull/2055) + [#2060](https://github.com/B2B-net-S-A/NEXUS/pull/2060) (dane po scraperze, bramka integracji), [#2056](https://github.com/B2B-net-S-A/NEXUS/pull/2056) (wyszukiwanie), [#2061](https://github.com/B2B-net-S-A/NEXUS/pull/2061) (przekazanie, propozycje, Champion), [#2067](https://github.com/B2B-net-S-A/NEXUS/pull/2067) (Trivy); D3, D4, D5, D9 na produkcji; scraper S3–S9 lokalnie. D6 zastąpiony decyzją z 07.10 (#2058). Szczegóły i dowody: `docs/recruitment-audit-2026-10-06-completion-report.md`.

## Czeka na Artura (decyzje)

| # | Decyzja | Opcje | Rekomendacja |
|---|---|---|---|
| D1 | Krytyczne prawie nigdy nie są ustawione (od 04.10 przy rekrutacjach z wierszami DL wybiera najczęściej „Brak krytycznych”) — „Szukaj ręcznie” i propozycje AI niczego wtedy nie wymagają | (a) zostaw; (b) bez decyzji DL obowiązuje podpowiedź z historii (jak w propozycjach AI) i ekran mówi to wprost; (c) przekazanie wymaga wyboru ≥1 krytycznej, gdy must ma technologię | (b) |
| D2 | „Mile widziane” wygrywa z „Dop.” (stopnie leksykograficzne), technologia liczona 2× | (a) zostaw; (b) tylko wiersze, bez dublowania; (c) jedna ocena „Dop.” + premia | (b), pomiar `eval_manual_search_order`, potem (c) |
| D3 | Włączyć `KEYWORD_SEARCH_FOLDED_FTS` (gotowe od 26.09; „c#” 5,7 s → 0,2 s; „lodz” = „Łódź” w CV) | tak / nie | tak, po `compare_keyword_fold_fts` |
| D4 | Karty scrapera: 1 159 z opublikowanych rekrutacji NEXUSA → „Do przejrzenia” (narzędzie gotowe, próba na sucho wygasa **12.10**); 1 271 na zamkniętych → usunąć? | przenieść / zostawić; zamknięte: usunąć / zostawić | przenieść przed 12.10 (z poprawką R7); zamknięte usunąć nowym trybem |
| D5 | 1 901 stawek od scrapera (UoP ÷168 jako ręczna B2B) | cofnąć wszystkie (paragon) / tylko gdzie stawka < 70 / zostawić | cofnąć wszystkie zapisy konta 244 bez późniejszej zmiany człowieka, stawka zostaje w notatce |
| D6 | Propozycje z nocnego przeglądu: ile na noc i czy wygasają | TOP_K 60 → 10–15; wygasanie po 2 nocach bez odświeżenia | tak i tak |
| D7 | Uczestnicy kategorii (`auto_cc`, ~6/rekrutację) dostają powiadomienia rekrutacji, przy której nie pracują | zostaw / tylko „Moja kategoria” bez dzwonków / osobna kategoria wyciszalna | tylko „Moja kategoria” |
| D8 | DL z dodatkową rolą rekrutera dostaje requesty z automatu | zostaw / wyłącz z automatu | wyłącz (konto 91 dostało 749969) |
| D9 | Job JJIT w NEXUSIE od 3 tygodni w `dry_run` obok Maca | przełączyć na NEXUS i wyłączyć Maca / zostać przy Macu i wyłączyć job | najpierw naprawy S3–S6 w jednym miejscu; do tego czasu wyłączyć job (podwójne logowanie na konto portalu) |

## Co zrobiono

- Runda 1: 4 agenty (przekazanie, zasilanie wyszukiwania, silnik wyszukiwania, PR-y 29.09–06.10) + pomiary SQL.
- Runda 2: 6 agentów (scrapery, propozycje, przekazanie do rekrutera, ekran wyszukiwania, ranking i wydajność, tworzenie rekrutacji i Champion) + przegląd repozytoriów scraperów.
- Każde znalezisko „wysokie” sprawdzone osobno kodem albo zapytaniem na produkcji.
- Odrzucone po weryfikacji: wielkie polskie litery w `keyword_fts` (działa), słowa z „ lub ” w wierszach (0 na prod), „Szukaj ręcznie wymaga wszystkich technologii przy »brak krytycznych«” (nieprawda przy profilu z wierszami — `ManualSearchPanel.tsx:107`; dotyczy tylko profili bez wierszy, W3).
- Sprostowane: scraper wysyła `auto_match` od 05.10 12:37 (commit 161b011) — 06.10 zero nowych kart; karty scrapera mają notatkę automatu, więc narzędzie konwersji je obejmuje.
- Notatka w pamięci o runnerze Pracuj.pl. Pliki SQL w scratchpadzie sesji.

## Plan napraw (proponowane PR-y, po decyzjach)

| Fala | PR | Zawartość | Ryzyko |
|---|---|---|---|
| 0 (dziś–12.10) | — | D4: zapis `convert-integration-cards` przed 12.10 (po decyzji), D5 korekta stawek, S7 rotacja webhooka Slacka + czyszczenie logów | dane prod — wymaga zgody |
| 1 | NEXUS „szybkie poprawki” | W1 opis = faktyczne filtry; Q1 QC po całych słowach; K7 fraza przez `( : ,`; U1 „Przypisz” → Nowi + telemetria; H1 dzwonek przy `/owner` `/claim` PATCH `manual_add`; R1 odrzucanie osób już w rekrutacji; U3/U4 paczki po 100 i „Dodano” | niskie |
| 2 | NEXUS „propozycje” | R2 wygasanie + TOP_K (D6), R3 poranny dzwonek do zespołu `job_team`, R4–R6, R8 „Pomiń” zbiorczo, U5/R telemetria otwarć, R7 data karty | średnie |
| 3 | NEXUS „Champion i przekazanie” | N1 nie nadpisywać brudnego szkicu, N2 wysyłać tylko zmienione sekcje + `expected_fingerprint` + DL w odbiorcach WS, N3 nadmiar wierszy do „mile widziane”, N4 lista braków, P1 odmiana w odczycie maila, P2 sync kolumn przy wierszach, H2 „Nowe requesty dla Ciebie” + mail | średnie |
| 4 | NEXUS „wyszukiwanie” | D1/W2 `effective_critical` z serwera, D2 ranking, D3 flaga, K8 nazwiska tylko dla górnego pola, K9 `no_data`, W3, W4 aliasy w wierszach obowiązkowych, M3 „Dop.” po 200 | średnie, pomiar przed/po |
| 5 | scraper (repo poza NEXUSEM) | S3 bez zapisu stawki, S4 tożsamość z panelu, S5 licznik kosztu, S6 ponowienia, S7 `httpx` WARNING, S8 reguły z NEXUSA (`auto_match_rules`) | niskie |

## Dane z produkcji (06.10)

- Od 25.09: 1 173 karty scrapera (`entry_source=auto_match`) w rekrutacjach z NEXUSA → 1 osoba dalej w lejku; 21 osób dodanych ręcznie → 10 dalej.
- Od 01.10 do 05.10 12:20: 357 kart scrapera mimo decyzji 30.09 (runner bez `auto_match`), naprawione 05.10 12:37 w scraperze.
- Otwarte karty scrapera tylko w „Ogłoszeniach” (wszystkie rekrutacje): 2 433 w 169 rekrutacjach.
- „Do przejrzenia” w rekrutacjach z NEXUSA: 1 636 propozycji z nocnego przeglądu, dodane 19; z nowych CV 205/20; z portali 180/0.
- 55 rekrutacji z NEXUSA od 25.09: wiersze wymagań w 8 (edytor od 02.10), krytyczne: 3 wybrane, 13 „brak”, 39 bez decyzji.
- Luka aliasów w słowach kluczowych: „postgres” bez „PostgreSQL” 304 / 12 952 (≈2%), „k8s” 18 / 7 667, „js” 435 / 17 087.

## Znaleziska (runda 1)

### S — scraper / integracje
- **S1 (naprawione 05.10)** runner Pracuj.pl/JJIT wysyłał `proposals/bulk` bez `auto_match` → karty zamiast propozycji. Poprawka w repo scrapera (161b011).
- **S2 (sprostowane w rundzie 2)** 2 440 otwartych kart scrapera; każda ma notatkę automatu, więc `convert-integration-cards` (gałąź z #2043) przenosi 1 159 kart z 23 opublikowanych rekrutacji NEXUSA (próba na sucho 05.10: 1 160, wygasa 12.10). 1 271 kart na rekrutacjach zamkniętych/z Traffita narzędzie pomija z założenia — potrzebny tryb „tylko usuń”.

### W — zasilanie wyszukiwania z rekrutacji
- **W1 (wysoka, regresja #1993)** `useJobSearchSeed.ts:89` — zakładka „Szukaj w bazie” i kafel piszą „Musi mieć: wszystkie wiersze-technologie”, a filtr wymaga tylko krytycznych; przy „brak krytycznych” liczba ≈ cała baza. Poprawka: split z `championCriticalRowFlags(...) ?? techRows` + test.
- **W2 (średnia)** krytyczne `null`: front = nic, serwer = podpowiedź z historii (`job-search-filters.ts:66`, `critical_skills.py:257`). Powiązane z D1.
- **W3 (średnia)** profil z `search.requirements` bez `stack.rows` (import pliku kasuje wiersze) → wszystkie technologie naraz obowiązkowe.
- **W4 (niska, ≈2%)** obowiązkowy wiersz nie rozwija aliasów; `classify_skills` dla nazwy kanonicznej nie dokłada wariantów, dla aliasu tak.
- **W5 (niska)** klasyfikacja wierszy: timeout 1,5 s → wiersz obowiązkowy; `staleTime: Infinity`; fałszywy baner „wymagania zmieniły się”.
- **W6 (niska)** wiersze „mile widziane” z `stack.rows` nie trafiają do wyszukiwania.

### K — silnik wyszukiwania
- **K1 (wysoka, przy OFF)** słowa ze znakami (c#, c++, .net, node.js, ci/cd) → regex po całym CV z TOAST (5,7 s) i w `_preferred_rank` dla całego zbioru przy `sort=match`; słowa bez polskich znaków nie trafiają w CV. → D3.
- **K2 (średnio-wysoka)** ranking leksykograficzny „Mile widziane” > „Dop.”, podwójne liczenie technologii. → D2.
- **K3 (średnia)** „Umiejętności” (JSON skills) i słowa kluczowe (korpus) tną różne zbiory; „Java 8” w JSON nie spełnia „Java”.
- **K4 (niska)** „C”, „R” wycinane po cichu (min. 2 znaki) — front i serwer.
- **K5 (niska)** pamięć kolejności „Dopasowanie”: klucz po `max(stage.id)` — usunięta osoba wraca po 5 min, przetasowanie stron po każdym ruchu.
- **K6 (niska)** `q_preferred_group` ignoruje `q_scope`; `sort=relevance` przy samych słowach = losowe.

### P — przekazanie (tworzenie rekrutacji)
- **P1 (wysoka, skala niepotwierdzona)** odczyt maila: „Javy/Springa/Dockerem” — wiersz wypada po cichu albo zapisuje się odmieniony (`job_request_intake.py:437`, `:519`). Mechanizm odmiany jest w `dz_review`.
- **P2 (średnio-wysoka)** kopia z szablonu tego samego klienta: `jobs.must_skills` = pierwsze słowa wierszy, synchronizacja nie rusza (`job_lifecycle.py:784`) → „Kafka lub RabbitMQ” jako „Kafka” w bramce krytycznych.
- **P3 (średnia, 0 na prod)** słowo z „ lub ” kasuje `stack.rows` (`champion_requirement_rows.py:215`).
- **P4 (niska)** „C”/„R” nie da się wpisać; przycinanie słów do 100 znaków w połowie wyrazu.
- **P5 (niska)** „Java*” wpisane ręcznie łapie JavaScript.
- **P6 (niska)** wiersz krytyczny po zmianie słów → 422 jako napis, nie `job_not_ready`.
- **P7 (niska, admin)** „Kryteria” PATCH-ują kolumny z pominięciem wierszy → bramka krytycznych cicho przestaje działać.
- **P8 (niska)** szablon od innego klienta gubi `stack.notes`.
- **P9 (niska, #2036)** nazwa od klienta składana z tytułu AI.
- **P10 (kosmetyka)** etykiety odmienione/z gwiazdką w must i tytule roboczym („banking, communication”).

### Q — inne PR-y z tygodnia
- **Q1 (średnia, #2036)** QC CV `cv_qc.py:205` — porównanie fragmentem tekstu: „Scala” ⊂ „scalanie”, „Ruby” ⊂ „rubryka” → blokujące sprawdzenie przepuszcza zmyśloną technologię.
- **Q2 (niska, #2039)** kategoria przypisana po wektorze — wektor/payload nieaktualny do reconcilera.
- **Q3 (niska, #2053)** notatka `kind=HUMAN` po edycji może zostać `card` → odznaczone pola wrócą z projekcji.
- **Q4 (niska, #2037/#2053)** `_latest_filled_screening` bez reguły 30 dni.
- **Q5 (niska, #2036)** `company_year_claims` po pierwszym słowie („IT”, „Bank”) → fałszywe uwagi.
- **Q6 (niska, #2043)** wzorzec SQL nie łapie `score:&nbsp;71`.

## Runda 2

### S — scrapery (`~/pracuj scrapper`, Mac; job JJIT w NEXUSIE chodzi w `dry_run` od 16.09, nic nie zapisuje)
- **S3 (krytyczna, potwierdzona na prod)** stawka „B2B/h” liczona z miesięcznych oczekiwań z formularza (÷168, rodzaj umowy nieznany, `nexus_pipeline.py:393-400`) idzie `PATCH /profile-rate` → w NEXUSIE `source="manual"`, `contract_type="b2b"`, `_manual_override_rate`, wchodzi do „Stawki od”. 14 dni: 1 901 profili, mediana 48 zł/h, 1 290 < 70 zł/h, 1 039 < 50. Łamie regułę „÷168 tylko przy B2B”; zaniża stawki w filtrach, plakietce budżetu, listach praktykantów.
- **S4 (wysoka)** e-mail/telefon z CV wygrywa z e-mailem z konta aplikującego (`traffit_pipeline.py:603`, `pracuj scraper.py:545`) → CV z nagłówkiem agencji trafia jako duplikat do obcej osoby (dokument, propozycje, stawka, dostępność).
- **S5 (wysoka, koszt)** `upload_cv_to_existing` uruchamia w NEXUSIE płatny `parse_cv` (REFRESH), a scraper liczy to jako „saved” — faktyczne płatne odczyty ≈2,3× więcej niż w Insights; `from-cv` → 409 → `/cv` = dwa odczyty; nowy kandydat czytany 2× (Luna dla Traffita + Sonnet w NEXUSIE).
- **S6 (średnia)** błąd NEXUSA (503 przy deployu) nie jest ponawiany — aplikacja trafia do `processed`, kandydat zostaje bez dopasowań.
- **S7 (średnia, bezpieczeństwo)** webhook Slacka nadal w logach (logger `httpx` INFO): 110× w dzisiejszym logu JJIT, 37 226× w `launchd.err.log` pracuj (42 MB, bez rotacji). → wyciszyć `httpx`, wyczyścić logi, zrotować webhook.
- **S8 (średnia)** `is_good_match` przepuszcza ofertę bez must-have samym wynikiem, 1 trafione must wystarcza przy progu 65; każdy aplikujący dopasowywany do wszystkich otwartych rekrutacji (kandydat 634482: 8 propozycji z jednej aplikacji); 47/180 propozycji `job_board` dubluje `new_cv` z auto-matcha NEXUSA (próg 70).
- **S9 (niska)** notatka scrapera wciąż powstaje (396/dzień, systemowa `application_form`), z tekstem „szacunek stawki B2B: 48 zł/h”.
- **S10 (niska)** job JJIT w NEXUSIE: run 61 wisi `running`; „tydzień obserwacji” trwa 3 tygodnie; podwójne logowanie na konto portalu; przy przełączeniu brak sita `check-duplicates` i ponowień 503.

### H — przekazanie do rekrutera (automat, dzwonki, pierwszy dzień)
Pomiary: automat w trybie `auto`, 13 osób, 32 requesty w puli, 0 bez rekrutera, 0 propozycji dla HoR. Od 04.10 rekruter przypisany i dzwonek w < 1 min. **Ale praca rusza w 9 z 37 opublikowanych rekrutacji z NEXUSA**; w 7 dniach 81 ruchów ludzi w 5 rekrutacjach przez 3 osoby. Dzwonki rekruterów: mediana 25/7 dni, odczytane 0–4%; `request_assignment_changed` 8 wysłanych, 0 odczytanych.
- **H1 (wysoka, potwierdzona)** brak dzwonka przy ręcznym ustawieniu rekrutera: `POST /owner` i `/claim` (`api/jobs.py` ~4746, ~4844), PATCH `recruiter_id`, `manual_add` na pulpicie — `notify_assigned` wołają tylko przekazanie, automat i decyzje o propozycjach.
- **H2 (wysoka)** dzwonek nie jest działającym kanałem: brak maila dla `request_assignment_changed` (`notification_delivery.py:176`), a „Czeka na Ciebie” nie ma „Nowe requesty dla Ciebie” — świeżo przypisany rekruter widzi „Nic na Ciebie nie czeka”.
- **H3 (wysoka)** pierwszy dzień rekrutera = 1 164 karty scrapera w „Ogłoszeniach” rekrutacji z NEXUSA (mediana 37/rekrutację, max 136); konwersja była tylko próbą na sucho 05.10. (= D4/S2)
- **H4 (średnia)** uczestnicy kategorii (`auto_cc`, 5,7/rekrutację) dostają powiadomienia rekrutacji, przy której nie pracują (`job_membership.py:161`) — szum zagłusza dzwonek o przypisaniu.
- **H5 (średnia)** obłożenie: kategoria 2 ma 18/32 requestów przy 4+3 osobach, jedna osoba prowadzi 5; 6 kont z rolą rekrutera bez kategorii (poza automatem i „Moją kategorią”).
- **H6 (średnia)** DL z dodatkową rolą rekrutera dostaje requesty z automatu (749969 → konto 91) — do potwierdzenia, czy zamierzone.
- **H7 (niska)** priorytet „Przyjmujemy kandydatów” + automat = rekrutacja bez rekrutera na zawsze; Compass wyłączony = przydział osoby na urlopie bez podpowiedzi; 5 opublikowanych rekrutacji nigdy nie przekazanych do searchu (poza pulą).

### R — propozycje „Do przejrzenia”
Pomiary: `job_proposals` 2 124 `proposed`, 58 `added`, **0 `dismissed` w całej historii**; `full_base` 61–84 osoby na rekrutację (limit 60), dodane 1,1%; 422 propozycje nie odświeżone >2 doby; 172 w zamkniętych rekrutacjach; skrót dzienny 53 wysłane / 1 przeczytany; skrzynka nie ma telemetrii otwarcia.
- **R1 (wysoka, potwierdzona)** `publish_run_proposals` (`auto_full_review.py:555`) nie odrzuca osób już w rekrutacji ani par pominiętych/dodanych — 54 propozycje zajmują miejsca w top-60.
- **R2 (wysoka)** propozycje nigdy nie wygasają — każda noc dopisuje do 60, stare zostają; lista rośnie do 80.
- **R3 (średnia)** skrót dzienny tylko dla `new_cv` i tylko do `recruiter_id`/`tac_id` (nie reguła `job_team`), treść odsyła do nieistniejącej skrzynki „Propozycje”; `full_base` nie ma żadnego sygnału dla rekrutera.
- **R4 (średnia)** `proposals_digest._pending_jobs` liczy surowe wiersze (z osobami już w rekrutacji) — inna liczba niż na kaflu.
- **R5 (średnia)** `mark_added` woła tylko `proposals_bulk` — inne drogi dodania zostawiają `proposed`, po „Usuń z rekrutacji” osoba wraca do propozycji.
- **R6 (średnia)** zamknięcie rekrutacji nie wygasza propozycji (172 wiersze).
- **R7 (niska)** konwersja kart ustawia `first_seen_at=now()` → 1 160 osób naraz w kaflu „Nowi z ogłoszeń (7 dni)”.
- **R8 (UX)** „Pomiń” wymaga powodu przy każdej osobie (przy 60–80 nikt nie zaczyna); wąski rozrzut wyników 70–80.

### U — ekran wyszukiwania i dodawanie
Pomiar: `manual_search` w telemetrii = 0 od 16.09 — to nie błąd, z okna „Szukaj ręcznie”/„Szukaj w bazie” nikt jeszcze nikogo nie dodał. 25 ręcznych dodań od 25.09: 20× „Dodaj po nazwisku”, 4× „Przypisz do rekrutacji” z listy kandydatów/profilu, 1× inna droga. **Rekruterzy szukają na głównej liście `/candidates`, nie w oknie rekrutacji.**
- **U1 (wysoka, potwierdzona)** „Przypisz do rekrutacji” (`POST /candidates/{id}/assign-to-job/{job}`, `recommendations.py:1272`) bierze pierwszy etap szablonu = „Ogłoszenia” (`posting`) → karta z plakietką „z ogłoszenia, nikt nie rozmawiał” (3 z 4 na prod); telemetria zgaduje przegląd (`emit_match_outcome`) i zawyża pozytywy C2. → przez `add_candidates_to_job` + `emit_pipeline_additions` z własnym źródłem.
- **U2 (wysoka)** telemetria gubi ponowne dodania: klucz `add_to_pipeline:norun:{job}:{cand}` + `ON CONFLICT DO NOTHING` (para dodana 5× = 1 wpis); integracja z `reason_code NULL` zajmuje klucze.
- **U3 (średnia)** zaznaczenie > 100 osób (przeżywa zmianę strony) → angielski 422 „List should have at most 100 items”.
- **U4 (średnia)** po dodaniu wiersz zostaje 2–4 s i można kliknąć drugi raz → czerwony toast; `already_in_job` zostają zaznaczone.
- **U5 (średnia)** okno wyszukiwania nie zapisuje wyświetleń — brak mianownika do pomiaru.
- **U6 (niska)** staging dzieli po `|` i gubi granice wierszy — przeniesienie słowa między wierszami stosuje się bez „Szukaj” i liczy jako 0 zmian.
- **U7 (niska)** zakładki „Nowi z ogłoszeń” i „Propozycje z bazy” mają wspólne zaznaczenie — „Dodaj N” dodaje osoby z niewidocznej zakładki; tablist bez strzałek.
- **U8 (niska)** Escape w polu słów bez listy podpowiedzi zamyka całe okno (szkic filtrów przepada); fokus po „Usuń wymaganie” na `body`; wyszukiwanie podobnych rekrutacji bez debounce; układ pól liczony od szerokości okna, nie panelu; „dodaj nowego kandydata” w pustym stanie nie dodaje do rekrutacji.

### K (runda 2) — silnik wyszukiwania i bramka AI
Pomiary (stara ścieżka, flaga OFF): 749857 Python+Django+FastAPI+PostgreSQL → 883 osoby, 1,3 s; 719526 Java+Kafka → 3 424, 4,4 s; pojedyncze słowo w gałęzi `keyword_doc ~*` czyta 80–110 tys. bloków. Profil bez wierszy (W3): 6 technologii naraz zostawia 145 z 64 736 osób.
- **K7 (wysoka, potwierdzona)** fraza w bramce AI (`keyword_terms.py:48`, odstęp `[\s/-]+`) nie przeskakuje „(”, „:”, „,” — „Spring (Boot, Data)” nie spełnia „Spring Boot”, a wyszukiwanie ręczne (tsvector) tak. Rekrutacja 719526: 16 doświadczonych Javowców ukrytych jako `missing_must`; 52 CV w bazie ma tylko taki zapis.
- **K8 (średnia)** wiersz „SAP”, „SAS”, „Ada”, „Julia” nigdy nie jest obowiązkowy, bo w bazie jest osoba o takim imieniu/nazwisku (`classify_keywords` → `person_token_exists`) — sprawdzać nazwiska tylko dla górnego pola listy.
- **K9 (średnia)** `no_data` ukrywa osoby z historią stanowisk (36 w 719526) i z plikiem CV bez odczytanego tekstu (~46) — `has_any_data` nie patrzy na `profile_text`; CV bez tekstu kierować do ponownego odczytu.
- **K10 (średnia)** „Dop.” przestaje maleć od pozycji 201 (pełna ocena tylko top 200) — dalej kolejność wektorowa, także dla wektorów `stale`.
- **K11 (średnia)** paginacja przesuwa się po każdym „Dodaj” (klucz kolejności z `max(stage.id)` → pełne przeliczenie, strona 2 pomija tyle osób, ile dodano).
- **K12 (niska)** odmiana w dowodzie must („Kafką”, „Javie”); przegląd na stałe `partial` przy 7 niezmierzonych z 3 087; „Mile widziane” liczone 2,4–4,1 s (K1).

### N — tworzenie rekrutacji i edycja Championa (runda 2)
Kontrole prod bez rozjazdów: `stack.must` = `jobs.must_skills` (0/55), krytyczne ⊆ must, budżet i dni w biurze profil = kolumny; 8 rekrutacji od 04.10 komplet (HM/termin albo „nie podał”).
- **N1 (wysoka, potwierdzona)** `ChampionProfileEditor.tsx:264` — `useEffect([data])` bezwarunkowo `setDraft/setBaseline`; każde odświeżenie profilu (PATCH terminu/priorytetu w „Zespół”, WS `champion_profile_changed`, powrót do karty, historia klienta po `/jobs/new`) kasuje niezapisane zmiany bez ostrzeżenia.
- **N2 (wysoka, uśpiona)** zapis Championa wysyła cały szkic, PUT ignoruje `expected_fingerprint`, `merge_insights` kasuje notatki spoza ładunku → DL nadpisuje zmiany rekrutera; DL nie jest odbiorcą `champion_profile_changed` (43/49 par). Dziś 0 przypadków (jeden edytor na rekrutację), ryzyko rośnie.
- **N3 (średnia, potwierdzona)** `clean_rows` (`champion_requirement_rows.py:86`) po cichu odrzuca 11.+ wiersz „musi mieć” (nie przenosi do „mile widziane”); 749969 straciło „CI/CD” i „automated testing”; 662/1 208 profili ma > 10 must — szablony tracą wymagania przy kopii.
- **N4 (średnia)** 422 `handoff_regression` w edytorze pokazuje samo zdanie bez listy braków (inne ekrany używają `job-gate-errors`).
- **N5 (niska)** zapis dowolnego bloku przelicza etykiety wierszy wg bieżącego słownika → zmiana must i przeliczenia dopasowań bez zmiany przez człowieka.
- **N6 (niska)** „liczba osób” zawsze 1 (domyślne 1 w schemacie i formularzu, bramka `< 1` martwa; 55/55 = 1; kopia szablonu nie przenosi).
- **N7 (niska)** autozapis formularza przy ukryciu karty w trakcie `POST /api/jobs` zakłada nowy formularz → „niedokończony” po utworzeniu.
- **N8 (dane)** słowa ogólne w wierszach łapią połowę bazy („IT” 30 306, „testing” 23 863, „communication” 17 799, „requirements” 16 514); polskie frazy-zdania dają 0 trafień (706640).

## Uwagi operacyjne
- 06.10 20:26 UTC deploy założył od nowa także Postgresa i Qdranta (RestartCount 0) — sprawdzić „Postgres restartował” w raporcie przerwy tego deployu.
- Job JJIT w NEXUSIE: run 61 (05.10) wisi jako `running`.
