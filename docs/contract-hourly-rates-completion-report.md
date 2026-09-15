# Stawki w module Kontrakty w zł/h — raport ukończenia

Ticket: „Ujednolicenie stawek w module Kontrakty do formatu godzinowego" (14.09.2026).

## Problem

W Kontraktach stawki były w zł/h, zł/MD albo zł/mc, więc eksport do Excela
mieszał jednostki. Przyczyna leżała w synchronizacji kontraktu z zamówieniami:
kontrakt przejmował jednostkę najnowszego zamówienia. Dlatego każde zamówienie
w MD przestawiało kontrakt na MD.

## Decyzje

- Przeliczamy wyłącznie kontrakty w MD (÷ 8). Kontrakty godzinowe i ryczałtowe
  (zł/mc) zostają bez zmian (decyzja Artura, 14.09.2026).
- Kwoty miesięczne muszą zostać takie same. Przeliczony kontrakt dostaje
  176 godzin w miesiącu (22 MD × 8 h). Bez tego MRR i marża spadłyby o 9%,
  bo godziny liczyły się domyślnie × 160.
- Zamówienia w module Klienci zostają nietknięte, zarówno co do jednostki, jak
  i wartości. Koszt wraca do zamówienia × 8, więc kwota się nie zmienia.

## Zmiany

| Obszar | Plik | Co |
|---|---|---|
| Schemat | `backend/alembic/versions/0309_contract_hourly_rates.py` + lustro w `entrypoint.sh` | Stawki kontraktu, 3 harmonogramy, stawka ramowa, widełki i marża poszerzone do `NUMERIC(16,6)`. Trigger walut jest zdejmowany i zakładany ponownie w tej samej transakcji. Entrypoint zmienia typ tylko wtedy, gdy kolumna się różni (dotąd przy każdym starcie zawężał stawkę ramową do `(12,2)`). |
| Synchronizacja | `backend/app/services/contract_order_sync.py` | `contract_unit_for_order` (MD → godziny). Konwersja z 6 miejscami po przecinku. Zamówienie w MD ustawia 176 h/mc. `apply_contract_hourly_policy`. |
| Konwersja | `backend/app/services/order_rate_snapshots.py` | Parametr `scale` i `CONTRACT_RATE_SCALE` (zamówienia zostają przy 0,001). |
| API | `backend/app/api/contracts.py` | POST przelicza kontrakt podany w MD. PATCH i aneks przejścia NA MD zwracają 422 `contract_rates_are_hourly`. Zapis kontraktu, który wciąż jest w MD, przelicza go w całości. |
| API | `backend/app/api/client_orders.py`, `backend/app/services/order_mail_apply.py` | Kontrakt z formularza zamówienia i szkic z maila są zapisywane w zł/h. |
| Korekta danych | `backend/app/services/contract_hourly_rate_repair.py` + blok w `entrypoint.sh` | Szczegóły w następnej sekcji. |
| Frontend | `contracts/new`, `contracts/[id]`, `AddProjectDialog` | Brak opcji „Dziennie”. Formularz nowego kontraktu domyślnie „Godzinowo”. |
| Dokumentacja | `CLAUDE.md`, instrukcja zamówień w Pomocy (przestemplowana) | Opis nowej reguły. |

## Jednorazowa korekta danych (marker `0309_contract_hourly_rates`)

- Zakres: każdy kontrakt `daily`.
- Przelicza stawki, harmonogramy, stawkę ramową i widełki ÷ 8 i ustawia
  176 h/mc.
- Przed zapisem sprawdza odwrotność (× 8 == dawna kwota). Kontrakt, którego
  nie da się przeliczyć dokładnie, zostaje w MD z powodem `inexact_conversion`.
- Po przeliczeniu miesięczny ekwiwalent każdej kwoty musi być równy temu
  sprzed korekty. Różnica = wyjątek i rollback.
- Suma kontrolna wszystkich `client_orders` (stawki, jednostka, MD, status,
  `updated_at`) przed i po musi być identyczna. Różnica = rollback.
- Czeka na poszerzone kolumny. Bez nich nie zapisuje markera i ponawia przy
  następnym starcie.
- Paragon zawiera tylko liczniki, ID i powody. Stare i nowe kwoty są pod
  `repair_details_0309_contract_hourly_rates`.

## Poprawki po przeglądzie adwersarialnym

- **Godziny miesiąca przy przeliczeniu kontrakt ↔ zamówienie należą do kontraktu**
  (`order_rate_snapshots.contract_rate_in_unit` / `order_rate_in_contract_unit`).
  Bez tego przeliczony kontrakt (125 zł/h × 176 h) z zamówieniem miesięcznym
  dostałby nocą koszt 20 000 zamiast 22 000, a krok przychodu 137,5 zł/h.
- **Zamówienia dziedziczące z kontraktu zostają w MD**
  (`order_unit_for_contract`: kontrakt godzinowy 176 h/mc → zamówienie w MD).
  Dotyczy szkiców przy dodaniu projektu i po podpisie, importu Nordea,
  uzupełniania szkiców bez stawek, przedłużenia bez jednostki i zamówienia
  z maila bez odczytanej jednostki.
- **Bramka maila (±40%)** porównuje stawkę kontraktu w jednostce zamówień, więc
  kontrola nie wyłącza się dla dokumentów w MD.
- **Marża zamówienia bez własnej stawki** i prefill przedłużenia biorą stawkę
  kontraktu przeliczoną na jednostkę zamówienia.
- **Kontrakt już godzinowy zachowuje swoje godziny** (ticket 1a). 176 h/mc
  dostaje wyłącznie przy przeliczeniu z MD albo przy pierwszym zamówieniu
  w MD, gdy nie ma jeszcze przychodu. Kontrakt 176-godzinny, którego najnowsze
  zamówienie jest godzinowe, przejmuje godziny tego zamówienia.
- **PATCH zmieniający jednostkę kontraktu w MD na inną zwraca 422** — samo
  przestawienie etykiety zostawiłoby kroki harmonogramu w MD.
- **Korekta 0309** działa w REPEATABLE READ (suma kontrolna na jednej migawce).
  Po markerze łapie też kontrakty zapisane w MD przez stary kontener w trakcie
  deployu (`late_converted_contract_ids`).

## Znane ograniczenia

- **Scalanie duplikatów kontraktów** (`contract_merge`) blokuje się, gdy dwa
  kontrakty godzinowe mają różną liczbę godzin w miesiącu (160 vs 176).
  To prawdziwa różnica miesięcznego ekwiwalentu, więc blokada zostaje jako
  decyzja do podjęcia w narzędziu scalania.
- **Kontrakt godzinowy z własnym przychodem i zamówieniem w MD** liczy
  miesięcznie swoje godziny (np. 160), a zamówienie × 22 MD. Taki kontrakt
  zostaje bez zmian zgodnie z ticketem.
- **Rozpoznanie „kontrakt z MD” opiera się na 176 h/mc.** Kontrakt, któremu
  ktoś ręcznie ustawił 176 h, przekaże dziedziczącym zamówieniom jednostkę MD.
- **Kontrakt ryczałtowy z zamówieniem w MD** przechodzi na zł/h (÷ 176) przy
  najbliższym zapisie zamówienia, tak jak wcześniej przechodził na MD.
- **Szkic zamówienia bez stawek** dziedziczy stawki z kontraktu z precyzją
  zamówienia (3 miejsca po przecinku).

## Weryfikacja

- Nowe testy: `backend/tests/test_contract_hourly_rates.py`. Dostosowane:
  `backend/tests/test_contract_order_sync.py`.
- Vitest: `AddProjectDialog.test.tsx`.
- Migracja sprawdzona w górę, w dół i ponownie w górę na Postgres 16. Blok
  entrypointu sprawdzony na wąskich kolumnach (dwa przebiegi, trigger zostaje).
