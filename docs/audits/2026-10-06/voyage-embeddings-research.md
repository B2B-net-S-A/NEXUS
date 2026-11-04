# Embeddingi Voyage — badanie na danych produkcyjnych (06.10.2026)

Pytanie: co można poprawić w wyszukiwaniu po znaczeniu (Voyage + Qdrant), żeby
NEXUS lepiej znajdował właściwych ludzi. Wszystko liczone na produkcji, tylko
odczyt, w jednorazowym kontenerze z obrazem backendu (`voyage-research/run.sh`).
Dane zostały na serwerze (`/root/voyage-research`), na dysk trafiły wyłącznie
wektory i liczby — żadnych tekstów CV. Koszt Voyage: 89,7 mln tokenów ≈ 6 USD.

## Metoda

- **Prawda:** para (rekrutacja, osoba), która doszła co najmniej do
  „Zweryfikowany” (verified, cv_sent, rozmowy, akceptacja, zatrudnienie).
  2 965 rekrutacji z ≥ 3 takimi osobami (badanie z 16.09 miało 80).
- **Podział w czasie:** uczenie/strojenie na rekrutacjach do 30.06.2025 (1 672)
  i z 2. półrocza 2025 (482), **wynik na rekrutacjach z 2026 (810)**. Sygnały
  z historii używają wyłącznie zdarzeń sprzed pierwszego ruchu ocenianej
  rekrutacji (`t0`).
- **Miara:** ranga każdej osoby z prawdy wśród WSZYSTKICH ~65 tys. kandydatów
  z wektorem (bez puli). R@K = odsetek osób z prawdy w top K; MRR = 1 / ranga
  najwyżej ustawionej. Różnice: bootstrap par rekrutacji, 95% CI; `*` = istotne.
- Zapytanie produkcyjne = `_build_job_text(job, max_field_chars=None)` + etykiety
  kontraktu wymagań, typ `query`, kawałki po 8000 znaków uśredniane (jak
  `full_search_measurement.request_vector`).

## Wyniki

### 1. Zapytanie (strona oferty) — obecne jest najlepsze

Test 2026, n = 810; bazowo R@100 0,327 · R@500 0,600 · MRR 0,221.

| Wariant zapytania | R@100 | R@500 | MRR |
|---|---|---|---|
| sam tytuł | −17,6* | −26,0* | −13,2* |
| tytuł + must/nice | −4,4* | −6,3* | −4,6* |
| bez profilu Championa | −3,7* | −5,2* | −2,3* |
| „pseudo-CV” (HyDE) jako document | −9,8* | −13,2* | −8,4* |
| ten sam tekst jako `document` | −2,1* | −3,1* | −1,3* |
| obecne + tytuł/wymagania (suma wektorów) | ≈0 | ≈0 | ≈0 |
| centrowanie / usuwanie głównych składowych | −3…−10* | −5…−23* | −1…−6* |

(punkty procentowe względem obecnego zapytania)

### 2. Indeks — zdrowy, z dwoma błędami

- 99,8% wektorów odpowiada aktualnemu tekstowi kandydata; 100% to voyage-3.
- **Nowi kandydaci mają nieaktualne wektory:** 125 ze 164 kandydatów dodanych
  w NEXUSIE w październiku (76%). Przyczyna (sprawdzona hashem dla każdego):
  kategoria kompetencji ustawiana PO zapisie wektora
  (`index_outbox_service.assign_cc_after_embed`, zmiana z 05.10), a kategoria
  jest w tekście v1 — nic nie zleca ponownego przeliczenia.
- **Reconciler dryfu nie dochodzi do nowych kandydatów:** kursor trzymany
  w pamięci (`tasks/index_drift_reconciler_task.py`, `cursors = {...: 0}`),
  pełne przejście = 65 tys. / 500 co 5 min ≈ 11 h, a każdy deploy zaczyna od
  id 0. Nowi kandydaci mają najwyższe id, więc są sprawdzani ostatni — czyli
  w praktyce nigdy.
- 1 932 punkty w Qdrancie (2,9%) bez kandydata w bazie (sieroty). Narzędzie
  `/api/admin/index-cleanup` istnieje.
- Kandydaci z tekstem < 500 znaków (5,1%, głównie CV-skany bez tekstu) są
  niewidoczni dla wyszukiwania po znaczeniu (średnio w top 100 przy 0,22
  rekrutacji vs 4,79 dla reszty). Wśród osób z prawdy to tylko 0,5%.
- Huby nie są problemem (najczęściej wypływający kandydaci to w 70% osoby
  rzeczywiście wybierane).

### 3. Tekst kandydata i model — małe różnice

300 rekrutacji z 2026, pula 11 747 kandydatów (osoby z prawdy + 10 tys. tła),
wszystkie warianty przeliczone dziś; odniesienie = obecny tekst v1 przeliczony
dziś (R@100 0,550, MRR 0,371).

| Wariant | R@10 | R@100 | R@500 | MRR | tokeny |
|---|---|---|---|---|---|
| v1 bez imienia i nazwiska | +0,5 | +0,5 | +0,4 | +1,1 | = |
| v1 bez imienia, nazwiska i angielskiej etykiety stażu | +0,5 | **+1,7*** | **+0,8*** | −0,5 | = |
| profil bez surowego CV (umiejętności, stanowiska, podsumowanie) | **+1,8*** | **+2,1*** | +0,4 | +0,3 | **¼** |
| CV na początku tekstu | −4,0* | −9,7* | −7,2* | −6,9* | = |
| v2 (kanoniczny, bez danych osobowych) | +0,2 | +1,0 | −1,3 | **−4,3*** | 0,2× |
| voyage-3.5 | +0,7 | +0,5 | +0,7 | −1,3 | = |
| voyage-4-large | +1,3 | +2,4* | 0,0 | −1,7 | 2× cena |

Zmiana modelu nadal nic nie daje (jak 16.09). v2 jest gorsze — nie włączać.

### 4. Uczenie na naszych parach — umiarkowany zysk samego wektora

Adapter zapytania: macierz 1024×1024 nakładana na wektor zapytania po Voyage,
uczona ridge na celu „średnia osób z prawdy − średnia trudnych negatywów”
(top 2000 bez prawdy). Wektory kandydatów bez zmian.

| | R@100 | R@500 | R@1000 | MRR |
|---|---|---|---|---|
| adapter z negatywami (λ=3, a=2) | **+3,2*** | **+2,4*** | 0,0 | **+3,5*** |
| adapter tylko na pozytywach | +1,2 | +3,2* | +2,3* | −0,5 |

### 5. Historia — największa dźwignia (nie jest to zmiana embeddingu)

**60,5% osób zweryfikowanych w rekrutacjach z 2026 było wcześniej
zweryfikowanych w innej rekrutacji; 75,6% było wcześniej w jakimkolwiek
pipeline.** Wektor tego nie wie. Sygnały (wszystkie bez przecieku — tylko
zdarzenia sprzed `t0`, bez wierszy tej samej rekrutacji):

- **F2** — premia dla osób z prawdy 25 najbardziej podobnych wcześniejszych
  rekrutacji (podobieństwo wektorów ofert), waga 0,05 × podobieństwo;
- **G2** — osoba zweryfikowana gdziekolwiek w ostatnich 30 dniach, +0,06.

| Test 2026 (n = 810) | R@100 | R@500 | R@1000 | MRR |
|---|---|---|---|---|
| obecnie (sam wektor) | 0,325 | 0,599 | 0,733 | 0,220 |
| premia legacy (algorytm `fetch_historical_boost_map`) | 0,462 | 0,693 | 0,791 | 0,358 |
| F2 | 0,475 | 0,704 | 0,801 | 0,372 |
| — tylko ten sam klient | 0,474 | 0,700 | 0,800 | 0,329 |
| — tylko inni klienci | 0,360 | 0,624 | 0,747 | 0,247 |
| G2 | 0,457 | 0,692 | 0,798 | 0,365 |
| **F2 + G2** | **0,525** | **0,736** | **0,825** | **0,401** |

Wynik jest taki sam dla rekrutacji sprzed uruchomienia przepięć (22.09) —
to nie echo istniejącej funkcji. Na tych samych 74 ofertach z badania 16.09:
sam wektor MRR 0,18, ocena kanoniczna 0,23, ocena legacy z premią historii 0,26.

**Koszt:** osoby nowe dla firmy (nigdy wcześniej w pipeline, ~24% prawdy)
spadają: R@500 0,625 → 0,584. Premia historii nie może zjadać miejsc nowym.

Dzisiaj premia historii działa tylko w starszych ścieżkach (`/ai-matches`,
rekomendacje, `compute_proposals`). Ocena kanoniczna — pełny przegląd bazy,
nocne „Propozycje z bazy”, kolumna „Dop.”, kolejność „Szukaj ręcznie” — świadomie
jej nie ma (`eval_matching.py`: „canonical fit never folds process history”).

## Ograniczenia

- Prawda to decyzje rekruterów, więc premiuje ich nawyki (stąd spadek dla
  nowych osób). Mierzymy „czy znajdujemy tych, których zespół wybrał”.
- Miara to sam wektor + sygnały; pełna ocena kanoniczna (stawka, lokalizacja,
  umiejętności) nie była przeliczana dla 810 rekrutacji.
- Etap 3 na próbce 300 rekrutacji i 11,7 tys. kandydatów, nie na całej bazie.

## Odtworzenie

Skrypty w `voyage-research/` (kopie tych z serwera). Kolejność:
`export.py` → `embed_queries.py` → `a0_quality.py`, `a1_variants.py`,
`a2_history.py`, `a2b.py`, `a2c.py`, `a2d.py` → `a3_candtext.py` → `a3_eval.py`
→ `a4_hubs.py`, `a5_stale.py`. Uruchamianie: `./run.sh <skrypt>` na serwerze
w `/root/voyage-research`.
