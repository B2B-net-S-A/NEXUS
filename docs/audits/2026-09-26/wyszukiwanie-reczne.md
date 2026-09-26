# Audyt wyszukiwania ręcznego i porównanie z wyszukiwaniem AI (26.09.2026)

- **Baza:** produkcja na `c6138f943` (#1855), korpus złożony w wersji 3,
  przeliczony w całości 26.09 o 09:16 UTC (pierwsze pełne przeliczenie od #1848).
- **Przełączniki na produkcji:** `KEYWORD_SEARCH_FOLDED_FTS` OFF,
  `AI_TEXT_SCHEMA_V3` OFF (embedding v1), `CANDIDATE_MATCH_SORT` domyślnie ON.
- **Tryb pracy:** wszystko tylko do odczytu. SQL w `SET TRANSACTION READ ONLY`,
  do API krótki token zmintowany w kontenerze backendu.
- **Poprzednia praca:** `docs/candidate-search-speed-quality-completion-report.md`
  (#1845, #1846, #1848, #1852).

## Jak powtórzyć

W kontenerze backendu (`docker exec -i -w /app -e PYTHONPATH=/app <backend> …`):

```
python -m scripts.search_quality_study --api --jobs 120      # części 1–10, ~6 min
python -m scripts.eval_manual_search_order --jobs 120 --rerank-top 100 --ai-top 500   # ~5 min
python -m scripts.compare_keyword_fold_fts "ci/cd" "spring boot"                     # wybrane słowa
```

Części badania (`scripts/search_quality_study.py`, `--only 1,3`):

1. stan danych;
2. stara vs nowa ścieżka słów;
3. skąd trafienie (CV, stanowisko, umiejętności, notatki);
4. warianty pisowni;
5. odmiana;
6. historia rekrutacji: czy wiersze wymagań znajdują osoby, które zespół potem wybrał;
7. API na żywo;
8. szum krótkich słów;
9. zgodność liczby w podpowiedzi z listą;
10. filtry a osoby wybrane przez zespół.

„Osoby wybrane przez zespół” to w całym raporcie pary z
`analytics_first_milestones` na etapie `verified` albo `cv_sent`.

## Naprawione w trakcie audytu

| # | co | dowód | PR |
|---|---|---|---|
| 1 | Przeliczanie korpusu po zmianie wersji zaczynało od zera przy każdym restarcie; od #1850 (deploy po każdym merge'u) wersja 2 nie skończyła się ani razu | brak `keyword_fold_fts_version` w `app_settings` 26.09 08:10; po poprawce restart o 09:09 wznowił od 222 710 | [#1854](https://github.com/B2B-net-S-A/NEXUS/pull/1854) |
| 2 | „Szukaj ręcznie” czytało kraj („Polska (lokalizacja obowiązkowa)”) i adres („ul. Chmielna 89”) jako miasto | przy takich rekrutacjach filtr wycinał 1 316 z 1 443 (91%) wybranych przez zespół | [#1855](https://github.com/B2B-net-S-A/NEXUS/pull/1855) |
| 3 | Zakres „CV/Stanowisko/Umiejętności” na nowej ścieżce nie rozumiał braku polskich znaków | „lodz” w CV 1 429 vs „łódź” 2 130; „zarzadzanie” 171 vs „zarządzanie” 12 035 | [#1856](https://github.com/B2B-net-S-A/NEXUS/pull/1856) |

## Najważniejsze wyniki

### Stara vs nowa ścieżka słów (wersja 3 składania, 50 słów)

- Nowa ścieżka traci razem 33 osoby, a zyskuje 5 450.
- Każdą utraconą osobę sprawdziłem na treści:

| grupa | osób | przykład |
|---|---:|---|
| miasto albo słowo w adresie e-mail | 7 | `los.gdansk@`, `marczak.krakow@`, `mazur.react@`, `tester.bszelag@` |
| linki w notatkach (`…/j.php`, `index.php`) | 13 | „php” |
| nazwa firmy lub domeny | 2 | Devops.ly, spark.fi |
| „Java.script” w notatce (to JavaScript) | 2 | „java” |
| nazwa pliku | 1 | „IT Tester.pdf” |
| wyraz sklejony kropką (świadomie zostaje) | 6 | „scrum.org” ×3, „Agile.a”, „8.krakow” ×2 |
| kod pocztowy sklejony z miastem | 1 | „51-520Wrocław” (kandydat 463837) |
| „krakow” w notatce, niepotwierdzone (prawdopodobnie link) | 1 | kandydat 4661 |

- **Czas nowej ścieżki (pomiar pojedynczy):**
  - „java” 14 s → 0,1 s, „c#” 13 s → 0,05 s, „f#” 9,8 s → 0,005 s;
  - frazy: „ci/cd” 1,4 → 0,66 s, „spring boot” 0,33 → 0,18 s, „power bi” 0,76 → 0,22 s;
  - wolne zostaje „*script” (gwiazdka na początku) — ~2 s na obu ścieżkach.
- **Uwaga do pomiaru:** w pełnym przebiegu „ci/cd” wyszło 7,4 s, bo cache był zimny.
  Osobny pomiar powtórzony dwa razy dał 0,66 s.

### Skąd trafienie (nowa ścieżka)

| słowo | osób | tylko w notatkach | bez tekstu CV |
|---|---:|---:|---:|
| java | 15 892 | 151 (1,0%) | 74 |
| tester | 8 314 | 370 (4,5%) | 15 |
| analityk | 3 360 | 457 (13,6%) | 15 |
| bankowość | 832 | 300 (36,1%) | 7 |
| ubezpieczenia | 555 | 103 (18,6%) | 2 |
| b2b | 9 617 | 4 593 (47,8%) | 65 |
| zdalnie | 2 878 | 1 861 (64,7%) | 12 |

- Technologie siedzą w CV.
- Warunki współpracy (B2B, praca zdalna) i dziedzina (bankowość, ubezpieczenia)
  siedzą w notatkach.
- Wyszukiwanie ręczne widzi notatki. Wyszukiwanie AI ich nie widzi (embedding v1, patrz „Mapa”).
- **Stan danych:**
  - 5,2% kandydatów nie ma tekstu CV; 209 z nich ma plik CV, którego tekstu nie odczytano;
  - 0,8% ma tekst CV sklejony (słowa bez spacji);
  - 4,7% nie ma CV, umiejętności ani notatek, więc słowem nie da się ich znaleźć;
  - 15,7% nie ma listy umiejętności.

### Wiersze wymagań na historii rekrutacji (120 rekrutacji, 879 wybranych osób)

- Wiersze to do 3 pierwszych must-have z rekrutacji.
- Notatki liczone są tylko sprzed otwarcia rekrutacji.

| miara | udział |
|---|---:|
| osoba spełnia WSZYSTKIE wiersze (tak szuka lista) | 38,9% |
| spełnia co najmniej jeden wiersz | 86,9% |
| trafienia dzięki samym notatkom | 2,3% |

- **Dlaczego 534 osoby nie spełniają wszystkich wierszy:** prawie zawsze słowa po
  prostu nie ma w danych. Must-have w rekrutacjach to często zwroty, a nie
  technologie („narzędzia case”, „inicjatywy ai”, „strategia rozwoju rozwiązań ai”).
- **Brak tekstu CV** tłumaczy tylko 2 osoby, sklejony tekst 1.

### Kolejność: ręczne vs AI (120 rekrutacji, `eval_manual_search_order`)

| kolejność | wybrani w wynikach w ogóle | rekrutacje z ≥1 wybranym na 1. stronie | wybrani w top 50 | MRR |
|---|---:|---:|---:|---:|
| najnowsi | 73,1% | 32,5% | 7,0% | 0,038 |
| ręczne: 2 wiersze I, wektor „Dop.” (dziś) | 73,1% | 83,3% | 29,8% | 0,283 |
| ręczne: jak wyżej + 100 pierwszych wg pełnego „Dop.” | 73,1% | 82,5% | 32,7% | 0,472 |
| ręczne: wiersze LUB, wektor „Dop.” | 95,3% | 82,5% | 22,3% | 0,250 |
| AI: cała baza, 500 najbliższych → wg „Dop.” | 100% | 88,3% | 34,3% | 0,461 |

- **Wybrani na 1. stronie (top 50):** obie metody 220, tylko AI 146, tylko ręczne 35,
  żadna 667. AI znajduje większość tego, co ręczne, i sporo więcej.
- **Kolejność „Dopasowanie” nie zgadza się z kolumną „Dop.”:** 10 z 19 sąsiednich
  par malejąco (rekrutacja #689443). Kolejność liczy sam wektor, a „Dop.” to pełny
  wynik: wektor 60, umiejętności 10, stawka 15, lokalizacja 5.
- **Koszt przeliczenia pełnym „Dop.”:** 100 osób ok. 160 ms, 200 osób ok. 350 ms.
  Pierwsze wywołanie dokłada ok. 1 s na wektor zapytania.
- **Przeciek sprawdzony:** tabela `requirement_verifications` na produkcji jest pusta.
- **Zastrzeżenia:**
  - Do testu weszły tylko rekrutacje, w których 2 wiersze I dają ≥100 osób
    (faworyzuje ręczne).
  - Pełny „Dop.” liczy dzisiejsze dane profilu.

### Filtry a osoby wybrane przez zespół (pary z 12 miesięcy: 9 969)

| filtr | wyciąłby wybranych |
|---|---:|
| stawka „do budżetu” (osoby ze znaną stawką przy rekrutacji z budżetem) | 38,7% |
| stawka > budżet + 10% | 30,4% |
| miasto rekrutacji (osoby ze znanym innym miastem, rekrutacje niezdalne) | 57,9% |
| kategoria kompetencji rekrutacji (dokładana przez „Szukaj ręcznie”) | 20,5% |
| status aktywny/pasywny (wycina tylko `blacklisted`) | 1,3% |
| którykolwiek z trzech dokładanych przez „Szukaj ręcznie” | 55,6% |

Dla tych osób 60% ma status dostępności `unknown`, a 22% ma datę dostępności.

### Warianty pisowni i odmiana

„Gubi” = osoby znalezione drugą formą, których pierwsza forma nie znajduje:

| wpisuje | druga forma | gubi | „z wariantami” podsuwa |
|---|---|---:|---|
| sql server | mssql | 1 473 | tak |
| power bi | powerbi | 469 | tak |
| javascript | js | 505 | nie |
| qa | quality assurance | 1 910 | nie |
| ux | user experience | 1 763 | nie |
| machine learning | ml | 1 316 | nie |
| analityk | analyst | 10 512 | nie |
| bankowość | banking | 7 657 | nie |
| ubezpieczenia | insurance | 3 360 | nie |
| tester | qa | 5 241 | nie |

Odmiana i angielski odpowiednik:
- „bankowość” 832 → „bankow*” 5 516 → „bankow*” LUB „banking” 11 803;
- „analityk” 3 360 → „analityk*” LUB „analyst” 15 454.

Pojedyncze polskie słowo w mianowniku znajduje ułamek osób.

### Szum krótkich słów (próbka 40 trafień na słowo)

| słowo | osób | co łapie |
|---|---:|---|
| r | 20 845 | prawie wyłącznie „2016 r.” z klauzuli RODO — słowo bezużyteczne |
| go | 4 740 | „go-live”, „GO FAR Sp. z o.o.”, rzadko język Go |
| it | 31 023 | ogólne „IT” |
| net | 1 639 | „EURO NET”, „Content Ed Net”, „test-net” |
| ada | 79 | adres LinkedIn („ada m-kulesza”), ADA/WCAG |
| swift | 1 378 | język Swift, ale też komunikaty bankowe SWIFT |
| sap, erp, crm, rust, ruby, rest, spring, bi, qa, ml | — | w próbce trafne |

### Zgodność liczby w podpowiedzi z listą

- Podpowiedź liczy bez notatek, więc obiecuje mniej, niż pokaże lista.
- Przykłady: „bankowość” 532 vs 832, „kraków” 5 936 vs 6 205, „scrum” 18 234 vs 18 341.
- Frazy („spring boot”) liczby nie mają — świadomie.

### API na żywo (stara ścieżka, dziś na produkcji)

| scenariusz | 1. zapytanie | 2. zapytanie |
|---|---:|---:|
| bez filtra | 421 ms | 176 ms |
| java | 996 ms | 951 ms |
| java + spring + sql | 2 160 ms | 1 903 ms |
| c# | 5 699 ms | 5 245 ms |
| java, sort=match | 1 508 ms | 261 ms |
| „Szukaj ręcznie”, bez wymagań, sort=match | 1 479 ms | 229 ms |

Po włączeniu przełącznika słowo kosztuje ~0,1 s zamiast ~1–5 s (tabela „stara vs nowa”).

## Mapa: skąd każda wyszukiwarka bierze dane

| | ręczne (słowa, v2) | AI (pula wektorowa, „Dop.”, pełny przegląd, Radar) |
|---|---|---|
| CV | cały tekst (do 200 tys. znaków) | 3 000 znaków (embedding v1) |
| notatki | treść wszystkich notatek | brak (v3 dokłada fakty z `_notes_insights`, flaga OFF) |
| pola Traffita, „o sobie” | tak | nie (tylko przez listę umiejętności) |
| `ai_summary` | nie (świadomie) | tak |
| must-have | nie odcina (wiersze to filtr, jeśli je wpisać) | ukrywa osobę, która ma ZNANE umiejętności i brak must-have |
| limit puli | brak; „po znaczeniu” 200 osób; `sort=match` ANN 3 000 przy zbiorze > 30 tys. | ANN 1 000 (Radar, /ai-matches); pełny przegląd = cała baza |

Pliki: `services/keyword_corpus.py:70-108` (pola korpusu),
`services/embedding_service.py:464-559` (tekst embeddingu v1, CV `[:3000]` w `:557`),
`services/scoring_service.py:111-127` (wagi), `services/dealbreaker_filters.py:609-735`
(ukrywanie), `services/candidate_text_retrieval.py:34` (pula 200),
`services/candidate_match_order.py:47-48` (limity kolejności).

## Otwarte — decyzje dla Artura (od najbardziej wpływowych)

1. **Filtry, które „Szukaj ręcznie” dokłada samo:** miasto rekrutacji i kategoria
   kompetencji wycinają razem 55,6% osób, które zespół wybrał.
   - Propozycja: oba jako „Mile widziane” (kolejność), nie filtr. Status zostaje
     (wycina tylko czarną listę).
   - Plik: `frontend/src/lib/job-search-prefill.ts:295-301`,
     `components/…/ManualSearchPanel.tsx` (`jobListFilters`).
2. **Włączenie `KEYWORD_SEARCH_FOLDED_FTS`:** porównanie po wersji 3 jest czyste
   (33 utracone = szum albo świadome wyjątki) i szybkie.
   - Najpierw wdrożyć #1856.
   - Włączenie: workflow „Coolify set env” z `redeploy=false`, potem zwykłe wdrożenie.
3. **Kolejność „Dopasowanie”:** przeliczać pierwsze 100–200 osób pełnym „Dop.”.
   - MRR 0,283 → 0,472, kolumna „Dop.” zgodna z kolejnością.
   - Koszt ~0,2–0,4 s, wynik trzymany w istniejącej pamięci 5 min.
4. **Wiersze wymagań z must-have łączone przez I** znajdują 39% wybranych.
   - Propozycja: w „Szukaj ręcznie” wiersze tylko z must-have, które są technologiami
     ze słownika (zwroty jak „narzędzia case” do „Mile widziane”).
   - Albo domyślnie jeden wiersz obowiązkowy, reszta „Mile widziane”.
5. **Polsko-angielskie odpowiedniki w „z wariantami”:**
   - analityk↔analyst, bankowość↔banking, ubezpieczenia↔insurance, tester↔QA,
     QA↔quality assurance, UX↔user experience, ML↔machine learning, JS↔JavaScript.
   - Dziś przycisk zna tylko aliasy technologii ze słownika.
6. **Wyszukiwanie AI nie widzi notatek ani CV powyżej 3 000 znaków** (embedding v1).
   - Flaga `AI_TEXT_SCHEMA_V3` istnieje, ale zmienia wektory całej bazy.
   - Wymaga reindeksu i pomiaru `eval_matching.py` przed/po (CLAUDE.md: A/B).
7. **Słowa-szum:** podpowiedź przy 1–2-literowych i wieloznacznych słowach
   („r”, „go”, „it”, „net”): „słowo wieloznaczne — spróbuj «golang», «język R»”.
   - „r” łapie klauzulę RODO w 20 845 CV.
8. **Liczba w podpowiedzi** pomija notatki (do 36% mniej niż lista).
   - Albo liczyć z notatkami, albo podpisać „w profilach”.

## Znane, świadomie zostawione

- Wyrazy sklejone kropką („scrum.org”) nie są rozcinane (decyzja 26.09).
- Kod pocztowy sklejony z miastem („51-520Wrocław”): rozcinanie cyfr od liter
  zepsułoby „b2b”, „s3”, „5g”, „2fa”.
- Stara ścieżka (dziś na produkcji) ma ten sam błąd zakresu z polskimi znakami co
  #1856. Nie poprawiana, bo zniknie po włączeniu przełącznika.
- „*script” ~2 s — gwiazdka na początku nie ma indeksu.

## Sprawdzone i czyste

- Korpus złożony: 0 kandydatów bez `keyword_fold_fts`; 0 notatek w formacie JSON Traffita.
- Zawężenie zakresu nigdy nie znajduje osoby, której „wszędzie” nie znajduje
  (kolumna „CV ⊄ wszędzie” = 0 dla 17 słów).
- Wersje zapisu „łódź”/„lodz”, „kraków”/„krakow”, „zarządzanie”/„zarzadzanie” dają
  w nowej ścieżce identyczne liczby (zakres „wszędzie”).
- Status aktywny/pasywny w „Szukaj ręcznie” wycina wyłącznie osoby z czarnej listy.
- Ścieżka AI nie ma błędu „Polska jako miasto” (`location_utils._COUNTRY_TOKENS`).
- Górne pole: „java spring” i „react typescript” → wiersze wymagań. „Kowalski”
  i „Kraków” zostają tekstem.
