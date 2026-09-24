# Test obciążeniowy produkcji — 24.09.2026

Cel: czy NEXUS wytrzyma ~30 osób pracujących naraz. Narzędzie i procedura:
`qa/load/prod-readonly.js`, `qa/README.md` (sekcja „Test obciążeniowy produkcji”).

## Jak mierzono

- Produkcja, wyłącznie odczyty, 14 prawdziwych kont (admin, 8 rekruterów, 4 DL,
  1 HoR), tokeny wystawione w kontenerze na 3 h i usunięte po biegu.
- Persony: 60% rekrutacja, 25% delivery, 15% kierownictwo. Przerwy 5–15 s
  między ekranami, ekran = kilka żądań równolegle, odpytywanie co 5 min.
- Bieg `load` 21:44–22:03 (10 → 30 osób) przerwało wdrożenie PR #1798 z innej
  sesji. Bieg `peak` 22:34–22:58: 30 osób przez 10 min, 50 osób przez 8 min.
- Monitor co ~19 s: `/api/health/live` z zewnątrz, CPU/RAM kontenerów,
  połączenia w `pg_stat_activity`; minutowe `runtime_metrics` z logów backendu.

## Wynik

| | 30 osób | 50 osób |
|---|---|---|
| Żądania/s | 9,6 | 15,7 |
| Błędy HTTP | 0 | 0 |
| p95 wszystkich żądań API (cały bieg) | 0,96 s | |
| Postgres CPU śr. / maks. | 133% / 494% | 177% / 489% |
| Backend CPU śr. / maks. | 22% / 65% | 37% / 81% |
| Obciążenie hosta (8 vCPU) śr. / maks. | 2,0 / 2,8 | 3,5 / 4,5 |
| Połączenia z puli w użyciu, maks. (limit 60) | 32 | 33 |
| Opóźnienie pętli zdarzeń, maks. w minucie | 0,3–2,1 s | 0,4–1,3 s |
| `/api/health/live` z zewnątrz, mediana / maks. | 169 ms / 3,2 s | 165 ms / 1,1 s |

**30 osób: system działa, bez błędów, z zapasem sprzętowym.** Większość ekranów
ma medianę 0,1–0,3 s. Przy 50 osobach też bez błędów, ale p95 wolnych ekranów
rośnie o 20–50%.

Jedyne błędy (2,5% w biegu `load`) zaczęły się dokładnie o 20:02:52Z, w chwili
wdrożenia: Coolify restartuje cały stos razem z Postgresem, ok. 2 min 502/503.

## Wąskie gardła (p50 / p95 przy 30 → 50 osobach)

| Endpoint | 30 osób | 50 osób | Przyczyna |
|---|---|---|---|
| `GET /api/competitions/monthly-races` | 5,7 / 6,1 s | 6,4 / 8,3 s | ranking na żywo (`VERIFIER_ANCHORED_CTE`) przy każdym wejściu na Insights |
| `GET /api/kpis/me/today` | 4,8 / 6,1 s | 5,1 / 7,0 s | osobne CTE dla każdego KPI; front odpytuje co 5 min u każdego na każdym ekranie |
| `GET /api/competitions/current` (Liga rekruterów) | 2,8 / 3,5 s | 3,3 / 4,6 s | jak wyżej |
| `GET /api/kpis/me/goals` (DL) | 0,08 / 0,15 s | 0,08 / 11,7 s | rzadkie przeliczenie po wygaśnięciu cache'u (120 s) |
| `GET /api/insights/team/people` | 0,13 / 0,2 s | 0,14 / 4,4 s | jak wyżej (cache 300 s) |
| Wyszukiwanie kandydatów (dosłowne) | 1,0 / 1,8 s | 1,3 / 2,4 s | |
| Lista kandydatów (50 wierszy) | 0,7 / 0,9 s | 0,8 / 1,4 s | |

Pętla zdarzeń backendu stoi co minutę od 0,3 do 2 s. W tym czasie nawet
`/api/health/live` czeka (3,2 s przy limicie healthchecka Dockera 5 s). To
praca Pythona w jedynym procesie uvicorna, nie baza: pula ma zapas, Postgres
ma wolne rdzenie.

## Co zrobiono w tym PR

- Rankingi konkursów (`/current`, `/monthly-races`) liczone raz na 60 s dla
  wszystkich (jeden wykonawca), cache czyszczony po zamrożeniu i rozstrzygnięciu
  remisu. Wynik nie zależy od oglądającego; nagrody wypłaca zamrożenie.

## Rekomendacje (poza tym PR)

1. **Wdrożenia nie w godzinach pracy.** Każde wdrożenie to ~2 min 502/503 dla
   wszystkich (restart całego stosu, łącznie z Postgresem). W dniu startu:
   etykieta `wstrzymaj` na PR-ach albo merge po pracy.
2. **`/api/kpis/me/today`:** policzyć wszystkie KPI jednym przebiegiem CTE
   zamiast osobno dla każdego KPI i dodać krótki cache per osoba — dziś to
   najdroższy element odpytywania w tle.
3. **Opóźnienia pętli zdarzeń:** znaleźć, która trasa blokuje pętlę na 1–2 s
   (profil `py-spy dump` w trakcie obciążenia albo log czasu CPU per żądanie).
4. Powtórzyć bieg `peak` po wdrożeniu tego PR — oczekiwany spadek
   `monthly-races`/`current` do pojedynczych przeliczeń na minutę.

## Czego test nie sprawdza

Przeglądarki, AI (generator CV, Jarvis), zapisów, importów i eksportów XLSX
oraz tras pominiętych jako zapisujące albo z limitem na IP (lista w
`qa/README.md`).
