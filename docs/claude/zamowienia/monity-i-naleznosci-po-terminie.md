# Monity płatności, VAT w PLN faktur walutowych i lista należności dla księgowej (23.11.2026)

Przegląd skrzynek Finansów z 23.11.2026 (wzorzec 10): nikt nie monitował klientów o zapłatę — dwie
faktury w EUR wyszły 1,5 i 2,5 miesiąca po terminie dopiero na pytanie klienta; klient z fakturami
w EUR płacił netto w EUR, a VAT w PLN nie dopłacał; główna księgowa co miesiąc ok. 20. dnia ręcznie
składała listę przeterminowanych należności dla osoby, która fakturuje. Wszystko stoi na „po terminie
tylko z dowodem z wyciągów” (`faktury-do-klientow-z-ksef.md`, sekcja od 0742) — bez dowodu nie ma
monitu ani dni po terminie.

Kod: `backend/app/services/client_invoicing/receivables.py` (VAT, eskalacja, stan na dzień),
`payment_reminders.py` (szkic i wysyłka), `overdue_export.py` (plik), `views.late_chains`;
trasy w `api/client_sales_invoices.py` (`/api/finance/sales-invoices/overdue/reminder`,
`…/overdue/month-close`); front `PaymentReminderDialog.tsx` i widok „Po terminie”
w `FinanceSalesInvoicesTab.tsx`.

## Monit („Przygotuj monit”)

- **Tylko po kliknięciu człowieka.** Finanse → Faktury do klientów → Po terminie: lista klientów
  z fakturami po terminie z dowodem, przy każdym „Przygotuj monit”. Szkic (`GET …/overdue/reminder`)
  nic nie wysyła; „Wyślij monit” pyta o potwierdzenie (`useConfirmV2`) i dopiero wtedy
  `POST …/overdue/reminder`. **Automatu nie ma** — to wysyłka do ludzi spoza firmy, jego włączenie
  (pętla, harmonogram) to decyzja Artura; bez niej nie dopisuj pętli ani przełącznika „wysyłaj sam”.
- **Ścieżka maili NEXUSA**: `services.email.send_email` (skrzynka serwisowa Graph, na stagingu SMTP →
  Mailpit), `reply_to` = adres osoby, która wysyła — odpowiedź klienta trafia do niej. Jeden mail na
  adresata. `send_email` zwraca `False` bez wyjątku: wtedy `sent: 0`, brak wpisu w Historii zdarzeń,
  a okno mówi, że monit nie wyszedł.
- **Faktury w monicie**: tylko z `overdue_days > 0` (dowód z wyciągów), z dniami do ostatniego dnia
  ciągłości (`statements_until`, w treści „Stan wpłat na …”). Faktura „brak danych o zapłacie”,
  kompensata (seria Benefit) i faktura bez klienta NEXUSA nie trafiają do monitu.
- **Eskalacja 7 / 14 / 30 dni** po terminie (`receivables.LEVELS`): przypomnienie, ponowne wezwanie,
  ostateczne wezwanie (z zastrzeżeniem odsetek ustawowych za opóźnienie w transakcjach handlowych).
  Poziom monitu = najwyższy z jego faktur. Przed 7. dniem szkic jest, a wysyłka zablokowana (409).
- **Adresaci tylko z listy szkicu** (serwer liczy ją od nowa przy wysyłce, inny adres = 422).
  Kolejność: kontakty klienta i jego scalonych duplikatów z działem albo stanowiskiem od finansów
  (`finanse`, `księgow`, `rozlicz`, `płatn`, `faktur`, `accounting`, `accounts payable`, `invoice`,
  `billing`…, `payment_reminders._FINANCE_WORDS`), potem adres paczki (`cl.send_to`) i akceptacji
  (`cl.client_acceptance`) z reguł rozliczeń klienta. Osobnych „kontaktów rozliczeniowych” w bazie
  nie ma — klient bez takiego kontaktu dostaje w oknie prośbę o dodanie kontaktu z działem „Finanse”
  w profilu. Wpisywania dowolnego adresu w oknie celowo nie ma (literówka = mail do obcej osoby).
- **Język**: angielski, gdy wszyscy nabywcy faktur mają kraj spoza Polski (`buyer_country`), inaczej
  polski; przełącznik w oknie. Rachunek do wpłaty z ustawień wystawiania
  (`payment_proof.receiving_account`, waluta wpłaty — dla VAT faktury walutowej rachunek PLN),
  podpis: imię osoby wysyłającej i nazwa sprzedawcy z ustawień wystawiania.
- **Ślad**: Historia zdarzeń `client.payment_reminder_sent` (poziom, id faktur, liczba adresatów,
  liczba nieudanych). Z niej „ostatni monit” w oknie i w pliku dla księgowej. Bez nowej tabeli.
- Uprawnienie: „Moduł Finanse” (jak reszta `/api/finance/sales-invoices`, wzorzec
  `tests/data/authz_golden/client_sales_invoices.json`). Delivery Lead monitu nie wysyła.

## VAT w PLN nieopłacony (faktury walutowe)

- `receivables.vat_gap`: faktura (łańcuch z korektami) w walucie obcej, wpłaty w jej walucie pokryły
  co najmniej netto łańcucha, a coś zostało do zapłaty — to tylko VAT. Wpłata mniejsza niż netto to
  zwykła częściowa zapłata (reszta to i netto, i VAT), faktura w PLN nigdy, faktura bez VAT nigdy.
- **Dowód idzie z rachunku PLN**, nie z rachunku waluty: `Proof.verdict(chain, day, currency="PLN",
  amount=VAT w PLN)`. Ciągłe wyciągi EUR nie mówią nic o przelewie VAT w PLN. Wpłata do sprawdzenia
  w PLN z numerem faktury w tytule albo w kwocie VAT w PLN (oraz operacja Księgi bez konta w tej
  kwocie) = „brak danych o zapłacie: wpłata do sprawdzenia”. Bez kursu porównujemy tylko numery.
- **VAT w PLN** = nieopłacony VAT × kurs faktury: kurs z wystawienia w NEXUSIE
  (`client_issued_invoices.fx_rate`), inaczej średni NBP z dnia roboczego przed dniem sprzedaży
  (`posting.rate_day`, jak `ledger/sources.invoice_rate`). Faktura nie trzyma `P_14_*W`, więc kwota
  może się różnić o grosze od VAT w PLN z faktury; brak kursu NBP w bazie = kwota pusta i zdanie
  „kwotę w PLN weź z faktury”.
- Na liście „Po terminie” taki wiersz ma `vat_pln_unpaid` (przy zapłacie „netto zapłacone · VAT do
  zapłaty … zł”), nad listą zdanie z liczbą i sumą (`vat_pln_unpaid` w odpowiedzi `…/overdue`).
- Wpłaty VAT w PLN nie da się przypisać do faktury w EUR (`assign_credit` odmawia innej waluty, a suma
  wpłat łańcucha jest w walucie faktury). Finanse zamykają ją „Opłacono” na kwotę VAT w walucie
  faktury, z powodem „VAT zapłacony w PLN, wyciąg z dnia …”.

## Lista na koniec miesiąca dla księgowej

- `GET …/overdue/month-close?month=RRRR-MM&format=xlsx|csv` (przycisk „Lista na koniec miesiąca”
  w widoku „Po terminie”, miesiąc z przełącznika nad zakładkami). Stan na ostatni dzień miesiąca,
  a w trwającym miesiącu na dziś (`business_today`).
- **Stan na dzień** (`receivables.as_of`): bez faktur wystawionych po tym dniu, bez korekt wystawionych
  po nim i bez wpłat zaksięgowanych po nim. Bierzemy wszystkie faktury bez „Zapłacono” w samej
  fakturze (nie tylko dziś otwarte) — faktura zapłacona w grudniu była należnością na 30.11.
- Wiersze: najpierw po terminie z dowodem (dni, poziom monitu, VAT w PLN, „wpłaty do …”), potem
  faktury z terminem za sobą bez danych o zapłacie — z powodem, **bez dni po terminie** (nie wracamy
  do zaległości z samego terminu). Kolumna „Ostatni monit” z Historii zdarzeń. Komórki zaczynające
  się od `=`, `+`, `-`, `@` neutralizuje `safe_row`.

## Testy

`tests/test_client_invoicing_receivables.py` (bez bazy: VAT przy częściowej zapłacie, korekcie,
korekcie do zera, fakturze w PLN i bez VAT; dowód z rachunku PLN, wpłata do sprawdzenia w PLN,
kompensata; progi 7/14/30; stan na dzień; treść PL/EN, odsetki tylko w ostatecznym; adresaci; plik),
`tests/test_client_invoicing_reminders_api.py` (z bazą: szkic, 403 dla DL i rekrutera, adres spoza
listy 422, wysyłka i wpis w Historii, kanał bez potwierdzenia, klient bez dowodu 409, plik na
listopad i październik), front `__tests__/PaymentReminder.test.tsx`; harness
`/preview/client-invoicing?state=overdue`.
