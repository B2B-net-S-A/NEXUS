# Pomiar A/B pasaży CV (Fala 2) — 2026-08-12 — werdykt: NO-GO

> Kontynuacja `matching-eval-2026-08-10-baseline.md`. Kryterium falsyfikacji,
> zapisane PRZED pomiarem (plan trzech fal): *jeśli sufit retrievalu przy puli
> 200 poprawi się o mniej niż ~3 p.p., hipoteza chunkowania jest dla tego
> korpusu fałszywa i zatrzymujemy się, zamiast stroić rozmiary chunków.*
>
> **Wynik: −1,8 p.p. Zatrzymujemy się.** `CV_PASSAGES_ENABLED` zostaje OFF.

## Warunki pomiaru

- Prod (Hetzner CCX33), kontener backendu po deployu `d82ee08` (#1130).
- Kolekcja `nexus_cv_passages`: **265 557 punktów** ze **49 901 CV** — komplet,
  zero pominiętych (backfill + wznowienie po restarcie Coolify + domknięcie
  luki 28 978–29 044 po incydencie Voyage). RSS Qdranta po zbudowaniu:
  **490,8 MiB** — przewidywanie z dry-runu (508 MB) trafione.
- Ustalenie uboczne: limit 2 GiB z `docker-compose.prod.yml` **nie obowiązuje
  na prodzie** (`docker inspect`: `Memory=0`) — Coolify buduje z samego
  `docker-compose.yml`, overlay prod z limitami nie wchodzi do komendy deployu.
  Dotyczy to wszystkich serwisów, nie tylko Qdranta. Doraźnie bezpieczne
  (0,5 GiB przy 30,6 GiB hosta); egzekwowanie limitów = osobna decyzja
  deploymentowa, poza zakresem tej inicjatywy.
- Obie strony: te same **40 ofert** (`--job-ids`, id 1391…), `--min-gt 3`,
  `--pool 200`, ten sam indeks, ten sam dzień. Jedyna różnica:
  `CV_PASSAGES_ENABLED` podane per-proces (`docker exec -e`).
- Ramię OFF ≠ baseline z 10.08 (16,4% vs 13,6%), bo indeks wzbogacił się od
  tamtej pory o teksty CV odzyskane w Fali 1. Porównania są ważne wyłącznie
  per-dzień — dlatego oba ramiona zmierzono tego samego dnia.

## Wyniki

| metryka | OFF | ON | Δ |
|---|---:|---:|---:|
| **Sufit retrievalu @200** (|GT ∩ pula| / |GT|) | **16,4%** | **14,6%** | **−1,8 p.p.** |
| Ofert z zerowym sufitem | 8/40 | 9/40 | +1 |
| Per oferta: lepiej / gorzej / bez zmian | — | — | 12 / 17 / 11 |
| P@5 | 0,025 | 0,030 | +0,005 |
| R@20n | 0,035 | 0,031 | −0,004 |
| MRR | 0,080 | 0,101 | +0,021 |
| nDCG@10 | 0,016 | 0,033 | +0,017 |

Największe ruchy sufitu per oferta:

| oferta | OFF → ON |
|---|---|
| Analityk Biznesowo-Systemowy (CZII) | 0% → 22% |
| ETL Developer | 47% → 63% |
| Kierownik Projektu (Bank Pocztowy) | 0% → 14% |
| Senior Power Apps Platform Developer | **83% → 42%** |
| Senior Power Platform Developer | **72% → 44%** |
| Analityk Systemowy Senior (PKO BP) | 17% → 0% |

## Interpretacja — dlaczego spadło, mimo że ranking się poprawił

Pula ma **sztywne 200 miejsc**. Scalanie union-max wpuszcza kandydatów
trafionych **jednym generycznym fragmentem** CV („współpraca z interesariuszami",
opis stosu z dawnej roli) kosztem kandydatów, których dopasowanie jest
całościowe, ale żaden pojedynczy akapit nie krzyczy. Widać to najlepiej na
ofertach Power Platform: wysoce wyspecjalizowane zapytanie, pasaże zalewają
pulę częściowymi trafieniami i wypychają ludzi, których stary wektor całego
profilu łapał bezbłędnie (83%→42%).

Jednocześnie metryki **kolejności** (MRR, nDCG@10, P@5) rosną: dla kandydatów,
którzy JUŻ są w puli, dowód z najlepszego pasażu poprawia ustawienie. Pasaże
pomagają rankować, ale psują członkostwo — a członkostwo jest wąskim gardłem
(scoring nie widzi 83,6% GT nawet w lepszym ramieniu).

## Decyzje

1. **`CV_PASSAGES_ENABLED` zostaje OFF** (default). Nie stroimy rozmiarów
   chunków — kryterium mówi „stop", nie „iteruj".
2. **Kolekcja `nexus_cv_passages` zostaje** jako zamrożony artefakt: regularny
   reindeks pasaży nie dopisuje (pisze je wyłącznie
   `scripts/backfill_cv_passages.py`), więc nie generuje bieżących kosztów
   Voyage; kasowanie kandydata usuwa jego pasaże bezwarunkowo (RODO). Re-test
   po Fali 3 (wzbogacony korpus) wymaga świeżego backfillu (~$3–4).
3. **Możliwy wariant przyszły, świadomie nieteraz:** pasaże wyłącznie do
   rankingu/uzasadnień (`similarity_for_candidate_ids`), członkostwo puli po
   staremu. Dziś zablokowane architektonicznie: cache score'ów ma klucz bez
   pola powierzchni, dlatego jedna flaga musi przełączać obie ścieżki naraz.
   Rozdzielenie = dopisanie pola powierzchni do klucza cache (inwalidacja).
4. **Żywe dźwignie sufitu:** hybryda BM25+RRF jako selekcja członkostwa
   (PR #1131, pomiar tym samym harnessem po merge) oraz rozmiar puli
   200→500/1000 (zmierzone w baseline 10.08: 13,6→22,8→32,6%).

## Pułapki harnessu (odtworzone na własnej skórze w tym pomiarze)

- `--job-ids` jest **dodatkowo przycinane** przez `--jobs` (default 10) —
  `.all()[:limit]` stosuje się PO filtrze id. A/B zawsze z jawnym `--jobs 40`.
- `--json` pisze do `<output>.with_suffix(".json")` **wewnątrz kontenera**,
  nie na stdout — przekierowanie stdout na hoście daje pusty plik.
- Marker ukończenia biegu = plik dotknięty PO `docker exec`, nie istnienie
  artefaktu (poprzedni nieudany bieg zostawia stary artefakt o dobrej nazwie).
