# Kontrola formalna faktury sprzedaży — przed wysyłką i dla faktur spoza NEXUSA (25.11.2026)

<!-- indeks: sale_checks, checks, checks_reason, checks_overridden, form-checks, data sprzedaży poza okresem, Contractor ID, cl.contractor_person_id, MD ponad dni robocze, osoba bez kontraktu, eBI24 -->

Po audycie fakturowania IV–X 2026 (25.11.2026): błędy, które klient odsyła do
korekty, a których nie widziała żadna kontrola NEXUSA. Kod:
`services/client_invoicing/sale_checks.py`; szkic i wysyłka w `issue.py`
(`payload` → `checks`, `prepare_send` → `checks_reason`); raport
`GET /api/finance/sales-invoices/form-checks` (`api/client_sales_invoices.py`,
ta sama bramka co lista faktur z KSeF). Bez migracji.

## Cztery kontrole (ostrzeżenia, nie blokady)

| Kontrola | Warunek | Klienci |
|---|---|---|
| Data sprzedaży a okres | szkic: data sprzedaży (`P_6`, bez niej data wystawienia) w innym miesiącu niż okres usługi z „Do faktury”; faktura z KSeF: nazwa pozycji wskazuje inny miesiąc (albo rok) niż data sprzedaży (`invoice_fields.months_in`) | wszyscy |
| Kod osoby | pozycja z „Contractor <osoba>” ma po „ID” (z dwukropkiem albo bez) kod `[A-Z]\d{5,7}`, który w NEXUSIE należy do tej osoby (`client_external_ids`, `client_person_no`; szkic: do kontraktu pozycji). Ostrzega też, gdy jako „Contractor” wpisano osobę z „Contact:” | reguła `cl.contractor_person_id` (Nordea), domyślnie wyłączona |
| MD ponad dni robocze | jednostka MD/dni powyżej dni roboczych miesiąca usługi, godziny powyżej dni roboczych × 8 (`core.scheduling.is_business_day`, święta PL) | wszyscy |
| Osoba bez kontraktu | osoba w polu osoby pozycji albo po „Contractor”/„Konsultant” bez kontraktu u klienta (ze scalonymi duplikatami; skrót i literówka nazwiska jak w `unknown_refs.same_person`); pozycja z kontraktem przechodzi | wszyscy z klientem |

- Kod osoby to reguła klienta w „Reguły klienta” → „Faktura do klienta”, nie
  warunek na nazwę klienta w kodzie (jak reszta `cl.*`,
  `wymagania-klientow-do-faktury-sprzedazy.md`). Włączają ją Finanse u Nordei.
- **Nieznany kod osoby z kontraktem** dostaje inne zdanie („NEXUS nie zna
  kodu … dopisz go w numerach osób”) niż kod, którego nie ma nikt — to brak
  danych w NEXUSIE, a nie błąd faktury.
- Korekt i zaliczek nie sprawdzamy (szkic: tylko `VAT`; raport: tylko
  `original` + `VAT`).

## Szkic z NEXUSA: wysyłka z powodem

- Karta szkicu ma `checks` (sekcja „Kontrola przed wysyłką”). Uwagi nie
  wyłączają „Wyślij do KSeF” (`can_send`), ale wysyłka bez powodu = 409 bez
  numeru i bez zmiany stanu. Przycisk otwiera wtedy okno „Wysłać mimo uwag
  kontroli?” z polem powodu (co najmniej 5 znaków, `CHECKS_REASON_MIN`).
- Powód i lista uwag idą do historii faktury (`checks_overridden`, kto i kiedy).
- Wysyłka seryjna („Wyślij zaznaczone”) nie pyta o powód: szkic z uwagami
  wraca w podsumowaniu jako „do poprawy” z treścią uwag — wysyła się go z karty.
- Kontrola biegnie przy każdym otwarciu karty i jeszcze raz przy wysyłce
  (reguła klienta mogła wejść po utworzeniu szkicu).

## Faktury spoza NEXUSA (eBI24): raport miesiąca

- Finanse → Faktury do klientów → „Faktury z KSeF”: wiersz „Kontrola faktur
  spoza NEXUSA: N faktur z uwagami (z M)” nad listą; rozwinięty — numer,
  klient, data sprzedaży i uwagi. Te same cztery kontrole, reguła kodu osoby
  według miesiąca usługi faktury.
- Liczone przy otwarciu zakładki na fakturach VAT z KSeF za miesiąc usługi,
  bez tych, które wystawił NEXUS (`client_issued_invoices.sales_invoice_id`).
  Faktury z KSeF dochodzą pętlą co godzinę, więc wynik jest zawsze świeży;
  zapisu w bazie ani migracji nie ma.
- Awaria zapytania pokazuje błąd z „Spróbuj ponownie”, nigdy „bez uwag”.
- Osobę bez kontraktu z faktury z KSeF widzi też Delivery Lead (alert
  `invoice_without_order_line`, `unknown_refs.py`); raport Finansów tego nie
  zastępuje.

## Pomiar (kopia produkcji 25.11.2026, faktury VAT z KSeF IV–XI 2026)

4 203 faktury (KSeF sprzedaży na kopii od 02.04.2026), 405 z co najmniej jedną
uwagą, reguła kodu osoby włączona tylko u Nordei:

| Uwaga | Faktury |
|---|---|
| godziny ponad dni robocze × 8 | 168 |
| NEXUS nie zna kodu osoby z kontraktem | 132 |
| osoba bez kontraktu | 61 |
| kod nie jest numerem żadnej osoby | 56 |
| miesiąc w nazwie pozycji ≠ data sprzedaży | 27 |
| MD ponad dni robocze | 19 |
| brak „ID” przy osobie | 4 |
| imię zamiast kodu w polu ID | 2 |
| osoba klienta jako „Contractor” | 1 |

## Testy

`tests/test_client_invoice_sale_checks.py` (bez bazy: dni robocze, data
sprzedaży, miesiąc w nazwie i inny rok, MD i godziny, kod poprawny, bez
dwukropka, imię w polu ID, osoba klienta jako „Contractor”, kod innej osoby,
nieznany kod z kontraktem i bez, kontrakt pozycji, osoba bez kontraktu),
`tests/test_client_invoice_sale_checks_db.py` (karta, 409 bez powodu i z za
krótkim, wysyłka z powodem i historia, czysty szkic bez powodu, raport
`/form-checks` z regułą Nordei, 403 rekrutera), front:
`IssuedInvoices.test.tsx` (okno z powodem), `FormChecksPanel.test.tsx`.
