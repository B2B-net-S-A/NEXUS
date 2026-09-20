# Finanse → Zmiany w zamówieniach — raport ukończenia

Ticket: nowa zakładka „Zmiany w zamówieniach" w module Finanse z podzakładkami
Zmiany · Wejścia · Zejścia · Braki, eksportem do Excela, licznikami i
powiadomieniem Delivery Leada o brakach.

> **Korekta 20.09.2026** — piąta podzakładka „Kończące się zamówienia" oraz
> zmiana kwalifikacji Wejść i Zejść. Patrz sekcja na końcu.

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

---

# Korekta 20.09.2026 — Wejścia, Zejścia i „Kończące się zamówienia"

## Zgłoszenie

Dwie podzakładki odpowiadały na inne pytanie, niż mówi ich nazwa:

* **Wejścia** obiecują „kto rozpoczął z nami współpracę", a pokazywały „czyje
  pierwsze ZAMÓWIENIE trafiło do NEXUSA w tym miesiącu".
* **Zejścia** obiecują „kto kończy współpracę", a pokazywały „czyje zamówienie
  kończy się w tym miesiącu i nie ma jeszcze następnego".

Zmierzone na produkcji (read-only SQL, wrzesień 2026):

| | przed | po |
|---|---|---|
| Wejścia | **39** wierszy, z tego 11 kontynuacji | **28** faktycznie nowych osób |
| Zejścia | do **87** wierszy z żywą umową + ~13 z zakończoną | tylko zapisane zakończenia |

## Przyczyna Wejść: rejestr zamówień jest młodszy niż współpraca

`_classify_entries` czytał wyłącznie wiersze `client_orders`. Przypadek ze
zgłoszenia: umowa `active`, bezterminowa, start w grudniu poprzedniego roku —
a pierwszy wiersz zamówienia startuje 1 września. Klasyfikator nie miał z czego
wywnioskować, że współpraca trwa od grudnia. Z 63 zamówień startujących we
wrześniu **38 miało umowę starszą niż własne zamówienie**.

Poprawka: `_classify_by_engagement` czyta `contracts` (bez `draft` i `void`)
i dokłada szczebel tuż przed `new`, lustrzany do drabinki z zamówień
(ten klient → równoległy inny klient → zakończona współpraca gdzie indziej).

**Próg to pierwszy dzień miesiąca, nie dzień startu zamówienia** — osobie
faktycznie nowej zakłada się umowę razem z pierwszym zamówieniem, często z datą
o kilka dni wcześniejszą; próg „ściśle przed startem" opróżniłby zakładkę.

Kontynuacja wywnioskowana z umowy nie ma poprzedniego numeru zamówienia, więc
`OrderChangeItem` niesie `engagement_since`, a obie warstwy renderują
„współpraca od DD.MM.RRRR" zamiast „—" (puste czyta się jak utrata danych).

## Przyczyna Zejść: trzy różne werdykty w jednej zakładce

`_exits` nadawał trzy werdykty, a tylko jeden mówił cokolwiek o współpracy.
Po korekcie `_exits` zwraca **dwie listy z jednego przebiegu**:

* `exits` — `ended_intent`, czyli zapisany koniec współpracy. **Decyzja Artura
  20.09.2026: wszystkie pięć rodzajów intencji zostaje w Zejściach**
  (wypowiedzenie/koniec umowy, zamiana kontraktora, decyzja DL po offboardingu
  MD, usunięcie z zamówienia, „zostaw jako historia") — wspólnym mianownikiem
  jest świadomy zapis człowieka.
* `ending_orders` — `ending_pending` i `no_successor`: zamówienie kończy się
  (albo skończyło) bez kolejnego, a współpraca trwa.

Bramka `works_until_md_exhausted or successor is not None` zostaje PRZED
drabinką werdyktów i zakres następcy zostaje per (osoba, klient).

## Piąta zakładka

`?sub=ending` / `?tab=ending`, po Zejściach, przed Brakami. Ten sam
`OrderExitItem`, ten sam render, ten sam komplet funkcji: szukajka, filtr
klienta, zakres dat („Data końca zamówienia"), eksport XLSX. Arkusz nazywa się
„Kończące się zam. (n)" — pełna nazwa nie mieści się w limicie 31 znaków Excela.

**Bez migracji** — zmiana wyłącznie w regułach odczytu.

## Weryfikacja korekty
- pytest `test_finance_order_changes.py` — 7 nowych testów: umowa starsza niż
  pierwsze zamówienie, próg miesięczny, szkic umowy jako niedowód, zakończona
  umowa u innego klienta, kończące się zamówienie poza Zejściami, żywy następca
  poza obiema listami, filtry + eksport nowej zakładki.
- vitest: pięć zakładek z licznikami, etykieta filtra daty, rozdział Zejść od
  Kończących się zamówień, „współpraca od …" zamiast „—".

## Znane ograniczenia korekty
- Osoba, której umowa zaczęła się w poprzednim miesiącu, a pierwsze zamówienie
  powstało w tym, nie pokaże się w Wejściach ŻADNEGO miesiąca (w swoim własnym
  nie było jeszcze zamówienia). Trafia do Zmian jako kontynuacja — tam, gdzie
  Finanse i tak szukają numeru zamówienia do faktury.
- Zejścia są nadal wyprowadzane z dat końca ZAMÓWIEŃ. Umowa zakończona
  w miesiącu, której zamówienie kończy się w innym, do zakładki nie trafi;
  `/terminate` dociąga daty zamówień do końca umowy, więc w praktyce pokrycie
  jest pełne (wrzesień 2026: 11 zakończonych umów vs 13 zamówień z zakończoną
  umową). Zmiana źródła danych zakładki to osobny ticket.
- „Kończące się zamówienia" i „Braki" częściowo się pokrywają: Braki to rejestr
  wykrytych luk z datą wykrycia i opóźnieniem (od `ORDER_GAP_TRACKING_START`),
  nowa zakładka to widok miesięczny liczony z zamówień.
