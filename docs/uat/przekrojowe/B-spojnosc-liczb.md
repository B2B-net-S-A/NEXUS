# B — Kontrola przekrojowa: spójność liczb między ekranami

| Pole | Wartość |
|---|---|
| Tryb | **R** |
| Persony | admin (widzi wszystko) + finance (do potwierdzenia, że widzi to samo) |
| Zależności | najlepiej PO P2/P3 (klient D1 ma konsultanta, kontrakt, zamówienie) — inaczej pary 1–6 na PRAWDZIWYM kliencie (tylko ID) |
| Czas | ~3 h |
| Głębokość | pełna |
| Akcje AI | nie |

## Cel

Ta sama wielkość pokazana w dwóch miejscach musi być równa. Agent nie ocenia, czy liczba jest
prawdziwa (to Fala 4) — ocenia, czy system sam sobie nie przeczy. Każda para = jeden wiersz
w tabeli wyników z DWIEMA wartościami i wynikiem `=` / `≠`.

## Pary do sprawdzenia

| # | Wielkość | Miejsce A | Miejsce B | Tolerancja |
|---|---|---|---|---|
| 1 | Aktywne MRR klienta | profil klienta → kafel „Aktywne MRR” | profil → tabela Konsultanci → Σ kolumny „Marża” | 0,01 |
| 2 | Marża konsultanta | profil → Konsultanci → „Marża” | (Stawka przychodowa − kosztowa) po przeliczeniu na PLN | 0,01 |
| 3 | Stawka przychodowa konsultanta | profil → Konsultanci | `/contracts/{id}` → krok harmonogramu klienta obowiązujący DZIŚ | 0 |
| 4 | Stawka kosztowa konsultanta | profil → Konsultanci | `/contracts/{id}` → krok harmonogramu kandydata DZIŚ | 0 |
| 5 | Stawka kosztowa w zamówieniu (jednoosobowe) | profil → Zamówienia → zamówienie | `/contracts/{id}` → stawka kosztowa na dzień referencyjny zamówienia | 0 |
| 6 | Okres zamówienia | profil → Zamówienia | `/contracts/{id}` → „Koniec zamówienia u klienta” (`client_order_*`) | 0 |
| 7 | MRR klienta | profil klienta → kafel | Insights → Rada → Klienci (MRR) → wiersz klienta | 0,01 |
| 8 | Liczba aktywnych konsultantów klienta | profil → Konsultanci (licznik) | `/contractors` z filtrem klienta | 0 |
| 9 | Liczba kandydatów w rekrutacji | `/jobs` karta D3 | `/jobs/{{D3}}` nagłówek | 0 |
| 10 | Liczba kart na kanbanie | Σ nagłówków kolumn | nagłówek rekrutacji | 0 |
| 11 | Kandydaci na etapie X | kanban D3 kolumna X | `/candidates` z filtrem rekrutacja=D3 + etap=X | 0 |
| 12 | Placementy osoby | Insights → Rekrutacja → Placementy | Insights → Liga → Hall of Fame (ta sama osoba, „Wszystko”) | 0 |
| 13 | Placementy per klient | Insights → Delivery Lead → Placementy wg klientów | Insights → Rekrutacja → Placementy z filtrem klienta | 0 |
| 14 | Lejek: liczba na etapie „CV wysłane” | Insights → Rekrutacja → Lejek (okres = poprzedni miesiąc) | Dashboard → lejek (ten sam okres, jeśli wybieralny) | 0 lub zapisz definicję różnicy |
| 15 | Wynik przeglądu bazy | `/talent-radar` (ten sam run) | `/jobs/{{D3}}` → Wyszukiwania (ten sam run) | populacja, kompletne, niekompletne, kolejność top 20 = 0 |
| 16 | Dopasowanie kandydata | `/candidates/search` kolumna | `/jobs/{{D3}}` → dock kandydata → pierścień | 0 (ten sam `profile_key`) |
| 17 | MD pozostałe (grupa MD) | karta grupy → pasek linii | `GET …/order-groups` → `md_total − Σ konsumpcji + korekta` | 0,000001 |
| 18 | Budżet kosztowy | karta grupy → `budget_remaining` | `budget_amount − budget_used + korekta` | 0,01 |
| 19 | Liczba umów B2B „aktywne i w trakcie” | generator → zakładka 1 licznik | `GET …/generated?contract_status=active&contract_status=in_progress` → total | 0 |
| 20 | Liczba kontraktów obowiązujących | `/contracts` licznik „M aktywnych kontraktów” | `GET /api/contracts?status=active` + `status=ending` → total | 0 |
| 21 | Wyniki miesięczne: suma | `/finance` → stopka | Σ wierszy (3 kolumny) | 0,01 |
| 22 | Wyniki miesięczne vs Rada | `/finance` → miesiąc X przychód | Insights → Rada → KPI i finanse → miesiąc X | zapisz definicję różnicy, jeśli ≠ |
| 23 | Statystyki systemu | Ustawienia → System → „Kandydaci” | `/candidates` licznik łączny | 0 (lub różnica = usunięci/soft-deleted — zapisz) |
| 24 | Zgłoszenia | `/applications` licznik | `/jobs/{{D3}}` → ogłoszenia → zgłoszenia | 0 |
| 25 | Powiadomienia nieprzeczytane | dzwonek badge | `GET /api/notifications?unread=true` → total | 0 |

## Procedura

1. Dla każdej pary: otwórz A, zapisz wartość + zrzut; otwórz B, zapisz + zrzut; oblicz.
2. `≠` → zgłoszenie **P1** z obiema wartościami, obiema trasami, ID obiektu. Nie interpretuj,
   która strona ma rację — to robi Fala 3.
3. Dla par 7, 12, 13, 14, 22: jeśli `≠`, sprawdź, czy ekrany DEKLARUJĄ różną definicję
   (np. kod definicji `first_hired_per_candidate_job` w obu odpowiedziach API). Ta sama
   deklaracja + inne liczby = P1. Różne deklaracje = obserwacja produktowa (P3), nie błąd.
4. Pary 15–16: uruchom JEDEN przegląd (liczy się do limitu 3 z M02 — skoordynuj; najlepiej
   użyj `run_id` z M02 zamiast nowego).

## Wynik — `wyniki/B/spojnosc.md`

```markdown
| # | Wielkość | Obiekt (ID) | A | B | Wynik | Zgłoszenie |
|---|---|---|---|---|---|---|
| 1 | Aktywne MRR | client {{D1}} | 12 400,00 | 12 400,00 | = | — |
| 12 | Placementy | user 42, Wszystko | 17 | 15 | ≠ | B-B01 |
```
