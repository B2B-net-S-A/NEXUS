# Wystawianie faktur sprzedaży z NEXUSA do KSeF (E4, 13.11.2026)

NEXUS zastępuje eBI24 przy fakturach do klientów (~450 faktur miesięcznie, ~29 klientów, osobna pozycja na
konsultanta). Ten etap: szkice z „Do faktury”, numeracja, XML FA(3), wysyłka do KSeF 2.0, PDF, korekta
i zaliczkowa. Kod: `services/client_invoicing/{issue,fa3_build,numbering,ksef_send,issue_settings,invoice_pdf}.py`,
trasy `api/client_issued_invoices.py` (`/api/finance/issued-invoices`), migracja `0696_sales_invoice_issue`
(SQL w `services/client_invoice_issue_schema.py`, lustro w entrypoincie przez `hr_schema_bundle`).

## Kto i gdzie

- Wyłącznie „Moduł Finanse” (`FinanceModuleUser`) i sekcja Finanse na każdej trasie; moduł
  `app_settings['client_invoicing']` wyłączony = 404 (admin widzi). Delivery Lead i rekruter — 403.
- Finanse → Faktury do klientów: „Wystaw za miesiąc”, „Szkice”, „Wysłane”, „Ustawienia wystawiania”.
  Karta faktury: `/finance/faktury/{id}` (kroki Szkic → Wyślij do KSeF → Przyjęta → UPO → Zapłacona).

## Ustawienia (nie w kodzie)

- `app_settings['client_invoice_issue']`: dane sprzedawcy (nazwa, NIP, adres, miejsce wystawienia), rachunki
  per waluta (PLN, EUR, USD), termin płatności (domyślnie 14 dni), nazwa usługi w pozycji, wzory serii,
  stawka VAT domyślna, nadpisanie stawki i terminu przy kliencie, podstawa zwolnienia (dla „zw.”).
  Bez nazwy, NIP-u i adresu sprzedawcy oraz rachunku w walucie faktury wysyłka czeka z komunikatem.
- NIP sprzedawcy musi być równy `KSEF_CONTEXT_NIP` — inaczej KSeF odrzuciłby fakturę.
- Nabywca z UE (VAT UE w `clients.nip`, np. `FI12345678`) dostaje serię UE i stawkę `np II` (odwrotne
  obciążenie, `P_13_9`, `P_18`=1), chyba że klient ma nadpisanie.

## Numeracja

- Serie: `PL` `{n}/{mm}/{yyyy}`, `UE` `{n}/{mm}/{yyyy}/UE`, `ZAL` `ZAL/{n}/{mm}/{yyyy}`, `KOR` `KOR/{n}/{mm}/{yyyy}`
  (wzory edytowalne; `{n}` bez zer wiodących jak w eBI24). Miesiąc numeru = miesiąc daty wystawienia.
- **Szkic nie ma numeru** (w eBI24 szkic zjadał numer i robił dziury). Numer nadaje się w transakcji tuż przed
  wysyłką do KSeF, pod blokadą wiersza `client_invoice_series` (`SELECT … FOR UPDATE`); unikalny indeks
  `uq_client_issued_invoices_number` to druga zapora. Numer i XML są zapisane (commit) przed rozmową z KSeF.
- „Następny numer” per seria i miesiąc ustawiają Finanse w ustawieniach — przejście z eBI24 w połowie miesiąca
  kontynuuje numerację. Nie da się go ustawić na numer już wydany (409).
- **Odrzucenie przez KSeF (decyzja do potwierdzenia przez Artura):** faktura odrzucona (`rejected`) albo
  niewysłana (`failed`) nie istnieje w obrocie, ale **zatrzymuje swój numer** — po poprawce idzie ponownie
  z tym samym numerem, więc w zwykłym przebiegu dziury nie ma. Data wystawienia może się zmienić tylko w tym
  samym miesiącu. Wycofanie takiej faktury: gdy jej numer jest ostatni w serii, wraca do puli (licznik
  w dół, wiersz znika); gdy nie jest ostatni, faktura zostaje jako `cancelled` z opisem „numer
  niewykorzystany” — to jedyne źródło dziury i jest udokumentowane przy numerze.

## Szkice z „Do faktury”

- Wiersze `billing.billing_rows` za miesiąc usługi; domyślnie jedna faktura na zamówienie, opcjonalnie faktura
  na osobę. Pozycja na osobę: „{usługa} — {konsultant} — {miesiąc} (zamówienie {numer})”, ilość × cena z
  „Do faktury” (MD, h, dni, mies.). Okres usługi w `OkresFa`, numer zamówienia klienta w
  `WarunkiTransakcji/Zamowienia/NrZamowienia`.
- Pozycja bez kwoty (brak zużycia MD, brak stawki) **blokuje szkic** z nazwiskiem osoby. Zamówienie kosztowe
  daje pozycję bez ceny (kwotę ustalają Finanse) — wysyłka czeka, aż ją wpiszą.
- Zamówienie z fakturą za ten miesiąc (szkic albo wysłana, bez wycofanych) nie daje drugiego szkicu (409).
- Szkic edytowalny: daty, okres, termin, nabywca, numer zamówienia, uwagi, waluta, seria (PL/UE), pozycje.
  Usunięcie szkicu nie zostawia śladu w numeracji.

## FA(3) i kwoty

- `fa3_build.py`: `FA (3)` / `1-0E`, kolejność elementów jak w schemacie MF. Wartość pozycji = ilość × cena
  (do grosza), VAT od sumy netto w stawce. Stawki `P_12`: 23, 8, 5, 0 KR, 0 EX, zw, np I, np II.
- Waluta obca: kurs średni NBP z ostatniego dnia roboczego **przed** datą dostawy (koniec okresu usługi) z
  `fx_rates` (`source='NBP'`, najwyżej 7 dni wstecz — inaczej brak kursu i wysyłka czeka). `KursWaluty`
  w pozycji, `P_14_xW` = VAT × kurs w złotych. Korekta bierze kurs faktury korygowanej.
- Test „round-trip”: zbudowany XML czyta `hr/ksef/fa.py` i `fa_sales.py` (te same parsery co faktury z KSeF).
  **XSD FA(3) nie ma w repo** — walidacji XSD nie ma; pierwszą wysyłkę zrób w trybie `test` (MF waliduje schemat).

## Wysyłka do KSeF

- `KSEF_SALES_ISSUE_MODE=off|test|prod` (domyślnie `off`: „Wyślij do KSeF” nieaktywny z wyjaśnieniem; szkice
  działają). Kontekst `KSEF_CONTEXT_NIP`, osobny token `KSEF_SALES_ISSUE_TOKEN` z `InvoiceWrite` — token
  odczytu `KSEF_TOKEN` go nie ma. Ustawiane wyłącznie workflow „Coolify set env”.
- Sesja interaktywna (`ksef_send.py`): AES-256-CBC, klucz szyfrowany RSA-OAEP kluczem MF
  `SymmetricKeyEncryption`, `POST /sessions/online`, faktura, status (ok. 14 s odpytywania), zamknięcie, UPO.
  Wynik: 200 = `accepted` (numer KSeF), 4xx = `rejected` (kod i opis), błąd przed przyjęciem pliku = `failed`,
  w toku albo zerwana odpowiedź = `sent`/`sending` → „Sprawdź status” (bez ponownej wysyłki).
- Przyjęta faktura od razu trafia do `client_sales_invoices` z tym samym numerem KSeF (`sync.store_invoice`
  na naszym XML-u), więc pętla `sales_ksef_fetch` jej nie dubluje, i wiąże się z zamówieniem metodą
  **`issued`** — automat jej nie przepina (jak `manual`), Finanse mogą cofnąć. Korekta idzie za pierwotną
  (`correction`). Zapłata na karcie z istniejących zapłat (`client_sales_invoice_payments`).

## PDF

- `invoice_pdf.py`: wizualizacja z numerem KSeF i kodem QR weryfikacji (KOD I:
  `https://qr.ksef.mf.gov.pl/invoice/{NIP}/{DD-MM-RRRR}/{SHA-256 pliku, Base64URL}`, test: `qr-test`).
  Szkic i faktura bez przyjęcia: znak „SZKIC — dokument nie jest fakturą”, bez kodu.

## Korekta i zaliczkowa

- Korekta tylko do faktury przyjętej w KSeF: szkic z pozycjami pierwotnej jako „stan przed” (`StanPrzed`) i „po”,
  sumy = różnice, przyczyna obowiązkowa, `DaneFaKorygowanej` z numerem KSeF pierwotnej.
- Zaliczkowa minimalnie: klient, waluta, data otrzymania (`P_6`), wiersze w `Zamowienie`, zaliczka na pełną
  wartość zamówienia. Zaliczka częściowa i faktura rozliczeniowa (`ROZ`) — następny etap.

## Poza tym etapem (następne)

- Noty księgowe, wezwania do zapłaty, refaktury benefitów, faktura rozliczeniowa do zaliczek, korekta zaliczkowej,
  szablony cykliczne (604 w eBI24) i wystawianie seryjne jednym kliknięciem, wysyłka faktur mailem do klienta,
  certyfikat zamiast tokenu dla wysyłki, walidacja XSD FA(3) w CI, tryb offline KSeF.
