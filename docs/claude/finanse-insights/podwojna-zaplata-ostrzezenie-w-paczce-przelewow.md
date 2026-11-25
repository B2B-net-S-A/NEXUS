# „Możliwa podwójna zapłata” w paczce przelewów (25.11.2026)

<!-- indeks: double_payment, podwójna zapłata, korekta na plus, kwota korekty KSeF różnica, ten sam numer faktury, druga faktura w miesiącu, finance_ledger/double_pay.py -->

Po audycie fakturowania IV–X 2026 (25.11.2026): korekta kontraktora na plus
równa całej wcześniejszej fakturze (i podobne u czterech innych dostawców) oraz
dwie faktury jednej osoby na tę samą kwotę w jednym miesiącu. Każdy dokument
z osobna był poprawny, więc paczka zapłaciłaby tę samą usługę drugi raz.
Kod: `services/finance_ledger/double_pay.py`, wołany z `payments.plan`
(Finanse → Przelewy → plan paczki). Bez migracji.

## Kwota korekty w KSeF to różnica

- Netto, VAT i brutto korekty (`Kor`) w metadanych KSeF i w `P_13_*` XML-a
  to **różnica** „stan po” minus „stan przed”, nie stan po korekcie.
  Sprawdzone na XML-u korekty w `client_contractor_invoices.details`
  (kopia produkcji 25.11.2026): pozycja „przed” (`before_correction`) i „po”
  różnią się ceną jednostkową, a `net_amount` korekty to dokładnie różnica
  netto obu pozycji (np. przed 100, po 103 → korekta 3).
- Dlatego korekta na plus równa całej fakturze dokłada drugą całą fakturę.
  Łańcuch korekt faktury kontraktora (`invoice_chain`, `Payable` w
  `payments.py`) już sumuje brutto pierwotnej i korekt — ostrzeżenie mówi,
  że ta suma może zawierać usługę dwa razy.

## Trzy sytuacje (ostrzeżenie do odhaczenia, nie blokada)

Kod `double_payment` w `acks` pozycji planu, zdanie w `labels` (numer i data
drugiej faktury). Paczka z taką fakturą bez odhaczenia = 409 `needs_ack`,
jak biała lista i MPP. Bywają uczciwe (dwie osoby jednej firmy z tą samą
stawką, dopłata za cały miesiąc), dlatego nie blokujemy.

| Sytuacja | Warunek | Gdzie |
|---|---|---|
| Korekta = cała wcześniejsza faktura | korekta z netto > 0 równym netto wcześniejszej (albo z tego samego dnia) faktury `Vat` tego dostawcy, ta sama waluta | każdy dziennik |
| Druga faktura w miesiącu | druga faktura `Vat` tego dostawcy na to samo netto i walutę za ten sam miesiąc usługi | tylko „Kontraktorzy” |
| Ten sam numer dwa razy | ten sam numer (bez spacji, bez wielkości liter) od tego samego dostawcy | każdy dziennik |

- **Miesiąc usługi**: z `period_month` faktury przypiętej do kontraktu; gdy
  któryś dokument go nie ma (dokument wydatku z `approval_documents`), liczy
  się wystawienie w odstępie krótszym niż 20 dni (`SAME_MONTH_DAYS`).
  Miesiąc kalendarzowy daty wystawienia mylił faktury za kolejne miesiące
  (1. dnia za poprzedni, 30. za bieżący).
- **Druga faktura tylko u kontraktorów**: w zakupach i biurze ta sama kwota
  w miesiącu to raty i abonamenty (kopia 25.11: ok. 190 faktur od 10 dostawców).
- **Ten sam numer**: korekta na zero albo na minus z numerem faktury pierwotnej
  (pięć takich par na kopii) nie dokłada zapłaty i nie ostrzega.
- Druga faktura **odrzucona** w kolejce albo z flagą **„Duplikat”** się nie
  liczy: Finanse już ją rozstrzygnęły. Zapłacona — liczy się (o to chodzi).
- Faktura pierwotna z korektami: sprawdzamy też jej korekty z łańcucha, bo
  płacąc ją, płacimy sumę. Korekta rozliczana na pierwotnej ma własną blokadę
  („rozliczamy na fakturze pierwotnej”) i ostrzeżenia nie dostaje.
- Ta sama faktura w `client_contractor_invoices` i `approval_documents`
  (ten sam numer KSeF) liczy się raz.

## Pomiar (kopia produkcji 25.11.2026, faktury kosztowe od 02.2026)

4 860 wpisów kolejki kosztów (prawie wszystkie z `approval_documents`;
`client_contractor_invoices` ma faktury dopiero od 17.11). Ostrzeżenie dostaje
69 wpisów: korekta = cała faktura 6 (6 dostawców, wszystkie w „Kontraktorach”),
druga faktura w miesiącu 63 (23 dostawców), ten sam numer 0.

## Testy

`tests/test_finance_double_pay_rules.py` (bez bazy: różnica korekty, korekta
na minus, waluta, kolejne miesiące, miesiąc z kontraktu, dziennik, numer,
korekta na zero, „Duplikat”, inny dostawca), `tests/test_finance_double_pay_db.py`
(plan, `needs_ack`, paczka po odhaczeniu, „Duplikat” zdejmuje ostrzeżenie).
