# Co przy tworzeniu rekrutacji pomaga wyszukiwaniu kandydatów — badanie (26.09.2026)

- **Pytanie Artura:** czego brakuje w danych przy tworzeniu rekrutacji (formularz `/jobs/new`,
  profil Championa), żeby wyszukiwanie lepiej znajdowało kandydatów. Warunek: zachować język
  klienta (must have / nice to have), a każdą rekomendację potwierdzić testem.
- **Baza:** produkcja na `9165b4f7d`…`312d87f84` (w trakcie badania weszły wdrożenia innych sesji,
  żadne nie zmieniało bramki must-have ani formularza). Flagi produkcji istotne dla wyników:
  `CHAMPION_MATCH_SIGNALS_ENABLED=True`, `CHAMPION_SENIORITY_PENALTY_ENABLED=True`,
  `SKILL_ALIAS_EXTENDED_ENABLED=True`, `RUBRIC_DEALBREAKERS_ENABLED=True`,
  `AUTO_FULL_REVIEW_MAX_PER_NIGHT=5`, `AUTO_MATCH_REQUIRE_MUST=True`.
- **Tryb:** wszystko tylko do odczytu. Skrypty biegły w jednorazowym kontenerze z obrazem backendu
  (`run.sh`), połączenia z bazą wymuszone na `default_transaction_read_only` (`ro_boot.py`).
  Modele wołane bezpośrednio (bez zapisu telemetrii). Skrypty leżą obok:
  `docs/audits/2026-09-26/tworzenie-rekrutacji-a-wyszukiwanie/`.
- **Uzupełnia:** `docs/audits/2026-09-26/wyszukiwanie-reczne.md` (#1857) — tamten audyt dotyczy
  wyszukiwania ręcznego; ten dotyczy danych rekrutacji i wyszukiwania AI (pełny przegląd bazy,
  auto-dopasowanie). Wnioski są zgodne (tamten: tylko 38,9% wybranych spełnia 3 pierwsze must-have).

## Jak powtórzyć

Na serwerze produkcji: skopiuj katalog `tworzenie-rekrutacji-a-wyszukiwanie/` do
`/root/nexus-search-research/` i uruchamiaj `./run.sh /research/<skrypt>.py` (jednorazowy
kontener, 3 CPU / 6 GB, baza tylko do odczytu przez `ro_boot.py`). Argumenty przez zmienną
`RESEARCH_ARGS` (np. `RESEARCH_ARGS="n=120 seed=5" ./run.sh /research/model_study.py`).
`data.py` zapisuje cache zbiorów umiejętności kandydatów w `/root/nexus-search-research/cache` —
**usuń katalog po badaniu** (dane osobowe). Kolejność zależności: `gate_study` →
`model_study` (tworzy `model_sample.json`, `model_outputs_v1.json`) → `query_text_study`,
`ablation_study`, `rank_study2`, `rank_study3`. Nie uruchamiaj kilku naraz: przy czterech
kontenerach `/api/health/live` odpowiadał do 5 s. Wdrożenie w trakcie biegu restartuje Qdranta —
sprawdzaj `docker ps` (czas utworzenia `qdrant-…`) i powtarzaj bieg, jeśli wypadł w środku.
Zużycie tokenów modeli jest w tabeli B5 (łącznie kilkaset tysięcy tokenów, rząd kilku USD).

## Miara „trafności”

Nie mamy ręcznie ocenionych list, więc trafni = osoby, które zespół **wysłał do klienta**
(`analytics_first_milestones`: `cv_sent` i dalej), a osobno **mocno trafni** (rozmowa u klienta,
akceptacja, zatrudnienie). 3 811 rekrutacji ma takie osoby; 21 tys. par „wysłany”,
809 zatrudnień. Dla 23 rekrutacji założonych w NEXUSIE 25.09 (prawdziwe maile klientów) trafni =
osoby, które zespół już do nich dodał.

Ograniczenia: zespół szukał tych ludzi w Traffit, więc to próba „znalezionych”, nie „wszystkich
dobrych”; dane kandydata są dzisiejsze, nie z dnia wysyłki; część rankingów liczona na tle 3 000
losowych kandydatów (≈5% bazy), więc liczby są względne (porównanie wariantów), nie bezwzględne.

## Hipotezy i werdykty

| # | Hipoteza | Werdykt | Dowód |
|---|---|---|---|
| H1 | Bramka must-have (kandydat musi mieć KAŻDE must rozpoznane jako technologia) ukrywa trafnych | **potwierdzona, mocno** | B1, B3, B6 |
| H2 | Klient formułuje wymagania jako must have / nice to have, a Luna je wiernie przepisuje | **potwierdzona** | B2 |
| H3 | Must have klienta to w praktyce lista warunków koniecznych | **obalona** | B1, B4 |
| H4 | Wystarczy, że DL (albo model) wskaże 1–3 „krytyczne” must, i na nich zbudujemy bramkę | **obalona** (lepiej niż dziś, ale nadal gubi 28–80% trafnych) | B5, B6 |
| H5 | Winne są niepełne dane kandydata (lista umiejętności z Traffita), a tekst CV to naprawi | **częściowo** — pomaga, ale nie ratuje bramki | B4 |
| H6 | Bogatszy opis rekrutacji (mail, Champion) poprawia wyszukiwanie | **potwierdzona** | B7 |
| H7 | Język obcy jako pole do filtrowania pomoże | **obalona** (dane kandydatów tego nie niosą) | B8 |
| H8 | Wymagany staż to realny sygnał | **potwierdzona jako sygnał**, ale bramka ani kara nie poprawiają kolejności (punktacja już go liczy) | B6, B8, B9 |
| H9 | Branża (bank, ubezpieczenia…) jako dodatkowy bonus w rankingu pomoże | **obalona** — sygnał jest, ale wektor już go niesie | B8, B9 |
| H10 | Miękkie punkty za pokrycie must-have poprawią kolejność | **obalona** (zero zysku) | B6, B9 |
| H11 | Wybór modelu do czytania maila ma znaczenie | **nie dla wyszukiwania** — różnice w rdzeniu 59–72%, a każda bramka i tak przegrywa | B5 |
| H12 | Dane o biurze (miasto, dni) zapisane przy tworzeniu rekrutacji nie ukrywają trafnych | **obalona** — po zdjęciu bramki must to ona ukrywa 70 ze 150 dodanych; plus błąd nazw miast | B10, B11 |

## Badania

### B1. Obecna bramka na historii (3 057 rekrutacji; `gate_study.py`)

Reguła produkcji: `dealbreaker_filters.missing_must_skills`
(`backend/app/services/dealbreaker_filters.py:204`, wołane w `:700`) — kandydat z jakąkolwiek
wiedzą o umiejętnościach jest ukrywany, gdy brakuje mu któregokolwiek must, który przechodzi
`is_gate_eligible_must` (`:426`, reguła składniowa: krótka nazwa bez słów prozy — **nie** słownik).

| lista must | mediana pozycji | przepuszcza wysłanych | przepuszcza mocno trafnych | rekrutacji, w których ginie >50% wysłanych | przepuszcza bazy |
|---|---:|---:|---:|---:|---:|
| kolumna rekrutacji (historia z Traffita) | 1 | 27% | 26% | 71% | 3,4% |
| lista technologii jak z nowego formularza (stack Championa) | 10 | **3,5%** | 3,3% | **97%** | 0,2% |
| ta sama lista, tylko nazwy ze słownika | 5 | 23% | 22% | 78% | 2,1% |

Warianty łagodniejsze (ta sama miara, lista jak z formularza, tylko nazwy ze słownika):
„pierwsza pozycja” 73%, „co najmniej połowa” 74%, „dwie pierwsze” 55%.

Najczęściej „brakujące” u wysłanych etykiety to nie technologie, tylko zwroty i kategorie:
„software developer”, „język angielski”, „bankowość”, „wzorce projektowe”, „bazy danych”, „qa”
— bramka traktuje je jak technologie, bo przechodzą regułę składniową.

### B2. Jak wyglądają zapytania klientów i co z nich robi Luna (23 maile z 25.09)

- 22 z 23 maili ma sekcję must (Nordea: „Must-have knowledge and experience”, przetargi:
  „KOMPETENCJE OBLIGATORYJNE”), 18 — sekcję nice to have. Sekcje must mają 5–28 linii.
- Luna (`JOB_REQUEST_INTAKE`) przepisuje must wiernie: 153 ze 174 pozycji stoją w sekcji must
  maila, 10 w nice, 11 gdzie indziej.
- **Limit „max 10”** (`backend/app/services/llm_prompts.py:947`) ucina listę w 12 z 22 rekrutacji.
- Must klienta miesza rzeczy różnego rodzaju: rdzeń roli (Java, Spring Boot), przykłady
  („CI/CD tools like Bitbucket, Jenkins”), metodyki, lata, miękkie. Luna zapisuje przykłady jako
  osobne must („Bitbucket”, „Jenkins”), a wersje razem z nazwą („Java 8+”, „React.js 18+”).
- Błąd jakości: dziedzina „systemy przetwarzające dane medyczne” z `min_years = 18` (#689421).

### B3. Nowe rekrutacje z 25.09 na żywo (`new_jobs_study.py`, 11 rekrutacji z dodanymi osobami)

| wariant | osoby dodane przez zespół widoczne na liście | wśród pierwszych 100 |
|---|---:|---:|
| bez bramki | 100% | 77% |
| **obecna bramka** | **0%** | 0% |
| rdzeń z maila — Luna (+ tekst CV) | 28% | 21% |
| rdzeń z maila — Opus (+ tekst CV) | 20% | 16% |

Obecna bramka zostawia widoczne ≈0% bazy z danymi o umiejętnościach — stąd nocny przegląd bazy dla
tych rekrutacji pokazywał wyłącznie osoby bez żadnych danych (0 propozycji w 3 z 5).

### B4. Czy winne są dane kandydata? (`cv_presence_study.py`)

- Ze wszystkich przypadków „wysłany nie ma must X” 28,5% (kolumna) / 12,6% (lista z Championa)
  to X, które **jest** w pełnym tekście CV — lista umiejętności kandydata jest niepełna.
- Kontrola ręczna (SQL): 553 osoby wysłane do rekrutacji z Kafką w must — Kafka jest w CV
  u 44%, w liście umiejętności u 59%. Czyli ~40% wysłanych nie ma jej nigdzie.
- Bramka „wszystkie must” liczona z listą umiejętności **i** tekstem CV: 27% → 51% wysłanych
  (kolumna), 3,5% → 5,5% (lista z formularza). Tekst CV pomaga, bramki nie ratuje.

Wniosek: must have klienta to wymagania do rozmowy, nie filtr. Zespół wysyła — a klient
zatrudnia — ludzi, którzy spełniają część listy (mocno trafni wypadają tak samo jak wysłani).

### B5. Modele wybierające rdzeń must (`model_study.py`, 120 rekrutacji, ten sam prompt)

Prompt: „z listy MUST HAVE klienta wskaż 1–3 technologie, bez których nie wysłałbyś CV; bez wersji,
bez przykładów, bez miękkich; alternatywy jako «A lub B»”. Bramka = rdzeń; tylko lista umiejętności.

| model | śr. pozycji rdzenia | przepuszcza wysłanych | mocno trafnych | rekrutacji z >50% straty | koszt (tokeny we/wy na 120) |
|---|---:|---:|---:|---:|---|
| Claude Opus 5.5 | 1,34 | **72%** | 68% | 25% | 138 k / 51 k |
| GPT-6 Luna | 1,14 | 68% | 63% | 31% | 87 k / 8 k |
| Claude Sonnet 5 | 1,59 | 64% | 59% | 34% | 138 k / 14 k |
| Claude Haiku 4.5 | 1,84 | 59% | 49% | 40% | 101 k / 17 k |
| (bez modelu) pierwsza pozycja listy | 1 | 45% | 45% | 55% | — |
| (bez modelu) technologia z tytułu | ≤2 | 62% | 61% | 36% | — |

Opus wybiera najlepiej, Luna prawie tak samo przy ułamku kosztu. Ale żaden rdzeń nie daje
bramki bez strat (patrz B6).

### B6. Lista, którą widzi rekruter — symulacja pełnego przeglądu (`rank_study2.py`, 120 rekrutacji)

Tło: wysłani + 3 000 losowych kandydatów, ocena produkcyjna (`canonical_fit`, jak ekrany C2),
potem warianty. Dwa niezależne biegi (w obu Qdrant zrestartował się przez wdrożenia innych sesji,
co dotyka wszystkich wariantów tak samo) dały te same wyniki z dokładnością do 1 pp; tabela z drugiego.

| wariant | wysłani w top 20 | w top 100 | P@10 | MRR | widoczna część listy |
|---|---:|---:|---:|---:|---:|
| **bez bramki must** | **58,6%** | 73,2% | 0,346 | 0,758 | 100% |
| obecna bramka (wszystkie must, lista umiejętności) | 35,0% | 44,3% | 0,204 | 0,493 | 56% |
| wszystkie must, lista + tekst CV | 36,2% | 45,7% | 0,212 | 0,501 | 56% |
| połowa must, lista + tekst CV | 48,7% | 60,7% | 0,293 | 0,661 | 59% |
| rdzeń Luny, lista | 43,3% | 53,6% | 0,264 | 0,643 | 43% |
| rdzeń Luny, lista + tekst CV | 46,7% | 58,3% | 0,283 | 0,686 | 44% |
| rdzeń Sonneta, lista + tekst CV | 46,3% | 57,3% | 0,294 | 0,673 | 37% |
| bez bramki, + punkty za pokrycie must (10) | 58,9% | 73,5% | 0,345 | 0,730 | 100% |
| bez bramki, + punkty za rdzeń (15) | 59,0% | 74,5% | 0,348 | 0,760 | 100% |
| bramka stażu (minimum − 1 rok, brak danych przechodzi) | 58,4% | 72,3% | 0,345 | 0,758 | 83% |
| bramka stażu (minimum − 2 lata) | 58,6% | 73,1% | 0,346 | 0,758 | 88% |

Każda bramka z must obniża trafność o 17–40%. Miękkie punkty nie dają istotnego zysku (±0,4 pp).

### B7. Co w tekście rekrutacji znajduje właściwych ludzi (`query_text_study.py`, `ablation_study.py`)

Wektor zapytania z różnych wersji tekstu; wysłani ukryci wśród 3 000 losowych.

| tekst zapytania | wysłani w top 20 | w top 100 |
|---|---:|---:|
| **produkcyjny (tytuł, mail, must/nice, Champion)** | **54%** | **88%** |
| tytuł + must + nice + projekt | 51% | 84% |
| tytuł + lista must | 48% | 82% |
| „ustrukturyzowany” (rola, lata, rdzeń, reszta must, dziedzina) | 46% | 81% |
| tytuł + rdzeń | 36% | 69% |
| sam tytuł | 30% | 61% |
| produkcyjny **bez całego Championa** | 50% | 84% |
| bez pojedynczej sekcji Championa (pytania / search / projekt / klient) | 53–55% | 87–89% |

Każde skrócenie szkodzi; cały Champion to ok. +8% trafień w top 20, żadna pojedyncza sekcja nie
dominuje. Rekrutacje z Traffita nie mają opisu (26 z 4 355 ma >200 znaków), więc tam wektor
opiera się na tytule, must i Championie — nowe rekrutacje z mailem mają lepszy punkt startu.

Uwaga: pula zapytań auto-dopasowania i „Moich ludzi” (top 300 z wyszukiwania wektorowego +
BM25) zawiera tylko 31% wysłanych (`rank_study.py`). Pełny przegląd bazy tego ograniczenia nie ma.

### B8. Sygnały: język, staż, branża (`signals_study.py`)

- **Język:** angielski jest w profilu 48% bazy, **poziom** ma 3,8% (reszta `unknown`). Wysłani do
  rekrutacji wymagających angielskiego mają angielski w profilu rzadziej (45%) niż baza.
  Filtr po języku ukrywałby trafnych przypadkowo.
- **Staż:** 85% wysłanych spełnia wymagane minimum lat, 92% minimum − 1 rok; w bazie ≥5 lat ma 53%.
- **Branża:** przy rekrutacjach bankowych bankowość w CV ma 52% wysłanych vs 26% bazy (×2,0);
  ubezpieczenia ×4,0, energetyka ×2,4, zdrowie ×1,9, sektor publiczny ×1,9.

### B9. Sygnały dołożone do rankingu (`rank_study3.py`, 80 rekrutacji; B6 dla bramki stażu)

| wariant | wysłani w top 20 | MRR |
|---|---:|---:|
| produkcja (bez bramki must) | 57,2% | 0,771 |
| kara za staż wyłączona | 56,9% | 0,768 |
| + punkty za pokrycie must (10) | 56,9% | 0,743 |
| + bonus za branżę (5) | 55,3% | 0,764 |
| + bonus za branżę (10) | 54,1% | 0,760 |
| must (10) + branża (5) | 55,0% | 0,744 |

Kara za staż (włączona na produkcji) i bonusy nic nie dają ponad wektor: branża i technologie są
już w tekście, więc wektor je widzi. Bramka stażu (B6) skraca listę o 12–17% bez utraty trafnych,
ale też bez poprawy kolejności.

### B10. Nocny przegląd na PEŁNEJ bazie, 4 nowe rekrutacje (`full_base_check.py`, 63 tys. kandydatów)

Ocena produkcyjna każdej osoby w bazie, potem reguły produkcji z bramką must-have i bez niej.
Próg propozycji 70 pkt, najwyżej 60 propozycji (jak `AUTO_FULL_REVIEW_*`).

| rekrutacja | propozycje ≥70: dziś → bez bramki must | dodani przez zespół widoczni: dziś → bez bramki must | miejsca dodanych na liście (bez bramki must) |
|---|---|---|---|
| Senior Java Developer (Gradle, #689430) | 0 → 60 | 0/22 → 8/22 | 124, 416, 442, 780… |
| Senior Java Developer (8+, #689431) | 9 → 60 | 0/23 → 10/23 | **8**, 181, 287, 770… |
| Senior Frontend (React, #689433) | 0 → 56 | 0/10 → 2/10 | 3446, 6078 |
| Windows Expert (#689440) | 0 → 60 | 0/11 → 7/11 | **1, 9, 10, 48, 65**, 259… |

Dziś obecna bramka zostawia w każdej z nich ~3 100 osób — wyłącznie bez danych o umiejętnościach.
Bez niej lista ma ~33 tys. osób, a resztę ukrywa **bramka miasta biura (27 tys.)**.

Trzeci wariant — bez bramki must **i** bez twardej bramki biura (miasto, dni; budżet zostaje):

| rekrutacja | dodani widoczni | miejsca dodanych na liście |
|---|---|---|
| Senior Java (Gradle) | 20/22 | 147, 174, 366, 412, 466… |
| Senior Java (8+) | 22/23 | 8, 139, 183, 238, 275… |
| Senior Frontend (React) | 8/11 | 28, 100, 323… |
| Windows Expert | 11/11 | 1, 10, 11, 57, 79… |

Razem 61 z 67 (91%) zamiast 0. Dla rekrutacji Java ludzie wybrani przez zespół są jednak zwykle na
miejscach 140–800 i nie wchodzą do 60 nocnych propozycji — sama kolejność (wektor) ma tu sufit.

### B11. Dlaczego zespół „nie widzi” ludzi, których sam wybrał — nowe rekrutacje (`reasons_check.py`)

150 osób dodanych przez zespół do rekrutacji z 25.09, reguły produkcji:

| reguła | widoczni | ukryci: brak must | ukryci: miasto biura | ukryci: dni w biurze | ukryci: budżet |
|---|---:|---:|---:|---:|---:|
| dziś | **1** | 147 | — | — | 2 |
| bez bramki must | 64 | 0 | **70** | 14 | 2 |

Bramka miasta (`dealbreaker_filters.office_city_mismatch`, `:273`) jest twarda przy rekrutacjach
z dniami w biurze. Dwa problemy — oba zaczynają się przy tworzeniu rekrutacji:

1. **Porównanie nazw miast bez odmian językowych** (`location_utils.location_tokens` + `tokens_overlap`):
   „Warszawa” ≠ „Warsaw”, „Gdańsk” ≠ „Gdansk”, „Kraków” ≠ „Krakow”, a „Gdansk or Warsaw” to jeden
   token. Luna czyta angielskie maile i zapisuje miasto po angielsku: rekrutacja „Warsaw” (#689439)
   ukrywa 15 494 kandydatów z „Warszawa”; „Gdansk or Warsaw” (#689442) ukrywa każdego ze znanym
   miastem. **To błąd**, nie decyzja.
2. **Jedno miasto zamiast listy.** Klient pisze „Gdańsk, Gdynia, Warsaw, hybrid in rotation”
   (#689431), formularz zapisuje „Warszawa”. Zespół i tak dodaje ludzi z Krakowa, Wrocławia, Łodzi
   do hybryd w Warszawie (dojazdy raz–dwa razy w tygodniu, relokacja) — 70 ze 150. Audyt #1857:
   filtr miasta wycina 57,9% wybranych ze znanym innym miastem.

## Rekomendacje

### Formularz tworzenia rekrutacji (`/jobs/new`, Champion)

1. **Zostaw język klienta: „Must have” i „Nice to have”, przepisane 1:1.** Bez nowej kategorii
   „krytyczne/wymagane” jako filtra — B5/B6 pokazują, że każda bramka z wybranych pozycji gubi
   21–80% trafnych. Luna robi to dobrze (B2); zmienić dwie rzeczy:
   - **zdjąć limit „max 10”** (albo podnieść do 30) — ucina 12 z 22 list;
   - **przy każdej pozycji rozdzielić nazwę i dopisek:** „Java 8+” → „Java” (+ „8+” w notatce),
     „CI/CD tools like Bitbucket, Jenkins” → jedna pozycja „CI/CD (np. Bitbucket, Jenkins)”,
     nie trzy osobne must. To poprawia czytelność i punktację umiejętności, nie filtr.
2. **Wymagane lata doświadczenia — zawsze** (dziś 13 z 23). To jedyny poza technologiami sygnał,
   który trafni spełniają (85–92%) i który mocno różnicuje bazę. Używany w punktacji (kara za staż)
   i w screeningu; jako twardy filtr skraca listę o 12–17% bez strat, ale nie poprawia jej początku —
   opcjonalny przełącznik „ukryj młodszych niż minimum − 2 lata”, nie domyślny filtr.
3. **Pełna treść maila w opisie + Champion** — zostają jak są. Bogatszy tekst = lepsze
   wyszukiwanie (B7); nie skracać, nie zastępować „ustrukturyzowanym” skrótem.
4. **Branża i język** — zbierać (branża: `experience.domains`, język: pole z poziomem), ale jako
   informacja do screeningu i plakietka, **nie** jako filtr ani bonus. Branża już działa przez
   wektor (B9); język nie ma danych po stronie kandydata (B8).
5. Walidacja `min_years` w dziedzinach: nie więcej niż wymagany staż ogólny (przypadek „18 lat”).
6. **Biuro: lista miast zamiast jednego pola i polskie nazwy.** Luna ma zapisywać wszystkie miasta
   z maila („Gdańsk, Gdynia, Warszawa”, „w rotacji”) i zawsze w polskiej formie (Warszawa, nie
   Warsaw). Formularz pokazuje je jako chipy do poprawy przez DL (B11).

### Wyszukiwanie (to jest warunek, żeby formularz w ogóle pomagał)

7. **Zdjąć bramkę must-have z pełnego przeglądu bazy i auto-dopasowania** (ukrywanie za brak
   któregokolwiek must). Must zostaje w punktacji (warstwa umiejętności) i w plakietkach ✓/✗/?.
   Bez tego każda nowa rekrutacja z pełną listą must pokazuje wyłącznie puste profile (B3).
   Uwaga: `RUBRIC_DEALBREAKERS_ENABLED=false` wyłącza też budżet i biuro — to za dużo; zmiana musi
   dotyczyć tylko must (np. `search_dealbreaker_inputs(exclude_missing_must=False)` jako domyślne
   albo polityka `none`), z bumpem `MUST_GATE_POLICY_VERSION`.
8. **Naprawić porównanie miast** w bramce biura: odmiany językowe i bez polskich znaków
   (Warsaw/Warszawa, Gdansk/Gdańsk, Krakow/Kraków) — `pl_places` zna już aliasy („Warsaw”, „Trójmiasto”) i zwija polskie znaki — oraz
   rozdzielanie „A or B”, „A, B”. To błąd, bez decyzji produktowej.
9. **Decyzja dla Artura: bramka miasta biura twarda czy ostrzegawcza.** Dane (B11, #1857) mówią,
   że zespół wysyła ludzi z innych miast do hybryd (70 ze 150; 58% wybranych ze znanym innym
   miastem). Propozycja: przy hybrydzie inne miasto = plakietka „inne miasto — dojazd/relokacja?”
   i niższa pozycja (warstwa lokalizacji już to liczy), nie ukrycie; twardo tylko przy pracy
   stacjonarnej 4–5 dni.
10. Plakietki ✓/✗ must czytają też tekst CV (B4: 28,5% „braków” jest w CV).
11. Poza zakresem tego badania, ale wyszło po drodze: nocny przegląd bazy robi 5 rekrutacji na noc
   (z 13 nowych opublikowanych 25.09 przegląd dostało 5); filtr budżetu i miasta w wyszukiwaniu
   ręcznym wycina odpowiednio 39% i 58% wybranych ze znaną stawką/miastem (#1857).

### Czego nie robić (sprawdzone, nie działa)

- „Krytyczne must” jako twardy filtr — ani wskazane przez DL, ani przez model (B5, B6).
- Filtr po języku obcym (B8).
- Bonus za branżę albo za liczbę spełnionych must w rankingu (B9).
- Skrócony, „ustrukturyzowany” tekst zapytania zamiast pełnego (B7).
- Twarda bramka stażu jako domyślna (B6: nie poprawia kolejności).

## Sprawdzone i czyste

- Luna wiernie przepisuje sekcję must klienta (B2).
- Wektor produkcyjny (pełny tekst) jest najlepszym z testowanych wariantów (B7).
- Kara za staż nie szkodzi (B9).

## Otwarte / niepotwierdzone

- **Jakość 60 nowych propozycji po zdjęciu bramki (B10) — niepotwierdzona.** Wiemy, że się pojawią
  (56–60 na rekrutację zamiast 0–9) i że osoby wybrane przez zespół są na liście, ale tylko
  1–4 z nich wchodzi do tych 60. Czy pozostałe propozycje są trafne, oceni dopiero DL — proponuję
  pierwsze noce po zmianie przejrzeć je na 3–4 rekrutacjach.
- Pełna baza sprawdzona na 4 rekrutacjach; reszta wyników to symulacje na tle 3 000 losowych
  kandydatów (≈5% bazy). Kierunek jest ten sam we wszystkich badaniach, skala może się różnić.
- Kolejność Java-rekrutacji (osoby zespołu na miejscach 140–800) to osobny problem rankingu —
  poza tym badaniem (patrz A/B tekstu embeddingu v3, #1862).
