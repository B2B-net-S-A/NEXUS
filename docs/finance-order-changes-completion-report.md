# Finanse → Zmiany w zamówieniach — raport ukończenia

Ticket: nowa zakładka „Zmiany w zamówieniach" w module Finanse z podzakładkami
Zmiany · Wejścia · Zejścia · Braki, eksportem do Excela, licznikami i
powiadomieniem Delivery Leada o brakach.

## Decyzje (Artur, 14.09.2026)

| Pytanie | Decyzja |
|---|---|
| Miesiąc zmiany stawki / daty końca | miesiąc **wprowadzenia** zmiany |
| Przedłużenie tej samej osoby w Wejściach | ~~pokazywane, oznaczone „Kontynuacja po zam. X"~~ — **zmienione 16.09.2026**, patrz niżej |
| Co NIE jest Brakiem | wypowiedziana umowa, szkic następnego zamówienia, decyzja offboardingu MD / „zostaw jako historię" (dodatkowo: zamiana kontraktora) |
| Powiadomienie DL | alert w sekcji DL (powtórka co 7 dni) + dzwonek |

## Co powstało

**Backend**
- Migracja `0308_finance_order_changes` (+ lustro w `entrypoint.sh`):
  tabele `order_change_events`, `order_gaps` (bez FK), typ alertu DL
  `order_missing_successor`, wartość enuma `notificationtype`.
- `services/order_change_audit.py` — dziennik starej → nowej wartości stawki
  kosztowej, przychodowej i daty końca (jedna zmiana na transakcję).
- `services/order_facts.py` — wspólny odczyt: okres efektywny, reguła
  następcy, świadome zakończenia.
- `services/order_gaps.py` + `tasks/order_gaps.py` — wykrywanie braków
  (00:30 Warszawa + start), zamykanie przy zapisie zamówienia i z maila,
  alert DL + dzwonek, reguła powtórki w `dl_alerts_scanner`.
- `services/finance_order_changes.py` — cztery listy + eksport XLSX (4 arkusze).
- Endpointy: `GET /api/finance/order-changes?year&month`,
  `GET /api/finance/order-changes/export?year&month` (sekcja Finance).
- Env: `ORDER_GAPS_ENABLED`, `ORDER_GAP_TRACKING_START` (2026-08-01),
  `ORDER_GAP_LOOKBACK_DAYS` (45), `ORDER_GAPS_RUN_HOUR_LOCAL`/`MINUTE_LOCAL`.

**Frontend**
- `/finance?view=order-changes` (`&sub=entries|exits|gaps`, `&month=RRRR-MM`).
- `components/finance/OrderChangesTab.tsx`, `OrderChangesPanel.tsx`,
  `lib/finance-order-changes.ts`; harness `/preview/finance-order-changes`.
- `DlAlertsSection` znowu zamontowana na pulpicie Delivery Leada (od #1304
  nie była wyświetlana nigdzie).
- Dzwonek: ikona dla `order_missing_successor`.

**Dokumentacja**: sekcja w `CLAUDE.md`, akapit o Brakach w instrukcji zamówień
dla DL (przestemplowana).

## Weryfikacja
- pytest: `test_finance_order_changes.py` (19 testów: dziennik zmian, filtr
  szumu, stan pośredni po synchronizacji, braki i wyłączenia, MD po dacie
  końca, kontrakt bez osoby, okno wsteczne, zamknięcie przez API, widok
  miesiąca, eksport, bramka sekcji) + zestawy zamówień/kontraktów/alertów DL.
- Migracja: upgrade → downgrade do 0307 → upgrade.
- vitest: formatowanie, panel z licznikami, strona Finansów, pulpit DL,
  middleware; `tsc --noEmit` i ESLint czyste.
- Wizualnie: harness w przeglądarce (desktop i 375 px).
- Przegląd adwersarialny: 2 błędy wysokie i 5 średnich — naprawione
  (linie MD po dacie końca, stan pośredni, zamykanie z maila, savepoint na
  brak, zawężenie w SQL, okno wsteczne, kontrakt bez osoby, kill-switch
  przypomnień, dane widoczne przy nieudanym odświeżeniu w tle).

## Znane ograniczenia
- Historia zmian stawek i dat zaczyna się od wdrożenia (starej wartości nigdy
  nie zapisywano) — widok mówi to wprost.
- „Dodatkowy projekt" rozpoznaje równoległe zamówienie tylko u INNEGO klienta.
- Linia MD kończona wyczerpaniem budżetu po więcej niż 45 dniach od daty końca
  nie tworzy braku (okno wsteczne).
- Pierwszy przebieg tworzy braki za okres od 01.08.2026; alerty w sekcji DL
  powstają dla wszystkich otwartych, dzwonek tylko dla świeżych.

---

# Korekta kwalifikacji zakładek + filtry i eksport per zakładka (16.09.2026)

Ticket: „Wejścia" zbierały każdą osobę zaczynającą zamówienie w miesiącu, także
przedłużających i pracujących równolegle — Finanse czytają tę listę jako „kto
doszedł", więc kłamała (Adam Matecki, Aleksandra Likas, Piotr Żukowski
figurowali jako wejścia, choć zmienili tylko numer zamówienia). „Zejścia"
pokazywały wiersze z werdyktem „Kontynuacja", czyli osoby, które NIE schodzą.
Żadna zakładka nie miała wyszukiwania ani filtrów, a eksport zawsze zrzucał
cztery arkusze.

## Decyzje (Artur, 16.09.2026)

| Pytanie | Decyzja |
|---|---|
| Co znaczy „zmiana klienta" | konsultant przechodzi do INNEGO klienta (pola `client_id` zamówienia nie da się edytować — `ClientOrderUpdate` go nie ma) |
| Co zostaje w Wejściach | wyłącznie osoby bez żadnego innego niezanulowanego zamówienia u jakiegokolwiek klienta |
| Gdzie liczyć filtry | na serwerze — jedno źródło prawdy dla ekranu i eksportu |

## Nowa kwalifikacja

| Zakładka | Zawiera |
|---|---|
| **Wejścia** | osoba zaczynająca z nami współpracę po raz pierwszy („Nowy konsultant", z ewentualnym „Szkic") |
| **Zejścia** | osoba, która od kolejnego miesiąca nie świadczy już usług — niezależnie od przyczyny |
| **Zmiany** | każda zmiana stawki kosztowej i przychodowej (bez progu), zmiana daty końca oraz nowe zamówienia osób już współpracujących: kontynuacja, zmiana klienta, dodatkowy projekt |
| **Braki** | bez zmian |

`_classify_entries` rozstrzyga pierwszym trafieniem: `additional_project` →
`order_continuation` (`previous_of`, 31 dni, ten sam klient) → `client_change`
albo `order_continuation` po kliencie ostatniego wcześniejszego zamówienia →
`new`. Zejście liczy się z faktów, nie z napisu werdyktu
(`works_until_md_exhausted or successor is not None` → wiersz odpada), więc
odpada też „wypowiedzenie + żywy następca".

**Bez migracji** — trzy nowe rodzaje wierszy Zmian są syntetyczne, liczone przy
odczycie; CHECK na `order_change_events.field` i dziennik zostają nietknięte.

## Filtry i eksport

- `GET /api/finance/order-changes?…&q&client_id&date_from&date_to` — jedna
  funkcja `apply_filters` zawęża cztery listy i przelicza liczniki.
- `GET /api/finance/order-changes/export?…&tab=` — ta sama funkcja; `tab`
  pominięty daje cały audyt (zgodność wstecz).
- Data znaczy w każdej zakładce co innego (zmiana / start / koniec / dzień
  wykrycia braku) — etykieta pola zmienia się z zakładką.
- `OrderChangesPanel` nie odpytuje API sam: picker klienta wchodzi slotem, bo
  ten sam komponent renderuje publiczny harness (zero zapytań).

## Weryfikacja
- pytest `test_finance_order_changes.py` — 30 testów (w tym 9 nowych:
  kwalifikacja wejść, dwa zamówienia tego samego dnia, wypowiedzenie
  z następcą i bez, filtry per zakładka, eksport z filtrami, odwrócony zakres).
  Mutacje (zdjęcie filtru kontynuacji, zdjęcie rozstrzygnięcia tego samego
  dnia) wywracają testy — nie są puste.
- vitest: 8 testów panelu, 9 formatowania, strona Finansów, middleware.
- `tsc --noEmit` i ESLint czyste (182 ostrzeżenia = dotychczasowy dług, limit 300).
- Wizualnie: harness `/preview/finance-order-changes` w przeglądarce — Matecki
  jako „Kontynuacja zamówienia", Żukowski jako „Zmiana klienta", w Wejściach
  wyłącznie Grono i Kalbarczyk z plakietką „Nowy konsultant"; chipy filtrów,
  „Wyczyść wszystko", brak błędów w konsoli.

## Znane ograniczenia
- Osoba wracająca po dłuższej przerwie nie jest wejściem — trafia do Zmian jako
  kontynuacja (albo zmiana klienta) z numerem ostatniego zamówienia.
- Szkic u innego klienta nie liczy się jako trwająca współpraca (lustro reguły
  „dodatkowego projektu"), ale JEST poprawnym poprzednikiem w `previous_of`
  u tego samego klienta — ta reguła została świadomie nietknięta.
- Filtry są wspólne dla czterech zakładek (przełączenie zakładki ich nie
  czyści); eksport bierze zakładkę aktywną.
