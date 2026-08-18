# Zamówienia u klienta: cykl życia, zamówienia kosztowe, powiadomienia DL, PDF

Pięć ticketów, jeden PR, jedna migracja (`0233`). Wszystkie dotykają zakładki
**Klienci → profil → Zamówienia**, która renderuje **dwa różne widoki** — i to
rozwidlenie jest osią całej pracy.

| Widok | Kiedy | Komponent | Tickety |
|---|---|---|---|
| wielo-konsultantowy (MD) | `MULTI_CONSULTANT_ORDER_CLIENT_IDS` (BIK/Polkomtel/BNP) | `MultiConsultantOrdersTab` | usuwanie/zakończenie/przywrócenie/PDF, zamówienia kosztowe |
| jednoosobowy | wszyscy pozostali (Alior, Bank Pocztowy…) | `OrdersAndContractsTab` | PDF w „Uzupełnij zamówienie", drag&drop, liczniki, brakujące pola |
| dashboard DL | — | `DashboardV2Preset` | sekcja Powiadomienia |

## Co się zmieniło

### 1. Cykl życia zamówienia (widok MD)

`client_order_groups` dostaje `status` ∈ `active | completed | exhausted`.
**Stan, nie data** — data nie odróżnia zamówienia domkniętego świadomie od
takiego, któremu minął termin, a to dwie różne decyzje operacyjne.

Nowe trasy: `DELETE …/lines/{id}`, `DELETE …/{group}` (kasuje też linie — do
0233 zwracało 409 i pomyłki zostawały w rejestrze na zawsze), `POST …/close`,
`POST …/reopen`, `POST …/extend`.

Trzy decyzje, które trzeba znać:

* **Zakończenie jest lustrem syncu terminacji kontraktu** (`contracts.py:2918`):
  data zapisuje się zawsze, `completed` dostają tylko linie, których dzień już
  nadszedł. Bez tego zakończenie zaplanowane w przód wyłączałoby kogoś, kto
  dziś pracuje.
* **Usunięcie nie kasuje linii z historią** — zdejmuje ją z grupy. Twarde
  kasowanie tylko dla szkicu bez pliku PO, zużycia MD i faktur. Ticket żąda
  „znika bez śladu", więc wpis `dodanie_konsultanta` tej osoby też znika, ale
  `zamiana_kontraktora` ZOSTAJE: mówi o dwóch osobach naraz.
* **Przedłużenie to NOWA grupa** (`predecessor_group_id`), nie edycja
  poprzedniej — na poprzedniej rozliczono już faktury.

### 2. Zamówienia kosztowe (Polkomtel)

Kwota mieszka na **grupie**, nie na linii: to jedna pula dzielona przez kilku
konsultantów. Linia kosztowa ma obie stawki i **puste pola MD** — dlatego 0233
rozluźnia `ck_client_orders_md_coherence`. Gwarancja, o którą chodziło, zostaje
(budżet wymaga dodatniej stawki przychodowej — jest dzielnikiem), ale odwrotność
przestaje obowiązywać. **Do 0233 linia kosztowa w ogóle nie dawała się zapisać.**

`settle_group` przelicza całe zamówienie **od zera**, po `(period_month,
order_id)`. To nie jest ostrożność, tylko mechanizm: razem z UNIQUE
`(order_id, period_month)` czyni ponowny import idempotentnym, a stała kolejność
sprawia, że odpowiedź na pytanie „której osobie zabrakło budżetu" nie zmienia
się między odczytami. `settled_amount` / `unsettled_amount` są **zapisane**, nie
liczone przy odczycie.

Reszta nie schodzi poniżej zera; nadwyżka ląduje jako `unsettled_amount` na
konkretnej linii — „budżet przekroczony o X" bez wskazania osoby nie daje się
rozliczyć z klientem.

**UI pokazuje TRZY liczby.** Ticket nazywa „zużyciem" wartość, która maleje —
czyli resztę. `Kwota 50 000 · wykorzystano 30 000 · pozostało 20 000` + pasek.
Jedno pole podpisane „zużycie", a pokazujące resztę, myli dokładnie w rozmowie
o pieniądzach.

### 3. Import: „Uwagi" i „Faktura"

Ścieżka kosztowa jest **drugą, niezależną** ścieżką w „Import zużycia MD"
(`/finance?view=md`) — nie w „Wynikach miesięcznych", których świadoma decyzja
o nieprzechowywaniu „Uwag" zostaje nietknięta.

Numer wybierany jest przez **konfrontację z istniejącymi zamówieniami**
(`extract_order_number_candidates`), nie heurystyką „najdłuższy ciąg cyfr":
w tej samej komórce stoi często rok albo numer transzy, a zgadywanie odjęłoby
kwotę z cudzego budżetu i wyszło dopiero na fakturze. Wiersz wchodzi na tę
ścieżkę tylko gdy ma **numer i kwotę** — bez kwoty nie ma czego odjąć, więc
czerwień byłaby fałszywym alarmem.

`cost_status` jest OSOBNĄ kolumną od `status`: jeden wiersz bywa jednocześnie
MD-dopasowany po nazwisku i kosztowo-niedopasowany po numerze.

> **Defekt znaleziony przy pisaniu testów, naprawiony.** Realny arkusz z Finansów
> ma obok siebie „Średnia Stawka MD" i „Ilość MD". Parser brał **pierwszą
> pasującą** kolumnę, czyli STAWKĘ, i raportowałby 1000 „dni" zamiast 15. Błąd
> byłby cichy — liczba jest poprawna arytmetycznie, tylko opisuje co innego.
> Dodane `_MD_ANTI_HEADERS` (stawka/rate/cena/kwota/…) plus regresja.

### 4. Powiadomienia Delivery Leada

**Osobna tabela `dl_alerts`, nie `notifications`.** Tamta zna wyłącznie
`is_read`: nie wie, kto i kiedy sprawę załatwił, więc nie ma czasu reakcji,
czyli nie ma czego wyeksportować. Ma też dobowy indeks dedupu, który tłumiłby
powtórki, i fail-closed filtr widoczności, przez który rola Finanse nie
zobaczyłaby tych wpisów niezależnie od nadanych uprawnień.

**Powtórka co 7 dni jest NOWYM wierszem**, nie aktualizacją — raport ma
pokazywać, ile tygodni sprawa czekała. Numer okna wchodzi w `dedupe_key`, a okno
liczy się od daty PIERWSZEGO alertu tej sprawy, nie od poniedziałku (inaczej
wszystkie alerty zsynchronizowałyby się w jeden dzień i sekcja stawałaby się
cotygodniową ścianą). Powtórki ustają po `handled` **albo** gdy warunek ustąpi.
Wpisy nie są kasowane — log JEST raportem.

Cztery reguły w jednym rejestrze `ALERT_RULES`; dołożenie piątej to dopisanie
funkcji i wpisu. Wyczerpanie budżetu jest **zdarzeniowe** (emitowane w chwili
zejścia do zera), nie skanowane — opisuje stan, który się już nie zmienia.

Eksport XLSX: DL własne wpisy, `scope=all` tylko admin i Finanse. Parametr jest
jawny, żeby admin otwierający własną skrzynkę nie wyeksportował przypadkiem
cudzych spraw. Komórki tekstowe przechodzą przez `_formula_safe` (treść alertu
niesie nazwy wpisane przez ludzi).

### 5. Widok jednoosobowy: liczniki i pola, których „nie było"

**Liczniki** przy czterech pigułkach liczone z tej samej listy, co filtr —
predykaty w jednym miejscu, bo dwie kopie tej samej reguły dają licznik, który
nie zgadza się z listą pod nim. „Kończące się 30d" jest podzbiorem „Aktywni",
więc suma pigułek świadomie ≠ „Wszyscy".

**Zgłoszenie „u Banku Pocztowego nie da się nic wpisać" — przyczyna ustalona
z kodu, nie zgadnięta.** „Stawka przychodowa" wisiała na `canManageFinance &&
activeOrder`, a „Numer" i „Okres" renderowały nieedytowalne `—`, gdy kontraktor
nie ma ani jednego `ClientOrder`; stawka kosztowa renderowała się, ale zapis
rzucał wyjątkiem. **U Aliora pola działają wyłącznie dlatego, że jego zamówienia
zostały kiedyś zaimportowane — to różnica DANYCH, nie konfiguracji klienta.**

Dlatego poprawka jest jedna i globalna: przy braku zamówienia wszystkie cztery
pola są edytowalne, a pierwszy zapis zakłada szkic `ClientOrder` (`title` =
wpisany numer albo `"(bez numeru)"`, status `draft`) i stosuje wartość. Obejmuje
wszystkich 27 klientów z listy i każdego przyszłego. Alior nie jest dotykany.

### 6. PDF: odczyt i drag&drop

Nowy `ds/FileDropZone` — jeden komponent zamiast szóstej niezależnej
implementacji drag&drop w repo. Widoczny obszar to **`<label htmlFor>`**, nie
`div role="button"`: etykieta wiąże tekst z prawdziwą kontrolką, klik otwiera
okno natywnie, a automatyzacja trafia w pole po nazwie. (Pierwsza wersja użyła
diva i **złamała istniejące testy** `ExtendOrderDialog` — złapane, poprawione
w komponencie, nie w teście.) Walidacja rozszerzenia i rozmiaru jest **ta sama
dla obu dróg dodania**; upuszczenie omija atrybut `accept` przeglądarki.

`md_total` doszedł do odczytu (`ORDER_EXTRACTION` v2 — bump konieczny, cache
promptu jest kluczowany wersją). **Nie podlega redakcji finansowej** — MD są
wielkością operacyjną, a to DL ma je wpisać.

**Dwie polityki nadpisywania, celowo różne** (oba wymogi są w ticketach wprost):
widok MD pyta „Tak/Nie" przy rozbieżności z ręcznym wpisem, widok jednoosobowy
nadpisuje po cichu. Wspólna warstwa: `lib/order-extraction.ts`.

## Skutki uboczne wybranych opcji — przyjęte świadomie

* **Rola `finance` dostaje cztery akcje cyklu życia**, czyli także wgląd w listę
  z nazwiskami konsultantów — powierzchnię, od której repo konsekwentnie ją
  odcina. Wybrane przy planowaniu (dosłowne odczytanie ticketu).
* **`head_of_recruitment` dostaje te akcje u WSZYSTKICH klientów**, bez
  przypisania: tak działa istniejący guard tras. Delivery Lead nadal potrzebuje
  jawnego przypisania.
* **`_has_md_line_management_role` (stawki) NIE został poszerzony** — zostaje
  przy admin + DL. Broni tego `test_rate_gate_did_not_leak_to_lifecycle_roles`.

## Świadomie poza zakresem

* **Wejście nawigacyjne do modułu Klienci dla roli `finance`.** `nav.clients` to
  role operacyjne; ten PR nadaje uprawnienie w API i pokazuje przyciski, ale nie
  otwiera całego modułu (lista klientów, Projekty, Profil, Analityka) dla
  Finansów — to osobna zmiana RBAC. **W praktyce przyciski klikną admin, Head of
  Recruitment i przypisany Delivery Lead.**
* **Pole „Liczba MD" w `ExtendOrderDialog`** (widok jednoosobowy). Byłoby martwe:
  klienci MD tego dialogu nigdy nie widzą, a zwykłe zamówienie nie ma budżetu MD,
  w którym ta liczba mogłaby wylądować. Odpowiednikiem jest **„Dodaj
  przedłużenie" w widoku MD** (`ExtendOrderGroupModal`), gdzie liczba MD trafia
  na linię konsultanta — zgodnie z wybraną opcją.
* **Zakończenie/wyczerpanie zamówienia NIE terminuje kontraktów konsultantów.**
  Ticket mówi wprost, że pozostają widoczni; wyczerpany budżet to fakt handlowy,
  nie koniec współpracy. MRR i rejestr kontraktów nietknięte.

## Weryfikacja

| Co | Wynik |
|---|---|
| Łańcuch migracji od zera na czystym Postgresie 16 (`… → 0230 → 0233`) | ✅ |
| Jedna głowa alembica (liczona AST-em) | ✅ 1 |
| **Lustro `entrypoint.sh` uruchomione na bazie zatrzymanej na 0230** | ✅ 0 pominiętych instrukcji spośród nowych |
| **Diff schematu: migracja vs lustro** (72 kolumny, CHECK-i, UNIQUE) | ✅ identyczne |
| Backend: nowe testy (`test_order_lifecycle_and_cost`, `test_dl_alerts`, `test_md_import_cost_columns`, `test_order_lifecycle_migration`) | ✅ 55 |
| Backend: istniejące testy zamówień i parserów | ✅ 93 |
| `ruff check` + `ruff format --check` na zmienionych plikach | ✅ |
| Frontend `type-check`, `lint`, `build` | ✅ |
| Frontend vitest (pełny) | ✅ 1299 |

Lustro DDL sprawdzone **wykonaniem**, nie czytaniem: `entrypoint.sh` łyka błąd
każdej instrukcji z osobna i drukuje `skip:`, więc zepsute DDL jest **ciche** —
jedyny dowód to uruchomienie go na bazie i porównanie schematu z migracją.

Harnessy wizualne (publiczne, zero zapytań do API):
`/preview/order-lifecycle` (5 stanów karty: MD, kosztowe, wyczerpane
z niepełnym rozliczeniem, zakończone, brak zejścia) oraz `/preview/dl-alerts`
(dane, pustka, awaria — obok siebie, żeby widać było, że nie wyglądają tak samo).

## Aktywacja na produkcji

1. `COST_ORDER_CLIENT_IDS` = ID Polkomtela w Coolify. Pusto → checkbox
   „Zamówienie kosztowe" nie renderuje się nigdzie, a API odrzuca założenie
   takiego zamówienia (fail-closed).
2. `DL_ALERTS_ENABLED` — domyślnie `true`. Wyłączenie kończy pętlę skanera
   **przed** nią, nie budzi procesu co 24 h po to, by sprawdzić tę samą flagę.
3. Po deployu `/api/health/deep` musi być zielony i pokazywać obie nowe tabele —
   to jedyny realny dowód, że migracja się wykonała (prodowy alembic bywa
   osierocony).
