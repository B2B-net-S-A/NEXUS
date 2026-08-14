# Program naprawy wyszukiwarki talentów — raport końcowy (2026-08-10 → 2026-08-14)

> Kontynuacja `matching-eval-2026-08-10-baseline.md` (NO-GO i diagnoza sufitu
> retrievalu) oraz `matching-eval-2026-08-12-passages-ab.md` (werdykt pasaży).
> Ten dokument domyka trzy fale + pomiary końcowe.

## Wynik końcowy (warunki produkcyjne: pula 1000 + boost historyczny)

| metryka | baseline 10.08 | **14.08** |
|---|---:|---:|
| **Sufit retrievalu** (|GT ∩ pula| / |GT|) | 13,6% (@200) | **41,3%** (@1000) — **3×** |
| Ofert bez ani jednego GT w puli | 9/40 | **2/40** |
| **P@5** (prod, z boostem) | 0,085 | **0,125 (+47%)** |
| **MRR** (prod, z boostem) | 0,209 | **0,291 (+39%)** |

Pokrycie danych (populacja 57 478 kandydatów):

| pole | przed | po |
|---|---:|---:|
| skills (realna lista) | ~600 (1%) | **49 379 (86%)** |
| city | 7 647 (13%) | **40 471 (70%)** — po biegu znormalizowane egzonimy (5 391 wierszy, Warsaw→Warszawa itd.) |
| years_it_experience | 671 (1,2%) | **49 651 (86%)** |
| country | ~0 | **48 590 (85%)** |

## Co weszło (chronologicznie)

1. **Fala 1** — odzysk tekstów CV z plików + `MATCH_POOL_SIZE=1000` z batch
   N+1 (#1099) + naprawa harnessu (`--pool`, pełne `ranked_candidate_ids`).
2. **Fala 2 (pasaże)** — zbudowana, zmierzona A/B, **NO-GO** wg zarejestrowanego
   kryterium (sufit @200 −1,8 p.p.); flaga OFF, kolekcja zamrożona. Szczegóły
   w raporcie z 12.08.
3. **Hybryda BM25+RRF** (#1131) — zmierzona: +0,4 p.p., 38/40 ofert bez zmiany
   członkostwa puli; flaga OFF.
4. **Fala 3 (backfill pól z CV)** — 49 792 CV przez Haiku 4.5 w 3 shardach CLI
   (`--until-id` #1137, samowznawialne launchery przeżyły ~10 deployów).
   Koszt realny **$365** (52 312 calli, 105,8M in / 51,9M out). Reindeks
   wektorów w rytmie biegu (outbox: 56 121 done / 0 pending po zakończeniu);
   `mark_stale_for_candidate` unieważnia cache score'ów w tym samym workerze.
5. Po drodze wymuszone jakością danych: normalizator kształtu `skills`
   (#1134 — Haiku oddawał JSON-string w 75% wierszy; +192 historyczne stringi
   ścieżki interaktywnej naprawione skryptem), pre-check kolizji e-maila +
   kwarantanna savepoint per wiersz (#1141 — duplikat osoby zatruwał paczkę
   i płacił wielokrotnie), limity pamięci compose realnie egzekwowane (#1135),
   pin `qdrant:v1.17.1` (#1136).

## Ablacja wag (14.08, pula 1000, 40 ofert) — kierunek sfalsyfikowany

| profil | P@5 | R@20n | MRR |
|---|---:|---:|---:|
| default (35/30/12/8/5) | 0,020 | 0,050 | 0,082 |
| semantic_only | 0,030 | 0,031 | 0,110 |
| **skills_only** | **0,000** | 0,011 | 0,022 |
| skills_heavy / semantic_heavy / balanced | ~0,020 | ~0,050 | ~0,082 |
| **default + boost historyczny (= prod)** | **0,125** | **0,120** | **0,291** |

Wnioski:

- **Miksy wag są w szumie** — strojenie wag zamknięte jedną tabelą, zero kodu.
- **Boost historyczny (similar-jobs) to najsilniejszy sygnał rankingowy**
  (6× P@5 względem czystych wag) — już produkcyjny.
- **`skills_only` = 0 NIE jest bugiem.** Warstwa działa (test empiryczny:
  GT 20/20, losowi 0/20 na ofercie „Java") — ale jest **bramką binarną**:
  wewnątrz puli 1000 dla javowej oferty Javę mają prawie wszyscy, więc remis.
  Po Fali 3 słabszą stroną dopasowania jest **oferta**: `must_skills` to
  zwykle 1–3 generyczne wpisy („Java", „Power Platform"), czasem artefakt
  („Software Developer"). Warstwa skills nie ma na ofercie materiału, żeby
  różnicować.

## Rekomendowany następny krok (nierozpoczęty — decyzja biznesowa)

**Wzbogacenie strony ofertowej**: ekstrakcja 5–8 granularnych, ważonych
wymagań z JD dla ofert z ubogim `must_skills` (~88% korpusu), tym samym
wzorcem co Fala 3 (kalibracja → pomiar → pełny bieg; koszt rzędu $20 na
~4k ofert). Kryterium zarejestrowane przed pomiarem: `skills_only` P@5 > 0
i `default+boost` bez regresu na tych samych 40 ofertach.

Pozostałe otwarte artefakty:
- **129 unikalnych duplikatów osób** (kolizje e-maili z biegu) —
  `/root/email-collisions-dedup.txt` na serwerze; wsad dla dedupu, NIE scalać
  automatycznie.
- ~9,9k wierszy „wiecznie w scope" = CV bez danego pola (głównie miasta) —
  nie przepuszczać ponownie, to granica korpusu.
