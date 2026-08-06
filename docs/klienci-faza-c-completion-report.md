# Faza C ticketów Klienci — completion report (tickety #3 + #5)

> Domknięcie programu 5 ticketów pracownika: [analiza](klienci-tickety-analiza.md) ·
> [weryfikacja Codexa](klienci-tickety-weryfikacja-codex.md) · [Faza A](klienci-faza-a-completion-report.md) ·
> [decyzje Fazy B](klienci-faza-b-decyzje.md). Data: 2026-08-06.
> **Status: WDROŻONE + smoke-tested na prod (`d9f8c28`).**

## PR #1056 — ticket #3: „część umowy" Centrum e-Zdrowia
- `client_orders.project_part` — VARCHAR(8) nullable + CHECK `cz1|cz2|cz4|cz5|cz6`
  (cz.3 celowo nie istnieje). Migracja **0216** + mirror w `entrypoint.sh`.
- Bramka po **client_id=115** (`app/services/ezdrowie.py` + lustrzany
  `frontend/src/lib/ezdrowie.ts`) — nie po nazwie (decyzja Fazy B).
- Walidacja: Flow A/B wymagają części dla e-Zdrowia („Wybierz część umowy"),
  zakazują u pozostałych; PATCH waliduje słownik.
- Profil: filtr części (pigułki) tylko dla e-Zdrowia; `project_part` z
  **reprezentatywnego zamówienia** (pokrywa dziś, fallback najnowsze — przyszłe
  przedłużenie nie przejmuje wiersza); licznik zawęża się z filtrem (review).
- Formularze: dropdown pod Rekrutacją w „Nowy kontraktor" i przedłużeniu
  (dziedziczy część); select kompletacji na karcie zamówienia (disabled na czas
  zapisu + re-sync po błędzie — review).
- „Otwarte rekrutacje" (lista) usunięta u WSZYSTKICH klientów, kafelek metryki
  zostaje; akcje **Dodaj/Lost przeniesione do Projektów** (`CloseJobAsLostModal`
  = jedyny caller `POST /jobs/{id}/close` — bez re-homingu funkcja by zginęła).
- Bonus: `update_order` eager-loaduje kontrakt — ubita latentna mina
  `MissingGreenlet` 500 (żaden test wcześniej nie PATCHował zamówień).

## PR #1057 — ticket #5: epic zakończenia projektu
- **Sync jedną datą**: `POST /contracts/{id}/terminate` domyka w tej samej
  transakcji zamówienia kontraktu — startujące po dacie → `cancelled`; otwarte →
  `end_date = data`, `completed` gdy data nadeszła (przyszłą materializuje
  dzienny skaner — lustrzana semantyka P0.7, konsultant nie znika z Obecnych
  przed datą efektywną). **B2BGeneratedContract nietknięty** (step 6).
- **Idempotentny replay** — identyczna dyspozycja bez drugiej `Activity`/aneksu
  (fix duplikatu z weryfikacji audytów).
- Profil: sekcja „Konsultanci" z zakładkami **Obecni | Archiwum konsultantów**
  (Archiwum = read-model z zakończonych kontraktów, end date, ReEngage);
  wiersz z **koszt + przychód + marża** (`monthly_rate_candidate`, redakcja
  finansowa); **„Zakończ" usunięty z Obecnych**; „Historia" → „Przegrane rekrutacje".
- Akcje: „Zakończ" w Zamówieniach obok przedłużenia (tylko active/ending);
  „Zakończ projekt" per wiersz w Kontraktach (wiersz = 1 projekt u 1 klienta —
  wybór klienta zbędny, ustalenie Q12; `ContractorListItem.client_id` dodany).
- Modale: **data zakończenia WYMAGANA** (required + guard) — dotąd puste pole
  przechodziło i backend po cichu podstawiał dzisiaj.

## Testy / weryfikacja

| Warstwa | Wynik |
|---|---|
| BE pytest (docker, alembic heads z 0216) | `test_ezdrowie_project_part` 5/5 (Flow A/B required+forbidden, PATCH edge-cases, profil reprezentanta z edycją na żywo) · `test_terminate_engagement_sync` 2/2 (dziś + data przyszła, cancelled-future, historyczne nietknięte, replay bez dubla Activity) · regresje dl_portal 15/15, suite B2B |
| BE ruff | check + format ✓ (obie bramki) |
| FE | tsc ✓ · lint ✓ · vitest 31–38/38 (`ezdrowie.test.ts` — bramka po id, słownik bez cz.3, NULL-part tylko pod „Wszystkie") |
| Review | #1056: 3 wątki naprawione (testy Flow B/PATCH, licznik przy filtrze, race+revert selecta) · #1057: 0 wątków |

## Wyniki smoke na produkcji (2026-08-06, `d9f8c28`)

**Ticket #3 (Centrum e-Zdrowia, id 115):**
- Filtr „Wszystkie części + cz.1/2/4/5/6" widoczny NA 115; klik cz.2 → licznik
  0 + „Brak konsultantów spełniających wybrane kryteria." (części jeszcze
  nieuzupełnione — NULL tylko pod „Wszystkie", zgodnie z projektem).
- Formularz „Nowy kontraktor": „Wybór części umowy *" pod Rekrutacją + hint
  „Pole wymagane dla Centrum e-Zdrowia."
- Kontrola negatywna (BNP): brak filtra i pola.
- Lista „Otwartych rekrutacji" zniknęła też u klienta z 2 otwartymi (kafelek
  „2" został); Projekty: akcje **Dodaj/Lost** przy aktywnych, szkice bez akcji.

**Ticket #5:**
- Profil BNP: zakładki „Obecni konsultanci (36) | Archiwum konsultantów (0)";
  wiersz „koszt 16 000,00 zł/mc · przychód 22 720,00 zł/mc · marża 6 720,00 zł";
  w Obecnych tylko „Extend" — „Zakończ" zniknął.
- Zamówienia: „Zakończ" obok „Dodaj przedłużenie" przy aktywnych (drafty bez —
  celowo); modal „Powód *" + **„Data zakończenia projektu *"** + „Zakończ
  projekt" → **anulowany** (żaden realny kontrakt nie został zakończony —
  mechanika syncu pokryta 2 testami integracyjnymi).
- Kontrakty: „Zakończ projekt" przy każdym z 379 aktywnych wierszy.

## Znane ograniczenia / świadomie poza zakresem
- Pełny e2e terminacji na prod nieodpalony (mutacja realnych danych) — pokrycie
  przez testy integracyjne BE.
- Limit 100 na `historical.placements`/`lost_jobs` (widoczny na e-Zdrowiu:
  „Przegrane (100)") — paginacja Archiwum do wzięcia, gdy pierwszy klient
  przekroczy 100 zakończeń.
- Drobne z listy weryfikacji nadal otwarte: snapshot stawki historycznej,
  granica dnia Europe/Warsaw, off-by-one terminate vs skaner, PATCH-bypass pól
  terminacji, TAC-scope terminacji (świadoma decyzja do podjęcia).

## Program 5 ticketów — stan końcowy

| Ticket | Realizacja |
|---|---|
| #1 statusy + nazwa | Faza A (#1052 nazwa→display_name) + Faza B (#1054 status NEXUS-owned + kuracja 98×inactive; sekcje≠status — decyzja; 2 GUARDED: Ergo Hestia, Nationale Nederlanden do przeniesienia placementem) |
| #2 wyszukiwarka zamówień | Faza A (#1051) — smoke: nazwisko 9→1, numer „RITM0813" 47→1 |
| #3 część umowy e-Zdrowia | Faza C (#1056) — po scaleniu duplikatu 37721→115 (#1054) |
| #4 stawka przychodowa + karta | Faza A (#1051) — pkt 1 istniał; sprzątanie + bugi /mc i 0-jako-brak |
| #5 zakończenie projektu | Faza C (#1057) — sync jedną datą, Obecni/Archiwum, 2 powierzchnie akcji |
