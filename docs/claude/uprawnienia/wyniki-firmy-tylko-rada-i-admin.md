# Zbiorcze wyniki firmy: Rada, admin i osoba z nadaniem (decyzja Artura 02.11.2026)
<!-- indeks: uprawnienie company_results „Wyniki firmy”, BoardReader i CompanyResultsUser zamiast Modułu Finanse; mail board_monthly_report tylko Rada i admin; Finanse pracują na pojedynczych rekordach -->

2 listopada „Podsumowanie Rady” z przychodem i marżą firmy dostało 11 osób,
w tym 5 z działu Finanse. Nie była to awaria: odbiorców i ekrany wyznaczał
„Moduł Finanse”, który Finanse mają domyślnie. Artur: takie podsumowania mają
widzieć Rada i admini. Finanse pracują na pojedynczych rekordach. Kwota przy
konkretnym kontrakcie jest w porządku, a jedno kliknięcie pokazujące wszystkie
marże i podsumowanie całości już nie.
Makiety i audyt: https://claude.ai/artifact/P9J4Zgecx7B9D9S9VQvQoN.

## Reguła

- **„Wyniki firmy: podsumowania przychodu i marży”** (`company_results`,
  grupa „Pieniądze”, 0629) to osobne uprawnienie. Bez domyślnych posiadaczy
  poza adminem i bez zależności, więc nadanie nie otwiera przy okazji Delivery.
  Admin może nadać je jednej osobie w „Osoby i role”. Na start nikt z Finansów
  go nie ma.
- **Rada czyta z tytułu roli** (`reads_board_money`, `BoardReader`). Rada nie
  przyjmuje nadań i nie dostaje tras modułu Finanse.
- **Mail `board_monthly_report`:** Rada i osoby z imiennym nadaniem
  `users.receives_board_report` (0629, „Osoby i role” → edycja osoby; Artur
  zaznacza je sobie). Nazwiska nie ma w kodzie, bo repo jest publiczne. Sama rola
  admin ani „Wyniki firmy” maila nie otwierają: Artur wskazał odbiorców wprost.
  Ekrany Firmy adminowie widzą dalej, do zmiany ich roli.
  `board_placement_alert` idzie tylko do Rady.
- **Moduł Finanse** zostaje narzędziem pracy: faktury, zgody, zmiany
  w zamówieniach, Wyniki miesięczne. Nie zdejmuj `VIEW_FINANCE` z roli Finanse:
  otwiera ponad 40 powierzchni z pojedynczymi rekordami. Trasy zbiorcze mają
  własną bramkę.

## Co jest za uprawnieniem

- `BoardReader` (uprawnienie albo Rada): Insights → Firma, `/api/insights/board`,
  `/board/flows`, `/clients/ranking`, raport Ranking klientów.
- `CompanyResultsUser` (uprawnienie, bez Rady, która ma te liczby w Firmie):
  Analityka kontraktów, Przegląd klientów, `/api/analytics/v1/finance/*`,
  `/executive/board`, `/api/dashboard/v2/finance`, `/api/reports/sales`,
  `/api/invoices/dso`. Kwoty przetargów w `analytics_v1` to samo uprawnienie.
- **Rok do roku:** „Moduł Finanse” wchodzi, ale dostaje tabelę bez kwot, jak
  Head of Recruitment (`BoardTrendReader` + `reads_board_money`).
- **Kreator metryk i pulpit** (`custom_metrics/engine`): źródło „finance” liczy
  całą firmę tylko z uprawnieniem. Delivery Lead liczy swój portfel jak dotąd.
  Inny posiadacz „Stawki i kwoty: podgląd” dostaje odmowę, bo dawałby sumę
  firmy. Finanse nie mają kafla `margin_monthly` w układzie domyślnym.
- **Jarvis** woła API tokenem pytającego, więc zamknięcie tras zamyka też czat.

## Zostaje przy rekordzie

Karta klienta, kontraktu i zamówienia, zakładka Zmiany w zamówieniach, Płace,
wydatki ze zgodą oraz kwoty przy pojedynczej parze (mail i dzwonek o zmianie
stawki: decyzja Artura 02.11.2026, bez zmian).

Lista kontraktów, eksporty, kafle sum w Wynikach miesięcznych i Fakturach oraz
`/api/my-clients` to następny PR tego programu.

**Nie da się ukryć ekranem:** dział sam wgrywa arkusz Wyników z marżą każdej
osoby, więc sumę ma we własnym pliku.

## Nowy raport albo kafel

Suma kwot całej firmy bierze bramkę `CompanyResultsUser` albo `BoardReader`,
nigdy `finance_module` ani `VIEW_FINANCE`. Zmiana dostępu = diff wzorca
`tests/data/authz_golden/`, a reguła w środku handlera potrzebuje własnego testu.
