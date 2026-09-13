# P3 — Przepływ: zamówienia MD i kosztowe → import zużycia → zakończenie współpracy → eksport

| Pole | Wartość |
|---|---|
| Tryb | **W** — konto admina; `wyniki/LOCK` |
| Moduły | M07 → M09 → M08 → M06 |
| MUST | tak, jeśli w pilotażu jest Delivery Lead klienta wielo-konsultantowego; inaczej SHOULD |
| Zależności | P2 (kandydat P1 ma kontrakt u D1); Fala 0 (D2 w `MULTI_CONSULTANT_ORDER_CLIENT_IDS`, D5, D7, D8 bez kontraktów u D2) |
| Czas | ~3 h |
| Akcje AI | 2 odczyty PDF |
| CZŁOWIEK | krok 14 (decyzja offboardingowa — dane testowe, agent może; człowiek zatwierdza start) |

## Cel

Klient rozliczany w MD: jedno zamówienie na 3 osoby z własnymi limitami → Finanse importują
miesięczne zużycie → budżet topnieje → jedna osoba kończy → Delivery Lead decyduje, co z jej MD →
eksport Excel pokazuje stan na dziś. Obok: zamówienie kosztowe (wspólna pula) i zamiana kontraktora.

## Dane

Klient D2 (wielo-konsultantowy), osoby D5 (Anna Testowa), D7 (Maria Fikcyjna), D8 (Piotr Wzorcowy) —
BEZ kontraktów u D2 (serwer założy szkice). `zamowienie-wieloosobowe.pdf` (D5 40 MD × 1200,
Jan Próbny 30 × 1100 → zamień na Marię Fikcyjną w fixtures, D8 20 × 1300), `zamowienie-kosztowe.pdf`,
`md-import.xlsx` (5 wierszy: 3 osoby + „Nieznany Człowiek” + nazwisko odwrócone).

## Kroki — zamówienie MD

| # | Akcja (admin) | Weryfikacja | Zapisz |
|---|---|---|---|
| 1 | `/clients/{{D2}}?tab=zamowienia` → „Nowe zamówienie” → typ MD (per osoba) → `zamowienie-wieloosobowe.pdf` → „Zczytaj i uzupełnij całe zamówienie” (**AI 1**) | 3 karty; dopasowanie: `none` dla wszystkich (brak kontraktów u D2) → opcja „szkic nowego kontraktora” per karta; picker konsultanta pokazuje „Baza Nexus” z D5/D7/D8 | — |
| 2 | na każdej karcie wybierz osobę z „Baza Nexus” (`candidate_id`) → status Aktywne → Zapisz | JEDEN `POST /order-groups` z 3 liniami; grupa `active`; 3 linie z `md_total` 40/30/20 i `md_rate_revenue` 1200/1100/1300; serwer założył 3 kontrakty `draft` u D2 (`payload.contract_created` w historii); PDF w profilu KAŻDEJ osoby (Pliki i umowy) | `group_id`, 3 × `line_id`, 3 × `contract_id` |
| 3 | historia grupy | 3 × „dodanie konsultanta” z autorem admin, `origin: document` | — |
| 4 | linia D5 → stawka kosztowa MD = 900 → Zapisz (admin ma prawo) | `md_rate_cost = 900`; kontrakt D5@D2 NIE dostał tej stawki (linie grup poza kierunkiem kosztowym — zamierzone) | — |
| 5 | podgląd finance → ta grupa | liczby MD widoczne; stawki „—”; pasek zużycia 0/40 | — |

## Kroki — import zużycia MD (Finanse)

| # | Akcja (admin) | Weryfikacja | Zapisz |
|---|---|---|---|
| 6 | `/finance?view=md` → Import → `md-import.xlsx` → miesiąc = bieżący → Importuj | parser znalazł nagłówek na 2. arkuszu; kolumna „Ilość MD” (NIE „Średnia Stawka MD”); wyniki: D5 10 MD → OK; Maria 5 MD → OK (nazwisko odwrócone też dopasowane — tokeny jako zbiór); D8 8 MD → OK; „Nieznany Człowiek” → „Brak aktywnego zamówienia”; wiersz kosztowy (numer QA/003 — jeszcze nie istnieje) → `cost_status` niedopasowany | `import_id` |
| 7 | grupa → paski | D5: 30/40 pozostało; Maria: 25/30; D8: 12/20 (`md_remaining = md_total − Σ`) | — |
| 8 | ten sam plik jeszcze raz, ten sam miesiąc | IDEMPOTENCJA: wiersze konsumpcji NADPISANE (UNIQUE `(order_id, period_month)`), pozostałości BEZ zmian (nie 20/40) | — |
| 9 | linia D8 → „Korekta ręczna” +5 MD → Zapisz | `md_manual_adjustment = 5`; pozostało 17/20; ponowny import (krok 8) NIE kasuje korekty (osobna kolumna) | — |
| 10 | ręcznie edytuj plik: D8 25 MD w innym miesiącu (poprzedni) → Importuj | D8 pozostało 20 + 5 − 8 − 25 = **−8** → poniżej zera: kolor ostrzegawczy, NIE ucięte do 0 | — |

## Kroki — zamiana i zakończenie

| # | Akcja (admin) | Weryfikacja | Zapisz |
|---|---|---|---|
| 11 | linia Maria → „Zamień kontraktora” → nowa osoba D9 (bez CV — nieistotne) z „Baza Nexus”, stawka 1000, data zamiany = dziś | nowa linia: `md = 25 × 1100 / 1000 = 27,5` (wartość w PLN zachowana); stara linia `completed` z datą; zdarzenie „zamiana kontraktora” z obiema stawkami i MD w `payload` | `line_id_new` |
| 12 | jw. z datą zamiany w PRZYSZŁOŚCI (+7 dni) na linii D5 → nowa osoba D6? (D6 ma kontrakt u D1, u D2 nie — OK) | stara linia dostaje datę, ale `status` NIE `completed` (dzień nie nadszedł); nowa linia zaplanowana | — |
| 13 | `/contracts/{{contract_D8@D2}}` → „Wypowiedz” (terminacja) z datą dziś, powód `contractor_found_other_project` | kontrakt `ended`; linia D8 `completed`, `end_date` ucięta do dziś; **sprawa offboardingowa** `pending` w grupie; alert DL (jeśli `DL_ALERTS_ENABLED`) | `case_id` |
| 14 | sprawa → decyzja **„Przywróć”** (współpraca trwa) → data końca: pusta (zamówienie bezterminowe) | linia D8 wraca na `active`; kontrakt D8@D2 wskrzeszony (`sync_contract_to_live_order`) jako aktywny BEZTERMINOWY; pula NIETKNIĘTA (−8 dalej); zdarzenie `przywrocenie_konsultanta` | — |
| 15 | ponownie wypowiedz D8@D2 → sprawa → decyzja **„Przenieś”** MD na linię D5 | pula D8 przeliczona na D5 po stawkach (`md_D5 += md_D8_pozostałe × 1300 / 1200`; przy −8 → ujemne przeniesienie? zapisz zachowanie — oczekiwane: odmowa lub 0; to obserwacja, nie P1); D8 poza obsadą; pod D8 zdanie „wykorzystał(a) X MD … nie wraca do puli” | — |
| 16 | grupa → „Zakończ zamówienie” z datą w przyszłości (+30 dni) | data zapisana; grupa `completed` od razu, linie `active` do daty (lustro syncu terminacji); import za bieżący miesiąc NADAL działa dla tej grupy (`group_settles_in_month`) | — |
| 17 | grupa → „Przywróć” | grupa `active`; `closure_*` wyczyszczone | — |

## Kroki — zamówienie kosztowe

| # | Akcja (admin) | Weryfikacja | Zapisz |
|---|---|---|---|
| 18 | „Nowe zamówienie” → kosztowe → `zamowienie-kosztowe.pdf` (**AI 2**) → 2 osoby z bazy (D5, D7 — mogą mieć już szkice u D2, zostaną REUŻYTE) → Zapisz | grupa `is_cost_based`, `budget_amount = 150 000` na GRUPIE; linie bez MD; ŻADNEGO drugiego kontraktu tej samej osoby u D2 | `cost_group_id` |
| 19 | import: plik z wierszem `QA/003/2026`, kwota 40 000, osoba D5 | `settle_group`: `budget_used = 40 000`, `budget_remaining = 110 000`; `settled_amount` na linii D5 | — |
| 20 | import: kwota 200 000 (ponad budżet) | `budget_remaining = 0` (nie ujemne), `unsettled_amount = 90 000` na KONKRETNEJ linii; UI: „budżet przekroczony” z osobą | — |
| 21 | „Zamień kontraktora” na linii kosztowej D7 → D9 | DZIAŁA (nie 422 „brak budżetu MD”); nowa linia z NULL-ami MD; `budget_remaining` bez zmian | — |

## Kroki — eksport i widoki

| # | Akcja | Weryfikacja | Zapisz |
|---|---|---|---|
| 22 | Eksport Excel zamówień D2 | wiersze: tylko linie obowiązujące DZIŚ, jedna na kontrakt; linia z zamianą w przyszłości (krok 12): STARA osoba (nowa zaczyna później); wiersz zbiorczy grupy obecny; zakończone (Maria z kroku 11) NIEobecne | plik |
| 23 | `/clients/{{D2}}` → Profil → Konsultanci | osoby z aktywnymi liniami; stawki MD; MRR | — |
| 24 | `/clients/{{D2}}` → Profil → „Zakończeni” | Maria (kontrakt `draft`, nie `ended` → NIE w Zakończonych, bo decyduje UMOWA) — zapisz, gdzie ląduje | — |
| 25 | podgląd DL przypisany do D2 → cała zakładka | kwoty widoczne (portfel); akcje cyklu życia widoczne | — |
| 26 | Pomoc → instrukcja zamówień → data „ostatnia aktualizacja” | równa stemplowi (`stamp_orders_procedure.py`) — jeśli w Fali 3 zmienisz logikę zamówień, CI wymusi przestemplowanie | — |

## Sprzątanie

Po P4. Do `utworzone.json`: grupy, linie, importy (`DELETE` jeśli API pozwala; inaczej „ręcznie”),
kontrakty `draft` u D2 (usuwalne), sprawy offboardingowe.

## Kryteria PASS

Kroki 2, 6–8, 11, 13–14, 18–20, 22 = P1 przy FAIL. Kroki 4, 9, 10, 15–17, 21 = P2.
Zachowanie z kroku 15 (ujemna pula przy „Przenieś”) — zapisz jako obserwację do decyzji produktowej.
