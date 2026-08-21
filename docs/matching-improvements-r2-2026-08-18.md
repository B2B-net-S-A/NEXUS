# Wyszukiwarka — runda 2 ulepszeń 1–6 (2026-08-18)

> Kontynuacja programu jakości matchingu po rundzie 1
> (`docs/matching-improvements-1-6-2026-08-18.md`). Diagnoza po rundzie 1:
> sufit retrievalu ~50% przy puli 2000 i semantyka = 60% score'u przesuwają
> największą dźwignię z wag na REPREZENTACJĘ (co wkładamy do wektora)
> i stronę zapytania. Sześć ulepszeń w jednym PR, dyscyplina bez zmian:
> flagi default-OFF, pomiar na zamrożonych zbiorach, flip tylko zwycięzców.

## Zmierzone przesłanki (prod, 18.08)

| fakt | liczba |
|---|---|
| CV dłuższe niż 3000 znaków (ucinane przez builder v1) | **31 959 / 50 596 (63%)** |
| Kandydaci z `skills_evidenced` z notatek (nigdy w wektorze) | **7 352** |
| Daty `end` w `experience[0]` (cecha świeżości) | **83 / 52 876 (0,16%)** |
| Role w `experience[0]` (cecha title-match) | 16 610 / 52 876 (31%) |

## Co weszło (per punkt)

**1. Embedding tekst v3 + kolekcja side-by-side** (`AI_TEXT_SCHEMA_V3`,
default OFF). `build_candidate_text_v3` = sekcje v2 (bez PII) + **pełne CV
zawsze** (cap 12 000 znaków; v1 ucinał na 3 000, a voyage-3-large przyjmuje
32k tokenów — limit był naszym literałem) + sekcja `[NOTES]` z faktów
potwierdzonych w rozmowach (`skills_evidenced`, certyfikaty, języki; świadomie
BEZ stawek, wet i luk — stawki to dane wrażliwe, a luka obserwowana to sygnał
negatywny). Payload punktu w Qdrancie **traci pole `name`** (nikt go nie
czyta — zweryfikowane grepem; PII w indeksie to koszt RODO bez zysku).
Przełącznik kolekcji istniał od dawna (`QDRANT_COLLECTION`); oba wpisy weszły
do `_SCORING_CACHE_INPUTS`, więc flip unieważnia cache score'ów.
`delete_candidate_embedding` kasuje teraz z **każdej** kolekcji o prefiksie
`nexus_candidates` — w oknie side-by-side kasowanie tylko z aktywnej
zostawiałoby wektor osoby w drugiej (klasa przecieku domknięta wcześniej dla
pasaży). `reembed_collections` dostał `--ensure-collection`.

**2. Multi-query retrieval** (`MULTI_QUERY_RETRIEVAL_ENABLED`, default OFF).
Unia pul z zapytania głównego + wariantów (`tytuł+seniority`,
`must+nice skills` — `build_job_query_variants`). Warianty decydują
o CZŁONKOSTWIE puli; podobieństwo dosypki liczone osobno względem tekstu
głównego (`similarity_for_candidate_ids`) — ten sam wzorzec co hybryda, bo
kosinusy względem różnych tekstów żyją na różnych skalach. Dlatego flaga
świadomie NIE wchodzi do `_SCORING_CACHE_INPUTS` (zamrożone testem). Wpięte
we wszystkie pięć powierzchni fasady: rekomendacje, Talent Radar, propozycje,
digest, harness.

**3. Higiena pomiarowa.** Drugi zamrożony holdout **B** (50 ofert:
`FROZEN_JOB_IDS_2026_08_B`) — Champion + GT≥3 + bez seedów, z wykluczeniem
zbioru A ORAZ 50 ofert treningowych LTR. Po kilkunastu eksperymentach na A
werdykt GO przyszłego flipu powinien odtwarzać się na zbiorze, którego żadna
dotychczasowa decyzja nie widziała. Kontrola progów (`RECOMMENDATION_MIN_SCORE=40`,
digest 55) po zmianie rozkładu score'ów — pomiar operacyjny po deployu.

**4. Cechy do nominacji offline.** Zrzut warstw (`--dump-layers`) niesie teraz
pole `features` z `title_match` (Jaccard tokenów merytorycznych tytułu oferty
vs role z historii kandydata; stopwordy seniority odpadają). `weight_search`
dostał `--with-feature NAME` — cecha wchodzi jako dodatkowy wymiar simpleksu
(siatka rekurencyjna zamiast zagnieżdżonych pętli). **Cecha świeżości
doświadczenia: NO-GO-data** — daty końca ról ma 0,16% kandydatów; cecha na
martwej kolumnie nie ma czego mierzyć (najpierw wymagałaby backfillu dat,
osobna decyzja).

**5. LTR właściwy — trener offline** (`scripts/ltr_train.py`). Gradient
boosting (drzewa głębokości 2, histogramy, logloss), czysty stdlib,
deterministyczny, walidacja k-fold PO OFERTACH; porównanie z liniowym
baseline'em tymi samymi metrykami rankingowymi. Regresja logistyczna byłaby
bez sensu (monotoniczna sigmoida = ten sam ranking co wagi liniowe), więc
pytanie brzmi wyłącznie: czy NIELINIOWOŚĆ coś wnosi. Werdykt z biegu na
zrzucie treningowym — sekcja „Pomiary" niżej.

**6. Powierzchnie omijające silnik.** Rekonesans (agent, pełna tabela 28
powierzchni w transkrypcie sesji) wykazał, że obie wady z audytu 08-07 są już
naprawione: filtr `experience_years` przepuszcza NULL-e (rejestr `NULL_POLICY`
+ test na `IS NULL` w SQL), a rekomendowane wyszukiwania Championa są
hybrydowe (`q` + `search_mode="hybrid"` w schemacie i promptcie v2). Realna
resztka była we FRONCIE: `CandidateSearchView` startował z
`search_mode: "boolean"` (standalone `/candidates/search` nie dotykał wektorów,
dopóki użytkownik nie kliknął „Semantycznie"), a `AddCandidatesQuickModal`
w ogóle nie wysyłał trybu. Oba przełączone na **default `"hybrid"`** — bramka
backendu wymaga niepustego `q`, więc wyszukiwanie samymi filtrami zachowuje
się identycznie jak dotąd; hybryda włącza się dokładnie tam, gdzie wnosi
wartość. Poza zakresem (świadomie): `_count_matching_candidates` jako dolne
oszacowanie (udokumentowane w kodzie), `ILIKE` bez unaccent w top-barze
(nawigacja, nie talent matching), stały `champion_fit` dla kandydatów spoza
pipeline'u (zmiana scoringu = osobny pomiar).

## Protokół pomiarowy (po deployu)

1. **v3**: `reembed_collections --target candidates --commit --ensure-collection`
   w procesie z `QDRANT_COLLECTION=<nazwa v3> AI_TEXT_SCHEMA_V3=true`
   (koszt ~$10–15, ~57k kandydatów) → A/B harnessem na zamrożonych A
   (`docker exec -e` z oboma env) → przy GO potwierdzenie na holdoucie B →
   flip obu env w Coolify (cache inwaliduje się digestem) → po oknie
   stabilności drop starej kolekcji.
2. **Multi-query**: A/B `docker exec -e MULTI_QUERY_RETRIEVAL_ENABLED=true`
   na zbiorze A, potwierdzenie na B przy GO.
3. **title_match**: świeży zrzut `--dump-layers` (już z `features`) → simpleks
   `--with-feature title_match` → ewentualna walidacja `--weights` na A + B.
4. **Progi**: histogram score'ów przy nowych wagach → korekta env tylko przy
   wyraźnym rozjeździe.

Kryterium GO bez zmian: R@20n bez regresu (≥ baseline − 0.002) ORAZ ≥1 metryka
rankingowa > baseline + 0.002; od tej rundy dodatkowo potwierdzenie kierunku
na holdoucie B.

## Pomiary — komplet (18.08 wieczór)

Orkiestrator post-deploy: baseline → multi-query → świeży zrzut z features →
re-embed 57k do kolekcji side-by-side (~34 min, ~$12) → evale v3.
Wszystko na zamrożonym zbiorze A, pula 2000, wagi 60/10/15/5/0.

| eksperyment | zbiór | P@5 | R@20n | MRR | nDCG | werdykt |
|---|---|---|---|---|---|---|
| baseline | A | 0.248 | 0.199 | 0.461 | 0.162 | — |
| multi-query | A | 0.248 | 0.199 | 0.461 | 0.162 | **NO-GO** (zero delty) |
| embedding v3 | A | **0.220** | 0.191 | 0.432 | 0.171 | **NO-GO** (P@5 −11%, R −0.008) |
| v3 + multi-query | A | 0.220 | 0.191 | 0.432 | 0.171 | NO-GO (jak v3) |
| linear 60/10/15/5/0 (referencja zrzutu) | train | 0.093 | 0.154 | 0.259 | — | — |
| GBDT d2×60 (CV po ofertach) | train | 0.093 | **0.087** | 0.244 | — | **NO-GO** |
| title_match (simpleks 6D) | świeży zrzut | — | — | — | — | **NO-GO** (waga 0 w całym topie) |

**Wnioski rundy 2 — wszystkie cztery eksperymenty jakościowe NO-GO, i to jest
wynik, nie porażka:**

- **Multi-query zero delty przy puli 2000** — spójnie z hybrydą: przy tej
  wielkości puli dźwignie CZŁONKOSTWA są wyczerpane; zapytanie główne już
  pokrywa kierunki wariantów (warianty to podzbiory treści oferty).
- **v3 (pełne CV + notatki) POGARSZA precyzję** mimo lepszego nDCG: surowy
  tekst 12k znaków rozmywa wyselekcjonowany sygnał strukturalny w jednym
  uśrednionym wektorze. To samo zjawisko, które położyło pasaże — dłuższy
  kontekst na wejściu ≠ lepszy wektor. Kolekcja v3 skasowana (odtworzenie
  = jeden bieg reembed).
- **title_match**: tylko 8% par ma niezerową wartość, a simpleks — mogąc
  oddać cesze dowolny budżet — daje jej 0 w każdej czołowej kombinacji.
- **Sufit obecnej architektury osiągnięty.** Reprezentacja (jeden wektor),
  członkostwo puli i forma modelu (liniowa) są wycisnięte. Dalszy postęp
  wymaga NOWYCH DANYCH (daty ról, champion sync z Traffita, adopcja
  pipeline'u → lepsze GT), nie kolejnych przestawień istniejących.

**Co z rundy 2 REALNIE działa na prodzie:** hybryda domyślna w wyszukiwarce
ręcznej (zweryfikowana klikiem: 199 wyników/1,2 s, badge „Semantycznie" od
wejścia), delete ze wszystkich kolekcji (RODO), payload bez nazwisk, holdout B
jako bezpiecznik przyszłych flipów, maszyneria cech w zrzucie + trener LTR.

**Punkt 5 rozstrzygnięty offline:** nieliniowość na frakcjach pięciu warstw
NIE wnosi sygnału — GBDT remisuje w P@5 i wyraźnie przegrywa R@20n i MRR
z liniowym optimum simpleksu (porównanie i tak konserwatywne dla GBDT).
LTR właściwy zamknięty bez kosztu serwingu; kolejne podejście miałoby sens
dopiero z NOWYMI cechami (np. title_match po nominacji), nie z tą samą piątką.

## Pułapki utrwalone w tej rundzie

- Cecha wymaga danych: świeżość doświadczenia wyglądała rozsądnie, a ma 0,16%
  pokrycia dat — **pokrycie kolumny mierz PRZED pisaniem kodu cechy**.
- Kosinusy względem różnych tekstów (warianty zapytań) nie mogą trafiać do
  jednej `similarity_map` — członkostwo z unii, podobieństwo z tekstu
  głównego (wzorzec hybrydy, zamrożony testami).
- Fake'i `retrieve_candidate_pool` w testach muszą przyjmować nowe kwargi
  fasady — dwa testy padły na `TypeError` w try/except, który połknął błąd
  i zwrócił pustą listę (awaria wyglądała jak pusty wynik).
