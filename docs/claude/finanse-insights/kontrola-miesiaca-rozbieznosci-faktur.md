# Kontrola miesiąca: rozbieżności faktur klient ↔ konsultant (0784, 25.11.2026)
<!-- indeks: month_check, month_check_cases, „Rozbieżności” w Przebiegu miesiąca (`mcTab=diff`), GET/POST /api/finance/settlements/month-check, hours_mismatch, cost_without_sale, sale_without_cost, over_working_days, ±1 miesiąc, 15. dzień, karta DL month_check_data, mail poniedziałkowy month_check_report, app_settings month_check_mail / month_check_last_run, podsumowanie 12. dnia -->

Decyzja Artura z 25.11.2026 po audycie fakturowania IV–X: 16 spraw na setki
tysięcy złotych (inne godziny u klienta i u konsultanta, konsultant
zafakturował, a klient nie, i odwrotnie), których nikt nie zauważył. NEXUS
łapie je sam co noc; rutyna Claude'a 12. dnia zostaje tylko jako zapas.
Kod: `backend/app/services/month_check/` (reguła w `rules.py` bez bazy,
wejście w `collect.py`, zapis i decyzje w `service.py`, maile w `mail.py`,
karta DL w `cards.py`), pętla `app/tasks/month_check.py`.

## Co sprawdza

Osoba × miesiąc, trzy ostatnie zakończone miesiące, raz na dobę po 3:00.

- **`hours_mismatch`** — godziny z faktury do klienta (MD × 8) × stawka
  kosztowa kontraktu ≠ netto faktury konsultanta o więcej niż pół dnia
  (4 h × stawka). Kwota sprawy = różnica (plus: konsultant zafakturował więcej).
- **`cost_without_sale`** — konsultant zafakturował, a klient po 15. dniu
  następnego miesiąca nie ma faktury z tą osobą. Kwota = netto konsultanta.
- **`sale_without_cost`** — klient zafakturowany, a faktury konsultanta po
  15. dniu nie ma. Tylko osoby, które mają w KSeF jakąkolwiek fakturę
  (bez niej to papier albo nieznany NIP — licznik `no_ksef_invoices`).
  Kwota = godziny × stawka kosztowa.
- **`over_working_days`** — więcej godzin na fakturach do klienta niż dni
  roboczych × 8 (święta z `hr.calendar`), **tylko gdy faktura konsultanta
  z tego miesiąca nie potwierdza tych godzin** (decyzja Artura 25.11:
  nadgodziny Nordei zafakturowane po obu stronach to nie błąd; licznik
  `overtime_confirmed`). Klucz sprawy ma też klienta.

**Okno ±1 miesiąca.** Faktura konsultanta nie ma okresu: od 25. dnia bieżący
miesiąc, do 10. poprzedni, pomiędzy ten, który lepiej pasuje do godzin
u klienta; faktura przypięta przez rozliczenia (`client_contractor_invoices`)
ma miesiąc z rozliczenia. Korekta idzie do miesiąca faktury o przeciwnej
kwocie, bez takiej do ostatniej wcześniejszej. Rozbieżność, którą znosi
przesunięcie o miesiąc (dwa miesiące razem się zgadzają), nie jest sprawą.

## Kto jest na pozycji faktury

- Numer osoby u klienta (Nordea `ID: M…`, `client_external_ids`
  potwierdzone), potem pełne imię i nazwisko osoby z kontraktem u klienta
  trwającym w miesiącu (`contract_rate_history.collect.match_item`), potem
  osoba po znaczniku „Contractor”/„Konsultant” ze skrótem podwójnego nazwiska
  albo literówką (`unknown_refs.same_person`). „NazwiskoID: M…” sklejone
  rozdzielamy przed dopasowaniem.
- Pozycja bez nikogo, a faktura przypięta do zamówień jednej osoby — ta osoba
  (BNP: numer zamówienia, „Praca kontraktora: 414097”).
- Faktura w „Nieznani nabywcy”: pozycja z pełnym imieniem i nazwiskiem osoby
  z **jednym** trwającym kontraktem idzie do klienta tego kontraktu (PFRON
  na kopii 25.11: wszystkie faktury czekały na nabywcę). Gdy osoba ma kilka
  kontraktów, jej sprawa „koszt bez sprzedaży” czeka (`sale_waits_for_buyer`).
- Faktura konsultanta: NIP sprzedawcy = `candidates.nip` (uzupełnia go
  `contractor_nip`, #4002), bez niego pełne imię i nazwisko w nazwie
  sprzedawcy, jedna osoba z kontraktem w NEXUSIE. Inkubator bez osoby w nazwie
  nie wiąże nikogo.

## Pominięcia (liczone osobno, widać je na ekranie)

`client_without_names` (faktura zbiorcza `cl.collective_invoice` albo klient,
którego faktury w miesiącu nie nazywają nikogo), `parallel_contracts` (dwa
kontrakty w miesiącu — kosztu nie da się podzielić), `no_ksef_invoices`,
`not_comparable` (stawka ryczałtowa, zmiana stawki w miesiącu, inna waluta
faktury niż stawki), `outside_contracts` (faktura konsultanta po kontrakcie
zakończonym dawniej niż 62 dni), `waiting_for_deadline` (przed 16. dniem).

## Stany i decyzje Finansów

`new` → `to_correct` („Do korekty”) albo `explained` („Wyjaśnione”, powód
obowiązkowy, CHECK w bazie). Sprawa znaleziona ponownie zostaje w swoim
stanie, z bieżącą kwotą i fakturami. Sprawa, której przebieg nie znajduje,
zamyka się sama (`closed`, bez autora) — tylko w miesiącu i rodzaju, które
przebieg sprawdzał. Zamknięta, która wraca, jest znowu `new` (i trafia do
maila). „Cofnij” przy wyjaśnionej wraca do `new`.

## Ekran, karta DL, maile

- **Finanse → Przebieg miesiąca → „Rozbieżności”** (`mcTab=diff`, makieta
  przyjęta przez Artura 25.11): podsumowanie (zgodne osobo-miesiące, sprawy
  i kwota, otwarte, wyjaśnione, pominięcia), filtr stanów, wiersze z kwotą,
  numerami faktur i akcjami. Ta sama bramka co Przebieg (`FinanceModuleUser`
  + moduł rozliczeń); kwoty i netto faktur tylko przy `has_financial_access`.
- **Karta DL** `month_check_data` — tylko sprawy danych (`cost_without_sale`
  i `sale_without_cost` z `no_contract`/`no_order`), **bez kwot i numerów
  faktur**. Zamyka się sama, gdy sprawa zniknie albo Finanse ją wyjaśnią.
- **Mail w poniedziałek od 8:00** (`month_check_report`, obowiązkowy): nowe
  otwarte sprawy z 7 dni, z kwotą, numerami faktur i linkiem. Pusty tydzień
  nie wychodzi. **12. dnia od 8:00** — podsumowanie poprzedniego miesiąca.
- **Adresaci: `app_settings['month_check_mail']`.** Domyślnie (`to_finance`
  brak albo `false`) tygodniowy mail idzie wyłącznie do Artura (próba);
  podsumowanie 12. dnia nie wychodzi. Do Finansów (rola `finance`, główna
  albo dodatkowa) dopiero po „wysyłaj” Artura w sesji:
  `INSERT … ('month_check_mail', '{"to_finance": true}')` przez zwykłą ścieżkę
  zmian danych na produkcji. Nie przełączaj bez jego słowa.
- Liczniki ostatniego przebiegu per miesiąc: `app_settings['month_check_last_run']`.

## Pomiar na kopii produkcji z 25.11.2026 (staging, transakcja cofnięta)

NIP-y z `contractor_nip.backfill` policzone w tej samej transakcji (na
produkcji wejdą po wdrożeniu #4002). Osobo-miesiące / zgodne / sprawy
(godziny, koszt bez sprzedaży, sprzedaż bez kosztu, ponad dni robocze):

| Miesiąc | Osobo-mies. | Zgodne | Godziny | Koszt bez sprz. | Sprz. bez kosztu | Ponad dni |
|---|---|---|---|---|---|---|
| VII | 423 | 351 | 9 | 5 | 2 | 1 |
| VIII | 443 | 373 | 5 | 4 | 2 | 3 |
| IX | 461 | 388 | 8 | 4 | 1 | 4 |
| X | 476 | 403 | 9 | 5 | 2 | 4 |

Wszystkie 16 spraw audytu wychodzą (IV–VI z przebiegu na tamtych miesiącach);
sprawa 16 (opis pozycji Nordei) to nadgodziny potwierdzone przez konsultanta
i przy przyjętym wariancie sprawy nie daje. Przebieg trwa ok. 13 s.

## Testy

`tests/test_month_check_rules.py` (reguła, miesiąc faktury, dopasowanie
pozycji), `tests/test_month_check_db.py` (przebieg, stany, decyzje, karta DL),
`tests/test_month_check_mail.py` (terminy, treść, pętla raz na dobę), front
`month-close/__tests__/month-check-panel.test.tsx`.
