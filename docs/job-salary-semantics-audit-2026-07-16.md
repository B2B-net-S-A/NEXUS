# Audyt semantyki `Job.salary_min/max` — brief do decyzji

**Data:** 2026-07-16
**Kontekst:** program przebudowy wyszukiwania (SEARCH-P0-01) podpiął filtr stawki godzinowej pod `Candidate.expected_rate_hourly`, a prefill z oferty mapuje `Job.salary_min/max` → `rate_hourly_min/max`. Audyt planu wskazał "rate-semantics data audit" jako otwartą decyzję biznesową. Ten brief dostarcza dane **z historii kodu** (bez dostępu do prod DB).

## Ustalenia (code-level, konkluzywne)

1. **Jedyny moment zmiany semantyki:** commit `80ae156` z **2026-06-11** — _"feat(jobs): stawka godzinowa zamiast miesięcznej w formularzu dodawania oferty"_. Wcześniej formularz zbierał **stawkę miesięczną**, od tej daty zbiera **PLN/h** (dzisiejsze labelki: "Stawka godzinowa min/max (PLN/h)").
2. **Writerzy pola** (wszyscy przeanalizowani):
   - formularz UI (AppShell) — jedyne źródło ręcznych wartości;
   - klonowanie oferty (`jobs.py` `copy_fields` oraz `clients.py:203`) — **dziedziczy** wartości źródłowej oferty, więc klon oferty sprzed 2026-06-11 przenosi semantykę miesięczną nawet przy późniejszym `created_at`;
   - **import Traffit NIE zapisuje salary** (mappers/importer — brak pola) — brak trzeciego źródła.
3. **Konsekwencja dla wyszukiwania:** prefill oferty "miesięcznej" (np. 15 000–20 000) trafia do filtra PLN/h → wyklucza wszystkich kandydatów z wypełnioną stawką (zostają tylko ci bez stawki, bo missing=included). Filtr jest wtedy bezużyteczny, choć nie zeruje wyników.

## Reguła podziału danych (do walidacji na prod DB)

| Kryterium | Interpretacja |
|---|---|
| `created_at < 2026-06-11` | miesięczna (PLN/mies.) |
| `created_at ≥ 2026-06-11` | godzinowa (PLN/h) |
| wartość < 1 000 | na pewno godzinowa |
| wartość > 3 000 | na pewno miesięczna |
| 1 000–3 000 | dwuznaczna (rzadkie; ręczny przegląd) |

Walidacja SQL (read-only, do odpalenia z serwera / przez snapshot):

```sql
SELECT
  (created_at >= '2026-06-11') AS after_cutoff,
  COUNT(*)                                        AS jobs,
  COUNT(*) FILTER (WHERE salary_min IS NOT NULL)  AS with_salary,
  COUNT(*) FILTER (WHERE salary_min > 3000)       AS looks_monthly,
  COUNT(*) FILTER (WHERE salary_min < 1000 AND salary_min IS NOT NULL) AS looks_hourly
FROM jobs GROUP BY 1;
```

## Opcje decyzji (dla Artura)

**A. Kolumna `salary_period` (rekomendowana).** Migracja dodaje `salary_period VARCHAR` (`hourly`/`monthly`), backfill regułą data+wartość z tabeli wyżej; prefill wyszukiwania używa `salary_min/max` tylko gdy `hourly`. Zero przekształcania liczb = zero ryzyka zepsucia danych; dwuznaczne rekordy dostają `NULL` (prefill je pomija).

**B. Konwersja in-place.** Jednorazowa migracja `miesięczna ÷ 168 → godzinowa` dla rekordów sprzed cutoffu. Prostszy model danych, ale nieodwracalnie przekształca oryginalne wartości i wymaga arbitralnego przelicznika (168 h/mc vs 160 vs 21×8).

**C. Nic nie robić.** Filtr stawki w prefillu bywa bezsensowny dla starych ofert; rekruterzy czyszczą go ręcznie. Koszt: cicha strata trafności.

Decyzja blokuje: pełne zaufanie do prefillu stawki + przyszłe Phase-4 unified scoring (stawka jako sygnał dopasowania).
